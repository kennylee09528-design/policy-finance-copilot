"""多账号长轮询：每个 wechat_bindings 一条轮询线程；文件锁保证单进程单 poller（避免同 token 多端抢消息）。"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from .. import db
from ..config import DATA_DIR
from . import config as C
from . import identity as I
from . import service as S
from .ilink import IlinkClient

LOCK_DIR = DATA_DIR / "wechat_locks"
_lock = threading.RLock()
_threads: dict[int, threading.Thread] = {}
_stop = threading.Event()
_supervisor = None


def _lock_path(binding_id: int) -> Path:
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    return LOCK_DIR / f"binding_{binding_id}.lock"


def _try_lock(path: Path):
    """非阻塞独占锁（fcntl）；拿不到则返回 None（已有其它 poller）。"""
    import fcntl
    path.touch(exist_ok=True)
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    os.write(fd, f"pid={os.getpid()} t={db.now()}\n".encode())
    return fd


def _unlock(fd):
    if fd is None:
        return
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def status():
    cfg = C.get()
    alive = [bid for bid, t in _threads.items() if t.is_alive()]
    return {
        "enabled": cfg["enabled"],
        "bot_name": cfg.get("bot_name") or C.BOT_NAME,
        "polling": len(alive),
        "bindings_ok": (db.q1("SELECT COUNT(*) n FROM wechat_bindings WHERE status='正常'") or {"n": 0})["n"],
        "need_rebind": (db.q1("SELECT COUNT(*) n FROM wechat_bindings WHERE status='需重新扫码'") or {"n": 0})["n"],
        "alive_ids": alive,
    }


def reload():
    """配置或绑定变更后：停掉多余线程、为新绑定拉起线程。"""
    with _lock:
        _reconcile()


def _reconcile():
    cfg = C.get()
    want = set()
    if cfg["enabled"] and not os.environ.get("PH_DISABLE_SCHEDULER"):
        for b in db.q("SELECT id FROM wechat_bindings WHERE status='正常'"):
            want.add(b["id"])
    # stop gone
    for bid, t in list(_threads.items()):
        if bid not in want:
            # thread checks binding status / stop flag each loop
            _threads.pop(bid, None)
    # start missing
    for bid in want:
        t = _threads.get(bid)
        if t and t.is_alive():
            continue
        th = threading.Thread(target=_poll_one, args=(bid,), daemon=True, name=f"wechat-poll-{bid}")
        _threads[bid] = th
        th.start()


def _poll_one(binding_id: int):
    lock_fd = _try_lock(_lock_path(binding_id))
    if lock_fd is None:
        return  # another worker already polling this token
    client = None
    stale_hits = 0
    try:
        while not _stop.is_set():
            cfg = C.get()
            b = db.q1("SELECT * FROM wechat_bindings WHERE id=?", (binding_id,))
            if not b or b["status"] != "正常" or not cfg["enabled"]:
                break
            token = I.token_of(b)
            if client is None or client.token != token or client.base_url != (b.get("baseurl") or client.base_url):
                if client:
                    try:
                        client.notify(False)
                    except Exception:  # noqa: BLE001
                        pass
                    client.close()
                client = IlinkClient(token=token, base_url=b.get("baseurl") or None)
                client.notify(True)
            timeout = float(cfg.get("poll_timeout_s") or 35)
            r = client.get_updates(b.get("cursor") or "", timeout=timeout)
            if r.stale or r.http_status in (401, 403):
                stale_hits += 1
                if stale_hits >= 2:
                    I.mark_rebind(binding_id, f"session timeout (-14): {r.errmsg or r.error}")
                    break
                time.sleep(30)
                continue
            if r.error or r.http_status != 200 or r.ret not in (None, 0) or r.errcode not in (None, 0):
                time.sleep(5)
                continue
            stale_hits = 0
            buf = (r.body or {}).get("get_updates_buf")
            for msg in (r.body or {}).get("msgs") or []:
                try:
                    S.on_inbound(b, msg, client)
                except Exception as e:  # noqa: BLE001
                    db.audit({"name": "普惠Bot", "username": b["username"], "role": "system"}, "微信", "入站异常", str(binding_id), str(e)[:300])
                b = db.q1("SELECT * FROM wechat_bindings WHERE id=?", (binding_id,)) or b
            if buf is not None and buf != b.get("cursor"):
                db.execute("UPDATE wechat_bindings SET cursor=?, updated_at=? WHERE id=?", (buf, db.now(), binding_id))
    finally:
        if client:
            try:
                client.notify(False)
            except Exception:  # noqa: BLE001
                pass
            client.close()
        _unlock(lock_fd)
        with _lock:
            cur = _threads.get(binding_id)
            if cur is threading.current_thread():
                _threads.pop(binding_id, None)


def _supervise():
    while not _stop.is_set():
        try:
            with _lock:
                _reconcile()
        except Exception:  # noqa: BLE001
            pass
        _stop.wait(15)


def start():
    global _supervisor
    if os.environ.get("PH_DISABLE_SCHEDULER"):
        return
    with _lock:
        if _supervisor and _supervisor.is_alive():
            return
        _stop.clear()
        _reconcile()
        _supervisor = threading.Thread(target=_supervise, daemon=True, name="wechat-supervisor")
        _supervisor.start()


def stop():
    _stop.set()
