"""管理员登录：bcrypt 哈希 + 服务端会话（HttpOnly Cookie）。
首次启动随机生成初始密码写入 data/admin_initial_password.txt（权限 600），首次登录强制改密。无任何硬编码默认密码。"""
import hashlib
import os
import secrets
import time
from datetime import datetime, timedelta

import bcrypt
from fastapi import HTTPException, Request

from . import db
from .config import DATA_DIR

COOKIE = "ph_admin"
SESSION_HOURS = 8
INIT_FILE = DATA_DIR / "admin_initial_password.txt"
MIN_LEN = 10
_fails: dict[str, list[float]] = {}


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def _write_initial(username: str, pw: str):
    INIT_FILE.write_text(f"管理员账号：{username}\n初始密码：{pw}\n生成时间：{db.now()}\n首次登录后须修改密码，修改成功后本文件自动删除。\n",
                         encoding="utf-8")
    os.chmod(INIT_FILE, 0o600)


def ensure_admin():
    if db.q1("SELECT 1 x FROM admin_users LIMIT 1"):
        return None
    pw = secrets.token_urlsafe(12)
    db.execute("INSERT INTO admin_users(username,pw_hash,must_change,created_at,updated_at) VALUES(?,?,1,?,?)",
               ("admin", _hash(pw), db.now(), db.now()))
    _write_initial("admin", pw)
    return pw


def reset_password(username="admin", password=None):
    pw = password or secrets.token_urlsafe(12)
    h = _hash(pw)
    if db.q1("SELECT 1 x FROM admin_users WHERE username=?", (username,)):
        db.execute("UPDATE admin_users SET pw_hash=?, must_change=1, updated_at=? WHERE username=?", (h, db.now(), username))
    else:
        db.execute("INSERT INTO admin_users(username,pw_hash,must_change,created_at,updated_at) VALUES(?,?,1,?,?)",
                   (username, h, db.now(), db.now()))
    db.execute("DELETE FROM admin_sessions WHERE username=?", (username,))
    _write_initial(username, pw)
    db.audit({"name": "CLI", "role": "admin"}, "系统", "重置管理员密码", username)
    return pw


def _tok_hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def login(username: str, password: str, ip: str):
    key = f"{ip}|{username}"
    now = time.time()
    fails = [t for t in _fails.get(key, []) if now - t < 300]
    if len(fails) >= 5:
        raise HTTPException(429, "登录失败次数过多，请 5 分钟后再试")
    u = db.q1("SELECT * FROM admin_users WHERE username=?", (username,))
    if not u or not bcrypt.checkpw(password.encode(), u["pw_hash"].encode()):
        fails.append(now)
        _fails[key] = fails
        db.audit({"name": username or "?", "role": "admin"}, "系统", "管理员登录失败", ip)
        raise HTTPException(401, "用户名或密码错误")
    _fails.pop(key, None)
    tok = secrets.token_urlsafe(32)
    exp = (datetime.now() + timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO admin_sessions(token_hash,username,created_at,expires_at,ip) VALUES(?,?,?,?,?)",
               (_tok_hash(tok), username, db.now(), exp, ip))
    db.audit({"name": username, "role": "admin"}, "系统", "管理员登录", ip)
    return tok, bool(u["must_change"])


def session_user(request: Request):
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    s = db.q1("SELECT * FROM admin_sessions WHERE token_hash=?", (_tok_hash(tok),))
    if not s or s["expires_at"] < db.now():
        return None
    u = db.q1("SELECT username, must_change FROM admin_users WHERE username=?", (s["username"],))
    return {"name": u["username"], "role": "admin", "must_change": bool(u["must_change"]), "org": None} if u else None


def require_admin_session(request: Request):
    u = session_user(request)
    if not u:
        raise HTTPException(401, "请先以管理员身份登录")
    if u["must_change"]:
        raise HTTPException(403, "首次登录须先修改密码")
    return u


def logout(request: Request):
    tok = request.cookies.get(COOKIE)
    if tok:
        db.execute("DELETE FROM admin_sessions WHERE token_hash=?", (_tok_hash(tok),))


def change_password(username: str, old: str, new: str):
    u = db.q1("SELECT * FROM admin_users WHERE username=?", (username,))
    if not u or not bcrypt.checkpw(old.encode(), u["pw_hash"].encode()):
        raise HTTPException(400, "原密码不正确")
    if len(new) < MIN_LEN or new == old or new.isdigit() or new.isalpha():
        raise HTTPException(400, f"新密码至少 {MIN_LEN} 位，须同时包含字母和数字/符号，且不能与原密码相同")
    db.execute("UPDATE admin_users SET pw_hash=?, must_change=0, updated_at=? WHERE username=?", (_hash(new), db.now(), username))
    if INIT_FILE.exists():
        INIT_FILE.unlink()
    db.audit({"name": username, "role": "admin"}, "系统", "修改管理员密码", username)
