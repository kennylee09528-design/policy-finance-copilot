"""微信绑定：网页端为已登录用户生成 QR；扫码成功后把 ilink_user_id ↔ 工作台账号写入 wechat_bindings（bot_token 加密）。"""
from __future__ import annotations

import base64
import io
import threading
from datetime import datetime, timedelta

import qrcode
from fastapi import HTTPException

from .. import db
from .. import users as U
from ..llm.crypto import decrypt, encrypt
from . import config as C
from .ilink import DEFAULT_BASE_URL, IlinkClient

_qr_lock = threading.RLock()
_pollers: dict[int, threading.Thread] = {}  # sid -> background QR status poller thread


def _png_b64(url: str) -> str:
    buf = io.BytesIO()
    qrcode.make(url, box_size=8, border=2).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def bindings(status: str = ""):
    sql, a = "SELECT id, username, ilink_user_id, ilink_bot_id, baseurl, status, last_error, bound_at, last_seen, updated_at FROM wechat_bindings", []
    if status:
        sql += " WHERE status=?"
        a.append(status)
    rows = db.q(sql + " ORDER BY bound_at DESC", a)
    for r in rows:
        u = db.q1("SELECT display_name, role, org, enabled FROM users WHERE username=?", (r["username"],))
        r["display_name"] = (u or {}).get("display_name")
        r["role"] = (u or {}).get("role")
        r["org"] = (u or {}).get("org")
        r["user_enabled"] = bool((u or {}).get("enabled", 0))
        r["ilink_user_id_masked"] = _mask(r["ilink_user_id"], 10)
        r["ilink_bot_id_masked"] = _mask(r.get("ilink_bot_id") or "", 8)
    return rows


def _mask(s, keep=8):
    s = s or ""
    return (s[:keep] + "…" + s[-4:]) if len(s) > keep + 4 else ("***" if s else "")


def mine(username):
    b = db.q1("SELECT id, ilink_user_id, status, bound_at, last_seen, last_error FROM wechat_bindings WHERE username=?", (username,))
    if not b:
        return None
    b["ilink_user_id_masked"] = _mask(b["ilink_user_id"], 10)
    return b


def user_of(ilink_user_id):
    b = db.q1("SELECT * FROM wechat_bindings WHERE ilink_user_id=?", (ilink_user_id,))
    if not b:
        return None, None, None
    if b["status"] == "需重新扫码":
        return None, "您的微信绑定已失效（会话超时），请回到工作台网页重新扫码绑定。", b
    if b["status"] != "正常":
        return None, "微信绑定已停用，请联系管理员。", b
    u = db.q1("SELECT * FROM users WHERE username=?", (b["username"],))
    if not u or not u["enabled"]:
        return None, "您绑定的工作台账号已停用，请联系管理员。", b
    if u["must_change"]:
        return None, "您的工作台账号需先在网页端修改初始密码后才能使用。", b
    db.execute("UPDATE wechat_bindings SET last_seen=? WHERE id=?", (db.now(), b["id"]))
    return U.as_user(u), None, b


def token_of(binding) -> str:
    return decrypt(binding["bot_token_enc"])


def start_qr(username: str, purpose: str = "user", by=None):
    """为工作台账号开启一次扫码绑定。同一账号同时只保留一个进行中的会话。"""
    cfg = C.get()
    if not cfg["enabled"] and purpose != "admin_test":
        raise HTTPException(400, "管理员尚未启用微信普惠Bot（系统管理 → 微信普惠Bot）")
    if purpose == "user":
        u = db.q1("SELECT * FROM users WHERE username=? AND enabled=1", (username,))
        if not u:
            raise HTTPException(400, "仅业务账号可绑定微信")
    with _qr_lock:
        # 作废旧会话
        for old in db.q("SELECT id FROM wechat_qr_sessions WHERE username=? AND status IN ('wait','scaned','need_verifycode')", (username,)):
            db.execute("UPDATE wechat_qr_sessions SET status='expired', message='被新会话取代', updated_at=? WHERE id=?", (db.now(), old["id"]))
        # 取最近本地 token 列表，便于服务端识别已绑定
        local = []
        for b in db.q("SELECT bot_token_enc FROM wechat_bindings ORDER BY id DESC LIMIT 10"):
            try:
                local.append(decrypt(b["bot_token_enc"]))
            except Exception:  # noqa: BLE001
                pass
        cli = IlinkClient()
        try:
            r = cli.get_bot_qrcode(local)
        finally:
            cli.close()
        if not r.ok or not r.body or not r.body.get("qrcode") or not r.body.get("qrcode_img_content"):
            raise HTTPException(502, f"向微信申请二维码失败：ret={r.ret} errmsg={r.errmsg} err={r.error}")
        qrcode_id, qr_url = r.body["qrcode"], r.body["qrcode_img_content"]
        exp = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        sid = db.execute(
            "INSERT INTO wechat_qr_sessions(username,purpose,qrcode,qr_url,status,message,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (username, purpose, qrcode_id, qr_url, "wait", "请用微信扫描二维码", db.now(), db.now(), exp))
        if by:
            db.audit(by, "微信", "发起微信扫码绑定", username, {"session": sid, "purpose": purpose})
        _start_qr_poller(sid)
        return session_public(sid)


def session_public(sid: int):
    s = db.q1("SELECT * FROM wechat_qr_sessions WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "扫码会话不存在")
    out = {k: s[k] for k in ("id", "username", "purpose", "status", "message", "verify_needed", "created_at", "updated_at", "expires_at", "result_user_id")}
    out["qr_png"] = _png_b64(s["qr_url"]) if s.get("qr_url") and s["status"] in ("wait", "scaned", "need_verifycode") else None
    out["qr_link"] = s.get("qr_url") if out["qr_png"] else None
    if s.get("result_user_id"):
        out["result_user_id_masked"] = _mask(s["result_user_id"], 10)
    return out


def submit_verify_code(sid: int, code: str, username: str):
    s = db.q1("SELECT * FROM wechat_qr_sessions WHERE id=?", (sid,))
    if not s or s["username"] != username:
        raise HTTPException(404, "扫码会话不存在")
    if s["status"] != "need_verifycode":
        raise HTTPException(400, "当前不需要配对码")
    code = (code or "").strip()
    if not code.isdigit() or not (4 <= len(code) <= 8):
        raise HTTPException(400, "配对码应为手机上显示的 4~8 位数字")
    db.execute("UPDATE wechat_qr_sessions SET message=?, updated_at=? WHERE id=?", (f"verify:{code}", db.now(), sid))
    return session_public(sid)


def _start_qr_poller(sid: int):
    if sid in _pollers and _pollers[sid].is_alive():
        return

    def run():
        try:
            _poll_qr(sid)
        finally:
            _pollers.pop(sid, None)

    t = threading.Thread(target=run, daemon=True, name=f"wechat-qr-{sid}")
    _pollers[sid] = t
    t.start()


def _poll_qr(sid: int):
    cli = IlinkClient()
    poll_base = DEFAULT_BASE_URL
    pending_code = None
    refreshes = 0
    try:
        while True:
            s = db.q1("SELECT * FROM wechat_qr_sessions WHERE id=?", (sid,))
            if not s or s["status"] in ("confirmed", "failed", "expired", "binded_elsewhere"):
                return
            if s["expires_at"] < db.now() and s["status"] == "wait" and refreshes >= 3:
                db.execute("UPDATE wechat_qr_sessions SET status='expired', message='二维码多次过期', updated_at=? WHERE id=?", (db.now(), sid))
                return
            # 用户提交的配对码
            msg = s.get("message") or ""
            if msg.startswith("verify:") and s["status"] == "need_verifycode":
                pending_code = msg.split(":", 1)[1]
                db.execute("UPDATE wechat_qr_sessions SET message=? WHERE id=?", ("正在校验配对码…", sid))
            r = cli.get_qrcode_status(s["qrcode"], pending_code, base_url=poll_base)
            body = r.body or {}
            st = body.get("status", "wait")
            if st == "wait":
                continue
            if st == "scaned":
                pending_code = None
                db.execute("UPDATE wechat_qr_sessions SET status='scaned', message='已扫码，请在手机上确认', verify_needed=0, updated_at=? WHERE id=?", (db.now(), sid))
                continue
            if st == "need_verifycode":
                pending_code = None
                db.execute("UPDATE wechat_qr_sessions SET status='need_verifycode', verify_needed=1, message='请输入手机上显示的配对码', updated_at=? WHERE id=?", (db.now(), sid))
                continue
            if st == "verify_code_blocked":
                db.execute("UPDATE wechat_qr_sessions SET status='failed', message='配对码错误次数过多，请重新发起绑定', updated_at=? WHERE id=?", (db.now(), sid))
                return
            if st == "expired":
                refreshes += 1
                if refreshes > 3:
                    db.execute("UPDATE wechat_qr_sessions SET status='expired', message='二维码已过期，请重新发起', updated_at=? WHERE id=?", (db.now(), sid))
                    return
                # 自动刷新 QR
                local = []
                rr = cli.get_bot_qrcode(local)
                if not rr.ok or not rr.body:
                    db.execute("UPDATE wechat_qr_sessions SET status='failed', message='刷新二维码失败', updated_at=? WHERE id=?", (db.now(), sid))
                    return
                exp = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
                db.execute("UPDATE wechat_qr_sessions SET qrcode=?, qr_url=?, status='wait', message='二维码已刷新，请重新扫描', verify_needed=0, updated_at=?, expires_at=? WHERE id=?",
                           (rr.body["qrcode"], rr.body["qrcode_img_content"], db.now(), exp, sid))
                poll_base = DEFAULT_BASE_URL
                continue
            if st == "scaned_but_redirect":
                host = body.get("redirect_host")
                if host:
                    poll_base = f"https://{host}"
                continue
            if st == "binded_redirect":
                db.execute("UPDATE wechat_qr_sessions SET status='binded_elsewhere', message='该微信已绑定到其它设备/实例，请先在原处断开或换微信号', updated_at=? WHERE id=?", (db.now(), sid))
                return
            if st == "confirmed":
                if not body.get("bot_token") or not body.get("ilink_bot_id"):
                    db.execute("UPDATE wechat_qr_sessions SET status='failed', message='确认成功但缺少凭证', updated_at=? WHERE id=?", (db.now(), sid))
                    return
                _finalize_bind(s["username"], body, sid)
                return
    finally:
        cli.close()


def _finalize_bind(username: str, body: dict, sid: int):
    uid = body.get("ilink_user_id") or ""
    if not uid:
        db.execute("UPDATE wechat_qr_sessions SET status='failed', message='确认成功但缺少 ilink_user_id', updated_at=? WHERE id=?", (db.now(), sid))
        return
    # 1 账号 1 微信；1 微信 1 账号
    old = db.q("SELECT id FROM wechat_bindings WHERE username=? OR ilink_user_id=?", (username, uid))
    for o in old:
        db.execute("DELETE FROM wechat_bindings WHERE id=?", (o["id"],))
    bid = db.execute(
        "INSERT INTO wechat_bindings(username,ilink_user_id,ilink_bot_id,bot_token_enc,baseurl,cursor,status,bound_at,last_seen,updated_at) VALUES(?,?,?,?,?,'','正常',?,?,?)",
        (username, uid, body.get("ilink_bot_id"), encrypt(body["bot_token"]), body.get("baseurl") or DEFAULT_BASE_URL,
         db.now(), db.now(), db.now()))
    db.execute("UPDATE wechat_qr_sessions SET status='confirmed', message='绑定成功', result_user_id=?, result_bot_id=?, updated_at=? WHERE id=?",
               (uid, body.get("ilink_bot_id"), db.now(), sid))
    who = db.q1("SELECT * FROM users WHERE username=?", (username,))
    audit_user = U.as_user(who) if who else {"name": username, "username": username, "role": "?"}
    db.audit(audit_user, "微信", "绑定微信", username, {"binding_id": bid, "ilink_user_id": uid[-8:]})
    # 通知 poller 重载
    from . import poller
    poller.reload()


def unbind(username: str = None, binding_id: int = None, by=None):
    if binding_id:
        rows = db.q("SELECT * FROM wechat_bindings WHERE id=?", (binding_id,))
    else:
        rows = db.q("SELECT * FROM wechat_bindings WHERE username=?", (username,))
    for r in rows:
        db.execute("DELETE FROM wechat_bindings WHERE id=?", (r["id"],))
        db.execute("DELETE FROM wechat_pending WHERE binding_id=?", (r["id"],))
        db.audit(by or {"name": r["username"], "username": r["username"], "role": "?"}, "微信", "解除微信绑定", r["username"],
                 {"ilink_user_id": (r["ilink_user_id"] or "")[-8:]})
    if rows:
        from . import poller
        poller.reload()
    return len(rows)


def mark_rebind(binding_id: int, err: str):
    db.execute("UPDATE wechat_bindings SET status='需重新扫码', last_error=?, updated_at=?, context_token=NULL WHERE id=?",
               ((err or "")[:300], db.now(), binding_id))
