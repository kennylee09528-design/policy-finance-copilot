"""运行可靠性：启动时恢复中断任务、调度器单实例锁与心跳状态、HTTP 退避重试。"""
import os
import random
import threading
import time
from datetime import datetime

import httpx

from . import db
from .config import DATA_DIR

RETRY_STATUS = (429, 500, 502, 503, 504)
_lock_fh = None
_mem = {}


# ---------------- 退避重试（大模型 / 搜索） ----------------
def post_retry(url, *, json=None, headers=None, timeout=None, attempts=None, label="HTTP"):
    """对 429/5xx 与网络超时/连接错误做指数退避重试；其他 4xx 立即返回。"""
    n = int(attempts or os.environ.get("PH_HTTP_RETRIES", 3))
    base = float(os.environ.get("PH_RETRY_BASE", 1.5))
    last_exc = None
    for i in range(n):
        try:
            r = httpx.post(url, json=json, headers=headers, timeout=timeout)
            if r.status_code not in RETRY_STATUS or i == n - 1:
                if i:
                    note("retry", f"{label} 第 {i + 1} 次尝试返回 {r.status_code}")
                return r
            wait = base * (2 ** i)
            ra = r.headers.get("retry-after") if hasattr(r, "headers") else None
            if ra and ra.isdigit():
                wait = max(wait, min(float(ra), 20.0))
            note("retry", f"{label} 返回 {r.status_code}，{wait:.1f}s 后重试（{i + 1}/{n - 1}）")
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            if i == n - 1:
                raise
            wait = base * (2 ** i)
            note("retry", f"{label} 网络错误 {type(e).__name__}，{wait:.1f}s 后重试（{i + 1}/{n - 1}）")
        if wait:
            time.sleep(wait + random.uniform(0, base * 0.2))
    if last_exc:
        raise last_exc
    return r


def note(kind, msg):
    ev = _mem.setdefault(kind, [])
    ev.append({"at": db.now(), "msg": msg})
    del ev[:-50]


# ---------------- 调度器：单实例锁 + 心跳 ----------------
def acquire_scheduler_lock():
    """多进程/多 worker 时只允许一个进程运行定时任务。"""
    global _lock_fh
    if _lock_fh:
        return True
    try:
        import fcntl
        fh = open(DATA_DIR / "scheduler.lock", "w")  # noqa: SIM115
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        _lock_fh = fh
        return True
    except (OSError, ImportError):
        return False


def beat(name, **info):
    """调度器心跳：每轮循环调用；run/result/error 在实际执行时写入。"""
    st = db.get_setting("sched_status", {}) or {}
    cur = st.get(name, {})
    cur.update({"tick": db.now(), "pid": os.getpid(), **info})
    st[name] = cur
    db.set_setting("sched_status", st)


def run_job(name, fn, *a, **kw):
    t0 = time.time()
    beat(name, last_start=db.now(), running=True)
    try:
        res = fn(*a, **kw)
        beat(name, running=False, last_end=db.now(), last_ok=True, last_error=None, last_ms=int((time.time() - t0) * 1000))
        return res
    except Exception as e:  # noqa: BLE001
        beat(name, running=False, last_end=db.now(), last_ok=False, last_error=f"{type(e).__name__}: {getattr(e, 'detail', e)}"[:300])
        db.audit({"name": "系统", "role": "system"}, "系统", "定时任务失败", name, str(getattr(e, "detail", e))[:300])
        return None


# ---------------- 启动时恢复 ----------------
M3_RUNNING = ("排队", "检索资料", "写作中", "核对中")


def recover_on_startup():
    n3 = 0
    for t in db.q(f"SELECT id, status FROM m3_tasks WHERE status IN ({','.join('?' * len(M3_RUNNING))})", M3_RUNNING):
        db.execute("UPDATE m3_tasks SET status='已中断', stage='已中断', error=?, updated_at=? WHERE id=?",
                   (f"服务重启时任务处于「{t['status']}」，已标记中断；可在任务页点击「重新运行」", db.now(), t["id"]))
        db.execute("INSERT INTO m3_events(task_id,ts,agent,stage,message,elapsed_ms,tokens) VALUES(?,?,?,?,?,?,?)",
                   (t["id"], db.now(), "system", "中断", "服务重启，任务中断（可重新运行）", 0, 0))
        n3 += 1
    r1 = db.q("SELECT id FROM m1_runs WHERE status='运行中'")
    for r in r1:
        db.execute("UPDATE m1_runs SET status='已中断', finished_at=?, log=COALESCE(log,'') || ? WHERE id=?",
                   (db.now(), "\n服务重启，采集中断", r["id"]))
    st = db.get_setting("sched_status", {}) or {}
    for v in st.values():
        v["running"] = False
    db.set_setting("sched_status", st)
    db.set_setting("last_boot", {"at": db.now(), "recovered_m3": n3, "recovered_m1": len(r1)})
    return n3, len(r1)


def status():
    from .m1 import config as M1C
    from .m2 import config as M2C
    st = db.get_setting("sched_status", {}) or {}
    m1s, m2s = M1C.get().get("schedule") or {}, M2C.get().get("schedule") or {}
    plan = {"m1_collect": {"name": "M1 定时采集", "enabled": bool(m1s.get("enabled")), "plan": "、".join(m1s.get("times", []))},
            "m2_brief": {"name": "M2 每日简报", "enabled": bool(m2s.get("enabled")), "plan": m2s.get("time")},
            "backup": {"name": "数据库每日备份", "enabled": True, "plan": (db.get_setting("backup_config", {}) or {}).get("time", "02:30")}}
    sched = []
    for k, p in plan.items():
        s = st.get(k, {})
        alive = False
        if s.get("tick"):
            alive = (datetime.now() - datetime.strptime(s["tick"], "%Y-%m-%d %H:%M:%S")).total_seconds() < 180
        sched.append({"key": k, **p, **s, "alive": alive})
    cert = None
    try:
        from .backup import bdir
        f = bdir() / "cert_status.txt"
        if f.exists():
            line = f.read_text().strip().splitlines()[0]
            end = datetime.strptime(line.split("=", 1)[1].strip(), "%b %d %H:%M:%S %Y %Z")
            local = end + (datetime.now() - datetime.utcnow())
            cert = {"not_after": local.strftime("%Y-%m-%d %H:%M"), "days_left": round((end - datetime.utcnow()).total_seconds() / 86400, 1),
                    "checked_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
    except (OSError, ValueError, IndexError):
        cert = None
    return {
        "cert": cert,
        "boot": db.get_setting("last_boot", {}),
        "scheduler_disabled": bool(os.environ.get("PH_DISABLE_SCHEDULER")),
        "lock_held": bool(_lock_fh),
        "schedulers": sched,
        "interrupted": db.q("SELECT id, title, status, error, updated_at FROM m3_tasks WHERE status IN ('已中断','失败') ORDER BY id DESC LIMIT 20"),
        "m1_runs": db.q("SELECT id, started_at, finished_at, trigger, status FROM m1_runs ORDER BY id DESC LIMIT 10"),
        "retries": list(reversed(_mem.get("retry", [])))[:20],
        "threads": sorted(t.name for t in threading.enumerate()),
    }
