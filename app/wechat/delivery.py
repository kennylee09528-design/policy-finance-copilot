"""发送回复：≤10 条文本（可 Markdown）+ 文件；额度用尽或 context_token 失效时写入 pending，下次入站补发。"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from .. import db
from ..config import DATA_DIR
from . import config as C
from .ilink import MEDIA_FILE, IlinkClient, Uploaded

PENDING_DIR = DATA_DIR / C.PENDING_DIR_NAME


def split_text(text: str, chunk: int) -> list[str]:
    text = (text or "").rstrip()
    if not text:
        return []
    if len(text) <= chunk:
        return [text]
    parts, buf = [], []
    n = 0
    for line in text.split("\n"):
        add = len(line) + (1 if buf else 0)
        if n + add > chunk and buf:
            parts.append("\n".join(buf))
            buf, n = [line], len(line)
        else:
            buf.append(line)
            n += add
    if buf:
        parts.append("\n".join(buf))
    # hard split any oversized chunk
    out = []
    for p in parts:
        while len(p) > chunk:
            out.append(p[:chunk])
            p = p[chunk:]
        if p:
            out.append(p)
    return out


def merge_into_budget(texts: list[str], files_n: int, max_replies: int, chunk: int) -> list[str]:
    """把多段文字合并到「最多 max_replies - files_n」条消息里。"""
    budget = max(0, max_replies - files_n)
    if budget == 0:
        return []
    flat = []
    for t in texts:
        flat.extend(split_text(t, chunk))
    if not flat:
        return []
    if len(flat) <= budget:
        return flat
    # 合并多余段到前 budget 条
    out = flat[: budget - 1]
    rest = "\n\n".join(flat[budget - 1 :])
    # 末条仍可能超长 → 再切，但丢掉放不下的并加提示
    tail = split_text(rest, chunk)
    if len(out) + len(tail) <= budget:
        out.extend(tail)
    else:
        keep = budget - len(out) - 1
        out.extend(tail[: max(keep, 0)])
        out.append((tail[keep] if keep < len(tail) else "")[: chunk - 40] + "\n…（内容过长已截断；完整版请到网页查看或发邮箱）")
    return out[:budget]


class Sender:
    def __init__(self, client: IlinkClient, binding: dict, context_token: str | None):
        self.client = client
        self.binding = binding
        self.token = context_token
        self.cfg = C.get()
        self.sent = 0
        self.max = int(self.cfg["max_replies"])
        self.chunk = int(self.cfg["text_chunk"])
        self.to = binding["ilink_user_id"]
        self.expired = False
        self.errors = []

    def _room(self):
        return max(0, self.max - self.sent)

    def send_text(self, text: str) -> bool:
        if self.expired or not text:
            return False
        if self._room() <= 0:
            enqueue_text(self.binding, text, note="reply_quota_exhausted")
            return False
        r = self.client.send_text(self.to, text, self.token)
        if r.stale:
            self.expired = True
            self.errors.append("session timeout (-14)")
            enqueue_text(self.binding, text, note="context_expired")
            return False
        if not r.delivered:
            self.errors.append(f"send failed ret={r.ret} errmsg={r.errmsg}")
            # ret=-2 prepare failed ≈ 额度用尽或 token 无效
            if r.ret == -2:
                enqueue_text(self.binding, text, note="prepare_failed")
                self.expired = True
            return False
        self.sent += 1
        return True

    def send_file_bytes(self, name: str, data: bytes) -> bool:
        if self.expired:
            enqueue_file(self.binding, name, data, note="context_expired")
            return False
        if self._room() <= 0:
            enqueue_file(self.binding, name, data, note="reply_quota_exhausted")
            return False
        max_b = int(self.cfg["max_file_mb"]) * 1024 * 1024
        if len(data) > max_b:
            self.send_text(f"文件 {name}（{len(data)/1048576:.1f} MB）超过微信通道上限 {self.cfg['max_file_mb']} MB，请到网页下载或发邮箱。")
            return False
        up = self.client.upload_media(data, MEDIA_FILE, self.to)
        if not up.ok:
            self.errors.append(up.error or "upload failed")
            enqueue_file(self.binding, name, data, note="upload_failed")
            self.send_text(f"文件 {name} 上传失败，已加入待发队列；您下次发任意消息时我会补发，或请到网页下载。")
            return False
        r = self.client.send_file(self.to, up, name, self.token)
        if r.stale or r.ret == -2:
            self.expired = True
            enqueue_file(self.binding, name, data, note="send_failed")
            return False
        if not r.delivered:
            self.errors.append(f"file send failed ret={r.ret}")
            enqueue_file(self.binding, name, data, note="send_failed")
            return False
        self.sent += 1
        return True

    def deliver(self, reply: str, files: list) -> dict:
        """files: list of (name, bytes, mime). Returns stats."""
        files = list(files or [])
        can_files = min(len(files), self._room())
        # 先为文件留名额，再把文字压进剩余条数
        msgs = merge_into_budget([reply] if reply else [], can_files, self._room(), self.chunk)
        text_budget = max(0, self._room() - can_files)
        for m in msgs[:text_budget]:
            self.send_text(m)
        for name, data, _mime in files[:can_files]:
            self.send_file_bytes(name, data)
        for m in msgs[text_budget:]:
            enqueue_text(self.binding, m, note="deferred_text")
        for name, data, _mime in files[can_files:]:
            enqueue_file(self.binding, name, data, note="deferred_file")
        return {"sent": self.sent, "expired": self.expired, "errors": self.errors}


def enqueue_text(binding, text, note=""):
    if not text:
        return
    cfg = C.get()
    exp = (datetime.now() + timedelta(hours=int(cfg["pending_ttl_hours"]))).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO wechat_pending(binding_id,username,ilink_user_id,kind,text,created_at,expires_at,note) VALUES(?,?,?,?,?,?,?,?)",
               (binding["id"], binding["username"], binding["ilink_user_id"], "text", text[:8000], db.now(), exp, note))


def enqueue_file(binding, name, data: bytes, note=""):
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)[:80] or "file.bin"
    path = PENDING_DIR / f"b{binding['id']}_{int(datetime.now().timestamp())}_{safe}"
    path.write_bytes(data)
    cfg = C.get()
    exp = (datetime.now() + timedelta(hours=int(cfg["pending_ttl_hours"]))).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO wechat_pending(binding_id,username,ilink_user_id,kind,file_name,file_path,file_size,created_at,expires_at,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (binding["id"], binding["username"], binding["ilink_user_id"], "file", name, str(path), len(data), db.now(), exp, note))


def flush_pending(client: IlinkClient, binding: dict, context_token: str) -> int:
    """用户新消息到来时补发队列；返回发出条数。"""
    rows = db.q("SELECT * FROM wechat_pending WHERE binding_id=? AND delivered_at IS NULL AND expires_at>=? ORDER BY id LIMIT 20",
                (binding["id"], db.now()))
    if not rows:
        return 0
    sender = Sender(client, binding, context_token)
    # 先告知
    n = len(rows)
    sender.send_text(f"您有 {n} 条之前未能及时送达的内容，正在补发…")
    for r in rows:
        if sender.expired or sender._room() <= 0:
            break
        if r["kind"] == "text":
            ok = sender.send_text(r["text"])
        else:
            try:
                data = Path(r["file_path"]).read_bytes() if r.get("file_path") and os.path.exists(r["file_path"]) else None
            except OSError:
                data = None
            if not data:
                db.execute("UPDATE wechat_pending SET delivered_at=?, note=? WHERE id=?", (db.now(), "file_missing", r["id"]))
                continue
            ok = sender.send_file_bytes(r["file_name"] or "file.bin", data)
        if ok:
            db.execute("UPDATE wechat_pending SET delivered_at=? WHERE id=?", (db.now(), r["id"]))
            if r.get("file_path") and os.path.exists(r["file_path"]):
                try:
                    os.unlink(r["file_path"])
                except OSError:
                    pass
    # 清理过期
    for old in db.q("SELECT id, file_path FROM wechat_pending WHERE delivered_at IS NULL AND expires_at<?", (db.now(),)):
        if old.get("file_path") and os.path.exists(old["file_path"]):
            try:
                os.unlink(old["file_path"])
            except OSError:
                pass
        db.execute("DELETE FROM wechat_pending WHERE id=?", (old["id"],))
    left = db.q1("SELECT COUNT(*) n FROM wechat_pending WHERE binding_id=? AND delivered_at IS NULL", (binding["id"],))["n"]
    if left and not sender.expired and sender._room() > 0:
        sender.send_text(f"还有 {left} 条待发（受每条提问最多 {sender.max} 条回复限制）。请再发「继续」让我接着发；或到网页下载 / 发邮箱。")
    return sender.sent
