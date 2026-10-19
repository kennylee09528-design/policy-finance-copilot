"""回归：登录页密码框必须能用真实键盘输入（曾因 onkeydown 返回 false 吞掉按键）。
- 静态检查：前端不得出现 `onkeydown = e => ... && ...` 这类会返回 false 的写法；
- 浏览器检查（有 Playwright + Chrome 时）：逐键输入用户名/密码，回车登录；业务账号访问系统管理时的管理员登录框同样可输入。"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
CHROME = "/usr/bin/google-chrome"


def test_no_key_handler_returning_false():
    bad = []
    for f in (ROOT / "static").rglob("*.js"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"on(keydown|keypress|keyup|beforeinput|input)\s*=\s*\(?\w*\)?\s*=>(?!\s*\{)", line):
                bad.append(f"{f.name}:{i}: {line.strip()}")
    assert not bad, "按键处理函数请用花括号函数体，避免返回 false 取消输入：\n" + "\n".join(bad)


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def live():
    pytest.importorskip("playwright")
    if not shutil.which(CHROME) and not os.path.exists(CHROME):
        pytest.skip("no chrome")
    d = tempfile.mkdtemp(); port = _free_port(); base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PH_DATA_DIR=d, PH_DISABLE_SCHEDULER="1", PH_AUTH_MODE="session")
    subprocess.run([sys.executable, "-c", "from app import admin_auth as A; A.reset_password('admin','Type-Admin-2026x')"], env=env, check=True, cwd=ROOT)
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], env=env, cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                httpx.get(base + "/api/health"); break
            except Exception:
                time.sleep(0.25)
        c = httpx.Client(base_url=base)
        c.post("/api/admin/login", json={"username": "admin", "password": "Type-Admin-2026x"})
        c.post("/api/admin/password", json={"old": "Type-Admin-2026x", "new": "Type-Admin-2026y"})
        ipw = c.post("/api/admin/users", json={"username": "nb_type", "display_name": "内部用户", "role": "internal"}).json()["initial_password"]
        yield base, ipw
    finally:
        p.terminate(); p.wait(10)


def test_password_fields_accept_real_typing(live):
    from playwright.sync_api import sync_playwright
    base, ipw = live
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/"); pg.wait_for_selector("#li_p")
        # 错误密码：逐键输入后值完整，回车得到「用户名或密码错误」
        pg.click("#li_u"); pg.keyboard.type("admin")
        pg.click("#li_p"); pg.keyboard.type("Wrong-Pass-1")
        assert pg.input_value("#li_u") == "admin"
        assert pg.input_value("#li_p") == "Wrong-Pass-1"
        pg.keyboard.press("Backspace"); assert pg.input_value("#li_p") == "Wrong-Pass-"
        pg.keyboard.press("Enter"); pg.wait_for_selector("#toast", state="visible")
        assert "用户名或密码错误" in pg.inner_text("#toast")
        # 正确密码：键盘输入 + 回车登录管理员
        pg.fill("#li_p", ""); pg.click("#li_p"); pg.keyboard.type("Type-Admin-2026y"); pg.keyboard.press("Enter")
        pg.wait_for_selector("#loginMask.hidden", state="attached", timeout=8000)
        pg.click("text=退出"); pg.wait_for_selector("#li_p")
        # 业务账号首次登录 → 改密页三个密码框都能输入
        pg.click("#li_u"); pg.keyboard.type("nb_type"); pg.click("#li_p"); pg.keyboard.type(ipw); pg.keyboard.press("Enter")
        pg.wait_for_selector("#pw_o")
        for sel, val in (("#pw_o", ipw), ("#pw_n", "Type-User-2026z"), ("#pw_n2", "Type-User-2026z")):
            pg.click(sel); pg.keyboard.type(val); assert pg.input_value(sel) == val
        pg.click("#pw_ok"); pg.wait_for_selector("#loginMask.hidden", state="attached", timeout=8000)
        # 业务账号访问系统管理 → 管理员登录框可输入
        pg.goto(base + "/#admin"); pg.wait_for_selector("#lg_p")
        pg.click("#lg_u"); pg.keyboard.type("admin"); pg.click("#lg_p"); pg.keyboard.type("Type-Admin-2026y")
        assert pg.input_value("#lg_p") == "Type-Admin-2026y"
        b.close()
    assert not errs, errs


def test_frontend_not_cached_stale(client):
    for path in ("/", "/static/js/app.js"):
        r = client.get(path)
        assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache"


def test_app_never_returns_401_behind_basic_auth(client):
    """外层 Basic Auth 下，应用 401 会让 Chrome 清掉缓存口令并循环弹窗；应用层一律 403 + X-App-Auth。"""
    from fastapi.testclient import TestClient
    from app.main import app
    anon = TestClient(app)
    for method, path, body in (("post", "/api/admin/login", {"username": "admin", "password": "wrong-pass-x"}),
                               ("post", "/api/auth/login", {"username": "nobody_x", "password": "wrong-pass-x"}),
                               ("get", "/api/admin/me", None)):
        r = getattr(anon, method)(path, json=body) if body else getattr(anon, method)(path)
        if r.status_code == 200:
            continue  # 某些 me 接口未登录返回 logged_in=false
        assert r.status_code != 401 and "www-authenticate" not in r.headers, (path, r.status_code)
    r = anon.post("/api/admin/login", json={"username": "admin", "password": "wrong-pass-x"})
    assert r.status_code == 403 and r.headers.get("x-app-auth") == "login-required"
