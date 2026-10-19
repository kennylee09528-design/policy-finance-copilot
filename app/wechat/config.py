"""微信普惠Bot 配置（全局开关；每位用户的 bot_token 存在 wechat_bindings 表，Fernet 加密）。"""
from .. import db

CFG_KEY = "wechat_config"
BOT_NAME = "普惠Bot"
DEFAULT = {
    "enabled": False,
    "bot_name": BOT_NAME,
    "rate_per_min": 20,
    "max_replies": 10,          # spike 实测：每条入站最多 10 条回复
    "text_chunk": 3500,         # 官方客户端 4000；留余量
    "max_file_mb": 15,          # spike：10MB OK，25MB 未完成；保守 15MB
    "pending_ttl_hours": 48,
    "poll_timeout_s": 35,
}
PENDING_DIR_NAME = "wechat_pending"


def get():
    return {**DEFAULT, **(db.get_setting(CFG_KEY, {}) or {})}


def public():
    c = get()
    n = db.q1("SELECT COUNT(*) n FROM wechat_bindings WHERE status='正常'") or {"n": 0}
    need = db.q1("SELECT COUNT(*) n FROM wechat_bindings WHERE status='需重新扫码'") or {"n": 0}
    return {**c, "bound_ok": n["n"], "need_rebind": need["n"]}


def save(body, admin):
    c = get()
    c["enabled"] = bool(body.get("enabled", c["enabled"]))
    c["bot_name"] = (body.get("bot_name") or BOT_NAME).strip()[:40] or BOT_NAME
    for k, lo, hi in (("rate_per_min", 1, 120), ("max_replies", 1, 10), ("text_chunk", 500, 4000),
                      ("max_file_mb", 1, 20), ("pending_ttl_hours", 1, 168), ("poll_timeout_s", 10, 60)):
        if body.get(k) not in (None, ""):
            c[k] = max(lo, min(hi, int(body[k])))
    db.set_setting(CFG_KEY, c)
    db.audit(admin, "微信", "保存微信普惠Bot配置", c["bot_name"], {"enabled": c["enabled"]})
    return public()
