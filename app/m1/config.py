"""M1 采集配置（管理员可在页面编辑，存 settings.m1_config）。以下为默认值。"""
import copy

from .. import db

PROVINCES = ["北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东",
             "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"]
SPECIAL_CITIES = ["深圳", "宁波", "青岛", "大连", "厦门"]
GD_CITIES = ["广州", "珠海", "汕头", "佛山", "韶关", "河源", "梅州", "惠州", "汕尾", "东莞", "中山", "江门", "阳江", "湛江", "茂名",
             "肇庆", "清远", "潮州", "揭阳", "云浮"]  # 深圳归入重点特殊财政管理城市

OFFICIAL = "官方(A1/A2)"  # 按 URL 路径自动区分：命中正式文件路径 → A1，否则 A2

DEFAULT = {
    "template": "{region} {topic}",
    "topics": ["政府性融资担保 政策", "再担保 业务", "融资担保 风险补偿", "担保费 补贴 贴息", "国家融资担保基金 合作",
               "普惠金融 小微企业 融资担保", "科技金融 担保", "民间投资 专项担保", "银担合作 分险", "融资担保 代偿补偿"],
    "tiers": [
        {"name": "国家", "layer": "国家", "regions": ["全国"], "every_run": True},
        {"name": "广东本省", "layer": "省级", "regions": ["广东"], "every_run": True},
        {"name": "广东地市", "layer": "普通地市", "regions": GD_CITIES, "every_run": False},
        {"name": "重点特殊财政管理城市", "layer": "重点特殊财政管理城市", "regions": SPECIAL_CITIES, "every_run": False},
        {"name": "其他省级行政区", "layer": "省级", "regions": [p for p in PROVINCES if p != "广东"], "every_run": False},
    ],
    "max_queries_per_run": 60,       # 手动采集每轮最多检索次数（成本控制）；“每轮必扫”层级优先，其余轮转
    "max_queries_scheduled_per_day": 5,  # 定时采集每日硬上限（与手动分开；按主题加权轮转）
    "results_per_query": 8,
    "time_range": "week",            # day / week / month / year / none
    "keep_levels": ["A1", "A2", "B1"],
    "a1_path_regex": r"(zcfg|zcwj|zhengce|xxgk|zwgk|gkml|gongbao|tzgg|wjfb|fgwj|zfwj|zcjd_wj|\.pdf$)",
    "fetch_content": True,
    "ai_summary_per_run": 20,        # 每轮最多 AI 摘要条数（需在 M1 页面选择模型）
    "schedule": {"enabled": False, "times": ["07:00"]},
    "rules": [
        {"domain": "mp.weixin.qq.com", "path_regex": "", "publisher": "微信公众号", "level": "C1", "layer": ""},
        {"domain": "qq.com", "path_regex": "", "publisher": "腾讯新闻", "level": "B2", "layer": ""},
        {"domain": "www.gov.cn", "path_regex": "", "publisher": "中国政府网（国务院）", "level": OFFICIAL, "layer": "国家"},
        {"domain": "mof.gov.cn", "path_regex": "", "publisher": "财政部", "level": OFFICIAL, "layer": "国家"},
        {"domain": "pbc.gov.cn", "path_regex": "", "publisher": "中国人民银行", "level": OFFICIAL, "layer": "国家"},
        {"domain": "nfra.gov.cn", "path_regex": "", "publisher": "国家金融监督管理总局", "level": OFFICIAL, "layer": "国家"},
        {"domain": "ndrc.gov.cn", "path_regex": "", "publisher": "国家发展改革委", "level": OFFICIAL, "layer": "国家"},
        {"domain": "miit.gov.cn", "path_regex": "", "publisher": "工业和信息化部", "level": OFFICIAL, "layer": "国家"},
        {"domain": "most.gov.cn", "path_regex": "", "publisher": "科学技术部", "level": OFFICIAL, "layer": "国家"},
        {"domain": "mohrss.gov.cn", "path_regex": "", "publisher": "人力资源和社会保障部", "level": OFFICIAL, "layer": "国家"},
        {"domain": "moa.gov.cn", "path_regex": "", "publisher": "农业农村部", "level": OFFICIAL, "layer": "国家"},
        {"domain": "czt.gd.gov.cn", "path_regex": "", "publisher": "广东省财政厅", "level": OFFICIAL, "layer": "省级"},
        {"domain": "jrjgj.gd.gov.cn", "path_regex": "", "publisher": "广东省地方金融管理局", "level": OFFICIAL, "layer": "省级"},
        {"domain": "gd.gov.cn", "path_regex": "", "publisher": "广东省人民政府及部门", "level": OFFICIAL, "layer": "省级"},
        {"domain": "gov.cn", "path_regex": "", "publisher": "政府网站", "level": OFFICIAL, "layer": ""},
        {"domain": "news.cn", "path_regex": "", "publisher": "新华社（新华网）", "level": "B1", "layer": ""},
        {"domain": "xinhuanet.com", "path_regex": "", "publisher": "新华社（新华网）", "level": "B1", "layer": ""},
        {"domain": "people.com.cn", "path_regex": "", "publisher": "人民日报（人民网）", "level": "B1", "layer": ""},
        {"domain": "ce.cn", "path_regex": "", "publisher": "经济日报（中国经济网）", "level": "B1", "layer": ""},
        {"domain": "financialnews.com.cn", "path_regex": "", "publisher": "金融时报（中国金融新闻网）", "level": "B1", "layer": ""},
        {"domain": "stcn.com", "path_regex": "", "publisher": "证券时报", "level": "B1", "layer": ""},
        {"domain": "yicai.com", "path_regex": "", "publisher": "第一财经", "level": "B1", "layer": ""},
        {"domain": "21jingji.com", "path_regex": "", "publisher": "21世纪经济报道", "level": "B1", "layer": ""},
        {"domain": "cctv.com", "path_regex": "", "publisher": "央视网", "level": "B1", "layer": ""},
    ],
}
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


def get():
    cfg = copy.deepcopy(DEFAULT)
    cfg.update(db.get_setting("m1_config", {}) or {})
    return cfg


def save(cfg, user):
    import re
    out = get()
    for k in DEFAULT:
        if k in cfg:
            out[k] = cfg[k]
    if "{topic}" not in out["template"]:
        raise ValueError("查询模板必须包含 {topic}")
    for r in out["rules"]:
        r["domain"] = (r.get("domain") or "").strip().lower().lstrip("*.")
        if not r["domain"] or (r.get("level") not in LEVELS + [OFFICIAL]):
            raise ValueError(f"规则无效：{r}")
        if r.get("path_regex"):
            re.compile(r["path_regex"])
    re.compile(out["a1_path_regex"])
    times = out.get("schedule", {}).get("times", [])
    if not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t) for t in times):
        raise ValueError("定时时间格式应为 HH:MM，如 07:00")
    out["keep_levels"] = [x for x in out["keep_levels"] if x in LEVELS]
    out["max_queries_per_run"] = max(1, min(int(out["max_queries_per_run"]), 2000))
    out["max_queries_scheduled_per_day"] = max(1, min(int(out.get("max_queries_scheduled_per_day", 5)), 200))
    out["results_per_query"] = max(1, min(int(out["results_per_query"]), 20))
    db.set_setting("m1_config", out)
    db.audit(user, "M1", "修改采集配置", "", {"rules": len(out["rules"]), "topics": len(out["topics"]),
                                              "max_q": out["max_queries_per_run"],
                                              "sched_max_q": out["max_queries_scheduled_per_day"]})
    return out
