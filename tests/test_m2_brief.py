"""M2 今日行业 Brief：打分分档（4.2）、模板（4.3）、关键数字来源拦截、版本/编辑/发布锁定/导出、管理员权重。"""
import io
import zipfile
from datetime import datetime, timedelta

import pytest

from app import admin_auth, db
from app.m2 import brief as B

NOW = datetime.now()
TODAY = NOW.strftime("%Y-%m-%d")


def _ins(url, title, level, layer, region, content, summary=None, collected=None, pub=None, dup=None):
    return db.execute("INSERT INTO m1_items(url,title,publisher,level,layer,region,pub_date,snippet,content,summary,duplicate_of,collected_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (url, title, "测试发布方", level, layer, region, pub or TODAY, "", content, summary, dup,
                       (collected or NOW - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")))


@pytest.fixture(scope="module")
def items():
    ids = {
        "A": _ins("https://www.gov.cn/m2/a.htm", "关于进一步做好政府性融资担保工作的通知", "A1", "国家", "全国",
                  "国家融资担保基金再担保代偿补偿比例为30%。对担保费补贴给予支持。"),
        "B": _ins("https://gd.example/m2/b.htm", "广东普惠金融推进会召开", "B1", "省级", "广东", "全省小微企业贷款余额增长12.5%。会议部署下一步工作。"),
        "C": _ins("https://zj.example/m2/c.htm", "浙江普惠金融新举措", "B2", "省级", "浙江", "浙江支持小微企业，新增贷款200亿元。"),
        "D": _ins("https://st.example/m2/d.htm", "汕头某活动简讯", "C2", "普通地市", "汕头", "活动顺利举行。", pub=(NOW - timedelta(days=10)).strftime("%Y-%m-%d")),
        "E": _ins("https://www.mof.gov.cn/m2/e.htm", "财政部融资担保专项资金通知", "A1", "国家", "全国", "安排专项资金支持融资担保发展。",
                  summary="- 新增专项资金500亿元"),
        "F": _ins("https://www.gov.cn/m2/f.htm", "三天前的融资担保旧闻", "A1", "国家", "全国", "旧闻", collected=NOW - timedelta(days=3)),
    }
    ids["G"] = _ins("https://www.gov.cn/m2/g.htm", "关于进一步做好政府性融资担保工作的通知（转载）", "B1", "国家", "全国", "转载", dup=ids["A"])
    return ids


def test_scoring_and_tiers(items):
    from app.m2.config import get
    cfg = get()
    a = db.q1("SELECT * FROM m1_items WHERE id=?", (items["A"],))
    s = B.score(a, cfg, NOW)
    assert s["parts"] == {"来源等级": 100, "政策层级": 100, "业务相关度": 100, "时效性": 100} and s["total"] == 100 and s["tier"] == 3
    b = db.q1("SELECT * FROM m1_items WHERE id=?", (items["B"],))
    sb = B.score(b, cfg, NOW)
    assert B.layer_key(b) == "广东本省" and sb["tier"] == 2 and 60 <= sb["total"] < 80
    d = db.q1("SELECT * FROM m1_items WHERE id=?", (items["D"],))
    assert B.score(d, cfg, NOW)["tier"] == 1 and B.score(d, cfg, NOW)["parts"]["时效性"] == 10


def test_generate_template_block(client, items):
    r = client.post("/api/m2/briefs/generate", json={})
    assert r.status_code == 200
    b = r.json()
    by = {i["m1_id"]: i for i in b["items"]}
    assert items["F"] not in by and items["G"] not in by          # 窗口外 / 已合并重复 不入选
    assert by[items["A"]]["section"] == "必读" and by[items["B"]]["section"] == "关注"
    assert by[items["C"]]["section"] == "同业动态" and by[items["D"]]["section"] == "浏览"
    assert by[items["E"]]["blocked"] and "500亿元" in by[items["E"]]["block_reason"][0]
    md = b["markdown"]
    for h in ("一、今日必读", "二、值得关注", "三、同业动态", "四、数据速览", "五、待核实提示"):
        assert h in md
    main = md.split("## 五、")[0]
    assert "财政部融资担保专项资金通知" not in main and "500亿元" not in main      # 无来源数字被拦截
    assert "【政府性融资担保｜全国】关于进一步做好政府性融资担保工作的通知" in md and "30%" in md
    assert "★ 浏览（默认折叠）" in md
    assert b["stats"]["blocked"] >= 1 and b["status"] == "草稿"


def test_versions_edit_publish_export(client, items):
    b1 = client.post("/api/m2/briefs/generate", json={"date": TODAY}).json()
    assert b1["version"] >= 2
    past = client.post("/api/m2/briefs/generate", json={"date": "2026-09-01"}).json()
    assert past["brief_date"] == "2026-09-01" and past["stats"]["window"][1].startswith("2026-09-01")
    assert client.post("/api/m2/briefs/generate", json={"date": "2999-01-01"}).status_code == 400
    lst = client.get("/api/m2/briefs").json()
    assert any(x["brief_date"] == "2026-09-01" for x in lst) and any(x["brief_date"] == TODAY for x in lst)
    bid = b1["id"]
    # 编辑：调档、改要点（反哺 M1 人工校正），改出无来源数字 → 拦截
    r = client.put(f"/api/m2/briefs/{bid}", json={"items": [{"m1_id": items["B"], "tier": 3, "points": ["全省小微企业贷款余额增长12.5%"]},
                                                          {"m1_id": items["C"], "points": ["浙江新增贷款999亿元"]}]})
    e = r.json()
    by = {i["m1_id"]: i for i in e["items"]}
    assert by[items["B"]]["section"] == "必读" and not by[items["B"]]["blocked"]
    assert by[items["C"]]["blocked"] and "999亿元" not in e["markdown"].split("## 五、")[0]
    assert db.q1("SELECT manual_corrected FROM m1_items WHERE id=?", (items["B"],))["manual_corrected"] == 1
    # 手工改 Markdown 把被拦截条目塞回正文 → 不能发布
    md = e["markdown"].replace("## 五、", "补充：财政部融资担保专项资金通知\n\n## 五、")
    client.put(f"/api/m2/briefs/{bid}", json={"markdown": md})
    assert client.post(f"/api/m2/briefs/{bid}/publish").status_code == 409
    client.put(f"/api/m2/briefs/{bid}", json={"markdown": e["markdown"]})
    p = client.post(f"/api/m2/briefs/{bid}/publish")
    assert p.status_code == 200 and p.json()["status"] == "已发布"
    assert client.put(f"/api/m2/briefs/{bid}", json={"markdown": "x"}).status_code == 409   # 发布后锁定
    m = client.get(f"/api/m2/briefs/{bid}/export.md")
    assert m.status_code == 200 and "今日行业 Brief" in m.text
    d = client.get(f"/api/m2/briefs/{bid}/export.docx")
    assert d.status_code == 200 and d.content[:2] == b"PK"
    xml = zipfile.ZipFile(io.BytesIO(d.content)).read("word/document.xml").decode()
    assert "今日必读" in xml and "数据速览" in xml


def test_admin_weights(client, items):
    import httpx
    c2 = httpx.Client(transport=client._transport, base_url=str(client.base_url))
    assert c2.put("/api/admin/m2/config", json={"weights": {"level": 0.5}}).status_code == 403
    admin_auth.reset_password("admin", "Init-pass-m2")
    client.post("/api/admin/login", json={"username": "admin", "password": "Init-pass-m2"})
    client.post("/api/admin/password", json={"old": "Init-pass-m2", "new": "M2-Admin-2026!x"})
    bad = client.put("/api/admin/m2/config", json={"weights": {"level": 0.5, "layer": 0.5, "relevance": 0.5, "timeliness": 0.5}})
    assert bad.status_code == 400
    ok = client.put("/api/admin/m2/config", json={"weights": {"level": 0.1, "layer": 0.1, "relevance": 0.7, "timeliness": 0.1}, "window_hours": 96, "max_items": 200,
                                                  "schedule": {"enabled": True, "time": "07:30"}})
    assert ok.status_code == 200 and ok.json()["weights"]["relevance"] == 0.7
    b = client.post("/api/m2/briefs/generate", json={}).json()
    assert b["config"]["weights"]["relevance"] == 0.7 and b["stats"]["window"] and items["F"] in {i["m1_id"] for i in b["items"]}  # 96h 窗口纳入 3 天前条目
    client.post("/api/admin/m2/config/reset")


def test_scheduler_window():
    assert B._plus30("07:30") == "08:00" and B._plus30("23:50") == "23:59"
