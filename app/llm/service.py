from fastapi import HTTPException

from .. import db
from . import client
from .crypto import decrypt, encrypt, mask
from .presets import PRESET_MAP, SENSITIVE_MODULES, SLOTS


def _prov_out(p):
    key = ""
    try:
        key = decrypt(p["api_key_enc"]) if p["api_key_enc"] else ""
    except Exception:  # noqa: BLE001
        key = ""
    return {"id": p["id"], "vendor": p["vendor"], "vendor_name": PRESET_MAP.get(p["vendor"], {}).get("name", p["vendor"]),
            "name": p["name"], "base_url": p["base_url"], "enabled": bool(p["enabled"]), "is_private": bool(p["is_private"]),
            "has_key": bool(key), "api_key_masked": mask(key), "created_at": p["created_at"], "updated_at": p["updated_at"]}


def _model_out(m):
    return {"id": m["id"], "provider_id": m["provider_id"], "model_id": m["model_id"], "display_name": m["display_name"] or m["model_id"],
            "params": db.jload(m["params"], {}), "enabled": bool(m["enabled"]), "allow_sensitive": bool(m["allow_sensitive"]),
            "last_test": db.jload(m["last_test"], None)}


def list_all():
    provs = [_prov_out(p) for p in db.q("SELECT * FROM llm_providers ORDER BY id")]
    models = [_model_out(m) for m in db.q("SELECT * FROM llm_models ORDER BY provider_id, id")]
    for p in provs:
        p["models"] = [m for m in models if m["provider_id"] == p["id"]]
    return provs


def save_provider(body, user, pid=None):
    vendor = body.get("vendor") or "openai_compatible"
    if vendor not in PRESET_MAP:
        raise HTTPException(400, "未知厂商类型")
    name = (body.get("name") or PRESET_MAP[vendor]["name"]).strip()
    base = (body.get("base_url") or "").strip()
    if not base.startswith(("http://", "https://")):
        raise HTTPException(400, "base_url 须以 http:// 或 https:// 开头")
    is_private = 1 if (body.get("is_private") if "is_private" in body else PRESET_MAP[vendor].get("is_private")) else 0
    enabled = 1 if body.get("enabled", True) else 0
    key = (body.get("api_key") or "").strip() or None  # 去掉粘贴带入的首尾空白/换行
    if key:
        if any(c.isspace() for c in key) or any(ord(c) > 127 for c in key):
            raise HTTPException(400, "API Key 中含空格/换行或中文字符，请重新复制粘贴")
        if key.startswith("tvly-"):
            raise HTTPException(400, "这是 Tavily 搜索服务的 Key（tvly- 开头），不是大模型 Key；搜索 Key 请在「搜索服务」中配置")
        if vendor == "deepseek" and not key.startswith("sk-"):
            raise HTTPException(400, "DeepSeek 的 API Key 以 sk- 开头，请在 platform.deepseek.com → API keys 创建并粘贴")
    if pid is None:
        pid = db.execute("INSERT INTO llm_providers(vendor,name,base_url,api_key_enc,enabled,is_private,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                         (vendor, name, base, encrypt(key or ""), enabled, is_private, db.now(), db.now()))
    else:
        if not db.q1("SELECT 1 x FROM llm_providers WHERE id=?", (pid,)):
            raise HTTPException(404, "供应商不存在")
        db.execute("UPDATE llm_providers SET vendor=?,name=?,base_url=?,enabled=?,is_private=?,updated_at=? WHERE id=?",
                   (vendor, name, base, enabled, is_private, db.now(), pid))
        if key:  # 留空 = 不修改原 Key
            db.execute("UPDATE llm_providers SET api_key_enc=? WHERE id=?", (encrypt(key), pid))
        if body.get("clear_key"):
            db.execute("UPDATE llm_providers SET api_key_enc='' WHERE id=?", (pid,))
    db.audit(user, "系统", "保存大模型供应商", name, {"vendor": vendor, "base_url": base, "key_changed": bool(key)})
    return pid


def delete_provider(pid, user):
    db.execute("DELETE FROM llm_models WHERE provider_id=?", (pid,))
    db.execute("DELETE FROM llm_providers WHERE id=?", (pid,))
    db.audit(user, "系统", "删除大模型供应商", pid)


def save_model(body, user, mid=None):
    pid = int(body["provider_id"])
    if not db.q1("SELECT 1 x FROM llm_providers WHERE id=?", (pid,)):
        raise HTTPException(404, "供应商不存在")
    model_id = (body.get("model_id") or "").strip()
    if not model_id:
        raise HTTPException(400, "模型 ID 不能为空")
    params = {}
    for k in ("temperature", "top_p", "max_tokens"):
        v = (body.get("params") or {}).get(k)
        if v not in (None, ""):
            params[k] = int(v) if k == "max_tokens" else float(v)
    vals = (pid, model_id, body.get("display_name") or model_id, db.jdump(params), 1 if body.get("enabled", True) else 0,
            1 if body.get("allow_sensitive") else 0)
    if mid is None:
        mid = db.execute("INSERT INTO llm_models(provider_id,model_id,display_name,params,enabled,allow_sensitive,created_at) VALUES(?,?,?,?,?,?,?)",
                         (*vals, db.now()))
    else:
        db.execute("UPDATE llm_models SET provider_id=?,model_id=?,display_name=?,params=?,enabled=?,allow_sensitive=? WHERE id=?", (*vals, mid))
    db.audit(user, "系统", "保存模型", model_id, {"allow_sensitive": bool(body.get("allow_sensitive")), "params": params})
    return mid


def delete_model(mid, user):
    db.execute("DELETE FROM llm_models WHERE id=?", (mid,))
    db.audit(user, "系统", "删除模型", mid)


def _resolve(mid):
    m = db.q1("SELECT m.*, p.base_url, p.api_key_enc, p.enabled p_enabled, p.name p_name FROM llm_models m JOIN llm_providers p ON p.id=m.provider_id WHERE m.id=?", (mid,))
    if not m:
        raise HTTPException(404, "模型不存在")
    return m


def test_model(mid, user):
    m = _resolve(mid)
    try:
        r = client.chat(m["base_url"], decrypt(m["api_key_enc"]), m["model_id"],
                        [{"role": "user", "content": "请只回复：连接正常"}], {"max_tokens": 16, "temperature": 0}, timeout=20)
        res = {"ok": True, "ms": r["ms"], "reply": r["content"][:60], "at": db.now()}
    except client.LLMError as e:
        res = {"ok": False, "error": str(e)[:300], "at": db.now()}
    db.execute("UPDATE llm_models SET last_test=? WHERE id=?", (db.jdump(res), mid))
    db.audit(user, "系统", "测试模型连接", m["model_id"], {"ok": res["ok"]})
    return res


def public_models():
    """供各业务页面下拉选择：不含任何 Key / base_url。"""
    rows = db.q("SELECT m.id, m.model_id, m.display_name, m.allow_sensitive, p.name p_name, p.is_private FROM llm_models m "
                "JOIN llm_providers p ON p.id=m.provider_id WHERE m.enabled=1 AND p.enabled=1 ORDER BY p.is_private DESC, p.id, m.id")
    return [{"id": r["id"], "label": f"{r['p_name']} · {r['display_name'] or r['model_id']}", "allow_sensitive": bool(r["allow_sensitive"]),
             "is_private": bool(r["is_private"])} for r in rows]


def assignments():
    return db.get_setting("llm_assign", {}) or {}


def check_allowed(slot, mid):
    if slot not in SLOTS:
        raise HTTPException(400, "未知的 AI 环节")
    if mid is None:
        return
    m = _resolve(mid)
    if not (m["enabled"] and m["p_enabled"]):
        raise HTTPException(400, "该模型已停用")
    if SLOTS[slot]["module"] in SENSITIVE_MODULES and not m["allow_sensitive"]:
        raise HTTPException(403, "该模型未被授权处理敏感模块（M4/M5 机构授信与额度数据），请选择公司私有模型或已授权模型")


def assign(slot, mid, user):
    check_allowed(slot, mid)
    a = assignments()
    a[slot] = mid
    db.set_setting("llm_assign", a)
    db.audit(user, "系统", "选择模型", slot, {"model": mid})
    return a


def require_sensitive(mid, what="该环节"):
    m = _resolve(mid)
    if not m["allow_sensitive"]:
        raise HTTPException(403, f"{what}将使用 M5 机构业务数据，所选模型未被授权处理敏感数据，请改用公司私有模型或已授权模型")


CALL_CAP = 200_000  # 单次输入/输出快照最大保存字符数
CALL_KEEP_DAYS = 180


def _snapshot(slot, m, params, messages, user, ref, prompt_version, r=None, err=None):
    """大模型调用快照：可复现（模型、参数、提示词版本、完整输入、原始输出、tokens、耗时、关联任务）。"""
    try:
        u = (r or {}).get("usage") or {}
        inp = db.jdump(messages)
        db.execute("INSERT INTO llm_calls(ts,slot,module,model_db_id,model,provider,params,prompt_version,ref,input,output,raw_output,"
                   "prompt_tokens,completion_tokens,total_tokens,ms,ok,error,user) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (db.now(), slot, SLOTS.get(slot, {}).get("module", ""), m["id"], m["model_id"], m.get("p_name"),
                    db.jdump(params), prompt_version, ref, inp[:CALL_CAP], ((r or {}).get("content") or "")[:CALL_CAP],
                    ((r or {}).get("raw") or "")[:CALL_CAP], u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens"),
                    (r or {}).get("ms"), 0 if err else 1, (str(err) or "")[:2000] if err else None, user.get("name")))
        if db.q1("SELECT COUNT(*) n FROM llm_calls")["n"] % 200 == 0:
            db.execute("DELETE FROM llm_calls WHERE ts < datetime('now','localtime',?)", (f"-{CALL_KEEP_DAYS} days",))
    except Exception:  # noqa: BLE001 快照失败不影响业务
        pass


def run(slot, messages, user, mid=None, overrides=None, timeout=60, ref=None, prompt_version=None):
    mid = mid or assignments().get(slot)
    if not mid:
        raise HTTPException(400, "该环节尚未选择模型，请先在页面上方选择，或由管理员在「系统管理 · 大模型配置」中添加模型")
    check_allowed(slot, mid)
    m = _resolve(mid)
    params = db.jload(m["params"], {})
    params.update({k: v for k, v in (overrides or {}).items() if v not in (None, "")})
    try:
        r = client.chat(m["base_url"], decrypt(m["api_key_enc"]), m["model_id"], messages, params, timeout=timeout)
    except client.LLMError as e:
        _snapshot(slot, m, params, messages, user, ref, prompt_version, err=e)
        raise HTTPException(502, f"模型调用失败：{e}") from e
    _snapshot(slot, m, params, messages, user, ref, prompt_version, r=r)
    u = r.get("usage") or {}
    tokens = u.get("total_tokens") or int((sum(len(x.get("content") or "") for x in messages) + len(r["content"])) / 1.5)
    db.audit(user, SLOTS[slot]["module"].upper(), "调用大模型", slot, {"model": m["model_id"], "ms": r["ms"], "tokens": tokens})
    return {"content": r["content"], "ms": r["ms"], "model": m["model_id"], "tokens": tokens, "tokens_estimated": not u.get("total_tokens"),
            "finish_reason": r.get("finish_reason")}
