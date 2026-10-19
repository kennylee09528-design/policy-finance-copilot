"""飞书长连接（WebSocket）接收进程：python -m app.feishu.ws_runner
由主进程的 ws_manager 拉起/重启；使用官方 lark-oapi SDK 主动连接飞书（出站连接，无需公网回调地址 / 不受 Caddy 口令影响）。"""
import json
import sys

from .. import db
from . import config as C
from . import service as S


def set_status(state, msg=""):
    db.set_setting("feishu_ws_status", {"state": state, "msg": msg[:300], "at": db.now()})


def build_handler(cfg, dispatch=None):
    """SDK 事件处理器：把 SDK 的强类型事件还原成与 HTTP 回调一致的 JSON，交给 service.dispatch。"""
    import lark_oapi as lark
    dispatch = dispatch or S.dispatch

    def on_message(data):
        try:
            dispatch(json.loads(lark.JSON.marshal(data)), source="长连接")
        except Exception as e:  # noqa: BLE001
            print("dispatch error:", e, file=sys.stderr, flush=True)

    return (lark.EventDispatcherHandler.builder(C.secret(cfg, "encrypt_key"), C.secret(cfg, "verification_token"))
            .register_p2_im_message_receive_v1(on_message).build())


def main():
    cfg = C.get()
    if not (cfg["enabled"] and C.configured(cfg)):
        return 0
    import lark_oapi as lark
    secret = C.secret(cfg, "app_secret")
    handler = build_handler(cfg)
    cli = lark.ws.Client(cfg["app_id"], secret, event_handler=handler, log_level=lark.LogLevel.INFO, domain=C.base_url(cfg))
    set_status("连接中", "正在连接飞书长连接…")
    cli.start()  # 阻塞；初始连接失败（如凭据错误）会抛异常 → 进程退出，由 manager 记录并按退避重试
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        set_status("连接失败", f"{type(e).__name__}: {e}")
        print("ws runner failed:", e, file=sys.stderr, flush=True)
        sys.exit(1)
