from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile

from . import db
from . import records as REC
from . import watermark as W
from .auth import current_user, require_internal
from .config import M5_SAMPLE_DIR, M5_SUMMARY_SAMPLE
from .m5 import limits as L
from .m5 import service as S
from .routes_m4 import file_resp

r = APIRouter(prefix="/api/m5", tags=["M5 机构看板"])
SAMPLE_PORTS = {"regular": "2-1.常规.xlsx", "tech": "2-2.科创.xlsx", "private": "2-3.民投.xlsx", "t2t": "2-4.总对总.xlsx"}


def internal(user=Depends(current_user)):
    require_internal(user)
    return user


@r.get("/limit-sets")
def limit_sets(view: str = "", user=Depends(internal)):
    return REC.filter_rows("m5_limit_set", L.list_limit_sets(), view, user)


@r.get("/limit-sets/{lid}")
def limit_set(lid: int, user=Depends(internal)):
    return L.get_limit_set(lid)


@r.post("/limit-sets/import")
async def import_limits(file: UploadFile = File(...), user=Depends(internal)):
    data = L.parse_limit_workbook(await file.read())
    return {"limit_set_id": L.save_limit_set(f"导入：{file.filename}", f"手工导入:{file.filename}", data, user), "warnings": data["warnings"]}


@r.post("/limit-sets/import-sample")
def import_limits_sample(user=Depends(internal)):
    data = L.parse_limit_workbook(M5_SUMMARY_SAMPLE.read_bytes())
    return {"limit_set_id": L.save_limit_set(f"导入：{M5_SUMMARY_SAMPLE.name}", f"手工导入:{M5_SUMMARY_SAMPLE.name}", data, user),
            "warnings": data["warnings"]}


@r.post("/limit-sets/from-m4")
def limits_from_m4(body: dict = Body(...), user=Depends(internal)):
    return {"limit_set_id": L.from_m4_scheme(body["scheme_id"], user, body.get("base_limit_id"))}


@r.put("/limit-sets/{lid}")
def edit_limits(lid: int, body: dict = Body(...), user=Depends(internal)):
    return {"limit_set_id": L.update_limit_set(lid, body["data"], user, body.get("reason"))}


@r.get("/snapshots")
def snapshots(view: str = "", user=Depends(current_user)):
    return REC.filter_rows("m5_snapshot", S.list_snapshots(), "" if user["role"] == "institution" else view, user)


@r.post("/snapshots")
async def new_snapshot(stat_date: str = Form(...), label: str = Form(""), limit_set_id: int | None = Form(None),
                       regular: UploadFile | None = File(None), tech: UploadFile | None = File(None),
                       private: UploadFile | None = File(None), t2t: UploadFile | None = File(None), user=Depends(internal)):
    sid = S.create_snapshot(stat_date, label, limit_set_id, user)
    res = {}
    for port, f in (("regular", regular), ("tech", tech), ("private", private), ("t2t", t2t)):
        if f is not None and f.filename:
            led = S.upload_port(sid, port, await f.read(), f.filename, user)
            res[port] = {"total": led["total"], "period_end": led["period_end"], "warnings": led["warnings"]}
    return {"snapshot_id": sid, "ports": res}


@r.post("/snapshots/sample")
def sample_snapshot(body: dict = Body(default={}), user=Depends(internal)):
    lid = body.get("limit_set_id")
    if not lid:
        data = L.parse_limit_workbook(M5_SUMMARY_SAMPLE.read_bytes())
        lid = L.save_limit_set(f"导入：{M5_SUMMARY_SAMPLE.name}", f"手工导入:{M5_SUMMARY_SAMPLE.name}", data, user)
    sid = S.create_snapshot(body.get("stat_date", "2026-09-19"), body.get("label", "样表导入"), lid, user)
    for port, fn in SAMPLE_PORTS.items():
        S.upload_port(sid, port, (M5_SAMPLE_DIR / fn).read_bytes(), fn, user)
    return {"snapshot_id": sid, "limit_set_id": lid}


@r.post("/snapshots/{sid}/ports/{port}")
async def upload(sid: int, port: str, file: UploadFile = File(...), user=Depends(internal)):
    led = S.upload_port(sid, port, await file.read(), file.filename, user)
    return {"total": led["total"], "direct": led["direct"], "period_end": led["period_end"], "warnings": led["warnings"]}


@r.post("/snapshots/{sid}/manual-direct")
def manual_direct(sid: int, body: dict = Body(...), user=Depends(internal)):
    v = body.get("value")
    S.set_manual_direct(sid, body["port"], None if v in (None, "") else float(v), user, body.get("reason"))
    return {"ok": True}


@r.post("/snapshots/{sid}/notes")
def notes(sid: int, body: dict = Body(...), user=Depends(internal)):
    S.save_notes(sid, body.get("notes", {}), user)
    return {"ok": True}


@r.post("/snapshots/{sid}/limit-set")
def snap_limit(sid: int, body: dict = Body(...), user=Depends(internal)):
    S.set_limit_set(sid, body["limit_set_id"], user)
    return {"ok": True}


@r.get("/snapshots/{sid}/dashboard")
def dash(sid: int, user=Depends(current_user)):
    REC.ensure_live("m5_snapshot", sid, user)
    if user["role"] == "institution":
        REC.ensure_live("m5_snapshot", sid)  # 已删除快照对机构不可见
    d = S.dashboard(sid, user)
    if user["role"] == "institution":  # 机构用户仅可见本机构行（行级权限钩子），隐藏汇总
        d["summary"] = None
        d["notes"] = {}
        d["alerts"] = []
        d["notes_auto"] = {}
        d["limit_warnings"] = []
        d["ports"] = {p: None for p in d["ports"]}  # 全网端口合计不对机构开放
    return d


@r.get("/snapshots/latest/id")
def latest(user=Depends(current_user)):
    s = db.q1("SELECT id FROM m5_snapshots WHERE deleted_at IS NULL AND archived_at IS NULL ORDER BY stat_date DESC, id DESC LIMIT 1") \
        or db.q1("SELECT id FROM m5_snapshots WHERE deleted_at IS NULL ORDER BY stat_date DESC, id DESC LIMIT 1")
    return {"id": s["id"] if s else None}


@r.get("/snapshots/{sid}/export.xlsx")
def export(sid: int, user=Depends(internal)):
    data, name = S.export_xlsx(sid)
    db.audit(user, "M5", "导出看板", sid, {"filename": name})
    return file_resp(W.xlsx_bytes(data, user), name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@r.get("/rules")
def get_rules(user=Depends(current_user)):
    return S.rules()


@r.put("/rules")
def put_rules(body: dict = Body(...), user=Depends(internal)):
    cur = S.rules()
    for k in ("red", "over", "lag_time", "lag_rate", "swing", "low_hint"):
        if k in body:
            v = float(body[k])
            if not 0 <= v <= 10:
                raise HTTPException(400, f"{k} 超出范围")
            cur[k] = v
    if "direct_entities" in body:
        cur["direct_entities"] = [x.strip() for x in body["direct_entities"] if x.strip()]
    db.set_setting("m5_rules", cur)
    db.audit(user, "M5", "修改预警规则", "", cur)
    return cur
