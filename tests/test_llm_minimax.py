"""MiniMax 预设与兼容怪癖（mock）：国内/国际 base_url、<think> 剥离、温度/top_p 夹紧、max_tokens→max_completion_tokens。"""
import httpx

from app.llm import client
from app.llm.presets import PRESET_MAP


def test_presets():
    assert PRESET_MAP["minimax"]["base_url"] == "https://api.minimaxi.com/v1"
    assert PRESET_MAP["minimax_intl"]["base_url"] == "https://api.minimax.io/v1"
    for v in ("minimax", "minimax_intl"):
        assert "MiniMax-M2" in PRESET_MAP[v]["models"] and "MiniMax-M3" in PRESET_MAP[v]["models"]


def test_minimax_quirks(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json)
        return httpx.Response(200, json={"choices": [{"message": {"content": "<think>先分析一下……\n</think>\n\n连接正常"}}],
                                         "model": json["model"], "usage": {"total_tokens": 42}})
    monkeypatch.setattr("app.llm.client.httpx.post", fake_post)
    r = client.chat("https://api.minimaxi.com/v1", "k", "MiniMax-M2", [{"role": "user", "content": "hi"}],
                    {"temperature": 0, "top_p": 1.5, "max_tokens": 16, "presence_penalty": 0.5})
    b = seen["body"]
    assert seen["url"] == "https://api.minimaxi.com/v1/chat/completions"
    assert r["content"] == "连接正常"
    assert b["temperature"] == 0.01 and b["top_p"] == 1.0 and "max_tokens" not in b and b["max_completion_tokens"] == 2048
    assert "presence_penalty" not in b and b["reasoning_split"] is True
    client.chat("https://api.minimax.io/v1", "k", "MiniMax-M2.5", [{"role": "user", "content": "hi"}], {"temperature": 3})
    assert seen["body"]["temperature"] == 2.0
    # 非 MiniMax 不改参数，但同样剥离 <think>
    client.chat("https://api.deepseek.com/v1", "k", "deepseek-chat", [{"role": "user", "content": "hi"}], {"temperature": 0, "max_tokens": 16})
    assert seen["body"]["temperature"] == 0 and seen["body"]["max_tokens"] == 16 and "reasoning_split" not in seen["body"]


def test_strip_think():
    assert client.strip_think("<think>a</think>答案") == "答案"
    assert client.strip_think("<think>被截断的思考") == ""
    assert client.strip_think("普通回答") == "普通回答"
    assert client.is_minimax("https://api.minimaxi.com/v1") and not client.is_minimax("https://minimax.evil.example/v1")


def test_token_plan_anthropic(monkeypatch):
    from app.llm.presets import PRESET_MAP
    p = PRESET_MAP["minimax_token_plan"]
    assert p["base_url"] == "https://api.minimax.cn/anthropic" and "MiniMax-M3" in p["models"] and not p.get("allow_sensitive")
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, headers=headers)
        return httpx.Response(200, json={"id": "msg_1", "type": "message", "role": "assistant", "model": json["model"],
                                         "content": [{"type": "thinking", "thinking": "内部推理"}, {"type": "text", "text": "连接正常"}],
                                         "usage": {"input_tokens": 12, "output_tokens": 30}})
    monkeypatch.setattr("app.llm.client.httpx.post", fake_post)
    r = client.chat(p["base_url"], "sk-cp-test", "MiniMax-M3",
                    [{"role": "system", "content": "你是助手"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
                    {"temperature": 0, "max_tokens": 16})
    b, h = seen["body"], seen["headers"]
    assert seen["url"] == "https://api.minimax.cn/anthropic/v1/messages"
    assert h["x-api-key"] == "sk-cp-test" and h["Authorization"] == "Bearer sk-cp-test" and h["anthropic-version"]
    assert b["system"] == "你是助手" and b["messages"] == [{"role": "user", "content": "a\n\nb"}]
    assert b["temperature"] == 0.01 and b["max_tokens"] == 2048
    assert r["content"] == "连接正常" and r["usage"]["total_tokens"] == 42


def test_token_plan_429(monkeypatch):
    import pytest
    monkeypatch.setattr("app.llm.client.httpx.post", lambda url, json=None, headers=None, timeout=None: httpx.Response(429, text='{"error":"rate limit sk-cp-secret"}'))
    with pytest.raises(client.LLMError) as e:
        client.chat("https://api.minimax.cn/anthropic", "sk-cp-secret", "MiniMax-M3", [{"role": "user", "content": "x"}])
    assert "额度窗口" in str(e.value) and "sk-cp-secret" not in str(e.value)


