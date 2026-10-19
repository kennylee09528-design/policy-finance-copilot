"""数据库每日自动备份（独立于数据卷的目录）+ 轮换 + 完整性校验 + 恢复。

备份目录：环境变量 PH_BACKUP_DIR（docker compose 中挂载宿主机 /opt/puhui-workbench-backups → /backup），
未设置时为 data/backups（仅开发用）。每个备份是一个 .tar.gz：workbench.db（SQLite 在线备份 API 生成的一致性快照）、
secret.key（API Key 加密密钥，恢复后已保存的 Key 才能解密）、ppt/templates（管理员上传的模板）。"""
import io
import os
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from . import db, ops
from .config import DATA_DIR, DB_PATH

DEFAULT = {"time": "02:30", "keep_daily": 14, "keep_weekly": 8, "enabled": True}
NAME = "workbench_%Y%m%d_%H%M%S"


def bdir():
    p = Path(os.environ.get("PH_BACKUP_DIR") or (DATA_DIR / "backups"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def cfg():
    return {**DEFAULT, **(db.get_setting("backup_config", {}) or {})}


def save_cfg(body, user):
    c = cfg()
    if "time" in body:
        datetime.strptime(body["time"], "%H:%M")
        c["time"] = body["time"]
    for k in ("keep_daily", "keep_weekly"):
        if k in body:
            c[k] = max(1, min(int(body[k]), 365))
    if "enabled" in body:
        c["enabled"] = bool(body["enabled"])
    db.set_setting("backup_config", c)
    db.audit(user, "系统", "修改备份设置", "", c)
    return c


def backup_now(trigger="手动", user=None):
    out = bdir()
    name = datetime.now().strftime(NAME) + ".tar.gz"
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "workbench.db"
        dst = sqlite3.connect(snap)
        with db._lock:  # noqa: SLF001
            db.conn().backup(dst)
        dst.close()
        chk = sqlite3.connect(snap).execute("PRAGMA integrity_check").fetchone()[0]
        if chk != "ok":
            raise RuntimeError(f"备份快照完整性校验失败：{chk}")
        tmp = out / (name + ".part")
        with tarfile.open(tmp, "w:gz") as tf:
            tf.add(snap, "workbench.db")
            sk = DATA_DIR / "secret.key"
            if sk.exists():
                tf.add(sk, "secret.key")
            tpl = DATA_DIR / "ppt" / "templates"
            if tpl.exists():
                tf.add(tpl, "ppt/templates")
            meta = f"created_at={db.now()}\ntrigger={trigger}\nintegrity={chk}\n".encode()
            ti = tarfile.TarInfo("BACKUP_INFO.txt")
            ti.size = len(meta)
            tf.addfile(ti, io.BytesIO(meta))
        os.chmod(tmp, 0o600)
        tmp.rename(out / name)
    removed = rotate()
    info = {"name": name, "size": (out / name).stat().st_size, "integrity": chk, "removed": removed, "trigger": trigger, "at": db.now()}
    db.set_setting("backup_last", info)
    if user:
        db.audit(user, "系统", "数据库备份", name, {"size": info["size"], "removed": len(removed)})
    return info


def _parse(n):
    try:
        return datetime.strptime(n.split(".")[0], NAME)
    except ValueError:
        return None


def rotate():
    """保留最近 keep_daily 天的每日最新一份 + 最近 keep_weekly 周的每周最早一份；其余删除。"""
    c = cfg()
    files = sorted([(d, p) for p in bdir().glob("workbench_*.tar.gz") if (d := _parse(p.name))], reverse=True)
    keep, days, weeks = set(), [], {}
    for d, p in files:
        day = d.date()
        if day not in days:
            if len(days) < c["keep_daily"]:
                keep.add(p)
            days.append(day)
        wk = d.isocalendar()[:2]
        weeks[wk] = p  # 逆序遍历：最后写入的是该周最早一份
    for wk in sorted(weeks, reverse=True)[: c["keep_weekly"]]:
        keep.add(weeks[wk])
    removed = []
    for _d, p in files:
        if p not in keep:
            p.unlink()
            removed.append(p.name)
    return removed


def listing():
    return {"dir": str(bdir()), "config": cfg(), "last": db.get_setting("backup_last"),
            "files": [{"name": p.name, "size": p.stat().st_size, "at": _parse(p.name).strftime("%Y-%m-%d %H:%M:%S")}
                      for p in sorted(bdir().glob("workbench_*.tar.gz"), reverse=True) if _parse(p.name)]}


def restore(path, target_db=None):
    """离线恢复（须先停止应用）：校验 → 当前库另存为 pre_restore → 替换数据库/密钥/模板。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    target_db = Path(target_db or DB_PATH)
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(path, "r:gz") as tf:
            tf.extractall(td, filter="data")
        snap = Path(td) / "workbench.db"
        chk = sqlite3.connect(snap).execute("PRAGMA integrity_check").fetchone()[0]
        if chk != "ok":
            raise RuntimeError(f"备份文件完整性校验失败：{chk}")
        if target_db.exists():
            keep = target_db.with_name(f"pre_restore_{datetime.now():%Y%m%d_%H%M%S}.db")
            s = sqlite3.connect(target_db)
            d = sqlite3.connect(keep)
            s.backup(d)
            d.close()
            s.close()
        for suf in ("-wal", "-shm"):
            Path(str(target_db) + suf).unlink(missing_ok=True)
        src = sqlite3.connect(snap)
        dst = sqlite3.connect(target_db)
        src.backup(dst)
        dst.close()
        src.close()
        sk = Path(td) / "secret.key"
        if sk.exists():
            (target_db.parent / "secret.key").write_bytes(sk.read_bytes())
            os.chmod(target_db.parent / "secret.key", 0o600)
        tpl = Path(td) / "ppt" / "templates"
        if tpl.exists():
            dt = target_db.parent / "ppt" / "templates"
            dt.mkdir(parents=True, exist_ok=True)
            for f in tpl.iterdir():
                (dt / f.name).write_bytes(f.read_bytes())
    return {"restored": str(path), "integrity": chk}


def _loop():
    while True:
        try:
            ops.beat("backup")
            c = cfg()
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            if c["enabled"] and now.strftime("%H:%M") >= c["time"] and db.get_setting("backup_sched_last") != today:
                db.set_setting("backup_sched_last", today)
                ops.run_job("backup", backup_now, "定时")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(60)


def start_scheduler():
    if os.environ.get("PH_DISABLE_SCHEDULER") or not ops.acquire_scheduler_lock():
        return
    threading.Thread(target=_loop, daemon=True, name="backup-scheduler").start()


def require_file(name):
    p = bdir() / name
    if "/" in name or not p.exists() or not _parse(name):
        raise HTTPException(404, "备份不存在")
    return p
