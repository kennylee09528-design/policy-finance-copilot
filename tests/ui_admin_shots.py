"""系统管理页截图（在独立演示实例上执行，不改动正式实例的管理员密码）：python tests/ui_admin_shots.py http://127.0.0.1:8001 <data_dir>"""
import sys, asyncio, pathlib
from playwright.async_api import async_playwright
BASE, DD = sys.argv[1], pathlib.Path(sys.argv[2])
OUT = "/workspace/ai-contest/screens"
async def main():
    pw = [l.split("：", 1)[1].strip() for l in (DD / "admin_initial_password.txt").read_text().splitlines() if l.startswith("初始密码")][0]
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width": 1600, "height": 1000})
        await pg.goto(BASE + "/#admin"); await pg.wait_for_timeout(1000)
        await pg.screenshot(path=f"{OUT}/22_admin_login.png")
        await pg.fill("#lg_p", pw); await pg.click("#lg_ok"); await pg.wait_for_timeout(1200)
        await pg.screenshot(path=f"{OUT}/23_admin_force_change.png")
        await pg.fill("#cp_o", pw); await pg.fill("#cp_n", "Demo-Admin-2026!"); await pg.fill("#cp_n2", "Demo-Admin-2026!")
        await pg.click("#cp_ok"); await pg.wait_for_timeout(1200)
        async def add(vendor, url=None, name=None):
            await pg.click(f"text={vendor}"); await pg.wait_for_timeout(400)
            if name: await pg.fill("#pf_name", name)
            if url: await pg.fill("#pf_url", url)
            await pg.click("#pf_ok"); await pg.wait_for_timeout(900)
        await add("公司私有模型（自有算力云）", "https://llm.company.internal/v1", "公司私有模型（示例地址，待填写真实网关）")
        await add("DeepSeek 深度求索"); await add("通义千问（阿里云百炼）")
        await pg.click("text=＋ 添加模型 >> nth=0"); await pg.wait_for_timeout(400)
        await pg.fill("#mf_id", "（待填写模型ID）"); await pg.fill("#mf_dn", "私有大模型"); await pg.click("#mf_ok"); await pg.wait_for_timeout(900)
        links = pg.locator("a.edit", has_text="测试连接")
        await links.nth(1).click(); await pg.wait_for_timeout(6000)
        await pg.screenshot(path=f"{OUT}/24_admin_llm_config.png", full_page=True)
        await pg.locator("button", has_text="编辑").nth(1).click(); await pg.wait_for_timeout(500)
        await pg.screenshot(path=f"{OUT}/25_admin_provider_edit.png")
        await pg.keyboard.press("Escape"); await pg.evaluate("closeModal()")
        await pg.goto(BASE + "/#admin/search"); await pg.wait_for_timeout(1000)
        for name in ["Tavily Search", "阿里云 IQS 通义晓搜（UnifiedSearch）"]:
            await pg.click(f"button:has-text('{name}')"); await pg.wait_for_timeout(400)
            await pg.click("#sp_ok"); await pg.wait_for_timeout(900)
        await pg.locator("a.edit", has_text="测试").first.click(); await pg.wait_for_timeout(5000)
        await pg.screenshot(path=f"{OUT}/27_admin_search.png", full_page=True)
        await pg.goto(BASE + "/#admin/m1"); await pg.wait_for_timeout(1200)
        await pg.screenshot(path=f"{OUT}/28_admin_m1_rules.png", full_page=True)
        await pg.goto(BASE + "/#m1"); await pg.wait_for_timeout(1200)
        await pg.screenshot(path=f"{OUT}/29_m1_collect.png", full_page=True)
        await pg.goto(BASE + "/#m3"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path=f"{OUT}/26_m3_research.png", full_page=True)
        await b.close()
asyncio.run(main())
