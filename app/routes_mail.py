"""邮件发送接口：管理员 SMTP 配置 / 测试；业务用户预览、确认、发送、发送记录。"""
from fastapi import APIRouter, Body, Depends

from . import admin_auth as A
from . import mailer as M
from .auth import current_user

r = APIRouter(prefix="/api", tags=["邮件"])


@r.get("/admin/mail/config")
def cfg(u=Depends(A.require_admin_session)):
    return M.public()


@r.put("/admin/mail/config")
def cfg_save(body: dict = Body(...), u=Depends(A.require_admin_session)):
    return M.save(body, u)


@r.post("/admin/mail/test")
def cfg_test(body: dict = Body(...), u=Depends(A.require_admin_session)):
    return M.test_send(body.get("to"), u)


@r.get("/mail/options")
def options(user=Depends(current_user)):
    c = M.public()
    return {"enabled": c["enabled"] and c["configured"], "allowed_domains": c["allowed_domains"], "max_recipients": c["max_recipients"],
            "can_send": user["role"] in ("admin", "internal")}


@r.post("/mail/preview")
def preview(body: dict = Body(...), user=Depends(current_user)):
    return M.preview(body.get("kind"), body.get("ref"), body.get("to"), body.get("opts"), user)


@r.post("/mail/send")
def send(body: dict = Body(...), user=Depends(current_user)):
    return M.send(body.get("kind"), body.get("ref"), body.get("to"), body.get("subject"), body.get("message"), body.get("opts"), user,
                  channel="网页", confirm=bool(body.get("confirm")), confirm_sensitive=bool(body.get("confirm_sensitive")))


@r.get("/mail/log")
def log(view: str = "", user=Depends(current_user)):
    M.require_sender(user)
    return M.log_rows(view, user)
