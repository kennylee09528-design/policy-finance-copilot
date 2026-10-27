"""M3 三 Agent 流水线。

研究及写作：知识库(M1, FTS5) + 联网检索 + M5 数据(仅占位符，数值由系统从库中填入) → 大纲 → 分段写作（逐句 [Sk] 标注）
核对：规则层（确定性，100% 拦截：金额/比例/排名/案例/机构/文件名称 句须有出处且数字/名称能在所引来源中找到）
      + 可选大模型核对（仅追加提示，不能解除标红）→《引用来源登记表》
人工修改终稿 → 再核对；标红句须改正或填写理由人工确认，否则不能定稿
总结：初稿 vs 终稿 差异 → 写作规范条目 → 下次写作注入
"""
import difflib
import hashlib
import io
import json
import re
import threading
import time

from fastapi import HTTPException

from .. import db
from ..llm import service as L
from ..textcheck import CASE_RE, CITE_RE, RANK_RE, key_numbers, norm, number_in_source, risk_kinds, sentences
from . import config as C

RUNNING = ("排队", "检索资料", "写作中", "核对中")
_t0 = {}


# ---------------- 任务/进度 ----------------
def _task(tid):
    t = db.q1("SELECT * FROM m3_tasks WHERE id=?", (tid,))
    if not t:
        raise HTTPException(404, "写作任务不存在")
    for k, d in (("requirements", {}), ("sources", []), ("facts", []), ("outline", []), ("check_result", None), ("final_check", None),
                 ("confirmations", {}), ("summary_result", None), ("tokens", {}), ("agents", {})):
        t[k] = db.jload(t[k], d)
    return t


def _upd(tid, **kw):
    for k in ("requirements", "sources", "facts", "outline", "check_result", "final_check", "confirmations", "summary_result", "tokens", "agents"):
        if k in kw and not isinstance(kw[k], str):
            kw[k] = db.jdump(kw[k])
    kw["updated_at"] = db.now()
    db.execute(f"UPDATE m3_tasks SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), tid))


def _ev(tid, agent, stage, message, segment=None, tokens=0, snippet=""):
    el = int((time.time() - _t0.get(tid, time.time())) * 1000)
    db.execute("INSERT INTO m3_events(task_id,ts,agent,stage,message,segment,elapsed_ms,tokens,snippet) VALUES(?,?,?,?,?,?,?,?,?)",
               (tid, db.now(), agent, stage, message, segment, el, tokens, (snippet or "")[:300]))


def _llm(tid, agent, messages, user, tokens):
    cfg = C.get()[agent]
    r = L.run(C.SLOT[agent], messages, user, mid=C.model_of(agent),
              overrides={"temperature": cfg.get("temperature"), "top_p": cfg.get("top_p"), "max_tokens": int(cfg.get("max_tokens") or 8192)}, timeout=max(int(cfg.get("timeout") or 120), 180),
              ref=f"m3_task:{tid}", prompt_version=f"{agent} v{C.active_prompt(agent)['version']}")
    tokens[agent] = tokens.get(agent, 0) + r["tokens"]
    _upd(tid, tokens=tokens)
    return r


# ---------------- 写作辅助 ----------------
CN_NUM = "一二三四五六七八九十"
SKELETONS = {
    "日报": ["一、今日要点", "二、政策动态", "三、行业与市场动态", "四、同业与地方实践", "五、对我司业务的启示与建议"],
    "研究报告": ["一、摘要与核心结论", "二、研究背景与政策脉络", "三、现状分析", "四、主要问题与风险", "五、对策建议"],
}


def _is_daily(req):
    return "日报" in (req.get("genre") or "")


def _skeleton(req):
    g = req.get("genre") or ""
    for k, v in SKELETONS.items():
        if k in g:
            return v
    return ["一、基本情况", "二、主要做法与成效", "三、存在问题", "四、下一步工作建议"]


def _web_queries(title, req):
    qs = [title]
    if "广东" not in title:
        qs.append(f"广东 {title}")
    if _is_daily(req):
        qs += ["融资担保 再担保 最新政策", "普惠金融 小微企业 融资 最新"]
    else:
        qs.append(f"{title} 政策 文件")
    return qs[:4]


def _cn_heading(k, h):
    h = re.sub(r"^[#\s]+", "", h).strip()
    h = re.sub(r"^([一二三四五六七八九十]+[、.．]|\d+[、.．]|第[一二三四五六七八九十]+(?:部分|节|章)[、：:\s]*)\s*", "", h)
    return f"{CN_NUM[k - 1] if k <= 10 else k}、{h}"


def _clean_section(body, heading, valid):
    lines = [x for x in body.split("\n")]
    core = re.sub(r"^[一二三四五六七八九十]+、", "", heading).strip()
    while lines and (not lines[0].strip() or (core and core in lines[0] and len(lines[0].strip()) <= len(heading) + 6)):
        lines.pop(0)  # 去掉模型重复输出的节标题
    body = "\n".join(re.sub(r"^#+\s*", "", x) for x in lines).strip()
    body = re.sub(r"\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in valid else "【待核实】", body)
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    return re.sub(r"\n{3,}", "\n\n", body)


def _llm_retry(tid, agent, messages, user, tokens, min_len=1, tries=3):
    last = None
    for i in range(tries):
        try:
            r = _llm(tid, agent, messages, user, tokens)
            if len((r.get("content") or "").strip()) >= min_len:
                return r
            last = HTTPException(502, f"模型输出过短（{len((r.get('content') or '').strip())} 字）")
        except HTTPException as e:
            last = e
        _ev(tid, agent, "重试", f"第 {i + 1} 次调用未成功：{last.detail}，{'重试' if i + 1 < tries else '放弃'}")
        time.sleep(2 * (i + 1))
    raise last


# ---------------- 资料准备 ----------------
def _terms(title, req_text):
    from ..m2.config import get as m2cfg
    text = f"{title} {req_text}"
    terms = [k for k in m2cfg()["keywords"] if k in text]
    for seg in re.split(r"[\s，。、；：:（）()《》“”\"'？！,.;!?]|的|与|和|及|关于|对", title):
        seg = seg.strip()
        if len(seg) >= 3 and seg not in terms:
            terms.append(seg[:12])
    return terms[:12]


def retrieve_kb(title, req_text, scope):
    terms = _terms(title, req_text)
    lv = scope.get("levels") or C.LEVELS
    lay = scope.get("layers") or []
    cond = f" AND i.level IN ({','.join('?' * len(lv))})" + (f" AND i.layer IN ({','.join('?' * len(lay))})" if lay else "")
    n = int(scope.get("kb_max") or 8)
    long_t = [t for t in terms if len(t) >= 3]
    rows = []
    if long_t:
        fq = " OR ".join('"' + t.replace('"', "") + '"' for t in long_t)
        rows = db.q("SELECT i.* FROM m1_fts f JOIN m1_items i ON i.id=f.rowid WHERE m1_fts MATCH ? AND i.duplicate_of IS NULL" + cond +
                    " ORDER BY bm25(m1_fts) LIMIT ?", (fq, *lv, *lay, n))
    short = [t for t in terms if len(t) < 3]
    if len(rows) < n and short:  # trigram 不支持 <3 字的词，LIKE 兜底
        have = [r["id"] for r in rows] or [0]
        like = " OR ".join("(i.title LIKE ? OR i.content LIKE ?)" for _ in short)
        rows += db.q(f"SELECT i.* FROM m1_items i WHERE ({like}) AND i.duplicate_of IS NULL AND i.id NOT IN ({','.join('?' * len(have))})" + cond +
                     " ORDER BY i.id DESC LIMIT ?", (*[x for t in short for x in (f"%{t}%", f"%{t}%")], *have, *lv, *lay, n - len(rows)))
    return rows, terms


def m5_facts(data_date=None):
    from ..m2.brief import _m5_rows
    rows = _m5_rows(data_date or "9999-12-31")
    return [{"id": f"F{i}", "name": r["name"], "value": r["value"], "delta": r["delta"], "source": r["source"]} for i, r in enumerate(rows, 1)]


def _kb_source(r, chars, fallback_level=None):
    """知识库命中。非现行有效时带上效力提示，供写作资料引用。"""
    from ..m1.validity import attach
    st, nt = attach(r)
    level = (r.get("level") or fallback_level) if fallback_level is not None else r.get("level")
    return {"type": "知识库(M1)", "m1_id": r["id"], "title": r["title"], "url": r["url"], "publisher": r["publisher"] or "",
            "level": level, "pub_date": r["pub_date"], "excerpt": (r["summary"] or r["snippet"] or r["content"] or "")[:chars],
            "text": (r["content"] or r["snippet"] or "")[:20000], "validity_status": st, "validity_notice": nt}


def _materials(sources, facts, chars):
    L_ = ["【资料清单】"]
    for s in sources:
        head = f"{s['id']}｜{s['title']}｜{s['publisher']}（{s['level']}）｜{s.get('pub_date') or '日期未标注'}"
        if s.get("validity_notice"):
            head += f"｜{s['validity_notice']}"
        L_.append(head + f"\n{(s['excerpt'] or '')[:chars]}")
    if facts:
        L_.append("【本公司 M5 台账数据（只写占位符，系统填数）】")
        L_ += [f"{{{{{f['id']}}}}}：{f['name']}（{f['source']}）" for f in facts]
    return "\n\n".join(L_)


def style_guide_text(limit=30):
    rows = db.q("SELECT category, content FROM m3_style_guide WHERE enabled=1 ORDER BY id DESC LIMIT ?", (limit,))
    return rows, ("\n".join(f"- [{r['category']}] {r['content']}" for r in rows) or "（暂无）")


def _json(text, default):
    m = re.search(r"(\{.*\}|\[.*\])", text or "", re.S)
    try:
        return json.loads(m.group(1)) if m else default
    except ValueError:
        return default


# ---------------- 核对（规则层） ----------------
def sent_key(s):
    return hashlib.sha1(norm(CITE_RE.sub("", s)).encode()).hexdigest()[:12]


def rule_check(text, sources, facts, confirmations=None):
    smap = {s["id"]: s for s in sources}
    fact_txt = " ".join(f"{f['value']} {f.get('delta') or ''}" for f in facts)
    items, used = [], {}
    for p, si, s in sentences(text):
        kinds = risk_kinds(s)
        if "【数据缺失" in s:
            kinds.append("数据缺失")
        if not kinds:
            continue
        cites = CITE_RE.findall(s)
        body = CITE_RE.sub("", s)
        missing = []
        if not cites:
            status = "未找到出处"
        else:
            unknown = [c for c in cites if c != "M5" and c not in smap]
            missing += [f"引用编号 {c} 不存在" for c in unknown]
            src = "\n".join((smap[c].get("text") or smap[c].get("excerpt") or "") + smap[c]["title"] for c in cites if c in smap)
            for frag, n, u in key_numbers(body):
                if not (number_in_source(n, u, src) or ("M5" in cites and number_in_source(n, u, fact_txt))):
                    missing.append(f"数字「{frag}」在所引来源中未找到")
            for m in RANK_RE.finditer(body):
                if norm(m.group(0)) not in norm(src):
                    missing.append(f"排名表述「{m.group(0)}」在所引来源中未找到")
            for m in CASE_RE.finditer(body):
                if norm(m.group(1)) not in norm(src):
                    missing.append(f"名称「{m.group(1)}」在所引来源中未找到")
            if "数据缺失" in kinds:
                missing.append("M5 数据占位符无对应数据")
            status = "存疑（待核实）" if missing else "已核实"
        k = sent_key(s)
        conf = (confirmations or {}).get(k)
        it = {"key": k, "para": p, "sent": si, "text": s, "kinds": kinds, "cites": cites, "status": status, "missing": missing,
              "red": status != "已核实" and not conf, "confirmed": conf}
        items.append(it)
        for c in cites:
            used.setdefault(c, []).append(it)
    register = []
    for sid, its in used.items():
        paras = sorted({i["para"] for i in its})
        loc = "第" + "、".join(map(str, paras)) + "段"
        ok = all(i["status"] == "已核实" or i["confirmed"] for i in its)
        if sid == "M5":
            register.append({"no": "M5", "source_name": (facts[0]["source"] if facts else "M5 机构看板"), "level": "内部台账", "location": loc,
                             "excerpt": "；".join(f"{f['name']}：{f['value']}" for f in facts)[:300], "url": "", "pub_date": "", "status": "已核实"})
        elif sid in smap:
            s = smap[sid]
            register.append({"no": sid, "source_name": f"{s['publisher']}《{s['title']}》", "level": s["level"], "location": loc,
                             "excerpt": (s.get("excerpt") or "")[:200], "url": s["url"], "pub_date": s.get("pub_date") or "",
                             "status": "已核实" if ok else "存疑（待核实）"})
    for i in items:
        if not i["cites"]:
            register.append({"no": "—", "source_name": "（无出处）", "level": "", "location": f"第{i['para']}段第{i['sent']}句", "excerpt": i["text"][:200],
                             "url": "", "pub_date": "", "status": "人工确认" if i["confirmed"] else "未找到出处"})
    register.sort(key=lambda r: (r["no"] == "—", r["no"] != "M5", int(r["no"][1:]) if r["no"].startswith("S") and r["no"][1:].isdigit() else 0))
    red = [i for i in items if i["red"]]
    return {"items": items, "register": register, "red": len(red), "risky": len(items),
            "verified": sum(1 for i in items if i["status"] == "已核实"), "llm_warnings": []}


def _save_register(t, chk):
    db.execute("DELETE FROM m3_citations WHERE task_id=?", (t["id"],))
    for r in chk["register"]:
        db.execute("INSERT INTO m3_citations(doc_name,title,source_name,level,location,excerpt,url,pub_date,verify_status,query,provider,created_by,created_at,updated_at,task_id) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (t["title"], r["no"], r["source_name"], r["level"], r["location"], r["excerpt"], r["url"], r["pub_date"],
                    "存疑（待核实）" if r["status"] in ("存疑（待核实）",) else ("已核实" if r["status"] in ("已核实", "人工确认") else "未找到出处"),
                    "核对 Agent", "M3", "核对 Agent", db.now(), db.now(), t["id"]))


# ---------------- 主流程 ----------------
def create(body, user):
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "请输入题目")
    req = {"text": body.get("requirements") or "", "genre": body.get("genre") or "工作报告", "tone": body.get("tone") or "正式、简洁",
           "words": int(body.get("words") or 3000), "use_kb": bool(body.get("use_kb", True)), "use_web": bool(body.get("use_web", True)),
           "use_m5": bool(body.get("use_m5", False)), "data_date": body.get("data_date") or None}
    cfg = C.get()
    if not C.model_of("writer"):
        raise HTTPException(400, "研究及写作 Agent 尚未配置模型：请管理员在「系统管理 · M3 写作 Agent」中设置，或在页面上方选择")
    if req["use_m5"]:
        for a in C.AGENTS:
            mid = C.model_of(a)
            if mid and cfg[a].get("enabled", True):
                L.require_sensitive(mid, f"M3 {C.AGENTS[a]}")
    agents = {a: {"model_id": C.model_of(a), "temperature": cfg[a]["temperature"], "prompt_version": C.active_prompt(a)["version"],
                  "scope": cfg[a]["scope"]} for a in C.AGENTS}
    tid = db.execute("INSERT INTO m3_tasks(title,requirements,status,stage,agents,tokens,confirmations,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (title, db.jdump(req), "排队", "排队", db.jdump(agents), "{}", "{}", user["name"], db.now(), db.now()))
    db.audit(user, "M3", "新建写作任务", tid, {"title": title, **{k: req[k] for k in ("use_kb", "use_web", "use_m5")}})
    _t0[tid] = time.time()
    if body.get("sync"):
        _run(tid, user)
    else:
        threading.Thread(target=_run, args=(tid, user), daemon=True, name=f"m3-task-{tid}").start()
    return tid


def _run(tid, user):
    tokens = {}
    try:
        t = _task(tid)
        req, cfg = t["requirements"], C.get()
        ws = cfg["writer"]["scope"]
        # 1) 资料
        _upd(tid, status="检索资料", stage="研究：检索资料")
        sources = []
        if req["use_kb"]:
            rows, terms = retrieve_kb(t["title"], req["text"], ws)
            for r in rows:
                sources.append(_kb_source(r, ws.get("excerpt_chars", 600), "C2"))
            if _is_daily(req):  # 日报：补充 M1 最近采集的条目
                have = {r["id"] for r in rows}
                lv = ws.get("levels") or C.LEVELS
                for r in db.q(f"SELECT * FROM m1_items WHERE duplicate_of IS NULL AND level IN ({','.join('?' * len(lv))}) "
                              "ORDER BY COALESCE(pub_date, collected_at) DESC, id DESC LIMIT ?", (*lv, int(ws.get("kb_max") or 8))):
                    if r["id"] not in have:
                        rows.append(r)
                        sources.append(_kb_source(r, ws.get("excerpt_chars", 600), "C2"))
            _ev(tid, "writer", "检索", f"知识库检索（{'、'.join(terms[:6])}）命中 {len(rows)} 条")
        if req["use_web"]:
            try:
                from ..m1.classify import classify
                from ..m1.config import get as m1cfg
                from ..search import service as S
                res, seen_u, errs = [], set(), []
                for qy in _web_queries(t["title"], req):
                    try:
                        for x in S.search(qy, user, int(ws.get("web_max") or 6), "week" if _is_daily(req) else "year", purpose="M3"):
                            if x["url"] not in seen_u:
                                seen_u.add(x["url"])
                                res.append(x)
                    except HTTPException as e:
                        errs.append(str(e.detail))
                if not res and errs:
                    raise HTTPException(502, errs[0])
                res = res[:int(ws.get("web_max") or 6) * 2]
                mc = m1cfg()
                known = {s["url"] for s in sources}
                n0 = len(sources)
                for x in res:
                    c = classify(x["url"], mc) or {}
                    lv = c.get("level", "C2")
                    if x["url"] in known or lv not in (ws.get("levels") or C.LEVELS):
                        continue
                    body = x.get("snippet") or ""
                    if ws.get("fetch_web", True):
                        try:  # 抓取原文正文，供写作与核对比对（失败则仅用摘要）
                            from ..m1.fetch import fetch
                            body = (fetch(x["url"], timeout=10).get("text") or "")[:20000] or body
                        except Exception:  # noqa: BLE001
                            pass
                    sources.append({"type": "联网检索", "title": x["title"], "url": x["url"], "publisher": c.get("publisher", x.get("site") or ""),
                                    "level": lv, "pub_date": x.get("date"), "excerpt": body[:ws.get("excerpt_chars", 600)],
                                    "text": body + "\n" + (x.get("snippet") or "")})
                _ev(tid, "writer", "检索", f"联网检索返回 {len(res)} 条，纳入 {len(sources) - n0} 条（知识范围：{'/'.join(ws.get('levels') or [])}）")
            except HTTPException as e:
                _ev(tid, "writer", "检索", f"联网检索跳过：{e.detail}")
        for i, s in enumerate(sources, 1):
            s["id"] = f"S{i}"
        facts = m5_facts(req.get("data_date")) if req["use_m5"] else []
        if req["use_m5"]:
            _ev(tid, "writer", "检索", f"M5 数据库取数 {len(facts)} 项（数值不经大模型，由系统填入）")
        _upd(tid, sources=sources, facts=facts)
        # 2) 大纲
        guide_rows, guide = style_guide_text(cfg["summarizer"]["scope"].get("max_entries", 30))
        sys_p = C.active_prompt("writer")["content"].replace("{tone}", req["tone"]).replace("{genre}", req["genre"]).replace("{style_guide}", guide)
        mats = _materials(sources, facts, ws.get("excerpt_chars", 600))
        base = f"题目：{t['title']}\n写作要求：{req['text'] or '无'}\n目标字数：约 {req['words']} 字\n\n{mats}"
        sid_list = "、".join(x["id"] for x in sources) or "（无）"
        rules = (f"\n\n【硬性要求】1. 只能引用资料清单中存在的编号（{sid_list}），不得编造编号；资料清单为空或无对应资料时，不写具体数字、排名、案例，"
                 "需要数据处写「【待核实】」。2. " + ("本公司数据只写 {{Fk}} 占位符。" if facts else "本任务未接入本公司台账数据，严禁写 {{F1}} 之类占位符或任何本公司业务数字，确需时写「【待核实】」。") +
                 " 3. 每段围绕本节主题充分展开，必须写完整，以句号结束，不要输出 Markdown 标题符号（#）和节标题。")
        _upd(tid, status="写作中", stage="写作：生成大纲")
        _ev(tid, "writer", "大纲", f"注入写作规范 {len(guide_rows)} 条，资料 {len(sources)} 份，开始生成大纲（文体：{req['genre']}）")
        skel = _skeleton(req)
        outline = []
        try:
            r = _llm_retry(tid, "writer", [{"role": "system", "content": sys_p}, {"role": "user", "content": base +
                           f"\n\n请先给出大纲，仅输出 JSON 数组：[{{\"heading\":\"一、……\",\"points\":[\"……\"]}}]。建议结构（可调整措辞，不得缺节）：{'；'.join(skel)}。"
                           "每节 2~4 个要点，要点须能由资料清单支撑。"}], user, tokens, min_len=20)
            outline = _json(r["content"], [])
            _ev(tid, "writer", "大纲", "大纲已生成", tokens=r["tokens"])
        except HTTPException as e:
            _ev(tid, "writer", "大纲", f"大纲生成失败，改用标准结构：{e.detail}")
        if not isinstance(outline, list) or len(outline) < 2:
            outline = [{"heading": h, "points": []} for h in skel]
        outline = [{"heading": str(o.get("heading") or o) if isinstance(o, dict) else str(o), "points": (o.get("points") or []) if isinstance(o, dict) else []} for o in outline][:8]
        outline = [{**o, "heading": _cn_heading(k, o["heading"])} for k, o in enumerate(outline, 1)]
        _upd(tid, outline=outline)
        _ev(tid, "writer", "大纲", f"大纲 {len(outline)} 节", snippet=" / ".join(o["heading"] for o in outline))
        # 3) 分段写作（逐节生成 → 截断续写 → 失败重试 → 组装）
        parts, done_ = [], []
        per = max(500, req["words"] // len(outline))
        valid = {x["id"] for x in sources}
        for k, o in enumerate(outline, 1):
            _upd(tid, stage=f"写作：第 {k}/{len(outline)} 节")
            _ev(tid, "writer", "分段写作", f"开始第 {k}/{len(outline)} 节：{o['heading']}", segment=k)
            msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": base +
                    f"\n\n大纲：{json.dumps(outline, ensure_ascii=False)}\n\n现在只写第 {k} 节「{o['heading']}」（要点：{'；'.join(map(str, o['points'])) or '自拟'}），"
                    f"{per}~{int(per * 1.4)} 字；每个事实句末标注 [Sk]。" + rules}]
            try:
                r = _llm_retry(tid, "writer", msgs, user, tokens, min_len=20)
                body = r["content"].strip()
                if r.get("finish_reason") == "length":  # 截断 → 续写一次
                    r2 = _llm_retry(tid, "writer", msgs + [{"role": "assistant", "content": body},
                                    {"role": "user", "content": "上文因长度被截断，请从断处接着写完本节，不要重复已写内容。"}], user, tokens, min_len=1)
                    body += r2["content"].strip()
                    _ev(tid, "writer", "分段写作", f"第 {k} 节输出被截断，已续写", segment=k)
                body = _clean_section(body, o["heading"], valid)
                done_.append(k)
            except HTTPException as e:
                body = f"【本节生成失败，待补写：{e.detail}】"
            parts.append(f"{o['heading']}\n{body}")
            _ev(tid, "writer", "分段写作", f"第 {k} 节完成（{len(body)} 字）", segment=k, tokens=r["tokens"] if k in done_ else 0, snippet=body[:120])
        if not done_:
            raise HTTPException(502, "各节均生成失败，请检查写作模型配置")
        _ev(tid, "writer", "组装", f"全文 {len(outline)} 节，成功 {len(done_)} 节，{sum(len(x) for x in parts)} 字")
        draft = "\n".join(parts)
        fmap = {f["id"]: f for f in facts}
        draft = re.sub(r"\{\{\s*(F\d+)\s*\}\}(\s*\[M5\])?", lambda m: f"{fmap[m.group(1)]['value']}[M5]" if m.group(1) in fmap else "【待核实】", draft)
        _upd(tid, draft=draft, final=draft, status="核对中", stage="核对：规则核验")
        # 4) 核对
        chk = rule_check(draft, sources, facts)
        _ev(tid, "checker", "规则核验", f"风险句 {chk['risky']} 句：已核实 {chk['verified']}，标红 {chk['red']}")
        if cfg["checker"].get("enabled", True) and C.model_of("checker"):
            _upd(tid, stage="核对：大模型核对")
            try:
                r = _llm(tid, "checker", [{"role": "system", "content": C.active_prompt("checker")["content"]},
                                          {"role": "user", "content": f"{mats}\n\n【待核对稿件】\n{draft}"}], user, tokens)
                chk["llm_warnings"] = [i for i in (_json(r["content"], {}) or {}).get("issues", []) if isinstance(i, dict)][:30]
                _ev(tid, "checker", "大模型核对", f"提示 {len(chk['llm_warnings'])} 条（仅提示，不解除标红）", tokens=r["tokens"])
            except HTTPException as e:
                _ev(tid, "checker", "大模型核对", f"跳过：{e.detail}")
        t = _task(tid)
        _save_register(t, chk)
        fchk = chk
        if chk["red"] and cfg["checker"].get("auto_revise", True):
            _upd(tid, check_result=chk, final_check=chk, stage="核对：自动修订标红句")
            try:
                auto_revise(tid, user)
                fchk = _task(tid)["final_check"]
            except Exception as e:  # noqa: BLE001
                _ev(tid, "checker", "自动修订", f"跳过：{type(e).__name__}: {e}")
        st = "待人工修改（有标红）" if fchk["red"] else "待人工定稿"
        _upd(tid, check_result=chk, final_check=fchk, status=st, stage="等待人工修改终稿")
        _ev(tid, "checker", "完成", f"《引用来源登记表》{len(fchk['register'])} 行；{st}")
    except HTTPException as e:
        _upd(tid, status="失败", stage="失败", error=str(e.detail), tokens=tokens)
        _ev(tid, "system", "失败", str(e.detail))
    except Exception as e:  # noqa: BLE001
        _upd(tid, status="失败", stage="失败", error=f"{type(e).__name__}: {e}", tokens=tokens)
        _ev(tid, "system", "失败", f"{type(e).__name__}: {e}")


def detail(tid):
    t = _task(tid)
    t["events"] = db.q("SELECT * FROM m3_events WHERE task_id=? ORDER BY id", (tid,))
    t["elapsed_ms"] = t["events"][-1]["elapsed_ms"] if t["events"] else 0
    t["tokens_total"] = sum(t["tokens"].values())
    for s in t["sources"]:
        s.pop("text", None)
    return t


def save_final(tid, final, user):
    t = _task(tid)
    if t["status"] in RUNNING:
        raise HTTPException(409, "任务仍在进行中")
    if t["status"] in ("已定稿", "已总结"):
        raise HTTPException(409, "已定稿，不可修改")
    chk = rule_check(final, t["sources"], t["facts"], t["confirmations"])
    _upd(tid, final=final, final_check=chk, status="待人工修改（有标红）" if chk["red"] else "待人工定稿")
    _save_register(t, chk)
    db.audit(user, "M3", "保存终稿并复核", tid, {"red": chk["red"]})
    return chk


def confirm(tid, key, reason, user):
    if not (reason or "").strip():
        raise HTTPException(400, "人工确认须填写理由（如：已与原始文件核对）")
    t = _task(tid)
    c = t["confirmations"]
    c[key] = {"by": user["name"], "at": db.now(), "reason": reason.strip()}
    _upd(tid, confirmations=c)
    db.audit(user, "M3", "人工确认标红句", tid, {"key": key, "reason": reason})
    return save_final(tid, t["final"], user)


def finalize(tid, user):
    t = _task(tid)
    chk = rule_check(t["final"] or "", t["sources"], t["facts"], t["confirmations"])
    if chk["red"]:
        raise HTTPException(409, f"仍有 {chk['red']} 句标红（金额/比例/排名/案例等缺少可核实出处），请修改或人工确认后再定稿")
    _save_register(t, chk)
    _upd(tid, final_check=chk, status="已定稿", stage="已定稿", finalized_at=db.now())
    db.audit(user, "M3", "定稿", tid)
    return chk


def diff_ops(a, b):
    sa = [s for _, _, s in sentences(a)]
    sb = [s for _, _, s in sentences(b)]
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
        if tag != "equal":
            ops.append({"op": {"replace": "修改", "delete": "删除", "insert": "新增"}[tag], "draft": "".join(sa[i1:i2]), "final": "".join(sb[j1:j2])})
    return ops


def _rule_entries(ops):
    out = []
    for o in ops:
        if o["op"] == "修改":
            sm = difflib.SequenceMatcher(None, o["draft"], o["final"])
            for tag, i1, i2, j1, j2 in sm.get_opcodes():
                a, b = o["draft"][i1:i2].strip(), o["final"][j1:j2].strip()
                if tag == "replace" and 1 < len(a) <= 20 and 1 < len(b) <= 20 and not re.search(r"\d", a + b):
                    out.append({"category": "措辞", "content": f"用「{b}」替代「{a}」"})
        elif o["op"] == "删除" and len(o["draft"]) <= 60:
            out.append({"category": "结构", "content": f"避免类似表述：「{CITE_RE.sub('', o['draft'])[:50]}」"})
    seen, res = set(), []
    for e in out:
        if e["content"] not in seen:
            seen.add(e["content"])
            res.append(e)
    return res[:10]


def summarize(tid, user):
    t = _task(tid)
    if t["status"] not in ("已定稿", "已总结"):
        raise HTTPException(409, "请先定稿，再由总结 Agent 对比初稿与终稿")
    ops = diff_ops(t["draft"] or "", t["final"] or "")
    entries, method, tokens = [], "规则", t["tokens"]
    cfg = C.get()["summarizer"]
    _t0.setdefault(tid, time.time())
    if ops and cfg.get("enabled", True) and C.model_of("summarizer"):
        try:
            r = _llm(tid, "summarizer", [{"role": "system", "content": C.active_prompt("summarizer")["content"]},
                                         {"role": "user", "content": json.dumps(ops[:40], ensure_ascii=False)}], user, tokens)
            entries = [e for e in (_json(r["content"], {}) or {}).get("entries", []) if isinstance(e, dict) and e.get("content")][:10]
            method = "总结 Agent"
            _ev(tid, "summarizer", "总结", f"提炼写作规范 {len(entries)} 条", tokens=r["tokens"])
        except HTTPException as e:
            _ev(tid, "summarizer", "总结", f"模型不可用，改用规则提炼：{e.detail}")
    if not entries:
        entries = _rule_entries(ops)
    ids = []
    for e in entries:
        cat = e.get("category") if e.get("category") in ("措辞", "结构", "口径") else "措辞"
        ids.append(db.execute("INSERT INTO m3_style_guide(category,content,source_task_id,enabled,created_by,created_at) VALUES(?,?,?,1,?,?)",
                              (cat, str(e["content"])[:200], tid, "总结 Agent", db.now())))
    res = {"diff": ops, "n_changes": len(ops), "entries": entries, "entry_ids": ids, "method": method}
    _upd(tid, summary_result=res, status="已总结", stage="已总结")
    db.audit(user, "M3", "总结写作规范", tid, {"changes": len(ops), "entries": len(entries)})
    return res


# ---------------- 自动修订（核对后，逐条处理标红句） ----------------
AUTH_LEVELS = ("A1", "A2", "B1")
PENDING = "【待核实】"


def _verified_with(sent, src, facts):
    """sent 去掉原引用、改引 src 后能否通过规则核验。"""
    body = CITE_RE.sub("", sent).replace(PENDING, "").strip()
    end = body[-1] if body and body[-1] in "。！？；!?;" else ""
    cand = (body[:-1] if end else body) + f"[{src['id']}]" + end
    chk = rule_check(cand, [src], facts)
    return cand if chk["items"] and not chk["red"] else None


def _find_support(sent, sources, facts, user, budget):
    """先在已有资料中找，再查知识库，再联网（仅权威等级）；返回 (改写后的句子, 新增来源或 None)。"""
    for s in sources:
        c = _verified_with(sent, s, facts)
        if c:
            return c, None
    body = CITE_RE.sub("", sent).replace(PENDING, "")
    q = re.sub(r"\s+", " ", body)[:60]
    rows, _ = retrieve_kb(q, "", {"levels": list(AUTH_LEVELS), "kb_max": 5})
    known = {s.get("url") for s in sources}
    cands = [_kb_source(r, 600) for r in rows if r["url"] not in known]
    if budget["web"] > 0:
        budget["web"] -= 1
        try:
            from ..m1.classify import classify
            from ..m1.config import get as m1cfg
            from ..m1.fetch import fetch
            from ..search import service as S
            mc = m1cfg()
            for x in S.search(q, user, 5, "none", purpose="M3"):
                lv = (classify(x["url"], mc) or {}).get("level", "C2")
                if lv not in AUTH_LEVELS or x["url"] in known:
                    continue
                text = x.get("snippet") or ""
                try:
                    text = (fetch(x["url"], timeout=10).get("text") or "")[:20000] or text
                except Exception:  # noqa: BLE001
                    pass
                cands.append({"type": "联网检索", "title": x["title"], "url": x["url"], "publisher": (classify(x["url"], mc) or {}).get("publisher", x.get("site") or ""),
                              "level": lv, "pub_date": x.get("date"), "excerpt": text[:600], "text": text + "\n" + (x.get("snippet") or "")})
        except HTTPException:
            pass
    for c in cands:
        c["id"] = f"S{len(sources) + 1}"
        v = _verified_with(sent, c, facts)
        if v:
            return v, c
    return None, None


def _rewrite(tid, sent, sources, facts, user, tokens):
    """请写作模型去掉无法核实的数字/名称；结果仍须通过规则核验，否则删除该句。"""
    if not C.model_of("writer"):
        return ""
    cites = [c for c in CITE_RE.findall(sent) if c != "M5"]
    ctx = "\n".join(f"{s['id']}｜{s['title']}\n{(s.get('text') or s.get('excerpt') or '')[:1500]}" for s in sources if s["id"] in cites)
    try:
        r = _llm(tid, "writer", [{"role": "system", "content": "你是公文审校员，只做删减改写，绝不新增任何事实、数字、名称。"},
                                 {"role": "user", "content": f"下面这句话中的数字、排名或机构/文件名称无法在所引资料中核实：\n「{sent}」\n所引资料：\n{ctx or '（无）'}\n"
                                  "请改写为不含无法核实的数字、排名、具体名称的定性表述，保留原有引用编号；若删去后没有实质内容，只输出「删除」。只输出改写后的一句话。"}], user, tokens)
    except HTTPException:
        return ""
    out = (r["content"] or "").strip().strip("「」\"")
    if not out or out.startswith("删除") or len(out) > len(sent) + 20:
        return ""
    chk = rule_check(out, sources, facts)
    return out if not chk["red"] else ""


def revise_task(tid, user):
    t = _task(tid)
    if t["status"] in RUNNING:
        raise HTTPException(409, "任务仍在进行中")
    if t["status"] in ("已定稿", "已总结"):
        raise HTTPException(409, "已定稿，不可修改")
    _t0.setdefault(tid, time.time())
    db.audit(user, "M3", "自动修订标红句", tid)
    return auto_revise(tid, user)


def auto_revise(tid, user, web_budget=12):
    """对标红句：找真实出处补引 → 否则删去不可核实内容改写 → 否则删句；剩余标红句行内加【待核实】。返回 (修订前, 修订后) 标红数。"""
    t = _task(tid)
    sources, facts, tokens = t["sources"], t["facts"], t["tokens"]
    # 详情接口不返回 text；从任务表取的 sources 含 text
    text = t["final"] or t["draft"] or ""
    chk0 = rule_check(text, sources, facts, t["confirmations"])
    budget = {"web": web_budget}
    stats = {"补引": 0, "改写": 0, "删除": 0}
    _ev(tid, "checker", "自动修订", f"开始：标红 {chk0['red']} 句")
    for it in [i for i in chk0["items"] if i["red"]]:
        sent = it["text"]
        if sent not in text:
            continue
        new, src = _find_support(sent, sources, facts, user, budget)
        if new:
            if src:
                sources.append(src)
            text = text.replace(sent, new, 1)
            stats["补引"] += 1
            continue
        rw = _rewrite(tid, sent, sources, facts, user, tokens)
        text = text.replace(sent, rw, 1)
        stats["改写" if rw else "删除"] += 1
    chk = rule_check(text, sources, facts, t["confirmations"])
    for it in [i for i in chk["items"] if i["red"]]:  # 剩余标红：行内标注
        s = it["text"]
        if PENDING not in s and s in text:
            end = s[-1] if s[-1] in "。！？；!?;" else ""
            text = text.replace(s, (s[:-1] if end else s) + PENDING + end, 1)
    text = re.sub(r"\n{3,}", "\n\n", text)
    chk = rule_check(text, sources, facts, t["confirmations"])
    _upd(tid, sources=sources, final=text, final_check=chk, tokens=tokens,
         status="待人工修改（有标红）" if chk["red"] else "待人工定稿", stage="等待人工修改终稿")
    _save_register(_task(tid), chk)
    _ev(tid, "checker", "自动修订", f"完成：补充出处 {stats['补引']} 句、改写 {stats['改写']} 句、删除 {stats['删除']} 句；标红 {chk0['red']} → {chk['red']}")
    return {"before": chk0["red"], "after": chk["red"], **stats}


# ---------------- 导出 ----------------
def to_markdown(tid):
    t = _task(tid)
    chk = t["final_check"] or t["check_result"] or {"register": []}
    L_ = [f"# {t['title']}", "", t["final"] or t["draft"] or "", "", "## 附：引用来源登记表", "",
          "| 序号 | 来源编号 | 来源名称 | 来源类型 | 出处位置 | 原文摘录 | 链接 | 发布日期 | 核验状态 |", "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(chk["register"], 1):
        L_.append(f"| {i} | {r['no']} | {r['source_name']} | {r['level']} | {r['location']} | {(r['excerpt'] or '').replace('|', '/').replace(chr(10), ' ')[:120]} | {r['url']} | {r['pub_date']} | {r['status']} |")
    if t["summary_result"]:
        L_ += ["", "## 附：修改痕迹说明", f"初稿 → 终稿共 {t['summary_result']['n_changes']} 处修改；沉淀写作规范 {len(t['summary_result']['entries'])} 条。"]
    return "\n".join(L_) + "\n"


def to_docx(tid):
    from docx import Document
    from docx.shared import Pt, RGBColor
    t = _task(tid)
    chk = t["final_check"] or t["check_result"] or {"register": [], "items": []}
    reds = {i["text"] for i in chk.get("items", []) if i.get("red")}
    doc = Document()
    doc.styles["Normal"].font.name = "仿宋"
    doc.styles["Normal"].font.size = Pt(12)
    doc.add_heading(t["title"], 0)
    if t["status"] not in ("已定稿", "已总结"):
        doc.add_paragraph("【未定稿：红色句子为核对未通过内容】")
    for para in (t["final"] or t["draft"] or "").split("\n"):
        if not para.strip():
            continue
        if re.match(r"^[一二三四五六七八九十]+、", para) and len(para) < 40:
            doc.add_heading(para, 1)
            continue
        p = doc.add_paragraph()
        for m in re.finditer(r"[^。！？；!?;]+[。！？；!?;]?", para):
            run = p.add_run(m.group(0))
            if m.group(0).strip() in reds:
                run.font.color.rgb = RGBColor(0xC0, 0, 0)
    doc.add_heading("附：引用来源登记表", 1)
    doc.add_paragraph("说明：来源编号 S1、S2… 为本报告资料清单中的第 1、2… 份资料，正文句末 [Sk] 表示该句出处；[M5] 表示数字由系统从机构看板（M5）台账填入；"
                      "「【待核实】」表示系统内暂无可核实数据，需人工补充。来源等级：A1 官方正式文件、A2 官方发布、B1 权威媒体、B2 一般媒体、C1 自媒体、C2 其他线索。")
    cols = ["序号", "来源编号", "来源名称", "来源类型", "出处位置", "原文摘录", "链接", "发布日期", "核验状态"]
    tb = doc.add_table(rows=1, cols=len(cols))
    tb.style = "Table Grid"
    for i, c in enumerate(cols):
        tb.rows[0].cells[i].text = c
    for i, r in enumerate(chk["register"], 1):
        cells = tb.add_row().cells
        for j, v in enumerate([str(i), r["no"], r["source_name"], r["level"], r["location"], (r["excerpt"] or "")[:150], r["url"], r["pub_date"] or "", r["status"]]):
            cells[j].text = v or ""
    if t["summary_result"]:
        doc.add_heading("附：修改痕迹说明", 1)
        sr = t["summary_result"]
        doc.add_paragraph(f"初稿 → 终稿共 {sr['n_changes']} 处修改；总结 Agent（{sr['method']}）沉淀写作规范 {len(sr['entries'])} 条：")
        for e in sr["entries"]:
            doc.add_paragraph(f"[{e.get('category')}] {e.get('content')}", style="List Bullet")
        for o in sr["diff"][:30]:
            doc.add_paragraph(f"{o['op']}：{o['draft'][:80] or '（无）'} → {o['final'][:80] or '（无）'}", style="List Bullet")
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


def rerun(tid, user):
    """已中断 / 失败的任务重新运行（保留原题目与要求，重置中间结果）。"""
    t = _task(tid)
    if t["status"] not in ("已中断", "失败"):
        raise HTTPException(409, "只有「已中断」或「失败」的任务可以重新运行")
    if t["requirements"].get("use_m5"):
        for a in C.AGENTS:
            mid = C.model_of(a)
            if mid and C.get()[a].get("enabled", True):
                L.require_sensitive(mid, f"M3 {C.AGENTS[a]}")
    _upd(tid, status="排队", stage="排队", error=None, draft=None, final=None, check_result=None, final_check=None, outline=[], sources=[], facts=[])
    _ev(tid, "system", "重新运行", f"{user['name']} 重新运行任务")
    db.audit(user, "M3", "重新运行写作任务", tid)
    _t0[tid] = time.time()
    threading.Thread(target=_run, args=(tid, user), daemon=True, name=f"m3-task-{tid}").start()
    return {"ok": True}
