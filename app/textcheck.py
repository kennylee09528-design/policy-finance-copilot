"""文本核验工具：关键数字抽取、来源比对、风险句识别（M2 关键数字校验、M3 核对 Agent 规则层）。"""
import re

NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
UNIT = r"(?:%|％|‰|个百分点|万亿元|亿元|万元|千元|元|万亿|亿|万|倍|家|户|笔|项|人次|人|个)"
KEYNUM_RE = re.compile(rf"({NUM})\s*({UNIT})")
RANK_RE = re.compile(r"(第[一二三四五六七八九十百\d]+(名|位)|排名|位居|居全省|居全国|名列|首位|前[一二三四五十\d]+(名|位|强))")
CASE_RE = re.compile(r"(《[^》]{2,60}》|案例|[\u4e00-\u9fa5（）()]{2,30}(有限公司|股份公司|银行|集团|担保公司|合作社))")
CITE_RE = re.compile(r"\[(S\d+|M5)\]")
SENT_RE = re.compile(r"[^。！？；!?;\n]+[。！？；!?;]?")


def norm(s):
    return re.sub(r"[\s,，\u3000]", "", s or "").replace("％", "%")


def key_numbers(text):
    """返回 [(原文片段, 数字串(无逗号), 单位)]，不含年月日。"""
    out = []
    for m in KEYNUM_RE.finditer(text or ""):
        out.append((m.group(0), m.group(1).replace(",", ""), m.group(2).replace("％", "%")))
    return out


def number_in_source(numstr, unit, source_text):
    src = norm(source_text)
    if not src:
        return False
    n = numstr.rstrip("0").rstrip(".") if "." in numstr else numstr
    for cand in {numstr, n}:
        if re.search(rf"(?<![\d.]){re.escape(cand)}(?![\d])", src):
            return True
    return False


def sentences(text):
    """按段落、句子切分：[(段号, 句号, 句子)]，段号从 1 开始。"""
    out = []
    for pi, para in enumerate([p for p in (text or "").split("\n") if p.strip()], 1):
        for si, m in enumerate(SENT_RE.finditer(para), 1):
            s = m.group(0).strip()
            if s:
                out.append((pi, si, s))
    return out


def risk_kinds(sentence):
    s = CITE_RE.sub("", sentence)
    kinds = []
    if key_numbers(s):
        kinds.append("金额/比例/数量")
    if RANK_RE.search(s):
        kinds.append("排名")
    if CASE_RE.search(s):
        kinds.append("案例/机构/文件名称")
    return kinds
