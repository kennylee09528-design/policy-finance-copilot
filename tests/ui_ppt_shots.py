"""PPT 页面冒烟 + 截图：python tests/ui_ppt_shots.py http://127.0.0.1:8011 demo [user:pass]"""
import asyncio
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011"
PREFIX = sys.argv[2] if len(sys.argv) > 2 else "demo"
CRED = sys.argv[3] if len(sys.argv) > 3 else None
OUT = "/workspace/ai-contest/screens"


async def main():
    errs = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        kw = {"viewport": {"width": 1600, "height": 1000}, "ignore_https_errors": False}
        if CRED:
            u, pw = CRED.split(":", 1)
            kw["http_credentials"] = {"username": u, "password": pw}
        ctx = await b.new_context(**kw)
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))

        async def shot(name, h, wait=1500):
            await pg.goto(BASE + "/" + h)
            await pg.reload()
            await pg.wait_for_timeout(wait)
            txt = await pg.inner_text("#view")
            if "页面加载失败" in txt:
                errs.append(f"{name}: {txt[:200]}")
            await pg.screenshot(path=f"{OUT}/{PREFIX}-{name}.png", full_page=True)
        await shot("ppt_new", "#ppt")
        # 走一遍 UI：选择额度汇报 → 不用模型 → 开始
        await pg.select_option("#p_model", "")
        await pg.click("text=开始：请 Agent 确认需求")
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path=f"{OUT}/{PREFIX}-ppt_sheet.png", full_page=True)
        await pg.fill(".p_ans >> nth=0", "公司经营层，突出预警机构")
        await pg.click("text=确认需求单，生成大纲")
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path=f"{OUT}/{PREFIX}-ppt_outline.png", full_page=True)
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await pg.click("text=确认大纲，生成 PPT")
        await pg.wait_for_timeout(9000)
        await pg.screenshot(path=f"{OUT}/{PREFIX}-ppt_done.png", full_page=True)
        txt = await pg.inner_text("#view")
        if "数字溯源通过" not in txt:
            errs.append("生成后未见『数字溯源通过』")
        await shot("ppt_history", "#ppt/history")
        await b.close()
    print("ERRORS:", errs or "none")

asyncio.run(main())
