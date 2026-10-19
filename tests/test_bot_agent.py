"""机器人 Agent 问答：mock 大模型。覆盖路由、权限、不编造数字、敏感数据规则、联网查询脱敏、多轮上下文、回退。"""
import json

import pytest

from app import db
from app.feishu import agent as AG
from app.feishu import service as FS

pytestmark = pytest.mark.usefixtures("isolated_db")
INT = {"name": "张三", "username": "ag_int", "role": "internal"}
INST = {"name": "机构甲", "username": "ag_inst", "role": "institution", "org": "测试机构"}


def ctx(user, key="wx:u1"):
    return FS.Ctx(open_id=key, chat_id="c", chat_type="p2p", group=False, user=user, cfg={"group_data": False}, via="微信", bot_name="普惠Bot", api=None)


class FakeLLM:
    def __init__(self, tool="llm", answer="再担保是对担保机构的担保。"):
        self.tool, self.answer, self.calls = tool, answer, []

    def __call__(self, slot, mid, messages, user, max_tokens=600, timeout=40):
        self.calls.append({"slot": slot, "mid": mid, "messages": messages})
        if "路由器" in messages[0]["content"]:
            return json.dumps({"tool": self.tool, "question": messages[-1]["content"].split("当前问题：")[-1], "keyword": "担保"})
        return self.answer


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    AG._mem.clear()
    models = {"normal": (False,), "sens": (True,)}
    monkeypatch.setattr(AG, "_model", lambda sens: ("bot.agent_sensitive", "sens") if sens else ("bot.agent", "normal"))
    monkeypatch.setattr(AG, "_org_names", lambda: ["示例P融资再担保有限公司"])
    return models


def fake_handlers(rec):
    def mk(name):
        def h(c, t, kw=""):
            rec.append((name, c.user["role"], t))
            return {"reply": f"[{name}] 额度 1,234.00 万元", "files": [], "intent": name, "status": "已处理"}
        return h
    return {k: mk(k) for k in ("quota", "alerts", "brief", "policy", "reports")}


def test_system_route_uses_db_handler_and_tags(monkeypatch):
    llm = FakeLLM(tool="quota")
    monkeypatch.setattr(AG, "_call", llm)
    rec = []
    r = AG.answer(ctx(INT), "示例P再担保额度使用情况", fake_handlers(rec))
    assert rec and rec[0][0] == "quota"
    assert r["reply"].startswith("[quota] 额度 1,234.00 万元") and "「来源：系统」" in r["reply"]
    assert r["route"] == "system" and len(llm.calls) == 1  # 系统结果不再交给大模型改写
    assert llm.calls[0]["slot"] == "bot.agent_sensitive"  # 涉额度/机构 → 敏感授权模型
    a = db.q1("SELECT * FROM audit_log WHERE action LIKE '智能问答·系统%' ORDER BY id DESC LIMIT 1")
    assert a is not None


def test_llm_fallback_tag_and_no_system_data(monkeypatch):
    llm = FakeLLM(tool="llm")
    monkeypatch.setattr(AG, "_call", llm)
    r = AG.answer(ctx(INT), "什么是再担保", fake_handlers([]))
    assert r["route"] == "llm" and "「AI 生成，仅供参考」" in r["reply"]
    assert llm.calls[0]["slot"] == "bot.agent"
    assert "不得编造" in llm.calls[1]["messages"][0]["content"]


def test_institution_cannot_reach_internal_tools(monkeypatch):
    monkeypatch.setattr(AG, "_call", FakeLLM(tool="reports"))
    rec = []
    r = AG.answer(ctx(INST), "最新的研究报告", fake_handlers(rec))
    assert not rec  # reports 不在机构的工具列表 → 不调用
    monkeypatch.setattr(AG, "_call", FakeLLM(tool="m4"))
    r = AG.answer(ctx(INST), "授信测算结果", fake_handlers(rec))
    assert "1,234" not in r["reply"] and not rec


def test_institution_quota_passes_bound_user(monkeypatch):
    monkeypatch.setattr(AG, "_call", FakeLLM(tool="quota"))
    rec = []
    AG.answer(ctx(INST), "我们额度还剩多少", fake_handlers(rec))
    assert rec[0][1] == "institution"  # 行级过滤由 handler 按绑定账号执行


def test_search_query_sanitized(monkeypatch):
    monkeypatch.setattr(AG, "_call", FakeLLM(tool="search", answer="最新政策要点 [1]"))
    seen = {}
    from app.search import service as SS

    def fake_search(q, user=None, **kw):
        seen["q"] = q
        return [{"title": "国务院文件", "url": "https://www.gov.cn/x", "content": "内容"}]
    monkeypatch.setattr(SS, "search", fake_search)
    r = AG.answer(ctx(INT), "示例P融资再担保有限公司 3000万 最新融资担保降费政策", fake_handlers([]))
    assert "示例" not in seen["q"] and "3000" not in seen["q"] and "降费" in seen["q"]
    assert r["route"] == "search" and "https://www.gov.cn/x" in r["reply"] and "AI 生成" in r["reply"]


def test_sensitive_without_authorized_model_falls_back(monkeypatch):
    monkeypatch.setattr(AG, "_model", lambda sens: (None, None) if sens else ("bot.agent", "normal"))
    llm = FakeLLM(tool="quota")
    monkeypatch.setattr(AG, "_call", llm)
    rec = []
    r = AG.answer(ctx(INT), "示例P再担保额度使用情况", fake_handlers(rec))
    assert not llm.calls  # 涉敏问题绝不发给未授权模型
    assert rec[0][0] == "quota" and "「来源：系统」" in r["reply"]  # 规则直达系统工具
    assert AG.answer(ctx(INT), "机构合作有什么建议", fake_handlers([])) is None and not llm.calls  # 涉敏问题绝不发给未授权模型


def test_real_model_selection_respects_allow_sensitive(monkeypatch):
    monkeypatch.undo()
    pid = db.execute("INSERT INTO llm_providers(name,base_url,api_key_enc,enabled) VALUES('t','http://x','',1)")
    mid = db.execute("INSERT INTO llm_models(provider_id,model_id,enabled,allow_sensitive) VALUES(?,?,1,0)", (pid, "m-x"))
    db.set_setting("llm_assign", {"bot.agent": mid})
    assert AG._model(False) == ("bot.agent", mid)
    assert AG._model(True) == (None, None)


def test_multi_turn_context_and_expiry(monkeypatch):
    llm = FakeLLM(tool="llm")
    monkeypatch.setattr(AG, "_call", llm)
    c = ctx(INT, "wx:mt")
    for i in range(8):
        AG.answer(c, f"问题{i}", fake_handlers([]))
    assert len(AG._mem["wx:mt"]["q"]) == 6
    assert "问题7" in llm.calls[-2]["messages"][1]["content"] and "问题6" in llm.calls[-2]["messages"][1]["content"]
    AG._mem["wx:mt"]["t"] -= AG.TTL + 1
    assert len(AG._hist("wx:mt")["q"]) == 0


def test_handle_bound_commands_untouched_and_llm_down_fallback(monkeypatch):
    called = []
    monkeypatch.setattr(AG, "answer", lambda *a: called.append(1) or None)
    r = FS.handle_bound(ctx(INT), "帮助")
    assert r["intent"] == "help" and not called
    r = FS.handle_bound(ctx(INT), "预警")  # agent 返回 None → 原固定规则
    assert called and r["intent"] == "alerts"
