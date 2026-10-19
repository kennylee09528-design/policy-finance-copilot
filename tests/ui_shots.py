"""前端冒烟 + 截图：python tests/ui_shots.py [base_url]"""
import sys, asyncio
from playwright.async_api import async_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = "/workspace/ai-contest/screens"
PAGES = [("01_home", "#home"), ("02_m4_result", "#m4/result"), ("03_m4_data", "#m4/data"), ("04_m4_params", "#m4/params"),
         ("05_m4_versions", "#m4/versions"), ("06_m4_qingshi", "#m4/qingshi"), ("07_m4_history", "#m4/history"),
         ("08_m5_summary", "#m5/summary"), ("09_m5_inst", "#m5/inst"), ("10_m5_charts", "#m5/charts"), ("11_m5_import", "#m5/import"),
         ("12_m5_limits", "#m5/limits"), ("13_m5_rules", "#m5/rules"), ("14_inst", "#inst"), ("15_audit", "#audit"),
         ("16_m1_proto", "#m1/kb"), ("17_m2", "#m2"), ("18_m3_proto", "#m3/writing"), ("20_admin", "#admin")]
async def main():
    errs = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1600, "height": 1000})
        pg.on("console", lambda m: m.type == "error" and errs.append(m.text))
        pg.on("pageerror", lambda e: errs.append(str(e)))
        for name, h in PAGES:
            await pg.goto(BASE + "/" + h); await pg.wait_for_timeout(1500)
            await pg.screenshot(path=f"{OUT}/{name}.png", full_page=name not in ("16_m1_proto", "17_m2", "18_m3_proto"))
            txt = await pg.inner_text("#view")
            if "页面加载失败" in txt: errs.append(f"{name}: {txt[:200]}")
        await pg.goto(BASE + "/selftest"); await pg.wait_for_timeout(800)
        for k, v in dict(scale=500000, emp=300, zxzn=95, lj=1.5, dn=1.2, pj=90, zc=100000).items():
            await pg.fill("#" + k, str(v))
        await pg.click("#go"); await pg.wait_for_timeout(800)
        await pg.screenshot(path=f"{OUT}/19_selftest.png", full_page=True)
        # 机构用户视图
        await pg.goto(BASE + "/#m5"); await pg.evaluate("localStorage.setItem('ph_role','institution');localStorage.removeItem('ph_org')")
        await pg.reload(); await pg.wait_for_timeout(1800)
        await pg.screenshot(path=f"{OUT}/21_m5_institution_view.png", full_page=True)
        await pg.evaluate("localStorage.setItem('ph_role','internal');localStorage.removeItem('ph_org')")
        await b.close()
    print("ERRORS:", errs or "none")
asyncio.run(main())
