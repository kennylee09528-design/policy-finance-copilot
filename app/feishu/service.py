"""飞书机器人业务层：事件去重 / 限流 / 群聊@ 判断 / 身份与权限 / 指令与自然语言意图路由 / 各能力处理 / 多轮对话 / 审计。

原则：
- 数字只来自数据库（M5 看板、M3 报告、M2 简报…），大模型只做「意图识别」，且只看到用户的提问文字，不接触任何业务数据；
- 权限随绑定账号的角色：合作机构账号只能查本机构 M5 与已发布简报；内部资料类功能（M1/M3/PPT/邮件）仅内部账号；
- 每条回答注明数据来源与数据时间；每条消息写入事件日志与操作留痕（含绑定的账号）。"""
import json
import re
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi import HTTPException

from .. import db
from .. import mailer as M
from .. import watermark as W
from ..llm import service as L
from . import api as A
from . import config as C
from . import identity as I

POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="feishu")
_hits: dict[str, deque] = defaultdict(deque)
_cleanup = {"t": 0.0}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@(?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,}")
STATE_TTL_MIN = 30
INTERNAL_ONLY = {"policy", "reports", "report_file", "ppt_file", "ppt_start", "mail"}
DATA_INTENTS = {"quota", "alerts", "reports", "report_file", "ppt_file", "ppt_start", "mail"}  # 群聊默认不回答（避免内部数据被群内他人看到）
PORT_NAMES = {"regular": "常规业务", "tech": "科技创新专项", "private": "民间投资专项", "t2t": "总对总"}


# ---------------------------------------------------------------- 入口：去重 + 异步处理
def _seen(key):
    if not key:
        return False
    with db._lock:
        if db.q1("SELECT 1 x FROM feishu_seen WHERE key=?", (key,)):
            return True
        db.execute("INSERT INTO feishu_seen(key,ts) VALUES(?,?)", (key, db.now()))
    if time.time() - _cleanup["t"] > 3600:
        _cleanup["t"] = time.time()
        db.execute("DELETE FROM feishu_seen WHERE ts < ?", ((datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),))
        db.execute("DELETE FROM feishu_events WHERE ts < ?", ((datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S"),))
    return False


def dispatch(payload, source="长连接", sync=False):
    """接收到事件（长连接回调 / HTTP 回调）后调用：快速去重后交给线程池处理，立即返回（飞书要求 3 秒内响应）。"""
    if not C.get()["enabled"]:
        return
    hdr, ev = payload.get("header") or {}, payload.get("event") or {}
    if hdr.get("event_type") != "im.message.receive_v1":
        return
    if _seen(hdr.get("event_id")) or _seen((ev.get("message") or {}).get("message_id")):
        return  # 飞书重试的重复事件
    if sync:
        _safe(payload, source)
    else:
        POOL.submit(_safe, payload, source)


def _safe(payload, source):
    try:
        process(payload, source)
    except Exception as e:  # noqa: BLE001
        db.audit({"name": "飞书机器人", "username": "", "role": "system"}, "飞书", "处理异常", "", str(e)[:300])


class Ctx:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _mentioned_bot(cfg, api, mentions):
    if not mentions:
        return False
    bot = cfg.get("bot_open_id")
    if not bot:
        try:
            info = api.bot_info()
            bot = info["open_id"]
            cfg["bot_open_id"], cfg["bot_name"] = bot, info["name"]
            db.set_setting(C.CFG_KEY, cfg)
        except Exception:  # noqa: BLE001
            return True  # 取不到机器人身份时，只要有人被 @ 就响应（宁可响应也不漏）
    return any(((m.get("id") or {}).get("open_id") == bot) for m in mentions)


def _text_of(msg, mentions):
    try:
        t = json.loads(msg.get("content") or "{}").get("text", "")
    except ValueError:
        t = ""
    for m in mentions or []:
        t = t.replace(m.get("key") or "\0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _rate_ok(open_id, per_min):
    now = time.time()
    q = _hits[open_id]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= per_min:
        return False
    q.append(now)
    return True


def _log(ctx, **kw):
    if not getattr(ctx, "log_id", None):
        ctx.log_id = db.execute("INSERT INTO feishu_events(ts,event_id,message_id,open_id,chat_id,chat_type,text,source,status) VALUES(?,?,?,?,?,?,?,?,?)",
                                (db.now(), ctx.event_id, ctx.message_id, ctx.open_id, ctx.chat_id, ctx.chat_type, re.sub(r"(绑定\s*)[A-Za-z0-9]{6,12}", r"\1******", ctx.text)[:300],
                                 ctx.source, "处理中"))
    if kw:
        db.execute(f"UPDATE feishu_events SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), ctx.log_id))


def process(payload, source="长连接"):
    cfg = C.get()
    hdr, ev = payload.get("header") or {}, payload.get("event") or {}
    msg, sender = ev.get("message") or {}, ev.get("sender") or {}
    if sender.get("sender_type") not in (None, "user"):
        return
    api = A.get_api()
    mentions = msg.get("mentions") or []
    group = msg.get("chat_type") == "group"
    if group and not _mentioned_bot(cfg, api, mentions):
        return  # 群聊只响应 @ 机器人的消息
    ctx = Ctx(api=api, cfg=cfg, open_id=(sender.get("sender_id") or {}).get("open_id", ""), chat_id=msg.get("chat_id"), chat_type=msg.get("chat_type"),
              group=group, message_id=msg.get("message_id"), event_id=hdr.get("event_id"), source=source, user=None, text=_text_of(msg, mentions), log_id=None)
    _log(ctx)
    res = {"reply": "", "files": [], "intent": "", "status": "已处理"}
    try:
        if msg.get("message_type") != "text":
            res.update(reply="目前只支持文字消息，请直接用文字提问，例如发送「帮助」。", status="忽略（非文字）")
        elif not _rate_ok(ctx.open_id, int(cfg["rate_per_min"])):
            res.update(reply=f"操作太频繁了（每分钟最多 {cfg['rate_per_min']} 条），请稍后再试。", status="限流")
        else:
            res.update(handle(ctx, ctx.text))
    except HTTPException as e:
        res.update(reply=f"⚠ {e.detail if isinstance(e.detail, str) else '请求未能完成'}", status="拒绝", error=str(e.detail)[:200])
    except Exception as e:  # noqa: BLE001
        res.update(reply="抱歉，处理时出错了，已记录，请稍后再试。", status="错误", error=f"{type(e).__name__}: {e}"[:300])
    err = None
    try:
        send(ctx, res["reply"], res["files"])
    except Exception as e:  # noqa: BLE001
        err = f"发送失败：{e}"[:300]
    _log(ctx, username=(ctx.user or {}).get("username"), intent=res["intent"], status="发送失败" if err else res["status"], reply=(res["reply"] or "")[:400], error=err or res.get("error"))
    if ctx.user:
        db.audit(ctx.user, "飞书", f"飞书消息·{res['intent'] or '其他'}", ctx.open_id[-6:] if ctx.open_id else "", {"status": res["status"], "chat": ctx.chat_type,
                 "files": [f[0] for f in res["files"]], "text": re.sub(r"(绑定\s*)\S+", r"\1***", ctx.text)[:80], "via": "飞书"})


def send(ctx, text, files):
    api = ctx.api
    if text:
        text = text[:6000]
        try:
            api.reply_text(ctx.message_id, text) if ctx.group else api.send_text(ctx.chat_id, text)
        except A.FeishuError:
            api.send_text(ctx.chat_id, text)
    for name, data, _mime in files:
        if len(data) > 30 * 1024 * 1024:
            api.send_text(ctx.chat_id, f"文件 {name} 超过飞书 30MB 上限，请在网页端下载。")
            continue
        api.send_file(ctx.chat_id, api.upload_file(name, data))


# ---------------------------------------------------------------- 多轮对话状态
def state_get(ctx):
    r = db.q1("SELECT * FROM feishu_state WHERE open_id=?", (ctx.open_id,))
    if not r:
        return None
    if r["updated_at"] < (datetime.now() - timedelta(minutes=STATE_TTL_MIN)).strftime("%Y-%m-%d %H:%M:%S"):
        state_clear(ctx)
        return None
    s = db.jload(r["state"], {})
    return s if s.get("chat_id") == ctx.chat_id else None


def state_set(ctx, s):
    s["chat_id"] = ctx.chat_id
    db.execute("INSERT INTO feishu_state(open_id,state,updated_at) VALUES(?,?,?) ON CONFLICT(open_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at",
               (ctx.open_id, db.jdump(s), db.now()))


def state_clear(ctx):
    db.execute("DELETE FROM feishu_state WHERE open_id=?", (ctx.open_id,))


# ---------------------------------------------------------------- 文本工具
def wan(v):
    return "—" if v is None else f"{v:,.2f} 万元"


def pct(v):
    return "—" if v is None else f"{v * 100:.2f}%"


def foot(src, when=None):
    return f"\n——\n数据来源：{src}\n" + (f"数据时间：{when}\n" if when else "") + f"查询时间：{db.now()}"


BIND_HELP = ("您还没有绑定工作台账号，暂时不能查询。\n"
             "绑定方法：\n1. 在电脑浏览器登录「普惠业务工作台」；\n2. 点击页面右上角「绑定飞书」，获取 8 位绑定码（{ttl} 分钟内有效）；\n"
             "3. 在这里（私聊）发送：绑定 绑定码\n例如：绑定 AB12CD34\n绑定后，您能查看的内容与您在网页端的权限完全一致。")


def help_text(user, bot_name="普惠业务工作台机器人", channel="飞书"):
    """channel-agnostic help; Feishu/WeChat both call this."""
    base = [f"我是「{bot_name}」。您可以直接发这些话：",
            "· 额度 / 额度 某某机构 —— 查询额度使用情况（最新 M5 快照）",
            "· 预警 —— 查看预警列表",
            "· 今日简报 —— 查看最新行业简报（含来源与权威分级）"]
    if user["role"] != "institution":
        base += ["· 政策 关键词 —— 检索 M1 知识库（标注来源与分级）",
                 "· 报告 / 报告 关键词 / 报告 #编号 —— 查看已定稿研究报告",
                 "· 报告文件 #编号 —— 把 Word 报告作为文件发给您",
                 "· 生成PPT —— 多轮对话发起 PPT 生成（确认需求单与大纲后生成并发文件）",
                 "· PPT文件 #任务号 —— 获取已生成的 PPT",
                 "· 发邮箱 报告 #编号 name@公司域名 —— 把报告发到邮箱（先预览，回复「确认发送」才发）"]
    if channel == "飞书":
        base += ["· 取消 —— 放弃当前多轮操作；解除绑定 —— 解绑本飞书账号",
                 f"您当前身份：{user['name']}（{ {'internal': '普惠部内部', 'institution': '合作机构：' + str(user.get('org') or '')}.get(user['role'], user['role']) }）。群聊中请 @我 再提问；涉及内部数据的功能请私聊使用。"]
    else:
        base += ["· 取消 —— 放弃当前多轮操作；解除绑定 —— 解绑本微信（也可在网页「绑定微信」处操作）",
                 f"您当前身份：{user['name']}（{ {'internal': '普惠部内部', 'institution': '合作机构：' + str(user.get('org') or '')}.get(user['role'], user['role']) }）。",
                 "说明：微信通道每条提问最多回复 10 条消息；长任务（如生成PPT）会先回执，完成后发出；若发送窗口已过期，下次您发任意消息时补发，或请到网页下载/发邮箱。"]
    return "\n".join(base)


# ---------------------------------------------------------------- 意图识别：规则优先，规则识别不了再交给大模型（只传提问文字）
RULES = [
    ("help", r"^(帮助|help|菜单|功能|你能做什么|你会什么|怎么用|\?|？)$"),
    ("unbind", r"^(解除绑定|解绑|取消绑定)"),
    ("ppt_file", r"(ppt|演示稿|PPT)\s*(文件|下载)|(获取|下载|发我|发给我).{0,6}(ppt|演示稿)"),
    ("mail", r"(发|送|寄).{0,3}(邮箱|邮件)|邮件发送|发邮件|发到邮箱|发送到邮箱"),
    ("report_file", r"(报告|研究报告).{0,3}(文件|word|docx|下载)|(下载|获取|发我|发给我|导出).{0,6}(报告|研究报告)"),
    ("ppt_start", r"(生成|制作|做|新建|发起|帮我做).{0,6}(ppt|演示稿|汇报材料)|^ppt$|^PPT$"),
    ("reports", r"研究报告|^报告|报告列表|查.{0,3}报告"),
    ("alerts", r"预警|告警|风险提示"),
    ("quota", r"额度|使用率|使用情况|备案|用了多少|还剩|剩余"),
    ("brief", r"简报|brief|今日(行业)?(资讯|动态)?$|行业动态"),
    ("policy", r"政策|检索|搜索|法规|文件.{0,3}(查|搜)"),
]
COMMAND_INTENTS = {"help", "unbind", "ppt_file", "mail", "report_file", "ppt_start"}
ROUTER_INTENTS = ("quota", "alerts", "brief", "policy", "reports", "report_file", "ppt_start", "mail", "help")


def rule_intent(t):
    for name, pat in RULES:
        if re.search(pat, t, re.I):
            return name
    return None


def llm_intent(ctx, t):
    """自然语言兜底：大模型只负责把问题归类到固定意图，不接触任何业务数据；输出严格校验。"""
    sys = ("你是企业内部工作台聊天助手的意图识别器。只输出 JSON，不要解释。可选 intent：" + "、".join(ROUTER_INTENTS) +
           "（quota=额度使用情况，alerts=预警，brief=今日行业简报，policy=政策检索，reports=查看研究报告，report_file=获取报告文件，ppt_start=生成PPT，mail=发邮件，help=不确定/闲聊）。"
           '格式：{"intent":"...","keyword":"可选的检索关键词，最多20字"}')
    try:
        r = L.run("feishu.router", [{"role": "system", "content": sys}, {"role": "user", "content": t[:200]}], ctx.user, timeout=20, ref="feishu")
        m = re.search(r"\{.*\}", r["content"], re.S)
        o = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        return None, ""
    it = o.get("intent")
    return (it if it in ROUTER_INTENTS else None), str(o.get("keyword") or "")[:20]


# ---------------------------------------------------------------- 主流程
def handle(ctx, t):
    """Feishu entry: resolve binding (code), then channel-agnostic handle_bound."""
    uid_user, note = I.user_of(ctx.open_id)
    if uid_user is None:
        m = re.match(r"^绑定\s*([A-Za-z0-9]{6,12})$", t)
        if m and ctx.group:
            return {"reply": "为保护绑定码，请私聊机器人发送「绑定 绑定码」。", "files": [], "intent": "bind", "status": "拒绝"}
        if m:
            u, err = I.bind_with_code(ctx.open_id, m.group(1))
            if u:
                ctx.user = u
                return {"reply": f"绑定成功：{u['name']}（{'普惠部内部' if u['role'] == 'internal' else '合作机构：' + str(u.get('org') or '')}）。\n发送「帮助」查看可以做什么。", "files": [], "intent": "bind", "status": "已处理"}
            return {"reply": err, "files": [], "intent": "bind", "status": "拒绝"}
        return {"reply": note or BIND_HELP.format(ttl=ctx.cfg["bind_ttl_min"]), "files": [], "intent": "未绑定", "status": "未绑定"}
    ctx.user = uid_user
    ctx.via = getattr(ctx, "via", "飞书")
    ctx.bot_name = getattr(ctx, "bot_name", "普惠业务工作台机器人")
    return handle_bound(ctx, t)


def handle_bound(ctx, t):
    """Channel-agnostic command router (Feishu + WeChat). Requires ctx.user already set."""
    user = ctx.user
    if re.match(r"^(取消|退出|算了|放弃)$", t):
        state_clear(ctx)
        from . import agent as AG
        AG.clear(ctx.open_id)
        return _r("已取消当前操作。", "cancel")
    st = state_get(ctx)
    if st:
        r = continue_flow(ctx, st, t)
        if r is not None:
            return r
    intent = rule_intent(t)
    kw = ""
    if intent not in COMMAND_INTENTS and not (getattr(ctx, "group", False) and not (ctx.cfg or {}).get("group_data")):
        from . import agent as AG
        r = AG.answer(ctx, t, HANDLERS)  # 大模型不可用 → None，回到固定规则
        if r is not None:
            return r
    if not intent:
        intent, kw = llm_intent(ctx, t)
    if not intent:
        return _r("抱歉，我没太明白。试试：额度、预警、今日简报，或发送「帮助」查看全部功能。", "未识别")
    if user["role"] == "institution" and intent in INTERNAL_ONLY:
        return _r("该功能仅对普惠部内部账号开放（合作机构账号可查询本机构额度、预警和已发布简报）。", intent, "拒绝")
    if getattr(ctx, "group", False) and intent in DATA_INTENTS and not (ctx.cfg or {}).get("group_data"):
        return _r("为保护内部数据，这个功能请私聊机器人使用（群聊中只回答简报、政策检索等一般性问题）。", intent, "拒绝")
    if intent == "unbind":
        unbind = getattr(ctx, "unbind_fn", None)
        if unbind:
            n = unbind(ctx)
        else:
            n = I.unbind(open_id=ctx.open_id, by=user)
        via = getattr(ctx, "via", "飞书")
        tip = "已解除绑定。如需重新使用，请在网页端「绑定飞书」获取新的绑定码。" if via == "飞书" else "已解除绑定。如需重新使用，请在网页端点击「绑定微信」重新扫码。"
        return _r(tip if n else "当前没有绑定。", intent)
    if intent == "help":
        return _r(help_text(user, bot_name=getattr(ctx, "bot_name", "普惠业务工作台机器人"), channel=getattr(ctx, "via", "飞书")), intent)
    fn = HANDLERS.get(intent)
    r = fn(ctx, t, kw)
    r.setdefault("intent", intent)
    return r


def _r(text, intent="", status="已处理", files=None):
    return {"reply": text, "files": files or [], "intent": intent, "status": status}


# ---------------------------------------------------------------- 额度 / 预警（M5）
def _latest_snapshot():
    return (db.q1("SELECT id, stat_date, label, limit_set_id FROM m5_snapshots WHERE deleted_at IS NULL AND archived_at IS NULL ORDER BY stat_date DESC, id DESC LIMIT 1")
            or db.q1("SELECT id, stat_date, label, limit_set_id FROM m5_snapshots WHERE deleted_at IS NULL ORDER BY stat_date DESC, id DESC LIMIT 1"))


def _dashboard(user):
    s = _latest_snapshot()
    if not s:
        return None, None
    from ..m5 import service as S
    return s, S.dashboard(s["id"], user)  # 机构账号：行级过滤在 dashboard 内完成


def _match_rows(t, rows):
    from ..m4.service import short_name
    out = []
    for r in rows:
        n = r["name"]
        sn = short_name(n)
        n2 = re.sub(r"市|县|区|融资|有限|股份|责任|公司|集团", "", n)
        if n in t or (len(sn) >= 2 and sn in t) or (len(n2) >= 4 and n2 in t) or (len(n) >= 4 and n[:4] in t and "示例集团" not in n[:2]):
            out.append(r)
    return out


def _row_text(r, stat):
    ls = [f"【{r['name']}】"]
    ls.append(f"常规业务：额度 {wan(r['regular_limit'])}，已备案 {wan(r['regular_amt'])}，使用率 {pct(r['regular_rate'])}，剩余 {wan(r['regular_remain'])}")
    ls.append(f"科技创新专项：已备案 {wan(r['tech_amt'])}")
    ls.append(f"民间投资专项：额度 {wan(r['private_limit'])}，已备案 {wan(r['private_amt'])}，使用率 {pct(r['private_rate'])}")
    ls.append(f"总对总：已备案 {wan(r['t2t_amt'])}；各类合计备案 {wan(r['total_amt'])}")
    for w in r.get("warn") or []:
        ls.append("⚠ " + w["msg"])
    return "\n".join(ls)


def h_quota(ctx, t, kw=""):
    s, d = _dashboard(ctx.user)
    if not s:
        return _r("暂无 M5 看板快照数据，请先在工作台导入台账。", "quota")
    rows = d["rows"]
    src = f"M5 机构看板 · 快照 #{s['id']}「{s.get('label') or ''}」（额度表 #{s['limit_set_id']}）"
    when = f"统计日期 {s['stat_date']}"
    if ctx.user["role"] == "institution":
        if not rows:
            return _r(f"在最新快照中没有找到本机构（{ctx.user.get('org')}）的数据。", "quota")
        return _r(f"本机构额度使用情况（金额单位：万元）\n" + "\n".join(_row_text(r, s) for r in rows) + foot(src, when), "quota")
    hit = _match_rows(t, rows)
    if hit:
        return _r("额度使用情况（金额单位：万元）\n" + "\n\n".join(_row_text(r, s) for r in hit[:3]) + foot(src, when), "quota")
    sm = d["summary"]
    reg = sm["regular"]
    ls = [f"全网额度使用情况（金额单位：万元；统计日期 {s['stat_date']}，时间进度 {d['time_progress'] * 100:.1f}%）",
          f"常规业务：国担额度 {wan(reg['guodan'])}，累计备案 {wan(reg['total']['amount'])}，使用率 {pct(reg['total'].get('rate'))}，剩余 {wan(reg['total'].get('remain'))}",
          f"科技创新专项累计备案 {wan(sm['tech']['total']['amount'])}；民间投资专项累计备案 {wan(sm['private']['total']['amount'])}；总对总累计备案 {wan(sm['t2t']['total']['amount'])}"]
    top = sorted([r for r in rows if r.get("regular_rate") is not None], key=lambda r: -r["regular_rate"])[:5]
    if top:
        ls.append("常规使用率最高的机构：")
        ls += [f"  {i}. {r['name']}：{pct(r['regular_rate'])}（已备案 {wan(r['regular_amt'])} / 额度 {wan(r['regular_limit'])}）" for i, r in enumerate(top, 1)]
    ls.append("提示：发送「额度 机构名称」可查看某家机构的明细。")
    return _r("\n".join(ls) + foot(src, when), "quota")


def h_alerts(ctx, t, kw=""):
    s, d = _dashboard(ctx.user)
    if not s:
        return _r("暂无 M5 看板快照数据。", "alerts")
    src = f"M5 机构看板 · 快照 #{s['id']}「{s.get('label') or ''}」预警规则（红线/超额/进度滞后/环比波动）"
    when = f"统计日期 {s['stat_date']}"
    order = {"over": 0, "red": 1, "yellow": 2, "check": 3}
    hit = _match_rows(t, d["rows"]) if ctx.user["role"] != "institution" else []
    rows = hit or d["rows"]
    items = [(order.get(w["level"], 9), r["name"], w["msg"]) for r in rows for w in (r.get("warn") or [])]
    items.sort()
    ls = []
    if hit and not items:
        return _r("、".join(r["name"] for r in hit) + "：当前没有预警事项。" + foot(src, when), "alerts")
    if ctx.user["role"] != "institution" and not hit:
        ls += [f"· {a['msg']}" for a in d["alerts"] if a["level"] in ("error", "warn")][:8]
    ls += [f"· {n}：{m}" for _, n, m in items][:20]
    if not ls:
        return _r("当前没有预警事项。" + foot(src, when), "alerts")
    return _r(f"预警列表（共 {len(ls)} 条，最多显示 28 条）：\n" + "\n".join(ls) + foot(src, when), "alerts")


# ---------------------------------------------------------------- 简报 / 政策（M2 / M1）
def h_brief(ctx, t, kw=""):
    from ..m2 import brief as B
    d = re.search(r"(20\d\d-\d\d-\d\d)", t)
    inst = ctx.user["role"] == "institution"
    sql = "SELECT id FROM m2_briefs WHERE deleted_at IS NULL" + (" AND status='已发布'" if inst else "") + (" AND brief_date=?" if d else "")
    row = db.q1(sql + " ORDER BY (status='已发布') DESC, brief_date DESC, version DESC LIMIT 1", (d.group(1),) if d else ())  # 优先最新已发布；没有才退到草稿
    if not row:
        return _r("暂无" + ("已发布的" if inst else "") + "行业简报。", "brief")
    b = B.get(row["id"])
    items = [i for i in b["items"] if i.get("include", True) and not i.get("blocked") and i.get("section") in ("必读", "关注")][:6]
    ls = [f"{b['brief_date']} 今日行业 Brief（v{b['version']}，{b['status']}）共 {len(b['items'])} 条，精选："]
    for n, i in enumerate(items, 1):
        pts = "；".join(i.get("points") or [])[:90]
        ls.append(f"{n}. 【{i.get('category', '')}】{i['title']}\n   来源：{i['publisher']}（{i['level']}）｜{i.get('pub_date') or '未标注'}｜{i['url']}" + (f"\n   要点：{pts}" if pts else ""))
    if not items:
        ls.append("（本期暂无必读/关注条目）")
    return _r("\n".join(ls) + foot(f"M2 今日行业 Brief {b['brief_date']} v{b['version']}（{b['status']}）", b.get("published_at") or b.get("generated_at")), "brief")


def h_policy(ctx, t, kw=""):
    q = kw or re.sub(r"^(政策|检索|搜索|查询|查一下|帮我查|搜一下)\s*[：:]?\s*", "", t).strip()
    q = re.sub(r"(的)?(政策|文件|法规)$", "", q).strip() or ""
    if len(q) < 2:
        return _r("请带上关键词，例如：政策 融资担保 降费", "policy")
    like = f"%{q}%"
    from ..m1.validity import notice as validity_notice
    rows = db.q("SELECT title, publisher, level, pub_date, url, validity_status FROM m1_items WHERE duplicate_of IS NULL AND (title LIKE ? OR snippet LIKE ? OR summary LIKE ? OR publisher LIKE ?) "
                "ORDER BY level, COALESCE(pub_date,'') DESC LIMIT 6", (like,) * 4)
    n = db.q1("SELECT COUNT(*) n FROM m1_items WHERE duplicate_of IS NULL AND (title LIKE ? OR snippet LIKE ? OR summary LIKE ? OR publisher LIKE ?)", (like,) * 4)["n"]
    if not rows:
        return _r(f"M1 知识库中没有找到与「{q}」相关的条目。" + foot("M1 财金协同知识库"), "policy")
    ls = [f"与「{q}」相关的政策/资讯，共 {n} 条，按权威分级显示前 {len(rows)} 条："]
    for i, r in enumerate(rows, 1):
        line = f"{i}. {r['title']}\n   来源：{r['publisher'] or '—'}｜权威分级：{r['level']}｜发布：{r['pub_date'] or '未标注'}\n   {r['url']}"
        nt = validity_notice(r.get("validity_status"))
        if nt:
            line += f"\n   {nt}"
        ls.append(line)
    return _r("\n".join(ls) + foot("M1 财金协同知识库（来源分级 A1 最权威；非现行有效请勿作决策依据）"), "policy")


# ---------------------------------------------------------------- 研究报告（M3）
def _finalized(where="", args=(), limit=8):
    return db.q("SELECT id, title, created_by, finalized_at FROM m3_tasks WHERE status IN ('已定稿','已总结') AND deleted_at IS NULL AND archived_at IS NULL" + where
                + " ORDER BY id DESC LIMIT ?", (*args, limit))


def _tid(t):
    m = re.search(r"#\s*(\d+)", t) or re.search(r"(?:报告|任务)\s*(\d+)", t)
    return int(m.group(1)) if m else None


def h_reports(ctx, t, kw=""):
    tid = _tid(t)
    if tid:
        r = db.q1("SELECT * FROM m3_tasks WHERE id=? AND deleted_at IS NULL", (tid,))
        if not r or r["status"] not in ("已定稿", "已总结"):
            return _r(f"没有找到已定稿的研究报告 #{tid}（草稿不通过机器人提供）。", "reports")
        chk = db.jload(r["final_check"], {}) or {}
        body = (r["final"] or "").strip()
        ex = body[:500] + ("……" if len(body) > 500 else "")
        return _r(f"研究报告 #{r['id']}《{r['title']}》\n定稿时间：{r['finalized_at']}　创建人：{r['created_by']}　引用来源登记：{len(chk.get('register', []))} 条\n\n摘录：\n{ex}\n\n"
                  f"回复「报告文件 #{r['id']}」获取 Word 文件；「发邮箱 报告 #{r['id']} 邮箱地址」发送到邮箱。" + foot(f"M3 行业研究院 · 写作任务 #{r['id']}（已定稿）", r["finalized_at"]), "reports")
    q = kw or re.sub(r"^(研究)?报告(列表)?|查(一下|找)?", "", t).strip()
    rows = _finalized(" AND title LIKE ?", (f"%{q}%",)) if q else _finalized()
    if not rows:
        return _r("没有找到已定稿的研究报告。" + foot("M3 行业研究院"), "reports")
    ls = [f"已定稿的研究报告（{'关键词「' + q + '」，' if q else ''}最近 {len(rows)} 篇）："]
    ls += [f"#{r['id']}《{r['title']}》 定稿 {r['finalized_at']} · {r['created_by']}" for r in rows]
    ls.append("回复「报告 #编号」查看摘录，「报告文件 #编号」获取 Word。")
    return _r("\n".join(ls) + foot("M3 行业研究院（仅已定稿）"), "reports")


def h_report_file(ctx, t, kw=""):
    from ..m3 import pipeline as P
    tid = _tid(t)
    if not tid:
        rows = _finalized(limit=1)
        if not rows:
            return _r("没有已定稿的研究报告。", "report_file")
        tid = rows[0]["id"]
    d = M._task_ready(tid)  # 仅已定稿且无标红未决项
    name = f"{d['title'][:40]}.docx"
    data = W.docx_bytes(P.to_docx(tid), ctx.user)
    db.audit(ctx.user, "M3", "导出 Word", tid, {"filename": name, "via": getattr(ctx, "via", "飞书")})
    return _r(f"已发送研究报告 #{tid}《{d['title']}》的 Word 文件（带「内部资料 注意保密」水印与导出人信息）。" + foot(f"M3 行业研究院 · 写作任务 #{tid}", d.get("finalized_at")), "report_file",
              files=[(name, data, "docx")])


def h_ppt_file(ctx, t, kw=""):
    jid = _tid(t)
    sql, a = "SELECT f.* FROM ppt_files f JOIN ppt_jobs j ON j.id=f.job_id WHERE j.deleted_at IS NULL", ()
    if jid:
        sql, a = sql + " AND j.id=?", (jid,)
    f = db.q1(sql + " ORDER BY f.id DESC LIMIT 1", a)
    if not f:
        return _r("没有找到已生成的 PPT 文件。发送「生成PPT」可以发起新的任务。", "ppt_file")
    return _ppt_deliver_reply(ctx, f, "ppt_file")


def _ppt_deliver_reply(ctx, f, intent):
    from pathlib import Path
    data = W.pptx_bytes(Path(f["path"]).read_bytes(), ctx.user)
    db.audit(ctx.user, "PPT", "下载 PPT", f["id"], {"job": f["job_id"], "version": f["version"], "filename": f["filename"], "via": getattr(ctx, "via", "飞书")})
    tr = db.jload(f["trace"], {}) or {}
    tr_txt = (f"数字溯源检查：{'通过' if tr.get('ok') else '发现 ' + str(len(tr.get('violations', []))) + ' 处疑点，请核对'}（检查数字 {tr.get('numbers_checked', 0)} 个、图表序列 {tr.get('chart_series_checked', 0)} 个，均须来自数据库）\n"
              if tr else "")
    return _r(f"PPT 已发送：{f['filename']}（v{f['version']}，{f['pages']} 页，带水印）。\n{tr_txt.rstrip()}" + foot(f"PPT 生成 Agent · 任务 #{f['job_id']} 第 {f['version']} 版", f["created_at"]),
              intent, files=[(f["filename"], data, "pptx")])


# ---------------------------------------------------------------- 发邮箱
KIND_WORDS = (("m2_brief", r"简报|brief"), ("ppt_file", r"ppt|演示稿"), ("m3_report", r"报告|研究"))


def h_mail(ctx, t, kw=""):
    emails = EMAIL_RE.findall(t)
    kind = next((k for k, p in KIND_WORDS if re.search(p, t, re.I)), "m3_report")
    ref = _tid(t)
    if kind == "m3_report" and not ref:
        rows = _finalized(limit=1)
        ref = rows[0]["id"] if rows else None
    elif kind == "m2_brief" and not ref:
        d = re.search(r"(20\d\d-\d\d-\d\d)", t)
        r = db.q1("SELECT id FROM m2_briefs WHERE status='已发布' AND deleted_at IS NULL" + (" AND brief_date=?" if d else "") + " ORDER BY brief_date DESC, version DESC LIMIT 1", (d.group(1),) if d else ())
        ref = r["id"] if r else None
    elif kind == "ppt_file":
        f = db.q1("SELECT f.id FROM ppt_files f JOIN ppt_jobs j ON j.id=f.job_id WHERE j.deleted_at IS NULL" + (" AND j.id=?" if ref else "") + " ORDER BY f.id DESC LIMIT 1", (ref,) if ref else ())
        ref = f["id"] if f else None
    if not ref:
        return _r("没有找到要发送的文档。请指定，例如：发邮箱 报告 #3 name@公司域名", "mail")
    if not emails:
        return _r("请带上收件邮箱，例如：发邮箱 报告 #%s name@公司域名.com\n（只能发到管理员允许的邮箱域名：%s）" % (ref, "、".join(M.get()["allowed_domains"]) or "管理员尚未设置"), "mail")
    p = M.preview(kind, ref, emails, {}, ctx.user)
    if p["recipient_error"]:
        return _r("⚠ " + p["recipient_error"], "mail", "拒绝")
    if not p["smtp_ready"]:
        return _r("邮件发送功能管理员尚未配置/启用，暂不能发送。", "mail", "拒绝")
    subj = re.sub(EMAIL_RE, "", re.sub(r"#\s*\d+|发(送)?(到)?(邮箱|邮件)|报告|简报|ppt|PPT|演示稿|研究|发|邮箱|邮件|给|到|主题[：:]?", " ", t)).strip(" ，,;；:：")
    state_set(ctx, {"step": "mail_confirm", "kind": kind, "ref": ref, "to": p["recipients"], "subject": subj[:100] or p["subject"], "sensitive": p["sensitive"]})
    ls = ["请确认邮件信息（尚未发送）：", f"收件人：{'、'.join(p['recipients'])}", f"主题：{subj[:100] or p['subject']}", f"文档：{p['kind_name']}《{p['title']}》（{p['version']}）",
          f"附件：{'、'.join(a['name'] for a in p['attachments'])}（共 {p['size_mb']} MB，带水印）"] + [f"⚠ {w}" for w in p["warnings"]]
    ls.append("回复「确认涉密发送」发送" if p["sensitive"] else "回复「确认发送」发送")
    ls.append("回复「取消」放弃。发送后无法撤回，请核对收件人。")
    return _r("\n".join(ls), "mail")


# ---------------------------------------------------------------- PPT 多轮
def _deck_options():
    from ..ppt.data import DECKS
    return list(DECKS.items())


def h_ppt_start(ctx, t, kw=""):
    opts = _deck_options()
    state_set(ctx, {"step": "deck"})
    ls = ["请选择要生成的演示稿类型（回复序号）："] + [f"{i}. {v['name']}（数据来源：{v['source']}{'，含内部数据，建议使用公司自有大模型' if v['sensitive'] else ''}）" for i, (_k, v) in enumerate(opts, 1)]
    ls.append("回复「取消」放弃。随后我会先确认需求单和大纲，您确认后才会生成文件。")
    return _r("\n".join(ls), "ppt_start")


def _source_choices(deck):
    if deck == "usage":
        rows = db.q("SELECT id, stat_date, label FROM m5_snapshots WHERE deleted_at IS NULL ORDER BY stat_date DESC, id DESC LIMIT 5")
        return [({"snapshot_id": r["id"]}, f"M5 快照 #{r['id']}（{r['stat_date']} {r['label'] or ''}）") for r in rows]
    if deck == "scheme":
        rows = db.q("SELECT id, version, name, status, is_current FROM m4_schemes WHERE deleted_at IS NULL ORDER BY is_current DESC, version DESC LIMIT 5")
        return [({"scheme_id": r["id"]}, f"M4 方案 v{r['version']}「{r['name'] or ''}」（{r['status']}{'，当前生效' if r['is_current'] else ''}）") for r in rows]
    if deck == "policy":
        today = datetime.now()
        return [({"date_from": (today - timedelta(days=n)).strftime("%Y-%m-%d"), "date_to": today.strftime("%Y-%m-%d")}, f"M2 简报：最近 {n} 天") for n in (30, 7, 90)]
    rows = _finalized(limit=5)
    return [({"task_id": r["id"]}, f"M3 报告 #{r['id']}《{r['title']}》") for r in rows]


def continue_flow(ctx, st, t):
    from ..ppt import agent as G
    step = st.get("step")
    num = int(t) if t.isdigit() else None
    if ctx.user["role"] == "institution":
        state_clear(ctx)
        return None
    if step in ("deck", "source", "outline", "sheet") and num is None and rule_intent(t) not in (None, "ppt_start") and t not in ("确认", "确认大纲", "好", "好的", "是", "生成", "确认生成"):
        if step in ("deck", "source"):  # 用户转去问别的 → 放弃当前选择，按新指令处理
            state_clear(ctx)
            return None
    if step == "deck":
        opts = _deck_options()
        if num is None or not 1 <= num <= len(opts):
            return _r("请回复序号（例如 1），或回复「取消」。", "ppt_start")
        deck = opts[num - 1][0]
        ch = _source_choices(deck)
        if not ch:
            state_clear(ctx)
            return _r(f"没有可用的数据来源（{opts[num - 1][1]['source']}），请先在工作台准备数据。", "ppt_start", "拒绝")
        state_set(ctx, {"step": "source", "deck": deck, "choices": ch})
        return _r("请选择数据来源（回复序号；回复「确认」使用第 1 项）：\n" + "\n".join(f"{i}. {lab}" for i, (_s, lab) in enumerate(ch, 1)), "ppt_start")
    if step == "source":
        ch = st["choices"]
        idx = 1 if t in ("确认", "好", "好的", "是") else num
        if idx is None or not 1 <= idx <= len(ch):
            return _r("请回复序号，或回复「确认」使用第 1 项，「取消」放弃。", "ppt_start")
        try:
            j = G.create({"deck_type": st["deck"], "scope": ch[idx - 1][0]}, ctx.user)
        except HTTPException as e:
            state_clear(ctx)
            return _r(f"⚠ 创建 PPT 任务失败：{e.detail}", "ppt_start", "拒绝")
        state_set(ctx, {"step": "sheet", "job": j["id"]})
        sh = j["sheet"]
        qs = "\n".join(f"  {i}. {q}" for i, q in enumerate(j["questions"], 1))
        return _r(f"已创建 PPT 任务 #{j['id']}：{j['title']}（{j['deck_name']}，数据：{ch[idx - 1][1]}）\n"
                  f"需求单（建议）：受众「{sh.get('audience', '')}」；目的「{sh.get('purpose', '')}」；约 {sh.get('pages', '')} 页；风格「{sh.get('style', '')}」；语气「{sh.get('tone', '')}」；章节：{'、'.join(sh.get('sections', []))}\n"
                  f"我想先确认几个问题：\n{qs}\n请回复您的回答（一条消息即可），或回复「确认」直接采用建议的需求单；「取消」放弃。", "ppt_start")
    if step == "sheet":
        try:
            j = G.confirm_sheet(st["job"], {"answers": [] if t in ("确认", "好", "好的", "是") else [t]}, ctx.user)
        except HTTPException as e:
            return _r(f"⚠ {e.detail}", "ppt_start", "拒绝")
        state_set(ctx, {"step": "outline", "job": j["id"]})
        return _r(_outline_text(j), "ppt_start")
    if step == "outline":
        if t in ("确认大纲", "确认", "生成", "确认生成"):
            try:
                G.generate(st["job"], {"confirm": True, "thumbnails": False}, ctx.user)
            except HTTPException as e:
                state_clear(ctx)
                return _r(f"⚠ 生成失败：{e.detail}", "ppt_start", "拒绝")
            state_clear(ctx)
            f = db.q1("SELECT * FROM ppt_files WHERE job_id=? ORDER BY version DESC LIMIT 1", (st["job"],))
            return _ppt_deliver_reply(ctx, f, "ppt_start")
        try:
            j = G.regenerate_outline(st["job"], {"message": t}, ctx.user)
        except HTTPException as e:
            return _r(f"⚠ {e.detail}", "ppt_start", "拒绝")
        return _r("已按您的意见重新生成大纲。\n" + _outline_text(j), "ppt_start")
    if step == "mail_confirm":
        ok = t in ("确认发送", "确认涉密发送") or (t == "确认" and not st["sensitive"])
        if t == "确认" and st["sensitive"]:
            return _r("该文档含敏感数据，请回复「确认涉密发送」继续，或「取消」。", "mail")
        if not ok:
            state_clear(ctx)
            return None  # 不是确认语 → 视为新指令
        if st["sensitive"] and t != "确认涉密发送":
            return _r("该文档含敏感数据，请回复「确认涉密发送」继续，或「取消」。", "mail")
        state_clear(ctx)
        r = M.send(st["kind"], st["ref"], st["to"], st["subject"], "", {}, ctx.user, channel=getattr(ctx, "via", "飞书"), confirm=True, confirm_sensitive=bool(st["sensitive"]))
        return _r(f"邮件已发送至 {'、'.join(r['to'])}。\n主题：{r['subject']}\n附件：{'、'.join(r['attachments'])}（{r['version']}）\n发送记录已写入「操作留痕 → 邮件发送记录」。", "mail")
    state_clear(ctx)
    return None


def _outline_text(j):
    pages = j["outline"] or []
    ls = [f"已生成大纲，共 {len(pages)} 页（数字由系统从数据库填入，不经过大模型）："]
    ls += [f"{i}. [{p.get('kind')}] {p.get('title') or ''}".rstrip() for i, p in enumerate(pages[:30], 1)]
    if j.get("warnings"):
        ls.append(f"提示：{len(j['warnings'])} 条自动修正（{j['warnings'][-1][:60]}）")
    ls.append("回复「确认大纲」开始生成 PPT；直接回复修改意见（如「增加风险提示页」）会重新生成大纲；「取消」放弃。")
    return "\n".join(ls)


HANDLERS = {"quota": h_quota, "alerts": h_alerts, "brief": h_brief, "policy": h_policy, "reports": h_reports, "report_file": h_report_file,
            "ppt_file": h_ppt_file, "mail": h_mail, "ppt_start": h_ppt_start}
