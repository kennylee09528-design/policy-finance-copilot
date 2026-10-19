"""M1 增强：语义检索（无向量模型退化 / 有向量模型）、来源健康、复核队列、被引用、去重抽检。"""
import httpx
import pytest

from app import db
from app.llm import service as L

N = db.now


@pytest.fixture(autouse=True, scope="module")
def _cleanup():
    yield  # 测试数据不留给其他模块（如 test_m1_search 的等级断言）
    for host in ("ins", "bad", "cite", "dup"):
        db.execute("DELETE FROM m1_items WHERE url LIKE ?", (f"https://{host}.example/%",))
    db.execute("DELETE FROM m3_citations WHERE url LIKE 'https://cite.example/%'")


def _item(url, title, publisher="财政部", level="A1", fetch="已抓取", pub="2026-09-01", summary="要点", dup=None, content=""):
    return db.execute("INSERT INTO m1_items(url,title,publisher,level,fetch_status,pub_date,summary,duplicate_of,collected_at,content) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (url, title, publisher, level, fetch, pub, summary, dup, N(), content))


def test_semantic_fallback_and_embedding(client, monkeypatch):
    a = _item("https://ins.example/a", "关于实施小微企业融资担保降费奖补政策的通知", content="对担保费率降至1%以下的机构给予奖补")
    b = _item("https://ins.example/b", "农业农村部关于加快发展智慧农业的意见")
    r = client.get("/api/m1/semantic", params={"q": "小微企业融资担保降费奖补"}).json()
    ids = [x["id"] for x in r["results"]]
    # 同库其他用例（如 M2）也会写入担保类条目，只要求 a 排在前列、无关条目 b 不在其前
    assert "字符二元组" in r["method"] and a in ids[:3] and (b not in ids or ids.index(b) > ids.index(a))
    # 配置向量模型：mock /embeddings，按是否含“担保”给出向量
    u = {"name": "测试", "role": "admin"}
    p = L.save_provider({"vendor": "dashscope", "base_url": "https://emb.example/v1", "api_key": "sk-emb-xxxxxxxx"}, u)
    mid = L.save_model({"provider_id": p, "model_id": "text-embedding-v3"}, u)
    L.assign("m1.embed", mid, u)

    def fake(url, json=None, headers=None, timeout=None):
        assert url.endswith("/embeddings")
        vec = lambda t: [1.0, 0.0] if ("担保" in t or "增信" in t) else [0.0, 1.0]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": vec(t)} for i, t in enumerate(json["input"])]})
    monkeypatch.setattr("app.llm.client.httpx.post", fake)
    r = client.get("/api/m1/semantic", params={"q": "增信支持"}).json()
    assert "向量语义检索" in r["method"] and r["results"][0]["id"] in (a,) + tuple(x["id"] for x in db.q("SELECT id FROM m1_items WHERE title LIKE '%担保%'"))
    assert db.q1("SELECT COUNT(*) n FROM m1_embeddings WHERE model_db_id=?", (mid,))["n"] >= 2
    a = db.get_setting("llm_assign", {}); a.pop("m1.embed", None); db.set_setting("llm_assign", a)


def test_health_review_cited_dedup(client):
    for i in range(3):
        _item(f"https://bad.example/{i}", f"坏来源{i}", publisher="某坏来源网", level="C1", fetch="抓取失败：timeout", pub=None, summary=None)
    h = {x["publisher"]: x for x in client.get("/api/m1/sources/health").json()}
    assert h["某坏来源网"]["status"] == "异常" and h["某坏来源网"]["fail_rate"] == 1.0
    q = client.get("/api/m1/review").json()
    bad = next(x for x in q["queue"] if x["title"] == "坏来源0")
    assert "正文未抓取成功" in bad["reasons"] and "缺发布日期" in bad["reasons"]
    assert client.post(f"/api/m1/items/{bad['id']}/review", json={"action": "level", "level": "B1"}).status_code == 200
    assert bad["id"] not in [x["id"] for x in client.get("/api/m1/review").json()["queue"]]
    assert db.q1("SELECT level, level_manual FROM m1_items WHERE id=?", (bad["id"],))["level"] == "B1"
    # 被引用
    it = _item("https://cite.example/x", "被引用的政策")
    db.execute("INSERT INTO m3_citations(doc_name,url,title,created_at) VALUES('某报告','https://cite.example/x','t',?)", (N(),))
    assert len(client.get(f"/api/m1/items/{it}/citations").json()) == 1
    lst = client.get("/api/m1/items", params={"kw": "被引用的政策"}).json()["items"]
    assert lst[0]["cited"] == 1
    # 去重抽检
    o = _item("https://dup.example/o", "同一政策")
    d1 = _item("https://dup.example/d1", "同一政策（转载）", dup=o)
    d2 = _item("https://dup.example/d2", "完全不同的政策", dup=o)
    s = client.get("/api/m1/dedup/sample?n=50").json()
    assert {d1, d2} <= {x["id"] for x in s["sample"]}
    client.post(f"/api/m1/dedup/{d1}", json={"verdict": "correct"})
    client.post(f"/api/m1/dedup/{d2}", json={"verdict": "wrong"})
    s = client.get("/api/m1/dedup/sample").json()
    assert s["checked"] >= 2 and s["accuracy"] is not None
    assert db.q1("SELECT duplicate_of FROM m1_items WHERE id=?", (d2,))["duplicate_of"] is None
    assert client.post(f"/api/m1/dedup/{o}", json={"verdict": "correct"}).status_code == 400
