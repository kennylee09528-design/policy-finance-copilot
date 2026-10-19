"""M4 授信测算引擎（与附件2计算表公式逐项对应）。

  J = I/10000                                   （规模系数）
  K = 就业人数/(I+基期常数)×10000 ；L = K/全省均值   （就业系数）
  M = ROUND(支小支农占比,2)/100 ；N = IF(M≥90%,1,M/90%)
  O = 近3年累计代偿率/100 ；P = MAX(1−(O−均值)/均值, 0.5)
  Q = 上一年代偿率/100   ；R = MAX(1−(Q−均值)/均值, 0.5)
  T = 评价分/100
  U = J×(L·wL + N·wN + P·wP + R·wR + T·wT)
  V = ROUND(增资总额×2/1000,0)×1000
  W = I + V − H（上一年民投）
  X = ROUND(ΣW×U/ΣU, 0)   （Σ 仅含参与分配的机构；固定额度机构不参与，X=给定额度）
  第三次调整后 = X + 第三次调整(±，人工、必填原因)
  常规授信 = 第三次调整后 + 民投完成率调整
  最终授信 = 常规授信 + 民间投资专项额度

PRD（feedback_1018）新增「初步授信额度」链路（与附件2 计算表 Z~AI 列公式一致，均为未经人工改动的公式值）：
  Z = X ；AA = Z
  AB = ROUND(IF(ROUND(AA/10000,0)×10000=0, 10000, ROUND(AA/1000,0)×1000)/10000, 0)×10000
  AH = AF/AB（AF=截止备案金额） ；AC = AB + IF(AH≥40%, 20000, 0)  → 初步授信额度
  AI = AC + D（民间投资专项）；Y = X − G（G=2026 工行预计 >0 时）
  目前最新常规业务授信额度 = 申请表 C+D + Σ人工增减 ；目前最新民间投资授信额度 = 申请表 F + Σ人工增减
权重：5 项合计须 = 1（容差 ±0.02）；超出容差时按比例归一后计算并告警。
"""
from .xlsxformula import xround

DEFAULT_TIERS = {"hi": 18.0, "lo": 10.0, "cut_mid": 0.2, "cut_low": 0.4, "add_hi": 1.0, "add_mid": 0.8, "add_low": 0.6}


def mintou_rule(q3_base, balance, rate, tiers=None):
    """请示附表：民投完成率档位规则。可调整额度 = 授信余额 − 三季度基本额度。返回 (调整额, 说明)。"""
    t = {**DEFAULT_TIERS, **(tiers or {})}
    if q3_base is None or balance is None or rate is None:
        return None, "未填写完成率/基本额度/授信余额"
    adj = balance - q3_base
    if adj >= 0:
        if rate >= t["hi"]:
            return 0.0, f"可调整额度≥0 且完成率≥{t['hi']:g}%：不调整"
        if rate >= t["lo"]:
            return -adj * t["cut_mid"], f"可调整额度≥0 且 {t['lo']:g}%≤完成率<{t['hi']:g}%：调减 可调整额度×{t['cut_mid']:.0%}"
        return -adj * t["cut_low"], f"可调整额度≥0 且完成率<{t['lo']:g}%：调减 可调整额度×{t['cut_low']:.0%}"
    gap = q3_base - balance
    if rate >= t["hi"]:
        return gap * t["add_hi"], f"存在缺口且完成率≥{t['hi']:g}%：调增 缺口×{t['add_hi']:.0%}"
    if rate >= t["lo"]:
        return gap * t["add_mid"], f"存在缺口且 {t['lo']:g}%≤完成率<{t['hi']:g}%：调增 缺口×{t['add_mid']:.0%}"
    return gap * t["add_low"], f"存在缺口且完成率<{t['lo']:g}%：调增 缺口×{t['add_low']:.0%}"


def _coef(r, c, w):
    out = {}
    I = r.get("scale")
    out["I"] = I
    bcs = c.get("base_consts") or {}  # 规模基期常数：附件2 仅个别机构 K 列含此项（按机构配置）
    base_const = bcs[r["name"]] if r.get("name") in bcs and bcs[r["name"]] is not None else (r.get("base_const") or 0)
    out["J"] = I / 10000 if I is not None else None
    emp = r.get("emp")
    if emp is not None and I is not None and (I + base_const) != 0:
        out["K"] = emp / (I + base_const) * 10000
        out["L"] = out["K"] / c["emp_avg"]
    else:
        out["K"] = out["L"] = None
    z = r.get("zxzn_raw")
    if z is not None:
        out["M"] = xround(z, 2) / 100
        th = c.get("zxzn_threshold", 0.9)
        out["N"] = 1.0 if out["M"] >= th else out["M"] / th
    else:
        out["M"] = out["N"] = None
    lj = r.get("lj_raw")
    out["O"] = lj / 100 if lj is not None else None
    out["P"] = max(1 - (out["O"] - c["lj_avg"]) / c["lj_avg"], c.get("floor", 0.5)) if lj is not None else None
    dn = r.get("dn_raw")
    out["Q"] = dn / 100 if dn is not None else None
    out["R"] = max(1 - (out["Q"] - c["dn_avg"]) / c["dn_avg"], c.get("floor", 0.5)) if dn is not None else None
    out["S"] = r.get("pj")
    out["T"] = r["pj"] / 100 if r.get("pj") is not None else None
    parts = [out["J"], out["L"], out["N"], out["P"], out["R"], out["T"]]
    if all(p is not None for p in parts):
        out["U"] = out["J"] * (out["L"] * w["L"] + out["N"] * w["N"] + out["P"] * w["P"] + out["R"] * w["R"] + out["T"] * w["T"])
    else:
        out["U"] = None
    if r.get("v_const") is not None:
        out["V"] = r["v_const"]
    else:
        out["V"] = xround((r.get("zc_total") or 0) * 2 / 1000, 0) * 1000
    out["H"] = r.get("mintou_prev") or 0.0
    out["W"] = (I or 0) + out["V"] - out["H"]
    return out


WEIGHT_TOL = 0.02


def ab_round(aa):
    """第五次调整 AB：AA 按 1000 取整后落到 1 万档；取整后为 0 给 10000。"""
    if aa is None:
        return None
    inner = 10000 if xround(aa / 10000, 0) * 10000 == 0 else xround(aa / 1000, 0) * 1000
    return xround(inner / 10000, 0) * 10000


def prelim_chain(x, row, c):
    """X → Z/AA/AB/AH/AC（初步授信额度）。"""
    out = {}
    if row.get("fixed"):
        v = row.get("fixed_ac") if row.get("fixed_ac") is not None else row.get("fixed_quota")
        out.update(Z=v, AA=v, AB=v, AF=row.get("filed_amount"), AH=None, AC=v, bonus=0.0)
        return out
    out["Z"] = x
    out["AA"] = x
    out["AB"] = ab_round(x)
    af = row.get("filed_amount")
    out["AF"] = af
    out["AH"] = (af / out["AB"]) if (af is not None and out["AB"]) else None
    ratio, bonus = c.get("filed_ratio", 0.4), c.get("filed_bonus", 20000)
    out["bonus"] = bonus if (out["AH"] is not None and out["AH"] >= ratio) else 0.0
    out["AC"] = out["AB"] + out["bonus"] if out["AB"] is not None else None
    return out


def effective_weights(w):
    s = sum(w.values())
    if abs(s - 1) <= WEIGHT_TOL or s == 0:
        return dict(w), s, False
    return {k: v / s for k, v in w.items()}, s, True


def compute(rows, params, adjustments=None, mintou_inputs=None, cur_adjust=None):
    """rows: 数据集逐机构输入；params: {weights, constants}；
    adjustments: {机构: {"third": {...}, "mintou": {...}}}（最新有效值）；mintou_inputs: {机构: {q3_base, balance, rate}}。"""
    c = params["constants"]
    adjustments = adjustments or {}
    mintou_inputs = mintou_inputs or {}
    cur_adjust = cur_adjust or {}
    alerts = []
    w, wsum, normalized = effective_weights(params["weights"])
    if normalized:
        alerts.append({"level": "error", "type": "权重和≠1", "msg": f"当前 5 项权重合计 {wsum:.4f}，超出 1±{WEIGHT_TOL}："
                       f"已按比例归一后计算（{'/'.join(f'{k}={v:.4f}' for k, v in w.items())}），应调整为合计=1"})
    elif abs(wsum - 1) > 1e-9:
        alerts.append({"level": "warn", "type": "权重和容差", "msg": f"当前权重合计 {wsum:.4f}，在 1±{WEIGHT_TOL} 容差内，按原值计算"})
    res = []
    for r in rows:
        co = _coef(r, c, w)
        res.append({"name": r["name"], "seq": r.get("seq"), "fixed": bool(r.get("fixed")), **co})
    pool = [x for x in res if not x["fixed"]]
    missing_u = [x["name"] for x in pool if x["U"] is None]
    for n in missing_u:
        alerts.append({"level": "error", "type": "数据缺失", "msg": f"「{n}」系数数据不全，无法计算总系数 U"})
    sumW = sum(x["W"] for x in pool)
    sumU = sum(x["U"] for x in pool if x["U"] is not None)
    for x, r in zip(res, rows):
        if x["fixed"]:
            x["X"] = r.get("fixed_quota")
        elif x["U"] is None or sumU == 0:
            x["X"] = None
        else:
            x["X"] = xround(sumW * x["U"] / sumU, 0)
        adj = adjustments.get(x["name"], {})
        third = adj.get("third")
        x["third"] = third["value"] if third else 0.0
        x["third_reason"] = third["reason"] if third else ""
        x["third_by"] = f"{third['operator']} {third['created_at']}" if third else ""
        x["after_third"] = (x["X"] or 0) + x["third"]
        mi = mintou_inputs.get(x["name"], {})
        auto, why = mintou_rule(mi.get("q3_base"), mi.get("balance"), mi.get("rate"), c.get("mintou_tiers"))
        ov = adj.get("mintou")
        x["mintou_inputs"] = mi
        x["mintou_auto"] = auto
        x["mintou_rule"] = why
        if ov:
            x["mintou_adj"] = ov["value"]
            x["mintou_reason"] = f"人工覆盖：{ov['reason']}（{ov['operator']} {ov['created_at']}）"
        else:
            x["mintou_adj"] = auto or 0.0
            x["mintou_reason"] = why if auto is not None else ""
        x["regular_final"] = x["after_third"] + x["mintou_adj"]
        x["mintou_special"] = r.get("mintou_special") or 0.0
        x["final"] = x["regular_final"] + x["mintou_special"]
        x["tech_quota"] = r.get("tech_quota")
        x["tech_quota1"] = r.get("tech_quota1")
        x.update(prelim_chain(x["X"], r, c))
        x["D"] = r.get("mintou_special") or 0.0
        x["AI"] = (x["AC"] + x["D"]) if x["AC"] is not None else None
        icbc = r.get("icbc") or {}
        x["E"], x["F"], x["G"] = icbc.get("E"), icbc.get("F"), icbc.get("G")
        x["Y"] = (x["X"] - x["G"]) if (x["G"] or 0) > 0 and x["X"] is not None else None
        x["AG"] = r.get("net_amount")
        ca = cur_adjust.get(x["name"], {})
        x["cur_regular_base"] = r.get("apply_regular_tech") or 0.0
        x["cur_mintou_base"] = r.get("mintou_special") or 0.0
        x["cur_regular_delta"] = ca.get("cur_regular", 0.0)
        x["cur_mintou_delta"] = ca.get("cur_mintou", 0.0)
        x["cur_regular"] = x["cur_regular_base"] + x["cur_regular_delta"]
        x["cur_mintou"] = x["cur_mintou_base"] + x["cur_mintou_delta"]
    totals = {
        "sumW": sumW, "sumU": sumU, "count": len(res), "pool_count": len(pool),
        "fixed_count": len(res) - len(pool),
        "sumX": sum(x["X"] or 0 for x in res), "sumThird": sum(x["third"] for x in res),
        "sumMintouAdj": sum(x["mintou_adj"] for x in res),
        "sumRegular": sum(x["regular_final"] for x in res),
        "sumMintouSpecial": sum(x["mintou_special"] for x in res),
        "sumFinal": sum(x["final"] for x in res),
        "sumAC": sum(x["AC"] or 0 for x in res), "sumAI": sum(x["AI"] or 0 for x in res),
        "sumCurRegular": sum(x["cur_regular"] for x in res), "sumCurMintou": sum(x["cur_mintou"] for x in res),
        "weight_sum": wsum, "weights_normalized": normalized, "weights_effective": w,
    }
    return {"rows": res, "totals": totals, "alerts": alerts}
