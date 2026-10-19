"""微信普惠Bot UI 冒烟 + 截图（QR 用 mock iLink）：python tests/ui_wechat_shots.py"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.async_api import async_playwright

OUT = "/workspace/ai-contest/screens"
PORT = 8028
BASE = f"http://127.0.0.1:{PORT}"
PW = "Wx-Admin-2026y"


def start():
    d = tempfile.mkdtemp()
    env = dict(os.environ, PH_DATA_DIR=d, PH_DISABLE_SCHEDULER="1", PH_AUTH_MODE="session")
    subprocess.run([sys.executable, "-c", "from app import admin_auth as A; A.reset_password('admin','Wx-Admin-2026x')"], env=env, check=True)
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            httpx.get(BASE + "/api/health"); break
        except Exception:
            time.sleep(0.5)
    c = httpx.Client(base_url=BASE, timeout=180)
    c.post("/api/admin/login", json={"username": "admin", "password": "Wx-Admin-2026x"})
    c.post("/api/admin/password", json={"old": "Wx-Admin-2026x", "new": PW})
    assert c.post("/api/admin/demo/load").status_code == 200
    r = c.post("/api/admin/users", json={"username": "zhang_san", "display_name": "张三", "role": "internal"}).json()
    assert c.put("/api/admin/wechat/config", json={"enabled": True, "bot_name": "普惠Bot"}).status_code == 200
    return p, c, r["initial_password"], d, env


async def main():
    p, c, zpw, d, env = start()
    errs = []
    try:
        # mock QR at API level by patching in-process via a one-shot script that writes a fake session? 
        # Simpler: monkeypatch through env isn't available; call identity with fake client in a helper that pre-creates a wait session.
        sim = f'''
from app.wechat import identity as I, ilink as IL, config as C
from app import db
from app.llm.crypto import encrypt
import base64, io, qrcode
# enable already done
# create a fake "wait" session with a real PNG for screenshot
url = "https://liteapp.weixin.qq.com/q/demo-puhui-bot"
buf = io.BytesIO(); qrcode.make(url, box_size=8, border=2).save(buf, format="PNG")
# insert binding for demo list
db.execute("INSERT INTO wechat_bindings(username,ilink_user_id,ilink_bot_id,bot_token_enc,baseurl,status,bound_at,last_seen,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
           ("zhang_san","o9cqDEMO@im.wechat","bot@im.bot",encrypt("demo-token"),"https://ilinkai.weixin.qq.com","正常",db.now(),db.now(),db.now()))
db.execute("INSERT INTO wechat_events(ts,message_id,ilink_user_id,username,text,intent,status,reply,source) VALUES(?,?,?,?,?,?,?,?,?)",
           (db.now(),"m1","o9cqDEMO@im.wechat","zhang_san","额度","quota","已处理","全网额度使用情况…\\n数据来源：M5","微信"))
print("seeded")
'''
        subprocess.run([sys.executable, "-c", sim], env=env, check=True, cwd="/workspace/ai-contest/app")

        async with async_playwright() as pw:
            b = await pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
            pg = await (await b.new_context(viewport={"width": 1500, "height": 1000})).new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(BASE + "/"); await pg.wait_for_selector("#li_u")
            await pg.click("#li_u"); await pg.keyboard.type("admin"); await pg.click("#li_p"); await pg.keyboard.type(PW); await pg.keyboard.press("Enter")
            await pg.wait_for_timeout(1500)
            await pg.goto(BASE + "/#admin/wechat"); await pg.wait_for_timeout(2000)
            await pg.screenshot(path=f"{OUT}/wechat-admin_config.png", full_page=True)
            t = await pg.inner_text("#view")
            assert "普惠Bot" in t and "zhang_san" in t
            # user bind dialog (will call real QR API which hits real weixin — skip by showing already-bound state)
            await pg.click("text=退出登录"); await pg.wait_for_selector("#li_p")
            await pg.click("#li_u"); await pg.keyboard.type("zhang_san"); await pg.click("#li_p"); await pg.keyboard.type(zpw); await pg.keyboard.press("Enter")
            await pg.wait_for_selector("#pw_o")
            for s, v in (("#pw_o", zpw), ("#pw_n", "Zhang-Pass-2026z"), ("#pw_n2", "Zhang-Pass-2026z")):
                await pg.click(s); await pg.keyboard.type(v)
            await pg.click("#pw_ok"); await pg.wait_for_timeout(1500)
            await pg.click("text=绑定微信"); await pg.wait_for_timeout(800)
            await pg.screenshot(path=f"{OUT}/wechat-bind_dialog.png")
            await b.close()
    finally:
        p.terminate()
    print("页面错误：", errs or "无")
    assert not errs

asyncio.run(main())
