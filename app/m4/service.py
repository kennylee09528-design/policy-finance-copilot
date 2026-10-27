"""M4 业务服务：数据集、参数版本、方案版本、人工调整留痕。"""
from fastapi import HTTPException

from .. import db
from .calc import DEFAULT_TIERS, compute
from .importer import import_workbook
from .spec import result_meta

LOCKED = ("已上会", "已批复")


# ---------------- 机构主数据（M4/M5 共用） ----------------
def upsert_institutions(rows):
    for r in rows:
        ex = db.q1("SELECT id FROM institutions WHERE full_name=?", (r["name"],))
        if ex:
            db.execute("UPDATE institutions SET is_fixed_quota=?, updated_at=? WHERE id=?",
                       (1 if r.get("fixed") else 0, db.now(), ex["id"]))
        else:
            db.execute("INSERT INTO institutions(full_name,short_name,is_fixed_quota,status,org_code,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,?)",
                       (r["name"], short_name(r["name"]), 1 if r.get("fixed") else 0, "正常", r["name"], db.now(), db.now()))


def short_name(n):
    import re
    m = re.search(r"（(.+?)）", n)
    if n.startswith("示例普惠金融") and m:
        return f"示例普惠（{m.group(1)}）"
    s = re.sub(r"(融资再担保|融资担保|融资担保投资|中小企业融资担保|融资担保股份)?(有限责任公司|股份有限公司|有限公司)$", "", n)
    return s.replace("融资担保投资", "").replace("融资担保", "")[:12] or n


# ---------------- 参数版本 ----------------
def create_params(weights, constants, label, user, note=""):
    v = (db.q1("SELECT MAX(version) v FROM m4_params") or {}).get("v") or 0
    pid = db.execute("INSERT INTO m4_params(version,label,weights,constants,created_by,created_at,note) VALUES(?,?,?,?,?,?,?)",
                     (v + 1, label, db.jdump(weights), db.jdump(constants), user["name"], db.now(), note))
    db.audit(user, "M4", "新建参数版本", f"v{v + 1}", {"weights": weights, "constants": constants, "note": note})
    return pid


def get_params(pid):
    p = db.q1("SELECT * FROM m4_params WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "参数版本不存在")
    p["weights"] = db.jload(p["weights"])
    p["constants"] = db.jload(p["constants"])
    return p


def list_params():
    out = db.q("SELECT * FROM m4_params ORDER BY version DESC")
    for p in out:
        p["weights"] = db.jload(p["weights"])
        p["constants"] = db.jload(p["constants"])
    return out


# ---------------- 数据集 ----------------
def import_dataset(data: bytes, filename, user, prefill_excel_adjust=True):
    payload = import_workbook(data, filename)
    did = db.execute("INSERT INTO m4_datasets(name,source_file,imported_at,imported_by,payload) VALUES(?,?,?,?,?)",
                     (f"{filename} 导入", filename, db.now(), user["name"], db.jdump(payload)))
    upsert_institutions(payload["rows"])
    consts = dict(payload["constants"])
    consts["zxzn_threshold"] = payload["zxzn_threshold"]
    consts["floor"] = 0.5
    consts["mintou_tiers"] = DEFAULT_TIERS
    pid = create_params(payload["weights_from_workbook"], consts, f"自{filename}解析", user,
                        "权重解析自计算表 U 列公式；均值按 L/P/R 列引用的单元格公式求值")
    db.audit(user, "M4", "导入附件2", filename, {"dataset_id": did, "rows": len(payload["rows"]),
                                                "alerts": len(payload["alerts"])})
    sid = create_scheme(did, pid, user, name="导入初始方案（模型测算）", note="X 为模型测算值，未做人工调整")
    if prefill_excel_adjust:
        sid2 = copy_scheme(sid, user, name="附件2口径方案（含原表第三~六次调整）",
                           note="第三次调整值 = 附件2 第六次调整(AC) − 第二次调整(X)，用于复现原表最终授信(AI)")
        for r in payload["rows"]:
            ac, x = r["excel"].get("AC"), r["excel"].get("X")
            if isinstance(ac, (int, float)) and isinstance(x, (int, float)) and ac != x:
                add_adjustment(sid2, r["name"], "third", ac - x,
                               "依据附件2：第三次至第六次调整（人工核定/取整/备案激励）合并导入", user)
        recompute(sid2)
        set_current(sid2, user)
    return {"dataset_id": did, "param_id": pid, "scheme_id": sid, "alerts": payload["alerts"]}


def get_dataset(did):
    d = db.q1("SELECT * FROM m4_datasets WHERE id=?", (did,))
    if not d:
        raise HTTPException(404, "数据集不存在")
    d["payload"] = db.jload(d["payload"])
    return d


INPUT_FIELDS = ["scale", "mintou_prev", "emp", "base_const", "zxzn_raw", "lj_raw", "dn_raw", "pj", "zc_total",
                "mintou_special", "tech_quota", "fixed", "fixed_quota"]


def update_dataset_row(did, name, fields, user, reason):
    """逐一表单填报 / 修改：生成新数据集版本（原数据集保持不变，便于追溯）。"""
    if not reason:
        raise HTTPException(400, "修改基础数据必须填写原因")
    d = get_dataset(did)
    rows = d["payload"]["rows"]
    tgt = next((r for r in rows if r["name"] == name), None)
    if tgt is None:
        tgt = {"row": None, "seq": len(rows) + 1, "name": name, "sources": {}, "notes": ["表单新增"], "excel": {},
               "fixed": False, "v_const": None}
        rows.append(tgt)
    before = {k: tgt.get(k) for k in INPUT_FIELDS}
    for k, v in fields.items():
        if k in INPUT_FIELDS:
            tgt[k] = v
            tgt.setdefault("sources", {})[k] = "表单填报"
            if k == "zc_total":
                tgt["v_const"] = None
    d["payload"].setdefault("edits", []).append({"name": name, "before": before, "after": fields, "by": user["name"],
                                                 "at": db.now(), "reason": reason})
    nid = db.execute("INSERT INTO m4_datasets(name,source_file,imported_at,imported_by,payload) VALUES(?,?,?,?,?)",
                     (f"{d['name']}（表单修订）", d["source_file"], db.now(), user["name"], db.jdump(d["payload"])))
    upsert_institutions([tgt])
    db.audit(user, "M4", "表单修改基础数据", name, {"from_dataset": did, "to_dataset": nid, "fields": fields, "reason": reason})
    return nid


# ---------------- 方案版本 ----------------
def _next_version():
    return ((db.q1("SELECT MAX(version) v FROM m4_schemes") or {}).get("v") or 0) + 1


def create_scheme(did, pid, user, name="", note="", parent_id=None, inputs=None):
    v = _next_version()
    sid = db.execute("INSERT INTO m4_schemes(version,name,dataset_id,param_id,status,parent_id,created_by,created_at,note,inputs) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (v, name or f"方案 v{v}", did, pid, "草稿", parent_id, user["name"], db.now(), note,
                      db.jdump(inputs or {})))
    db.audit(user, "M4", "新建方案版本", f"v{v}", {"dataset_id": did, "param_id": pid, "parent": parent_id})
    recompute(sid)
    if not db.q1("SELECT id FROM m4_schemes WHERE is_current=1"):
        set_current(sid, user)
    return sid


def copy_scheme(sid, user, name="", note="", param_id=None, dataset_id=None):
    s = get_scheme(sid, with_result=False)
    nid = create_scheme(dataset_id or s["dataset_id"], param_id or s["param_id"], user,
                        name=name or f"{s['name']} 副本", note=note or f"复制自 v{s['version']}",
                        parent_id=sid, inputs=s["inputs"])
    with db.tx() as c:  # 复制有效调整（保留原操作人/时间，追加复制说明）
        for a in current_adjustments_list(sid):
            c.execute("INSERT INTO m4_adjustments(scheme_id,institution,kind,value,reason,operator,role,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (nid, a["institution"], a["kind"], a["value"], a["reason"], a["operator"], a["role"], a["created_at"]))
        for a in db.q("SELECT * FROM m4_adjustments WHERE scheme_id=? AND kind IN ('cur_regular','cur_mintou') ORDER BY id", (sid,)):
            c.execute("INSERT INTO m4_adjustments(scheme_id,institution,kind,value,reason,operator,role,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (nid, a["institution"], a["kind"], a["value"], a["reason"], a["operator"], a["role"], a["created_at"]))
    recompute(nid)
    return nid


def get_scheme(sid, with_result=True):
    s = db.q1("SELECT * FROM m4_schemes WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "方案不存在")
    s["inputs"] = db.jload(s["inputs"], {})
    s["status_log"] = db.jload(s["status_log"], [])
    s["result"] = db.jload(s["result"]) if with_result else None
    return s


def list_schemes():
    out = db.q("SELECT id,version,name,dataset_id,param_id,status,parent_id,is_current,created_by,created_at,note,status_log "
               "FROM m4_schemes ORDER BY version DESC")
    for s in out:
        s["status_log"] = db.jload(s["status_log"], [])
        r = db.q1("SELECT result FROM m4_schemes WHERE id=?", (s["id"],))
        res = db.jload(r["result"], {}) or {}
        s["totals"] = res.get("totals")
        s["alert_count"] = len([a for a in res.get("alerts", []) if a["level"] == "error"])
    return out


def current_adjustments_list(sid):
    """每个机构、每类调整取最新一条（完整历史见 adjustment_history）。"""
    rows = db.q("SELECT * FROM m4_adjustments WHERE scheme_id=? ORDER BY id", (sid,))
    latest = {}
    for a in rows:
        latest[(a["institution"], a["kind"])] = a
    return [a for a in latest.values() if a["kind"] in ("third", "mintou") and not (a["kind"] == "mintou" and a["value"] is None)]


CUR_KINDS = {"cur_regular": "目前最新常规业务授信额度", "cur_mintou": "目前最新民间投资授信额度"}


def cur_adjust_sums(sid):
    out = {}
    for a in db.q("SELECT institution,kind,SUM(value) v FROM m4_adjustments WHERE scheme_id=? AND kind IN "
                  "('cur_regular','cur_mintou') GROUP BY institution,kind", (sid,)):
        out.setdefault(a["institution"], {})[a["kind"]] = a["v"] or 0.0
    return out


def cur_log(sid):
    """目前最新额度人工增减记录（时间、机构、调整前、调整后、调整量、原因、操作人），新→旧。"""
    s = get_scheme(sid, with_result=False)
    d = get_dataset(s["dataset_id"])
    base = {r["name"]: {"cur_regular": r.get("apply_regular_tech") or 0.0, "cur_mintou": r.get("mintou_special") or 0.0}
            for r in d["payload"]["rows"]}
    run, out = {}, []
    for a in db.q("SELECT * FROM m4_adjustments WHERE scheme_id=? AND kind IN ('cur_regular','cur_mintou') ORDER BY id", (sid,)):
        k = (a["institution"], a["kind"])
        before = run.get(k, base.get(a["institution"], {}).get(a["kind"], 0.0))
        after = before + (a["value"] or 0.0)
        run[k] = after
        out.append({"id": a["id"], "time": a["created_at"], "institution": a["institution"], "kind": a["kind"],
                    "field": CUR_KINDS[a["kind"]], "before": before, "after": after, "delta": a["value"],
                    "reason": a["reason"], "operator": a["operator"]})
    return out[::-1]


def add_cur_adjustment(sid, inst, kind, delta, reason, user):
    s = get_scheme(sid, with_result=False)
    _check_editable(s)
    if kind not in CUR_KINDS:
        raise HTTPException(400, "未知调整类型")
    if not reason or not str(reason).strip():
        raise HTTPException(400, "调整原因为必填项")
    try:
        delta = float(delta)
    except (TypeError, ValueError):
        raise HTTPException(400, "调整量须为数字（万元，正数上调、负数下调）")
    if delta == 0:
        raise HTTPException(400, "调整量不能为 0")
    names = {r["name"] for r in get_dataset(s["dataset_id"])["payload"]["rows"]}
    if inst not in names:
        raise HTTPException(404, "方案中没有该机构")
    db.execute("INSERT INTO m4_adjustments(scheme_id,institution,kind,value,reason,operator,role,created_at) VALUES(?,?,?,?,?,?,?,?)",
               (sid, inst, kind, delta, reason.strip(), user["name"], user["role"], db.now()))
    db.audit(user, "M4", "调整" + CUR_KINDS[kind], inst, {"scheme_id": sid, "delta": delta, "reason": reason})
    return recompute(sid)


def current_adjustments(sid):
    out = {}
    for a in current_adjustments_list(sid):
        out.setdefault(a["institution"], {})[a["kind"]] = a
    return out


def adjustment_history(sid):
    return db.q("SELECT * FROM m4_adjustments WHERE scheme_id=? ORDER BY id DESC", (sid,))


def _check_editable(s):
    if s["status"] in LOCKED:
        raise HTTPException(409, f"方案已标注「{s['status']}」，不可修改；请复制为新版本后调整")


def add_adjustment(sid, inst, kind, value, reason, user):
    s = get_scheme(sid, with_result=False)
    _check_editable(s)
    if not reason or not str(reason).strip():
        raise HTTPException(400, "调整原因为必填项")
    if kind not in ("third", "mintou"):
        raise HTTPException(400, "未知调整类型")
    db.execute("INSERT INTO m4_adjustments(scheme_id,institution,kind,value,reason,operator,role,created_at) VALUES(?,?,?,?,?,?,?,?)",
               (sid, inst, kind, value, reason.strip(), user["name"], user["role"], db.now()))
    db.audit(user, "M4", "人工调整" if kind == "third" else "民投调整覆盖", inst,
             {"scheme_id": sid, "value": value, "reason": reason})


def set_mintou_inputs(sid, inst, q3_base, balance, rate, user):
    s = get_scheme(sid, with_result=False)
    _check_editable(s)
    inputs = s["inputs"]
    inputs.setdefault("mintou", {})[inst] = {"q3_base": q3_base, "balance": balance, "rate": rate}
    db.execute("UPDATE m4_schemes SET inputs=? WHERE id=?", (db.jdump(inputs), sid))
    db.audit(user, "M4", "填写民投完成率输入", inst, {"scheme_id": sid, "q3_base": q3_base, "balance": balance, "rate": rate})
    return recompute(sid)


def recompute(sid):
    s = get_scheme(sid, with_result=False)
    d = get_dataset(s["dataset_id"])
    p = get_params(s["param_id"])
    res = compute(d["payload"]["rows"], p, current_adjustments(sid), s["inputs"].get("mintou", {}), cur_adjust_sums(sid))
    res["alerts"] = d["payload"].get("alerts", []) + res["alerts"]
    res["param"] = {"id": p["id"], "version": p["version"], "weights": p["weights"],
                    "constants": {k: v for k, v in p["constants"].items() if not k.endswith("_formula")}}
    excel = {r["name"]: r.get("excel", {}) for r in d["payload"]["rows"]}
    for r in res["rows"]:
        e = excel.get(r["name"], {})
        r["excel_W"], r["excel_X"], r["excel_AC"], r["excel_AI"] = e.get("W"), e.get("X"), e.get("AC"), e.get("AI")
        r["excel_Z"], r["excel_AA"], r["excel_AB"] = e.get("Z"), e.get("AA"), e.get("AB")
        r["excel_C"], r["excel_D"] = e.get("C"), e.get("D")
    res["source"] = {"file": d["source_file"], "imported_at": d["imported_at"], "mode": d["payload"].get("mode", "workbook"),
                     "sheet_map": d["payload"].get("sheet_map")}
    res["meta"] = result_meta(p, s["dataset_id"])
    db.execute("UPDATE m4_schemes SET result=? WHERE id=?", (db.jdump(res), sid))
    return res


def set_status(sid, status, user, remark=""):
    if status not in ("草稿", "已上会", "已批复"):
        raise HTTPException(400, "状态只能是 草稿/已上会/已批复")
    s = get_scheme(sid, with_result=False)
    if s["status"] == "已批复" and status != "已批复":
        raise HTTPException(409, "已批复方案不可撤回")
    res = db.jload(db.q1("SELECT result FROM m4_schemes WHERE id=?", (sid,))["result"], {})
    if status != "草稿" and any(a["type"] == "权重和≠1" for a in res.get("alerts", [])):
        raise HTTPException(409, "权重和≠1，禁止标注上会/批复")
    log = s["status_log"] + [{"from": s["status"], "to": status, "by": user["name"], "at": db.now(), "remark": remark}]
    db.execute("UPDATE m4_schemes SET status=?, status_log=? WHERE id=?", (status, db.jdump(log), sid))
    db.audit(user, "M4", "方案状态变更", f"v{s['version']}", {"from": s["status"], "to": status, "remark": remark})


def set_current(sid, user):
    with db.tx() as c:
        c.execute("UPDATE m4_schemes SET is_current=0")
        c.execute("UPDATE m4_schemes SET is_current=1 WHERE id=?", (sid,))
    db.audit(user, "M4", "设为当前方案", sid)


def rollback(sid, user):
    """回滚：以历史版本为基础生成新草稿并设为当前，历史版本本身不被修改。"""
    s = get_scheme(sid, with_result=False)
    nid = copy_scheme(sid, user, name=f"回滚自 v{s['version']}", note=f"回滚至 v{s['version']}（{s['name']}）")
    set_current(nid, user)
    db.audit(user, "M4", "方案回滚", f"v{s['version']}", {"new_scheme": nid})
    return nid


def compare(a, b):
    sa, sb = get_scheme(a), get_scheme(b)
    ra = {r["name"]: r for r in sa["result"]["rows"]}
    rb = {r["name"]: r for r in sb["result"]["rows"]}
    names = list(dict.fromkeys(list(ra) + list(rb)))
    keys = ["W", "X", "third", "mintou_adj", "regular_final", "mintou_special", "final"]
    rows = []
    for n in names:
        x, y = ra.get(n, {}), rb.get(n, {})
        row = {"name": n, "a": {k: x.get(k) for k in keys}, "b": {k: y.get(k) for k in keys}}
        row["diff"] = {k: (y.get(k) or 0) - (x.get(k) or 0) for k in keys}
        row["changed"] = any(abs(v) > 1e-6 for v in row["diff"].values())
        rows.append(row)
    return {"a": {k: sa[k] for k in ("id", "version", "name", "status")}, "b": {k: sb[k] for k in ("id", "version", "name", "status")},
            "rows": rows, "totals": {"a": sa["result"]["totals"], "b": sb["result"]["totals"]},
            "param_diff": {"a": sa["result"]["param"], "b": sb["result"]["param"]}}
