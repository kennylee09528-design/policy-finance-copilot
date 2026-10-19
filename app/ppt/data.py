"""数据包（Pack）：各类演示稿所需的全部数字、表格、图表、文字块均由代码从数据库取值并格式化。
大模型只看到「数据目录」（编号、名称、类型），看不到数值；页面中的数字只能来自这里。"""
import re

from fastapi import HTTPException

from .. import db

NUMTOK = re.compile(r"\d+(?:[,，]\d{3})*(?:\.\d+)?")
DECKS = {
    "usage": {"name": "额度使用情况汇报", "source": "M5 快照", "sensitive": True},
    "scheme": {"name": "授信方案上会材料", "source": "M4 方案版本", "sensitive": True},
    "policy": {"name": "政策简报 / 月度政策汇编", "source": "M2 简报（日期范围）", "sensitive": False},
    "research": {"name": "研究报告配套演示稿", "source": "M3 已定稿任务", "sensitive": False},
}


def wan(v):
    return "—" if v is None else f"{v:,.2f}"


def pct(v):
    return "—" if v is None else f"{v * 100:.2f}%"


def yi(v):
    return "—" if v is None else f"{v / 10000:,.2f} 亿元"


def sgn(v):
    return "—" if v is None else f"{v:+,.2f}"


def short(n):
    from ..m4.service import short_name
    try:
        return short_name(n) or n
    except Exception:  # noqa: BLE001
        return n


class Pack:
    def __init__(self, deck_type, title, subtitle, sensitive):
        self.d = {"deck_type": deck_type, "meta": {"title": title, "subtitle": subtitle, "org": "示例省级融资再担保有限公司 · 普惠业务部"},
                  "facts": {}, "tables": {}, "charts": {}, "texts": {}, "sensitive": sensitive, "sections": []}

    def fact(self, fid, name, value, raw=None, unit=""):
        self.d["facts"][fid] = {"name": name, "value": value, "raw": raw, "unit": unit}

    def table(self, tid, title, columns, rows, note=""):
        self.d["tables"][tid] = {"title": title, "columns": columns, "rows": [[("" if c is None else str(c)) for c in r] for r in rows], "note": note}

    def chart(self, cid, title, ctype, categories, series, fmt="#,##0.00", unit=""):
        self.d["charts"][cid] = {"title": title, "type": ctype, "categories": [str(c) for c in categories],
                                 "series": [{"name": n, "values": [None if v is None else float(v) for v in vals]} for n, vals in series],
                                 "fmt": fmt, "unit": unit}

    def text(self, xid, title, items):
        self.d["texts"][xid] = {"title": title, "items": [str(i) for i in items if str(i).strip()]}

    def done(self):
        return self.d


def catalog(pack):
    """供大模型阅读的数据目录：只有编号、名称与类型，不含任何数值。"""
    L = ["【可用数据块（数值由系统从数据库插入；你只能引用编号，严禁自己写任何数字）】"]
    for k, f in pack["facts"].items():
        L.append(f"{k}｜指标｜{f['name']}（正文中写 {{{{{k}}}}} 由系统填数）")
    for k, t in pack["charts"].items():
        L.append(f"{k}｜图表（{t['type']}）｜{t['title']}｜类别 {len(t['categories'])} 个")
    for k, t in pack["tables"].items():
        L.append(f"{k}｜表格｜{t['title']}｜{len(t['rows'])} 行，列：{'、'.join(t['columns'])}")
    for k, t in pack["texts"].items():
        L.append(f"{k}｜文字块｜{t['title']}｜{len(t['items'])} 条")
    if pack.get("sections"):
        L.append("建议章节：" + "、".join(pack["sections"]))
    return "\n".join(L)


def allowed_tokens(pack, extra_texts=()):
    """数据包中所有由代码生成的字符串里出现的数字记号（用于溯源检查）。"""
    toks = set()

    def add(s):
        for m in NUMTOK.finditer(str(s or "")):
            toks.add(m.group(0).replace(",", "").replace("，", ""))
    for v in pack["meta"].values():
        add(v)
    for f in pack["facts"].values():
        add(f["value"]); add(f["name"])
    for t in pack["tables"].values():
        add(t["title"]); add(t.get("note"))
        for c in t["columns"]:
            add(c)
        for r in t["rows"]:
            for c in r:
                add(c)
    for t in pack["charts"].values():
        add(t["title"]); add(t.get("unit"))
        for c in t["categories"]:
            add(c)
        for s in t["series"]:
            add(s["name"])
    for t in pack["texts"].values():
        add(t["title"])
        for i in t["items"]:
            add(i)
    for s in extra_texts:
        add(s)
    return toks


# ---------------- 1. 额度使用情况汇报（M5） ----------------
def pack_usage(scope):
    from ..m5 import service as S
    sid = int(scope.get("snapshot_id") or 0) or (db.q1("SELECT id FROM m5_snapshots WHERE deleted_at IS NULL ORDER BY stat_date DESC, id DESC LIMIT 1") or {}).get("id")
    if not sid:
        raise HTTPException(400, "尚无 M5 看板快照，请先在 M5 上传台账")
    d = S.dashboard(sid)
    snap, sm = d["snapshot"], d["summary"]
    period = scope.get("period") or "周报"
    p = Pack("usage", f"普惠业务额度使用情况汇报（{period}）", f"统计时点 {snap['stat_date']} · 快照 #{sid}", True)
    R, T, P_, X = sm["regular"], sm["tech"], sm["private"], sm["t2t"]
    p.fact("F1", "常规业务累计备案（万元）", wan(R["total"]["amount"]), R["total"]["amount"], "万元")
    p.fact("F2", "常规业务使用率（÷国担额度）", pct(R["total"].get("rate")), R["total"].get("rate"))
    p.fact("F3", "常规业务使用率（÷分配额度）", pct(R["total"].get("rate_alloc")), R["total"].get("rate_alloc"))
    p.fact("F4", "科技创新专项累计备案（万元）", wan(T["total"]["amount"]), T["total"]["amount"], "万元")
    p.fact("F5", "民间投资专项累计备案（万元）", wan(P_["total"]["amount"]), P_["total"]["amount"], "万元")
    p.fact("F6", "总对总累计备案（万元）", wan(X["total"]["amount"]), X["total"]["amount"], "万元")
    p.fact("F7", "总对总使用率（÷国担额度）", pct(X["total"].get("rate")), X["total"].get("rate"))
    p.fact("F8", "年度时间进度", pct(d.get("time_progress")), d.get("time_progress"))
    p.fact("F9", "常规业务剩余额度（万元）", wan(R["total"].get("remain")), R["total"].get("remain"), "万元")
    if R["total"].get("delta") is not None:
        p.fact("F10", "常规业务较上期增加（万元）", sgn(R["total"]["delta"]), R["total"]["delta"], "万元")
    names = {"regular": "常规业务", "tech": "科技专项", "private": "民间投资", "t2t": "总对总"}
    p.chart("C1", "四类业务累计备案（万元）", "column", [names[k] for k in names], [("累计备案", [sm[k]["total"]["amount"] for k in names])])
    rows = [r for r in d["rows"] if r.get("regular_limit")]
    rows.sort(key=lambda r: -(r.get("regular_rate") or 0))
    cats = [short(r["name"]) for r in rows]
    p.chart("C2", "分机构常规额度使用进度（已备案 / 剩余，万元）", "bar_stacked", cats,
            [("已备案", [r["regular_amt"] or 0 for r in rows]), ("剩余额度", [max(0, r.get("regular_remain") or 0) for r in rows])])
    p.chart("C3", "分机构常规额度使用率", "bar", cats, [("使用率", [r.get("regular_rate") or 0 for r in rows])], fmt="0.00%")
    pr = [r for r in d["rows"] if r.get("private_limit")]
    pr.sort(key=lambda r: -(r.get("private_rate") or 0))
    p.chart("C4", "分机构民间投资专项使用率", "bar", [short(r["name"]) for r in pr], [("使用率", [r.get("private_rate") or 0 for r in pr])], fmt="0.00%")
    p.table("T1", "分机构额度使用明细（万元）", ["机构", "常规额度", "常规累计备案", "常规使用率", "民投额度", "民投累计备案", "民投使用率", "预警"],
            [[short(r["name"]), wan(r.get("regular_limit")), wan(r.get("regular_amt")), pct(r.get("regular_rate")), wan(r.get("private_limit")),
              wan(r.get("private_amt")), pct(r.get("private_rate")), "；".join(w if isinstance(w, str) else w.get("msg", "") for w in (r.get("warn") or []))] for r in rows])
    warns = [a["msg"] for a in d.get("alerts", [])] + [w if isinstance(w, str) else w.get("msg", "") for w in (d.get("limit_warnings") or [])]
    for r in d["rows"]:
        for w in r.get("warn") or []:
            warns.append(f"{short(r['name'])}：{w if isinstance(w, str) else w.get('msg', '')}")
    p.text("X1", "预警事项", warns or ["本期无预警事项"])
    p.text("X2", "环比说明", [v for v in (d.get("notes") or {}).values() if v])
    p.d["sections"] = ["总体情况", "分机构使用进度", "预警事项", "环比说明"]
    p.d["source"] = {"m5_snapshot": sid, "stat_date": snap["stat_date"]}
    return p.done()


# ---------------- 2. 授信方案上会材料（M4） ----------------
KIND = {"third": "第三次调整", "mintou": "民投完成率调整（人工覆盖）"}
COEF = {"L": "就业贡献系数", "N": "支小支农系数", "P": "累计代偿率系数", "R": "当年代偿率系数", "T": "评价分系数"}


def pack_scheme(scope):
    from ..m4 import service as M
    sid = int(scope.get("scheme_id") or 0) or (db.q1("SELECT id FROM m4_schemes WHERE deleted_at IS NULL ORDER BY is_current DESC, version DESC LIMIT 1") or {}).get("id")
    if not sid:
        raise HTTPException(400, "尚无 M4 授信方案")
    s = M.get_scheme(sid)
    res, t = s["result"], s["result"]["totals"]
    p = Pack("scheme", "2026 年合作担保机构授信方案（上会材料）", f"方案 v{s['version']}「{s['name']}」 · 状态：{s['status']}", True)
    p.fact("F1", "参与测算机构数（家）", f"{t['count']}", t["count"])
    p.fact("F2", "其中固定额度机构（家）", f"{t['fixed_count']}", t["fixed_count"])
    p.fact("F3", "第一次调整合计 W（万元）", wan(t["sumW"]), t["sumW"], "万元")
    p.fact("F4", "第二次调整合计 X（万元）", wan(t["sumX"]), t["sumX"], "万元")
    p.fact("F5", "第三次调整合计（万元）", wan(t["sumThird"]), t["sumThird"], "万元")
    p.fact("F6", "民投完成率调整合计（万元）", wan(t["sumMintouAdj"]), t["sumMintouAdj"], "万元")
    p.fact("F7", "常规授信额度合计（万元）", wan(t["sumRegular"]), t["sumRegular"], "万元")
    p.fact("F8", "民间投资专项合计（万元）", wan(t["sumMintouSpecial"]), t["sumMintouSpecial"], "万元")
    p.fact("F9", "最终授信额度合计（万元）", wan(t["sumFinal"]), t["sumFinal"], "万元")
    pr = res["param"]
    c = pr["constants"]
    p.table("T1", f"系数规则（参数 v{pr['version']}）", ["项目", "取值", "说明"],
            [[f"权重 {COEF.get(k, k)}", f"{v:.2f}", f"总系数 U 中 {k} 的权重"] for k, v in pr["weights"].items()] +
            [["全省平均户均就业人数", f"{c.get('emp_avg'):,.2f}" if c.get("emp_avg") is not None else "—", "就业系数基准"],
             ["累计代偿率全省均值", pct(c.get("lj_avg")), "累计代偿率系数基准"],
             ["当年代偿率全省均值", pct(c.get("dn_avg")), "当年代偿率系数基准"],
             ["支小支农阈值", pct(c.get("zxzn_threshold")), "低于阈值系数下调"],
             ["系数下限", f"{c.get('floor')}", "单项系数下限"]])
    rows = sorted(res["rows"], key=lambda r: -(r["final"] or 0))
    p.table("T2", "三步调整结果（万元）", ["机构", "第一次调整 W", "第二次调整 X", "第三次调整", "民投完成率调整", "常规授信", "民投专项", "最终授信"],
            [[short(r["name"]) + ("（固定）" if r["fixed"] else ""), wan(r["W"]), wan(r["X"]), sgn(r["third"]), sgn(r["mintou_adj"]),
              wan(r["regular_final"]), wan(r["mintou_special"]), wan(r["final"])] for r in rows])
    adj = M.current_adjustments_list(sid)
    p.table("T3", "人工调整及原因", ["机构", "类型", "调整值（万元）", "原因", "操作人", "时间"],
            [[short(a["institution"]), KIND.get(a["kind"], a["kind"]), sgn(a["value"]), a["reason"] or "", a["operator"] or "", (a["created_at"] or "")[:16]] for a in adj])
    top = rows[:15]
    p.chart("C1", "最终授信额度构成（前 15 家，万元）", "bar_stacked", [short(r["name"]) for r in top],
            [("第二次调整 X", [r["X"] or 0 for r in top]), ("第三次调整", [r["third"] or 0 for r in top]),
             ("民投完成率调整", [r["mintou_adj"] or 0 for r in top]), ("民投专项", [r["mintou_special"] or 0 for r in top])])
    p.chart("C2", "各步骤合计（万元）", "column", ["第一次调整 W", "第二次调整 X", "常规授信", "最终授信"],
            [("合计", [t["sumW"], t["sumX"], t["sumRegular"], t["sumFinal"]])])
    p.text("X1", "测算提示", [a["msg"] for a in res.get("alerts", [])] or ["无"])
    p.d["sections"] = ["测算依据与系数规则", "三步调整结果", "人工调整及原因", "提请审议事项"]
    p.d["source"] = {"m4_scheme": sid, "version": s["version"]}
    return p.done()


# ---------------- 3. 政策简报 / 月度汇编（M2） ----------------
def pack_policy(scope):
    d1, d2 = scope.get("date_from"), scope.get("date_to")
    if not (d1 and d2) or d1 > d2:
        raise HTTPException(400, "请选择有效的日期范围")
    briefs = db.q("SELECT * FROM m2_briefs WHERE brief_date BETWEEN ? AND ? ORDER BY brief_date, (status='已发布') DESC, version DESC", (d1, d2))
    chosen = {}
    for b in briefs:
        # 每日取最新版本（含草稿）：旧的已发布版可能早于后续补采的条目（2026-10-12 线上已发布 v2 为 0 条、草稿 v8+ 才有条目）
        if b["brief_date"] not in chosen or b["version"] > chosen[b["brief_date"]]["version"]:
            chosen[b["brief_date"]] = b
    if not chosen:
        raise HTTPException(400, "该日期范围内没有 M2 简报")
    seen, items = set(), []
    for dt, b in sorted(chosen.items()):
        for i in (db.jload(b["items"], {}) or {}).get("items", []):
            if i.get("blocked") or i.get("include") is False or i["url"] in seen:
                continue
            seen.add(i["url"])
            items.append({**i, "brief_date": dt})
    p = Pack("policy", "政策简报汇编" if d1 != d2 else "今日政策简报", f"{d1} 至 {d2} · 共 {len(chosen)} 期简报", False)
    stars = {3: "★★★ 今日必读", 2: "★★ 值得关注", 1: "★ 浏览"}
    for tier, tid in ((3, "T3"), (2, "T2"), (1, "T1")):
        g = [i for i in items if i["tier"] == tier]
        p.table(tid, f"{stars[tier]}（{len(g)} 条）", ["日期", "类别｜地域", "标题", "来源（等级）", "链接"],
                [[i["brief_date"], f"{i['category']}｜{i.get('region') or '—'}", i["title"], f"{i['publisher']}（{i['level']}）", i["url"]] for i in g])
        p.text("X" + str(tier), f"{stars[tier]} 要点", [f"{i['title']}：{'；'.join(i.get('points') or [])}（{i['publisher']}，{i['level']}）" for i in g])
    p.fact("F1", "入选条目（条）", str(len(items)), len(items))
    for tier, fid in ((3, "F2"), (2, "F3"), (1, "F4")):
        n = sum(1 for i in items if i["tier"] == tier)
        p.fact(fid, f"{stars[tier]}（条）", str(n), n)
    p.fact("F5", "简报期数", str(len(chosen)), len(chosen))
    cats = {}
    for i in items:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
    ck = sorted(cats, key=lambda k: -cats[k])
    p.chart("C1", "按类别统计（条）", "column", ck, [("条目数", [cats[k] for k in ck])], fmt="0")
    lv = {}
    for i in items:
        lv[i["level"]] = lv.get(i["level"], 0) + 1
    lk = sorted(lv)
    p.chart("C2", "按来源等级统计（条）", "column", lk, [("条目数", [lv[k] for k in lk])], fmt="0")
    # 数据速览取区间内最新生成的一期（含草稿），并标明期次/状态与统计时点
    newest = max(briefs, key=lambda b: (b["brief_date"], b["version"]))
    last = db.jload(newest["items"], {}).get("data_rows", [])
    if last:
        stat = (re.search(r"统计时点 ([0-9-]+)", last[0].get("source") or "") or [None, "—"])[1]
        p.table("T4", f"数据速览（截至 {stat}）", ["指标", "数值", "较上期", "来源"], [[r["name"], r["value"], r["delta"], r["source"]] for r in last],
                note=f"取自 {newest['brief_date']} 第{newest['version']}版简报（{newest['status']}），M5 统计时点 {stat}")
    p.d["sections"] = ["今日必读", "值得关注", "同业动态与浏览", "数据速览"]
    p.d["source"] = {"m2_briefs": [b["id"] for b in chosen.values()],
                     "versions": [f"{b['brief_date']} 第{b['version']}版（{b['status']}）" for _, b in sorted(chosen.items())]}
    return p.done()


# ---------------- 4. 研究报告配套演示稿（M3） ----------------
def pack_research(scope):
    from ..m3 import pipeline as P3
    tid = int(scope.get("task_id") or 0)
    if not tid:
        r = db.q1("SELECT id FROM m3_tasks WHERE status IN ('已定稿','已总结') ORDER BY id DESC LIMIT 1")
        tid = r["id"] if r else 0
    if not tid:
        raise HTTPException(400, "尚无已定稿的 M3 写作任务")
    t = P3._task(tid)
    if t["status"] not in ("已定稿", "已总结"):
        raise HTTPException(400, "该 M3 任务尚未定稿，不能生成配套演示稿")
    uses_m5 = bool(t["requirements"].get("use_m5") or t["facts"])
    p = Pack("research", t["title"], "研究报告配套演示稿", uses_m5)
    for f in t["facts"]:
        p.fact(f["id"], f["name"], f["value"])
    secs, cur = [], None
    for line in (t["final"] or "").split("\n"):
        if not line.strip():
            continue
        if re.match(r"^[一二三四五六七八九十]+、", line) and len(line) < 40:
            cur = {"heading": line.strip(), "body": []}
            secs.append(cur)
        elif cur:
            cur["body"].append(line.strip())
        else:
            cur = {"heading": "概述", "body": [line.strip()]}
            secs.append(cur)
    chk = t["final_check"] or t["check_result"] or {"items": [], "register": []}
    ok = {i["text"] for i in chk["items"] if i["status"] == "已核实" or i.get("confirmed")}
    for k, s in enumerate(secs, 1):
        body = " ".join(s["body"])
        sents = [x.strip() for x in re.findall(r"[^。！？；]+[。！？；]?", body) if x.strip()]
        # 已核实的含数字句子原样引用（数字来自终稿，终稿数字已经核对 Agent 逐句核实）
        quotes = [x for x in sents if x in ok and NUMTOK.search(x)]
        plain = [c for c in (re.sub(r"\[(?:S\d+|M5)\]", "", x).strip() for x in sents) if c and not NUMTOK.search(c)]
        p.text(f"X{k}", s["heading"], quotes)
        p.text(f"P{k}", s["heading"] + "（无数字句，供提炼要点参考）", plain[:8])
    reg = chk.get("register", [])
    p.table("T1", "引用来源登记表", ["编号", "来源名称", "类型", "出处位置", "链接", "发布日期", "核验状态"],
            [[r["no"], r["source_name"], r["level"], r["location"], r["url"], r["pub_date"] or "", r["status"]] for r in reg])
    p.d["sections"] = [s["heading"] for s in secs]
    p.d["source"] = {"m3_task": tid, "uses_m5": uses_m5}
    return p.done()


BUILDERS = {"usage": pack_usage, "scheme": pack_scheme, "policy": pack_policy, "research": pack_research}


def build(deck_type, scope):
    if deck_type not in BUILDERS:
        raise HTTPException(400, "未知的演示稿类型")
    return BUILDERS[deck_type](scope or {})
