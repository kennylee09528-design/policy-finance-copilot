"""可靠性：429/5xx 退避重试、启动恢复中断任务、重新运行、调度状态。"""
import httpx

from app import admin_auth, db, ops
from app.llm import client as LC


def test_retry_then_ok(monkeypatch):
    seq = [httpx.Response(429, text="rate"), httpx.Response(503, text="busy"),
           httpx.Response(200, json={"choices": [{"message": {"content": "好"}}], "model": "m"})]
    calls = []

    def fake(url, json=None, headers=None, timeout=None):
        calls.append(1)
        return seq.pop(0)
    monkeypatch.setattr("app.llm.client.httpx.post", fake)
    r = LC.chat("https://x.example/v1", "k", "m", [{"role": "user", "content": "hi"}])
    assert r["content"] == "好" and len(calls) == 3
    assert any("429" in x["msg"] for x in ops._mem["retry"])


def test_no_retry_on_400_and_gives_up(monkeypatch):
    calls = []

    def fake400(url, json=None, headers=None, timeout=None):
        calls.append(1)
        return httpx.Response(400, text="bad")
    monkeypatch.setattr("app.llm.client.httpx.post", fake400)
    try:
        LC.chat("https://x.example/v1", "k", "m", [{"role": "user", "content": "hi"}])
    except LC.LLMError as e:
        assert "400" in str(e)
    assert len(calls) == 1
    calls.clear()

    def fake_to(url, json=None, headers=None, timeout=None):
        calls.append(1)
        raise httpx.ConnectTimeout("t")
    monkeypatch.setattr("app.llm.client.httpx.post", fake_to)
    try:
        LC.chat("https://x.example/v1", "k", "m", [{"role": "user", "content": "hi"}])
        raise AssertionError
    except LC.LLMError as e:
        assert "网络错误" in str(e)
    assert len(calls) == 3


def test_recover_and_rerun(client, monkeypatch):
    tid = db.execute("INSERT INTO m3_tasks(title,requirements,status,stage,tokens,confirmations,agents,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     ("中断测试", db.jdump({"text": "", "genre": "报告", "tone": "正式", "words": 300, "use_kb": False, "use_web": False, "use_m5": False}),
                      "写作中", "写作：第 1/3 节", "{}", "{}", "{}", "t", db.now(), db.now()))
    rid = db.execute("INSERT INTO m1_runs(started_at,trigger,status,stats,log) VALUES(?,?,?,?,?)", (db.now(), "手动", "运行中", "{}", ""))
    n3, n1 = ops.recover_on_startup()
    assert n3 >= 1 and n1 >= 1
    t = client.get(f"/api/m3/tasks/{tid}").json()
    assert t["status"] == "已中断" and "重新运行" in t["error"]
    assert db.q1("SELECT status FROM m1_runs WHERE id=?", (rid,))["status"] == "已中断"
    import app.m3.pipeline as P
    ran = []
    monkeypatch.setattr(P, "_run", lambda tid, user: ran.append(tid))
    assert client.post(f"/api/m3/tasks/{tid}/rerun").status_code == 200
    import time
    time.sleep(0.1)
    assert ran == [tid] and db.q1("SELECT status FROM m3_tasks WHERE id=?", (tid,))["status"] == "排队"
    assert client.post(f"/api/m3/tasks/{tid}/rerun").status_code == 409


def test_run_job_and_status(client):
    ops.run_job("m2_brief", lambda: 1)
    ops.run_job("m1_collect", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    admin_auth.reset_password("admin", "Init-pass-ops")
    client.post("/api/admin/login", json={"username": "admin", "password": "Init-pass-ops"})
    client.post("/api/admin/password", json={"old": "Init-pass-ops", "new": "Ops-Admin-2026!x"})
    s = client.get("/api/admin/ops").json()
    by = {x["key"]: x for x in s["schedulers"]}
    assert by["m2_brief"]["last_ok"] is True and by["m1_collect"]["last_ok"] is False and "boom" in by["m1_collect"]["last_error"]
    assert s["boot"]["at"]
