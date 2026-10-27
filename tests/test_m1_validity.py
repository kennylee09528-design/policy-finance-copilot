"""M1 政策效力：人工核定、90 天到期列表、问答/检索提示。"""
from datetime import date, timedelta

import pytest

from app import db
from app.feishu.service import Ctx, h_policy
from app.m1.validity import WINDOW_DAYS, notice
from app.m3.pipeline import _kb_source, _materials


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db.execute("DELETE FROM m1_items WHERE url LIKE 'https://validity.example/%'")


def _add(url, title, **kw):
    cols = ["url", "title", "publisher", "level", "pub_date", "snippet", "collected_at"]
    vals = [url, title, kw.get("publisher", "示例发布方"), kw.get("level", "A1"), kw.get("pub_date", "2026-01-01"),
            kw.get("snippet", title), db.now()]
    return db.execute(f"INSERT INTO m1_items({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)


def test_default_unknown_and_manual_edit(client):
    iid = _add("https://validity.example/a", "示例关于担保降费的通知")
    it = client.get(f"/api/m1/items/{iid}").json()
    assert it["validity_status"] == "未知"
    assert "效力未核定" in it["validity_notice"] and "勿作决策依据" in it["validity_notice"]
    r = client.put(f"/api/m1/items/{iid}/validity", json={
        "validity_status": "现行有效", "doc_no": "示文〔2026〕1号", "effective_date": "2026-01-01",
        "expiry_date": (date.today() + timedelta(days=30)).isoformat(), "validity_note": "人工核对原文",
        "superseded_by": "",
    }, headers={"X-User": "zhangsan"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["validity_status"] == "现行有效" and body["validity_notice"] is None
    assert body["doc_no"] == "示文〔2026〕1号" and body["validity_updated_by"] == "zhangsan"
    assert client.put(f"/api/m1/items/{iid}/validity", json={"validity_status": "有效"}).status_code == 400
    assert client.put(f"/api/m1/items/{iid}/validity", json={"validity_status": "现行有效", "expiry_date": "2026/01/01"}).status_code == 400
    assert client.put(f"/api/m1/items/{iid}", json={"level": "A2", "reason": "改等级"}).status_code == 200
    kept = client.get(f"/api/m1/items/{iid}").json()
    assert kept["level"] == "A2" and kept["validity_status"] == "现行有效" and kept["doc_no"] == "示文〔2026〕1号"
    assert client.put(f"/api/m1/items/{iid}/validity", json={"validity_status": "已废止"}, headers={"X-Role": "institution"}).status_code == 403
    aud = db.q("SELECT action FROM audit_log WHERE module='M1' AND target=? ORDER BY id DESC", (str(iid),))
    assert any(a["action"] == "人工核定效力" for a in aud)


def test_expiring_window_and_filters(client):
    today = date.today()
    soon = _add("https://validity.example/soon", "示例即将到期的奖补办法")
    edge = _add("https://validity.example/edge", "示例第89天到期的意见")
    later = _add("https://validity.example/later", "示例九十天后的通知")
    past = _add("https://validity.example/past", "示例已过期仍标有效的函")
    dead = _add("https://validity.example/dead", "示例已废止的办法")
    unknown = _add("https://validity.example/unk", "示例效力未知的通知")

    def put(iid, status, expiry=None, abolished=None):
        assert client.put(f"/api/m1/items/{iid}/validity", json={
            "validity_status": status, "expiry_date": expiry or "", "abolished_at": abolished or "",
        }).status_code == 200

    put(soon, "现行有效", (today + timedelta(days=30)).isoformat())
    put(edge, "现行有效", (today + timedelta(days=WINDOW_DAYS - 1)).isoformat())
    put(later, "现行有效", (today + timedelta(days=WINDOW_DAYS)).isoformat())
    put(past, "现行有效", (today - timedelta(days=1)).isoformat())
    put(dead, "已废止", (today + timedelta(days=10)).isoformat(), today.isoformat())

    exp = client.get("/api/m1/expiring").json()
    ids = {x["id"] for x in exp["items"]}
    assert {soon, edge, past} <= ids
    assert later not in ids and dead not in ids and unknown not in ids
    assert exp["days"] == 90
    past_row = next(x for x in exp["items"] if x["id"] == past)
    assert past_row["overdue"] is True
    home = client.get("/api/home").json()
    assert home["m1"]["expiring"] >= 3

    listed = {x["id"] for x in client.get("/api/m1/items", params={"validity": "expiring", "limit": 1000}).json()["items"]}
    assert {soon, edge, past} <= listed and later not in listed
    abolished = {x["id"] for x in client.get("/api/m1/items", params={"validity": "abolished", "kw": "示例已废止"}).json()["items"]}
    assert abolished == {dead}
    assert client.get("/api/m1/items", params={"validity": "not-a-status"}).status_code == 400
    # 未知仍可在列表里筛到，并带效力未核定
    unk = client.get("/api/m1/items", params={"validity": "未知", "kw": "效力未知"}).json()["items"]
    assert unk and unk[0]["id"] == unknown and "效力未核定" in unk[0]["validity_notice"]


def test_answer_and_search_notice(client):
    iid = _add("https://validity.example/qa", "示例虚构降费奖补问答条目", snippet="示例虚构降费奖补")
    sem = client.get("/api/m1/semantic", params={"q": "示例虚构降费奖补问答", "k": 50}).json()
    hit = next(x for x in sem["results"] if x["id"] == iid)
    assert hit["validity_status"] == "未知" and "效力未核定" in hit["validity_notice"]
    assert client.put(f"/api/m1/items/{iid}/validity", json={"validity_status": "已废止", "abolished_at": "2026-02-01",
                                                            "superseded_by": "示例新办法"}).status_code == 200
    sem = client.get("/api/m1/semantic", params={"q": "示例虚构降费奖补问答", "k": 50}).json()
    hit = next(x for x in sem["results"] if x["id"] == iid)
    assert hit["validity_status"] == "已废止" and "勿作决策依据" in hit["validity_notice"] and "已废止" in hit["validity_notice"]
    ctx = Ctx(user={"name": "张三", "role": "internal", "username": "zhangsan"})
    reply = h_policy(ctx, "政策 示例虚构降费奖补")["reply"]
    assert "已废止" in reply and "勿作决策依据" in reply
    assert notice("现行有效") is None
    src = _kb_source({"id": iid, "title": "示例", "url": "https://validity.example/qa", "publisher": "示例发布方",
                      "level": "A1", "pub_date": "2026-01-01", "summary": "要点", "content": "", "snippet": "",
                      "validity_status": "已失效"}, 100)
    text = _materials([{"id": "S1", **{k: src[k] for k in ("title", "publisher", "level", "pub_date", "excerpt", "validity_notice")}}], [], 50)
    assert "已失效" in text and "勿作决策依据" in text
    plain = _materials([{"id": "S1", "title": "现行", "publisher": "示例发布方", "level": "A1", "pub_date": "2026-01-01",
                         "excerpt": "正文无数字", "validity_notice": None}], [], 50)
    assert "勿作决策依据" not in plain
