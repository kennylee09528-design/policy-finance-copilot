"""执行记录的归档 / 删除（软删除 + 回收站 + 管理员彻底清除），跨模块统一实现。

- 归档：默认列表不显示；列表切到「已归档」可查看、可恢复。数据本身不变，下游引用照常可用。
- 删除：软删除（deleted_at），默认列表与「已归档」均不显示，详情接口返回 404；留痕记录。
  管理员可在「回收站」恢复或彻底清除（物理删除记录及其附属数据，如 PPT 文件）。
- 权限：仅记录创建人（owner）或系统管理员可操作；合作机构用户不可操作。
- 引用保护：删除被定稿/已发布/当前生效成果引用的记录时，先返回 409 + 引用清单，前端二次确认后带 force=true 才执行；
  少数情况直接禁止（当前生效的授信方案、运行中的任务）。
"""
import json
import shutil

from fastapi import HTTPException

from . import db

# kind -> (表, 模块, 显示名, owner 列, 标题表达式)
KINDS = {
    "m1_run": ("m1_runs", "M1", "采集记录", "created_by", "'采集 #' || id || ' · ' || COALESCE(trigger,'') || ' · ' || COALESCE(started_at,'')"),
    "m2_brief": ("m2_briefs", "M2", "简报", "generated_by", "brief_date || ' v' || version"),
    "m3_task": ("m3_tasks", "M3", "写作任务", "created_by", "title"),
    "m4_scheme": ("m4_schemes", "M4", "授信方案版本", "created_by", "'v' || version || ' ' || COALESCE(name,'')"),
    "m4_dataset": ("m4_datasets", "M4", "导入数据集", "imported_by", "COALESCE(name, source_file)"),
    "m5_snapshot": ("m5_snapshots", "M5", "看板快照", "created_by", "stat_date || ' ' || COALESCE(label,'')"),
    "m5_limit_set": ("m5_limit_sets", "M5", "额度表", "created_by", "name"),
    "ppt_job": ("ppt_jobs", "PPT", "PPT 任务", "created_by", "COALESCE(title, deck_type)"),
    "mail": ("mail_log", "邮件", "邮件发送记录", "user", "COALESCE(subject,'')"),
    "export": ("export_log", "导出", "导出记录", "user", "COALESCE(filename, action)"),
}
COLS = ("archived_at TEXT", "archived_by TEXT", "deleted_at TEXT", "deleted_by TEXT")


def migrations():
    out = [f"ALTER TABLE {t} ADD COLUMN {c}" for t, *_ in KINDS.values() for c in COLS]
    return out + ["ALTER TABLE m1_runs ADD COLUMN created_by TEXT"]


def _kind(kind):
    if kind not in KINDS:
        raise HTTPException(404, "未知记录类型")
    return KINDS[kind]


def live_sql(alias=""):
    """未删除记录的 SQL 条件（供「最新快照」「当前方案」等自动选取逻辑使用）。"""
    return f"{alias + '.' if alias else ''}deleted_at IS NULL"


def can_manage(user, owner):
    if user["role"] == "admin":
        return True
    return user["role"] == "internal" and bool(owner) and owner in (user.get("name"), user.get("username"))


def filter_rows(kind, rows, view, user):
    """按视图过滤列表：''=默认（未归档未删除）、archived=已归档、deleted=回收站（仅管理员）、all。
    并为每行补充 archived_at / deleted_at / can_manage，供前端显示操作按钮。"""
    table, _m, _n, owner_col, _t = _kind(kind)
    if view == "deleted" and user["role"] != "admin":
        raise HTTPException(403, "回收站仅系统管理员可见")
    if not rows:
        return rows
    ids = [r["id"] for r in rows]
    st = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for x in db.q(f"SELECT id, archived_at, archived_by, deleted_at, deleted_by, {owner_col} AS _owner FROM {table} WHERE id IN ({','.join('?' * len(part))})", part):
            st[x["id"]] = x
    out = []
    for r in rows:
        s = st.get(r["id"]) or {}
        arch, dele = s.get("archived_at"), s.get("deleted_at")
        keep = {"": not arch and not dele, "archived": bool(arch) and not dele, "deleted": bool(dele), "all": not dele}.get(view or "", not arch and not dele)
        if keep:
            r.update(archived_at=arch, archived_by=s.get("archived_by"), deleted_at=dele, deleted_by=s.get("deleted_by"),
                     can_manage=user["role"] != "institution" and can_manage(user, s.get("_owner")))
            out.append(r)
    return out


def ensure_live(kind, rid, user=None):
    """详情接口调用：已删除记录对非管理员返回 404。"""
    table = _kind(kind)[0]
    x = db.q1(f"SELECT deleted_at FROM {table} WHERE id=?", (rid,))
    if x and x["deleted_at"] and not (user and user["role"] == "admin"):
        raise HTTPException(404, "记录已删除")


# ---------------- 引用检查 ----------------
def _ppt_refs(key, rid):
    out = []
    for j in db.q("SELECT id, title, status, scope FROM ppt_jobs WHERE deleted_at IS NULL"):
        sc = db.jload(j["scope"], {}) or {}
        if str(sc.get(key) or "") == str(rid):
            out.append(f"PPT 任务 #{j['id']}「{j['title'] or ''}」（{j['status']}）基于该记录生成")
    return out


def refs(kind, rid):
    """返回 (blockers, warnings)。blockers 不可删除；warnings 需用户二次确认。"""
    b, w = [], []
    if kind == "m4_scheme":
        s = db.q1("SELECT * FROM m4_schemes WHERE id=?", (rid,))
        if s:
            if s["is_current"]:
                b.append("这是当前生效的授信方案版本，请先将其他版本设为当前")
            if s["status"] in ("已上会", "已批复"):
                w.append(f"方案状态为「{s['status']}」（已定稿成果）")
            for c in db.q("SELECT version FROM m4_schemes WHERE parent_id=? AND deleted_at IS NULL", (rid,)):
                w.append(f"版本 v{c['version']} 由该版本复制而来")
            for x in db.q("SELECT id, name FROM m5_limit_sets WHERE deleted_at IS NULL AND source=?", (f"M4方案#{rid}",)):
                w.append(f"M5 额度表 #{x['id']}「{x['name']}」来源于该方案")
            w += _ppt_refs("scheme_id", rid)
    elif kind == "m4_dataset":
        for s in db.q("SELECT version, status, is_current FROM m4_schemes WHERE dataset_id=? AND deleted_at IS NULL", (rid,)):
            (b if s["is_current"] else w).append(f"授信方案 v{s['version']}（{s['status']}{'，当前生效' if s['is_current'] else ''}）基于该数据集计算")
    elif kind == "m5_limit_set":
        for s in db.q("SELECT id, stat_date FROM m5_snapshots WHERE limit_set_id=? AND deleted_at IS NULL", (rid,)):
            w.append(f"看板快照 #{s['id']}（{s['stat_date']}）使用该额度表")
    elif kind == "m5_snapshot":
        latest = db.q1("SELECT id FROM m5_snapshots WHERE deleted_at IS NULL ORDER BY stat_date DESC, id DESC LIMIT 1")
        if latest and latest["id"] == rid:
            w.append("这是最新一期看板快照（机构用户与首页默认显示）")
        w += _ppt_refs("snapshot_id", rid)
    elif kind == "m2_brief":
        x = db.q1("SELECT status FROM m2_briefs WHERE id=?", (rid,))
        if x and x["status"] == "已发布":
            w.append("该简报已发布（合作机构用户可见）")
    elif kind == "m3_task":
        x = db.q1("SELECT status, finalized_at FROM m3_tasks WHERE id=?", (rid,))
        if x:
            if x["status"] in ("运行中",):
                b.append("任务正在运行，请等待结束后再删除")
            if x["finalized_at"]:
                w.append("该写作任务已定稿")
            n = db.q1("SELECT COUNT(*) n FROM m3_style_guide WHERE source_task_id=?", (rid,))["n"]
            if n:
                w.append(f"写作规范库中有 {n} 条规范总结自该任务（删除后规范保留）")
            n = db.q1("SELECT COUNT(*) n FROM m3_citations WHERE task_id=?", (rid,))["n"]
            if n:
                w.append(f"引用来源登记表中有 {n} 条登记关联该任务（删除后登记保留）")
            w += _ppt_refs("task_id", rid)
    elif kind == "ppt_job":
        n = db.q1("SELECT COUNT(*) n FROM ppt_files WHERE job_id=?", (rid,))["n"]
        if n:
            w.append(f"已生成 {n} 个 PPT 版本，删除后不可下载（管理员可在回收站恢复）")
    elif kind == "m1_run":
        x = db.q1("SELECT status FROM m1_runs WHERE id=?", (rid,))
        if x and x["status"] == "运行中":
            b.append("采集正在运行")
    return b, w


# ---------------- 操作 ----------------
def _rows(kind, ids):
    table, _m, _n, owner_col, title = _kind(kind)
    ids = [int(i) for i in ids or []][:500]
    if not ids:
        raise HTTPException(400, "请选择记录")
    rows = db.q(f"SELECT id, {owner_col} AS _owner, {title} AS _title, archived_at, deleted_at FROM {table} WHERE id IN ({','.join('?' * len(ids))})", ids)
    if len(rows) != len(set(ids)):
        raise HTTPException(404, "部分记录不存在")
    return rows


def _check_perm(user, rows):
    if user["role"] == "institution":
        raise HTTPException(403, "合作机构用户无权操作")
    bad = [r for r in rows if not can_manage(user, r["_owner"])]
    if bad:
        raise HTTPException(403, "仅创建人或系统管理员可操作：" + "、".join(f"#{r['id']}（创建人 {r['_owner'] or '系统'}）" for r in bad[:5]))


def act(kind, action, ids, user, force=False):
    table, module, name, _o, _t = _kind(kind)
    rows = _rows(kind, ids)
    if action in ("restore", "purge") and user["role"] != "admin":
        raise HTTPException(403, "回收站操作仅系统管理员可执行")
    _check_perm(user, rows)
    now = db.now()
    ids = [r["id"] for r in rows]
    ph = ",".join("?" * len(ids))
    if action == "archive":
        db.execute(f"UPDATE {table} SET archived_at=?, archived_by=? WHERE id IN ({ph}) AND deleted_at IS NULL", (now, user["name"], *ids))
        label = "归档"
    elif action == "unarchive":
        db.execute(f"UPDATE {table} SET archived_at=NULL, archived_by=NULL WHERE id IN ({ph})", ids)
        label = "取消归档"
    elif action == "delete":
        blockers, warns = {}, {}
        for r in rows:
            b, w = refs(kind, r["id"])
            if b:
                blockers[r["id"]] = b
            if w:
                warns[r["id"]] = w
        if blockers:
            raise HTTPException(409, {"blocked": True, "msg": "以下记录不能删除", "items": [{"id": i, "title": next(r["_title"] for r in rows if r["id"] == i), "reasons": v} for i, v in blockers.items()]})
        if warns and not force:
            raise HTTPException(409, {"needs_confirm": True, "msg": "以下记录被已定稿/已发布/生效中的成果引用，确认仍要删除？", "items": [{"id": i, "title": next(r["_title"] for r in rows if r["id"] == i), "reasons": v} for i, v in warns.items()]})
        db.execute(f"UPDATE {table} SET deleted_at=?, deleted_by=? WHERE id IN ({ph}) AND deleted_at IS NULL", (now, user["name"], *ids))
        label = "删除（移入回收站）" + ("（已确认引用提示）" if warns else "")
    elif action == "restore":
        db.execute(f"UPDATE {table} SET deleted_at=NULL, deleted_by=NULL WHERE id IN ({ph})", ids)
        label = "从回收站恢复"
    elif action == "purge":
        live = [r["id"] for r in rows if not r["deleted_at"]]
        if live:
            raise HTTPException(400, f"只能彻底清除回收站中的记录（{live} 未删除）")
        for i in ids:
            _purge(kind, i)
        label = "彻底清除"
    else:
        raise HTTPException(400, "未知操作")
    db.audit(user, module, f"{name}{label}", ",".join(map(str, ids)), {"kind": kind, "titles": [r["_title"] for r in rows][:20]})
    return {"ok": True, "count": len(ids)}


def _purge(kind, rid):
    table = KINDS[kind][0]
    if kind == "ppt_job":
        from .ppt.agent import PPT_DIR
        shutil.rmtree(PPT_DIR / f"job{rid}", ignore_errors=True)
        db.execute("DELETE FROM ppt_files WHERE job_id=?", (rid,))
    elif kind == "m3_task":
        db.execute("DELETE FROM m3_events WHERE task_id=?", (rid,))
    elif kind == "m4_scheme":
        db.execute("DELETE FROM m4_adjustments WHERE scheme_id=?", (rid,))
    elif kind == "m5_snapshot":
        db.execute("DELETE FROM m5_ledgers WHERE snapshot_id=?", (rid,))
    db.execute(f"DELETE FROM {table} WHERE id=?", (rid,))


def recycle_bin(user):
    if user["role"] != "admin":
        raise HTTPException(403, "回收站仅系统管理员可见")
    out = []
    for kind, (table, module, name, owner_col, title) in KINDS.items():
        for x in db.q(f"SELECT id, {title} AS title, {owner_col} AS owner, deleted_at, deleted_by FROM {table} WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC LIMIT 300"):
            out.append(x | {"kind": kind, "module": module, "kind_name": name})
    return sorted(out, key=lambda x: x["deleted_at"], reverse=True)


# ---------------- 导出记录 ----------------
def log_export(user, module, action, target, detail=None):
    """db.audit 遇到「导出」类动作时调用，形成可归档/删除的导出历史。"""
    fn = None
    if isinstance(detail, dict):
        fn = detail.get("filename")
    db.execute("INSERT INTO export_log(ts,user,username,module,action,target,filename,detail) VALUES(?,?,?,?,?,?,?,?)",
               (db.now(), user.get("name"), user.get("username"), module, action, str(target), fn,
                json.dumps(detail, ensure_ascii=False) if detail and not isinstance(detail, str) else detail))
