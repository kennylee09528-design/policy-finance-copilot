"""登录/角色 UI 冒烟 + 截图（本地 session 模式）：python tests/ui_login_shots.py
自动起一个临时数据目录的本地服务，走：登录页 → 管理员登录 → 新建内部/机构账号 → 机构账号首次改密 → 机构视图。"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.async_api import async_playwright

OUT = "/workspace/ai-contest/screens"
PORT = 8023
BASE = f"http://127.0.0.1:{PORT}"


def start():
    d = tempfile.mkdtemp()
    env = dict(os.environ, PH_DATA_DIR=d, PH_DISABLE_SCHEDULER="1", PH_AUTH_MODE="session")
    pw = "Shot-Admin-2026x"
    subprocess.run([sys.executable, "-c", f"from app import admin_auth as A; A.reset_password('admin','{pw}')"], env=env, check=True)
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            httpx.get(BASE + "/api/health"); break
        except Exception:
            time.sleep(0.5)
    c = httpx.Client(base_url=BASE)
    c.post("/api/admin/login", json={"username": "admin", "password": pw})
    c.post("/api/admin/password", json={"old": pw, "new": "Shot-Admin-2026y"})
    c.post("/api/m4/import-sample"); c.post("/api/m5/limit-sets/import-sample"); c.post("/api/m5/snapshots/sample", json={})
    inst = c.get("/api/institutions").json()[0]["full_name"]
    ipw = c.post("/api/admin/users", json={"username": "jg_shot", "display_name": "机构用户A", "role": "institution", "org": inst}).json()["initial_password"]
    return p, ipw


async def main():
    p, ipw = start()
    errs = []
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
            ctx = await b.new_context(viewport={"width": 1500, "height": 950})
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(BASE + "/"); await pg.wait_for_timeout(1200)
            await pg.screenshot(path=f"{OUT}/auth-login.png")
            await pg.fill("#li_u", "admin"); await pg.fill("#li_p", "Shot-Admin-2026y"); await pg.click("#li_ok")
            await pg.wait_for_timeout(1500)
            assert "工作台" in await pg.inner_text("#view")
            await pg.goto(BASE + "/#admin/users"); await pg.wait_for_timeout(1500)
            await pg.screenshot(path=f"{OUT}/auth-admin_users.png", full_page=True)
            await pg.click("text=退出"); await pg.wait_for_timeout(800)
            await pg.fill("#li_u", "jg_shot"); await pg.fill("#li_p", ipw); await pg.click("#li_ok"); await pg.wait_for_timeout(1200)
            await pg.screenshot(path=f"{OUT}/auth-force_change.png")
            await pg.fill("#pw_o", ipw); await pg.fill("#pw_n", "Inst-Pass-2026"); await pg.fill("#pw_n2", "Inst-Pass-2026"); await pg.click("#pw_ok")
            await pg.wait_for_timeout(1500)
            await pg.goto(BASE + "/#m5"); await pg.wait_for_timeout(2000)
            await pg.screenshot(path=f"{OUT}/auth-institution_m5.png", full_page=True)
            hidden = await pg.eval_on_selector_all(".nav-item.hidden", "els => els.map(e => e.dataset.page)")
            print("机构用户隐藏菜单:", hidden)
            assert "m4" in hidden and "ppt" in hidden and "m3" in hidden
            await b.close()
    finally:
        p.terminate()
    print("page errors:", errs)
    sys.exit(1 if errs else 0)


asyncio.run(main())
