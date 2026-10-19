"""SQLite 数据层（单文件、单进程）。"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from .config import DB_PATH

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS institutions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name TEXT UNIQUE NOT NULL,
  short_name TEXT, city TEXT,
  is_holding INTEGER DEFAULT 0,
  is_fixed_quota INTEGER DEFAULT 0,
  reg_capital REAL, reg_capital_adj REAL,
  status TEXT DEFAULT '正常',
  org_code TEXT,            -- 行级权限预留：机构用户的组织编码
  aliases TEXT DEFAULT '[]',-- 别名（用于名称匹配）
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, user TEXT, role TEXT, module TEXT, action TEXT, target TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS m4_datasets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, source_file TEXT, imported_at TEXT, imported_by TEXT,
  verified INTEGER DEFAULT 0,     -- 是否已与国担系统核备
  payload TEXT                    -- JSON：逐机构输入 + 常量 + 原表缓存值 + 校验
);
CREATE TABLE IF NOT EXISTS m4_params(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version INTEGER, label TEXT, weights TEXT, constants TEXT,
  created_by TEXT, created_at TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS m4_schemes(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version INTEGER, name TEXT, dataset_id INTEGER, param_id INTEGER,
  status TEXT DEFAULT '草稿',      -- 草稿 / 已上会 / 已批复
  parent_id INTEGER, is_current INTEGER DEFAULT 0,
  created_by TEXT, created_at TEXT, note TEXT,
  status_log TEXT DEFAULT '[]',
  inputs TEXT,                     -- 方案自带的逐机构民投完成率等输入（JSON）
  result TEXT                      -- 最近一次计算结果快照（JSON）
);
CREATE TABLE IF NOT EXISTS m4_adjustments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scheme_id INTEGER, institution TEXT,
  kind TEXT,                       -- third：第三次调整；mintou：民投完成率调整（人工覆盖）
  value REAL, reason TEXT NOT NULL,
  operator TEXT, role TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS m5_limit_sets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, source TEXT, created_at TEXT, created_by TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS m5_snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stat_date TEXT, label TEXT, limit_set_id INTEGER,
  created_at TEXT, created_by TEXT,
  notes TEXT DEFAULT '{}',         -- 环比说明（人工编辑后的文本），按业务类型
  manual_direct TEXT DEFAULT '{}'  -- 台账缺直保行时的手工直保金额（万元）
);
CREATE TABLE IF NOT EXISTS m5_ledgers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id INTEGER, port TEXT, file_name TEXT,
  period_start TEXT, period_end TEXT, updated_on TEXT,
  total REAL, direct REAL, direct_source TEXT,
  rows TEXT, warnings TEXT, uploaded_at TEXT, uploaded_by TEXT,
  UNIQUE(snapshot_id, port)
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS llm_providers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor TEXT, name TEXT, base_url TEXT, api_key_enc TEXT,
  enabled INTEGER DEFAULT 1, is_private INTEGER DEFAULT 0,
  extra TEXT DEFAULT '{}', created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS llm_models(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id INTEGER, model_id TEXT, display_name TEXT,
  params TEXT DEFAULT '{}', enabled INTEGER DEFAULT 1,
  allow_sensitive INTEGER DEFAULT 0,
  last_test TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS search_providers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor TEXT, name TEXT, endpoint TEXT, api_key_enc TEXT,
  enabled INTEGER DEFAULT 1, is_default INTEGER DEFAULT 0,
  params TEXT DEFAULT '{}', last_test TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS m1_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT UNIQUE, title TEXT, publisher TEXT, level TEXT, layer TEXT, region TEXT, topic TEXT,
  pub_date TEXT, snippet TEXT, content TEXT, summary TEXT, query TEXT, provider TEXT,
  fetch_status TEXT, duplicate_of INTEGER, level_manual INTEGER DEFAULT 0,
  run_id INTEGER, collected_at TEXT, fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS m1_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT, finished_at TEXT, trigger TEXT, status TEXT, stats TEXT, log TEXT
);
CREATE TABLE IF NOT EXISTS m3_citations(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_name TEXT, title TEXT, source_name TEXT, level TEXT, location TEXT, excerpt TEXT,
  url TEXT, pub_date TEXT, verify_status TEXT DEFAULT '存疑（待核实）', query TEXT, provider TEXT,
  created_by TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS m2_briefs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brief_date TEXT, version INTEGER, status TEXT DEFAULT '草稿',
  items TEXT, markdown TEXT, stats TEXT, config TEXT, model TEXT,
  generated_at TEXT, generated_by TEXT, edited_at TEXT, edited_by TEXT, published_at TEXT, published_by TEXT
);
CREATE TABLE IF NOT EXISTS m3_prompts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent TEXT, version INTEGER, content TEXT, note TEXT, active INTEGER DEFAULT 0,
  created_by TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS m3_tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT, requirements TEXT, status TEXT, stage TEXT,
  sources TEXT, facts TEXT, outline TEXT, draft TEXT, check_result TEXT,
  final TEXT, final_check TEXT, confirmations TEXT DEFAULT '{}', summary_result TEXT,
  tokens TEXT DEFAULT '{}', agents TEXT, error TEXT,
  created_by TEXT, created_at TEXT, updated_at TEXT, finalized_at TEXT
);
CREATE TABLE IF NOT EXISTS m3_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER, ts TEXT, agent TEXT, stage TEXT, message TEXT, segment INTEGER,
  elapsed_ms INTEGER, tokens INTEGER, snippet TEXT
);
CREATE TABLE IF NOT EXISTS m3_style_guide(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT, content TEXT, source_task_id INTEGER, enabled INTEGER DEFAULT 1,
  created_by TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS ppt_jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deck_type TEXT, title TEXT, scope TEXT, model_id INTEGER, template_id INTEGER, status TEXT, step INTEGER DEFAULT 1,
  pack TEXT, questions TEXT, sheet TEXT, sheet_confirmed_at TEXT, outline TEXT, outline_confirmed_at TEXT,
  messages TEXT DEFAULT '[]', warnings TEXT DEFAULT '[]', tokens INTEGER DEFAULT 0, prompt_version INTEGER,
  created_by TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS ppt_files(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER, version INTEGER, filename TEXT, path TEXT, pages INTEGER, thumbs TEXT, trace TEXT,
  outline TEXT, sheet TEXT, template_id INTEGER, created_by TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS ppt_prompts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deck_type TEXT, version INTEGER, content TEXT, note TEXT, active INTEGER DEFAULT 0, created_by TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS ppt_templates(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, filename TEXT, path TEXT, layouts TEXT, active INTEGER DEFAULT 0, uploaded_by TEXT, uploaded_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS m1_fts USING fts5(title, summary, content, publisher, content='m1_items', content_rowid='id', tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS m1_fts_ai AFTER INSERT ON m1_items BEGIN
  INSERT INTO m1_fts(rowid,title,summary,content,publisher) VALUES (new.id,new.title,new.summary,new.content,new.publisher);
END;
CREATE TRIGGER IF NOT EXISTS m1_fts_ad AFTER DELETE ON m1_items BEGIN
  INSERT INTO m1_fts(m1_fts,rowid,title,summary,content,publisher) VALUES('delete',old.id,old.title,old.summary,old.content,old.publisher);
END;
CREATE TRIGGER IF NOT EXISTS m1_fts_au AFTER UPDATE ON m1_items BEGIN
  INSERT INTO m1_fts(m1_fts,rowid,title,summary,content,publisher) VALUES('delete',old.id,old.title,old.summary,old.content,old.publisher);
  INSERT INTO m1_fts(rowid,title,summary,content,publisher) VALUES (new.id,new.title,new.summary,new.content,new.publisher);
END;
CREATE TABLE IF NOT EXISTS admin_users(
  username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL,
  must_change INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, slot TEXT, module TEXT, model_db_id INTEGER, model TEXT, provider TEXT, params TEXT, prompt_version TEXT, ref TEXT,
  input TEXT, output TEXT, raw_output TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
  ms INTEGER, ok INTEGER, error TEXT, user TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON llm_calls(ts);
CREATE INDEX IF NOT EXISTS idx_llm_calls_ref ON llm_calls(ref);
CREATE TABLE IF NOT EXISTS m1_embeddings(
  item_id INTEGER, model_db_id INTEGER, vec TEXT, created_at TEXT, PRIMARY KEY(item_id, model_db_id)
);
CREATE TABLE IF NOT EXISTS m1_dedup_checks(
  item_id INTEGER PRIMARY KEY, original_id INTEGER, verdict TEXT, checked_by TEXT, checked_at TEXT
);
CREATE TABLE IF NOT EXISTS export_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, user TEXT, username TEXT, module TEXT, action TEXT, target TEXT, filename TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS users(
  username TEXT PRIMARY KEY, display_name TEXT, role TEXT NOT NULL, org TEXT, pw_hash TEXT NOT NULL,
  must_change INTEGER DEFAULT 1, enabled INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT, last_login TEXT, created_by TEXT
);
CREATE TABLE IF NOT EXISTS user_sessions(
  token_hash TEXT PRIMARY KEY, username TEXT, created_at TEXT, expires_at TEXT, ip TEXT
);
CREATE TABLE IF NOT EXISTS mail_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, user TEXT, username TEXT, role TEXT, channel TEXT,        -- channel: 网页 / 飞书
  kind TEXT, ref_id INTEGER, ref_title TEXT, doc_version TEXT,       -- kind: m3_report / m2_brief / ppt_file
  to_addrs TEXT, subject TEXT, message TEXT, attachments TEXT,       -- attachments: [{name,size}]
  status TEXT, error TEXT, sensitive_confirmed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS feishu_bindings(
  open_id TEXT PRIMARY KEY, username TEXT NOT NULL, bound_at TEXT, bound_by TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS feishu_bind_codes(
  code_hash TEXT PRIMARY KEY, username TEXT, created_at TEXT, expires_at TEXT, used_at TEXT
);
CREATE TABLE IF NOT EXISTS feishu_state(
  open_id TEXT PRIMARY KEY, state TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS feishu_seen(
  key TEXT PRIMARY KEY, ts TEXT
);
CREATE TABLE IF NOT EXISTS feishu_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, event_id TEXT, message_id TEXT, open_id TEXT, chat_id TEXT, chat_type TEXT, username TEXT,
  text TEXT, intent TEXT, status TEXT, reply TEXT, error TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS wechat_bindings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  ilink_user_id TEXT UNIQUE NOT NULL,
  ilink_bot_id TEXT,
  bot_token_enc TEXT NOT NULL,
  baseurl TEXT,
  cursor TEXT DEFAULT '',
  context_token TEXT,
  context_at TEXT,
  status TEXT DEFAULT '正常',          -- 正常 / 需重新扫码 / 停用
  last_error TEXT,
  bound_at TEXT, last_seen TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS wechat_qr_sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL,             -- 正在绑定的工作台账号（或 admin 自测用的目标账号）
  purpose TEXT DEFAULT 'user',        -- user / admin_test
  qrcode TEXT, qr_url TEXT,
  status TEXT DEFAULT 'wait',
  message TEXT,
  verify_needed INTEGER DEFAULT 0,
  result_user_id TEXT, result_bot_id TEXT,
  created_at TEXT, updated_at TEXT, expires_at TEXT
);
CREATE TABLE IF NOT EXISTS wechat_pending(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  binding_id INTEGER, username TEXT, ilink_user_id TEXT,
  kind TEXT,                          -- text / file
  text TEXT, file_name TEXT, file_path TEXT, file_size INTEGER,
  created_at TEXT, delivered_at TEXT, expires_at TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS wechat_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, message_id TEXT, ilink_user_id TEXT, username TEXT,
  text TEXT, intent TEXT, status TEXT, reply TEXT, error TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS wechat_seen(
  key TEXT PRIMARY KEY, ts TEXT
);
CREATE TABLE IF NOT EXISTS admin_sessions(
  token_hash TEXT PRIMARY KEY, username TEXT, created_at TEXT, expires_at TEXT, ip TEXT
);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_conn = None


MIGRATIONS = [  # 旧库增量加列（已存在则忽略）
    "ALTER TABLE m1_items ADD COLUMN manual_corrected INTEGER DEFAULT 0",
    "ALTER TABLE m1_items ADD COLUMN key_numbers TEXT",
    "ALTER TABLE m3_citations ADD COLUMN task_id INTEGER",
    "ALTER TABLE audit_log ADD COLUMN username TEXT",
    "ALTER TABLE m1_items ADD COLUMN reviewed_at TEXT",
    "ALTER TABLE m1_items ADD COLUMN reviewed_by TEXT",
    "ALTER TABLE institutions ADD COLUMN all_access INTEGER DEFAULT 0",  # 1=全机构可见的业务机构（如再担保本部），不参与 M4/M5 合作机构测算
]

ALL_ACCESS_ORGS = [("示例省级融资再担保有限责任公司", "示例再担保公司")]


def _migrate(c):
    from .records import migrations as rec_migrations  # 各模块执行记录的归档/删除列
    for sql in MIGRATIONS + rec_migrations():
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass
    for full, short in ALL_ACCESS_ORGS:
        c.execute("INSERT OR IGNORE INTO institutions(full_name,short_name,status,org_code,all_access,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",
                  (full, short, "正常", full, now(), now()))
        c.execute("UPDATE institutions SET all_access=1 WHERE full_name=?", (full,))
    if c.execute("SELECT value FROM settings WHERE key='m1_fts_built'").fetchone() is None:
        c.execute("INSERT INTO m1_fts(m1_fts) VALUES('rebuild')")
        c.execute("INSERT INTO settings(key,value) VALUES('m1_fts_built','1')")


def conn():
    global _conn
    if _conn is None:
        _conn = _connect()
        _conn.executescript(SCHEMA)
        _migrate(_conn)
        _conn.commit()
    return _conn


@contextmanager
def tx():
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def execute(sql, args=()):
    with tx() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def jload(s, default=None):
    if s is None or s == "":
        return default
    return json.loads(s)


def jdump(o):
    return json.dumps(o, ensure_ascii=False)


def audit(user, module, action, target="", detail=""):
    execute(
        "INSERT INTO audit_log(ts,user,username,role,module,action,target,detail) VALUES(?,?,?,?,?,?,?,?)",
        (now(), user.get("name"), user.get("username"), user.get("role"), module, action, str(target),
         detail if isinstance(detail, str) else jdump(detail)),
    )
    if action.startswith("导出") or action.startswith("下载"):
        from .records import log_export
        log_export(user, module, action, target, detail)


def get_setting(key, default=None):
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return jload(r["value"], default) if r else default


def set_setting(key, value):
    execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, jdump(value)))


def reset_connection():
    """测试用：切换数据库后重建连接。"""
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None
