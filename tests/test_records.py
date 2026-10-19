"""跨模块执行记录：归档 / 恢复 / 软删除 / 引用确认 / 回收站 / 彻底清除 / 权限 / 导出历史。（header 身份模式）"""
from urllib.parse import quote

from app import db

A = {"X-User": quote("张三"), "X-Role": "internal"}
B = {"X-User": quote("李四"), "X-Role": "internal"}
ADM = {"X-User": quote("管理员"), "X-Role": "admin"}
INST = {"X-User": quote("机构"), "X-Role": "institution"}


def _ids(c, path, h=A, view=""):
    r = c.get(path + ("?view=" + view if view else ""), headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    rows = d["runs"] if isinstance(d, dict) else d
    return [x["id"] for x in rows]


def _task(owner, status="已完成", finalized=None):
    return db.execute("INSERT INTO m3_tasks(title,status,created_by,created_at,finalized_at) VALUES(?,?,?,?,?)",
                      (f"{owner}的任务", status, owner, db.now(), finalized))


def test_archive_restore_and_owner_permission(client):
    t = _task("张三")
    assert t in _ids(client, "/api/m3/tasks")
    # 他人不能操作；机构用户不能操作
    r = client.post("/api/records/m3_task/archive", json={"ids": [t]}, headers=B)
    assert r.status_code == 403 and "创建人" in r.json()["detail"]
    assert client.post("/api/records/m3_task/archive", json={"ids": [t]}, headers=INST).status_code == 403
    assert client.post("/api/records/m3_task/archive", json={"ids": [t]}, headers=A).status_code == 200
    assert t not in _ids(client, "/api/m3/tasks")
    assert t in _ids(client, "/api/m3/tasks", view="archived")
    assert client.get(f"/api/m3/tasks/{t}", headers=A).status_code == 200  # 归档不影响查看
    assert client.post("/api/records/m3_task/unarchive", json={"ids": [t]}, headers=ADM).status_code == 200  # 管理员可操作他人记录
    assert t in _ids(client, "/api/m3/tasks")
    a = db.q("SELECT action, user FROM audit_log WHERE module='M3' AND target=? ORDER BY id", (str(t),))
    assert [x["action"] for x in a][-2:] == ["写作任务归档", "写作任务取消归档"]


def test_delete_confirm_bin_restore_purge(client):
    t = _task("张三", "已定稿", db.now())
    r = client.post("/api/records/m3_task/delete", json={"ids": [t]}, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["needs_confirm"]
    assert "已定稿" in r.json()["detail"]["items"][0]["reasons"][0]
    assert client.post("/api/records/m3_task/delete", json={"ids": [t], "force": True}, headers=A).status_code == 200
    assert t not in _ids(client, "/api/m3/tasks") and t not in _ids(client, "/api/m3/tasks", view="archived")
    assert client.get(f"/api/m3/tasks/{t}", headers=A).status_code == 404
    assert client.get("/api/records/bin", headers=A).status_code == 403
    assert client.get("/api/m3/tasks?view=deleted", headers=A).status_code == 403
    assert any(x["kind"] == "m3_task" and x["id"] == t for x in client.get("/api/records/bin", headers=ADM).json())
    assert client.post("/api/records/m3_task/restore", json={"ids": [t]}, headers=A).status_code == 403
    assert client.post("/api/records/m3_task/restore", json={"ids": [t]}, headers=ADM).status_code == 200
    assert t in _ids(client, "/api/m3/tasks")
    assert client.post("/api/records/m3_task/purge", json={"ids": [t]}, headers=ADM).status_code == 400  # 未删除不能清除
    client.post("/api/records/m3_task/delete", json={"ids": [t], "force": True}, headers=ADM)
    db.execute("INSERT INTO m3_events(task_id,ts,message) VALUES(?,?,?)", (t, db.now(), "x"))
    assert client.post("/api/records/m3_task/purge", json={"ids": [t]}, headers=ADM).status_code == 200
    assert not db.q1("SELECT 1 x FROM m3_tasks WHERE id=?", (t,)) and not db.q1("SELECT 1 x FROM m3_events WHERE task_id=?", (t,))


def test_batch_and_running_blocked(client):
    ids = [_task("张三") for _ in range(3)]
    assert client.post("/api/records/m3_task/archive", json={"ids": ids}, headers=A).json()["count"] == 3
    assert set(ids) <= set(_ids(client, "/api/m3/tasks", view="archived"))
    run = _task("张三", "运行中")
    r = client.post("/api/records/m3_task/delete", json={"ids": [run], "force": True}, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["blocked"]


def test_m4_current_scheme_blocked_and_dataset_warning(client):
    if not db.q1("SELECT 1 x FROM m4_schemes WHERE is_current=1"):
        assert client.post("/api/m4/import-sample", headers=ADM).status_code == 200
    cur = db.q1("SELECT id, dataset_id FROM m4_schemes WHERE is_current=1")
    r = client.post("/api/records/m4_scheme/delete", json={"ids": [cur["id"]], "force": True}, headers=ADM)
    assert r.status_code == 409 and r.json()["detail"]["blocked"]
    r = client.post("/api/records/m4_dataset/delete", json={"ids": [cur["dataset_id"]], "force": True}, headers=ADM)
    assert r.status_code == 409 and "当前生效" in str(r.json()["detail"])
    # 归档当前方案允许（数据仍可用），列表默认隐藏
    assert client.post("/api/records/m4_scheme/archive", json={"ids": [cur["id"]]}, headers=ADM).status_code == 200
    assert cur["id"] not in _ids(client, "/api/m4/schemes", ADM)
    assert client.get("/api/m4/schemes/current", headers=ADM).json()["id"] == cur["id"]
    client.post("/api/records/m4_scheme/unarchive", json={"ids": [cur["id"]]}, headers=ADM)


def test_m5_snapshot_delete_hides_latest(client):
    if not db.q1("SELECT 1 x FROM m5_limit_sets"):
        client.post("/api/m5/limit-sets/import-sample", headers=ADM)
    s1 = client.post("/api/m5/snapshots/sample", json={}, headers=ADM).json()
    sid = s1.get("id") or s1.get("snapshot_id") or db.q1("SELECT MAX(id) m FROM m5_snapshots")["m"]
    r = client.post("/api/records/m5_snapshot/delete", json={"ids": [sid]}, headers=ADM)
    if r.status_code == 409:
        assert r.json()["detail"]["needs_confirm"]
        r = client.post("/api/records/m5_snapshot/delete", json={"ids": [sid], "force": True}, headers=ADM)
    assert r.status_code == 200
    assert client.get("/api/m5/snapshots/latest/id", headers=INST).json()["id"] != sid
    assert client.get(f"/api/m5/snapshots/{sid}/dashboard", headers=INST).status_code == 404
    client.post("/api/records/m5_snapshot/restore", json={"ids": [sid]}, headers=ADM)


def test_ppt_and_m2_m1_lists(client):
    j = db.execute("INSERT INTO ppt_jobs(deck_type,title,status,created_by,created_at,scope) VALUES('usage','t','已生成','张三',?,'{}')", (db.now(),))
    db.execute("INSERT INTO ppt_files(job_id,version,filename,path) VALUES(?,1,'a.pptx','/nonexistent')", (j,))
    r = client.post("/api/records/ppt_job/delete", json={"ids": [j]}, headers=A)
    assert r.status_code == 409 and "PPT 版本" in str(r.json()["detail"])
    b = db.execute("INSERT INTO m2_briefs(brief_date,version,status,generated_by,generated_at) VALUES('2025-01-01',1,'已发布','张三',?)", (db.now(),))
    assert client.post("/api/records/m2_brief/archive", json={"ids": [b]}, headers=A).status_code == 200
    assert b not in _ids(client, "/api/m2/briefs", INST) and b in _ids(client, "/api/m2/briefs", view="archived")
    assert b not in _ids(client, "/api/m2/briefs", INST, view="archived")  # 机构用户不能切归档视图
    run = db.execute("INSERT INTO m1_runs(started_at,trigger,status,stats,created_by) VALUES(?,?,?,?,?)", (db.now(), "手动", "完成", "{}", "张三"))
    assert client.post("/api/records/m1_run/delete", json={"ids": [run]}, headers=A).status_code == 200
    assert run not in _ids(client, "/api/m1/runs")
    assert client.post("/api/records/nope/delete", json={"ids": [1]}, headers=A).status_code == 404


def test_export_history(client):
    db.execute("INSERT INTO m2_briefs(brief_date,version,status,markdown,generated_by,generated_at) VALUES('2025-02-02',1,'已发布','# x','张三',?)", (db.now(),))
    bid = db.q1("SELECT id FROM m2_briefs WHERE brief_date='2025-02-02'")["id"]
    assert client.get(f"/api/m2/briefs/{bid}/export.md", headers=A).status_code == 200
    ex = client.get("/api/exports", headers=A).json()
    e = ex[0]
    assert e["action"] == "导出 Markdown" and e["filename"].endswith(".md") and e["can_manage"]
    assert client.post("/api/records/export/archive", json={"ids": [e["id"]]}, headers=B).status_code == 403
    assert client.post("/api/records/export/delete", json={"ids": [e["id"]]}, headers=A).status_code == 200
    assert e["id"] not in [x["id"] for x in client.get("/api/exports", headers=A).json()]
