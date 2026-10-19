"""管理飞书长连接子进程：随服务启动、保存配置后重启、异常退出按退避重试。"""
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from .. import db
from ..config import DATA_DIR
from . import config as C

_lock = threading.RLock()
_proc = {"p": None, "sig": None, "stop": False}


def _sig(cfg):
    return (cfg["enabled"], cfg["mode"], cfg["app_id"], cfg["app_secret_enc"], cfg["verification_token_enc"], cfg["encrypt_key_enc"], cfg["domain"])


def status():
    p = _proc["p"]
    s = db.get_setting("feishu_ws_status", {}) or {}
    alive = bool(p and p.poll() is None)
    cfg = C.get()
    want = cfg["enabled"] and cfg["mode"] == "ws" and C.configured(cfg)
    if not want:
        return {"state": "未启用", "msg": "接收方式不是长连接或机器人未启用", "running": False}
    state = s.get("state", "未启动")
    if alive and state == "连接中" and s.get("at") and (datetime.now() - datetime.strptime(s["at"], "%Y-%m-%d %H:%M:%S")).total_seconds() > 20:
        state = "运行中"  # 进程存活超过 20 秒仍未退出：凭据通过校验、长连接已建立（失败时进程会立即退出）
    return {"state": state if alive else (s.get("state") if s.get("state") == "连接失败" else "未运行"), "msg": s.get("msg", ""), "at": s.get("at"), "running": alive}


def stop():
    with _lock:
        p = _proc["p"]
        _proc["p"] = None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(8)
            except subprocess.TimeoutExpired:
                p.kill()


def _spawn():
    log = open(DATA_DIR / "feishu_ws.log", "ab")
    env = dict(os.environ)
    p = subprocess.Popen([sys.executable, "-m", "app.feishu.ws_runner"], stdout=log, stderr=log, env=env, cwd=str(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
    _proc["p"] = p
    return p


def apply():
    """配置变更后调用：按最新配置启动 / 重启 / 停止长连接。"""
    with _lock:
        cfg = C.get()
        stop()
        _proc["sig"] = _sig(cfg)
        if cfg["enabled"] and cfg["mode"] == "ws" and C.configured(cfg):
            db.set_setting("feishu_ws_status", {"state": "连接中", "msg": "", "at": db.now()})
            _spawn()
        else:
            db.set_setting("feishu_ws_status", {"state": "未启用", "msg": "", "at": db.now()})


def _supervise():
    backoff = 20
    while True:
        time.sleep(15)
        try:
            cfg = C.get()
            want = cfg["enabled"] and cfg["mode"] == "ws" and C.configured(cfg)
            with _lock:
                p = _proc["p"]
                if _sig(cfg) != _proc["sig"]:
                    apply()
                elif want and (p is None or p.poll() is not None):
                    if p is not None:
                        backoff = min(backoff * 2, 300)
                    time.sleep(min(backoff, 5))
                    _spawn()
                elif p and p.poll() is None:
                    backoff = 20
        except Exception:  # noqa: BLE001
            pass


def start():
    if os.environ.get("PH_DISABLE_SCHEDULER"):
        return
    apply()
    threading.Thread(target=_supervise, daemon=True, name="feishu-ws-supervisor").start()
