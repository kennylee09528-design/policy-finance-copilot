"""M3 三个 Agent 的配置（管理员）与版本化提示词模板。"""
import copy

from fastapi import HTTPException

from .. import db

AGENTS = {"writer": "研究及写作 Agent", "checker": "核对 Agent", "summarizer": "总结 Agent"}
SLOT = {"writer": "m3.writer", "checker": "m3.checker", "summarizer": "m3.summarizer"}
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]

DEFAULT = {
    "writer": {"model_id": None, "temperature": 0.4, "top_p": None, "timeout": 120, "enabled": True,
               "skills": ["知识库检索", "联网检索", "大纲", "分段写作", "M5 数据占位"],
               "scope": {"levels": ["A1", "A2", "B1", "B2"], "layers": [], "kb_max": 8, "web_max": 6, "excerpt_chars": 600}},
    "checker": {"model_id": None, "temperature": 0.0, "top_p": None, "timeout": 120, "enabled": True, "auto_revise": True,
                "skills": ["规则核验(必选)", "大模型格式核对(可选)"], "scope": {"levels": LEVELS, "layers": []}},
    "summarizer": {"model_id": None, "temperature": 0.2, "top_p": None, "timeout": 90, "enabled": True,
                   "skills": ["初稿/终稿对比", "提炼写作规范"], "scope": {"max_entries": 30}},
}

PROMPTS = {
    "writer": """你是示例省级融资再担保有限公司普惠业务部的材料写作助手。
写作规则（必须遵守）：
1. 只能使用【资料清单】中的信息；每个事实性陈述（尤其金额、比例、排名、案例/机构/文件名称）句末必须标注来源编号，如 [S1]，可多个 [S1][S3]。
2. 本公司业务数据（M5 台账）只能写占位符 {{F1}}、{{F2}} …，由系统从数据库填入真实数值；严禁自行编写任何本公司业务数字。
3. 资料中没有的数字、排名、案例一律不写，不得推测。
4. 文风：{tone}；文体：{genre}；用语规范、简洁、符合公文习惯。
【本单位写作规范（由总结 Agent 从历次人工修改中沉淀）】
{style_guide}""",
    "checker": """你是材料核对员。对照【资料清单】逐句核对下列稿件，找出：数字与来源不一致、引用编号与内容不符、无来源的事实陈述、格式/用语不规范。
仅输出 JSON：{"issues":[{"text":"原句片段","problem":"问题说明","severity":"高|中|低"}]}，没有问题输出 {"issues":[]}。""",
    "summarizer": """你是写作规范提炼员。下面是 AI 初稿与人工终稿的逐处差异。请提炼可复用的写作规范（措辞偏好、结构调整、数据口径），
每条不超过 60 字，不要复述具体数字。仅输出 JSON：{"entries":[{"category":"措辞|结构|口径","content":"规范内容"}]}。""",
}


def get():
    cfg = copy.deepcopy(DEFAULT)
    saved = db.get_setting("m3_agents", {}) or {}
    for a, v in saved.items():
        if a in cfg:
            sc = {**cfg[a]["scope"], **(v.get("scope") or {})}
            cfg[a].update(v)
            cfg[a]["scope"] = sc
    return cfg


def save(body, user):
    cfg = get()
    for a, v in (body or {}).items():
        if a not in AGENTS:
            raise ValueError(f"未知 Agent：{a}")
        t = v.get("temperature", cfg[a]["temperature"])
        if t is not None and not (0 <= float(t) <= 2):
            raise ValueError("temperature 应在 0~2 之间")
        if v.get("model_id") not in (None, ""):
            from ..llm.service import check_allowed
            check_allowed(SLOT[a], int(v["model_id"]))
        for k in ("model_id", "temperature", "top_p", "timeout", "enabled", "skills", "auto_revise"):
            if k in v:
                cfg[a][k] = (int(v[k]) if v[k] not in (None, "") else None) if k == "model_id" else v[k]
        if "scope" in v:
            sc = v["scope"]
            if "levels" in sc and any(x not in LEVELS for x in sc["levels"]):
                raise ValueError("知识范围来源等级无效")
            cfg[a]["scope"].update(sc)
    db.set_setting("m3_agents", cfg)
    db.audit(user, "M3", "修改 Agent 配置", "", {a: {k: cfg[a][k] for k in ("model_id", "temperature")} for a in cfg})
    return cfg


def model_of(agent):
    from ..llm.service import assignments
    return get()[agent].get("model_id") or assignments().get(SLOT[agent])


# ---------- 版本化提示词 ----------
def _seed():
    for a, txt in PROMPTS.items():
        if not db.q1("SELECT id FROM m3_prompts WHERE agent=?", (a,)):
            db.execute("INSERT INTO m3_prompts(agent,version,content,note,active,created_by,created_at) VALUES(?,?,?,?,1,?,?)",
                       (a, 1, txt, "系统默认模板", "系统", db.now()))


def prompts(agent=None):
    _seed()
    if agent:
        return db.q("SELECT * FROM m3_prompts WHERE agent=? ORDER BY version DESC", (agent,))
    return db.q("SELECT * FROM m3_prompts ORDER BY agent, version DESC")


def active_prompt(agent):
    _seed()
    r = db.q1("SELECT * FROM m3_prompts WHERE agent=? AND active=1 ORDER BY version DESC LIMIT 1", (agent,))
    return r or {"version": 0, "content": PROMPTS[agent]}


def new_prompt(agent, content, note, user, activate=True):
    if agent not in AGENTS or not (content or "").strip():
        raise HTTPException(400, "Agent 或模板内容无效")
    _seed()
    v = db.q1("SELECT MAX(version) v FROM m3_prompts WHERE agent=?", (agent,))["v"] or 0
    pid = db.execute("INSERT INTO m3_prompts(agent,version,content,note,active,created_by,created_at) VALUES(?,?,?,?,0,?,?)",
                     (agent, v + 1, content, note or "", user["name"], db.now()))
    if activate:
        activate_prompt(pid, user)
    db.audit(user, "M3", "新建提示词版本", agent, {"version": v + 1})
    return pid


def activate_prompt(pid, user):
    p = db.q1("SELECT * FROM m3_prompts WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "模板不存在")
    db.execute("UPDATE m3_prompts SET active=CASE WHEN id=? THEN 1 ELSE 0 END WHERE agent=?", (pid, p["agent"]))
    db.audit(user, "M3", "启用提示词版本", p["agent"], {"version": p["version"]})
