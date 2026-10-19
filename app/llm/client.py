"""统一 OpenAI 兼容适配器（/chat/completions）。所有厂商与公司私有模型共用。"""
import re
import time
from urllib.parse import urlparse

import httpx

from .. import ops

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S | re.I)
MINIMAX_HOSTS = ("api.minimaxi.com", "api.minimax.cn", "api.minimax.io", "api.minimax.chat")


def strip_think(text: str) -> str:
    """去掉推理模型混在正文里的 <think>…</think>；若只有未闭合的 <think>（被截断），返回空串。"""
    t = THINK_RE.sub("", text or "")
    if re.match(r"\s*<think>", t, re.I):
        return ""
    return t.strip()


def is_minimax(base_url: str) -> bool:
    h = (urlparse(base_url or "").hostname or "").lower()
    return any(h == x or h.endswith("." + x) for x in MINIMAX_HOSTS)


def _minimax_body(body: dict):
    """MiniMax 兼容接口怪癖：温度 [0,2]（0 在部分型号报错，取 0.01）、top_p (0,1]；思考 token 计入长度上限；n 仅支持 1；不支持 penalty。"""
    if "temperature" in body:
        body["temperature"] = min(2.0, max(0.01, float(body["temperature"])))
    if "top_p" in body:
        body["top_p"] = min(1.0, max(0.01, float(body["top_p"])))
    mt = body.pop("max_tokens", None)
    if mt is not None:
        body["max_completion_tokens"] = max(int(mt), 2048)
    for k in ("presence_penalty", "frequency_penalty", "n"):
        body.pop(k, None)
    body["reasoning_split"] = True  # 思考内容放 reasoning_content，正文更干净（仍做 <think> 兜底剥离）


class LLMError(Exception):
    pass


def is_anthropic(base_url: str) -> bool:
    """base_url 以 /anthropic 结尾（如 MiniMax https://api.minimax.cn/anthropic）→ 使用 Anthropic Messages 协议。"""
    return (urlparse(base_url or "").path or "").rstrip("/").endswith("/anthropic")


def _http_error(r, api_key):
    txt = r.text[:300]
    if api_key:
        txt = txt.replace(api_key, "****")
    if r.status_code == 429:
        return LLMError(f"HTTP 429：限流或套餐额度窗口已用尽（包月套餐受 5 小时/周窗口与 RPM 限制），请稍后重试或改用按量计费 Key。{txt}")
    return LLMError(f"HTTP {r.status_code}：{txt}")


def chat_anthropic(base_url, api_key, model, messages, params=None, timeout=60):
    """Anthropic Messages 兼容：POST {base}/v1/messages；system 单独字段；只取 text 块（丢弃 thinking 块）。"""
    url = base_url.rstrip("/") + "/v1/messages"
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and m.get("content"))
    msgs = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "assistant" if m["role"] == "assistant" else "user"
        if msgs and msgs[-1]["role"] == role:  # Anthropic 要求 user/assistant 交替
            msgs[-1]["content"] += "\n\n" + (m.get("content") or "")
        else:
            msgs.append({"role": role, "content": m.get("content") or ""})
    p = params or {}
    body = {"model": model, "messages": msgs, "max_tokens": int(p.get("max_tokens") or 8192)}
    if system:
        body["system"] = system
    for k in ("temperature", "top_p"):
        if p.get(k) not in (None, ""):
            body[k] = p[k]
    if p.get("stop"):
        body["stop_sequences"] = p["stop"] if isinstance(p["stop"], list) else [p["stop"]]
    if is_minimax(base_url):
        if "temperature" in body:
            body["temperature"] = min(2.0, max(0.01, float(body["temperature"])))
        if "top_p" in body:
            body["top_p"] = min(1.0, max(0.01, float(body["top_p"])))
        body["max_tokens"] = max(body["max_tokens"], 2048)  # 思考 token 计入上限
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"  # MiniMax 文档示例使用 Bearer，两者都带
    t0 = time.time()
    try:
        r = ops.post_retry(url, json=body, headers=headers, timeout=timeout, label=f"大模型 {model}")
    except httpx.HTTPError as e:
        raise LLMError(f"网络错误：{type(e).__name__}: {e}") from e
    ms = int((time.time() - t0) * 1000)
    if r.status_code >= 400:
        raise _http_error(r, api_key)
    try:
        j = r.json()
        raw = "".join(b.get("text", "") or b.get("thinking", "") for b in j["content"])
        content = strip_think("".join(b.get("text", "") for b in j["content"] if b.get("type") == "text"))
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"返回格式不是 Anthropic Messages 格式：{r.text[:200]}") from e
    u = j.get("usage") or {}
    usage = {"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens"),
             "total_tokens": (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) or None}
    finish = {"max_tokens": "length"}.get(j.get("stop_reason"), j.get("stop_reason"))
    return {"content": content, "raw": raw, "ms": ms, "usage": usage, "model": j.get("model", model), "finish_reason": finish}


def chat(base_url: str, api_key: str, model: str, messages: list, params: dict | None = None, timeout: float = 60):
    if not base_url:
        raise LLMError("未配置 base_url")
    if is_anthropic(base_url):
        return chat_anthropic(base_url, api_key, model, messages, params, timeout)
    url = base_url.rstrip("/") + "/chat/completions"
    body = {"model": model, "messages": messages}
    for k, v in (params or {}).items():
        if k in ("temperature", "top_p", "max_tokens", "presence_penalty", "frequency_penalty", "stop") and v not in (None, ""):
            body[k] = v
    if is_minimax(base_url):
        _minimax_body(body)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    t0 = time.time()
    try:
        r = ops.post_retry(url, json=body, headers=headers, timeout=timeout, label=f"大模型 {model}")
    except httpx.HTTPError as e:
        raise LLMError(f"网络错误：{type(e).__name__}: {e}") from e
    ms = int((time.time() - t0) * 1000)
    if r.status_code >= 400:
        raise _http_error(r, api_key)
    try:
        j = r.json()
        msg = j["choices"][0]["message"]
        raw = (("<reasoning>" + msg["reasoning_content"] + "</reasoning>\n") if msg.get("reasoning_content") else "") + (msg.get("content") or "")
        content = strip_think(msg.get("content") or "")
        finish = j["choices"][0].get("finish_reason")
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"返回格式不是 OpenAI 兼容格式：{r.text[:200]}") from e
    return {"content": content, "raw": raw, "ms": ms, "usage": j.get("usage"), "model": j.get("model", model), "finish_reason": finish}


def embed(base_url: str, api_key: str, model: str, inputs: list, timeout: float = 60):
    """OpenAI 兼容 /embeddings 接口（通义 text-embedding-v3、智谱 embedding-3、私有部署 bge 等）。"""
    url = base_url.rstrip("/") + "/embeddings"
    r = ops.post_retry(url, json={"model": model, "input": inputs}, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                       timeout=timeout, label=f"向量模型 {model}")
    if r.status_code >= 400:
        raise _http_error(r, api_key)
    data = sorted(r.json()["data"], key=lambda x: x.get("index", 0))
    return [d["embedding"] for d in data]
