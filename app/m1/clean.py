"""正文清洗：去掉网页导航、政务公开元数据字段（索引号/主题分类/发文机关…）、竖排单字、私用区图标字符。
用于 M1 入库（fetch.extract 之后）、存量重洗（cli m1-reclean）及 M2 要点提炼前的兜底。"""
import re

PUA = re.compile(r"[\ue000-\uf8ff\u2002\u2003\u200b\ufeff]")
META = re.compile(r"^(索\s*引\s*号|主题分类|主\s*题\s*词|发文机关|发布机构|成文日期|发布日期|发文日期|生效日期|失效日期|发文字号|文\s*号|层\s*级|"
                  r"信息来源|来\s*源|浏览次数|访问量|有\s*效\s*性|文件状态|公开方式|公开范围|所属机构|名\s*称|分\s*类|体裁分类|组配分类|服务对象)\s*[：:]")
NAV = re.compile(r"^(打开|首页|登录|注册|无障碍|长者模式|English|网站地图|高级搜索|搜索|搜索位置|搜索以下关键词|排序方式|按时间|按相关度|标题|全文|"
                 r"不限|现行有效|已失效|收起|分享到[：:]?|订阅.*|点击播报.*|.*小字号|\d{6,}/\d{4}-\d+|【?打印】?|【?关闭】?|【?字体[：:].*|.*字号[：:]\s*大\s*中\s*小.*|下载文字版|下载图片版|"
                 r"上一篇|下一篇|返回顶部|扫一扫.*|当前位置.*|您现在的位置.*|责任编辑.*|相关链接|相关阅读|热点推荐|操作>>|分享到微信.*|打开微信.*扫一扫.*)\s*[：:]?$")

SENT = re.compile(r"[。，；！？,;]")


def clean_text(text):
    if not text:
        return text
    text = PUA.sub(" ", text)
    lines = [re.sub(r"[ \t\u3000\xa0]+", " ", l).strip() for l in text.splitlines()]
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        if not l:
            i += 1
            continue
        # 连续 4 行以上的短行（≤8 字，或 ≤20 字且无句读标点）视为导航/栏目列表或竖排字
        j = i
        while j < len(lines) and 0 < len(lines[j]) and (len(lines[j]) <= 8 or (len(lines[j]) <= 20 and not SENT.search(lines[j]))):
            j += 1
        if j - i >= 4:
            i = j
            continue
        if META.match(l):
            rest = META.sub("", l).strip()
            if len(rest) > 30:  # 「信息来源：省财政厅 为贯彻落实……」字段与正文同一行：保留正文
                out.append(rest)
                i += 1
                continue
            i += 1
            if not rest and i < len(lines) and len(lines[i]) <= 30 and not META.match(lines[i]):
                i += 1  # 字段值单独一行
            continue
        if NAV.match(l) or len(l) <= 2:
            i += 1
            continue
        out.append(l)
        i += 1
    return "\n".join(out).strip()


def clean_point(p):
    """要点/摘要单条：清洗并压成一行；剩余过短或仍像元数据则返回空。"""
    t = re.sub(r"\s+", " ", clean_text(p or "")).strip()
    if len(t) < 6 or re.search(r"索引号|主题分类|发文机关|分享到|高级搜索", t):
        return ""
    return t


def reclean_all(dry_run=False):
    """存量重洗：content / snippet 原地清洗（FTS 触发器随 UPDATE 同步）。返回统计。"""
    from .. import db
    n = changed = 0
    for it in db.q("SELECT id, content, snippet FROM m1_items"):
        n += 1
        c, s = clean_text(it["content"]), clean_text(it["snippet"])
        if c != it["content"] or s != it["snippet"]:
            changed += 1
            if not dry_run:
                db.execute("UPDATE m1_items SET content=?, snippet=? WHERE id=?", (c, s, it["id"]))
    return {"items": n, "changed": changed, "dry_run": dry_run}
