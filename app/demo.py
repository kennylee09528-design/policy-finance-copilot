"""演示数据包：管理员一键加载 / 一键清除。

加载的每一行都记录在 settings.demo_data 中，清除时只删除这些行（及其子表、文件），不影响真实业务数据。
M1 条目为演示用政策摘要（标注「演示数据」，链接指向发布机构官网首页），不代表真实文件原文。"""
import os
import shutil
from datetime import datetime, timedelta

from fastapi import HTTPException

from . import db

TAG = "演示数据"
# (标题, 发布方, 官网, 等级, 层级, 地域, 采集于几天前, 正文, 要点)
ITEMS = [
    ("关于有效发挥政府性融资担保基金作用切实支持小微企业和“三农”发展的指导意见（解读）", "国务院办公厅", "https://www.gov.cn/", "A1", "国家", "全国", 0,
     "政府性融资担保机构要聚焦支小支农主业，坚守准公共定位，逐步将平均担保费率降至1%以下。国家融资担保基金对再担保业务实行比例分险，原则上代偿补偿比例不低于20%。",
     ["聚焦支小支农主业，坚守准公共定位", "平均担保费率逐步降至1%以下", "国家融资担保基金代偿补偿比例原则上不低于20%"]),
    ("财政部 关于继续实施小微企业融资担保降费奖补政策的通知（摘要）", "财政部", "https://www.mof.gov.cn/", "A1", "国家", "全国", 0,
     "中央财政继续安排资金支持扩大小微企业融资担保业务规模、降低融资担保费率。奖补资金向担保费率不高于1%的地区倾斜。",
     ["继续安排资金支持扩大小微企业融资担保业务规模", "奖补资金向担保费率不高于1%的地区倾斜"]),
    ("国家融资担保基金 推进“总对总”批量担保业务扩面增量（摘要）", "国家融资担保基金", "https://www.gjrdjj.com/", "A1", "国家", "全国", 0,
     "国家融资担保基金联合银行推进“总对总”批量担保合作，对单户1000万元以下小微企业贷款实行银担分险，银行分险比例不低于20%。",
     ["推进“总对总”批量担保合作", "单户1000万元以下小微企业贷款实行银担分险", "银行分险比例不低于20%"]),
    ("广东省财政厅 关于完善政府性融资担保风险补偿机制的通知（摘要）", "广东省财政厅", "https://czt.gd.gov.cn/", "B1", "省级", "广东", 0,
     "省级财政对符合条件的政府性融资担保机构代偿损失给予风险补偿，补偿比例最高不超过代偿额的30%。",
     ["对代偿损失给予省级风险补偿", "补偿比例最高不超过代偿额的30%"]),
    ("广东省地方金融管理局 召开全省普惠金融推进会（摘要）", "广东省地方金融管理局", "https://jrjgj.gd.gov.cn/", "B1", "省级", "广东", 0,
     "会议要求各地持续深化政银担合作，扩大首贷、信用贷投放，推动融资担保服务向县域延伸。",
     ["持续深化政银担合作", "扩大首贷、信用贷投放", "推动融资担保服务向县域延伸"]),
    ("示例外省担保集团甲 推出科技型企业“创新担”专属产品（摘要）", "示例外省担保集团甲", "https://www.zjdb.com.cn/", "B2", "省级", "浙江", 0,
     "示例外省担保集团甲面向科技型中小企业推出专属担保产品，单户担保额度最高2000万元，担保费率0.5%。",
     ["面向科技型中小企业推出专属担保产品", "单户担保额度最高2000万元，担保费率0.5%"]),
    ("深圳市 中小企业融资担保业务降费工作推进情况（摘要）", "深圳市地方金融管理局", "https://jr.sz.gov.cn/", "B2", "重点特殊财政管理城市", "深圳", 0,
     "深圳市推动政府性融资担保机构降低担保费率，支持专精特新企业融资。", ["推动政府性融资担保机构降费", "支持专精特新企业融资"]),
    ("汕头市 举办银担企融资对接会（摘要）", "汕头市金融工作局", "https://www.shantou.gov.cn/", "C2", "普通地市", "汕头", 0,
     "活动邀请银行、担保机构与企业现场对接，签约项目若干。", []),
    ("国务院常务会议 部署加大对民间投资支持力度（摘要）", "国务院", "https://www.gov.cn/", "A1", "国家", "全国", 1,
     "会议提出发挥政府性融资担保作用，支持民间投资项目融资，鼓励金融机构扩大中长期贷款投放。",
     ["发挥政府性融资担保作用支持民间投资", "鼓励扩大中长期贷款投放"]),
    ("工业和信息化部 关于加强专精特新中小企业融资服务的通知（摘要）", "工业和信息化部", "https://www.miit.gov.cn/", "A1", "国家", "全国", 1,
     "推动政府性融资担保机构为专精特新中小企业提供增信服务，鼓励开发知识产权质押担保产品。",
     ["为专精特新中小企业提供增信服务", "开发知识产权质押担保产品"]),
    ("广东省 民营经济高质量发展若干措施（融资担保部分摘要）", "广东省人民政府", "https://www.gd.gov.cn/", "B1", "省级", "广东", 1,
     "加大政府性融资担保对民营企业支持力度，对民间投资项目贷款担保给予费率优惠。", ["加大对民营企业支持力度", "民间投资项目贷款担保费率优惠"]),
    ("示例外省再担保集团乙 推进“苏科贷”扩面（摘要）", "示例外省再担保集团乙", "https://www.jscgc.com.cn/", "B2", "省级", "江苏", 1,
     "示例外省再担保集团乙联合合作银行推进科技贷款扩面，重点支持首贷企业。", ["推进科技贷款扩面", "重点支持首贷企业"]),
    ("东莞市 政府性融资担保机构服务制造业企业情况（摘要）", "东莞市金融工作局", "https://www.dg.gov.cn/", "C1", "普通地市", "东莞", 1,
     "东莞推动政府性融资担保支持制造业企业技术改造。", []),
    ("农业农村部 关于做好农业信贷担保服务工作的通知（摘要）", "农业农村部", "https://www.moa.gov.cn/", "A1", "国家", "全国", 2,
     "全国农担体系聚焦适度规模经营主体，单户担保额度原则上不超过1000万元，不得收取保证金。",
     ["聚焦适度规模经营主体", "单户担保额度原则上不超过1000万元", "不得收取保证金"]),
    ("中国人民银行广东省分行 普惠小微贷款投放情况通报（摘要）", "中国人民银行广东省分行", "https://guangzhou.pbc.gov.cn/", "B1", "省级", "广东", 2,
     "全省普惠小微贷款保持较快增长，信用贷款占比持续提升。", ["普惠小微贷款保持较快增长", "信用贷款占比持续提升"]),
    ("四川省 政府性融资担保体系建设推进会（摘要）", "四川省财政厅", "https://czt.sc.gov.cn/", "B2", "省级", "四川", 2,
     "四川推进省市县三级政府性融资担保体系建设，强化再担保分险功能。", ["推进三级体系建设", "强化再担保分险功能"]),
    ("广州市 科技型中小企业信贷风险补偿资金池扩容（摘要）", "广州市科学技术局", "https://kjj.gz.gov.cn/", "C1", "普通地市", "广州", 2,
     "广州市扩大科技信贷风险补偿资金池规模，引导银行和担保机构加大支持。", ["扩大科技信贷风险补偿资金池", "引导银行和担保机构加大支持"]),
    ("财政部 普惠金融发展专项资金管理办法（修订摘要）", "财政部", "https://www.mof.gov.cn/", "A1", "国家", "全国", 3,
     "专项资金用于支持普惠金融发展，包括创业担保贷款贴息、融资担保业务降费奖补等方向。",
     ["专项资金支持创业担保贷款贴息", "支持融资担保业务降费奖补"]),
    ("人力资源社会保障部 创业担保贷款政策落实情况（摘要）", "人力资源社会保障部", "https://www.mohrss.gov.cn/", "A2", "国家", "全国", 3,
     "各地加大创业担保贷款发放力度，个人创业担保贷款额度最高30万元。", ["加大创业担保贷款发放力度", "个人创业担保贷款额度最高30万元"]),
    ("示例省级融资再担保有限公司 召开合作机构业务推进会（摘要）", "示例省级融资再担保有限公司", "https://www.example.com/", "B1", "省级", "广东", 3,
     "会议通报合作担保机构授信额度使用进度，部署四季度业务推进与风险防控工作。", ["通报授信额度使用进度", "部署四季度业务推进与风险防控"]),
    ("山东省 政府性融资担保机构绩效评价办法（摘要）", "山东省财政厅", "https://czt.shandong.gov.cn/", "B2", "省级", "山东", 3,
     "山东省将支小支农业务占比、担保费率等纳入政府性融资担保机构绩效评价。", ["支小支农业务占比纳入绩效评价", "担保费率纳入绩效评价"]),
    ("国家金融监督管理总局 关于做好小微企业金融服务的通知（摘要）", "国家金融监督管理总局", "https://www.nfra.gov.cn/", "A1", "国家", "全国", 4,
     "推动银行业金融机构与政府性融资担保机构加强合作，提高小微企业首贷率和信用贷款比重。",
     ["加强银担合作", "提高小微企业首贷率和信用贷款比重"]),
    ("佛山市 政银担合作风险分担机制运行情况（摘要）", "佛山市金融工作局", "https://www.foshan.gov.cn/", "C1", "普通地市", "佛山", 4,
     "佛山市政银担合作按约定比例分担风险，支持本地小微企业融资。", []),
    ("湖南省 融资担保代偿补偿资金管理办法（摘要）", "湖南省财政厅", "https://czt.hunan.gov.cn/", "B2", "省级", "湖南", 5,
     "湖南省设立代偿补偿资金，对政府性融资担保机构支小支农业务代偿给予补偿。", ["设立代偿补偿资金", "支小支农业务代偿给予补偿"]),
    ("广东省 关于金融支持“百县千镇万村高质量发展工程”的意见（摘要）", "广东省人民政府办公厅", "https://www.gd.gov.cn/", "B1", "省级", "广东", 5,
     "发挥政府性融资担保作用，支持县域特色产业和乡村振兴项目融资。", ["支持县域特色产业融资", "支持乡村振兴项目融资"]),
    ("某自媒体 转载：政府性融资担保降费政策解读", "某财经自媒体", "https://www.example.com/", "C2", "其他", "全国", 5,
     "转载解读文章称担保费率将降至0.3%，原文未注明出处。", ["担保费率将降至0.3%"]),
    ("国务院办公厅 指导意见解读（转载）", "某门户网站", "https://news.example.com/", "C2", "国家", "全国", 6,
     "转载：政府性融资担保机构要聚焦支小支农主业，坚守准公共定位。", ["聚焦支小支农主业"]),
    ("福建省 小微企业融资担保增信基金运行情况（摘要）", "福建省财政厅", "https://czt.fujian.gov.cn/", "B2", "省级", "福建", 6,
     "福建省增信基金为小微企业贷款提供增信支持，扩大担保业务覆盖面。", ["为小微企业贷款提供增信支持"]),
]

DEMO_M3_TITLE = "政府性融资担保代偿补偿与银担合作情况研究（演示）"


def _ids(tbl):
    return {r["id"] for r in db.q(f"SELECT id FROM {tbl}")}


def status():
    d = db.get_setting("demo_data", {}) or {}
    return {"loaded": bool(d), "loaded_at": d.get("loaded_at"), "counts": {k: len(v) for k, v in d.items() if isinstance(v, list)}}


def load(user):
    if db.get_setting("demo_data"):
        raise HTTPException(409, "演示数据已加载；如需重新加载请先清除")
    track = {"loaded_at": db.now()}
    before = {t: _ids(t) for t in ("m4_datasets", "m4_params", "m4_schemes", "m5_limit_sets", "m5_snapshots")}
    from .config import M4_SAMPLE, M5_SAMPLE_DIR, M5_SUMMARY_SAMPLE
    if not db.q1("SELECT id FROM m4_schemes"):
        from .m4 import service as M4
        M4.import_dataset(M4_SAMPLE.read_bytes(), M4_SAMPLE.name, user, True)
    if not db.q1("SELECT id FROM m5_snapshots"):
        from .m5 import limits as L5, service as S5
        from .routes_m5 import SAMPLE_PORTS
        data = L5.parse_limit_workbook(M5_SUMMARY_SAMPLE.read_bytes())
        lid = L5.save_limit_set(f"导入：{M5_SUMMARY_SAMPLE.name}", f"手工导入:{M5_SUMMARY_SAMPLE.name}", data, user)
        sid = S5.create_snapshot("2026-09-19", "样表导入（演示）", lid, user)
        for port, fn in SAMPLE_PORTS.items():
            S5.upload_port(sid, port, (M5_SAMPLE_DIR / fn).read_bytes(), fn, user)
    for t, ids in before.items():
        track[t] = sorted(_ids(t) - ids)
    # M1
    today = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)
    m1, by_title = [], {}
    for n, (title, pub, site, lv, ly, rg, ago, content, pts) in enumerate(ITEMS, 1):
        when = today - timedelta(days=ago) + timedelta(minutes=n)
        dup = None
        if "转载" in title and "指导意见" in title:
            dup = by_title.get("指导意见")
        iid = db.execute("INSERT INTO m1_items(url,title,publisher,level,layer,region,topic,pub_date,snippet,content,summary,query,provider,fetch_status,"
                         "duplicate_of,collected_at,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (f"{site}#demo-{n:02d}", title, pub, lv, ly, rg, TAG, when.strftime("%Y-%m-%d"), content[:120], content,
                          "\n".join(f"- {p}" for p in pts) or None, "演示数据包", TAG, "成功" if pts else "仅摘要", dup,
                          when.strftime("%Y-%m-%d %H:%M:%S"), when.strftime("%Y-%m-%d %H:%M:%S")))
        if "指导意见" in title and not dup:
            by_title["指导意见"] = iid
        m1.append(iid)
    track["m1_items"] = m1
    # M2：近 7 天，每天一期，较早的已发布
    from .m2 import brief as B
    sys = {"name": user.get("name") or "演示数据", "role": "internal"}
    briefs = []
    for ago in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=ago)).strftime("%Y-%m-%d")
        bid = B.generate(d, sys, trigger="演示数据")
        briefs.append(bid)
        if ago >= 1:
            try:
                B.publish(bid, sys)
            except HTTPException:
                pass
    track["m2_briefs"] = briefs
    # M3：一篇已定稿任务（终稿为人工撰写的演示文本，经规则核对后生成登记表）
    track["m3_tasks"], track["m3_style_guide"] = _demo_m3(user)
    # PPT：四类样例（规则模式，不调用模型）
    from .ppt import agent as G
    jobs = []
    d0 = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    scopes = {"usage": {"period": "周报"}, "scheme": {}, "policy": {"date_from": d0, "date_to": datetime.now().strftime("%Y-%m-%d")},
              "research": {"task_id": track["m3_tasks"][0]}}
    for k, sc in scopes.items():
        try:
            j = G.create({"deck_type": k, "scope": {**sc, "_rule_only": True}}, user)
            G.confirm_sheet(j["id"], {}, user)
            G.generate(j["id"], {"confirm": True}, user)
            jobs.append(j["id"])
        except HTTPException as e:  # noqa: PERF203
            track.setdefault("warnings", []).append(f"PPT {k}：{e.detail}")
    track["ppt_jobs"] = jobs
    db.set_setting("demo_data", track)
    db.audit(user, "系统", "加载演示数据", "", {k: len(v) for k, v in track.items() if isinstance(v, list)})
    return status() | {"warnings": track.get("warnings", [])}


def _demo_m3(user):
    from .m3 import pipeline as P
    rows = db.q("SELECT * FROM m1_items WHERE topic=? AND duplicate_of IS NULL AND level IN ('A1','B1') ORDER BY id LIMIT 4", (TAG,))
    sources = [{"type": "知识库(M1)", "m1_id": r["id"], "title": r["title"], "url": r["url"], "publisher": r["publisher"], "level": r["level"],
                "pub_date": r["pub_date"], "excerpt": r["content"][:600], "text": r["content"], "id": f"S{i}"} for i, r in enumerate(rows, 1)]
    draft = ("一、政策背景\n政府性融资担保机构要聚焦支小支农主业，坚守准公共定位[S1]。国家融资担保基金代偿补偿比例原则上不低于20%[S1]。"
             "我省担保机构数量达到60家，位居全国前列。\n"
             "二、主要做法\n中央财政继续安排资金支持扩大小微企业融资担保业务规模[S2]。奖补资金向担保费率不高于1%的地区倾斜[S2]。各地持续优化银担合作机制。\n"
             "三、下一步建议\n建议进一步完善再担保风险分担机制，提升代偿补偿资金使用效率。建议加强数字化风控能力建设。")
    final = draft.replace("我省担保机构数量达到60家，位居全国前列。", "").replace("持续优化", "持续深化")
    chk0 = P.rule_check(draft, sources, [])
    chk = P.rule_check(final, sources, [])
    tid = db.execute("INSERT INTO m3_tasks(title,requirements,status,stage,sources,facts,outline,draft,check_result,final,final_check,confirmations,"
                     "tokens,agents,created_by,created_at,updated_at,finalized_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (DEMO_M3_TITLE, db.jdump({"text": "突出代偿补偿与银担合作（演示数据）", "genre": "研究报告", "tone": "正式、简洁", "words": 800,
                                               "use_kb": True, "use_web": False, "use_m5": False}),
                      "已定稿" if not chk["red"] else "待人工修改（有标红）", "已定稿", db.jdump(sources), "[]",
                      db.jdump([{"heading": h, "points": []} for h in ("一、政策背景", "二、主要做法", "三、下一步建议")]),
                      draft, db.jdump(chk0), final, db.jdump(chk), "{}", "{}", db.jdump({"note": TAG}), user.get("name"), db.now(), db.now(), db.now()))
    P._save_register({"id": tid, "title": DEMO_M3_TITLE}, chk)
    db.execute("INSERT INTO m3_events(task_id,ts,agent,stage,message,elapsed_ms,tokens) VALUES(?,?,?,?,?,?,?)",
               (tid, db.now(), "system", "演示", "演示数据：初稿与终稿为预置文本（未调用大模型），核对结果由规则层实时生成", 0, 0))
    sg = [db.execute("INSERT INTO m3_style_guide(category,content,source_task_id,enabled,created_by,created_at) VALUES(?,?,?,1,?,?)",
                     (c, t, tid, "总结 Agent（演示）", db.now()))
          for c, t in (("措辞", "用“持续深化”替代“持续优化”"), ("口径", "涉及机构数量、排名须注明出处与统计时点"))]
    return [tid], sg


def clear(user):
    d = db.get_setting("demo_data", {}) or {}
    if not d:
        raise HTTPException(404, "当前没有已加载的演示数据")
    from .ppt.agent import PPT_DIR

    def dl(tbl, ids, col="id"):
        if ids:
            db.execute(f"DELETE FROM {tbl} WHERE {col} IN ({','.join('?' * len(ids))})", tuple(ids))
    for jid in d.get("ppt_jobs", []):
        shutil.rmtree(PPT_DIR / f"job{jid}", ignore_errors=True)
    dl("ppt_files", d.get("ppt_jobs", []), "job_id")
    dl("ppt_jobs", d.get("ppt_jobs", []))
    dl("m3_events", d.get("m3_tasks", []), "task_id")
    dl("m3_citations", d.get("m3_tasks", []), "task_id")
    dl("m3_style_guide", d.get("m3_style_guide", []))
    dl("m3_tasks", d.get("m3_tasks", []))
    dl("m2_briefs", d.get("m2_briefs", []))
    dl("m1_items", d.get("m1_items", []))
    dl("m5_ledgers", d.get("m5_snapshots", []), "snapshot_id")
    dl("m5_snapshots", d.get("m5_snapshots", []))
    dl("m5_limit_sets", d.get("m5_limit_sets", []))
    dl("m4_adjustments", d.get("m4_schemes", []), "scheme_id")
    dl("m4_schemes", d.get("m4_schemes", []))
    dl("m4_params", d.get("m4_params", []))
    dl("m4_datasets", d.get("m4_datasets", []))
    db.execute("DELETE FROM settings WHERE key='demo_data'")
    db.audit(user, "系统", "清除演示数据", "", {k: len(v) for k, v in d.items() if isinstance(v, list)})
    return status()


# ---------------- 上线就绪检查（模型 / 搜索 / 数据） ----------------
def readiness():
    from .llm.presets import SLOTS
    from .llm.service import assignments
    models = db.q("SELECT m.id, m.model_id, m.allow_sensitive, m.enabled, p.base_url, p.vendor, p.name FROM llm_models m JOIN llm_providers p ON p.id=m.provider_id")
    a = assignments()
    token_plan = [m for m in models if m["vendor"] == "minimax_token_plan" or ("minimax" in (m["base_url"] or "") and (m["base_url"] or "").rstrip("/").endswith("/anthropic"))]
    checks = [
        {"key": "model", "ok": any(m["enabled"] for m in models), "text": "至少配置 1 个可用大模型（M1 摘要 / M2 / M3 / PPT 使用）", "fix": "#admin/llm"},
        {"key": "sensitive", "ok": any(m["enabled"] and m["allow_sensitive"] for m in models),
         "text": "至少 1 个「允许处理敏感数据」的模型（公司私有或已授权），用于 M5 数据写作与额度/授信类 PPT", "fix": "#admin/llm"},
        {"key": "slots", "ok": all(a.get(s) for s in ("m3.writer", "ppt.agent")) or bool(db.get_setting("m3_agents")),
         "text": f"关键环节已分配模型（已分配 {sum(1 for s in SLOTS if a.get(s))}/{len(SLOTS)}）", "fix": "#admin/llm"},
        {"key": "search", "ok": bool(db.q1("SELECT id FROM search_providers WHERE enabled=1")), "text": "联网搜索供应商（M1 采集、M3 联网检索）", "fix": "#admin/search"},
        {"key": "m1", "ok": bool(db.q1("SELECT id FROM m1_items")), "text": "M1 知识库已有条目", "fix": "#m1"},
        {"key": "m4", "ok": bool(db.q1("SELECT id FROM m4_schemes")), "text": "M4 已有授信方案", "fix": "#m4"},
        {"key": "m5", "ok": bool(db.q1("SELECT id FROM m5_snapshots")), "text": "M5 已有看板快照", "fix": "#m5"},
    ]
    warns = []
    if token_plan:
        warns.append("检测到 MiniMax 包月 Token Plan 配置：官方定位为个人开发者交互式使用，生产环境建议按量付费 Key；并受 5 小时/周额度窗口与限流约束，不建议作为服务端默认模型。")
    return {"checks": checks, "warnings": warns, "demo": status()}
