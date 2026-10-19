"""采集执行：生成查询 → 联网搜索 → 规则过滤分级 → 去重入库 → 抓正文 → AI 要点摘要；以及定时调度。"""
import os
import re
import threading
import time
import traceback
from datetime import datetime

from .. import db
from ..search import service as search
from . import config as C
from .classify import classify, norm_url
from .fetch import fetch

_lock = threading.Lock()
SYS = {"name": "M1定时采集", "role": "internal"}


def plan_queries(cfg, advance=False):
    """本轮查询：every_run 层级全部 + 其余 (地域×主题) 轮转，直到 max_queries_per_run。"""
    fixed, rot = [], []
    for t in cfg["tiers"]:
        for reg in t["regions"]:
            for tp in cfg["topics"]:
                q = cfg["template"].replace("{region}", "" if reg == "全国" else reg).replace("{topic}", tp).strip()
                item = {"query": re.sub(r"\s+", " ", q), "region": reg, "layer": t["layer"], "tier": t["name"], "topic": tp}
                (fixed if t.get("every_run") else rot).append(item)
    budget = cfg["max_queries_per_run"]
    out = fixed[:budget]
    left = budget - len(out)
    cur = int(db.get_setting("m1_cursor", 0) or 0)
    if rot and left > 0:
        n = min(left, len(rot))
        out += [rot[(cur + i) % len(rot)] for i in range(n)]
        if advance:
            db.set_setting("m1_cursor", (cur + n) % len(rot))
    return out, {"fixed": len(fixed), "rotating": len(rot), "cursor": cur, "cycle_runs": (len(rot) // max(1, left)) + (1 if len(rot) % max(1, left) else 0) if left > 0 else None}


# 定时采集优先主题：国家融资担保/再担保与相关政策（在轮转池中权重大，出现更勤）
_PRIORITY_TOPIC_KEYS = ("融资担保", "再担保", "国家融资担保基金")


def _is_priority_topic(topic):
    t = topic or ""
    return any(k in t for k in _PRIORITY_TOPIC_KEYS)


def _mk_query(cfg, region, layer, tier, topic):
    q = cfg["template"].replace("{region}", "" if region == "全国" else region).replace("{topic}", topic).strip()
    return {"query": re.sub(r"\s+", " ", q), "region": region, "layer": layer, "tier": tier, "topic": topic}


def scheduled_pool(cfg):
    """定时采集轮转池：国家/广东 × 主题为骨干；优先主题按 round-robin 加权约 3 倍（同日内主题分散）；其余地域×主题殿后。"""
    topics = list(cfg.get("topics") or [])
    pri = [tp for tp in topics if _is_priority_topic(tp)]
    rest = [tp for tp in topics if not _is_priority_topic(tp)]
    core = []
    # 每轮先扫一轮优先主题的国家，再扫广东，共 3 轮 → 优先主题出现更勤且日内分散
    for _ in range(3):
        for tp in pri:
            core.append(_mk_query(cfg, "全国", "国家", "国家", tp))
        for tp in pri:
            core.append(_mk_query(cfg, "广东", "省级", "广东本省", tp))
    for tp in rest:
        core.append(_mk_query(cfg, "全国", "国家", "国家", tp))
        core.append(_mk_query(cfg, "广东", "省级", "广东本省", tp))
    extras = []
    for t in cfg.get("tiers") or []:
        if t.get("every_run"):
            continue
        for reg in t.get("regions") or []:
            for tp in topics:
                extras.append(_mk_query(cfg, reg, t["layer"], t["name"], tp))
    return (core * 2) + extras


def plan_queries_scheduled(cfg, advance=False):
    """定时采集：每日硬上限 max_queries_scheduled_per_day，按加权池日更轮转；与手动 max_queries_per_run 独立。"""
    budget = max(1, min(int(cfg.get("max_queries_scheduled_per_day", 5) or 5), 200))
    today = datetime.now().strftime("%Y-%m-%d")
    usage = db.get_setting("m1_sched_day_usage", {}) or {}
    used = int(usage.get("count", 0) or 0) if usage.get("date") == today else 0
    remaining = max(0, budget - used)
    pool = scheduled_pool(cfg)
    cur = int(db.get_setting("m1_sched_cursor", 0) or 0)
    n = min(remaining, len(pool)) if pool and remaining else 0
    out = [pool[(cur + i) % len(pool)] for i in range(n)] if n else []
    if advance and out:
        db.set_setting("m1_sched_cursor", (cur + n) % max(len(pool), 1))
        db.set_setting("m1_sched_day_usage", {"date": today, "count": used + n})
    pri_n = sum(1 for x in out if _is_priority_topic(x["topic"]) and x["region"] in ("全国", "广东"))
    return out, {
        "mode": "scheduled",
        "budget": budget,
        "used_today": used + (n if advance else 0),
        "remaining_before": remaining,
        "pool": len(pool),
        "cursor": cur,
        "priority_in_plan": pri_n,
        "cycle_days": (len(pool) + budget - 1) // budget if budget else None,
    }


def _norm_title(t):
    return re.sub(r"[\s\W_]+", "", t or "")[:60]


def _summarize(item_id):
    from ..llm import service as L
    from ..llm.service import assignments
    if not assignments().get("m1.extract"):
        return False
    it = db.q1("SELECT * FROM m1_items WHERE id=?", (item_id,))
    body = (it["content"] or it["snippet"] or "")[:6000]
    if not body:
        return False
    prompt = ("请严格依据下文，提炼 3-5 条政策要点（每条一行，以“- ”开头），并抽取：发布机构、文号、关键数字（金额/比例/期限）。"
              "原文没有的信息写“未提及”，不得推测或编造。\n标题：" + (it["title"] or "") + "\n正文：\n" + body)
    r = L.run("m1.extract", [{"role": "user", "content": prompt}], SYS, ref=f"m1_item:{item_id}")
    db.execute("UPDATE m1_items SET summary=? WHERE id=?", (r["content"], item_id))
    return True


def run(trigger="manual", user=None, queries=None):
    if not _lock.acquire(blocking=False):
        raise RuntimeError("已有采集任务在运行")
    user = user or SYS
    rid = db.execute("INSERT INTO m1_runs(started_at,trigger,status,stats,log,created_by) VALUES(?,?,?,?,?,?)", (db.now(), trigger, "运行中", "{}", "", user.get("name")))
    log, st = [], {"queries": 0, "results": 0, "kept": 0, "new": 0, "dup": 0, "dropped": 0, "fetched": 0, "fetch_fail": 0, "summarized": 0, "errors": 0}
    try:
        cfg = C.get()
        if queries is not None:
            plan = queries
        elif str(trigger).startswith("定时"):
            plan = plan_queries_scheduled(cfg, advance=True)[0]
        else:
            plan = plan_queries(cfg, advance=True)[0]
        new_ids = []
        for qi in plan:
            st["queries"] += 1
            try:
                res = search.search(qi["query"], None, cfg["results_per_query"], cfg["time_range"])
            except Exception as e:  # noqa: BLE001  单条失败不影响全局
                st["errors"] += 1
                log.append(f"检索失败「{qi['query']}」：{getattr(e, 'detail', e)}")
                continue
            for r in res:
                st["results"] += 1
                if not r.get("url"):
                    continue
                c = classify(r["url"], cfg)
                if not c or c["level"] not in cfg["keep_levels"]:
                    st["dropped"] += 1
                    continue
                st["kept"] += 1
                url = norm_url(r["url"])
                if db.q1("SELECT 1 x FROM m1_items WHERE url=?", (url,)):
                    st["dup"] += 1
                    continue
                dup = None
                nt = _norm_title(r["title"])
                if nt:
                    for o in db.q("SELECT id,title,level FROM m1_items WHERE duplicate_of IS NULL AND title LIKE ?", (f"%{(r['title'] or '')[:12]}%",)):
                        if _norm_title(o["title"]) == nt:
                            dup = o["id"]
                            break
                iid = db.execute("INSERT OR IGNORE INTO m1_items(url,title,publisher,level,layer,region,topic,pub_date,snippet,query,provider,fetch_status,duplicate_of,run_id,collected_at) "
                                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (url, r["title"], c["publisher"], c["level"], c["layer"] or qi["layer"], qi["region"], qi["topic"], r.get("date"),
                                  r.get("snippet"), qi["query"], r.get("provider"), "待抓取", dup, rid, db.now()))
                st["new"] += 1
                new_ids.append(iid)
        if cfg["fetch_content"]:
            for iid in new_ids:
                it = db.q1("SELECT url,pub_date,title FROM m1_items WHERE id=?", (iid,))
                try:
                    f = fetch(it["url"])
                    db.execute("UPDATE m1_items SET content=?, pub_date=COALESCE(pub_date,?), title=CASE WHEN title='' OR title IS NULL THEN ? ELSE title END, "
                               "fetch_status=?, fetched_at=? WHERE id=?",
                               (f["text"], f["date"], f["title"], "PDF（未解析正文）" if f["kind"] == "pdf" else "已抓取", db.now(), iid))
                    st["fetched"] += 1
                except Exception as e:  # noqa: BLE001
                    st["fetch_fail"] += 1
                    db.execute("UPDATE m1_items SET fetch_status=? WHERE id=?", (f"抓取失败：{str(e)[:120]}", iid))
                time.sleep(0.3)
        for iid in new_ids[: cfg["ai_summary_per_run"]]:
            try:
                if _summarize(iid):
                    st["summarized"] += 1
            except Exception as e:  # noqa: BLE001
                log.append(f"AI 摘要失败 #{iid}：{getattr(e, 'detail', e)}")
                break
        status = "完成" if st["errors"] < st["queries"] or not st["queries"] else "失败"
    except Exception as e:  # noqa: BLE001
        status = "失败"
        log.append(traceback.format_exc()[-800:])
    finally:
        db.execute("UPDATE m1_runs SET finished_at=?, status=?, stats=?, log=? WHERE id=?", (db.now(), status, db.jdump(st), "\n".join(log[-200:]), rid))
        db.audit(user, "M1", "执行采集", rid, st)
        _lock.release()
    return rid


def run_async(trigger, user):
    if _lock.locked():
        raise RuntimeError("已有采集任务在运行")
    threading.Thread(target=lambda: _safe_run(trigger, user), daemon=True).start()


def _safe_run(trigger, user):
    try:
        run(trigger, user)
    except RuntimeError:
        pass


def _loop():
    from .. import ops
    while True:
        try:
            ops.beat("m1_collect")
            cfg = C.get()
            sch = cfg.get("schedule") or {}
            if sch.get("enabled"):
                now = datetime.now()
                hm = now.strftime("%H:%M")
                for t in sch.get("times", []):
                    key = f"{now:%Y-%m-%d} {t}"
                    if hm >= t and (db.get_setting("m1_sched_last", {}) or {}).get(t) != f"{now:%Y-%m-%d}" and hm < _plus(t, 30):
                        last = db.get_setting("m1_sched_last", {}) or {}
                        last[t] = f"{now:%Y-%m-%d}"
                        db.set_setting("m1_sched_last", last)
                        ops.run_job("m1_collect", run, f"定时 {key}", SYS)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(30)


def _plus(t, minutes):
    h, m = map(int, t.split(":"))
    m2 = h * 60 + m + minutes
    return f"{min(m2 // 60, 23):02d}:{m2 % 60 if m2 // 60 < 24 else 59:02d}"


def start_scheduler():
    from .. import ops
    if os.environ.get("PH_DISABLE_SCHEDULER") or not ops.acquire_scheduler_lock():
        return
    threading.Thread(target=_loop, daemon=True, name="m1-scheduler").start()
