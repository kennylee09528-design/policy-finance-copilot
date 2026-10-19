"""身份、角色与行级权限。

默认（PH_AUTH_MODE=session）：业务用户会话 Cookie（app/users.py）；已登录的系统管理员会话视为 admin 角色。
请求头 X-Role / X-User / X-Org 一律忽略（不可伪造身份）。
PH_AUTH_MODE=header 仅供自动化测试 / 本地开发使用（旧的演示身份头）。
"""
import os
from urllib.parse import unquote

from fastapi import Header, HTTPException, Request

from .users import ROLES


def auth_mode():
    return os.environ.get("PH_AUTH_MODE", "session")


def current_user(request: Request, x_user: str | None = Header(default=None), x_role: str | None = Header(default=None),
                 x_org: str | None = Header(default=None)):
    if auth_mode() == "header":
        role = x_role if x_role in ROLES else "internal"
        name = unquote(x_user) if x_user else "演示用户"
        return {"name": name, "username": name, "role": role, "org": unquote(x_org) if x_org else None}
    from . import admin_auth, users
    u = users.session_user(request)
    if u:
        if u["must_change"]:
            raise HTTPException(403, "首次登录须先修改密码")
        return u
    a = admin_auth.session_user(request)
    if a and not a["must_change"]:
        return {"name": a["name"], "username": a["name"], "role": "admin", "org": None}
    raise HTTPException(401, "请先登录")


def require_internal(user):
    """M4 仅内部可见（需求 6.4）。"""
    if user["role"] not in ("admin", "internal"):
        raise HTTPException(403, "该功能仅对普惠部内部开放（合作机构用户无权访问）")


def require_admin(user):
    if user["role"] != "admin":
        raise HTTPException(403, "仅系统管理员可操作")


def row_filter(user, rows, key="name"):
    """行级权限钩子：机构用户只能看到本机构数据（需求 8：一期预留）。"""
    if user["role"] == "institution":
        return [r for r in rows if r.get(key) == user.get("org")]
    return rows
