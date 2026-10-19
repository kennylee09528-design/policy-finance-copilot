"""Agent 式问答（微信普惠Bot / 飞书共用）。

流程：大模型路由（只看提问文字 + 本人近几轮提问）→
  · 系统工具：调用既有业务函数，回复全部数字直接来自数据库，标「来源：系统」（大模型不改写、不接触结果）；
  · 兜底：大模型回答一般业务知识；需要最新信息时 Tavily 联网（查询词剔除机构名/数字等内部信息），标「AI 生成，仅供参考」并附链接。
护栏：系统数据查不到就直说；行级权限由各工具内部按绑定账号执行；涉敏问题只用 allow_sensitive 模型；
大模型不可用 → 返回 None，由调用方回到原有固定规则。"""
import json
import re
import time
from collections import deque

from .. import db
from ..llm import service as L

SYS_TAG = "\n「来源：系统」"
AI_TAG = "\n「AI 生成，仅供参考」"
TURNS, TTL = 6, 30 * 60
_mem: dict[str, dict] = {}
SENS_KW = re.compile(r"额度|授信|备案|使用率|代偿|测算|在保|余额|预警|放款|机构|分支|合作行|再担保公司")
SYSTEM_TOOLS = {"quota", "alerts", "brief", "policy", "reports", "m4"}
TOOL_DESC = {
    "quota": "查询再担保额度/机构额度使用情况（M5 看板，可带机构名）",
    "alerts": "查询额度预警/风险提示（M5）",
    "brief": "今日/最新行业简报、今天有什么政策动态（M2）",
    "policy": "在工作台知识库检索政策/资讯（M1，需关键词）",
    "reports": "已定稿研究报告列表或检索（M3）",
    "m4": "授信额度测算方案结果（M4 当前方案汇总）",
    "llm": "一般业务知识、概念解释、政策解读，无需最新信息",
    "search": "需要最新外部信息（新闻、最新出台的外部政策、市场动态）",
}


# ---------------------------------------------------------------- 多轮上下文（仅存提问 + 路由；系统数据不入上下文）
def _hist(key):
    m = _mem.get(key)
    if not m or time.time() - m["t"] > TTL:
        m = _mem[key] = {"t": time.time(), "q": deque(maxlen=TURNS)}
    return m


def remember(key, q, route, answer=""):
    m = _hist(key)
    m["t"] = time.time()
    m["q"].append({"q": q[:200], "route": route, "a": answer[:300] if route in ("llm", "search") else ""})


def clear(key):
    _mem.pop(key, None)


# ---------------------------------------------------------------- 模型选择与敏感判断
def _org_names():
    try:
        return [r["name"] for r in db.q("SELECT name FROM m4_institutions")]
    except Exception:  # noqa: BLE001
        return []


def is_sensitive(t):
    if SENS_KW.search(t):
        return True
    from ..m4.service import short_name
    for n in _org_names():
        sn = short_name(n)
        if n in t or (len(sn) >= 2 and sn in t):
            return True
    return False


def _model(sensitive):
    """返回 (slot, model_id)；涉敏只用 allow_sensitive 模型。"""
    a = L.assignments()
    for slot in (["bot.agent_sensitive", "bot.agent", "feishu.router"] if sensitive else ["bot.agent", "feishu.router"]):
        mid = a.get(slot)
        if not mid:
            continue
        m = db.q1("SELECT m.enabled, m.allow_sensitive, p.enabled pe FROM llm_models m JOIN llm_providers p ON p.id=m.provider_id WHERE m.id=?", (mid,))
        if not m or not (m["enabled"] and m["pe"]):
            continue
        if sensitive and not m["allow_sensitive"]:
            continue
        return slot, mid
    return None, None


def _call(slot, mid, messages, user, max_tokens=600, timeout=40):
    return L.run(slot, messages, user, mid=mid, overrides={"max_tokens": max_tokens, "temperature": 0.2}, timeout=timeout, ref="bot.agent")["content"]


def sanitize_query(t):
    """进入外部搜索的查询词：去掉机构名、数字、内部系统词。"""
    from ..m4.service import short_name
    q = t
    for n in sorted(_org_names(), key=len, reverse=True):
        q = q.replace(n, "")
        sn = short_name(n)
        if len(sn) >= 2:
            q = q.replace(sn, "")
    q = re.sub(r"[\d.,，%]+(万|亿|元)?", "", q)
    q = re.sub(r"工作台|系统|我们|本机构|我司|内部", "", q)
    return re.sub(r"\s+", " ", q).strip()[:80]


# ---------------------------------------------------------------- 路由
def route(ctx, t, slot, mid):
    h = _hist(ctx.open_id)["q"]
    prev = "\n".join(f"- 用户问：{x['q']}（路由 {x['route']}）" for x in h) or "（无）"
    tools = {k: v for k, v in TOOL_DESC.items() if not (ctx.user["role"] == "institution" and k in ("policy", "reports", "m4"))}
    sys = ("你是普惠业务工作台机器人的路由器。根据用户问题选择一个工具，只输出 JSON，不要解释。\n工具：\n" +
           "\n".join(f"- {k}：{v}" for k, v in tools.items()) +
           "\n规则：凡涉及工作台内部数据（额度、机构、预警、简报、知识库、报告、测算）一律选系统工具；"
           "追问（如“那预警呢”“它的呢”）结合历史补全问题。\n"
           '格式：{"tool":"...","question":"补全后的完整问题","keyword":"检索关键词，可空，≤20字"}')
    out = _call(slot, mid, [{"role": "system", "content": sys},
                            {"role": "user", "content": f"历史提问：\n{prev}\n\n当前问题：{t[:300]}"}], ctx.user, max_tokens=200, timeout=25)
    m = re.search(r"\{.*\}", out, re.S)
    o = json.loads(m.group(0)) if m else {}
    tool = o.get("tool") if o.get("tool") in tools else "llm"
    return tool, (str(o.get("question") or t))[:300], str(o.get("keyword") or "")[:20]


def rule_tool(t):
    from .service import rule_intent
    if re.search(r"测算|授信方案", t):
        return "m4"
    it = rule_intent(t)
    return it if it in SYSTEM_TOOLS else None


# ---------------------------------------------------------------- 主入口
def answer(ctx, t, handlers):
    """返回 reply dict；大模型不可用返回 None（调用方回退固定规则）。"""
    sens = is_sensitive(t)
    slot, mid = _model(sens)
    if not mid:
        # 涉敏且无授权模型：不把问题发给任何大模型，按规则直达系统工具（仍标来源）
        tool = rule_tool(t) if sens else None
        if tool and not (ctx.user["role"] == "institution" and tool in ("policy", "reports", "m4")):
            r = system_answer(ctx, tool, t, "", handlers)
            remember(ctx.open_id, t, "system:" + tool)
            _audit(ctx, "系统", tool, t, "rules", None)
            return r
        return None
    try:
        tool, q, kw = route(ctx, t, slot, mid)
    except Exception:  # noqa: BLE001
        return None
    if tool in SYSTEM_TOOLS:
        r = system_answer(ctx, tool, q, kw, handlers)
        remember(ctx.open_id, t, "system:" + tool)
        _audit(ctx, "系统", tool, t, slot, mid)
        return r
    # 兜底：一般知识 / 联网
    try:
        r = llm_answer(ctx, t, q, tool == "search", slot, mid, sens)
    except Exception:  # noqa: BLE001
        return None
    remember(ctx.open_id, t, r["route"], r["reply"])
    _audit(ctx, "联网搜索" if r["route"] == "search" else "大模型", tool, t, slot, mid, links=r.get("links"))
    return r


def _audit(ctx, route_, tool, t, slot, mid, links=None):
    db.audit(ctx.user, "机器人", f"智能问答·{route_}", tool, {"via": getattr(ctx, "via", ""), "text": t[:80], "slot": slot, "model": mid, "links": (links or [])[:5]})


def system_answer(ctx, tool, q, kw, handlers):
    if tool == "m4":
        r = h_m4(ctx)
    else:
        if ctx.user["role"] == "institution" and tool in ("policy", "reports"):
            return _r("该功能仅对普惠部内部账号开放。", "agent:system:" + tool, "拒绝")
        r = handlers[tool](ctx, q, kw)
    r = dict(r)
    r["intent"] = "agent:system:" + tool
    r["route"] = "system"
    r["reply"] = (r.get("reply") or "") + SYS_TAG
    return r


def _r(text, intent, status="已处理"):
    return {"reply": text, "files": [], "intent": intent, "status": status}


def h_m4(ctx):
    from ..feishu.service import foot
    if ctx.user["role"] == "institution":
        return _r("授信测算仅对普惠部内部账号开放。", "m4", "拒绝")
    s = db.q1("SELECT id, version, name, status, result, created_at FROM m4_schemes WHERE is_current=1 ORDER BY id DESC LIMIT 1") \
        or db.q1("SELECT id, version, name, status, result, created_at FROM m4_schemes ORDER BY id DESC LIMIT 1")
    if not s:
        return _r("系统中暂无授信额度测算方案（M4）。", "m4")
    res = db.jload(s["result"], {}) or {}
    tt = res.get("totals") or {}
    if not tt:
        return _r(f"测算方案 v{s['version']}「{s['name'] or ''}」尚无计算结果。", "m4")

    def f(v):
        return "—" if v is None else f"{v:,.2f} 万元"
    rows = sorted(res.get("rows") or [], key=lambda x: -(x.get("final") or 0))[:5]
    ls = [f"授信额度测算 · 方案 v{s['version']}「{s['name'] or ''}」（{s['status']}）",
          f"参与机构 {tt.get('count')} 家（测算池 {tt.get('pool_count')}，固定额度 {tt.get('fixed_count')}）",
          f"系数测算额度合计 {f(tt.get('sumX'))}；第三方调整合计 {f(tt.get('sumThird'))}；民投调整合计 {f(tt.get('sumMintouAdj'))}",
          f"常规最终额度合计 {f(tt.get('sumRegular'))}；民投专项 {f(tt.get('sumMintouSpecial'))}；最终合计 {f(tt.get('sumFinal'))}"]
    if rows:
        ls.append("最终额度前 5：" + "；".join(f"{x['name']} {f(x.get('final'))}" for x in rows))
    return _r("\n".join(ls) + foot(f"M4 授信测算方案 #{s['id']}", s["created_at"]), "m4")


def llm_answer(ctx, t, q, need_search, slot, mid, sens):
    links, ctxt = [], ""
    route_ = "llm"
    if need_search:
        sq = sanitize_query(q)
        if len(sq) >= 2:
            from ..search import service as S
            try:
                res = S.search(sq, ctx.user, max_results=5, time_range="month", purpose="机器人")
                links = [{"title": x.get("title", ""), "url": x.get("url", "")} for x in res if x.get("url")][:5]
                ctxt = "\n\n".join(f"[{i}] {x.get('title','')}\n{x.get('url','')}\n{(x.get('content') or x.get('snippet') or '')[:500]}" for i, x in enumerate(res[:5], 1))
                route_ = "search"
            except Exception:  # noqa: BLE001
                ctxt = ""
    h = _hist(ctx.open_id)["q"]
    msgs = [{"role": "system", "content":
             "你是粤港澳地区普惠金融/融资担保/再担保业务助手，在微信里回答同事问题。要求：中文、简洁（300 字内，可用 Markdown 列表）；"
             "不得编造任何本工作台的内部数据（机构额度、备案金额、使用率、测算结果等），若用户问到这类数字，回答“系统中未查到该数据”，并建议发送「额度 机构名」等指令；"
             "引用联网资料时用 [序号] 标注；不确定就说明不确定。"}]
    for x in h:
        msgs.append({"role": "user", "content": x["q"]})
        msgs.append({"role": "assistant", "content": x["a"] or "（已由系统查询回答）"})
    msgs.append({"role": "user", "content": (f"联网检索结果：\n{ctxt}\n\n" if ctxt else "") + f"问题：{q}"})
    out = _call(slot, mid, msgs, ctx.user, max_tokens=700, timeout=60).strip()
    if not out:
        raise RuntimeError("empty")
    cited = [(i, x) for i, x in enumerate(links, 1) if f"[{i}]" in out] or list(enumerate(links, 1))[:2]
    links = [x for _, x in cited]
    if links:
        out += "\n\n参考链接：\n" + "\n".join(f"[{i}] {x['title'][:40]} {x['url']}" for i, x in cited)
    return {"reply": out + AI_TAG, "files": [], "intent": "agent:" + route_, "status": "已处理", "route": route_, "links": [x["url"] for x in links]}
