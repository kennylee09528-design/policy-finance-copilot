"""各搜索厂商适配器 → 统一结果。time_range 取值：day / week / month / year / none。"""
from urllib.parse import urlparse

import httpx

from .. import ops


class SearchError(Exception):
    pass


_IQS_TR = {"day": "OneDay", "week": "OneWeek", "month": "OneMonth", "year": "OneYear", "none": "NoLimit", None: "NoLimit"}


def _post(url, body, key, timeout):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        r = ops.post_retry(url, json=body, headers=headers, timeout=timeout, label="联网搜索")
    except httpx.HTTPError as e:
        raise SearchError(f"网络错误：{type(e).__name__}: {e}") from e
    if r.status_code >= 400:
        t = r.text[:300]
        if key:
            t = t.replace(key, "****")
        raise SearchError(f"HTTP {r.status_code}：{t}")
    try:
        return r.json()
    except ValueError as e:
        raise SearchError(f"返回不是 JSON：{r.text[:200]}") from e


def _site(u):
    try:
        return urlparse(u).hostname or ""
    except ValueError:
        return ""


def search(vendor, endpoint, key, query, max_results=10, time_range="week", include_domains=None, params=None, timeout=20):
    params = params or {}
    if vendor == "tavily":
        body = {"query": query, "max_results": max(1, min(int(max_results), 20)),
                "search_depth": params.get("search_depth", "basic"), "topic": params.get("topic", "general")}
        if time_range and time_range != "none":
            body["time_range"] = time_range
        if include_domains:
            body["include_domains"] = include_domains
        j = _post(endpoint, body, key, timeout)
        return [{"title": x.get("title") or "", "url": x.get("url") or "", "date": (x.get("published_date") or "")[:10] or None,
                 "snippet": (x.get("content") or "")[:500], "site": _site(x.get("url") or ""), "score": x.get("score")}
                for x in j.get("results", [])]
    if vendor == "aliyun_iqs":
        body = {"query": query[:500], "engineType": params.get("engineType", "Generic"), "timeRange": _IQS_TR.get(time_range, "NoLimit"),
                "contents": {"mainText": False, "summary": False, "rerankScore": True},
                "advancedParams": {"numResults": str(max(1, min(int(max_results), 50)))}}
        if include_domains and body["engineType"] not in ("Generic", "GenericAdvanced", "CNAuto"):
            body["advancedParams"]["includeSites"] = ",".join(include_domains[:20])
        j = _post(endpoint, body, key, timeout)
        return [{"title": x.get("title") or "", "url": x.get("link") or "", "date": (x.get("publishedTime") or "")[:10] or None,
                 "snippet": (x.get("snippet") or "")[:500], "site": x.get("hostname") or _site(x.get("link") or ""),
                 "score": x.get("rerankScore")} for x in j.get("pageItems", [])]
    raise SearchError(f"未知搜索厂商：{vendor}")
