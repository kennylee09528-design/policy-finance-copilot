"""飞书机器人配置：App Secret / Verification Token / Encrypt Key 均 Fernet 加密存储，永不回显。"""
import re

from fastapi import HTTPException

from .. import db
from ..llm.crypto import decrypt, encrypt

CFG_KEY = "feishu_config"
DOMAINS = {"feishu": "https://open.feishu.cn", "lark": "https://open.larksuite.com"}
DEFAULT = {"enabled": False, "domain": "feishu", "mode": "ws", "app_id": "", "app_secret_enc": "", "verification_token_enc": "", "encrypt_key_enc": "",
           "bot_open_id": "", "bot_name": "", "rate_per_min": 15, "bind_ttl_min": 10, "group_data": False, "last_test": None}
SECRETS = ("app_secret", "verification_token", "encrypt_key")


def get():
    return {**DEFAULT, **(db.get_setting(CFG_KEY, {}) or {})}


def secret(cfg, name):
    v = cfg.get(name + "_enc") or ""
    return decrypt(v) if v else ""


def base_url(cfg):
    return DOMAINS.get(cfg.get("domain"), DOMAINS["feishu"])


def configured(cfg=None):
    cfg = cfg or get()
    return bool(cfg["app_id"] and cfg["app_secret_enc"])


def public():
    c = get()
    out = {k: v for k, v in c.items() if not k.endswith("_enc")}
    for n in SECRETS:
        out["has_" + n] = bool(c[n + "_enc"])
    out["configured"] = configured(c)
    from ..llm import service as L
    out["router_model_id"] = (L.assignments() or {}).get("feishu.router")
    return out


def save(body, admin):
    c = get()
    app_id = (body.get("app_id") or "").strip()
    if app_id and not re.match(r"^[A-Za-z0-9_\-]{6,64}$", app_id):
        raise HTTPException(400, "App ID 格式不正确（形如 cli_a1b2c3d4e5f6g7h8）")
    domain = body.get("domain") or c["domain"]
    mode = body.get("mode") or c["mode"]
    if domain not in DOMAINS or mode not in ("ws", "http"):
        raise HTTPException(400, "域名须为 feishu / lark，接收方式须为 ws（长连接）/ http（回调）")
    if app_id != c["app_id"]:
        c["bot_open_id"] = c["bot_name"] = ""  # 换应用后需重新测试连接获取机器人身份
    c.update(app_id=app_id, domain=domain, mode=mode, enabled=bool(body.get("enabled", c["enabled"])), group_data=bool(body.get("group_data", c["group_data"])))
    for k, lo, hi in (("rate_per_min", 1, 120), ("bind_ttl_min", 1, 60)):
        if body.get(k) not in (None, ""):
            c[k] = max(lo, min(hi, int(body[k])))
    changed = []
    for n in SECRETS:
        v = body.get(n)
        if v:
            v = v.strip()
            if re.search(r"\s", v) or any(ord(ch) > 127 for ch in v):
                raise HTTPException(400, f"{n} 含空白或中文字符，请重新复制粘贴")
            c[n + "_enc"] = encrypt(v)
            changed.append(n)
        if body.get("clear_" + n):
            c[n + "_enc"] = ""
            changed.append("clear_" + n)
    if body.get("router_model_id") not in (None, ""):
        from ..llm import service as L
        L.assign("feishu.router", int(body["router_model_id"]), admin)
    db.set_setting(CFG_KEY, c)
    db.audit(admin, "飞书", "保存飞书机器人配置", c["app_id"], {"enabled": c["enabled"], "mode": mode, "domain": domain, "secrets_changed": changed})
    return public()
