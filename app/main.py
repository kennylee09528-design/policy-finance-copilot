"""普惠业务工作台 · FastAPI 入口（单进程：uvicorn app.main:app）。"""
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import STATIC_DIR
from .routes_common import r as common_r
from .routes_m4 import r as m4_r, selftest
from .routes_m5 import r as m5_r

app = FastAPI(title="普惠业务工作台 API", version="0.1.0")
db.conn()
app.include_router(common_r)
app.include_router(m4_r)
app.include_router(selftest)
app.include_router(m5_r)

from .routes_admin import r as admin_r  # noqa: E402
from . import admin_auth  # noqa: E402

app.include_router(admin_r)
from .routes_m1m3 import r as m1m3_r  # noqa: E402
from .m1 import collector as m1_collector  # noqa: E402

app.include_router(m1m3_r)
from .routes_m2m3 import r as m2m3_r  # noqa: E402
from .m2 import brief as m2_brief  # noqa: E402

app.include_router(m2m3_r)
from . import ops  # noqa: E402

ops.recover_on_startup()  # 重启前未完成的 M3 写作 / M1 采集标记为「已中断」
m1_collector.start_scheduler()
m2_brief.start_scheduler()
from . import backup as _backup  # noqa: E402

_backup.start_scheduler()  # 每日数据库备份（PH_BACKUP_DIR，轮换保留）
admin_auth.ensure_admin()  # 首次启动生成随机初始密码 → data/admin_initial_password.txt（600）
from . import users as _users  # noqa: E402
from .routes_auth import r as auth_r  # noqa: E402

_users.ensure_demo_users()  # 首次启动生成业务演示账号 → data/user_initial_passwords.txt（600）
app.include_router(auth_r)


@app.middleware("http")
async def _no_http_401(request, call_next):
    """应用层「未登录/用户名或密码错误」不用 HTTP 401：站点外层有 Caddy Basic Auth，
    Chrome 收到带缓存口令请求的 401（即使没有 WWW-Authenticate）会把外层口令判为被拒并清出缓存，
    下一个请求就会再次弹出浏览器口令框（循环弹窗）。改为 403 + X-App-Auth: login-required，前端据此回到登录页。"""
    resp = await call_next(request)
    if resp.status_code == 401:
        resp.status_code = 403
        resp.headers["X-App-Auth"] = "login-required"
        if "www-authenticate" in resp.headers:
            del resp.headers["www-authenticate"]
    return resp


@app.middleware("http")
async def _no_stale_frontend(request, call_next):
    """前端页面与脚本每次向服务器校验（ETag 未变则 304），避免浏览器沿用旧版 JS。"""
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p == "/selftest" or p.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "no-cache")
    return resp


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/selftest")
def selftest_page():
    return FileResponse(STATIC_DIR / "selftest.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
from .routes_ppt import r as ppt_r  # noqa: E402

app.include_router(ppt_r)
from .routes_mail import r as mail_r  # noqa: E402

app.include_router(mail_r)
from .routes_feishu import r as feishu_r  # noqa: E402

app.include_router(feishu_r)
from .feishu import ws_manager as _feishu_ws  # noqa: E402

_feishu_ws.start()  # 启用且为长连接模式时，拉起飞书长连接接收进程（测试/PH_DISABLE_SCHEDULER 下不启动）
from .routes_wechat import r as wechat_r  # noqa: E402

app.include_router(wechat_r)
from .wechat import poller as _wechat_poller  # noqa: E402

_wechat_poller.start()  # 启用后为每个已绑定微信拉起长轮询（PH_DISABLE_SCHEDULER 下不启动）
