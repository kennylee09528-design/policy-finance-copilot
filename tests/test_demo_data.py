"""演示数据包：管理员加载 / 清除（只删除自己写入的记录），上线就绪检查与 Token Plan 警示。"""
import httpx

from app import admin_auth, db


def test_demo_load_clear(client):
    admin_auth.reset_password("admin", "Init-pass-demo")
    client.post("/api/admin/login", json={"username": "admin", "password": "Init-pass-demo"})
    client.post("/api/admin/password", json={"old": "Init-pass-demo", "new": "Demo-Admin-2026!x"})
    c2 = httpx.Client(transport=client._transport, base_url=str(client.base_url))
    assert c2.post("/api/admin/demo/load").status_code == 403
    real = db.execute("INSERT INTO m1_items(url,title,level,collected_at) VALUES('https://real.example/1','真实条目','A1',?)", (db.now(),))
    r = client.get("/api/admin/demo").json()
    assert not r["demo"]["loaded"] and any(c["key"] == "model" for c in r["checks"])
    r = client.post("/api/admin/demo/load")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["loaded"] and d["counts"]["m1_items"] >= 25 and d["counts"]["m2_briefs"] == 7 and d["counts"]["ppt_jobs"] == 4, d
    assert client.post("/api/admin/demo/load").status_code == 409
    briefs = db.q("SELECT status FROM m2_briefs WHERE id IN (%s)" % ",".join(map(str, db.get_setting("demo_data")["m2_briefs"])))
    assert sum(b["status"] == "已发布" for b in briefs) == 6
    t = db.q1("SELECT * FROM m3_tasks WHERE id=?", (db.get_setting("demo_data")["m3_tasks"][0],))
    assert t["status"] == "已定稿" and db.q1("SELECT COUNT(*) n FROM m3_citations WHERE task_id=?", (t["id"],))["n"] >= 2
    files = db.q("SELECT trace FROM ppt_files WHERE job_id IN (%s)" % ",".join(map(str, db.get_setting("demo_data")["ppt_jobs"])))
    assert len(files) == 4 and all(db.jload(f["trace"])["ok"] for f in files)
    assert client.post("/api/admin/demo/clear").status_code == 200
    assert db.q1("SELECT COUNT(*) n FROM m1_items WHERE topic='演示数据'")["n"] == 0
    assert db.q1("SELECT id FROM m1_items WHERE id=?", (real,))      # 真实数据保留
    assert not client.get("/api/admin/demo").json()["demo"]["loaded"]
    db.execute("DELETE FROM m1_items WHERE id=?", (real,))


def test_token_plan_warning(client):
    from app.demo import readiness
    from app.llm import service as L
    u = {"name": "t", "role": "admin"}
    pid = L.save_provider({"vendor": "minimax_token_plan", "base_url": "https://api.minimax.cn/anthropic", "api_key": "sk-cp-xxxxxxxx"}, u)
    L.save_model({"provider_id": pid, "model_id": "MiniMax-M3"}, u)
    assert any("Token Plan" in w for w in readiness()["warnings"])
    L.delete_provider(pid, u)
