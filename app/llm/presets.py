"""厂商预设：只是表单默认值，管理员可任意修改 base_url / 模型 ID。
模型 ID 以各厂商控制台为准（厂商会不定期更新型号），此处仅为常用示例。"""

PRESETS = [
    {"vendor": "company_private", "name": "公司私有模型（自有算力云）", "base_url": "", "is_private": True,
     "models": [], "allow_sensitive": True,
     "hint": "公司自有算力云上部署的模型，需提供 OpenAI 兼容接口（/v1/chat/completions）。填写内网/专线地址、Key 与模型 ID；默认允许处理敏感模块（M4/M5）数据。"},
    {"vendor": "deepseek", "name": "DeepSeek 深度求索", "base_url": "https://api.deepseek.com/v1",
     "models": ["deepseek-chat", "deepseek-reasoner"], "hint": "控制台：platform.deepseek.com"},
    {"vendor": "dashscope", "name": "通义千问（阿里云百炼）", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "models": ["qwen-plus", "qwen-max", "qwen-turbo"], "hint": "百炼控制台创建 API-Key；使用 compatible-mode 兼容接口"},
    {"vendor": "hunyuan", "name": "腾讯混元", "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
     "models": ["hunyuan-turbos-latest", "hunyuan-lite"], "hint": "腾讯云混元控制台创建 API Key（OpenAI 兼容接口）"},
    {"vendor": "zhipu", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "models": ["glm-4-plus", "glm-4-flash"], "hint": "open.bigmodel.cn 创建 API Key"},
    {"vendor": "ark", "name": "豆包（火山方舟）", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
     "models": [], "hint": "模型 ID 填写方舟控制台的推理接入点 ID（ep-xxxx）或模型名称"},
    {"vendor": "moonshot", "name": "Kimi（月之暗面）", "base_url": "https://api.moonshot.cn/v1",
     "models": ["moonshot-v1-8k", "moonshot-v1-32k"], "hint": "platform.moonshot.cn 创建 API Key"},
    {"vendor": "qianfan", "name": "文心一言（百度千帆）", "base_url": "https://qianfan.baidubce.com/v2",
     "models": ["ernie-4.0-turbo-8k", "ernie-speed-128k"], "hint": "千帆 ModelBuilder 创建 API Key（v2 OpenAI 兼容接口）"},
    # MiniMax（2026-10 核对官方文档 platform.minimaxi.com / platform.minimax.io「OpenAI SDK」页）：
    # 国内账号用 api.minimaxi.com（注意多一个 i），海外账号用 api.minimax.io；两者 Key 不通用。
    # 怪癖（client.py 自动处理）：M2.x/M3 思考内容默认以 <think>…</think> 混在 content 中 → 发送 reasoning_split=true 并剥离；
    # temperature 范围 [0,2]、top_p [0,1]，越界报错 → 自动夹紧；思考 token 计入 max_tokens，过小会返回空内容 → 改用 max_completion_tokens 并设下限。
    {"vendor": "minimax", "name": "MiniMax（国内）", "base_url": "https://api.minimaxi.com/v1",
     "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5", "MiniMax-M2.5-highspeed", "MiniMax-M2.1", "MiniMax-M2"],
     "hint": "国内站 platform.minimaxi.com 创建 API Key；base_url 为 api.minimaxi.com/v1。推理模型思考内容会自动剥离，温度建议 1.0（范围 0~2）"},
    {"vendor": "minimax_intl", "name": "MiniMax（国际）", "base_url": "https://api.minimax.io/v1",
     "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5", "MiniMax-M2.5-highspeed", "MiniMax-M2.1", "MiniMax-M2"],
     "hint": "国际站 platform.minimax.io 创建 API Key（与国内站 Key 不通用）；数据出境，请勿用于敏感模块"},
    # MiniMax 包月 Token Plan（2026-10 核对 platform.minimaxi.com/docs/token-plan/*）：使用「订阅 Key」（sk-cp-…，订阅管理 > Token Plan），
    # 与按量计费 API Key 不互通；官方推荐 Anthropic 兼容 https://api.minimax.cn/anthropic（也可用 OpenAI 兼容 https://api.minimax.cn/v1）。
    # 官方 FAQ：面向个人开发者交互式使用，生产环境建议按量付费；5 小时固定窗口 + 周窗口额度、RPM/TPM 限流，高峰期动态收紧。
    {"vendor": "minimax_token_plan", "name": "MiniMax（包月 Token Plan）", "base_url": "https://api.minimax.cn/anthropic",
     "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"],
     "hint": "填「订阅 Key」（sk-cp- 开头，订阅管理 > Token Plan 查看），不是按量计费 API Key。默认走 Anthropic 兼容协议（base_url 以 /anthropic 结尾即自动切换）；"
             "也可改为 https://api.minimax.cn/v1 走 OpenAI 兼容。官方定位个人交互式使用、生产建议按量付费；受 5 小时/周额度窗口与限流约束，额度用尽返回 429。"
             "M Plan 用户模型填 MiniMax-M3.1-Flash-Preview。"},
    {"vendor": "anthropic_compatible", "name": "通用 Anthropic 兼容接口", "base_url": "", "models": [],
     "hint": "任意兼容 Anthropic Messages（{base_url}/v1/messages）的服务；base_url 须以 /anthropic 结尾，或按服务商文档填写"},
    {"vendor": "openai_compatible", "name": "通用 OpenAI 兼容接口", "base_url": "", "models": [],
     "hint": "任意兼容 /v1/chat/completions 的服务"},
]
PRESET_MAP = {p["vendor"]: p for p in PRESETS}

# 敏感模块（需求第 10 章：机构授信、额度使用数据不得发往未授权模型）
SENSITIVE_MODULES = {"m4", "m5"}
# 各模块可配置的 AI 环节
SLOTS = {
    "m1.extract": {"module": "m1", "name": "M1 采集条目要点摘要/抽取"},
    "m1.embed": {"module": "m1", "name": "M1 语义检索向量模型（Embedding，可选）"},
    "m2.brief": {"module": "m2", "name": "M2 今日行业 Brief · 简报生成"},
    "m3.writer": {"module": "m3", "name": "M3 研究及写作 Agent"},
    "m3.checker": {"module": "m3", "name": "M3 核对 Agent"},
    "m3.summarizer": {"module": "m3", "name": "M3 总结 Agent"},
    "m5.notes": {"module": "m5", "name": "M5 环比说明润色（敏感）"},
    "ppt.agent": {"module": "ppt", "name": "PPT 生成 Agent（需求确认 / 大纲）"},
    "bot.agent": {"module": "feishu", "name": "微信/飞书机器人 · 智能问答（路由 + 一般知识/联网兜底，不接触系统数据）"},
    "bot.agent_sensitive": {"module": "m5", "name": "微信/飞书机器人 · 智能问答（涉额度/机构问题，须已授权敏感数据模型）"},
    "feishu.router": {"module": "feishu", "name": "飞书机器人 · 意图识别（只理解提问，不接触任何业务数据）"},
}
