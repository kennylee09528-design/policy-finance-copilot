SEARCH_PRESETS = [
    {"vendor": "tavily", "name": "Tavily Search", "endpoint": "https://api.tavily.com/search",
     "params": {"search_depth": "basic", "topic": "general"},
     "hint": "app.tavily.com 创建 API Key（tvly-...）。请求：POST /search，Authorization: Bearer。topic=news 时返回发布日期。"},
    {"vendor": "aliyun_iqs", "name": "阿里云 IQS 通义晓搜（UnifiedSearch）", "endpoint": "https://cloud-iqs.aliyuncs.com/search/unified",
     "params": {"engineType": "Generic"},
     "hint": "IQS 控制台 → API Key 创建（约 5 分钟生效）。engineType 可选 Generic / GenericAdvanced / CNLiteBasic / CNAuto / GlobalAdvanced；站点限定仅 CNLiteBasic 等支持。服务端超时 5 秒。"},
]
SEARCH_PRESET_MAP = {p["vendor"]: p for p in SEARCH_PRESETS}
