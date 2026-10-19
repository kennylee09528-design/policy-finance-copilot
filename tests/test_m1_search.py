"""联网搜索供应商层 + M1 搜索驱动采集 + M3 引用登记 验收（外部接口全部以 mock 替代）。"""
import httpx
import pytest

from app import admin_auth
from app.m1 import collector, config as C
from app.m1.classify import classify

KEY = "tvly-secret-0123456789"


@pytest.fixture(scope="module")
def adm(client):
    admin_auth.reset_password("admin", "Init-pass-123")
    client.post("/api/admin/login", json={"username": "admin", "password": "Init-pass-123"})
    assert client.post("/api/admin/password", json={"old": "Init-pass-123", "new": "Search-Admin-2026!"}).status_code == 200
    return client


def fake_search_post(url, json=None, headers=None, timeout=None):
    assert headers["Authorization"] == f"Bearer {KEY}"
    if "tavily" in url:
        q = json["query"]
        return httpx.Response(200, json={"results": [
            {"title": f"{q} 关于印发融资担保支持办法的通知", "url": "https://czt.gd.gov.cn/zcfg/content/post_1.html", "content": "通知正文…", "published_date": "2026-09-28T08:00:00"},
            {"title": f"{q} 新闻发布会", "url": "https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202609/t1.htm", "content": "发布会…"},
            {"title": f"{q} 新华网报道", "url": "https://www.news.cn/fortune/20260929/a.html?utm_source=x", "content": "报道…"},
            {"title": f"{q} 公众号转载", "url": "https://mp.weixin.qq.com/s/abc", "content": "转载…"},
            {"title": f"{q} 某聚合站", "url": "https://www.example-agg.com/p/1", "content": "…"},
        ]})
    return httpx.Response(200, json={"pageItems": [{"title": "IQS 结果", "link": "https://www.gov.cn/zhengce/content/202609/c1.htm",
                                                     "snippet": "摘要", "publishedTime": "2026-09-27T10:00:00+08:00", "hostname": "中国政府网"}]})


def test_classify_rules():
    cfg = C.get()
    assert classify("https://czt.gd.gov.cn/zcfg/x.html", cfg)["level"] == "A1"
    assert classify("https://czt.gd.gov.cn/gkmlpt/x", cfg)["level"] == "A1"
    assert classify("https://czt.gd.gov.cn/czxw/x.html", cfg) == {"publisher": "广东省财政厅", "level": "A2", "layer": "省级", "rule": "czt.gd.gov.cn"}
    assert classify("https://www.sz.gov.cn/xxgk/a.html", cfg)["publisher"] == "政府网站（www.sz.gov.cn）"
    assert classify("https://mp.weixin.qq.com/s/x", cfg)["level"] == "C1"
    assert classify("https://news.qq.com/a", cfg)["level"] == "B2"
    assert classify("https://www.people.com.cn/n1/x", cfg)["level"] == "B1"
    assert classify("https://evilgov.cn/x", cfg)["level"] == "C2"  # 不是 gov.cn 子域


def test_plan_queries():
    cfg = C.get()
    plan, info = collector.plan_queries(cfg)
    assert len(plan) == cfg["max_queries_per_run"]
    assert info["fixed"] == 2 * len(cfg["topics"])
    assert plan[0]["query"] == cfg["topics"][0] and plan[len(cfg["topics"])]["region"] == "广东"
    total = sum(len(t["regions"]) for t in cfg["tiers"])
    assert total == 1 + 1 + 20 + 5 + 30  # 全国 + 广东 + 广东地市 + 5 个重点城市 + 其余 30 省


def test_search_provider_admin(adm, client, monkeypatch):
    monkeypatch.setattr("app.search.client.httpx.post", fake_search_post)
    assert client.post("/api/m1/run").status_code == 400  # 未配置搜索供应商
    r = adm.post("/api/admin/search/providers", json={"vendor": "tavily", "api_key": KEY})
    pid = r.json()["id"]
    lst = adm.get("/api/admin/search/providers").text
    assert KEY not in lst and "tvl****6789" in lst
    t = adm.post(f"/api/admin/search/providers/{pid}/test").json()
    assert t["ok"] and t["n"] == 5
    iqs = adm.post("/api/admin/search/providers", json={"vendor": "aliyun_iqs", "api_key": KEY}).json()["id"]
    assert adm.post(f"/api/admin/search/providers/{iqs}/test").json()["sample"] == "IQS 结果"
    provs = adm.get("/api/admin/search/providers").json()["providers"]
    assert [p["is_default"] for p in provs] == [True, False]
    adm.post(f"/api/admin/search/providers/{iqs}/default")
    assert [p["is_default"] for p in adm.get("/api/admin/search/providers").json()["providers"]] == [False, True]
    adm.post(f"/api/admin/search/providers/{pid}/default")
    # 非管理员不可读写配置
    c2 = httpx.Client(transport=client._transport, base_url=str(client.base_url))
    assert c2.get("/api/admin/search/providers").status_code == 403
    assert c2.put("/api/admin/m1/config", json={}).status_code == 403


def test_m1_collect(adm, monkeypatch):
    monkeypatch.setattr("app.search.client.httpx.post", fake_search_post)
    fetched = []
    monkeypatch.setattr(collector, "fetch", lambda u: fetched.append(u) or {"title": "", "text": "正文：担保费补贴不超过1%。", "date": "2026-09-28", "kind": "html", "final_url": u})
    monkeypatch.setattr(collector.time, "sleep", lambda s: None)
    cfg = adm.put("/api/admin/m1/config", json={"max_queries_per_run": 3, "topics": ["融资担保", "再担保"]}).json()
    assert cfg["max_queries_per_run"] == 3
    assert adm.put("/api/admin/m1/config", json={"template": "{region}"}).status_code == 400
    rid = collector.run("测试")
    from app import db
    run = db.q1("SELECT * FROM m1_runs WHERE id=?", (rid,))
    st = db.jload(run["stats"])
    assert run["status"] == "完成" and st["queries"] == 3 and st["results"] == 15
    assert st["dropped"] == 6  # 公众号 C1 + 聚合站 C2 不在保留等级
    items = adm.get("/api/m1/items?show_dup=true").json()["items"]
    assert {i["level"] for i in items} <= {"A1", "A2", "B1"}
    assert all("utm_source" not in i["url"] for i in items)
    assert len(items) == 3  # 3 个查询返回相同 3 个权威 URL → 按 URL 去重
    assert len(fetched) == 3
    it = adm.get(f"/api/m1/items/{items[0]['id']}").json()
    assert it["content"].startswith("正文") and it["fetch_status"] == "已抓取"
    # 再跑一次：同 URL 去重
    rid2 = collector.run("测试2")
    st2 = db.jload(db.q1("SELECT stats FROM m1_runs WHERE id=?", (rid2,))["stats"])
    assert st2["new"] + st2["dup"] == st2["kept"]
    assert adm.put(f"/api/m1/items/{items[0]['id']}", json={"level": "A1", "reason": "核对原文"}).status_code == 200
    assert adm.get("/api/m1/items", headers={"X-Role": "institution"}).status_code == 403


def test_m3_search_and_citations(adm, monkeypatch):
    monkeypatch.setattr("app.search.client.httpx.post", fake_search_post)
    res = adm.post("/api/m3/search", json={"query": "风险补偿"}).json()["results"]
    a1 = next(x for x in res if x["level"] == "A1")
    assert a1["url"] and a1["title"] and a1["date"] == "2026-09-28"
    assert adm.post("/api/m3/citations", json={"title": "无链接"}).status_code == 400
    cid = adm.post("/api/m3/citations", json={"doc_name": "测试稿", "title": a1["title"], "source_name": a1["publisher"], "level": a1["level"],
                                              "url": a1["url"], "pub_date": a1["date"], "query": "风险补偿", "provider": a1["provider"]}).json()["id"]
    lst = adm.get("/api/m3/citations?doc_name=测试稿").json()
    assert lst[0]["id"] == cid and lst[0]["verify_status"] == "存疑（待核实）"
    adm.put(f"/api/m3/citations/{cid}", json={"verify_status": "已核实", "location": "第2段", "excerpt": "担保费补贴"})
    r = adm.get("/api/m3/citations/export.xlsx?doc_name=测试稿")
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_fetch_ssrf_and_extract():
    from app.m1.fetch import extract, fetch
    with pytest.raises(ValueError):
        fetch("http://127.0.0.1:8000/api/health")
    html = '<html><head><title>站点</title><meta name="PubDate" content="2026-09-28 10:00"></head><body><nav>导航</nav><h1>关于融资担保的通知</h1><div class="TRS_Editor">' + "正文内容。" * 60 + "</div><footer>版权</footer></body></html>"
    o = extract(html.encode())
    assert extract("<html><head><meta charset='gb2312'><title>标题</title></head><body>财政厅</body></html>".encode("gb18030"))["title"] == "标题"
    assert o["title"] == "关于融资担保的通知" and o["date"] == "2026-09-28" and "导航" not in o["text"] and o["text"].startswith("正文内容")


def test_scheduled_daily_cap_and_priority_rotation(adm):
    """定时采集每日硬上限 5，优先国家/广东融资担保·再担保；手动预算独立；超额日返回空。"""
    from app import db
    cfg = adm.put("/api/admin/m1/config", json={
        "max_queries_per_run": 40,
        "max_queries_scheduled_per_day": 5,
        "topics": ["政府性融资担保 政策", "再担保 业务", "科技金融 担保", "民间投资 专项担保"],
    }).json()
    assert cfg["max_queries_scheduled_per_day"] == 5
    assert cfg["max_queries_per_run"] == 40
    db.set_setting("m1_sched_cursor", 0)
    db.set_setting("m1_sched_day_usage", {})
    plan, info = collector.plan_queries_scheduled(cfg, advance=True)
    assert len(plan) == 5
    assert info["budget"] == 5 and info["used_today"] == 5
    assert all(x["region"] in ("全国", "广东") for x in plan)
    assert sum(1 for x in plan if collector._is_priority_topic(x["topic"])) >= 3
    assert len({x["topic"] for x in plan}) >= 2  # 日内主题分散，非同一主题刷满
    # 同日再取：硬上限已用尽
    plan2, info2 = collector.plan_queries_scheduled(cfg, advance=True)
    assert plan2 == [] and info2["remaining_before"] == 0
    # 手动规划仍用 max_queries_per_run，不受定时上限影响
    mplan, minfo = collector.plan_queries(cfg)
    assert len(mplan) == 40
    assert minfo["fixed"] == 2 * len(cfg["topics"])
    # 轮转：清空当日用量后 cursor 前进，下一批与首批不同且仍覆盖优先主题
    db.set_setting("m1_sched_day_usage", {})
    plan3, _ = collector.plan_queries_scheduled(cfg, advance=True)
    assert len(plan3) == 5
    assert [x["query"] for x in plan3] != [x["query"] for x in plan]
    # 配置接口带回定时预览
    d = adm.get("/api/m1/config").json()
    assert d["config"]["max_queries_scheduled_per_day"] == 5
    assert "scheduled_next_plan" in d and d["scheduled_plan_info"]["budget"] == 5
