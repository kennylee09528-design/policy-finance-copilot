"""飞书用户 ↔ 工作台账号绑定：网页端生成一次性绑定码，用户在飞书里私聊机器人发送「绑定 码」；管理员也可手工映射。"""
import hashlib
import secrets
import time
from datetime import datetime, timedelta

from fastapi import HTTPException

from .. import db
from .. import users as U
from . import config as C

_fails: dict[str, list[float]] = {}
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _h(code):
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def new_code(user):
    """已登录的业务用户生成绑定码（同一账号旧的未用码作废）。"""
    un = user.get("username")
    if not un or not db.q1("SELECT 1 x FROM users WHERE username=? AND enabled=1", (un,)):
        raise HTTPException(400, "仅业务账号可绑定飞书（系统管理员请在「系统管理 → 飞书机器人」中为用户手工映射）")
    cfg = C.get()
    if not (cfg["enabled"] and C.configured(cfg)):
        raise HTTPException(400, "管理员尚未启用飞书机器人")
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    ttl = int(cfg["bind_ttl_min"])
    db.execute("DELETE FROM feishu_bind_codes WHERE username=? AND used_at IS NULL", (un,))
    db.execute("INSERT INTO feishu_bind_codes(code_hash,username,created_at,expires_at) VALUES(?,?,?,?)",
               (_h(code), un, db.now(), (datetime.now() + timedelta(minutes=ttl)).strftime("%Y-%m-%d %H:%M:%S")))
    db.audit(user, "飞书", "生成飞书绑定码", un, {"ttl_min": ttl})
    return {"code": code, "ttl_min": ttl, "bot_name": cfg["bot_name"]}


def bind_with_code(open_id, code):
    now = time.time()
    fails = [t for t in _fails.get(open_id, []) if now - t < 600]
    if len(fails) >= 5:
        return None, "绑定尝试次数过多，请 10 分钟后再试"
    row = db.q1("SELECT * FROM feishu_bind_codes WHERE code_hash=?", (_h(code),))
    if not row or row["used_at"] or row["expires_at"] < db.now():
        fails.append(now)
        _fails[open_id] = fails
        return None, "绑定码无效或已过期。请回到工作台网页，点击右上角「绑定飞书」重新生成。"
    u = db.q1("SELECT * FROM users WHERE username=? AND enabled=1", (row["username"],))
    if not u:
        return None, "该账号已停用，无法绑定"
    _fails.pop(open_id, None)
    db.execute("UPDATE feishu_bind_codes SET used_at=? WHERE code_hash=?", (db.now(), row["code_hash"]))
    _set(open_id, u["username"], u["username"])
    au = U.as_user(u)
    db.audit(au, "飞书", "绑定飞书", u["username"], {"open_id": open_id[-6:], "by": "绑定码"})
    return au, None


def _set(open_id, username, by):
    db.execute("DELETE FROM feishu_bindings WHERE username=? OR open_id=?", (username, open_id))  # 1 个账号 ↔ 1 个飞书用户
    db.execute("INSERT INTO feishu_bindings(open_id,username,bound_at,bound_by,last_seen) VALUES(?,?,?,?,?)", (open_id, username, db.now(), by, db.now()))


def admin_map(open_id, username, admin):
    open_id = (open_id or "").strip()
    if not open_id.startswith("ou_") or len(open_id) < 8:
        raise HTTPException(400, "open_id 形如 ou_xxxxxxxx（可在「事件日志」中查到未绑定用户发来的消息）")
    u = db.q1("SELECT * FROM users WHERE username=? AND enabled=1", (username,))
    if not u:
        raise HTTPException(404, "业务账号不存在或已停用")
    _set(open_id, username, admin["name"])
    db.audit(admin, "飞书", "管理员映射飞书账号", username, {"open_id": open_id[-6:]})
    return {"ok": True}


def unbind(open_id=None, username=None, by=None):
    where, arg = ("open_id=?", open_id) if open_id else ("username=?", username)
    rows = db.q(f"SELECT * FROM feishu_bindings WHERE {where}", (arg,))
    db.execute(f"DELETE FROM feishu_bindings WHERE {where}", (arg,))
    for r in rows:
        db.execute("DELETE FROM feishu_state WHERE open_id=?", (r["open_id"],))
        db.audit(by or {"name": r["username"], "username": r["username"], "role": "?"}, "飞书", "解除飞书绑定", r["username"], {"open_id": r["open_id"][-6:]})
    return len(rows)


def user_of(open_id):
    """返回 (用户 dict, 提示)：账号停用/需改密时返回 (None, 提示)。"""
    b = db.q1("SELECT * FROM feishu_bindings WHERE open_id=?", (open_id,))
    if not b:
        return None, None
    u = db.q1("SELECT * FROM users WHERE username=?", (b["username"],))
    if not u or not u["enabled"]:
        return None, "您绑定的工作台账号已停用，请联系管理员。"
    if u["must_change"]:
        return None, "您的工作台账号需先在网页端修改初始密码后才能使用。"
    db.execute("UPDATE feishu_bindings SET last_seen=? WHERE open_id=?", (db.now(), open_id))
    return U.as_user(u), None


def bindings():
    return db.q("SELECT b.open_id, b.username, b.bound_at, b.bound_by, b.last_seen, u.display_name, u.role, u.org, u.enabled "
                "FROM feishu_bindings b LEFT JOIN users u ON u.username=b.username ORDER BY b.bound_at DESC")


def mine(username):
    b = db.q1("SELECT bound_at, last_seen FROM feishu_bindings WHERE username=?", (username,))
    return b
