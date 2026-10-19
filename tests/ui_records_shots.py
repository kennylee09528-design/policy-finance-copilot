"""归档 / 删除 UI 冒烟 + 截图（本地 session 模式，自动起临时服务并加载演示数据）：python tests/ui_records_shots.py"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.async_api import async_playwright

OUT = "/workspace/ai-contest/screens"
PORT = 8024
BASE = f"http://127.0.0.1:{PORT}"
PW = "Shot-Admin-2026y"


def start():
    d = tempfile.mkdtemp()
    env = dict(os.environ, PH_DATA_DIR=d, PH_DISABLE_SCHEDULER="1", PH_AUTH_MODE="session")
    subprocess.run([sys.executable, "-c", "from app import admin_auth as A; A.reset_password('admin','Shot-Admin-2026x')"], env=env, check=True)
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            httpx.get(BASE + "/api/health"); break
        except Exception:
            time.sleep(0.5)
    c = httpx.Client(base_url=BASE, timeout=120)
    c.post("/api/admin/login", json={"username": "admin", "password": "Shot-Admin-2026x"})
    c.post("/api/admin/password", json={"old": "Shot-Admin-2026x", "new": PW})
    r = c.post("/api/admin/demo/load"); assert r.status_code == 200, r.text
    c.get("/api/m4/schemes/1/export.xlsx")
    return p


async def main():
    p = start()
    errs = []
    try:
        async with async_playwright() as pw:
            b = await pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
            ctx = await b.new_context(viewport={"width": 1500, "height": 950})
            pg = await ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
            await pg.goto(BASE + "/"); await pg.wait_for_timeout(800)
            await pg.fill("#li_u", "admin"); await pg.fill("#li_p", PW); await pg.click("#li_ok"); await pg.wait_for_timeout(1200)

            async def go(h, name, wait=1500):
                await pg.goto(BASE + "/" + h); await pg.wait_for_timeout(wait)
                t = await pg.inner_text("#view")
                if "页面加载失败" in t:
                    errs.append(f"{name}: {t[:200]}")
                await pg.screenshot(path=f"{OUT}/rec-{name}.png", full_page=True)
            await go("#home", "home", 2000)
            await go("#m3", "m3_list")
            # 删除已定稿任务 → 引用确认弹窗
            await pg.click("#view .task-row .rec-acts >> text=删除")
            await pg.wait_for_timeout(1000)
            await pg.screenshot(path=f"{OUT}/rec-m3_delete_confirm.png")
            await pg.click("#rec_force"); await pg.wait_for_timeout(1200)
            await go("#ppt/history", "ppt_history")
            # 批量归档 2 个 PPT 任务
            cbs = await pg.query_selector_all('.rec-cb[data-kind="ppt_job"]')
            for cb in cbs[:2]:
                await cb.check()
            await pg.click("text=批量归档"); await pg.wait_for_timeout(1200)
            await pg.click(".rec-tabs >> text=已归档"); await pg.wait_for_timeout(1000)
            await pg.screenshot(path=f"{OUT}/rec-ppt_archived.png", full_page=True)
            n = len(await pg.query_selector_all('.rec-cb[data-kind="ppt_job"]'))
            assert n == 2, n
            await go("#m4/versions", "m4_versions")
            await go("#m5/import", "m5_snapshots")
            await go("#m2", "m2_list")
            async with ctx.expect_page() as pp:
                await pg.click("text=导出 PDF")
            pdfp = await pp.value; await pdfp.wait_for_timeout(1500)
            await pdfp.screenshot(path=f"{OUT}/rec-m2_pdf_view.png", full_page=True); await pdfp.close()
            await go("#m5/charts", "m5_charts", 2500)
            async with ctx.expect_page() as pp:
                await pg.click("text=导出 PDF 快照")
            pdfp = await pp.value; await pdfp.wait_for_timeout(1500)
            await pdfp.screenshot(path=f"{OUT}/rec-m5_pdf_view.png", full_page=True)
            assert await pdfp.locator("img").count() >= 1, "图表未转为图片"
            await pdfp.close()
            await go("#m1", "m1_runs")
            await go("#m1/semantic", "m1_semantic_empty", 800)
            await pg.fill("#sq", "降低担保费率的奖补政策"); await pg.click("#view .panel button.primary"); await pg.wait_for_timeout(1500)
            await pg.screenshot(path=f"{OUT}/rec-m1_semantic.png", full_page=True)
            await go("#m1/health", "m1_health")
            await go("#m1/review", "m1_review")
            await go("#m1/dedup", "m1_dedup")
            await go("#admin/calls", "admin_llm_calls")
            await go("#admin/users", "admin_users")
            await go("#audit/exports", "exports")
            await go("#audit/bin", "recycle_bin")
            assert "M3 写作任务" in await pg.inner_text("#view")
            await b.close()
    finally:
        p.terminate()
    print("page errors:", errs)
    sys.exit(1 if errs else 0)


asyncio.run(main())
