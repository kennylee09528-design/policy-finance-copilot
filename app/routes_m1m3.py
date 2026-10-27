"""M1 搜索驱动采集 + M3 公开资料联网检索与《引用来源登记表》。"""
import io
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response

from . import db
from .auth import current_user, require_internal
from .m1 import collector, config as C
from .m1.classify import classify
from .m1 import insights as INS
from .m1 import validity as V
from .search import service as S

r = APIRouter(prefix="/api", tags=["M1/M3 联网检索"])


def internal(user=Depends(current_user)):
    require_internal(user)
    return user


# ---------------- M1 ----------------
@r.get("/m1/config")
def m1_config(user=Depends(internal)):
    cfg = C.get()
    plan, info = collector.plan_queries(cfg)
    splan, sinfo = collector.plan_queries_scheduled(cfg)
    return {"config": cfg, "next_plan": plan[:200], "plan_info": info, "plan_total": len(plan),
            "scheduled_next_plan": splan[:50], "scheduled_plan_info": sinfo, "scheduled_plan_total": len(splan)}


@r.post("/m1/run")
def m1_run(user=Depends(internal)):
    S._get()  # 无可用搜索供应商时直接提示
    try:
        collector.run_async("手动", user)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True}


@r.get("/m1/runs")
def m1_runs(view: str = "", user=Depends(internal)):
    from .records import filter_rows
    rows = filter_rows("m1_run", db.q("SELECT * FROM m1_runs ORDER BY id DESC LIMIT 1000"), view, user)[:50]
    for x in rows:
        x["stats"] = db.jload(x["stats"], {})
    return {"runs": rows, "running": collector._lock.locked()}


@r.get("/m1/items")
def m1_items(level: str = "", layer: str = "", region: str = "", kw: str = "", validity: str = "", show_dup: bool = False, limit: int = 300, user=Depends(internal)):
    sql, a = ("SELECT id,url,title,publisher,level,layer,region,topic,pub_date,snippet,summary,fetch_status,duplicate_of,level_manual,collected_at,"
              "validity_status,effective_date,expiry_date,abolished_at,doc_no FROM m1_items WHERE 1=1", [])
    if level:
        sql += " AND level IN (%s)" % ",".join("?" * len(level.split(",")))
        a += level.split(",")
    for k, v in (("layer", layer), ("region", region)):
        if v:
            sql += f" AND {k}=?"
            a.append(v)
    if kw:
        sql += " AND (title LIKE ? OR snippet LIKE ? OR content LIKE ? OR publisher LIKE ?)"
        a += [f"%{kw}%"] * 4
    sql += V.filter_sql(validity, a)
    if not show_dup:
        sql += " AND duplicate_of IS NULL"
    sql += " ORDER BY COALESCE(pub_date,'') DESC, id DESC LIMIT ?"
    a.append(min(limit, 1000))
    stats = db.q("SELECT level, COUNT(*) n FROM m1_items WHERE duplicate_of IS NULL GROUP BY level")
    items = db.q(sql, a)
    cc = INS.cited_counts([x["id"] for x in items])
    for x in items:
        x["cited"] = cc.get(x["id"], 0)
        V.annotate(x)
    return {"items": items, "stats": {x["level"]: x["n"] for x in stats}}


@r.get("/m1/expiring")
def m1_expiring(limit: int = 100, user=Depends(internal)):
    """现行有效且失效日期早于今天起 90 天的条目（含已过期但仍标现行有效）。"""
    return V.expiring_list(max(1, min(limit, 500)))


@r.get("/m1/semantic")
def m1_semantic(q: str, k: int = 20, user=Depends(internal)):
    return INS.semantic_search(q, max(1, min(k, 50)), user)


@r.post("/m1/semantic/answer")
def m1_semantic_answer(body: dict = Body(...), user=Depends(internal)):
    q = (body.get("q") or "").strip()
    if not q:
        raise HTTPException(400, "请输入问题")
    return INS.rag_answer(q[:300], user)


@r.get("/m1/sources/health")
def m1_health(user=Depends(internal)):
    return INS.source_health()


@r.get("/m1/review")
def m1_review_queue(user=Depends(internal)):
    return INS.review_queue()


@r.post("/m1/items/{iid}/review")
def m1_review(iid: int, body: dict = Body(...), user=Depends(internal)):
    return INS.review(iid, body, user)


@r.get("/m1/items/{iid}/citations")
def m1_cited(iid: int, user=Depends(internal)):
    return INS.citations_of(iid)


@r.get("/m1/dedup/sample")
def m1_dedup(n: int = 10, user=Depends(internal)):
    return INS.dedup_sample(max(1, min(n, 50)))


@r.post("/m1/dedup/{iid}")
def m1_dedup_judge(iid: int, body: dict = Body(...), user=Depends(internal)):
    return INS.dedup_judge(iid, body.get("verdict"), user)


@r.get("/m1/items/{iid}")
def m1_item(iid: int, user=Depends(internal)):
    it = db.q1("SELECT * FROM m1_items WHERE id=?", (iid,))
    if not it:
        raise HTTPException(404, "条目不存在")
    return V.annotate(it)


@r.put("/m1/items/{iid}/validity")
def m1_validity(iid: int, body: dict = Body(...), user=Depends(internal)):
    """人工核定效力状态与日期。不自动抽取失效日。"""
    return V.update(iid, body, user)


@r.put("/m1/items/{iid}")
def m1_item_edit(iid: int, body: dict = Body(...), user=Depends(internal)):
    if body.get("level") not in C.LEVELS:
        raise HTTPException(400, "来源等级无效")
    db.execute("UPDATE m1_items SET level=?, level_manual=1 WHERE id=?", (body["level"], iid))
    db.audit(user, "M1", "人工修改来源等级", iid, {"level": body["level"], "reason": body.get("reason", "")})
    return {"ok": True}


@r.post("/m1/items/{iid}/refetch")
def m1_refetch(iid: int, user=Depends(internal)):
    from .m1.fetch import fetch
    it = m1_item(iid, user)
    try:
        f = fetch(it["url"])
    except Exception as e:  # noqa: BLE001
        db.execute("UPDATE m1_items SET fetch_status=? WHERE id=?", (f"抓取失败：{str(e)[:120]}", iid))
        raise HTTPException(502, f"抓取失败：{e}") from e
    db.execute("UPDATE m1_items SET content=?, pub_date=COALESCE(pub_date,?), fetch_status=?, fetched_at=? WHERE id=?",
               (f["text"], f["date"], "已抓取" if f["kind"] == "html" else "PDF（未解析正文）", db.now(), iid))
    return m1_item(iid, user)


@r.post("/m1/items/{iid}/summarize")
def m1_summarize(iid: int, user=Depends(internal)):
    if not collector._summarize(iid):
        raise HTTPException(400, "未选择 M1 摘要模型，或条目无正文")
    return m1_item(iid, user)


# ---------------- M3：公开资料联网检索 + 引用登记 ----------------
@r.post("/m3/search")
def m3_search(body: dict = Body(...), user=Depends(internal)):
    cfg = C.get()
    res = S.search(body.get("query", ""), user, int(body.get("max_results") or 10), body.get("time_range") or "none", purpose="M3")
    for x in res:
        c = classify(x["url"], cfg) or {}
        x["level"], x["publisher"] = c.get("level", "C2"), c.get("publisher", x.get("site"))
    return {"results": res}


CIT_FIELDS = ["doc_name", "title", "source_name", "level", "location", "excerpt", "url", "pub_date", "verify_status", "query", "provider"]
VERIFY = ["已核实", "存疑（待核实）", "未找到出处"]


@r.get("/m3/citations")
def cit_list(doc_name: str = "", user=Depends(internal)):
    if doc_name:
        return db.q("SELECT * FROM m3_citations WHERE doc_name=? ORDER BY id", (doc_name,))
    return db.q("SELECT * FROM m3_citations ORDER BY id DESC LIMIT 500")


@r.post("/m3/citations")
def cit_add(body: dict = Body(...), user=Depends(internal)):
    if not body.get("title") or not body.get("url"):
        raise HTTPException(400, "网页类引用须有标题与链接")
    v = {k: body.get(k) for k in CIT_FIELDS}
    v["verify_status"] = v["verify_status"] if v["verify_status"] in VERIFY else "存疑（待核实）"
    cid = db.execute(f"INSERT INTO m3_citations({','.join(CIT_FIELDS)},created_by,created_at,updated_at) VALUES({','.join('?' * len(CIT_FIELDS))},?,?,?)",
                     (*v.values(), user["name"], db.now(), db.now()))
    db.audit(user, "M3", "登记引用出处", cid, {"title": v["title"], "url": v["url"]})
    return {"id": cid}


@r.put("/m3/citations/{cid}")
def cit_edit(cid: int, body: dict = Body(...), user=Depends(internal)):
    sets = {k: body[k] for k in CIT_FIELDS if k in body}
    if "verify_status" in sets and sets["verify_status"] not in VERIFY:
        raise HTTPException(400, "核验状态无效")
    if sets:
        db.execute(f"UPDATE m3_citations SET {', '.join(k + '=?' for k in sets)}, updated_at=? WHERE id=?", (*sets.values(), db.now(), cid))
        db.audit(user, "M3", "修改引用登记", cid, sets)
    return {"ok": True}


@r.delete("/m3/citations/{cid}")
def cit_del(cid: int, user=Depends(internal)):
    db.execute("DELETE FROM m3_citations WHERE id=?", (cid,))
    db.audit(user, "M3", "删除引用登记", cid)
    return {"ok": True}


@r.get("/m3/citations/export.xlsx")
def cit_export(doc_name: str = "", user=Depends(internal)):
    from openpyxl import Workbook
    rows = cit_list(doc_name, user)
    wb = Workbook()
    ws = wb.active
    ws.title = "引用来源登记表"
    ws.append(["序号", "所属稿件", "来源名称", "来源类型", "出处位置", "原文摘录", "链接", "发布日期", "核验状态", "检索词", "登记人", "登记时间"])
    for i, x in enumerate(rows, 1):
        ws.append([i, x["doc_name"], x["source_name"] or x["title"], x["level"], x["location"], x["excerpt"], x["url"], x["pub_date"],
                   x["verify_status"], x["query"], x["created_by"], x["created_at"]])
    bio = io.BytesIO()
    wb.save(bio)
    db.audit(user, "M3", "导出引用来源登记表", doc_name or "全部", {"filename": "引用来源登记表.xlsx"})
    from .watermark import xlsx_bytes
    return Response(xlsx_bytes(bio.getvalue(), user), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('引用来源登记表.xlsx')}"})
