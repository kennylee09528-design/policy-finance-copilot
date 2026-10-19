"""微信入站消息处理：绑定校验 → 复用飞书 handle_bound → 按 ≤10 条额度发送；长任务先回执再异步投递。"""
from __future__ import annotations

import re
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from .. import db
from ..feishu import service as FS
from . import config as C
from . import delivery as D
from . import identity as I
from .ilink import IlinkClient

POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="wechat")
_hits: dict[str, deque] = defaultdict(deque)
_cleanup = {"t": 0.0}
LONG_INTENTS = {"ppt_start"}  # 生成 PPT 可能较慢：先回执


def _seen(key):
    if not key:
        return False
    with db._lock:
        if db.q1("SELECT 1 x FROM wechat_seen WHERE key=?", (key,)):
            return True
        db.execute("INSERT INTO wechat_seen(key,ts) VALUES(?,?)", (key, db.now()))
    import time
    if time.time() - _cleanup["t"] > 3600:
        _cleanup["t"] = time.time()
        db.execute("DELETE FROM wechat_seen WHERE ts < ?", ((datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),))
        db.execute("DELETE FROM wechat_events WHERE ts < ?", ((datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S"),))
    return False


def _rate_ok(uid, per_min):
    import time
    now = time.time()
    q = _hits[uid]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= per_min:
        return False
    q.append(now)
    return True


def extract_text(msg: dict) -> str:
    parts = []
    for it in msg.get("item_list") or []:
        t = it.get("type")
        if t == 1:
            parts.append((it.get("text_item") or {}).get("text", ""))
        elif t == 3 and (it.get("voice_item") or {}).get("text"):
            parts.append((it.get("voice_item") or {}).get("text", ""))
        elif t == 4:
            parts.append("[文件] " + str((it.get("file_item") or {}).get("file_name", "")))
        else:
            parts.append({2: "[图片]", 3: "[语音]", 5: "[视频]"}.get(t, f"[类型{t}]"))
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def on_inbound(binding: dict, msg: dict, client: IlinkClient, sync: bool = False):
    """poller 收到该绑定账号的一条用户消息后调用。"""
    if not C.get()["enabled"]:
        return
    if msg.get("message_type") != 1:  # USER
        return
    mid = str(msg.get("message_id") or "")
    if _seen(mid):
        return
    if msg.get("from_user_id") != binding["ilink_user_id"]:
        return
    tok = msg.get("context_token")
    if tok:
        db.execute("UPDATE wechat_bindings SET context_token=?, context_at=?, updated_at=? WHERE id=?",
                   (tok, db.now(), db.now(), binding["id"]))
        binding = {**binding, "context_token": tok, "context_at": db.now()}
    text = extract_text(msg)
    if sync:
        _process(binding, msg, client, text, tok)
    else:
        POOL.submit(_safe, binding, msg, client, text, tok)


def _safe(binding, msg, client, text, tok):
    try:
        _process(binding, msg, client, text, tok)
    except Exception as e:  # noqa: BLE001
        db.audit({"name": "普惠Bot", "username": "", "role": "system"}, "微信", "处理异常", binding.get("username", ""), str(e)[:300])


def _process(binding, msg, client, text, tok):
    cfg = C.get()
    uid = binding["ilink_user_id"]
    log_id = db.execute(
        "INSERT INTO wechat_events(ts,message_id,ilink_user_id,username,text,source,status) VALUES(?,?,?,?,?,?,?)",
        (db.now(), str(msg.get("message_id") or ""), uid, binding["username"], (text or "")[:300], "微信", "处理中"))
    sender = D.Sender(client, binding, tok)

    # 先补发 pending（占用部分额度）
    if tok:
        D.flush_pending(client, binding, tok)
        # refresh sent count from a fresh sender for the actual reply
        sender = D.Sender(client, binding, tok)

    user, note, b2 = I.user_of(uid)
    if user is None:
        tip = note or "请先在网页端登录工作台，点击右上角「绑定微信」扫码绑定后再使用。"
        sender.send_text(tip)
        db.execute("UPDATE wechat_events SET status=?, reply=?, intent=? WHERE id=?", ("未绑定", tip[:400], "未绑定", log_id))
        return
    if not _rate_ok(uid, int(cfg["rate_per_min"])):
        tip = f"操作太频繁了（每分钟最多 {cfg['rate_per_min']} 条），请稍后再试。"
        sender.send_text(tip)
        db.execute("UPDATE wechat_events SET status=?, reply=?, username=? WHERE id=?", ("限流", tip[:400], user["username"], log_id))
        return

    if not text or text.startswith("["):
        tip = "目前只支持文字消息（语音若已转写也可）。请直接发送：帮助 / 额度 / 预警 / 今日简报 …"
        sender.send_text(tip)
        db.execute("UPDATE wechat_events SET status=?, reply=?, username=? WHERE id=?", ("忽略", tip[:400], user["username"], log_id))
        return

    # 「继续」：只冲 pending
    if re.match(r"^(继续|接着发|再发)$", text):
        n = D.flush_pending(client, binding, tok) if tok else 0
        if n == 0:
            sender.send_text("没有待补发的内容。发送「帮助」查看我能做什么。")
        db.execute("UPDATE wechat_events SET status=?, intent=?, username=?, reply=? WHERE id=?",
                   ("已处理", "pending", user["username"], f"flush={n}", log_id))
        return

    ctx = FS.Ctx(
        open_id=f"wx:{uid}",  # 与飞书 open_id 隔离的状态键
        chat_id=uid,
        chat_type="p2p",
        group=False,
        user=user,
        cfg={"group_data": False, "bind_ttl_min": 10},
        via="微信",
        bot_name=cfg.get("bot_name") or C.BOT_NAME,
        unbind_fn=lambda c: I.unbind(username=c.user["username"], by=c.user),
        api=None,
        message_id=str(msg.get("message_id") or ""),
        source="微信",
    )

    # 长任务：先回执，后台跑完再投递
    intent_peek = FS.rule_intent(text)
    if intent_peek in LONG_INTENTS or (FS.state_get(ctx) or {}).get("step") == "outline" and text in ("确认大纲", "确认", "生成", "确认生成"):
        sender.send_text(f"「{cfg.get('bot_name') or C.BOT_NAME}」已收到，正在处理（生成 PPT 可能需要一两分钟），完成后发给您…")
        try:
            res = FS.handle_bound(ctx, text)
        except Exception as e:  # noqa: BLE001
            res = {"reply": f"处理出错：{e}", "files": [], "intent": intent_peek or "?", "status": "错误"}
        # 用最新 token 再发（可能已被其它回复占用额度；不够则入 pending）
        binding2 = db.q1("SELECT * FROM wechat_bindings WHERE id=?", (binding["id"],)) or binding
        sender2 = D.Sender(client, binding2, binding2.get("context_token") or tok)
        stats = sender2.deliver(res.get("reply") or "", res.get("files") or [])
        if stats["expired"] or stats["sent"] == 0 and (res.get("reply") or res.get("files")):
            # 附加兜底说明
            D.enqueue_text(binding2,
                           "内容已就绪但微信发送窗口已过期。请再发「继续」补发；或登录网页下载 / 使用「发邮箱」。",
                           note="fallback_hint")
        db.execute("UPDATE wechat_events SET status=?, intent=?, username=?, reply=?, error=? WHERE id=?",
                   (res.get("status") or "已处理", res.get("intent") or "", user["username"],
                    (res.get("reply") or "")[:400], "; ".join(stats.get("errors") or [])[:200], log_id))
        db.audit(user, "微信", f"微信消息·{res.get('intent') or '其他'}", uid[-8:],
                 {"status": res.get("status"), "files": [f[0] for f in (res.get("files") or [])], "text": text[:80]})
        return

    try:
        res = FS.handle_bound(ctx, text)
    except Exception as e:  # noqa: BLE001
        from fastapi import HTTPException
        if isinstance(e, HTTPException):
            res = {"reply": f"⚠ {e.detail if isinstance(e.detail, str) else '请求未能完成'}", "files": [], "intent": "", "status": "拒绝"}
        else:
            res = {"reply": "抱歉，处理时出错了，已记录，请稍后再试。", "files": [], "intent": "", "status": "错误", "error": str(e)[:200]}

    stats = sender.deliver(res.get("reply") or "", res.get("files") or [])
    if stats["expired"] and (res.get("reply") or res.get("files")):
        D.enqueue_text(binding, "部分内容因微信发送限制未能立即送达。请再发「继续」补发；或登录网页下载 / 发邮箱。", note="fallback_hint")

    db.execute("UPDATE wechat_events SET status=?, intent=?, username=?, reply=?, error=? WHERE id=?",
               (res.get("status") or "已处理", res.get("intent") or "", user["username"],
                (res.get("reply") or "")[:400], "; ".join((res.get("error") and [res["error"]] or []) + (stats.get("errors") or []))[:200], log_id))
    db.audit(user, "微信", f"微信消息·{res.get('intent') or '其他'}", uid[-8:],
             {"status": res.get("status"), "files": [f[0] for f in (res.get("files") or [])], "text": text[:80]})


def events(limit=200, status=""):
    sql, a = "SELECT * FROM wechat_events", []
    if status:
        sql += " WHERE status=?"
        a.append(status)
    return db.q(sql + " ORDER BY id DESC LIMIT ?", (*a, min(limit, 500)))
