import copy

from .. import db

DEFAULT = {
    "window_hours": 24,                       # 取 M1 最近 N 小时采集的条目
    "weights": {"level": 0.30, "layer": 0.25, "relevance": 0.30, "timeliness": 0.15},
    "level_scores": {"A1": 100, "A2": 85, "B1": 70, "B2": 60, "C1": 45, "C2": 25},
    "layer_scores": {"国家": 100, "广东本省": 95, "其他省级": 80, "重点城市": 70, "地市": 55, "其他": 50},
    "keywords": {"融资担保": 40, "再担保": 40, "政府性融资担保": 40, "国家融资担保基金": 40, "国担基金": 40, "风险补偿": 35,
                 "贴息": 30, "担保费补贴": 30, "银担": 30, "分险": 25, "代偿": 25, "普惠金融": 20, "小微企业": 15,
                 "科技金融": 15, "民间投资": 15, "专精特新": 10, "三农": 10},
    "timeliness": [{"days": 1, "score": 100}, {"days": 3, "score": 70}, {"days": 7, "score": 40}],
    "timeliness_older": 10,
    "tiers": {"three": 80, "two": 60},
    "max_items": 40,
    "max_pub_age_days": 30,                   # 窗口内新采集但发布日期早于 N 天的（存量政策回填）不作为「今日」动态，仍在 M1 知识库可查
    "require_pub_date": True,                 # 发布日期未知的条目（多为存量文件）不作为今日动态
    "fallback_days": [3, 7, 14, 30],          # 窗口内条目不足 min_items 时，按发布日期依次扩展到近 N 天，并在简报中标注
    "min_items": 3,
    "include_m5": True,                       # 「数据速览」取 M5 最新快照（数值直接取库）
    "use_llm": True,                          # 选择了 M2 模型时，用模型提炼要点；否则抽取式
    "schedule": {"enabled": True, "time": "07:30"},
}


def get():
    cfg = copy.deepcopy(DEFAULT)
    cfg.update(db.get_setting("m2_config", {}) or {})
    return cfg


def save(body, user):
    import re
    cfg = get()
    for k in DEFAULT:
        if k in body:
            cfg[k] = body[k]
    w = cfg["weights"]
    if set(w) != {"level", "layer", "relevance", "timeliness"} or abs(sum(float(x) for x in w.values()) - 1) > 1e-6:
        raise ValueError("四项权重之和必须等于 1")
    if not (0 < float(cfg["tiers"]["two"]) < float(cfg["tiers"]["three"]) <= 100):
        raise ValueError("分档阈值须满足 0 < ★★ < ★★★ ≤ 100")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", cfg["schedule"]["time"]):
        raise ValueError("定时时间格式应为 HH:MM")
    cfg["window_hours"] = max(1, min(int(cfg["window_hours"]), 24 * 14))
    db.set_setting("m2_config", cfg)
    db.audit(user, "M2", "修改简报规则", "", {"weights": w, "tiers": cfg["tiers"]})
    return cfg
