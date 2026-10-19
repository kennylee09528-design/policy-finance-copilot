"""M3 三 Agent 流水线（大模型以 mock 替代）：配置/提示词版本、检索、M5 占位填数、核对拦截、人工确认、定稿、总结沉淀并注入、Word 导出。"""
import io
import json
import re
import zipfile

import httpx
import pytest

from app import admin_auth, db
from app.llm import service as L
from app.m3 import pipeline as P

CALLS = []
FACTS = [{"id": "F1", "name": "常规业务累计备案（直保+再保）", "value": "5,282,500.00 万元", "delta": "+1,000.00 万元", "source": "M5 机构看板（统计时点 2026-09-30）"}]


def fake_llm(url, json=None, headers=None, timeout=None):
    msgs = json["messages"]
    sys_p = next((m["content"] for m in msgs if m["role"] == "system"), "")
    user = msgs[-1]["content"]
    CALLS.append({"model": json["model"], "temperature": json.get("temperature"), "system": sys_p, "user": user})
    m = re.search(r"(S\d+)｜[^\n]*\n[^\n]*30%", user)
    sid = m.group(1) if m else "S1"
    if "材料核对员" in sys_p:
        out = '{"issues":[{"text":"各地","problem":"表述可更具体","severity":"低"}]}'
    elif "写作规范提炼员" in sys_p:
        out = '{"entries":[{"category":"措辞","content":"用“持续深化”替代“持续优化”"},{"category":"口径","content":"机构数量须注明统计口径与时点"}]}'
    elif "请先给出大纲" in user:
        out = '```json\n[{"heading":"一、政策背景","points":["代偿补偿"]},{"heading":"二、主要做法","points":["银担合作"]}]\n```'
    elif "现在只写第 1 节" in user:
        out = f"国家融资担保基金再担保代偿补偿比例为30%[{sid}]。" + ("截至目前本公司常规业务累计备案{{F1}}。" if "{{F1}}：" in user else "")
    else:
        out = f"我省担保机构数量达到120家。担保费率降至0.5%[{sid}]。各地持续优化银担合作机制[{sid}]。"
    return httpx.Response(200, json={"choices": [{"message": {"content": out}}], "model": json["model"], "usage": {"total_tokens": 100}})


@pytest.fixture(scope="module")
def env(client):
    admin_auth.reset_password("admin", "Init-pass-m3")
    client.post("/api/admin/login", json={"username": "admin", "password": "Init-pass-m3"})
    client.post("/api/admin/password", json={"old": "Init-pass-m3", "new": "M3-Admin-2026!x"})
    u = {"name": "测试", "role": "admin"}
    pub_p = L.save_provider({"vendor": "deepseek", "base_url": "https://pub.example/v1", "api_key": "sk-pub-xxxxxxxx"}, u)
    pri_p = L.save_provider({"vendor": "company_private", "base_url": "https://priv.example/v1", "api_key": "sk-pri-xxxxxxxx"}, u)
    pub = L.save_model({"provider_id": pub_p, "model_id": "m3-pub"}, u)
    pri = L.save_model({"provider_id": pri_p, "model_id": "m3-priv", "allow_sensitive": True}, u)
    db.execute("INSERT INTO m1_items(url,title,publisher,level,layer,region,pub_date,content,collected_at) VALUES(?,?,?,?,?,?,?,?,?)",
               ("https://www.gov.cn/m3/kb1.htm", "关于做好政府性融资担保代偿补偿工作的通知", "国务院办公厅", "A1", "国家", "全国", "2026-09-20",
                "国家融资担保基金再担保代偿补偿比例为30%。担保费率原则上不超过1%。", db.now()))
    return {"pub": pub, "pri": pri}


def _wait_done(client, tid):
    t = client.get(f"/api/m3/tasks/{tid}").json()
    assert t["status"] not in P.RUNNING, t
    return t


def test_agents_admin_and_sensitive(client, env, monkeypatch):
    monkeypatch.setattr("app.llm.client.httpx.post", fake_llm)
    c2 = httpx.Client(transport=client._transport, base_url=str(client.base_url))
    assert c2.put("/api/admin/m3/agents", json={"writer": {"temperature": 0.3}}).status_code == 403
    assert client.put("/api/admin/m3/agents", json={"writer": {"temperature": 5}}).status_code == 400
    r = client.put("/api/admin/m3/agents", json={a: {"model_id": env["pub"], "temperature": t} for a, t in (("writer", 0.3), ("checker", 0.0), ("summarizer", 0.2))})
    assert r.status_code == 200 and r.json()["writer"]["temperature"] == 0.3
    # 使用 M5 数据时，未授权敏感数据的模型被拒绝
    rr = client.post("/api/m3/tasks", json={"title": "测试", "use_m5": True, "use_web": False, "sync": True})
    assert rr.status_code == 403 and "敏感" in rr.json()["detail"]
    client.put("/api/admin/m3/agents", json={a: {"model_id": env["pri"]} for a in ("writer", "checker", "summarizer")})
    assert client.get("/api/m3/agents").json()["effective_model"]["writer"] == env["pri"]


def _no_revise(monkeypatch):
    get0 = P.C.get

    def get():
        c = get0()
        c["checker"]["auto_revise"] = False
        return c
    monkeypatch.setattr(P.C, "get", get)


def test_pipeline_check_finalize_summarize(client, env, monkeypatch):
    _no_revise(monkeypatch)  # 本用例验证未修订的核对结果
    monkeypatch.setattr("app.llm.client.httpx.post", fake_llm)
    monkeypatch.setattr(P, "m5_facts", lambda d=None: FACTS)
    CALLS.clear()
    r = client.post("/api/m3/tasks", json={"title": "政府性融资担保代偿补偿工作情况报告", "requirements": "突出代偿补偿与银担合作", "words": 800,
                                          "use_kb": True, "use_web": False, "use_m5": True, "sync": True})
    assert r.status_code == 200
    tid = r.json()["id"]
    t = _wait_done(client, tid)
    assert t["status"] == "待人工修改（有标红）", t.get("error")
    assert any(s["type"] == "知识库(M1)" and "代偿补偿" in s["title"] for s in t["sources"])
    assert "{{F1}}" not in t["draft"] and "5,282,500.00 万元[M5]" in t["draft"]        # M5 数值由系统填入
    assert all("5,282,500" not in c["user"] for c in CALLS if "请先给出大纲" in c["user"] or "现在只写" in c["user"])  # 写作模型看不到 M5 数值
    assert CALLS[0]["temperature"] == 0.3 and CALLS[0]["model"] == "m3-priv"
    segs = {e["segment"] for e in t["events"] if e["segment"]}
    assert segs == {1, 2} and t["tokens_total"] == 100 * len(CALLS) and t["elapsed_ms"] >= 0
    chk = t["check_result"]
    red = {i["text"]: i for i in chk["items"] if i["red"]}
    assert chk["red"] == 2
    assert red["我省担保机构数量达到120家。"]["status"] == "未找到出处"
    assert any(k.startswith("担保费率降至0.5%") and v["status"] == "存疑（待核实）" for k, v in red.items())
    assert any(i["status"] == "已核实" and "30%" in i["text"] for i in chk["items"])
    assert any(i["status"] == "已核实" and "[M5]" in i["text"] for i in chk["items"])
    assert chk["llm_warnings"] and chk["llm_warnings"][0]["problem"]
    reg = {r_["status"] for r_ in chk["register"]}
    assert {"未找到出处", "存疑（待核实）", "已核实"} <= reg
    rows = db.q("SELECT * FROM m3_citations WHERE task_id=?", (tid,))
    assert rows and any(x["verify_status"] == "未找到出处" for x in rows)
    # 标红未处理 → 不能定稿
    assert client.post(f"/api/m3/tasks/{tid}/finalize").status_code == 409
    # 人工修改终稿：删去无出处句、改措辞；存疑句人工确认（须填理由）
    final = t["draft"].replace("我省担保机构数量达到120家。", "").replace("持续优化", "持续深化")
    f = client.put(f"/api/m3/tasks/{tid}/final", json={"final": final}).json()
    assert f["red"] == 1
    key = next(i["key"] for i in f["items"] if i["red"])
    assert client.post(f"/api/m3/tasks/{tid}/confirm", json={"key": key, "reason": ""}).status_code == 400
    assert client.post(f"/api/m3/tasks/{tid}/confirm", json={"key": key, "reason": "已与原始文件第3条核对"}).json()["red"] == 0
    assert client.post(f"/api/m3/tasks/{tid}/finalize").status_code == 200
    assert client.put(f"/api/m3/tasks/{tid}/final", json={"final": "x"}).status_code == 409
    s = client.post(f"/api/m3/tasks/{tid}/summarize").json()
    assert s["method"] == "总结 Agent" and s["n_changes"] >= 1 and len(s["entry_ids"]) == 2
    guide = client.get("/api/m3/style").json()
    assert any("持续深化" in g["content"] and g["source_task_id"] == tid for g in guide)
    d = client.get(f"/api/m3/tasks/{tid}/export.docx")
    assert d.status_code == 200
    xml = zipfile.ZipFile(io.BytesIO(d.content)).read("word/document.xml").decode()
    assert "引用来源登记表" in xml and "修改痕迹说明" in xml and "已核实" in xml and "5,282,500.00 万元" in xml
    md = client.get(f"/api/m3/tasks/{tid}/export.md").text
    assert "| 来源编号 |" in md


def test_style_injection_and_prompt_version(client, env, monkeypatch):
    _no_revise(monkeypatch)
    monkeypatch.setattr("app.llm.client.httpx.post", fake_llm)
    tpl = "【V2模板】只用资料写作，句末标 [Sk]。文风{tone}。规范：\n{style_guide}"
    assert client.post("/api/admin/m3/prompts", json={"agent": "writer", "content": tpl, "note": "v2"}).status_code == 200
    vers = client.get("/api/admin/m3/prompts?agent=writer").json()
    assert vers[0]["version"] == 2 and vers[0]["active"] == 1 and vers[1]["active"] == 0
    sid = client.post("/api/m3/style", json={"category": "心得", "content": "对外材料不写内部简称"}).json()["id"]
    CALLS.clear()
    tid = client.post("/api/m3/tasks", json={"title": "政府性融资担保银担合作情况", "use_web": False, "use_m5": False, "sync": True}).json()["id"]
    t = _wait_done(client, tid)
    sysp = CALLS[0]["system"]
    assert "【V2模板】" in sysp and "持续深化" in sysp and "对外材料不写内部简称" in sysp
    assert t["agents"]["writer"]["prompt_version"] == 2
    client.put(f"/api/m3/style/{sid}", json={"enabled": False})
    CALLS.clear()
    client.post("/api/m3/tasks", json={"title": "再测一次融资担保", "use_web": False, "sync": True})
    assert "对外材料不写内部简称" not in CALLS[0]["system"]
    first = client.get("/api/admin/m3/prompts?agent=writer").json()[-1]
    client.post(f"/api/admin/m3/prompts/{first['id']}/activate")


def test_rule_check_rank_case():
    src = [{"id": "S1", "title": "通知", "excerpt": "", "text": "广东融资担保在保余额位居全国前列。", "publisher": "x", "level": "A1", "url": "u"}]
    chk = P.rule_check("我省融资担保规模位居全省第一。《广东省某某管理办法》明确了分险比例[S1]。规模位居全国前列[S1]。一般性表述。", src, [])
    st = {i["text"]: i["status"] for i in chk["items"]}
    assert st["我省融资担保规模位居全省第一。"] == "未找到出处"
    assert st["《广东省某某管理办法》明确了分险比例[S1]。"] == "存疑（待核实）"
    assert st["规模位居全国前列[S1]。"] == "已核实" and "一般性表述。" not in st and chk["red"] == 2


def test_no_writer_model(client, env):
    db.set_setting("m3_agents", {})
    a = db.get_setting("llm_assign", {})
    db.set_setting("llm_assign", {k: v for k, v in a.items() if not k.startswith("m3.")})
    assert client.post("/api/m3/tasks", json={"title": "x"}).status_code == 400
    db.set_setting("llm_assign", a)


def test_async_with_web_search(client, env, monkeypatch):
    import time
    from app.search import service as S

    def fake_post(url, json=None, headers=None, timeout=None):
        if "tavily" in url:
            return httpx.Response(200, json={"results": [{"title": "财政部 融资担保 降费通知", "url": "https://www.mof.gov.cn/m3/web1.htm",
                                                          "content": "摘要", "published_date": "2026-09-25"}]})
        return fake_llm(url, json, headers, timeout)
    monkeypatch.setattr("app.llm.client.httpx.post", fake_post)
    monkeypatch.setattr("app.search.client.httpx.post", fake_post)
    monkeypatch.setattr("app.m1.fetch.fetch", lambda u, timeout=10: {"text": "担保费率降至0.5%，代偿补偿比例为30%。"})
    if not db.q1("SELECT id FROM search_providers WHERE enabled=1"):
        S.save({"vendor": "tavily", "api_key": "tvly-x"}, {"name": "t", "role": "admin"})
    db.set_setting("m3_agents", {"writer": {"model_id": env["pub"]}, "checker": {"model_id": env["pub"]}})  # 不依赖前序用例的配置
    tid = client.post("/api/m3/tasks", json={"title": "融资担保降费情况", "use_kb": False, "use_web": True}).json()["id"]
    for _ in range(100):
        t = client.get(f"/api/m3/tasks/{tid}").json()
        if t["status"] not in P.RUNNING:
            break
        time.sleep(0.05)
    assert t["status"].startswith("待人工"), t.get("error")
    web = [s for s in t["sources"] if s["type"] == "联网检索"]
    assert web and "0.5%" in web[0]["excerpt"]
    # 0.5% 这次在抓取的原文中能找到 → 已核实；仍无出处的 120家 标红
    st = {i["text"]: i["status"] for i in t["check_result"]["items"]}
    assert any(k.startswith("担保费率降至0.5%") and v == "已核实" for k, v in st.items())
    assert st["我省担保机构数量达到120家。"] == "未找到出处"
