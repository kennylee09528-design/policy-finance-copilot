"""飞书机器人接口：管理员配置 / 测试 / 事件日志 / 账号映射；业务用户绑定；HTTP 事件回调（备选接收方式）。"""
import base64
import hashlib
import json

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from . import admin_auth as A
from . import db
from .auth import current_user
from .feishu import api as FA
from .feishu import config as C
from .feishu import identity as I
from .feishu import service as S

r = APIRouter(prefix="/api", tags=["飞书机器人"])


# ---------------- 管理员 ----------------
@r.get("/admin/feishu/config")
def cfg(u=Depends(A.require_admin_session)):
    from .feishu import ws_manager
    return {**C.public(), "ws_status": ws_manager.status(), "callback_path": "/api/feishu/events"}


@r.put("/admin/feishu/config")
def cfg_save(body: dict = Body(...), u=Depends(A.require_admin_session)):
    out = C.save(body, u)
    from .feishu import ws_manager
    if not _disabled():
        ws_manager.apply()
    return {**out, "ws_status": ws_manager.status()}


def _disabled():
    import os
    return bool(os.environ.get("PH_DISABLE_SCHEDULER"))


@r.post("/admin/feishu/test")
def test(u=Depends(A.require_admin_session)):
    c = C.get()
    if not C.configured(c):
        raise HTTPException(400, "请先填写并保存 App ID 与 App Secret")
    res = {"at": db.now()}
    try:
        api = FA.get_api()
        api.token()
        info = api.bot_info()
        c["bot_open_id"], c["bot_name"] = info["open_id"], info["name"]
        res.update(ok=True, bot_name=info["name"], bot_open_id=info["open_id"])
    except FA.FeishuError as e:
        res.update(ok=False, error=str(e)[:300])
    except Exception as e:  # noqa: BLE001
        res.update(ok=False, error=f"无法连接飞书：{type(e).__name__}: {e}"[:300])
    c["last_test"] = res
    db.set_setting(C.CFG_KEY, c)
    db.audit(u, "飞书", "测试飞书连接", c["app_id"], {"ok": res["ok"]})
    return res


@r.get("/admin/feishu/events")
def events(status: str = "", limit: int = 200, u=Depends(A.require_admin_session)):
    sql, a = "SELECT * FROM feishu_events", []
    if status:
        sql += " WHERE status=?"
        a.append(status)
    return db.q(sql + " ORDER BY id DESC LIMIT ?", (*a, min(limit, 500)))


@r.get("/admin/feishu/bindings")
def bindings(u=Depends(A.require_admin_session)):
    return {"bindings": I.bindings(), "users": [{"username": x["username"], "display_name": x["display_name"], "role": x["role"]} for x in db.q("SELECT username, display_name, role FROM users WHERE enabled=1 ORDER BY username")]}


@r.post("/admin/feishu/bindings")
def bind_map(body: dict = Body(...), u=Depends(A.require_admin_session)):
    return I.admin_map(body.get("open_id"), body.get("username"), u)


@r.delete("/admin/feishu/bindings/{open_id}")
def unbind(open_id: str, u=Depends(A.require_admin_session)):
    return {"removed": I.unbind(open_id=open_id, by=u)}


# ---------------- 业务用户 ----------------
@r.get("/feishu/me")
def me(user=Depends(current_user)):
    c = C.get()
    b = I.mine(user.get("username"))
    return {"enabled": bool(c["enabled"] and C.configured(c)), "bot_name": c["bot_name"], "bound": bool(b), "bound_at": b["bound_at"] if b else None, "last_seen": b["last_seen"] if b else None}


@r.post("/feishu/bind-code")
def bind_code(user=Depends(current_user)):
    return I.new_code(user)


@r.delete("/feishu/bind")
def unbind_me(user=Depends(current_user)):
    return {"removed": I.unbind(username=user.get("username"), by=user)}


# ---------------- HTTP 事件回调（备选；需 Caddy 对该路径放行 Basic Auth，见 docs/feishu_setup.md） ----------------
def decrypt_event(encrypt_key, b64):
    key = hashlib.sha256(encrypt_key.encode()).digest()
    raw = base64.b64decode(b64)
    dec = Cipher(algorithms.AES(key), modes.CBC(raw[:16])).decryptor()
    pt = dec.update(raw[16:]) + dec.finalize()
    un = padding.PKCS7(128).unpadder()
    return json.loads((un.update(pt) + un.finalize()).decode())


@r.post("/feishu/events")
async def callback(request: Request):
    c = C.get()
    if not (c["enabled"] and c["mode"] == "http" and C.configured(c)):
        raise HTTPException(404, "未启用")
    raw = await request.body()
    try:
        body = json.loads(raw)
    except ValueError as e:
        raise HTTPException(400, "无效 JSON") from e
    ek, tok = C.secret(c, "encrypt_key"), C.secret(c, "verification_token")
    if ek:
        sig = request.headers.get("x-lark-signature")
        ts, nonce = request.headers.get("x-lark-request-timestamp", ""), request.headers.get("x-lark-request-nonce", "")
        if sig and hashlib.sha256((ts + nonce + ek + raw.decode()).encode()).hexdigest() != sig:
            raise HTTPException(403, "签名校验失败")
        if "encrypt" in body:
            try:
                body = decrypt_event(ek, body["encrypt"])
            except Exception as e:  # noqa: BLE001
                raise HTTPException(400, "解密失败（Encrypt Key 不一致？）") from e
    elif "encrypt" in body:
        raise HTTPException(400, "收到加密事件，但未配置 Encrypt Key")
    got = body.get("token") or (body.get("header") or {}).get("token")
    if not tok or got != tok:
        raise HTTPException(403, "Verification Token 不匹配")
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}
    S.dispatch(body, source="HTTP回调")
    return {"code": 0}
