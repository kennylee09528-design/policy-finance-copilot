"""M2 今日行业 Brief 与 M3 写作任务（三 Agent）接口。"""
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response

from . import admin_auth as A
from . import db
from . import records as REC
from . import watermark as W
from .auth import current_user, require_internal
from .m2 import brief as B, config as M2C
from .m3 import config as M3C, pipeline as P

r = APIRouter(prefix="/api", tags=["M2/M3"])
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def internal(user=Depends(current_user)):
    require_internal(user)
    return user


def _file(data, name, mt):
    return Response(data, media_type=mt, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


# ---------------- M2 ----------------
@r.get("/m2/config")
def m2_config(user=Depends(internal)):
    return M2C.get()


@r.put("/admin/m2/config")
def m2_config_save(body: dict = Body(...), u=Depends(A.require_admin_session)):
    try:
        return M2C.save(body, u)
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(400, str(e)) from e


@r.post("/admin/m2/config/reset")
def m2_config_reset(u=Depends(A.require_admin_session)):
    db.set_setting("m2_config", {})
    db.audit(u, "M2", "恢复默认简报配置", "")
    return M2C.get()


def _published_only(user, b):
    """合作机构用户只能查看已发布的简报（需求 6.4）。"""
    if user["role"] == "institution" and b.get("status") != "已发布":
        raise HTTPException(404, "简报不存在或尚未发布")
    return b


@r.get("/m2/briefs")
def m2_list(date: str = "", view: str = "", user=Depends(current_user)):
    sql = "SELECT id, brief_date, version, status, stats, model, generated_at, generated_by, edited_at, published_at, published_by FROM m2_briefs WHERE 1=1"
    a = []
    if date:
        sql += " AND brief_date=?"
        a.append(date)
    if user["role"] == "institution":
        sql += " AND status='已发布'"
    from .records import filter_rows
    rows = filter_rows("m2_brief", db.q(sql + " ORDER BY brief_date DESC, version DESC LIMIT 2000", a), "" if user["role"] == "institution" else view, user)[:500]
    for x in rows:
        x["stats"] = db.jload(x["stats"], {})
    return rows


@r.post("/m2/briefs/generate")
def m2_generate(body: dict = Body(default={}), user=Depends(internal)):
    d = body.get("date") or datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(400, "日期格式应为 YYYY-MM-DD") from e
    if d > datetime.now().strftime("%Y-%m-%d"):
        raise HTTPException(400, "不能生成未来日期的简报")
    if body.get("model_id") not in (None, ""):
        from .llm.service import assign
        assign("m2.brief", int(body["model_id"]), user)
    bid = B.generate(d, user, trigger="手动生成" if d == datetime.now().strftime("%Y-%m-%d") else "补生成历史日期")
    return B.get(bid)


@r.get("/m2/briefs/{bid}")
def m2_get(bid: int, user=Depends(current_user)):
    REC.ensure_live("m2_brief", bid, user)
    return _published_only(user, B.get(bid))


@r.put("/m2/briefs/{bid}")
def m2_edit(bid: int, body: dict = Body(...), user=Depends(internal)):
    return B.edit(bid, body, user)


@r.post("/m2/briefs/{bid}/publish")
def m2_publish(bid: int, user=Depends(internal)):
    return B.publish(bid, user)


@r.get("/m2/briefs/{bid}/export.md")
def m2_md(bid: int, user=Depends(current_user)):
    b = _published_only(user, B.get(bid))
    name = f"今日行业Brief_{b['brief_date']}_v{b['version']}.md"
    db.audit(user, "M2", "导出 Markdown", bid, {"filename": name})
    return _file(W.md_text(b["markdown"], user).encode("utf-8"), name, "text/markdown; charset=utf-8")


@r.get("/m2/briefs/{bid}/export.docx")
def m2_docx(bid: int, user=Depends(current_user)):
    _published_only(user, B.get(bid))
    data, name = B.to_docx(bid)
    db.audit(user, "M2", "导出 Word", bid, {"filename": name})
    return _file(W.docx_bytes(data, user), name, DOCX)


# ---------------- M3 Agent 配置 / 提示词（管理员） ----------------
@r.get("/m3/agents")
def m3_agents(user=Depends(internal)):
    cfg = M3C.get()
    return {"agents": cfg, "names": M3C.AGENTS, "effective_model": {a: M3C.model_of(a) for a in M3C.AGENTS},
            "prompt_version": {a: M3C.active_prompt(a)["version"] for a in M3C.AGENTS}}


@r.put("/admin/m3/agents")
def m3_agents_save(body: dict = Body(...), u=Depends(A.require_admin_session)):
    try:
        return M3C.save(body, u)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e


@r.get("/admin/m3/prompts")
def m3_prompts(agent: str = "", u=Depends(A.require_admin_session)):
    return M3C.prompts(agent or None)


@r.post("/admin/m3/prompts")
def m3_prompt_new(body: dict = Body(...), u=Depends(A.require_admin_session)):
    return {"id": M3C.new_prompt(body.get("agent"), body.get("content"), body.get("note"), u, body.get("activate", True))}


@r.post("/admin/m3/prompts/{pid}/activate")
def m3_prompt_act(pid: int, u=Depends(A.require_admin_session)):
    M3C.activate_prompt(pid, u)
    return {"ok": True}


# ---------------- M3 写作任务 ----------------
@r.post("/m3/tasks")
def m3_create(body: dict = Body(...), user=Depends(internal)):
    return {"id": P.create(body, user)}


@r.get("/m3/tasks")
def m3_tasks(view: str = "", user=Depends(internal)):
    return REC.filter_rows("m3_task", db.q("SELECT id, title, status, stage, created_by, created_at, updated_at, finalized_at FROM m3_tasks ORDER BY id DESC LIMIT 2000"), view, user)[:200]


@r.get("/m3/tasks/{tid}")
def m3_task(tid: int, user=Depends(internal)):
    REC.ensure_live("m3_task", tid, user)
    return P.detail(tid)


@r.put("/m3/tasks/{tid}/final")
def m3_final(tid: int, body: dict = Body(...), user=Depends(internal)):
    return P.save_final(tid, body.get("final") or "", user)


@r.post("/m3/tasks/{tid}/confirm")
def m3_confirm(tid: int, body: dict = Body(...), user=Depends(internal)):
    return P.confirm(tid, body.get("key"), body.get("reason"), user)


@r.post("/m3/tasks/{tid}/revise")
def m3_revise(tid: int, user=Depends(internal)):
    return P.revise_task(tid, user)


@r.post("/m3/tasks/{tid}/finalize")
def m3_finalize(tid: int, user=Depends(internal)):
    return P.finalize(tid, user)


@r.post("/m3/tasks/{tid}/summarize")
def m3_summarize(tid: int, user=Depends(internal)):
    return P.summarize(tid, user)


@r.get("/m3/tasks/{tid}/export.docx")
def m3_docx(tid: int, user=Depends(internal)):
    t = P.detail(tid)
    db.audit(user, "M3", "导出 Word", tid, {"filename": f"{t['title'][:40]}.docx"})
    return _file(W.docx_bytes(P.to_docx(tid), user), f"{t['title'][:40]}.docx", DOCX)


@r.get("/m3/tasks/{tid}/export.md")
def m3_md(tid: int, user=Depends(internal)):
    t = P.detail(tid)
    db.audit(user, "M3", "导出 Markdown", tid, {"filename": f"{t['title'][:40]}.md"})
    return _file(W.md_text(P.to_markdown(tid), user).encode("utf-8"), f"{t['title'][:40]}.md", "text/markdown; charset=utf-8")


# ---------------- 写作规范（总结 Agent 沉淀 + 人工心得） ----------------
@r.get("/m3/style")
def style_list(user=Depends(internal)):
    return db.q("SELECT * FROM m3_style_guide ORDER BY id DESC")


@r.post("/m3/style")
def style_add(body: dict = Body(...), user=Depends(internal)):
    if not (body.get("content") or "").strip():
        raise HTTPException(400, "请输入规范内容")
    cat = body.get("category") if body.get("category") in ("措辞", "结构", "口径", "心得") else "心得"
    sid = db.execute("INSERT INTO m3_style_guide(category,content,source_task_id,enabled,created_by,created_at) VALUES(?,?,NULL,1,?,?)",
                     (cat, body["content"].strip()[:300], user["name"], db.now()))
    db.audit(user, "M3", "新增写作规范", sid)
    return {"id": sid}


@r.put("/m3/style/{sid}")
def style_edit(sid: int, body: dict = Body(...), user=Depends(internal)):
    if "enabled" in body:
        db.execute("UPDATE m3_style_guide SET enabled=? WHERE id=?", (1 if body["enabled"] else 0, sid))
    if body.get("content"):
        db.execute("UPDATE m3_style_guide SET content=? WHERE id=?", (body["content"][:300], sid))
    db.audit(user, "M3", "修改写作规范", sid, body)
    return {"ok": True}


@r.delete("/m3/style/{sid}")
def style_del(sid: int, user=Depends(internal)):
    db.execute("DELETE FROM m3_style_guide WHERE id=?", (sid,))
    db.audit(user, "M3", "删除写作规范", sid)
    return {"ok": True}


@r.post("/m3/tasks/{tid}/rerun")
def m3_rerun(tid: int, user=Depends(internal)):
    return P.rerun(tid, user)
