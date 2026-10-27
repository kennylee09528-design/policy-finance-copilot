"""M1 知识库增强：语义检索、来源健康、低置信度复核队列、被引用追踪、去重抽检。"""
import json
import math
import random
import re
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import HTTPException

from .. import db
from .validity import annotate, attach

LIVE = "duplicate_of IS NULL"


# ---------------- 语义检索 ----------------
def _text(it):
    return " ".join(x for x in (it.get("title"), it.get("summary"), it.get("snippet"), (it.get("content") or "")[:800]) if x)


def _grams(s):
    s = re.sub(r"[\s\W_]+", "", (s or "").lower())
    return Counter(s[i:i + 2] for i in range(len(s) - 1))


def _cos(a, b):
    if isinstance(a, Counter):
        num = sum(v * b.get(k, 0) for k, v in a.items())
        den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    else:
        num = sum(x * y for x, y in zip(a, b))
        den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


def _embed_model():
    from ..llm.service import assignments
    return assignments().get("m1.embed")


def _embed(mid, texts, kind="db"):
    from ..llm import client
    from ..llm.crypto import decrypt
    from ..llm.service import _resolve
    m = _resolve(mid)
    if "minimax" in (m["base_url"] or "").lower():
        return _embed_minimax(m["base_url"], decrypt(m["api_key_enc"]), m["model_id"], texts, kind), "embo-01"
    return client.embed(m["base_url"], decrypt(m["api_key_enc"]), m["model_id"], texts), m["model_id"]


def _embed_minimax(base_url, key, model, texts, kind="db"):
    """MiniMax 向量接口非 OpenAI 格式：{model: embo-01, texts, type: db|query} → {vectors}。槽位选了 MiniMax 对话模型时自动改用 embo-01。"""
    from .. import ops
    mdl = model if (model or "").startswith("embo") else "embo-01"
    r = ops.post_retry(base_url.rstrip("/") + "/embeddings", json={"model": mdl, "texts": texts, "type": kind},
                       headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=60, label=f"向量模型 {mdl}")
    j = r.json() if r.content else {}
    if r.status_code >= 400 or not j.get("vectors"):
        raise RuntimeError(f"MiniMax 向量接口返回异常：{str((j or {}).get('base_resp') or r.text)[:120]}")
    return j["vectors"]


def semantic_search(q, k=20, user=None):
    """有向量模型时用 Embedding 余弦相似度（条目向量缓存在 m1_embeddings，按需补齐）；
    未配置时退化为中文字符二元组 TF 余弦（离线可用，能匹配同义改写中的共有词）。"""
    q = (q or "").strip()
    if not q:
        raise HTTPException(400, "请输入检索内容")
    items = db.q(f"SELECT id,title,publisher,level,pub_date,url,summary,snippet,content,validity_status FROM m1_items WHERE {LIVE} ORDER BY id DESC LIMIT 3000")
    mid = _embed_model()
    method = "字符二元组相似度（未配置向量模型）"
    scores = {}
    if mid:
        try:
            have = {r["item_id"]: json.loads(r["vec"]) for r in db.q("SELECT item_id, vec FROM m1_embeddings WHERE model_db_id=?", (mid,))}
            missing = [it for it in items if it["id"] not in have][:256]
            for i in range(0, len(missing), 32):
                part = missing[i:i + 32]
                vecs, model = _embed(mid, [_text(x)[:2000] for x in part])
                for it, v in zip(part, vecs):
                    have[it["id"]] = v
                    db.execute("INSERT OR REPLACE INTO m1_embeddings(item_id, model_db_id, vec, created_at) VALUES(?,?,?,?)", (it["id"], mid, json.dumps(v), db.now()))
            qv, model = _embed(mid, [q], "query")
            scores = {it["id"]: _cos(qv[0], have[it["id"]]) for it in items if it["id"] in have}
            method = f"向量语义检索（{model}）"
        except Exception as e:  # noqa: BLE001 向量服务异常时退化，不影响使用
            method = f"字符二元组相似度（向量模型调用失败：{str(e)[:60]}）"
            scores = {}
    if not scores:
        qg = _grams(q)
        scores = {it["id"]: _cos(qg, _grams(_text(it))) for it in items}
    top = sorted(items, key=lambda x: scores.get(x["id"], 0), reverse=True)[:k]
    out = []
    for it in top:
        if scores.get(it["id"], 0) <= 0:
            continue
        row = annotate({k2: it[k2] for k2 in ("id", "title", "publisher", "level", "pub_date", "url", "validity_status")})
        row["score"] = round(scores.get(it["id"], 0), 4)
        row["excerpt"] = (it["summary"] or it["snippet"] or "")[:160]
        out.append(row)
    return {"method": method, "results": out}


def rag_answer(q, user, k=6):
    """基于知识库检索结果的问答（RAG）：只把前 k 条条目（标题/发布方/日期/要点或正文摘录）交给模型，要求逐句 [n] 标注出处；
    知识库未覆盖时如实说明。返回答案与编号来源（含条目 id 与原文链接），前端标「AI 生成，仅供参考」。"""
    from ..llm import service as L
    res = semantic_search(q, max(k, 20), user)
    top = [x for x in res["results"]][:k]
    if not top:
        return {"answer": "知识库中没有与该问题相关的条目，无法回答。", "sources": [], "method": res["method"], "covered": False}
    full = {r["id"]: r for r in db.q(f"SELECT id,title,publisher,pub_date,url,summary,snippet,content,validity_status FROM m1_items WHERE id IN ({','.join('?' * len(top))})", [x["id"] for x in top])}
    blocks = []
    for n, x in enumerate(top, 1):
        it = full.get(x["id"]) or {}
        st, nt = attach(it)
        body = (it.get("summary") or "") + "\n" + (it.get("content") or it.get("snippet") or "")
        eff = f"效力：{st}" + (f"。{nt}" if nt else "。")
        blocks.append(f"[{n}] 标题：{it.get('title')}\n发布方：{it.get('publisher')}｜日期：{it.get('pub_date') or '未标注'}\n{eff}\n内容摘录：{body.strip()[:1500]}")
    prompt = ("你是融资担保/再担保业务的政策研究助手。请只依据下面编号资料回答问题，不得使用资料以外的知识，不得编造文件名、文号、日期或数字。\n"
              "要求：1) 用中文简明作答（不超过 300 字，可分点）；2) 每个事实句末用 [编号] 标注出处，只能引用下列编号；"
              "3) 如果资料不足以回答，直接回答“知识库中暂无足够资料回答该问题”，并说明资料涉及了什么。\n\n"
              f"问题：{q}\n\n资料：\n" + "\n\n".join(blocks))
    r = L.run("m1.extract", [{"role": "user", "content": prompt}], user or {"name": "M1问答", "role": "internal"}, overrides={"temperature": 0.1}, timeout=120, ref="m1_rag")
    ans = re.sub(r"<think>.*?</think>", "", r["content"] or "", flags=re.S).strip()
    ans = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= len(top) else "", ans)  # 去掉越界编号
    used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", ans)})
    srcs = []
    for n, x in enumerate(top, 1):
        st, nt = attach(full.get(x["id"]) or x)
        srcs.append({"n": n, "id": x["id"], "title": x["title"], "url": x["url"], "publisher": x["publisher"], "level": x["level"],
                     "pub_date": x["pub_date"], "cited": n in used, "validity_status": st, "validity_notice": nt})
    notices = [{"n": s["n"], "id": s["id"], "title": s["title"], "validity_status": s["validity_status"], "notice": s["validity_notice"]}
               for s in srcs if s.get("validity_notice")]
    return {"answer": ans, "sources": srcs, "method": res["method"], "covered": bool(used), "model": r.get("model"),
            "validity_notices": notices}


# ---------------- 来源健康 ----------------
def source_health():
    rows = db.q(f"SELECT publisher, url, level, fetch_status, collected_at, pub_date FROM m1_items WHERE {LIVE}")
    by = {}
    week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        key = r["publisher"] or (urlparse(r["url"] or "").hostname or "未知")
        s = by.setdefault(key, {"publisher": key, "domain": urlparse(r["url"] or "").hostname, "items": 0, "week": 0, "fetch_fail": 0, "levels": Counter(),
                                "last_collected": "", "last_pub": ""})
        s["items"] += 1
        s["week"] += (r["collected_at"] or "") >= week
        s["fetch_fail"] += (r["fetch_status"] or "").startswith("抓取失败")
        s["levels"][r["level"] or "?"] += 1
        s["last_collected"] = max(s["last_collected"], r["collected_at"] or "")
        s["last_pub"] = max(s["last_pub"], r["pub_date"] or "")
    out = []
    stale = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    for s in by.values():
        s["fail_rate"] = round(s["fetch_fail"] / s["items"], 3) if s["items"] else 0
        s["levels"] = dict(s["levels"])
        flags = []
        if s["fail_rate"] >= 0.5 and s["items"] >= 2:
            flags.append("正文抓取失败率高")
        if s["last_pub"] and s["last_pub"] < stale:
            flags.append("30 天无新发布")
        if s["week"] == 0:
            flags.append("近 7 天未采集到")
        s["flags"] = flags
        s["status"] = "异常" if "正文抓取失败率高" in flags else ("关注" if flags else "正常")
        out.append(s)
    order = {"异常": 0, "关注": 1, "正常": 2}
    return sorted(out, key=lambda x: (order[x["status"]], -x["items"]))


# ---------------- 低置信度复核队列 ----------------
def _reasons(it):
    r = []
    if (it["fetch_status"] or "").startswith("抓取失败") or it["fetch_status"] == "待抓取":
        r.append("正文未抓取成功")
    if not it["pub_date"]:
        r.append("缺发布日期")
    if not it["publisher"]:
        r.append("缺发布方")
    if (it["level"] or "") in ("B2", "C1", "C2", "") and not it["level_manual"]:
        r.append(f"来源等级较低（{it['level'] or '未定级'}）")
    if not it["summary"]:
        r.append("无 AI 要点")
    if (it.get("provider") or "") == "manual":
        r.append("同事补录，待人工复核")
    return r


def review_queue(limit=200):
    rows = db.q(f"SELECT id,title,url,publisher,level,pub_date,fetch_status,summary,level_manual,collected_at,provider,uploaded_by FROM m1_items "
                f"WHERE {LIVE} AND reviewed_at IS NULL ORDER BY id DESC LIMIT 3000")
    out = []
    for it in rows:
        rs = _reasons(it)
        if rs:
            out.append({k: it[k] for k in ("id", "title", "url", "publisher", "level", "pub_date", "fetch_status", "collected_at", "uploaded_by")} | {"reasons": rs, "score": len(rs)})
    out.sort(key=lambda x: -x["score"])
    done = db.q1("SELECT COUNT(*) n FROM m1_items WHERE reviewed_at IS NOT NULL")["n"]
    return {"queue": out[:limit], "total": len(out), "reviewed": done}


def review(iid, body, user):
    it = db.q1("SELECT * FROM m1_items WHERE id=?", (iid,))
    if not it:
        raise HTTPException(404, "条目不存在")
    action = body.get("action")
    if action not in ("confirm", "duplicate", "level"):
        raise HTTPException(400, "操作无效")
    if action == "duplicate":
        dup = int(body.get("duplicate_of") or 0)
        if not dup or dup == iid or not db.q1("SELECT 1 x FROM m1_items WHERE id=?", (dup,)):
            raise HTTPException(400, "请填写正确的原条目编号")
        db.execute("UPDATE m1_items SET duplicate_of=? WHERE id=?", (dup, iid))
    if action == "level":
        lv = body.get("level")
        if lv not in ("A1", "A2", "B1", "B2", "C1", "C2"):
            raise HTTPException(400, "等级无效")
        db.execute("UPDATE m1_items SET level=?, level_manual=1 WHERE id=?", (lv, iid))
    db.execute("UPDATE m1_items SET reviewed_at=?, reviewed_by=? WHERE id=?", (db.now(), user["name"], iid))
    db.audit(user, "M1", "复核条目", iid, {"action": action, "note": body.get("note") or "", "level": body.get("level"), "duplicate_of": body.get("duplicate_of")})
    return {"ok": True}


# ---------------- 被引用 ----------------
def citations_of(iid):
    it = db.q1("SELECT url FROM m1_items WHERE id=?", (iid,))
    if not it:
        raise HTTPException(404, "条目不存在")
    rows = db.q("SELECT c.id, c.doc_name, c.task_id, c.location, c.verify_status, c.created_at, t.title task_title, t.status task_status "
                "FROM m3_citations c LEFT JOIN m3_tasks t ON t.id=c.task_id WHERE c.url=? ORDER BY c.id DESC", (it["url"],))
    return rows


def cited_counts(ids):
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    return {r["id"]: r["n"] for r in db.q(f"SELECT i.id, COUNT(c.id) n FROM m1_items i JOIN m3_citations c ON c.url=i.url WHERE i.id IN ({ph}) GROUP BY i.id", ids)}


# ---------------- 去重抽检 ----------------
def dedup_sample(n=10):
    dups = db.q("SELECT d.id, d.title, d.url, d.publisher, d.pub_date, d.duplicate_of, o.title o_title, o.url o_url, o.publisher o_publisher, o.pub_date o_pub_date "
                "FROM m1_items d JOIN m1_items o ON o.id=d.duplicate_of WHERE d.id NOT IN (SELECT item_id FROM m1_dedup_checks)")
    sample = random.sample(dups, min(n, len(dups)))
    st = db.q1("SELECT COUNT(*) n, SUM(CASE WHEN verdict='correct' THEN 1 ELSE 0 END) ok FROM m1_dedup_checks")
    total_dup = db.q1("SELECT COUNT(*) n FROM m1_items WHERE duplicate_of IS NOT NULL")["n"]
    return {"sample": sample, "checked": st["n"], "correct": st["ok"] or 0, "accuracy": round((st["ok"] or 0) / st["n"], 4) if st["n"] else None,
            "total_duplicates": total_dup, "unchecked": len(dups)}


def dedup_judge(iid, verdict, user):
    if verdict not in ("correct", "wrong"):
        raise HTTPException(400, "判定无效")
    it = db.q1("SELECT duplicate_of FROM m1_items WHERE id=?", (iid,))
    if not it or not it["duplicate_of"]:
        raise HTTPException(400, "该条目不是去重记录")
    db.execute("INSERT OR REPLACE INTO m1_dedup_checks(item_id, original_id, verdict, checked_by, checked_at) VALUES(?,?,?,?,?)",
               (iid, it["duplicate_of"], verdict, user["name"], db.now()))
    if verdict == "wrong":  # 误判：恢复为独立条目
        db.execute("UPDATE m1_items SET duplicate_of=NULL WHERE id=?", (iid,))
    db.audit(user, "M1", "去重抽检", iid, {"verdict": verdict, "original": it["duplicate_of"]})
    return {"ok": True}
