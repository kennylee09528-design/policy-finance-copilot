"""每日备份：一致性快照 + 完整性校验、轮换（天/周）、恢复。"""
import os
import sqlite3
import tarfile
from datetime import datetime, timedelta

from app import admin_auth, backup, db


def test_backup_rotate_restore(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PH_BACKUP_DIR", str(tmp_path / "bk"))
    admin_auth.reset_password("admin", "Init-pass-bk")
    client.post("/api/admin/login", json={"username": "admin", "password": "Init-pass-bk"})
    client.post("/api/admin/password", json={"old": "Init-pass-bk", "new": "Bk-Admin-2026!x"})
    db.set_setting("bk_marker", "v1")
    r = client.post("/api/admin/backups")
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["integrity"] == "ok"
    p = tmp_path / "bk" / info["name"]
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"
    names = tarfile.open(p).getnames()
    assert "workbench.db" in names and "BACKUP_INFO.txt" in names
    # 轮换：造 40 天每天 2 份
    base = datetime(2026, 8, 1, 2, 30)
    for i in range(40):
        for h in (0, 5):
            (tmp_path / "bk" / (base + timedelta(days=i, hours=h)).strftime("workbench_%Y%m%d_%H%M%S.tar.gz")).write_bytes(b"x")
    db.set_setting("backup_config", {"keep_daily": 5, "keep_weekly": 3})
    removed = backup.rotate()
    left = backup.listing()["files"]
    days = {f["name"][10:18] for f in left}
    assert removed and len(left) <= 5 + 3 and info["name"] in {f["name"] for f in left}
    assert len(days) >= 5
    # 恢复到另一个库文件
    tgt = tmp_path / "restore" / "workbench.db"
    tgt.parent.mkdir()
    sqlite3.connect(tgt).execute("CREATE TABLE x(a)").connection.commit()
    res = backup.restore(p, tgt)
    assert res["integrity"] == "ok"
    v = sqlite3.connect(tgt).execute("SELECT value FROM settings WHERE key='bk_marker'").fetchone()[0]
    assert v == '"v1"' and list(tgt.parent.glob("pre_restore_*.db"))
    assert client.get("/api/admin/backups").json()["last"]["name"] == info["name"]
    db.set_setting("backup_config", {})
