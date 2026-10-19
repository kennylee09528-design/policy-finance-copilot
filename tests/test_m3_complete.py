from app.m3 import pipeline as P


def test_clean_section_dedup_heading_and_unknown_cites():
    b = P._clean_section("## 二、现状分析\n\n**要点**：担保费率下降[S1]，另有说法[S9]。", "二、现状分析", {"S1"})
    assert not b.startswith("二、") and "[S1]" in b and "[S9]" not in b and "【待核实】" in b and "**" not in b


def test_heading_and_skeleton():
    assert P._cn_heading(3, "## 第三部分：主要问题") == "三、主要问题"
    assert P._skeleton({"genre": "日报研究报告"})[0] == "一、今日要点"
    assert len(P._skeleton({"genre": "研究报告"})) == 5
    assert any("融资担保" in q for q in P._web_queries("每日要闻", {"genre": "日报研究报告"}))


def test_retry_then_success(monkeypatch):
    calls = []

    def fake(tid, agent, messages, user, tokens):
        calls.append(1)
        return {"content": "" if len(calls) < 2 else "正文内容足够长" * 5, "tokens": 1}
    monkeypatch.setattr(P, "_llm", fake)
    monkeypatch.setattr(P, "_ev", lambda *a, **k: None)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    r = P._llm_retry(1, "writer", [], {}, {}, min_len=10)
    assert len(calls) == 2 and r["content"]


def test_auto_revise_support_rewrite_and_mark(monkeypatch):
    src = [{"id": "S1", "title": "通知", "publisher": "x", "level": "A1", "url": "u1", "excerpt": "", "text": "代偿补偿比例为30%。"},
           {"id": "S2", "title": "办法", "publisher": "y", "level": "A1", "url": "u2", "excerpt": "", "text": "担保费率降至0.5%。"}]
    # 在其他已有资料中找到出处 → 改引
    new, add = P._find_support("担保费率降至0.5%[S1]。", src, [], None, {"web": 0})
    assert new == "担保费率降至0.5%[S2]。" and add is None
    # 找不到 → 改写须通过核验，否则删除
    monkeypatch.setattr(P.C, "model_of", lambda a: 1)
    monkeypatch.setattr(P, "_llm", lambda *a, **k: {"content": "我省担保机构数量持续增加[S1]。", "tokens": 1})
    assert P._rewrite(1, "我省担保机构数量达到120家[S1]。", src, [], None, {}) == "我省担保机构数量持续增加[S1]。"
    monkeypatch.setattr(P, "_llm", lambda *a, **k: {"content": "我省担保机构达到99家[S1]。", "tokens": 1})
    assert P._rewrite(1, "我省担保机构数量达到120家[S1]。", src, [], None, {}) == ""
