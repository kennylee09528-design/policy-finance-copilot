"""邮件发送 UI 冒烟 + 截图（本地临时实例 + 本地 SMTP 接收桩）：python tests/ui_mail_shots.py"""
import asyncio
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

import httpx
from playwright.async_api import async_playwright

OUT = "/workspace/ai-contest/screens"
PORT, SMTP_PORT = 8026, 25726
BASE = f"http://127.0.0.1:{PORT}"
PW = "Mail-Admin-2026y"
MAILS = []


class Sink(socketserver.StreamRequestHandler):  # 极简 SMTP 接收桩（只为 UI 冒烟）
    def handle(self):
        w = lambda s: self.wfile.write((s + "\r\n").encode())  # noqa: E731
        w("220 sink ready")
        data = False
        buf = []
        while True:
            ln = self.rfile.readline()
            if not ln:
                return
            ln = ln.decode("utf-8", "replace")
            if data:
                if ln == ".\r\n":
                    MAILS.append("".join(buf)); buf = []; data = False; w("250 queued")
                else:
                    buf.append(ln)
                continue
            c = ln[:4].upper()
            if c in ("EHLO", "HELO"): w("250 sink")
            elif c == "DATA": data = True; w("354 go")
            elif c == "QUIT": w("221 bye"); return
            else: w("250 ok")


def start():
    d = tempfile.mkdtemp()
    env = dict(os.environ, PH_DATA_DIR=d, PH_DISABLE_SCHEDULER="1", PH_AUTH_MODE="session")
    subprocess.run([sys.executable, "-c", "from app import admin_auth as A; A.reset_password('admin','Mail-Admin-2026x')"], env=env, check=True)
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            httpx.get(BASE + "/api/health"); break
        except Exception:
            time.sleep(0.5)
    c = httpx.Client(base_url=BASE, timeout=180)
    c.post("/api/admin/login", json={"username": "admin", "password": "Mail-Admin-2026x"})
    c.post("/api/admin/password", json={"old": "Mail-Admin-2026x", "new": PW})
    assert c.post("/api/admin/demo/load").status_code == 200
    r = c.post("/api/admin/users", json={"username": "zhang_san", "display_name": "张三", "role": "internal"}).json()
    return p, r["initial_password"]


async def main():
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", SMTP_PORT), Sink)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    p, zpw = start()
    errs = []
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
            pg = await (await b.new_context(viewport={"width": 1500, "height": 950})).new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(BASE + "/"); await pg.wait_for_selector("#li_u")
            await pg.click("#li_u"); await pg.keyboard.type("admin"); await pg.click("#li_p"); await pg.keyboard.type(PW); await pg.keyboard.press("Enter"); await pg.wait_for_timeout(1500)
            await pg.goto(BASE + "/#admin/mail"); await pg.wait_for_timeout(1500)
            await pg.fill("#sm_host", "127.0.0.1"); await pg.fill("#sm_port", str(SMTP_PORT)); await pg.select_option("#sm_sec", "none")
            await pg.fill("#sm_user", ""); await pg.fill("#sm_sa", "workbench@company.com"); await pg.fill("#sm_dom", "company.com, *.corp.company.com"); await pg.check("#sm_en")
            await pg.click("text=保存"); await pg.wait_for_timeout(1200)
            await pg.fill("#sm_to", "me@company.com"); await pg.click("text=发送测试邮件"); await pg.wait_for_timeout(2500)
            await pg.screenshot(path=f"{OUT}/mail-admin_config.png", full_page=True)
            assert MAILS, "测试邮件未到达接收桩"
            import email
            from email import policy
            assert "内部资料" in str(email.message_from_string(MAILS[-1], policy=policy.default).get("X-Confidential"))
            # 业务用户：张三 登录（首次改密）
            await pg.click("text=退出登录"); await pg.wait_for_selector("#li_p")
            await pg.click("#li_u"); await pg.keyboard.type("zhang_san"); await pg.click("#li_p"); await pg.keyboard.type(zpw); await pg.keyboard.press("Enter")
            await pg.wait_for_selector("#pw_o")
            for s, v in (("#pw_o", zpw), ("#pw_n", "Zhang-Pass-2026z"), ("#pw_n2", "Zhang-Pass-2026z")):
                await pg.click(s); await pg.keyboard.type(v)
            await pg.click("#pw_ok"); await pg.wait_for_timeout(1500)
            tasks = httpx.get(BASE + "/api/health")  # noqa: F841
            await pg.goto(BASE + "/#m3"); await pg.wait_for_timeout(2000)
            # 选一个已定稿任务
            ok = await pg.evaluate("""async()=>{const l=await api('/api/m3/tasks');const t=l.find(x=>['已定稿','已总结'].includes(x.status));if(!t)return null;M3T.id=t.id;await route();return t.id}""")
            assert ok, "演示数据中没有已定稿的 M3 任务"
            await pg.wait_for_timeout(1800)
            await pg.screenshot(path=f"{OUT}/mail-m3_button.png")
            await pg.click("text=发送到邮箱"); await pg.wait_for_selector("#ml_to")
            await pg.fill("#ml_to", "lisi@company.com; wang@dept.corp.company.com"); await pg.fill("#ml_msg", "请审阅，周五前反馈意见。")
            await pg.screenshot(path=f"{OUT}/mail-dialog.png")
            await pg.click("#ml_next"); await pg.wait_for_selector("#ml_go"); await pg.wait_for_timeout(500)
            await pg.screenshot(path=f"{OUT}/mail-confirm.png")
            await pg.click("#ml_go"); await pg.wait_for_timeout(2500)
            assert any("lisi@company.com" in m for m in MAILS[1:]), "邮件未发出"
            # 外部域名被拒
            await pg.click("text=发送到邮箱"); await pg.wait_for_selector("#ml_to")
            await pg.fill("#ml_to", "outsider@gmail.com"); await pg.click("#ml_next"); await pg.wait_for_timeout(1200)
            await pg.screenshot(path=f"{OUT}/mail-blocked_domain.png")
            await pg.evaluate("closeModal()")
            await pg.goto(BASE + "/#audit/mails"); await pg.wait_for_timeout(1800)
            await pg.screenshot(path=f"{OUT}/mail-history.png")
            await b.close()
    finally:
        p.terminate(); srv.shutdown()
    print("页面错误：", errs or "无")
    assert not errs


asyncio.run(main())
