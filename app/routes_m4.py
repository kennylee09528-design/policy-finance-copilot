from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from . import db
from . import records as REC
from . import watermark as W
from .auth import current_user, require_internal
from .config import M4_SAMPLE
from .m4 import export, service
from .m4.calc import WEIGHT_TOL, compute
from .m4.spec import calc_module_hash, load_spec
from .m4.xlsxformula import xround

r = APIRouter(prefix="/api/m4", tags=["M4 机构授信管理"])


def internal(user=Depends(current_user)):
    require_internal(user)
    return user


def file_resp(data, name, mime):
    return Response(data, media_type=mime, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@r.post("/import")
async def import_xlsx(file: UploadFile = File(...), prefill: bool = Form(True), user=Depends(internal)):
    data = await file.read()
    try:
        return service.import_dataset(data, file.filename, user, prefill)
    except ValueError as e:
        raise HTTPException(400, str(e))


@r.post("/import-sample")
def import_sample(user=Depends(internal)):
    return service.import_dataset(M4_SAMPLE.read_bytes(), M4_SAMPLE.name, user, True)


@r.get("/datasets")
def datasets(view: str = "", user=Depends(internal)):
    return REC.filter_rows("m4_dataset", db.q("SELECT id,name,source_file,imported_at,imported_by,verified FROM m4_datasets ORDER BY id DESC"), view, user)


@r.get("/datasets/{did}")
def dataset(did: int, user=Depends(internal)):
    return service.get_dataset(did)


@r.post("/datasets/{did}/verify")
def verify(did: int, verified: bool = Body(..., embed=True), user=Depends(internal)):
    db.execute("UPDATE m4_datasets SET verified=? WHERE id=?", (1 if verified else 0, did))
    db.audit(user, "M4", "标记核备", did, {"verified": verified})
    return {"ok": True}


@r.post("/datasets/{did}/rows")
def edit_row(did: int, body: dict = Body(...), user=Depends(internal)):
    """表单填报/修改单个机构基础数据，生成新数据集版本；可选同时基于新数据集复制当前方案。"""
    nid = service.update_dataset_row(did, body["name"], body.get("fields", {}), user, body.get("reason"))
    out = {"dataset_id": nid}
    if body.get("scheme_id"):
        out["scheme_id"] = service.copy_scheme(body["scheme_id"], user, name="基础数据修订后方案",
                                               note=f"数据集#{nid}：{body.get('reason')}", dataset_id=nid)
    return out


@r.get("/params")
def params(user=Depends(internal)):
    return service.list_params()


@r.post("/params")
def new_params(body: dict = Body(...), user=Depends(internal)):
    w = {k: float(v) for k, v in body["weights"].items()}
    if abs(sum(w.values()) - 1) > WEIGHT_TOL:
        raise HTTPException(400, f"权重合计为 {sum(w.values()):.4f}，应调整为合计=1（容差 ±{WEIGHT_TOL}）")
    base = service.get_params(body["base_id"]) if body.get("base_id") else None
    consts = dict(base["constants"]) if base else {}
    consts.update({k: v for k, v in (body.get("constants") or {}).items() if v is not None})
    pid = service.create_params(w, consts, body.get("label") or "手工调整参数", user, body.get("note", ""))
    out = {"param_id": pid}
    if body.get("scheme_id"):
        out["scheme_id"] = service.copy_scheme(body["scheme_id"], user, name=f"参数 v{service.get_params(pid)['version']} 测算",
                                               note=body.get("note") or "参数调整后重新测算", param_id=pid)
    return out


@r.get("/schemes")
def schemes(view: str = "", user=Depends(internal)):
    return REC.filter_rows("m4_scheme", service.list_schemes(), view, user)


@r.get("/schemes/current")
def current(user=Depends(internal)):
    s = db.q1("SELECT id FROM m4_schemes WHERE is_current=1")
    if not s:
        return None
    return scheme(s["id"], user)


@r.get("/schemes/{sid}")
def scheme(sid: int, user=Depends(internal)):
    REC.ensure_live("m4_scheme", sid, user)
    s = service.get_scheme(sid)
    s["history"] = service.adjustment_history(sid)
    return s


@r.post("/schemes/{sid}/copy")
def copy(sid: int, body: dict = Body(default={}), user=Depends(internal)):
    return {"scheme_id": service.copy_scheme(sid, user, body.get("name", ""), body.get("note", ""))}


@r.post("/schemes/{sid}/adjust")
def adjust(sid: int, body: dict = Body(...), user=Depends(internal)):
    v = body.get("value")
    service.add_adjustment(sid, body["institution"], body.get("kind", "third"), None if v in (None, "") else float(v),
                           body.get("reason", ""), user)
    return service.recompute(sid)


@r.post("/schemes/{sid}/cur-adjust")
def cur_adjust(sid: int, body: dict = Body(...), user=Depends(internal)):
    """人工上调/下调「目前最新常规 / 民间投资授信额度」：delta 为增减量（万元），原因必填。"""
    REC.ensure_live("m4_scheme", sid, user)
    service.add_cur_adjustment(sid, body.get("institution"), body.get("kind"), body.get("delta"), body.get("reason", ""), user)
    return {"ok": True, "log": service.cur_log(sid)[:1]}


@r.get("/schemes/{sid}/cur-log")
def cur_log(sid: int, user=Depends(internal)):
    REC.ensure_live("m4_scheme", sid, user)
    return service.cur_log(sid)


@r.get("/schemes/{sid}/cur-log.xlsx")
def cur_log_xlsx(sid: int, user=Depends(internal)):
    REC.ensure_live("m4_scheme", sid, user)
    data, name = export.cur_log_xlsx(sid)
    db.audit(user, "M4", "导出授信额度调整记录", sid, {"filename": name})
    return file_resp(W.xlsx_bytes(data, user), name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@r.post("/schemes/{sid}/preview")
def preview(sid: int, body: dict = Body(default={}), user=Depends(internal)):
    """权重/常量即时重算（不保存）：返回各机构 U、X、AC 及权重合计/归一提示。"""
    s = service.get_scheme(sid, with_result=False)
    d = service.get_dataset(s["dataset_id"])
    p = service.get_params(s["param_id"])
    w = {k: float(body.get("weights", {}).get(k, v)) for k, v in p["weights"].items()}
    consts = dict(p["constants"])
    consts.update({k: float(v) for k, v in (body.get("constants") or {}).items() if v not in (None, "")})
    if isinstance(body.get("base_consts"), dict):
        consts["base_consts"] = {k: float(v) for k, v in body["base_consts"].items() if v not in (None, "")}
    res = compute(d["payload"]["rows"], {"weights": w, "constants": consts}, service.current_adjustments(sid),
                  s["inputs"].get("mintou", {}), service.cur_adjust_sums(sid))
    return {"totals": res["totals"], "alerts": [a for a in res["alerts"] if a["type"] in ("权重和≠1", "权重和容差")],
            "rows": [{k: x.get(k) for k in ("name", "fixed", "U", "W", "X", "AB", "AC")} for x in res["rows"]]}


@r.post("/schemes/{sid}/mintou")
def mintou(sid: int, body: dict = Body(...), user=Depends(internal)):
    f = lambda k: None if body.get(k) in (None, "") else float(body[k])  # noqa: E731
    return service.set_mintou_inputs(sid, body["institution"], f("q3_base"), f("balance"), f("rate"), user)


@r.post("/schemes/{sid}/status")
def status(sid: int, body: dict = Body(...), user=Depends(internal)):
    service.set_status(sid, body["status"], user, body.get("remark", ""))
    return {"ok": True}


@r.post("/schemes/{sid}/current")
def make_current(sid: int, user=Depends(internal)):
    service.set_current(sid, user)
    return {"ok": True}


@r.post("/schemes/{sid}/rollback")
def rollback(sid: int, user=Depends(internal)):
    return {"scheme_id": service.rollback(sid, user)}


@r.get("/compare")
def compare(a: int, b: int, user=Depends(internal)):
    return service.compare(a, b)


@r.get("/formula-spec")
def formula_spec(user=Depends(internal)):
    """当前公式口径文件（与某次测算结果里的 meta 对照）。"""
    spec = load_spec()
    return {**spec, "calc_module_hash": calc_module_hash()}


@r.get("/schemes/{sid}/formula-spec.xlsx")
def export_formula_spec(sid: int, user=Depends(internal)):
    REC.ensure_live("m4_scheme", sid, user)
    data, name = export.formula_spec_xlsx(sid)
    db.audit(user, "M4", "导出口径说明", sid, {"filename": name})
    return file_resp(W.xlsx_bytes(data, user), name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@r.get("/schemes/{sid}/export.xlsx")
def export_xlsx(sid: int, user=Depends(internal)):
    data, name = export.scheme_xlsx(sid)
    db.audit(user, "M4", "导出测算表", sid, {"filename": name})
    return file_resp(W.xlsx_bytes(data, user), name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@r.get("/schemes/{sid}/qingshi")
def qingshi_preview(sid: int, base: int | None = None, user=Depends(internal)):
    return export.qingshi_defaults(sid, base)


@r.post("/schemes/{sid}/qingshi.docx")
def qingshi(sid: int, body: dict = Body(default={}), user=Depends(internal)):
    data, name = export.qingshi_docx(sid, body.get("paragraphs"), body.get("base"))
    db.audit(user, "M4", "导出请示Word", sid, {"base": body.get("base"), "filename": name})
    return file_resp(W.docx_bytes(data, user), name, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@r.get("/audit")
def audit(user=Depends(internal)):
    return db.q("SELECT * FROM audit_log WHERE module='M4' ORDER BY id DESC LIMIT 300")


# ---------------- 单机构自测（对机构开放：不返回任何机构名称/明细，只返回额度池汇总） ----------------
selftest = APIRouter(prefix="/api/selftest", tags=["单机构自测"])


@selftest.get("/pool")
def pool():
    s = db.q1("SELECT id,result FROM m4_schemes WHERE is_current=1")
    if not s:
        return {"available": False}
    res = db.jload(s["result"])
    return {"available": True, "sumW": res["totals"]["sumW"], "sumU": res["totals"]["sumU"],
            "pool_count": res["totals"]["pool_count"], "weights": res["param"]["weights"],
            "constants": {k: res["param"]["constants"].get(k) for k in ("emp_avg", "lj_avg", "dn_avg", "zxzn_threshold", "floor")}}


@selftest.post("/calc")
def selftest_calc(body: dict = Body(...)):
    p = pool()
    if not p["available"]:
        raise HTTPException(409, "尚未发布测算方案，暂不能自测")
    f = lambda k: None if body.get(k) in (None, "") else float(body[k])  # noqa: E731
    row = {"name": "本机构", "scale": f("scale"), "emp": f("emp"), "base_const": 0.0, "zxzn_raw": f("zxzn"),
           "lj_raw": f("lj"), "dn_raw": f("dn"), "pj": f("pj"), "zc_total": f("zc") or 0, "mintou_prev": f("mintou") or 0, "v_const": None}
    out = compute([row], {"weights": p["weights"], "constants": p["constants"]})["rows"][0]
    if out["U"] is None:
        raise HTTPException(400, "请填写完整的规模、就业人数、支小支农占比、代偿率与评价分")
    keys = ["J", "K", "L", "M", "N", "O", "P", "Q", "R", "T", "U", "V", "W"]
    return {**{k: out[k] for k in keys},
            "note": "以上结果仅供机构自测参考，最终授信以批复为准。"}
