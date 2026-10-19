"""微信普惠Bot 接口：管理员配置 / 绑定列表 / 事件日志 / 强制解绑；业务用户扫码绑定。"""
from fastapi import APIRouter, Body, Depends, HTTPException

from . import admin_auth as A
from .auth import current_user
from .wechat import config as C
from .wechat import identity as I
from .wechat import poller
from .wechat import service as S

r = APIRouter(prefix="/api", tags=["微信普惠Bot"])


# ---------------- 管理员 ----------------
@r.get("/admin/wechat/config")
def cfg(u=Depends(A.require_admin_session)):
    return {**C.public(), "poller": poller.status()}


@r.put("/admin/wechat/config")
def cfg_save(body: dict = Body(...), u=Depends(A.require_admin_session)):
    out = C.save(body, u)
    poller.reload()
    return {**out, "poller": poller.status()}


@r.get("/admin/wechat/bindings")
def adm_bindings(u=Depends(A.require_admin_session)):
    return {"bindings": I.bindings()}


@r.delete("/admin/wechat/bindings/{bid}")
def adm_unbind(bid: int, u=Depends(A.require_admin_session)):
    return {"removed": I.unbind(binding_id=bid, by=u)}


@r.get("/admin/wechat/events")
def adm_events(status: str = "", limit: int = 200, u=Depends(A.require_admin_session)):
    return S.events(limit=limit, status=status)


@r.post("/admin/wechat/qr")
def adm_qr(body: dict = Body(default={}), u=Depends(A.require_admin_session)):
    """管理员自测绑定：把扫码微信号绑到指定业务账号（默认管理员自己的测试账号需先存在）。"""
    target = (body.get("username") or "").strip()
    if not target:
        raise HTTPException(400, "请指定要绑定的业务账号 username（扫码人的微信将映射到该账号）")
    return I.start_qr(target, purpose="admin_test", by=u)


@r.get("/admin/wechat/qr/{sid}")
def adm_qr_status(sid: int, u=Depends(A.require_admin_session)):
    return I.session_public(sid)


@r.post("/admin/wechat/qr/{sid}/verify")
def adm_qr_verify(sid: int, body: dict = Body(...), u=Depends(A.require_admin_session)):
    s = I.session_public(sid)
    return I.submit_verify_code(sid, body.get("code") or "", s["username"])


# ---------------- 业务用户 ----------------
@r.get("/wechat/me")
def me(user=Depends(current_user)):
    c = C.get()
    b = I.mine(user.get("username")) if user.get("username") else None
    return {"enabled": bool(c["enabled"]), "bot_name": c.get("bot_name") or C.BOT_NAME, "bound": bool(b), "binding": b}


@r.post("/wechat/qr")
def user_qr(user=Depends(current_user)):
    if not user.get("username") or user.get("role") == "admin":
        raise HTTPException(400, "请使用业务账号绑定微信（系统管理员可在「系统管理 → 微信普惠Bot」为账号发起扫码）")
    return I.start_qr(user["username"], purpose="user", by=user)


@r.get("/wechat/qr/{sid}")
def user_qr_status(sid: int, user=Depends(current_user)):
    s = I.session_public(sid)
    if s["username"] != user.get("username") and user.get("role") != "admin":
        raise HTTPException(403, "无权查看该扫码会话")
    return s


@r.post("/wechat/qr/{sid}/verify")
def user_qr_verify(sid: int, body: dict = Body(...), user=Depends(current_user)):
    s = I.session_public(sid)
    if s["username"] != user.get("username"):
        raise HTTPException(403, "无权操作该扫码会话")
    return I.submit_verify_code(sid, body.get("code") or "", user["username"])


@r.delete("/wechat/bind")
def user_unbind(user=Depends(current_user)):
    return {"removed": I.unbind(username=user.get("username"), by=user)}
