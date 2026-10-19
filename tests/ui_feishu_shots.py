"""飞书机器人 UI 冒烟 + 截图（本地临时实例；飞书 API 为本地 mock，不需要真实凭据）：python tests/ui_feishu_shots.py"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.async_api import async_playwright

OUT = "/workspace/ai-contest/screens"
PORT = 8027
BASE = f"http://127.0.0.1:{PORT}"
PW = "Fs-Admin-2026y"


def start():
    d = tempfile.mkdtemp()
    env = dict(os.environ, PH_DATA_DIR=d, PH_DISABLE_SCHEDULER="1", PH_AUTH_MODE="session")
    subprocess.run([sys.executable, "-c", "from app import admin_auth as A; A.reset_password('admin','Fs-Admin-2026x')"], env=env, check=True)
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            httpx.get(BASE + "/api/health"); break
        except Exception:
            time.sleep(0.5)
    c = httpx.Client(base_url=BASE, timeout=180)
    c.post("/api/admin/login", json={"username": "admin", "password": "Fs-Admin-2026x"})
    c.post("/api/admin/password", json={"old": "Fs-Admin-2026x", "new": PW})
    assert c.post("/api/admin/demo/load").status_code == 200
    r = c.post("/api/admin/users", json={"username": "zhang_san", "display_name": "张三", "role": "internal"}).json()
    c.put("/api/admin/feishu/config", json={"app_id": "cli_demo1234567890", "app_secret": "demo-secret-not-real", "mode": "ws", "enabled": True})
    return p, c, r["initial_password"], d, env


async def main():
    p, c, zpw, d, env = start()
    errs = []
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
            pg = await (await b.new_context(viewport={"width": 1500, "height": 1000})).new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(BASE + "/"); await pg.wait_for_selector("#li_u")
            await pg.click("#li_u"); await pg.keyboard.type("zhang_san"); await pg.click("#li_p"); await pg.keyboard.type(zpw); await pg.keyboard.press("Enter")
            await pg.wait_for_selector("#pw_o")
            for s, v in (("#pw_o", zpw), ("#pw_n", "Zhang-Pass-2026z"), ("#pw_n2", "Zhang-Pass-2026z")):
                await pg.click(s); await pg.keyboard.type(v)
            await pg.click("#pw_ok"); await pg.wait_for_timeout(1500)
            await pg.click("text=绑定飞书"); await pg.wait_for_selector("text=一次性绑定码"); await pg.wait_for_timeout(500)
            await pg.screenshot(path=f"{OUT}/feishu-bind_dialog.png")
            code = (await pg.inner_text(".note-box b")).split()[-1]
            await pg.evaluate("closeModal()")
            # 模拟机器人收到消息（mock 飞书 API；同一数据目录的独立进程调用服务层）
            sim = f"""
import json
from app.feishu import api as FA, service as S
LOG = []
class F:
    def bot_info(self): return {{"open_id":"ou_bot","name":"普惠业务工作台"}}
    def reply_text(self,*a): LOG.append(("bot", a[1]))
    def send_text(self,*a): LOG.append(("bot", a[1]))
    def upload_file(self,name,data): LOG.append(("file", name)); return name
    def send_file(self,*a): pass
FA.get_api = lambda: F()
def ev(t, i, oid="ou_demo_user_01"):
    if oid == "ou_demo_user_01" and not t.startswith("绑定"): LOG.append(("me", t))
    return {{"header":{{"event_id":"e%s"%i,"event_type":"im.message.receive_v1"}},"event":{{"sender":{{"sender_id":{{"open_id":oid}},"sender_type":"user"}},
      "message":{{"message_id":"m%s"%i,"chat_id":"oc_1","chat_type":"p2p","message_type":"text","content":json.dumps({{"text":t}},ensure_ascii=False)}}}}}}
S.dispatch(ev("额度", 1, "ou_stranger_0099"), sync=True)
for i,t in enumerate(["绑定 {code}","额度","预警","今日简报","报告","报告文件 #1","生成PPT"], 10): S.dispatch(ev(t,i), sync=True)
S._hits.clear()
S.dispatch(ev("绑定 AAAABBBB", 99, "ou_stranger_0099"), sync=True)
json.dump(LOG, open("{d}/transcript.json","w"), ensure_ascii=False)
"""
            subprocess.run([sys.executable, "-c", sim], env=env, check=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            import html, json
            log = json.load(open(f"{d}/transcript.json"))
            bub = "".join(f'<div class="r {k}"><div class="b">{"📎 " if k == "file" else ""}{html.escape(t).replace(chr(10), "<br>")}</div></div>' for k, t in log)
            pg2 = await (await b.new_context(viewport={"width": 760, "height": 1500})).new_page()
            await pg2.set_content(f"""<style>body{{font:14px 'Noto Sans CJK SC','Microsoft YaHei',sans-serif;background:#ededed;margin:0;padding:14px}}
            h4{{text-align:center;color:#888;font-weight:normal;margin:4px 0 12px}} .r{{display:flex;margin:8px 0}} .r.me{{justify-content:flex-end}}
            .b{{max-width:78%;padding:9px 12px;border-radius:8px;background:#fff;line-height:1.55;white-space:normal}} .me .b{{background:#95ec69}} .file .b{{background:#fff;border:1px solid #ccc}}</style>
            <h4>示意（飞书会话；机器人回复来自真实服务层 + 演示数据，飞书 API 为 mock）</h4>{bub}""")
            await pg2.screenshot(path=f"{OUT}/feishu-chat_simulated.png", full_page=True)
            await pg.click("text=退出"); await pg.wait_for_selector("#li_p")
            await pg.click("#li_u"); await pg.keyboard.type("admin"); await pg.click("#li_p"); await pg.keyboard.type(PW); await pg.keyboard.press("Enter"); await pg.wait_for_timeout(1500)
            await pg.goto(BASE + "/#admin/feishu"); await pg.wait_for_timeout(2000)
            await pg.screenshot(path=f"{OUT}/feishu-admin_config.png", full_page=True)
            t = await pg.inner_text("#view")
            assert "ou_demo_user_01" in t and "未绑定" in t and "zhang_san" in t, "事件日志/绑定列表未显示"
            assert "demo-secret-not-real" not in await pg.content()
            await b.close()
    finally:
        p.terminate()
    print("页面错误：", errs or "无")
    assert not errs

asyncio.run(main())
