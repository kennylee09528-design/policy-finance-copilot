"""政策条目效力：人工核定的状态与日期，以及问答/检索上的效力提示。

不自动抽取失效日。默认「未知」。即将到期 = 现行有效且失效日期早于今天起 90 天（含已过期但仍标现行有效）。
"""
import re
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from .. import db

STATUSES = ("现行有效", "已废止", "已失效", "未知")
WINDOW_DAYS = 90
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 非「现行有效」才提示。未知单独写明「效力未核定」，并同样注明勿作决策依据。
_NOTICES = {
    "已废止": "效力提示：已废止，勿作决策依据。",
    "已失效": "效力提示：已失效，勿作决策依据。",
    "未知": "效力提示：效力未核定，勿作决策依据。",
}


def notice(status):
    st = (status or "未知").strip() or "未知"
    return _NOTICES.get(st)


def attach(row):
    """返回 (状态, 提示或 None)。现行有效没有提示。"""
    st = (row.get("validity_status") or "未知").strip() or "未知"
    if st not in STATUSES:
        st = "未知"
    return st, notice(st)


def annotate(row):
    st, nt = attach(row)
    row["validity_status"] = st
    row["validity_notice"] = nt
    return row


def cutoff(today=None):
    base = today or date.today()
    return (base + timedelta(days=WINDOW_DAYS)).isoformat()


def expiring_count(today=None):
    return db.q1(
        "SELECT COUNT(*) n FROM m1_items WHERE duplicate_of IS NULL AND validity_status='现行有效' "
        "AND COALESCE(expiry_date,'')!='' AND expiry_date < ?",
        (cutoff(today),),
    )["n"]


def expiring_list(limit=100, today=None):
    cut = cutoff(today)
    today_s = (today or date.today()).isoformat()
    rows = db.q(
        "SELECT id,url,title,publisher,level,doc_no,effective_date,expiry_date,validity_status,validity_note "
        "FROM m1_items WHERE duplicate_of IS NULL AND validity_status='现行有效' "
        "AND COALESCE(expiry_date,'')!='' AND expiry_date < ? ORDER BY expiry_date, id LIMIT ?",
        (cut, limit),
    )
    for r in rows:
        r["overdue"] = (r["expiry_date"] or "") < today_s
        annotate(r)
    return {"days": WINDOW_DAYS, "cutoff": cut, "items": rows}


def filter_sql(kind, args):
    """列表筛选片段。kind 为空表示不筛。非法值抛 400。"""
    kind = (kind or "").strip()
    if not kind:
        return ""
    if kind == "expiring":
        args.append(cutoff())
        return " AND validity_status='现行有效' AND COALESCE(expiry_date,'')!='' AND expiry_date < ?"
    if kind in ("abolished", "已废止"):
        return " AND validity_status='已废止'"
    if kind in STATUSES:
        args.append(kind)
        return " AND COALESCE(validity_status,'未知')=?"
    raise HTTPException(400, "效力筛选无效")


def _date(value, label):
    if value in (None, ""):
        return None
    s = str(value).strip()[:10]
    if not _DATE.match(s):
        raise HTTPException(400, f"{label}须为 YYYY-MM-DD")
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(400, f"{label}不是有效日期") from e
    return s


def _text(value, limit):
    if value in (None, ""):
        return None
    return str(value).strip()[:limit] or None


def update(iid, body, user):
    if not db.q1("SELECT id FROM m1_items WHERE id=?", (iid,)):
        raise HTTPException(404, "条目不存在")
    st = (body.get("validity_status") or "未知").strip()
    if st not in STATUSES:
        raise HTTPException(400, "效力状态须为：现行有效 / 已废止 / 已失效 / 未知")
    eff = _date(body.get("effective_date"), "生效日期")
    exp = _date(body.get("expiry_date"), "失效日期")
    abo = _date(body.get("abolished_at"), "废止日期")
    doc = _text(body.get("doc_no"), 80)
    sup = _text(body.get("superseded_by"), 200)
    note = _text(body.get("validity_note"), 500)
    who = (user or {}).get("name") or ""
    db.execute(
        "UPDATE m1_items SET validity_status=?, effective_date=?, expiry_date=?, abolished_at=?, "
        "superseded_by=?, doc_no=?, validity_note=?, validity_updated_at=?, validity_updated_by=? WHERE id=?",
        (st, eff, exp, abo, sup, doc, note, db.now(), who, iid),
    )
    db.audit(user, "M1", "人工核定效力", iid, {
        "validity_status": st, "effective_date": eff, "expiry_date": exp, "abolished_at": abo,
        "doc_no": doc, "superseded_by": sup,
    })
    return annotate(db.q1("SELECT * FROM m1_items WHERE id=?", (iid,)))
