from fastapi import APIRouter, Body, Depends, HTTPException

from . import db
from .auth import ROLES, current_user, require_internal

r = APIRouter(prefix="/api", tags=["通用"])


@r.get("/me")
def me(user=Depends(current_user)):
    return {**user, "role_name": "再担保机构用户（全机构可见）" if user.get("all_access") else ROLES[user["role"]]}


@r.get("/institutions")
def institutions(user=Depends(current_user)):
    rows = db.q("SELECT * FROM institutions ORDER BY id")
    if user["role"] == "institution":
        rows = [x for x in rows if x["full_name"] == user["org"]]
    return rows


@r.put("/institutions/{iid}")
def edit_inst(iid: int, body: dict = Body(...), user=Depends(current_user)):
    require_internal(user)
    allowed = ["short_name", "city", "is_holding", "is_fixed_quota", "reg_capital", "reg_capital_adj", "status", "org_code"]
    sets = {k: body[k] for k in allowed if k in body}
    if not sets:
        raise HTTPException(400, "无可修改字段")
    db.execute(f"UPDATE institutions SET {', '.join(k + '=?' for k in sets)}, updated_at=? WHERE id=?",
               (*sets.values(), db.now(), iid))
    db.audit(user, "主数据", "修改机构", iid, sets)
    return {"ok": True}


@r.get("/audit")
def audit(user=Depends(current_user)):
    require_internal(user)
    return db.q("SELECT * FROM audit_log ORDER BY id DESC LIMIT 500")


@r.get("/home")
def home(user=Depends(current_user)):
    """工作台首页：一条数据主线（采集→沉淀→生产→核算→监控）的实时数字。"""
    L = "deleted_at IS NULL AND archived_at IS NULL"
    inst = user["role"] == "institution"
    s = db.q1(f"SELECT id,version,name,status,result FROM m4_schemes WHERE is_current=1 AND deleted_at IS NULL")
    m4 = None
    if s and not inst:
        t = (db.jload(s["result"], {}) or {}).get("totals") or {}
        m4 = {"id": s["id"], "version": s["version"], "name": s["name"], "status": s["status"], "sumFinal": t.get("sumFinal"),
              "sumRegular": t.get("sumRegular"), "count": t.get("count"),
              "adjustments": db.q1("SELECT COUNT(*) n FROM m4_adjustments WHERE scheme_id=?", (s["id"],))["n"],
              "versions": db.q1(f"SELECT COUNT(*) n FROM m4_schemes WHERE {L}")["n"]}
    snap = db.q1(f"SELECT id,stat_date FROM m5_snapshots WHERE {L} ORDER BY stat_date DESC, id DESC LIMIT 1")
    m5 = None
    if snap:
        m5 = dict(snap)
        try:
            from .m5 import service as S5
            d = S5.dashboard(snap["id"], user)
            reg = (d.get("summary") or {}).get("regular") or {}
            m5.update(rate=(reg.get("total") or {}).get("rate") if not inst else None, time_progress=d.get("time_progress"),
                      alerts=0 if inst else len(d.get("alerts") or []),
                      red=sum(1 for r in d["rows"] if any(w.get("level") in ("red", "over") for w in r.get("warn") or [])),
                      yellow=sum(1 for r in d["rows"] if any(w.get("level") == "yellow" for w in r.get("warn") or [])),
                      institutions=len(d["rows"]))
        except Exception as e:  # noqa: BLE001 首页不因单模块异常整体失败
            m5["error"] = str(e)[:100]
    out = {"m4": m4, "m5": m5, "institutions": db.q1("SELECT COUNT(*) n FROM institutions WHERE COALESCE(all_access,0)=0")["n"], "role": user["role"]}
    b = db.q1(f"SELECT id, brief_date, version, stats FROM m2_briefs WHERE status='已发布' AND {L} ORDER BY brief_date DESC, version DESC LIMIT 1")
    out["m2"] = {"latest": {"id": b["id"], "date": b["brief_date"], "items": (db.jload(b["stats"], {}) or {}).get("items")} if b else None,
                 "published": db.q1(f"SELECT COUNT(*) n FROM m2_briefs WHERE status='已发布' AND {L}")["n"]}
    if not inst:
        run = db.q1(f"SELECT started_at, status FROM m1_runs WHERE {L} ORDER BY id DESC LIMIT 1")
        from .m1.validity import expiring_count
        out["m1"] = {"items": db.q1("SELECT COUNT(*) n FROM m1_items WHERE duplicate_of IS NULL")["n"],
                     "authority": db.q1("SELECT COUNT(*) n FROM m1_items WHERE duplicate_of IS NULL AND level IN ('A1','A2')")["n"],
                     "week": db.q1("SELECT COUNT(*) n FROM m1_items WHERE duplicate_of IS NULL AND collected_at >= datetime('now','localtime','-7 days')")["n"],
                     "expiring": expiring_count(),
                     "last_run": run}
        out["m2"]["drafts"] = db.q1(f"SELECT COUNT(*) n FROM m2_briefs WHERE status!='已发布' AND {L}")["n"]
        out["m3"] = {"tasks": db.q1(f"SELECT COUNT(*) n FROM m3_tasks WHERE {L}")["n"],
                     "final": db.q1(f"SELECT COUNT(*) n FROM m3_tasks WHERE finalized_at IS NOT NULL AND {L}")["n"],
                     "citations": db.q1("SELECT COUNT(*) n FROM m3_citations")["n"],
                     "style": db.q1("SELECT COUNT(*) n FROM m3_style_guide WHERE enabled=1")["n"]}
        out["ppt"] = {"jobs": db.q1(f"SELECT COUNT(*) n FROM ppt_jobs WHERE {L}")["n"],
                      "files": db.q1("SELECT COUNT(*) n FROM ppt_files f JOIN ppt_jobs j ON j.id=f.job_id WHERE j.deleted_at IS NULL")["n"]}
    return out


# ---------------- 执行记录：归档 / 删除 / 回收站（跨模块） ----------------
@r.post("/records/{kind}/{action}")
def record_action(kind: str, action: str, body: dict = Body(...), user=Depends(current_user)):
    from . import records
    return records.act(kind, action, body.get("ids") or ([body["id"]] if body.get("id") else []), user, bool(body.get("force")))


@r.get("/records/{kind}/{rid}/refs")
def record_refs(kind: str, rid: int, user=Depends(current_user)):
    from . import records
    require_internal(user)
    records._kind(kind)
    b, w = records.refs(kind, rid)
    return {"blockers": b, "warnings": w}


@r.get("/records/bin")
def record_bin(user=Depends(current_user)):
    from . import records
    return records.recycle_bin(user)


@r.get("/exports")
def exports(view: str = "", user=Depends(current_user)):
    """导出历史：内部用户看全部，机构用户仅看自己的导出。"""
    from . import records
    if user["role"] == "institution":
        rows = db.q("SELECT * FROM export_log WHERE username=? ORDER BY id DESC LIMIT 2000", (user.get("username"),))
        view = ""
    else:
        rows = db.q("SELECT * FROM export_log ORDER BY id DESC LIMIT 2000")
    return records.filter_rows("export", rows, view, user)[:500]


@r.post("/exports/log")
def export_log(body: dict = Body(...), user=Depends(current_user)):
    """浏览器打印 / 另存 PDF 类导出（M2 简报 PDF、M5 看板 PDF 快照）的留痕与导出历史登记。"""
    module = str(body.get("module") or "")[:10]
    if module not in ("M2", "M5", "M3", "M4", "PPT"):
        raise HTTPException(400, "模块无效")
    if module != "M2" and module != "M5":
        require_internal(user)
    from . import watermark
    db.audit(user, module, "导出 PDF（打印）", str(body.get("target") or "")[:50], {"filename": str(body.get("filename") or "")[:120]})
    return {"ok": True, "watermark": watermark.info(user)}
