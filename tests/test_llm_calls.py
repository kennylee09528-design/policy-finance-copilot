"""大模型调用快照：成功/失败都记录完整输入、原始输出、参数、tokens、耗时、关联任务；管理员可查看。"""
import httpx
import pytest
from fastapi import HTTPException

from app import admin_auth, db
from app.llm import service as L


def fake_ok(url, json=None, headers=None, timeout=None):
    return httpx.Response(200, json={"choices": [{"message": {"content": "<think>想一想</think>答案：30%", "reasoning_content": "推理过程"}}],
                                     "model": json["model"], "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}})


def fake_bad(url, json=None, headers=None, timeout=None):
    return httpx.Response(400, json={"error": {"message": "bad request"}})


@pytest.fixture(scope="module")
def mid(client):
    admin_auth.reset_password("admin", "Init-pass-calls")
    client.post("/api/admin/login", json={"username": "admin", "password": "Init-pass-calls"})
    client.post("/api/admin/password", json={"old": "Init-pass-calls", "new": "Calls-Admin-2026!x"})
    u = {"name": "测试", "role": "admin"}
    p = L.save_provider({"vendor": "deepseek", "base_url": "https://calls.example/v1", "api_key": "sk-calls-xxxxxxxx"}, u)
    return L.save_model({"provider_id": p, "model_id": "calls-model", "params": {"temperature": 0.3}}, u)


def test_snapshot_success_and_failure(client, mid, monkeypatch):
    u = {"name": "张三", "role": "internal"}
    monkeypatch.setattr("app.llm.client.httpx.post", fake_ok)
    msgs = [{"role": "system", "content": "你是助手"}, {"role": "user", "content": "补偿比例是多少？" * 3}]
    r = L.run("m3.writer", msgs, u, mid=mid, overrides={"top_p": 0.9}, ref="m3_task:99", prompt_version="writer v3")
    assert r["content"] == "答案：30%"
    c = db.q1("SELECT * FROM llm_calls WHERE ref='m3_task:99' ORDER BY id DESC")
    assert c["ok"] == 1 and c["model"] == "calls-model" and c["prompt_version"] == "writer v3" and c["user"] == "张三"
    assert c["prompt_tokens"] == 11 and c["completion_tokens"] == 7 and c["total_tokens"] == 18 and c["ms"] is not None
    assert db.jload(c["input"]) == msgs and db.jload(c["params"])["top_p"] == 0.9 and db.jload(c["params"])["temperature"] == 0.3
    assert c["output"] == "答案：30%" and "推理过程" in c["raw_output"] and "<think>" in c["raw_output"]
    monkeypatch.setattr("app.llm.client.httpx.post", fake_bad)
    with pytest.raises(HTTPException):
        L.run("m3.writer", msgs, u, mid=mid, ref="m3_task:99")
    f = db.q1("SELECT * FROM llm_calls WHERE ref='m3_task:99' AND ok=0")
    assert f and "400" in f["error"]
    # 管理员查看
    d = client.get("/api/admin/llm/calls?ref=m3_task:99").json()
    assert len(d["calls"]) == 2 and "input" not in d["calls"][0] and d["stats"]["n"] >= 2
    one = client.get(f"/api/admin/llm/calls/{c['id']}").json()
    assert one["input"][1]["content"].startswith("补偿比例") and one["params"]["top_p"] == 0.9
    assert client.get("/api/admin/llm/calls?ok=0").json()["calls"][0]["ok"] == 0
    assert httpx.Client(transport=client._transport, base_url=str(client.base_url)).get("/api/admin/llm/calls").status_code == 403
