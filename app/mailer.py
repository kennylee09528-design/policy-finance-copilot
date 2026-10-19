"""研究报告 / 简报 / PPT 发送到邮箱（SMTP）。

安全约束（内部资料）：
- 收件人域名必须在管理员配置的白名单内；白名单为空 = 一律拒绝（须管理员先设置）。
- 仅已定稿且无标红未决项的研究报告可发送；使用了 M5 敏感数据的稿件须二次确认。
- 邮件正文与附件均带「内部资料 注意保密」与发送人信息；附件为带水印的 Word / PPT。
- 每人每小时限发 N 封；发送人、收件人、附件与版本、结果全部记入「邮件发送记录」与操作留痕。
"""
import re
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from fastapi import HTTPException

from . import db
from . import records as REC
from . import watermark as W
from .llm.crypto import decrypt, encrypt

CFG_KEY = "smtp_config"
DEFAULT = {"enabled": False, "host": "", "port": 465, "security": "ssl", "username": "", "password_enc": "",
           "sender_name": "普惠业务工作台", "sender_addr": "", "allowed_domains": [], "max_recipients": 10,
           "hourly_limit": 10, "max_attach_mb": 15, "last_test": None}
ADDR = re.compile(r"^[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+\.)+[A-Za-z]{2,}$")
DOMAIN = re.compile(r"^(\*\.)?([a-z0-9\-]+\.)+[a-z]{2,}$")
FOOTER = "内部资料 注意保密：本邮件及附件仅限收件人内部使用，请勿转发、截图外传或向无关人员披露。"
KINDS = {"m3_report": "M3 研究报告", "m2_brief": "M2 今日行业 Brief", "ppt_file": "PPT 演示稿"}


# ---------------- 配置 ----------------
def get():
    c = {**DEFAULT, **(db.get_setting(CFG_KEY, {}) or {})}
    return c


def public():
    c = get()
    out = {k: v for k, v in c.items() if k != "password_enc"}
    out["has_password"] = bool(c["password_enc"])
    out["configured"] = bool(c["host"] and c["sender_addr"])
    return out


def _norm_domains(xs):
    out = []
    for x in (xs if isinstance(xs, list) else re.split(r"[\s,;，；]+", str(xs or ""))):
        d = str(x).strip().lower().lstrip("@")
        if not d:
            continue
        if not DOMAIN.match(d):
            raise HTTPException(400, f"域名格式不正确：{x}（示例：example.com，或 *.example.com 表示含子域）")
        if d not in out:
            out.append(d)
    return out


def save(body, admin):
    c = get()
    host = (body.get("host") or "").strip()
    sec = body.get("security") or "ssl"
    if sec not in ("ssl", "starttls", "none"):
        raise HTTPException(400, "加密方式须为 ssl / starttls / none")
    try:
        port = int(body.get("port") or 0)
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "端口须为数字") from e
    if host and not re.match(r"^[A-Za-z0-9.\-]+$", host):
        raise HTTPException(400, "SMTP 主机格式不正确")
    if host and not 1 <= port <= 65535:
        raise HTTPException(400, "端口范围 1~65535")
    sa = (body.get("sender_addr") or "").strip()
    if sa and not ADDR.match(sa):
        raise HTTPException(400, "发件人地址格式不正确")
    c.update(host=host, port=port or c["port"], security=sec, username=(body.get("username") or "").strip(),
             sender_name=(body.get("sender_name") or "普惠业务工作台").strip()[:40], sender_addr=sa,
             allowed_domains=_norm_domains(body.get("allowed_domains", c["allowed_domains"])),
             enabled=bool(body.get("enabled", c["enabled"])))
    for k, lo, hi in (("max_recipients", 1, 50), ("hourly_limit", 1, 200), ("max_attach_mb", 1, 25)):
        if body.get(k) not in (None, ""):
            c[k] = max(lo, min(hi, int(body[k])))
    pw = body.get("password")
    if pw:  # 留空 = 不修改；Key 永不回显
        c["password_enc"] = encrypt(pw.strip())
    if body.get("clear_password"):
        c["password_enc"] = ""
    db.set_setting(CFG_KEY, c)
    db.audit(admin, "系统", "保存邮件(SMTP)配置", c["host"], {"port": c["port"], "security": sec, "domains": c["allowed_domains"], "enabled": c["enabled"],
                                                   "password_changed": bool(pw)})
    return public()


# ---------------- SMTP 发送 ----------------
def _open(c):
    ctx = ssl.create_default_context()
    if c["security"] == "ssl":
        s = smtplib.SMTP_SSL(c["host"], int(c["port"]), timeout=25, context=ctx)
    else:
        s = smtplib.SMTP(c["host"], int(c["port"]), timeout=25)
        s.ehlo()
        if c["security"] == "starttls":
            s.starttls(context=ctx)
            s.ehlo()
    if c["username"]:
        s.login(c["username"], decrypt(c["password_enc"]) if c["password_enc"] else "")
    return s


def _build(c, to, subject, text, html, attachments, cc=None):
    m = EmailMessage()
    m["From"] = formataddr((c["sender_name"], c["sender_addr"]))
    m["To"] = ", ".join(to)
    if cc:
        m["Cc"] = ", ".join(cc)
    m["Subject"] = subject
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=c["sender_addr"].split("@")[-1] or "localhost")
    m["X-Confidential"] = "内部资料 注意保密"
    m.set_content(text)
    m.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        mt, st = (mime or "application/octet-stream").split("/", 1)
        m.add_attachment(data, maintype=mt, subtype=st, filename=name)
    return m


def deliver(c, to, subject, text, html, attachments=None):
    if not (c["host"] and c["sender_addr"]):
        raise HTTPException(400, "邮件(SMTP)尚未配置：请管理员在「系统管理 → 邮件发送」中填写")
    msg = _build(c, to, subject, text, html, attachments)
    try:
        s = _open(c)
        try:
            s.send_message(msg)
        finally:
            try:
                s.quit()
            except Exception:  # noqa: BLE001
                pass
    except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
        raise HTTPException(502, "邮件发送失败：" + _clean_err(e, c)) from e
    return msg["Message-ID"]


def _clean_err(e, c):
    s = f"{type(e).__name__}: {e}"
    pw = decrypt(c["password_enc"]) if c.get("password_enc") else ""
    if pw:
        s = s.replace(pw, "****")
    return s[:300]


def test_send(to, admin):
    c = get()
    addr = (to or "").strip()
    if not ADDR.match(addr):
        raise HTTPException(400, "请输入有效的测试收件邮箱")
    txt = f"这是一封来自普惠业务工作台的 SMTP 测试邮件。\n发送人：{admin['name']}  时间：{db.now()}\n\n{FOOTER}\n"
    res = {"at": db.now(), "to": addr}
    try:
        deliver(c, [addr], "【测试】普惠业务工作台 邮件发送配置", txt, _html(txt))
        res["ok"] = True
    except HTTPException as e:
        res.update(ok=False, error=str(e.detail))
    c["last_test"] = res
    db.set_setting(CFG_KEY, c)
    db.audit(admin, "系统", "测试邮件发送", addr, {"ok": res["ok"]})
    return res


def _html(text):
    from html import escape
    body = "<br>".join(escape(x) for x in text.split("\n"))
    return (f'<div style="font-family:Microsoft YaHei,Arial,sans-serif;font-size:14px;color:#222;line-height:1.7">{body}</div>')


# ---------------- 收件人 / 限流 ----------------
def parse_recipients(raw):
    items = raw if isinstance(raw, list) else re.split(r"[\s,;，；]+", str(raw or ""))
    out = []
    for x in items:
        x = str(x).strip()
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return out


def domain_ok(addr, allowed):
    d = addr.rsplit("@", 1)[-1].lower()
    for a in allowed:
        if a.startswith("*."):
            if d.endswith(a[1:]) and d != a[2:]:
                return True
        elif d == a:
            return True
    return False


def check_recipients(c, raw):
    to = parse_recipients(raw)
    if not to:
        raise HTTPException(400, "请填写收件人邮箱")
    if len(to) > c["max_recipients"]:
        raise HTTPException(400, f"单封邮件最多 {c['max_recipients']} 个收件人")
    bad = [a for a in to if not ADDR.match(a)]
    if bad:
        raise HTTPException(400, "邮箱格式不正确：" + "、".join(bad))
    if not c["allowed_domains"]:
        raise HTTPException(403, "管理员尚未设置允许发送的邮箱域名白名单，为防止内部资料外泄，暂不可发送（系统管理 → 邮件发送）")
    ext = [a for a in to if not domain_ok(a, c["allowed_domains"])]
    if ext:
        raise HTTPException(403, "以下收件人不在允许的邮箱域名内（内部资料不得外发）：" + "、".join(ext) + "；允许域名：" + "、".join(c["allowed_domains"]))
    return to


def uname(user):
    return user.get("username") or user.get("name")


def rate_check(user, c):
    since = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    n = db.q1("SELECT COUNT(*) n FROM mail_log WHERE username=? AND ts>? AND deleted_at IS NULL", (uname(user), since))["n"]
    n2 = db.q1("SELECT COUNT(*) n FROM mail_log WHERE username=? AND ts>?", (uname(user), since))["n"]
    if max(n, n2) >= c["hourly_limit"]:
        raise HTTPException(429, f"发送过于频繁：每人每小时最多 {c['hourly_limit']} 封，请稍后再试")


# ---------------- 待发文档 ----------------
def _task_ready(tid):
    from .m3 import pipeline as P
    t = db.q1("SELECT * FROM m3_tasks WHERE id=?", (tid,))
    if not t or t["deleted_at"]:
        raise HTTPException(404, "研究报告不存在")
    d = P.detail(tid)
    if d["status"] not in ("已定稿", "已总结"):
        raise HTTPException(409, f"仅已定稿的研究报告可发送（当前状态：{d['status']}）")
    red = (d.get("final_check") or {}).get("red", 0)
    if red:
        raise HTTPException(409, f"报告仍有 {red} 句标红未决项，不能发送")
    return d


def prepare(kind, ref, opts, user):
    """返回待发文档：标题、版本说明、附件(name, bytes, mime)、是否敏感、提示。"""
    opts = opts or {}
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    warns, atts = [], []
    if kind == "m3_report":
        d = _task_ready(int(ref))
        from .m3 import pipeline as P
        REC.ensure_live("m3_task", int(ref), user)
        atts.append((f"{d['title'][:40]}.docx", W.docx_bytes(P.to_docx(d["id"]), user), DOCX))
        sens = bool((d.get("requirements") or {}).get("use_m5"))
        ver = f"定稿时间 {d.get('finalized_at') or '—'}"
        if opts.get("ppt_file_id"):
            f = db.q1("SELECT f.*, j.scope, j.deleted_at jd FROM ppt_files f JOIN ppt_jobs j ON j.id=f.job_id WHERE f.id=?", (int(opts["ppt_file_id"]),))
            if not f or f["jd"] or str((db.jload(f["scope"], {}) or {}).get("task_id") or "") != str(d["id"]):
                raise HTTPException(400, "所选 PPT 不是由该研究报告生成的配套演示稿")
            atts.append(_ppt_att(f, user, PPTX))
            ver += f"；PPT v{f['version']}"
        title, sub = d["title"], f"【内部资料】{d['title']}"
        ppts = [{"id": f["id"], "label": f"{f['filename']}（v{f['version']}，{f['created_at']}）"} for f in db.q(
            "SELECT f.id, f.filename, f.version, f.created_at, j.scope FROM ppt_files f JOIN ppt_jobs j ON j.id=f.job_id WHERE j.deleted_at IS NULL ORDER BY f.id DESC LIMIT 200")
            if str((db.jload(f["scope"], {}) or {}).get("task_id") or "") == str(d["id"])]
    elif kind == "m2_brief":
        from .m2 import brief as B
        REC.ensure_live("m2_brief", int(ref), user)
        b = B.get(int(ref))
        if b["status"] != "已发布":
            raise HTTPException(409, "仅已发布的简报可发送")
        data, name = B.to_docx(b["id"])
        atts.append((name, W.docx_bytes(data, user), DOCX))
        sens = bool(b.get("data_rows"))
        ver = f"v{b['version']}，发布时间 {b.get('published_at') or '—'}"
        title, sub, ppts = f"{b['brief_date']} 今日行业 Brief", f"【内部资料】今日行业 Brief {b['brief_date']}", []
    elif kind == "ppt_file":
        f = db.q1("SELECT f.*, j.title jt, j.pack, j.deleted_at jd FROM ppt_files f JOIN ppt_jobs j ON j.id=f.job_id WHERE f.id=?", (int(ref),))
        if not f or f["jd"]:
            raise HTTPException(404, "PPT 文件不存在")
        atts.append(_ppt_att(f, user, PPTX))
        sens = bool((db.jload(f["pack"], {}) or {}).get("sensitive"))
        ver = f"PPT v{f['version']}，生成时间 {f['created_at']}"
        title, sub, ppts = f["jt"] or f["filename"], f"【内部资料】{f['jt'] or f['filename']}", []
        tr = db.jload(f["trace"], {}) or {}
        if tr and not tr.get("ok", True):
            warns.append("该 PPT 数字溯源检查存在疑点，请核对后再发送")
    else:
        raise HTTPException(400, "不支持的发送类型")
    if sens:
        warns.append("该文档使用了 M5 机构业务数据（敏感）：发送前须勾选「已确认可发送」")
    return {"kind": kind, "kind_name": KINDS[kind], "ref": int(ref), "title": title, "version": ver, "subject": sub, "attachments": atts,
            "sensitive": sens, "warnings": warns, "ppt_options": ppts}


def _ppt_att(f, user, mime):
    import os
    from pathlib import Path
    if not os.path.exists(f["path"]):
        raise HTTPException(404, "PPT 文件不存在")
    return (f["filename"], W.pptx_bytes(Path(f["path"]).read_bytes(), user), mime)


def preview(kind, ref, raw_to, opts, user):
    c = get()
    require_sender(user)
    doc = prepare(kind, ref, opts, user)
    to, err = [], None
    try:
        to = check_recipients(c, raw_to) if raw_to else []
    except HTTPException as e:
        err = e.detail
    size = sum(len(a[1]) for a in doc["attachments"])
    return {"ok": bool(c["host"] and c["sender_addr"] and c["enabled"]), "smtp_ready": bool(c["host"] and c["sender_addr"] and c["enabled"]),
            "allowed_domains": c["allowed_domains"], "recipients": to, "recipient_error": err, "title": doc["title"], "kind_name": doc["kind_name"],
            "version": doc["version"], "subject": doc["subject"], "sensitive": doc["sensitive"], "warnings": doc["warnings"],
            "attachments": [{"name": a[0], "size": len(a[1])} for a in doc["attachments"]], "size_mb": round(size / 1048576, 2),
            "ppt_options": doc["ppt_options"], "sender": f"{c['sender_name']} <{c['sender_addr']}>"}


def require_sender(user):
    if user.get("role") not in ("admin", "internal"):
        raise HTTPException(403, "仅普惠部内部用户和管理员可发送邮件（合作机构用户不可用）")


def send(kind, ref, raw_to, subject, message, opts, user, channel="网页", confirm=False, confirm_sensitive=False):
    require_sender(user)
    c = get()
    if not c["enabled"]:
        raise HTTPException(400, "邮件发送功能未启用（管理员在「系统管理 → 邮件发送」中配置并启用）")
    if not confirm:
        raise HTTPException(400, "请先确认收件人后再发送（confirm=true）")
    to = check_recipients(c, raw_to)
    rate_check(user, c)
    doc = prepare(kind, ref, opts, user)
    if doc["sensitive"] and not confirm_sensitive:
        raise HTTPException(409, "该文档使用了 M5 敏感数据，须勾选「已确认可发送」后才能发送")
    size = sum(len(a[1]) for a in doc["attachments"])
    if size > c["max_attach_mb"] * 1048576:
        raise HTTPException(413, f"附件合计 {size / 1048576:.1f} MB，超过上限 {c['max_attach_mb']} MB")
    subject = (subject or doc["subject"]).strip()[:150]
    message = (message or "").strip()[:2000]
    who = W.info(user)
    names = [a[0] for a in doc["attachments"]]
    text = (f"{message}\n\n" if message else "") + "——————————\n" + f"文档：{doc['kind_name']}《{doc['title']}》（{doc['version']}）\n附件：{'、'.join(names)}\n" \
           f"发送人：{who['who']}　发送时间：{who['at']}　渠道：{channel}\n来源：{W.SYSTEM}\n\n{FOOTER}\n"
    html = _html(text.replace("\n" + FOOTER, "")).replace("</div>", f'<p style="margin-top:12px;color:#b3202f;font-weight:bold">{FOOTER}</p></div>')
    status, err = "已发送", None
    try:
        deliver(c, to, subject, text, html, doc["attachments"])
    except HTTPException as e:
        status, err = "失败", str(e.detail)
    lid = db.execute("INSERT INTO mail_log(ts,user,username,role,channel,kind,ref_id,ref_title,doc_version,to_addrs,subject,message,attachments,status,error,sensitive_confirmed) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (db.now(), user["name"], uname(user), user.get("role"), channel, kind, int(ref), doc["title"], doc["version"], ", ".join(to), subject, message,
                      db.jdump([{"name": a[0], "size": len(a[1])} for a in doc["attachments"]]), status, err, 1 if (doc["sensitive"] and confirm_sensitive) else 0))
    for nm in names:  # 附件即导出：计入导出记录，便于追溯
        db.audit(user, {"m3_report": "M3", "m2_brief": "M2", "ppt_file": "PPT"}[kind], "导出邮件附件", f"{kind}#{ref}", {"filename": nm, "via": f"邮件·{channel}", "to": to})
    db.audit(user, "邮件", "发送邮件" if status == "已发送" else "发送邮件失败", f"{kind}#{ref}",
             {"mail_id": lid, "to": to, "subject": subject, "attachments": names, "version": doc["version"], "channel": channel, "status": status, "error": err,
              "sensitive_confirmed": bool(doc["sensitive"] and confirm_sensitive)})
    if status != "已发送":
        raise HTTPException(502, err or "发送失败")
    return {"ok": True, "mail_id": lid, "to": to, "subject": subject, "attachments": names, "version": doc["version"]}


def log_rows(view, user):
    rows = db.q("SELECT id, ts, user, username, channel, kind, ref_id, ref_title, doc_version, to_addrs, subject, attachments, status, error, sensitive_confirmed "
                "FROM mail_log ORDER BY id DESC LIMIT 2000")
    if user["role"] != "admin":  # 内部用户只看自己发出的
        rows = [r for r in rows if r["username"] == uname(user)]
    for r in rows:
        r["attachments"] = db.jload(r["attachments"], [])
        r["kind_name"] = KINDS.get(r["kind"], r["kind"])
    return REC.filter_rows("mail", rows, view, user)[:500]
