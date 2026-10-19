"""业务用户登录（会话 Cookie）、角色与账号管理。

角色（需求第 10 章 / 6.4）：
  admin       系统管理员：全部模块 + 删除/清理他人记录
  internal    普惠部（内部）：M1~M5、PPT、机构主数据、操作留痕
  （机构主数据 all_access=1 的机构，如示例省级融资再担保有限责任公司：其 institution 账号按 internal 生效——全机构可见、全部业务功能，
   但无任何系统管理权限；系统管理仍只认独立的管理员会话）
  institution 合作机构用户：仅本机构 M5 看板（行级隔离）、已发布的 M2 简报、M1 公开政策；M3/M4/PPT 不可见
首次启动创建演示账号（随机初始密码写入 data/user_initial_passwords.txt，600），首次登录强制改密。"""
import hashlib
import os
import re
import secrets
import time
from datetime import datetime, timedelta

import bcrypt
from fastapi import HTTPException, Request

from . import db
from .config import DATA_DIR

COOKIE = "ph_user"
SESSION_HOURS = 12
INIT_FILE = DATA_DIR / "user_initial_passwords.txt"
MIN_LEN = 10
ROLES = {"admin": "系统管理员", "internal": "普惠部（内部）", "institution": "合作机构用户"}
BIZ_ROLES = ("internal", "institution")  # 系统管理员使用独立的管理员账号（admin_auth），不在业务账号中创建
_fails: dict[str, list[float]] = {}
UNAME = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")


def _hash(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def _tok(t):
    return hashlib.sha256(t.encode()).hexdigest()


def _write_init(lines):
    old = INIT_FILE.read_text(encoding="utf-8") if INIT_FILE.exists() else "业务账号初始密码（首次登录须修改；全部修改后可删除本文件）\n"
    INIT_FILE.write_text(old + "".join(lines), encoding="utf-8")
    os.chmod(INIT_FILE, 0o600)


def ensure_demo_users():
    if db.q1("SELECT 1 x FROM users LIMIT 1"):
        return []
    inst = db.q1("SELECT full_name FROM institutions WHERE COALESCE(all_access,0)=0 ORDER BY id LIMIT 1")
    made, lines = [], []
    for un, dn, role, org in (("puhui_demo", "普惠部演示账号", "internal", None),
                              ("jigou_demo", "合作机构演示账号", "institution", inst["full_name"] if inst else None)):
        pw = secrets.token_urlsafe(12)
        db.execute("INSERT INTO users(username,display_name,role,org,pw_hash,must_change,enabled,created_at,updated_at,created_by) VALUES(?,?,?,?,?,1,1,?,?,?)",
                   (un, dn, role, org, _hash(pw), db.now(), db.now(), "系统初始化"))
        lines.append(f"{un}（{ROLES[role]}{'，' + org if org else ''}）：{pw}\n")
        made.append(un)
    _write_init(lines)
    return made


def public(u):
    return {k: u[k] for k in ("username", "display_name", "role", "org", "enabled", "must_change", "created_at", "last_login", "created_by")} | {"role_name": ROLES.get(u["role"], u["role"])}


def all_access_org(org):
    return bool(org and db.q1("SELECT 1 x FROM institutions WHERE full_name=? AND all_access=1", (org,)))


def as_user(u):
    role, extra = u["role"], {}
    if role == "institution" and all_access_org(u["org"]):
        role, extra = "internal", {"all_access": True}  # 全机构可见：业务权限同普惠部；不是 admin
    return {"name": u["display_name"] or u["username"], "username": u["username"], "role": role, "org": u["org"], "must_change": bool(u["must_change"])} | extra


def login(username, password, ip):
    key = f"{ip}|{username}"
    now = time.time()
    fails = [t for t in _fails.get(key, []) if now - t < 300]
    if len(fails) >= 5:
        raise HTTPException(429, "登录失败次数过多，请 5 分钟后再试")
    u = db.q1("SELECT * FROM users WHERE username=?", (username,))
    if not u or not u["enabled"] or not bcrypt.checkpw(password.encode(), u["pw_hash"].encode()):
        fails.append(now)
        _fails[key] = fails
        db.audit({"name": username or "?", "username": username, "role": "?"}, "系统", "登录失败", ip)
        raise HTTPException(401, "用户名或密码错误（或账号已停用）")
    _fails.pop(key, None)
    t = secrets.token_urlsafe(32)
    exp = (datetime.now() + timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO user_sessions(token_hash,username,created_at,expires_at,ip) VALUES(?,?,?,?,?)", (_tok(t), username, db.now(), exp, ip))
    db.execute("UPDATE users SET last_login=? WHERE username=?", (db.now(), username))
    db.audit(as_user(u), "系统", "登录", ip)
    return t, as_user(u)


def session_user(request: Request):
    t = request.cookies.get(COOKIE)
    if not t:
        return None
    s = db.q1("SELECT * FROM user_sessions WHERE token_hash=?", (_tok(t),))
    if not s or s["expires_at"] < db.now():
        return None
    u = db.q1("SELECT * FROM users WHERE username=? AND enabled=1", (s["username"],))
    return as_user(u) if u else None


def logout(request: Request):
    t = request.cookies.get(COOKIE)
    if t:
        db.execute("DELETE FROM user_sessions WHERE token_hash=?", (_tok(t),))


def _check_pw(new, old=None):
    if len(new) < MIN_LEN or new == old or new.isdigit() or new.isalpha():
        raise HTTPException(400, f"新密码至少 {MIN_LEN} 位，须同时包含字母和数字/符号，且不能与原密码相同")


def change_password(username, old, new):
    u = db.q1("SELECT * FROM users WHERE username=?", (username,))
    if not u or not bcrypt.checkpw(old.encode(), u["pw_hash"].encode()):
        raise HTTPException(400, "原密码不正确")
    _check_pw(new, old)
    db.execute("UPDATE users SET pw_hash=?, must_change=0, updated_at=? WHERE username=?", (_hash(new), db.now(), username))
    db.audit(as_user(u), "系统", "修改密码", username)


# ---------------- 管理员：账号管理 ----------------
def _org_ok(role, org):
    if role == "institution":
        if not org or not db.q1("SELECT 1 x FROM institutions WHERE full_name=?", (org,)):
            raise HTTPException(400, "机构用户须选择机构主数据中的机构")
        return org
    return None


def create(body, admin):
    un = (body.get("username") or "").strip()
    if not UNAME.match(un):
        raise HTTPException(400, "用户名为 3~32 位字母、数字、下划线、点或短横线")
    role = body.get("role")
    if role not in BIZ_ROLES:
        raise HTTPException(400, "角色无效")
    if db.q1("SELECT 1 x FROM users WHERE username=?", (un,)):
        raise HTTPException(409, "用户名已存在")
    org = _org_ok(role, body.get("org"))
    pw = secrets.token_urlsafe(12)
    db.execute("INSERT INTO users(username,display_name,role,org,pw_hash,must_change,enabled,created_at,updated_at,created_by) VALUES(?,?,?,?,?,1,1,?,?,?)",
               (un, (body.get("display_name") or un).strip()[:40], role, org, _hash(pw), db.now(), db.now(), admin["name"]))
    db.audit(admin, "系统", "创建用户", un, {"role": role, "org": org})
    return {"user": public(db.q1("SELECT * FROM users WHERE username=?", (un,))), "initial_password": pw}


def update(username, body, admin):
    u = db.q1("SELECT * FROM users WHERE username=?", (username,))
    if not u:
        raise HTTPException(404, "用户不存在")
    role = body.get("role", u["role"])
    if role not in BIZ_ROLES:
        raise HTTPException(400, "角色无效")
    org = _org_ok(role, body.get("org", u["org"]))
    enabled = int(bool(body.get("enabled", u["enabled"])))
    db.execute("UPDATE users SET display_name=?, role=?, org=?, enabled=?, updated_at=? WHERE username=?",
               ((body.get("display_name") or u["display_name"])[:40], role, org, enabled, db.now(), username))
    if not enabled or role != u["role"] or org != u["org"]:
        db.execute("DELETE FROM user_sessions WHERE username=?", (username,))
    db.audit(admin, "系统", "修改用户", username, {"role": role, "org": org, "enabled": enabled})
    return public(db.q1("SELECT * FROM users WHERE username=?", (username,)))


def reset(username, admin):
    if not db.q1("SELECT 1 x FROM users WHERE username=?", (username,)):
        raise HTTPException(404, "用户不存在")
    pw = secrets.token_urlsafe(12)
    db.execute("UPDATE users SET pw_hash=?, must_change=1, updated_at=? WHERE username=?", (_hash(pw), db.now(), username))
    db.execute("DELETE FROM user_sessions WHERE username=?", (username,))
    db.audit(admin, "系统", "重置用户密码", username)
    return {"initial_password": pw}


def listing():
    return [public(u) for u in db.q("SELECT * FROM users ORDER BY created_at")]
