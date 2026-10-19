"""M1 正文清洗：导航、政务公开元数据字段、竖排单字、私用区图标；M2 要点不再带噪声。"""
from app.m1.clean import clean_point, clean_text
from app.m2 import brief as B

NOISY = """\ue6ea
 高级搜索
 搜索位置
 标题
 全文
 排序方式
发文字号：
 庆政办发〔2026〕11号
 层 级：
 市（地）级
 索\u2002引\u2002号：
 736916951/2026-010440
 主题分类：
 发文机关：
 打开
 首页
 党政
 人事
 反腐
 理论
日期：2026-09-10 来源：大庆市政府
各县、区人民政府：经市政府同意，现将《专项资金管理办法》印发给你们，请认真贯彻执行。
第一条 为高质量建设普惠金融发展示范区，提升政策效能和资金使用效益，制定本办法。
"""


def test_clean_text_strips_noise():
    t = clean_text(NOISY)
    for bad in ("主题分类", "高级搜索", "党政", "\ue6ea", "736916951", "发文机关"):
        assert bad not in t, bad
    assert "经市政府同意" in t and "第一条" in t


def test_meta_label_with_body_on_same_line_kept():
    body = "信息来源：省财政厅 为贯彻落实国务院办公厅关于有效发挥政府性融资担保基金作用的指导意见，省财政厅会同各有关部门积极推进再担保体系建设。"
    assert "为贯彻落实" in clean_text(body)


def test_clean_point_and_brief_points():
    assert clean_point("主题分类：\n发文机关：") == ""
    pts = B.points_and_numbers({"title": "关于印发专项资金管理办法的通知", "content": NOISY, "snippet": ""}, {"use_llm": False}, None)[0]
    assert pts and all("索引号" not in p and "\n" not in p and "主题分类" not in p for p in pts)
    assert pts[0].startswith("各县、区人民政府")
