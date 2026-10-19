"""M5 台账取数模块（与看板计算解耦，Q6：一期人工上传，预留接口取数）。

支持两种形态：
  1) 国担系统导出的「机构业务规模分析」汇总表（样表 2-1~2-4）：按机构一行，含 规模/笔数/户数；
  2) 明细台账（需求 7.1 建议字段）：序号|机构名称|业务类型|直保/再保|备案金额(万元)|备案日期|...，系统自动汇总。
直保口径：汇总表中「直保主体」（默认 示例省级融资再担保有限责任公司，可配置）所在行视为直保，其余为再保。
"""
import re
import warnings
from datetime import date, datetime
from io import BytesIO

import openpyxl

warnings.filterwarnings("ignore", message="Workbook contains no default style")

PORTS = {"regular": "常规", "tech": "科创", "private": "民投", "t2t": "总对总"}
DEFAULT_DIRECT_ENTITIES = ["示例省级融资再担保有限责任公司"]


class LedgerSource:
    """取数源抽象：parse(bytes) -> 标准化台账。二期可新增 GuodanApiSource 而不改看板计算。"""

    def fetch(self, port, **kw):
        raise NotImplementedError


class ManualUploadSource(LedgerSource):
    def fetch(self, port, data: bytes = b"", filename: str = "", direct_entities=None, **kw):
        return parse_ledger(data, filename, port, direct_entities)


class GuodanApiSource(LedgerSource):
    """预留：国担系统接口取数（T3，二期）。"""

    def fetch(self, port, **kw):
        raise NotImplementedError("国担系统接口尚未开通（二期）")


def _date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        return None


def _num(v):
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def parse_ledger(data: bytes, filename: str, port: str, direct_entities=None):
    direct_entities = direct_entities or DEFAULT_DIRECT_ENTITIES
    wb = openpyxl.load_workbook(BytesIO(data), data_only=True)
    ws = wb.worksheets[0]
    warnings = []
    cells = [[c.value for c in row] for row in ws.iter_rows()]
    text = " ".join(str(v) for row in cells[:6] for v in row if isinstance(v, str))
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})", text)
    period_start, period_end = (m.group(1), m.group(2)) if m else (None, None)
    um = re.search(r"数据更新日期[:：]\s*(\d{4}-\d{2}-\d{2})", text)
    updated_on = um.group(1) if um else None

    # 定位表头
    hdr_r, name_c = None, None
    for i, row in enumerate(cells[:15]):
        for j, v in enumerate(row):
            if isinstance(v, str) and v.strip() in ("机构名称", "直担机构名称", "合作机构"):
                hdr_r, name_c = i, j
                break
        if hdr_r is not None:
            break
    if hdr_r is None:
        raise ValueError("未识别到「机构名称」表头，请确认是国担系统导出的台账")
    header = [str(v).strip() if v else "" for v in cells[hdr_r]]
    sub = [str(v).strip() if v else "" for v in cells[hdr_r + 1]] if hdr_r + 1 < len(cells) else []

    detail_mode = any("直保" in h and "再保" in h for h in header) and any("备案金额" in h for h in header)
    rows = []
    total_row = None
    if detail_mode:
        ci = {h: j for j, h in enumerate(header)}
        amt_c = next(j for h, j in ci.items() if "备案金额" in h)
        dr_c = next(j for h, j in ci.items() if "直保" in h)
        date_c = next((j for h, j in ci.items() if "备案日期" in h), None)
        agg = {}
        for row in cells[hdr_r + 1:]:
            name = row[name_c] if name_c < len(row) else None
            if not name or str(name).strip() in ("合计", "总计"):
                continue
            amt = _num(row[amt_c]) or 0.0
            kind = str(row[dr_c] or "").strip()
            name = str(name).strip()
            a = agg.setdefault(name, {"name": name, "amount": 0.0, "count": 0, "households": None, "direct": 0.0})
            a["amount"] += amt
            a["count"] += 1
            if kind == "直保":
                a["direct"] += amt
            if date_c is not None and row[date_c]:
                dv = row[date_c]
                ds = dv.date().isoformat() if isinstance(dv, datetime) else (dv.isoformat() if isinstance(dv, date) else str(dv)[:10])
                period_end = max(period_end or ds, ds)
                period_start = min(period_start or ds, ds)
        rows = list(agg.values())
        direct = sum(r["direct"] for r in rows)
        total = sum(r["amount"] for r in rows)
        direct_source = "台账(明细直保/再保字段)"
        for r in rows:
            r["is_direct_entity"] = False
    else:
        # 汇总表：规模列 = 表头“规模”下的第一列
        amt_c = next((j for j, h in enumerate(header) if h == "规模"), None)
        if amt_c is None:
            amt_c = next((j for j, h in enumerate(sub) if h == "规模"), None)
        cnt_c = next((j for j, h in enumerate(sub) if h == "笔数"), None)
        hh_c = next((j for j, h in enumerate(sub) if h == "户数"), None)
        if amt_c is None:
            raise ValueError("未识别到「规模」列")
        for row in cells[hdr_r + 1:]:
            label = row[1] if len(row) > 1 else None
            name = row[name_c] if name_c < len(row) else None
            if isinstance(label, str) and label.strip() == "合计":
                total_row = _num(row[amt_c])
                continue
            if isinstance(label, str) and "备注" in label:
                break
            if not name or str(name).strip() in ("规模", "机构名称"):
                continue
            amt = _num(row[amt_c])
            if amt is None:
                continue
            rows.append({"name": str(name).strip(), "amount": amt,
                         "count": _num(row[cnt_c]) if cnt_c is not None else None,
                         "households": _num(row[hh_c]) if hh_c is not None else None,
                         "is_direct_entity": str(name).strip() in direct_entities})
        total = sum(r["amount"] for r in rows)
        if total_row is not None and abs(total_row - total) > 0.01:
            warnings.append(f"合计行 {total_row:,.6f} 与明细加总 {total:,.6f} 不一致，以合计行为准")
            total = total_row
        drows = [r for r in rows if r["is_direct_entity"]]
        if drows:
            direct = sum(r["amount"] for r in drows)
            direct_source = f"台账（{drows[0]['name']}行）"
        else:
            direct = None
            direct_source = "缺失"
            warnings.append("台账中未包含直保主体行，直保金额需手工填写（否则按缺失处理，再保=合计）")
    if not period_end:
        warnings.append("未识别到备案时间区间，请手工指定统计时点")
    return {"port": port, "file_name": filename, "period_start": period_start, "period_end": period_end,
            "updated_on": updated_on, "total": total, "direct": direct, "direct_source": direct_source,
            "rows": [r for r in rows if not r.get("is_direct_entity")], "direct_rows": [r for r in rows if r.get("is_direct_entity")],
            "warnings": warnings, "mode": "明细台账" if detail_mode else "机构业务规模汇总表"}
