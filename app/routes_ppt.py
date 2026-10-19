"""PPT 生成 Agent 接口。"""
import os
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from . import admin_auth as A
from . import db
from . import records as REC
from . import watermark as W
from .auth import current_user, require_internal
from .llm.service import public_models
from .ppt import agent as G, config as C
from .ppt.data import DECKS

r = APIRouter(prefix="/api", tags=["PPT"])
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def internal(user=Depends(current_user)):
    require_internal(user)
    return user


@r.get("/ppt/options")
def options(user=Depends(internal)):
    """新建任务所需的选项：类型、数据来源、模型、模板。"""
    return {
        "decks": DECKS,
        "snapshots": db.q("SELECT id, stat_date, label FROM m5_snapshots ORDER BY stat_date DESC, id DESC LIMIT 50"),
        "schemes": db.q("SELECT id, version, name, status, is_current FROM m4_schemes ORDER BY is_current DESC, version DESC LIMIT 50"),
        "brief_dates": [x["brief_date"] for x in db.q("SELECT DISTINCT brief_date FROM m2_briefs ORDER BY brief_date DESC LIMIT 120")],
        "m3_tasks": db.q("SELECT id, title, status FROM m3_tasks WHERE status IN ('已定稿','已总结') ORDER BY id DESC LIMIT 50"),
        "models": public_models(),
        "default_model": G.model_of(),
        "templates": [{"id": t["id"], "name": t["name"], "active": t["active"]} for t in G.templates()],
        "kinds": G.KINDS,
    }


@r.get("/ppt/jobs")
def jobs(view: str = "", user=Depends(internal)):
    return REC.filter_rows("ppt_job", G.list_jobs(), view, user)


@r.post("/ppt/jobs")
def create(body: dict = Body(...), user=Depends(internal)):
    return G.create(body, user)


@r.get("/ppt/jobs/{jid}")
def get(jid: int, user=Depends(internal)):
    REC.ensure_live("ppt_job", jid, user)
    return G.detail(jid)


@r.post("/ppt/jobs/{jid}/sheet")
def confirm_sheet(jid: int, body: dict = Body(...), user=Depends(internal)):
    return G.confirm_sheet(jid, body, user)


@r.post("/ppt/jobs/{jid}/outline/regenerate")
def regen(jid: int, body: dict = Body(default={}), user=Depends(internal)):
    return G.regenerate_outline(jid, body, user)


@r.put("/ppt/jobs/{jid}/outline")
def save_outline(jid: int, body: dict = Body(...), user=Depends(internal)):
    return G.save_outline(jid, body, user)


@r.post("/ppt/jobs/{jid}/generate")
def generate(jid: int, body: dict = Body(default={}), user=Depends(internal)):
    return G.generate(jid, body, user)


@r.get("/ppt/files/{fid}/download")
def download(fid: int, user=Depends(internal)):
    f = G.file_row(fid)
    db.audit(user, "PPT", "下载 PPT", fid, {"job": f["job_id"], "version": f["version"], "filename": f["filename"]})
    from pathlib import Path
    data = W.pptx_bytes(Path(f["path"]).read_bytes(), user)
    return Response(data, media_type=PPTX, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(f['filename'])}"})


@r.get("/ppt/files/{fid}/thumbs/{name}")
def thumb(fid: int, name: str, user=Depends(internal)):
    f = G.file_row(fid)
    if name not in db.jload(f["thumbs"], []):
        raise HTTPException(404, "缩略图不存在")
    return FileResponse(os.path.join(os.path.dirname(f["path"]), f"v{f['version']}_thumbs", name), media_type="image/png")


@r.get("/ppt/templates")
def templates(user=Depends(internal)):
    return G.templates()


# ---------------- 管理员 ----------------
@r.get("/admin/ppt/config")
def cfg(u=Depends(A.require_admin_session)):
    return {"config": C.get(), "prompts": C.prompts(), "templates": G.templates(), "decks": DECKS}


@r.put("/admin/ppt/config")
def cfg_save(body: dict = Body(...), u=Depends(A.require_admin_session)):
    return C.save(body, u)


@r.post("/admin/ppt/prompts")
def prompt_new(body: dict = Body(...), u=Depends(A.require_admin_session)):
    return {"id": C.new_prompt(body.get("deck_type"), body.get("content"), body.get("note"), u), "prompts": C.prompts()}


@r.post("/admin/ppt/prompts/{pid}/activate")
def prompt_act(pid: int, u=Depends(A.require_admin_session)):
    C.activate_prompt(pid, u)
    return C.prompts()


@r.post("/admin/ppt/templates")
async def tpl_upload(file: UploadFile = File(...), name: str = Form(""), u=Depends(A.require_admin_session)):
    return G.upload_template(name, file.filename or "template.pptx", await file.read(), u)


@r.post("/admin/ppt/templates/{tid}/activate")
def tpl_act(tid: int, u=Depends(A.require_admin_session)):
    G.activate_template(tid, u)
    return G.templates()


@r.delete("/admin/ppt/templates/{tid}")
def tpl_del(tid: int, u=Depends(A.require_admin_session)):
    G.delete_template(tid, u)
    return G.templates()
