"""业务用户登录 / 改密 + 管理员账号管理。"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from . import admin_auth as A
from . import db
from . import users as U
from .routes_admin import _secure

r = APIRouter(prefix="/api", tags=["登录与账号"])


def _ip(request):
    return request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()


@r.post("/auth/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    tok, u = U.login((body.get("username") or "").strip(), body.get("password") or "", _ip(request))
    response.set_cookie(U.COOKIE, tok, httponly=True, samesite="strict", secure=_secure(request), max_age=U.SESSION_HOURS * 3600, path="/")
    return {"ok": True, "user": u | {"role_name": ("再担保机构用户（全机构可见）" if u.get("all_access") else U.ROLES[u["role"]])}}


@r.post("/auth/logout")
def logout(request: Request, response: Response):
    U.logout(request)
    response.delete_cookie(U.COOKIE, path="/")
    return {"ok": True}


@r.get("/auth/me")
def me(request: Request):
    """前端启动时调用：返回当前身份（业务用户 / 管理员会话）或未登录。"""
    from .auth import auth_mode
    if auth_mode() == "header":
        return {"logged_in": True, "mode": "header", "user": {"name": "演示用户", "role": "internal", "role_name": U.ROLES["internal"], "org": None, "must_change": False}}
    u = U.session_user(request)
    if u:
        return {"logged_in": True, "kind": "user", "user": u | {"role_name": ("再担保机构用户（全机构可见）" if u.get("all_access") else U.ROLES[u["role"]])}}
    a = A.session_user(request)
    if a:
        return {"logged_in": True, "kind": "admin", "user": {"name": a["name"], "username": a["name"], "role": "admin", "role_name": U.ROLES["admin"], "org": None, "must_change": a["must_change"]}}
    return {"logged_in": False}


@r.post("/auth/password")
def password(request: Request, body: dict = Body(...)):
    u = U.session_user(request)
    if not u:
        raise HTTPException(401, "请先登录")
    U.change_password(u["username"], body.get("old") or "", body.get("new") or "")
    return {"ok": True}


# ---------------- 管理员：业务账号管理 ----------------
@r.get("/admin/users")
def users_list(a=Depends(A.require_admin_session)):
    insts = [x["full_name"] for x in db.q("SELECT full_name FROM institutions ORDER BY id")]
    return {"users": U.listing(), "roles": U.ROLES, "institutions": insts}


@r.post("/admin/users")
def users_create(body: dict = Body(...), a=Depends(A.require_admin_session)):
    return U.create(body, a)


@r.put("/admin/users/{username}")
def users_update(username: str, body: dict = Body(...), a=Depends(A.require_admin_session)):
    return U.update(username, body, a)


@r.post("/admin/users/{username}/reset")
def users_reset(username: str, a=Depends(A.require_admin_session)):
    return U.reset(username, a)
