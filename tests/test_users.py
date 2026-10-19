"""业务账号登录、强制改密、角色权限（session 模式）。"""
import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def sess(monkeypatch):
    monkeypatch.setenv("PH_AUTH_MODE", "session")
    from app.main import app
    from app import admin_auth, users
    pw = admin_auth.reset_password("admin", "Init-Pass-001x")
    adm = TestClient(app)
    adm.post("/api/admin/login", json={"username": "admin", "password": pw})
    adm.post("/api/admin/password", json={"old": pw, "new": "Admin-Pass-2026x"})
    return app, adm, users


def _new_user(adm, un, role, org=None):
    r = adm.post("/api/admin/users", json={"username": un, "display_name": un, "role": role, "org": org})
    assert r.status_code == 200, r.text
    return r.json()["initial_password"]


def _login(app, un, pw, new="Strong-Pass-99"):
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": un, "password": pw}).status_code == 200
    assert c.get("/api/m5/snapshots").status_code == 403  # 未改初始密码前不可用
    assert c.post("/api/auth/password", json={"old": pw, "new": "short"}).status_code == 400
    assert c.post("/api/auth/password", json={"old": pw, "new": new}).status_code == 200
    return c


def test_unauthenticated_and_header_ignored(sess):
    app, adm, users = sess
    c = TestClient(app)
    assert c.get("/api/m4/schemes").status_code == 403
    assert c.get("/api/m4/schemes", headers={"X-Role": "admin"}).status_code == 403  # 请求头不能伪造身份
    assert c.get("/api/auth/me").json() == {"logged_in": False}
    assert adm.get("/api/m4/schemes").status_code == 200  # 管理员会话 = admin 角色
    assert adm.get("/api/auth/me").json()["kind"] == "admin"


def test_internal_user_flow_and_audit(sess):
    app, adm, users = sess
    pw = _new_user(adm, "zhang_san", "internal")
    assert adm.post("/api/admin/users", json={"username": "zhang_san", "role": "internal"}).status_code == 409
    assert adm.post("/api/admin/users", json={"username": "x", "role": "internal"}).status_code == 400
    assert adm.post("/api/admin/users", json={"username": "bad_admin", "role": "admin"}).status_code == 400
    c = _login(app, "zhang_san", pw)
    me = c.get("/api/auth/me").json()
    assert me["user"]["role"] == "internal" and not me["user"]["must_change"]
    assert c.get("/api/m4/schemes").status_code == 200
    assert c.get("/api/admin/users").status_code == 403  # 业务账号不能进系统管理
    from app import db
    assert db.q1("SELECT * FROM audit_log WHERE username='zhang_san' AND action='修改密码'")
    # 停用 → 会话立即失效
    adm.put("/api/admin/users/zhang_san", json={"enabled": 0})
    assert c.get("/api/m4/schemes").status_code == 403
    assert TestClient(app).post("/api/auth/login", json={"username": "zhang_san", "password": "Strong-Pass-99"}).status_code == 403
    adm.put("/api/admin/users/zhang_san", json={"enabled": 1})
    # 重置 → 旧密码失效，须再次改密
    npw = adm.post("/api/admin/users/zhang_san/reset").json()["initial_password"]
    assert TestClient(app).post("/api/auth/login", json={"username": "zhang_san", "password": "Strong-Pass-99"}).status_code == 403
    _login(app, "zhang_san", npw, new="Another-Pass-77")
    c.post("/api/auth/logout")


def test_institution_scope(sess):
    app, adm, users = sess
    from app import db
    if not db.q1("SELECT 1 x FROM institutions WHERE COALESCE(all_access,0)=0"):
        assert adm.post("/api/m4/import-sample").status_code == 200
    adm.post("/api/m5/limit-sets/import-sample")
    adm.post("/api/m5/snapshots/sample", json={})
    insts = [x["full_name"] for x in db.q("SELECT full_name FROM institutions WHERE COALESCE(all_access,0)=0 ORDER BY id")]
    assert adm.post("/api/admin/users", json={"username": "jg_bad", "role": "institution"}).status_code == 400
    pw = _new_user(adm, "jg_user", "institution", insts[0])
    c = _login(app, "jg_user", pw)
    for path in ("/api/m4/schemes", "/api/m3/tasks", "/api/ppt/jobs", "/api/m1/items", "/api/audit"):
        assert c.get(path).status_code == 403, path
    assert [x["full_name"] for x in c.get("/api/institutions").json()] == [insts[0]]
    sid = c.get("/api/m5/snapshots/latest/id").json()
    sid = sid.get("id") if isinstance(sid, dict) else sid
    if sid:
        d = c.get(f"/api/m5/snapshots/{sid}/dashboard").json()
        names = {r.get("name") for r in d.get("rows", [])}
        assert names <= {insts[0], None}
        assert d["summary"] is None and all(v is None for v in d["ports"].values())
    # M2：只能看到已发布简报
    now = db.now()
    db.execute("INSERT INTO m2_briefs(brief_date,version,status,markdown,generated_at) VALUES('2026-01-02',1,'草稿','# d',?)", (now,))
    draft = db.q1("SELECT id FROM m2_briefs WHERE brief_date='2026-01-02'")["id"]
    db.execute("INSERT INTO m2_briefs(brief_date,version,status,markdown,generated_at) VALUES('2026-01-03',1,'已发布','# p',?)", (now,))
    assert all(b["status"] == "已发布" for b in c.get("/api/m2/briefs").json())
    assert c.get(f"/api/m2/briefs/{draft}").status_code == 404
    assert adm.get(f"/api/m2/briefs/{draft}").status_code == 200


ZDB = "示例省级融资再担保有限责任公司"


def test_zaidanbao_all_access(sess):
    """再担保公司账号：全机构可见 + 全部业务功能，但系统管理一律拒绝；且不计入合作机构测算。"""
    app, adm, users = sess
    from app import db
    assert db.q1("SELECT all_access FROM institutions WHERE full_name=?", (ZDB,))["all_access"] == 1
    if not db.q1("SELECT 1 x FROM institutions WHERE COALESCE(all_access,0)=0"):
        assert adm.post("/api/m4/import-sample").status_code == 200
    adm.post("/api/m5/limit-sets/import-sample")
    adm.post("/api/m5/snapshots/sample", json={})
    others = [x["full_name"] for x in db.q("SELECT full_name FROM institutions WHERE COALESCE(all_access,0)=0")]
    pw = _new_user(adm, "zdbtest", "institution", ZDB)
    c = _login(app, "zdbtest", pw)
    me = c.get("/api/me").json()
    assert me["role"] == "internal" and me["org"] == ZDB and me["all_access"] is True and "全机构" in me["role_name"]
    names = {x["full_name"] for x in c.get("/api/institutions").json()}
    assert set(others) <= names and len(others) > 1
    for path in ("/api/m4/schemes", "/api/m3/tasks", "/api/ppt/jobs", "/api/m1/items", "/api/audit", "/api/m2/briefs"):
        assert c.get(path).status_code == 200, path
    sid = c.get("/api/m5/snapshots/latest/id").json()
    sid = sid.get("id") if isinstance(sid, dict) else sid
    if sid:
        d = c.get(f"/api/m5/snapshots/{sid}/dashboard").json()
        rows = {r.get("name") for r in d.get("rows", [])}
        assert len(rows) > 1 and d["summary"] is not None and ZDB not in rows
        assert adm.get(f"/api/m5/snapshots/{sid}/dashboard").json()["rows"] == d["rows"]
    # M4 测算行不含再担保本身
    sc = c.get("/api/m4/schemes").json()
    if sc:
        s0 = sc[0] if isinstance(sc, list) else (sc.get("schemes") or [{}])[0]
        if s0.get("id"):
            res = c.get(f"/api/m4/schemes/{s0['id']}").json()
            rows = (res.get("result") or {}).get("rows") or res.get("rows") or []
            assert rows and ZDB not in {r.get("name") for r in rows}
    # 首页机构数不计入再担保
    assert c.get("/api/home").json()["institutions"] == len(others)
    # 系统管理：全部拒绝
    for m, path in (("get", "/api/admin/users"), ("post", "/api/admin/users"), ("put", "/api/admin/users/zdbtest"),
                    ("get", "/api/admin/llm/providers"), ("get", "/api/admin/search/providers"),
                    ("get", "/api/admin/mail/config"), ("put", "/api/admin/mail/config"), ("get", "/api/admin/feishu/config"),
                    ("get", "/api/admin/wechat/config"), ("put", "/api/admin/m3/agents"), ("get", "/api/admin/m3/prompts"),
                    ("post", "/api/admin/ppt/prompts"), ("put", "/api/admin/m1/config"), ("get", "/api/admin/ops"),
                    ("get", "/api/admin/backups"), ("get", "/api/admin/demo")):
        r = getattr(c, m)(path, **({"json": {}} if m != "get" else {}))
        assert r.status_code in (401, 403), (path, r.status_code)
    assert c.get("/api/admin/me").json()["logged_in"] is False
    # 机器人身份同样生效
    u = db.q1("SELECT * FROM users WHERE username='zdbtest'")
    assert users.as_user(u)["role"] == "internal"
    # 普通合作机构仍隔离
    assert users.as_user({**u, "org": others[0]})["role"] == "institution"


def test_lockout(sess):
    app, adm, users = sess
    _new_user(adm, "lock_me", "internal")
    c = TestClient(app)
    codes = [c.post("/api/auth/login", json={"username": "lock_me", "password": "wrong"}).status_code for _ in range(6)]
    assert codes[-1] == 429


def test_demo_users_file(sess):
    app, adm, users = sess
    from app import db
    db.execute("DELETE FROM users")
    made = users.ensure_demo_users()
    assert made == ["puhui_demo", "jigou_demo"]
    txt = users.INIT_FILE.read_text(encoding="utf-8")
    assert re.search(r"puhui_demo（普惠部（内部））：\S+", txt)
    import os, stat
    assert stat.S_IMODE(os.stat(users.INIT_FILE).st_mode) == 0o600
