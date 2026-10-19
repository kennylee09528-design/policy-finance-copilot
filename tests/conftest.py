import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="ph_test_")
os.environ["PH_DATA_DIR"] = _tmp
os.environ["PH_DISABLE_SCHEDULER"] = "1"
os.environ["PH_RETRY_BASE"] = "0"
os.environ.setdefault("PH_AUTH_MODE", "header")  # 业务接口测试用请求头身份；登录/角色在 test_users.py 用 session 模式验证
os.environ["PH_DB_PATH"] = str(Path(_tmp) / "test.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.main import app
    return TestClient(app)


ISOLATE_TABLES = ["m1_items", "m2_briefs", "m3_tasks", "m3_citations", "m5_snapshots", "m5_ledgers", "m5_limit_sets", "ppt_jobs", "ppt_files", "institutions", "users",
                  "user_sessions", "mail_log", "export_log", "feishu_bindings", "feishu_bind_codes", "feishu_state", "feishu_seen", "feishu_events", "wechat_bindings", "wechat_qr_sessions", "wechat_pending", "wechat_events", "wechat_seen"]
ISOLATE_SETTINGS = ["feishu_config", "smtp_config", "feishu_ws_status", "llm_assign", "wechat_config"]


@pytest.fixture(scope="module")
def isolated_db():
    """本模块新增的业务数据在模块结束后清掉，避免影响其他测试对「空库」的假设。"""
    from app import db
    mx = {t: (db.q1(f"SELECT COALESCE(MAX(rowid),0) m FROM {t}") or {"m": 0})["m"] for t in ISOLATE_TABLES}
    st = {k: db.q1("SELECT value FROM settings WHERE key=?", (k,)) for k in ISOLATE_SETTINGS}
    yield
    for t, m in mx.items():
        db.execute(f"DELETE FROM {t} WHERE rowid>?", (m,))
    for k, v in st.items():
        if v is None:
            db.execute("DELETE FROM settings WHERE key=?", (k,))
        else:
            db.execute("UPDATE settings SET value=? WHERE key=?", (v["value"], k))
