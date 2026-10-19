"""微信普惠Bot：mock iLink（QR / getupdates / sendmessage / 文件），复用飞书意图路由，无需真实微信。"""
import io
import json
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app import admin_auth, db
from app import users as U
from app.wechat import config as C
from app.wechat import delivery as D
from app.wechat import identity as I
from app.wechat import ilink as IL
from app.wechat import poller
from app.wechat import service as S

INT = {"X-User": quote("wx_zhang"), "X-Role": "internal"}
INST = {"X-User": quote("wx_inst"), "X-Role": "institution"}


class FakeTransport(IL.httpx.BaseTransport):
    """极简 httpx transport：按路径返回预设响应。"""

    def __init__(self):
        self.calls = []
        self.qr_status_seq = ["wait", "scaned", "confirmed"]
        self.qr_i = 0
        self.updates = []
        self.sent = []
        self.stale = False
        self.upload_ok = True
        self.reply_fail_after = 999
        self._reply_n = 0

    def handle_request(self, request):
        url = str(request.url)
        self.calls.append((request.method, url, request.content))
        path = request.url.path
        if path.endswith("get_bot_qrcode"):
            body = {"qrcode": "QRCODE1", "qrcode_img_content": "https://liteapp.weixin.qq.com/q/test"}
            return self._json(body)
        if "get_qrcode_status" in path:
            st = self.qr_status_seq[min(self.qr_i, len(self.qr_status_seq) - 1)]
            self.qr_i += 1
            body = {"status": st}
            if st == "confirmed":
                body.update(bot_token="tok-abc", ilink_bot_id="bot1@im.bot",
                            ilink_user_id="o9cqTESTUSER@im.wechat", baseurl="https://ilinkai.weixin.qq.com")
            if st == "need_verifycode":
                body = {"status": "need_verifycode"}
            return self._json(body)
        if path.endswith("getupdates"):
            if self.stale:
                return self._json({"errcode": -14, "errmsg": "session timeout"})
            msgs, self.updates = self.updates, []
            return self._json({"ret": 0, "msgs": msgs, "get_updates_buf": "CUR2"})
        if path.endswith("sendmessage"):
            self._reply_n += 1
            if self._reply_n > self.reply_fail_after:
                return self._json({"ret": -2, "errmsg": "prepare failed"})
            if self.stale:
                return self._json({"errcode": -14, "errmsg": "session timeout"})
            payload = json.loads(request.content.decode())
            self.sent.append(payload)
            return self._json({"ret": 0, "message_id": f"om_{len(self.sent)}"})
        if path.endswith("getuploadurl"):
            if not self.upload_ok:
                return self._json({"ret": 1, "errmsg": "denied"})
            return self._json({"ret": 0, "upload_full_url": "https://cdn.test/upload", "upload_param": "p"})
        if "cdn.test/upload" in url or path.endswith("/upload"):
            return IL.httpx.Response(200, headers={"x-encrypted-param": "dlparam"}, content=b"ok")
        if path.endswith("notifystart") or path.endswith("notifystop"):
            return self._json({"ret": 0})
        return self._json({"ret": 0})

    @staticmethod
    def _json(body, status=200):
        return IL.httpx.Response(status, headers={"content-type": "application/json"},
                                 content=json.dumps(body).encode())


pytestmark = pytest.mark.usefixtures("isolated_db")


@pytest.fixture(scope="module")
def adm():
    from app.main import app
    c = TestClient(app)
    admin_auth.reset_password("admin", "Wx-Admin-2026x")
    assert c.post("/api/admin/login", json={"username": "admin", "password": "Wx-Admin-2026x"}).status_code == 200
    assert c.post("/api/admin/password", json={"old": "Wx-Admin-2026x", "new": "Wx-Admin-2026y"}).status_code == 200
    return c


@pytest.fixture(scope="module")
def world(adm):
    from app.main import app
    c = TestClient(app)
    assert adm.put("/api/admin/wechat/config", json={"enabled": True, "bot_name": "普惠Bot", "max_replies": 10}).status_code == 200
    assert c.post("/api/m5/snapshots/sample", json={"stat_date": "2026-09-19"}, headers=INT).status_code == 200
    admin = {"name": "admin", "role": "admin"}
    U.create({"username": "wx_zhang", "display_name": "张三", "role": "internal"}, admin)
    # institution needs an org that exists in snapshot
    from app.m5 import service as MS
    s = MS.list_snapshots()[0]
    d = MS.dashboard(s["id"], {"name": "t", "role": "internal", "org": None})
    org = d["rows"][0]["name"]
    if not db.q1("SELECT 1 x FROM institutions WHERE full_name=?", (org,)):
        db.execute("INSERT INTO institutions(full_name,short_name,created_at,updated_at) VALUES(?,?,?,?)", (org, org[:4], db.now(), db.now()))
    U.create({"username": "wx_inst", "display_name": "机构用户", "role": "institution", "org": org}, admin)
    db.execute("UPDATE users SET must_change=0")
    return {"c": c, "org": org, "snap": s}


@pytest.fixture
def fake(monkeypatch):
    ft = FakeTransport()
    def make_client(token=None, base_url=None, **kw):
        return IL.IlinkClient(token=token, base_url=base_url or IL.DEFAULT_BASE_URL, transport=ft)
    monkeypatch.setattr(I, "IlinkClient", make_client)
    monkeypatch.setattr(S, "IlinkClient", make_client)
    # identity starts QR with IlinkClient()
    monkeypatch.setattr("app.wechat.identity.IlinkClient", make_client)
    monkeypatch.setattr("app.wechat.poller.IlinkClient", make_client)
    # speed up QR poller: run status transitions inline
    return ft


def _bind_user(c, headers, fake, username_header_user="wx_zhang"):
    """通过 API 走完 QR → confirmed，写入 bindings。"""
    fake.qr_i = 0
    fake.qr_status_seq = ["confirmed"]  # skip wait/scaned for speed
    r = c.post("/api/wechat/qr", headers=headers)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    # drive poller synchronously
    I._poll_qr(sid)
    s = c.get(f"/api/wechat/qr/{sid}", headers=headers).json()
    assert s["status"] == "confirmed", s
    b = db.q1("SELECT * FROM wechat_bindings WHERE username=?", (username_header_user,))
    assert b and b["status"] == "正常"
    return b


def test_config_and_help_name(adm, world):
    r = adm.get("/api/admin/wechat/config").json()
    assert r["bot_name"] == "普惠Bot" and r["enabled"] is True
    assert "bot_token" not in json.dumps(r)
    from app.feishu.service import help_text
    h = help_text({"name": "张三", "role": "internal", "org": None}, bot_name="普惠Bot", channel="微信")
    assert "普惠Bot" in h and ("补发" in h or "继续" in h)


def test_qr_bind_and_secret_encrypted(world, fake):
    c = world["c"]
    b = _bind_user(c, INT, fake)
    assert "tok-abc" not in b["bot_token_enc"]
    assert I.token_of(b) == "tok-abc"
    assert "tok-abc" not in c.get("/api/wechat/me", headers=INT).text
    assert c.get("/api/wechat/me", headers=INT).json()["bound"] is True
    # token never in events/admin list
    assert "tok-abc" not in adm_json(world)


def adm_json(world):
    # use admin session via raw db listing
    return json.dumps(I.bindings())


def test_inbound_quota_and_permissions(world, fake):
    c = world["c"]
    b = db.q1("SELECT * FROM wechat_bindings WHERE username='wx_zhang'") or _bind_user(c, INT, fake)
    cli = IL.IlinkClient(token="tok-abc", transport=fake)
    msg = {"message_id": "m1", "message_type": 1, "from_user_id": b["ilink_user_id"],
           "context_token": "CTX1", "item_list": [{"type": 1, "text_item": {"text": "额度"}}]}
    S.on_inbound(b, msg, cli, sync=True)
    assert fake.sent, "should have replied"
    text = fake.sent[0]["msg"]["item_list"][0]["text_item"]["text"]
    assert "数据来源：M5" in text and "普惠" not in text[:5] or "万元" in text or "使用" in text
    assert "数据来源" in text
    # dedup
    n = len(fake.sent)
    S.on_inbound(b, msg, cli, sync=True)
    assert len(fake.sent) == n
    # institution bind + isolation
    fake.qr_i = 0
    fake.qr_status_seq = ["confirmed"]
    # need different ilink_user_id for second bind - patch transport
    _orig = fake.handle_request
    def handle2(request):
        if "get_qrcode_status" in str(request.url):
            return fake._json({"status": "confirmed", "bot_token": "tok-inst", "ilink_bot_id": "bot2@im.bot",
                               "ilink_user_id": "o9cqINST@im.wechat", "baseurl": "https://ilinkai.weixin.qq.com"})
        return _orig(request)
    fake.handle_request = handle2
    r = c.post("/api/wechat/qr", headers=INST)
    assert r.status_code == 200
    I._poll_qr(r.json()["id"])
    bi = db.q1("SELECT * FROM wechat_bindings WHERE username='wx_inst'")
    assert bi
    fake.sent.clear()
    msg2 = {"message_id": "m2", "message_type": 1, "from_user_id": bi["ilink_user_id"],
            "context_token": "CTX2", "item_list": [{"type": 1, "text_item": {"text": "报告"}}]}
    S.on_inbound(bi, msg2, IL.IlinkClient(token="tok-inst", transport=fake), sync=True)
    assert "仅对普惠部内部" in fake.sent[0]["msg"]["item_list"][0]["text_item"]["text"]
    fake.handle_request = _orig


def test_max_10_replies_and_pending(world, fake):
    b = db.q1("SELECT * FROM wechat_bindings WHERE username='wx_zhang'")
    fake.sent.clear()
    fake._reply_n = 0
    fake.reply_fail_after = 10
    cli = IL.IlinkClient(token="tok-abc", transport=fake)
    sender = D.Sender(cli, b, "CTXQ")
    sender.max = 10
    # craft a long reply that would need many chunks + a file
    long = "\n".join(f"第{i}行内容：" + ("字" * 80) for i in range(40))
    files = [("报告.docx", b"PK\x00\x00fake-docx-content-here-enough", "docx")]
    stats = sender.deliver(long, files)
    assert stats["sent"] <= 10
    # either some pending or truncated
    pend = db.q("SELECT * FROM wechat_pending WHERE binding_id=?", (b["id"],))
    assert stats["sent"] + len(pend) >= 1
    # flush on next inbound
    fake._reply_n = 0
    fake.reply_fail_after = 999
    fake.sent.clear()
    msg = {"message_id": "m_cont", "message_type": 1, "from_user_id": b["ilink_user_id"],
           "context_token": "CTX3", "item_list": [{"type": 1, "text_item": {"text": "继续"}}]}
    S.on_inbound(b, msg, cli, sync=True)
    assert fake.sent  # flushed or "没有待补发"


def test_file_send_docx(world, fake):
    b = db.q1("SELECT * FROM wechat_bindings WHERE username='wx_zhang'")
    # finalized report
    tid = db.execute("INSERT INTO m3_tasks(title,requirements,status,stage,final,final_check,confirmations,tokens,agents,created_by,created_at,updated_at,finalized_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("微信通道测试报告", "{}", "已定稿", "已定稿", "一、总体\n业务稳健。", db.jdump({"red": 0, "items": [], "register": []}), "{}", "{}", "{}", "张三", db.now(), db.now(), db.now()))
    fake.sent.clear()
    fake._reply_n = 0
    cli = IL.IlinkClient(token="tok-abc", transport=fake)
    msg = {"message_id": "m_file", "message_type": 1, "from_user_id": b["ilink_user_id"],
           "context_token": "CTXF", "item_list": [{"type": 1, "text_item": {"text": f"报告文件 #{tid}"}}]}
    S.on_inbound(b, msg, cli, sync=True)
    kinds = [x["msg"]["item_list"][0]["type"] for x in fake.sent]
    assert 4 in kinds  # FILE item
    assert any(x["msg"]["item_list"][0].get("type") == 1 for x in fake.sent)


def test_stale_marks_rebind(world, fake):
    b = db.q1("SELECT * FROM wechat_bindings WHERE username='wx_zhang'")
    fake.stale = True
    cli = IL.IlinkClient(token="tok-abc", transport=fake)
    sender = D.Sender(cli, b, "CTXS")
    sender.send_text("hello")
    assert sender.expired
    # poller path
    I.mark_rebind(b["id"], "session timeout (-14)")
    b2 = db.q1("SELECT status FROM wechat_bindings WHERE id=?", (b["id"],))
    assert b2["status"] == "需重新扫码"
    fake.stale = False
    # restore for other tests
    db.execute("UPDATE wechat_bindings SET status='正常', last_error=NULL WHERE id=?", (b["id"],))


def test_unbind(world, fake):
    c = world["c"]
    assert c.delete("/api/wechat/bind", headers=INT).json()["removed"] >= 1
    assert c.get("/api/wechat/me", headers=INT).json()["bound"] is False
    # rebind for cleanliness
    _bind_user(c, INT, fake)


def test_admin_force_unbind_and_events(adm, world, fake):
    b = db.q1("SELECT * FROM wechat_bindings WHERE username='wx_zhang'")
    assert b
    ev = adm.get("/api/admin/wechat/events").json()
    assert isinstance(ev, list)
    assert adm.delete(f"/api/admin/wechat/bindings/{b['id']}").json()["removed"] == 1
    _bind_user(world["c"], INT, fake)


def test_split_and_merge_helpers():
    parts = D.split_text("a" * 100, 30)
    assert all(len(p) <= 30 for p in parts) and "".join(parts) == "a" * 100
    merged = D.merge_into_budget(["短1", "短2", "短3", "短4"], files_n=2, max_replies=5, chunk=100)
    assert len(merged) <= 3  # 5-2


def test_poller_status_and_single_lock(world, fake, monkeypatch):
    monkeypatch.delenv("PH_DISABLE_SCHEDULER", raising=False)
    # don't actually start long-running polls in test; just status + lock
    st = poller.status()
    assert "polling" in st and st["bot_name"] == "普惠Bot"
    path = poller._lock_path(999001)
    fd1 = poller._try_lock(path)
    assert fd1 is not None
    fd2 = poller._try_lock(path)
    assert fd2 is None  # second lock fails
    poller._unlock(fd1)
