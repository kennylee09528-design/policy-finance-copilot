"""系统管理：管理员登录 + 大模型供应商配置；以及供业务页面使用的模型选择/调用接口。"""
from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from . import admin_auth as A
from . import db
from .auth import current_user, require_internal
from .llm import service as L
from .llm.presets import PRESETS, SLOTS

r = APIRouter(prefix="/api", tags=["系统管理"])


def _secure(request: Request):
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


@r.post("/admin/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    tok, must = A.login((body.get("username") or "").strip(), body.get("password") or "", ip)
    response.set_cookie(A.COOKIE, tok, httponly=True, samesite="strict", secure=_secure(request), max_age=A.SESSION_HOURS * 3600, path="/")
    return {"ok": True, "must_change": must}


@r.post("/admin/logout")
def logout(request: Request, response: Response):
    A.logout(request)
    response.delete_cookie(A.COOKIE, path="/")
    return {"ok": True}


@r.get("/admin/me")
def me(request: Request):
    u = A.session_user(request)
    return {"logged_in": bool(u), "username": u["name"] if u else None, "must_change": u["must_change"] if u else False}


@r.post("/admin/password")
def change_pw(request: Request, body: dict = Body(...)):
    u = A.session_user(request)
    if not u:
        raise HTTPException(401, "请先登录")
    A.change_password(u["name"], body.get("old") or "", body.get("new") or "")
    return {"ok": True}


# ---------- 大模型配置（仅管理员） ----------
@r.get("/admin/llm/presets")
def presets(u=Depends(A.require_admin_session)):
    return {"presets": PRESETS, "slots": SLOTS}


@r.get("/admin/llm/providers")
def providers(u=Depends(A.require_admin_session)):
    return L.list_all()


@r.post("/admin/llm/providers")
def add_provider(body: dict = Body(...), u=Depends(A.require_admin_session)):
    pid = L.save_provider(body, u)
    for m in body.get("models") or []:  # 新建时可附带预设模型
        L.save_model({"provider_id": pid, "model_id": m, "allow_sensitive": body.get("allow_sensitive", False)}, u)
    return {"id": pid}


@r.put("/admin/llm/providers/{pid}")
def edit_provider(pid: int, body: dict = Body(...), u=Depends(A.require_admin_session)):
    return {"id": L.save_provider(body, u, pid)}


@r.delete("/admin/llm/providers/{pid}")
def del_provider(pid: int, u=Depends(A.require_admin_session)):
    L.delete_provider(pid, u)
    return {"ok": True}


@r.post("/admin/llm/models")
def add_model(body: dict = Body(...), u=Depends(A.require_admin_session)):
    return {"id": L.save_model(body, u)}


@r.put("/admin/llm/models/{mid}")
def edit_model(mid: int, body: dict = Body(...), u=Depends(A.require_admin_session)):
    return {"id": L.save_model(body, u, mid)}


@r.delete("/admin/llm/models/{mid}")
def del_model(mid: int, u=Depends(A.require_admin_session)):
    L.delete_model(mid, u)
    return {"ok": True}


@r.post("/admin/llm/models/{mid}/test")
def test_model(mid: int, u=Depends(A.require_admin_session)):
    return L.test_model(mid, u)


# ---------- 联网搜索供应商（仅管理员） ----------
from .search import service as SS  # noqa: E402
from .search.presets import SEARCH_PRESETS  # noqa: E402
from .m1 import config as M1C  # noqa: E402


@r.get("/admin/search/providers")
def s_list(u=Depends(A.require_admin_session)):
    return {"providers": SS.list_providers(), "presets": SEARCH_PRESETS}


@r.post("/admin/search/providers")
def s_add(body: dict = Body(...), u=Depends(A.require_admin_session)):
    return {"id": SS.save(body, u)}


@r.put("/admin/search/providers/{pid}")
def s_edit(pid: int, body: dict = Body(...), u=Depends(A.require_admin_session)):
    return {"id": SS.save(body, u, pid)}


@r.post("/admin/search/providers/{pid}/default")
def s_default(pid: int, u=Depends(A.require_admin_session)):
    SS.set_default(pid, u)
    return {"ok": True}


@r.delete("/admin/search/providers/{pid}")
def s_del(pid: int, u=Depends(A.require_admin_session)):
    SS.delete(pid, u)
    return {"ok": True}


@r.post("/admin/search/providers/{pid}/test")
def s_test(pid: int, u=Depends(A.require_admin_session)):
    return SS.test(pid, u)


# ---------- M1 采集规则与查询模板（仅管理员） ----------
@r.put("/admin/m1/config")
def m1_cfg(body: dict = Body(...), u=Depends(A.require_admin_session)):
    try:
        return M1C.save(body, u)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e


@r.post("/admin/m1/config/reset")
def m1_cfg_reset(u=Depends(A.require_admin_session)):
    db.set_setting("m1_config", {})
    db.audit(u, "M1", "恢复默认采集配置", "")
    return M1C.get()


# ---------- 业务页面使用（内部用户；不返回任何 Key / 地址） ----------
@r.get("/llm/models")
def pub_models(user=Depends(current_user)):
    require_internal(user)
    return {"models": L.public_models(), "assign": L.assignments(), "slots": SLOTS}


@r.post("/llm/assign")
def assign(body: dict = Body(...), user=Depends(current_user)):
    require_internal(user)
    mid = body.get("model_id")
    return L.assign(body["slot"], int(mid) if mid not in (None, "") else None, user)


@r.post("/llm/run")
def run(body: dict = Body(...), user=Depends(current_user)):
    require_internal(user)
    msgs = body.get("messages") or [{"role": "user", "content": body.get("prompt") or ""}]
    if not any((m.get("content") or "").strip() for m in msgs):
        raise HTTPException(400, "请输入内容")
    return L.run(body["slot"], msgs, user, body.get("model_id"))


@r.post("/m5/snapshots/{sid}/notes/ai")
def m5_notes_ai(sid: int, body: dict = Body(default={}), user=Depends(current_user)):
    """用已授权处理敏感数据的模型润色环比说明（敏感模块校验在 L.run 内执行）。"""
    require_internal(user)
    from .m5 import service as S
    d = S.dashboard(sid, user)
    txt = "\n".join(f"{k}：{v}" for k, v in d["notes"].items())
    prompt = ("你是示例再担保公司业务部的材料撰写人员。请将以下额度使用环比说明润色为正式公文表述，"
              "保持所有数字、单位、日期完全不变，不得新增任何数据，每类业务一段：\n" + txt)
    return L.run("m5.notes", [{"role": "user", "content": prompt}], user, body.get("model_id"))


# ---------------- 演示数据与上线就绪 ----------------
@r.get("/admin/demo")
def demo_status(u=Depends(A.require_admin_session)):
    from . import demo
    return demo.readiness()


@r.post("/admin/demo/load")
def demo_load(u=Depends(A.require_admin_session)):
    from . import demo
    return demo.load(u)


@r.post("/admin/demo/clear")
def demo_clear(u=Depends(A.require_admin_session)):
    from . import demo
    return demo.clear(u)


@r.get("/admin/ops")
def ops_status(u=Depends(A.require_admin_session)):
    from . import ops
    return ops.status()


@r.get("/admin/backups")
def backups(u=Depends(A.require_admin_session)):
    from . import backup
    return backup.listing()


@r.post("/admin/backups")
def backup_create(u=Depends(A.require_admin_session)):
    from . import backup, ops
    res = ops.run_job("backup", backup.backup_now, "手动", u)
    if not res:
        raise HTTPException(500, "备份失败，详见「运行状态」")
    return res


@r.put("/admin/backups/config")
def backup_cfg(body: dict = Body(...), u=Depends(A.require_admin_session)):
    from . import backup
    try:
        return backup.save_cfg(body, u)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, "备份设置无效") from e


# ---------------- 大模型调用快照（可复现） ----------------
@r.get("/admin/llm/calls")
def llm_calls(slot: str = "", ref: str = "", ok: str = "", q: str = "", limit: int = 200, u=Depends(A.require_admin_session)):
    sql, a = ("SELECT id,ts,slot,module,model,provider,prompt_version,ref,prompt_tokens,completion_tokens,total_tokens,ms,ok,"
              "substr(error,1,200) error,user,length(input) input_len,length(output) output_len FROM llm_calls WHERE 1=1"), []
    if slot:
        sql += " AND slot=?"
        a.append(slot)
    if ref:
        sql += " AND ref=?"
        a.append(ref)
    if ok in ("0", "1"):
        sql += " AND ok=?"
        a.append(int(ok))
    if q:
        sql += " AND (input LIKE ? OR output LIKE ?)"
        a += [f"%{q}%"] * 2
    rows = db.q(sql + " ORDER BY id DESC LIMIT ?", (*a, max(1, min(limit, 1000))))
    st = db.q1("SELECT COUNT(*) n, SUM(total_tokens) t, SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) f, AVG(ms) ms FROM llm_calls")
    return {"calls": rows, "stats": st, "slots": {k: v["name"] for k, v in SLOTS.items()}}


@r.get("/admin/llm/calls/{cid}")
def llm_call(cid: int, u=Depends(A.require_admin_session)):
    c = db.q1("SELECT * FROM llm_calls WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "记录不存在")
    c["input"] = db.jload(c["input"], c["input"])
    c["params"] = db.jload(c["params"], {})
    return c
