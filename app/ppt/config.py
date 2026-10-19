"""PPT Agent 配置：默认模型/温度、各类演示稿的版本化提示词模板、默认需求单与默认问题。"""
from fastapi import HTTPException

from .. import db
from .data import DECKS

DEFAULT = {"model_id": None, "temperature": 0.3, "top_p": None, "timeout": 120, "max_pages": 30}

BASE_RULES = """你是示例省级融资再担保有限公司普惠业务部的 PPT 策划助手，只负责演示稿的结构、标题与要点文字。
铁律：
1. 严禁写任何阿拉伯数字（金额、比例、排名、日期、页数都不行）。需要数据时，只能引用数据块编号：指标写 {{F1}} 这样的占位符（系统会填入数据库数值），图表/表格/文字块用页面的 data 字段引用编号（如 C1、T2、X1）。
2. 不得编造政策、机构、案例；要点必须基于给定资料。
3. 标题简洁（不超过 20 字），每页要点 3~5 条，每条不超过 40 字，公文风格。"""

PROMPTS = {
    "usage": BASE_RULES + "\n本稿类型：额度使用情况汇报（周报/月报），面向领导汇报国担额度使用进度、分机构进度、预警与环比变化。",
    "scheme": BASE_RULES + "\n本稿类型：授信方案上会材料，需讲清测算依据与系数规则、三步调整结果、人工调整及原因，并列出提请审议事项。",
    "policy": BASE_RULES + "\n本稿类型：政策简报/月度政策汇编，按 ★★★/★★/★ 分档组织，每条注明来源等级与链接（表格由系统生成）。",
    "research": BASE_RULES + "\n本稿类型：研究报告配套演示稿，按报告大纲生成议程，每章 3~5 条要点，引用来源登记表作为附录。",
}

DEFAULT_SHEET = {
    "usage": {"audience": "部门领导 / 公司经营层", "purpose": "汇报国担额度使用进度，提示预警机构，提出下一步推进建议", "pages": 12,
              "style": "稳重商务（工作台深红主题）", "tone": "正式、简洁", "period": "周报", "emphasis": "使用率偏低机构与预警事项"},
    "scheme": {"audience": "公司总经理办公会 / 党委会", "purpose": "提请审议 2026 年合作担保机构授信方案", "pages": 12,
               "style": "稳重商务（工作台深红主题）", "tone": "正式、严谨", "emphasis": "人工调整的依据与原因"},
    "policy": {"audience": "普惠业务部全体人员", "purpose": "汇总近期重要政策动态，便于学习与业务对接", "pages": 10,
               "style": "稳重商务（工作台深红主题）", "tone": "简洁、信息密度高", "emphasis": "★★★ 今日必读条目"},
    "research": {"audience": "公司领导及相关部门", "purpose": "配合研究报告进行汇报讲解", "pages": 10,
                 "style": "稳重商务（工作台深红主题）", "tone": "正式、条理清晰", "emphasis": "主要结论与建议"},
}

DEFAULT_QUESTIONS = {
    "usage": ["本次汇报对象是谁？是否需要突出某几家机构？", "是周报还是月报？是否需要展示环比变化？", "分机构明细展示全部机构，还是只展示预警/重点机构？", "页数希望控制在多少页以内？"],
    "scheme": ["上会场合与审议对象是什么？", "人工调整是否需要逐家列明原因？", "是否需要附系数规则说明页？", "需要提请审议的具体事项有哪些？"],
    "policy": ["汇编的读者是谁？是否需要包含 ★ 浏览级条目？", "需要按类别还是按档位组织？", "是否需要附数据速览？"],
    "research": ["演示场合与听众是谁？时长大约多少？", "哪些章节需要重点展开？", "是否需要附引用来源登记表？"],
}


def get():
    return {**DEFAULT, **(db.get_setting("ppt_config", {}) or {})}


def save(body, user):
    cfg = get()
    for k in DEFAULT:
        if k in body:
            cfg[k] = body[k]
    if cfg.get("model_id") not in (None, ""):
        from ..llm.service import check_allowed
        check_allowed("ppt.agent", int(cfg["model_id"]))
        cfg["model_id"] = int(cfg["model_id"])
    else:
        cfg["model_id"] = None
    t = cfg.get("temperature")
    if t is not None and not (0 <= float(t) <= 2):
        raise HTTPException(400, "temperature 应在 0~2 之间")
    db.set_setting("ppt_config", cfg)
    db.audit(user, "PPT", "修改 PPT Agent 配置", "", {k: cfg[k] for k in ("model_id", "temperature")})
    return cfg


def _seed():
    for k, txt in PROMPTS.items():
        if not db.q1("SELECT id FROM ppt_prompts WHERE deck_type=?", (k,)):
            db.execute("INSERT INTO ppt_prompts(deck_type,version,content,note,active,created_by,created_at) VALUES(?,?,?,?,1,?,?)",
                       (k, 1, txt, "系统默认模板", "系统", db.now()))


def prompts(deck_type=None):
    _seed()
    if deck_type:
        return db.q("SELECT * FROM ppt_prompts WHERE deck_type=? ORDER BY version DESC", (deck_type,))
    return db.q("SELECT * FROM ppt_prompts ORDER BY deck_type, version DESC")


def active_prompt(deck_type):
    _seed()
    return db.q1("SELECT * FROM ppt_prompts WHERE deck_type=? AND active=1 ORDER BY version DESC LIMIT 1", (deck_type,)) or {"version": 0, "content": PROMPTS[deck_type]}


def new_prompt(deck_type, content, note, user):
    if deck_type not in DECKS or not (content or "").strip():
        raise HTTPException(400, "类型或模板内容无效")
    _seed()
    v = db.q1("SELECT MAX(version) v FROM ppt_prompts WHERE deck_type=?", (deck_type,))["v"] or 0
    pid = db.execute("INSERT INTO ppt_prompts(deck_type,version,content,note,active,created_by,created_at) VALUES(?,?,?,?,0,?,?)",
                     (deck_type, v + 1, content, note or "", user["name"], db.now()))
    activate_prompt(pid, user)
    return pid


def activate_prompt(pid, user):
    p = db.q1("SELECT * FROM ppt_prompts WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "模板不存在")
    db.execute("UPDATE ppt_prompts SET active=CASE WHEN id=? THEN 1 ELSE 0 END WHERE deck_type=?", (pid, p["deck_type"]))
    db.audit(user, "PPT", "启用提示词版本", p["deck_type"], {"version": p["version"]})
