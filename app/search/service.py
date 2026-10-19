from fastapi import HTTPException

from .. import db
from ..llm.crypto import decrypt, encrypt, mask
from . import client
from .presets import SEARCH_PRESET_MAP


def _out(p):
    try:
        key = decrypt(p["api_key_enc"]) if p["api_key_enc"] else ""
    except Exception:  # noqa: BLE001
        key = ""
    return {"id": p["id"], "vendor": p["vendor"], "vendor_name": SEARCH_PRESET_MAP.get(p["vendor"], {}).get("name", p["vendor"]),
            "name": p["name"], "endpoint": p["endpoint"], "enabled": bool(p["enabled"]), "is_default": bool(p["is_default"]),
            "params": db.jload(p["params"], {}), "has_key": bool(key), "api_key_masked": mask(key),
            "last_test": db.jload(p["last_test"], None), "updated_at": p["updated_at"]}


def list_providers():
    return [_out(p) for p in db.q("SELECT * FROM search_providers ORDER BY id")]


def save(body, user, pid=None):
    vendor = body.get("vendor")
    if vendor not in SEARCH_PRESET_MAP:
        raise HTTPException(400, "未知搜索厂商")
    ep = (body.get("endpoint") or SEARCH_PRESET_MAP[vendor]["endpoint"]).strip()
    if not ep.startswith(("http://", "https://")):
        raise HTTPException(400, "接口地址须以 http(s):// 开头")
    name = body.get("name") or SEARCH_PRESET_MAP[vendor]["name"]
    params = body.get("params") if isinstance(body.get("params"), dict) else SEARCH_PRESET_MAP[vendor]["params"]
    en = 1 if body.get("enabled", True) else 0
    key = body.get("api_key")
    if pid is None:
        pid = db.execute("INSERT INTO search_providers(vendor,name,endpoint,api_key_enc,enabled,params,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                         (vendor, name, ep, encrypt(key or ""), en, db.jdump(params), db.now(), db.now()))
        if not db.q1("SELECT 1 x FROM search_providers WHERE is_default=1"):
            db.execute("UPDATE search_providers SET is_default=1 WHERE id=?", (pid,))
    else:
        db.execute("UPDATE search_providers SET name=?,endpoint=?,enabled=?,params=?,updated_at=? WHERE id=?", (name, ep, en, db.jdump(params), db.now(), pid))
        if key:
            db.execute("UPDATE search_providers SET api_key_enc=? WHERE id=?", (encrypt(key), pid))
        if body.get("clear_key"):
            db.execute("UPDATE search_providers SET api_key_enc='' WHERE id=?", (pid,))
    if body.get("is_default"):
        set_default(pid, user)
    db.audit(user, "系统", "保存搜索供应商", name, {"vendor": vendor, "endpoint": ep, "key_changed": bool(key)})
    return pid


def set_default(pid, user):
    db.execute("UPDATE search_providers SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END", (pid,))
    db.audit(user, "系统", "设为默认搜索", pid)


def delete(pid, user):
    db.execute("DELETE FROM search_providers WHERE id=?", (pid,))
    db.audit(user, "系统", "删除搜索供应商", pid)


def _get(pid=None):
    if pid:
        p = db.q1("SELECT * FROM search_providers WHERE id=?", (pid,))
    else:
        p = db.q1("SELECT * FROM search_providers WHERE enabled=1 ORDER BY is_default DESC, id LIMIT 1")
    if not p:
        raise HTTPException(400, "尚未配置可用的联网搜索供应商，请管理员在「系统管理 · 联网搜索」中添加并启用")
    if not p["enabled"]:
        raise HTTPException(400, "该搜索供应商已停用")
    return p


def search(query, user=None, max_results=10, time_range="week", include_domains=None, pid=None, purpose=""):
    if not (query or "").strip():
        raise HTTPException(400, "请输入检索词")
    p = _get(pid)
    # 未指定供应商时：默认供应商失败（如 Key 失效）自动依次改用其他已启用供应商
    cands = [p] + ([] if pid else [x for x in db.q("SELECT * FROM search_providers WHERE enabled=1 ORDER BY is_default DESC, id") if x["id"] != p["id"]])
    errs = []
    for p in cands:
        try:
            res = client.search(p["vendor"], p["endpoint"], decrypt(p["api_key_enc"]) if p["api_key_enc"] else "", query.strip(), max_results,
                                time_range, include_domains, db.jload(p["params"], {}))
            break
        except client.SearchError as e:
            errs.append(f"{p['name']}：{e}")
    else:
        raise HTTPException(502, "联网搜索失败：" + "；".join(errs))
    for r in res:
        r["provider"] = p["name"]
    if user:
        db.audit(user, purpose or "搜索", "联网检索", query, {"provider": p["name"], "n": len(res)})
    return res


def test(pid, user):
    p = _get(pid)
    try:
        res = client.search(p["vendor"], p["endpoint"], decrypt(p["api_key_enc"]), "政府性融资担保 政策", 3, "month", None,
                            db.jload(p["params"], {}), timeout=15)
        out = {"ok": True, "n": len(res), "sample": res[0]["title"][:40] if res else "", "at": db.now()}
    except client.SearchError as e:
        out = {"ok": False, "error": str(e)[:300], "at": db.now()}
    db.execute("UPDATE search_providers SET last_test=? WHERE id=?", (db.jdump(out), pid))
    db.audit(user, "系统", "测试搜索连接", p["name"], {"ok": out["ok"]})
    return out
