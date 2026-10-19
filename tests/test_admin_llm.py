"""管理员登录 + 大模型供应商层验收。"""
import os
import stat

import httpx
import pytest

from app import admin_auth
from app.config import DATA_DIR


def _init_pw():
    txt = (DATA_DIR / "admin_initial_password.txt").read_text(encoding="utf-8")
    return [l.split("：", 1)[1].strip() for l in txt.splitlines() if l.startswith("初始密码")][0]


@pytest.fixture(scope="module")
def admin(client):
    f = DATA_DIR / "admin_initial_password.txt"
    assert f.exists() and stat.S_IMODE(os.stat(f).st_mode) == 0o600
    pw = _init_pw()
    assert client.post("/api/admin/login", json={"username": "admin", "password": "wrong-pass"}).status_code == 403
    r = client.post("/api/admin/login", json={"username": "admin", "password": pw})
    assert r.status_code == 200 and r.json()["must_change"] is True
    assert client.get("/api/admin/llm/providers").status_code == 403  # 未改密不可用
    assert client.post("/api/admin/password", json={"old": pw, "new": "short"}).status_code == 400
    assert client.post("/api/admin/password", json={"old": pw, "new": "Ph-Admin-2026!x"}).status_code == 200
    assert not f.exists()
    assert client.get("/api/admin/llm/providers").status_code == 200
    return client


def test_unauthenticated_blocked(client):
    c2 = httpx.Client(transport=client._transport, base_url=str(client.base_url))
    assert c2.get("/api/admin/llm/providers").status_code == 403


def test_provider_key_never_returned(admin, monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, auth=headers.get("Authorization"), body=json)
        return httpx.Response(200, json={"choices": [{"message": {"content": "连接正常"}}], "model": json["model"]})

    monkeypatch.setattr("app.llm.client.httpx.post", fake_post)
    secret = "sk-test-1234567890abcdef"
    r = admin.post("/api/admin/llm/providers", json={"vendor": "company_private", "name": "公司私有模型", "base_url": "https://llm.internal.example/v1",
                                                     "api_key": secret, "models": ["corp-qwen-72b"], "allow_sensitive": True})
    pid = r.json()["id"]
    admin.post("/api/admin/llm/providers", json={"vendor": "deepseek", "base_url": "https://api.deepseek.com/v1", "api_key": "sk-ds-abcdefghijk", "models": ["deepseek-chat"]})
    lst = admin.get("/api/admin/llm/providers").text
    assert secret not in lst and "api_key_enc" not in lst and "sk-****cdef" in lst
    from app import db
    assert secret not in db.q1("SELECT api_key_enc FROM llm_providers WHERE id=?", (pid,))["api_key_enc"]
    provs = admin.get("/api/admin/llm/providers").json()
    priv = next(p for p in provs if p["id"] == pid)["models"][0]
    ds = next(p for p in provs if p["vendor"] == "deepseek")["models"][0]
    t = admin.post(f"/api/admin/llm/models/{priv['id']}/test").json()
    assert t["ok"] and seen["url"] == "https://llm.internal.example/v1/chat/completions" and seen["auth"] == f"Bearer {secret}"
    pub = admin.get("/api/llm/models").text
    assert secret not in pub and "llm.internal.example" not in pub
    # 敏感模块：未授权模型被拒绝，私有模型允许
    assert admin.post("/api/llm/assign", json={"slot": "m5.notes", "model_id": ds["id"]}).status_code == 403
    assert admin.post("/api/llm/assign", json={"slot": "m5.notes", "model_id": priv["id"]}).status_code == 200
    assert admin.post("/api/llm/assign", json={"slot": "m3.writer", "model_id": ds["id"]}).status_code == 200
    assert admin.post("/api/llm/run", json={"slot": "m5.notes", "model_id": ds["id"], "prompt": "x"}).status_code == 403
    r = admin.post("/api/llm/run", json={"slot": "m3.writer", "prompt": "你好"})
    assert r.status_code == 200 and r.json()["model"] == "deepseek-chat"
    # 机构用户不能看模型列表
    assert admin.get("/api/llm/models", headers={"X-Role": "institution"}).status_code == 403


def test_provider_key_validation_and_strip(admin):
    base = {"vendor": "deepseek", "name": "DS-key-check", "base_url": "https://api.deepseek.com/v1"}
    r = admin.post("/api/admin/llm/providers", json={**base, "api_key": "tvly-dev-abcdefghijklmnopqrstuvwxyz"})
    assert r.status_code == 400 and "Tavily" in r.json()["detail"]
    r = admin.post("/api/admin/llm/providers", json={**base, "api_key": "abcdefghijklmnop12345"})
    assert r.status_code == 400 and "sk-" in r.json()["detail"]
    r = admin.post("/api/admin/llm/providers", json={**base, "api_key": "sk-abc def"})
    assert r.status_code == 400
    r = admin.post("/api/admin/llm/providers", json={**base, "api_key": "  sk-abcdefghijklmnop1234\n"})
    assert r.status_code == 200
    p = [x for x in admin.get("/api/admin/llm/providers").json() if x["name"] == "DS-key-check"][0]
    assert p["api_key_masked"] == "sk-****1234"
    # 编辑时留空保留原 Key
    assert admin.put(f"/api/admin/llm/providers/{p['id']}", json={**base, "api_key": ""}).status_code == 200
    p2 = [x for x in admin.get("/api/admin/llm/providers").json() if x["id"] == p["id"]][0]
    assert p2["api_key_masked"] == "sk-****1234"
    admin.delete(f"/api/admin/llm/providers/{p['id']}")



def test_cli_reset(admin):
    pw = admin_auth.reset_password("admin")
    assert (DATA_DIR / "admin_initial_password.txt").exists()
    assert admin.get("/api/admin/llm/providers").status_code == 403  # 旧会话失效
    r = admin.post("/api/admin/login", json={"username": "admin", "password": pw})
    assert r.json()["must_change"] is True
