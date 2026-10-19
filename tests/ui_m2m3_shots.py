"""M2/M3 页面冒烟 + 截图（演示实例，假模型）：python tests/ui_m2m3_shots.py http://127.0.0.1:8001 demo"""
import sys, asyncio, json
from playwright.async_api import async_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
PREFIX = sys.argv[2] if len(sys.argv) > 2 else "demo"
OUT = "/workspace/ai-contest/screens"
async def main():
    errs = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1600, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        async def shot(name, h, wait=1800, full=True):
            await pg.goto(BASE + "/" + h); await pg.reload(); await pg.wait_for_timeout(wait)
            txt = await pg.inner_text("#view")
            if "页面加载失败" in txt: errs.append(f"{name}: {txt[:200]}")
            await pg.screenshot(path=f"{OUT}/{PREFIX}-{name}.png", full_page=full)
        await shot("m2_brief", "#m2")
        await shot("m3_task_draft", "#m3/tasks", 2500)
        # 人工终稿：删无出处句、改措辞，确认存疑句，定稿，总结
        r = await pg.request.get(BASE + "/api/m3/tasks/1"); t = await r.json()
        if t["status"].startswith("待人工"):
            final = t["draft"].replace("我省合作担保机构数量达到58家，位居全国前列。", "").replace("持续优化", "持续深化")
            r = await pg.request.put(BASE + "/api/m3/tasks/1/final", data=json.dumps({"final": final}), headers={"Content-Type": "application/json"})
            chk = await r.json()
            await shot("m3_task_review", "#m3/tasks", 2000)
            for i in chk["items"]:
                if i["red"]:
                    await pg.request.post(BASE + "/api/m3/tasks/1/confirm", data=json.dumps({"key": i["key"], "reason": "演示：已与原始文件核对"}), headers={"Content-Type": "application/json"})
            await pg.request.post(BASE + "/api/m3/tasks/1/finalize")
            await pg.request.post(BASE + "/api/m3/tasks/1/summarize")
        await shot("m3_task_final", "#m3/tasks", 2000)
        await shot("m3_style", "#m3/style")
        await pg.request.post(BASE + "/api/admin/login", data=json.dumps({"username": "admin", "password": "Demo-init-1234"}), headers={"Content-Type": "application/json"})
        await pg.request.post(BASE + "/api/admin/password", data=json.dumps({"old": "Demo-init-1234", "new": "Demo-Admin-2026!x"}), headers={"Content-Type": "application/json"})
        await shot("admin_m2", "#admin/m2")
        await shot("admin_m3", "#admin/m3")
        await b.close()
    print("ERRORS:", errs or "none")
asyncio.run(main())
