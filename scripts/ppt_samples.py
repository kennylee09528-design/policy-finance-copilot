"""生成四类 PPT 样例（独立临时数据目录；M4/M5 导入样例数据，M1/M2/M3 造少量演示数据；大模型以本地桩替代）。
用法：.venv/bin/python scripts/ppt_samples.py /workspace/ai-contest/samples_ppt"""
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "ppt_samples").resolve()
tmp = tempfile.mkdtemp(prefix="ph_ppt_")
os.environ.update(PH_DATA_DIR=tmp, PH_DB_PATH=str(Path(tmp) / "s.db"), PH_DISABLE_SCHEDULER="1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.llm import service as L  # noqa: E402
from app.main import app  # noqa: E402
from app.ppt import render as R  # noqa: E402

c = TestClient(app)
NOW = datetime.now()


def fake_llm(url, json=None, headers=None, timeout=None):
    msgs = json["messages"]
    sysp, user = msgs[0]["content"], msgs[-1]["content"]
    m = re.search(r"(S\d+)｜", user)
    sid = m.group(1) if m else "S1"
    if "请先给出大纲" in user:
        out = '[{"heading":"一、政策背景","points":["代偿补偿"]},{"heading":"二、主要做法","points":["银担合作"]},{"heading":"三、下一步建议","points":["建议"]}]'
    elif "现在只写第 1 节" in user:
        out = f"国家融资担保基金再担保代偿补偿比例为30%[{sid}]。政府性融资担保机构应聚焦支小支农主业，坚守准公共定位[{sid}]。"
    elif "现在只写第 2 节" in user:
        out = f"各地持续深化银担合作，推广“见贷即担”批量担保模式[{sid}]。担保费率原则上不超过1%[{sid}]。"
    elif "现在只写第 3 节" in user:
        out = "建议进一步完善再担保风险分担机制。建议加强数字化风控能力建设，提升业务审批效率。"
    elif "材料核对员" in sysp:
        out = '{"issues":[]}'
    else:
        out = "{}"
    return httpx.Response(200, json={"choices": [{"message": {"content": out}}], "model": json["model"], "usage": {"total_tokens": 80}})


httpx_post = httpx.post
httpx.post = lambda url, **kw: fake_llm(url, **kw) if "stub.local" in url else httpx_post(url, **kw)
import app.llm.client as LC  # noqa: E402
LC.httpx.post = httpx.post

assert c.post("/api/m4/import-sample").status_code == 200
assert c.post("/api/m5/snapshots/sample", json={"stat_date": "2026-09-19"}).status_code == 200
u = {"name": "样例", "role": "admin"}
pid = L.save_provider({"vendor": "company_private", "base_url": "https://stub.local/v1", "api_key": "sk-stub-xxxxxxxx"}, u)
mid = L.save_model({"provider_id": pid, "model_id": "stub-writer", "allow_sensitive": True}, u)
for slot in ("m3.writer", "m3.checker", "m3.summarizer"):
    L.assign(slot, mid, u)

ITEMS = [
    ("https://www.gov.cn/zhengce/a1.htm", "关于进一步做好政府性融资担保代偿补偿工作的通知", "国务院办公厅", "A1", "国家", "全国",
     "国家融资担保基金再担保代偿补偿比例为30%。担保费率原则上不超过1%。政府性融资担保机构应聚焦支小支农主业，坚守准公共定位。各地持续深化银担合作，推广“见贷即担”批量担保模式。"),
    ("https://www.mof.gov.cn/zhengce/a2.htm", "财政部关于实施小微企业融资担保降费奖补政策的通知", "财政部", "A1", "国家", "全国", "对扩大小微企业融资担保业务规模、降低费率的地区给予奖补。"),
    ("https://www.gd.gov.cn/zw/b1.htm", "广东省推进普惠金融高质量发展实施方案", "广东省人民政府", "B1", "省级", "广东", "全省政府性融资担保体系建设持续推进，提升首贷、信用贷支持力度。"),
    ("https://jrj.gd.gov.cn/b2.htm", "省地方金融管理局召开融资担保行业座谈会", "广东省地方金融管理局", "B1", "省级", "广东", "会议部署下一步政府性融资担保工作。"),
    ("https://zj.example.com/c1.htm", "浙江推出科技型企业专属担保产品", "示例外省担保集团甲", "B2", "省级", "浙江", "浙江为科技型中小企业提供专属担保产品，支持创新发展。"),
    ("https://st.example.com/c2.htm", "汕头举办银担企对接活动", "汕头市金融局", "C2", "普通地市", "汕头", "活动顺利举行，多家企业参与。"),
]
for url, t, pub, lv, ly, rg, ct in ITEMS:
    db.execute("INSERT INTO m1_items(url,title,publisher,level,layer,region,pub_date,snippet,content,summary,collected_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (url, t, pub, lv, ly, rg, NOW.strftime("%Y-%m-%d"), "", ct, None, (NOW - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")))
b = c.post("/api/m2/briefs/generate", json={}).json()
c.post(f"/api/m2/briefs/{b['id']}/publish")

t = c.post("/api/m3/tasks", json={"title": "政府性融资担保代偿补偿与银担合作情况研究", "requirements": "突出代偿补偿与银担合作", "words": 900,
                                  "use_kb": True, "use_web": False, "use_m5": False, "sync": True}).json()
task = c.get(f"/api/m3/tasks/{t['id']}").json()
final = task["draft"]
for it in task["check_result"]["items"]:
    if it["red"]:
        final = final.replace(it["text"], "")
r = c.put(f"/api/m3/tasks/{t['id']}/final", json={"final": final}).json()
assert r["red"] == 0, r
assert c.post(f"/api/m3/tasks/{t['id']}/finalize").status_code == 200

OUT.mkdir(parents=True, exist_ok=True)
today = NOW.strftime("%Y-%m-%d")
SCOPES = {"usage": {"period": "周报"}, "scheme": {}, "policy": {"date_from": today, "date_to": today}, "research": {"task_id": t["id"]}}
NAMES = {"usage": "1_额度使用情况汇报", "scheme": "2_授信方案上会材料", "policy": "3_政策简报", "research": "4_研究报告配套演示稿"}
report = []
for k, scope in SCOPES.items():
    j = c.post("/api/ppt/jobs", json={"deck_type": k, "scope": scope}).json()
    assert "id" in j, j
    c.post(f"/api/ppt/jobs/{j['id']}/sheet", json={"answers": ["部门领导"]})
    g = c.post(f"/api/ppt/jobs/{j['id']}/generate", json={"confirm": True, "thumbnails": False}).json()
    f = g["files"][0]
    row = db.q1("SELECT path FROM ppt_files WHERE id=?", (f["id"],))
    dst = OUT / f"{NAMES[k]}.pptx"
    shutil.copy(row["path"], dst)
    th = OUT / f"{NAMES[k]}_preview"
    if th.exists():
        shutil.rmtree(th)
    pngs = R.thumbnails(str(dst), str(th), dpi=60)
    report.append(f"{dst.name}: {f['pages']} 页, 溯源 {'通过' if f['trace']['ok'] else '异常'} "
                  f"({f['trace']['numbers_checked']} 个数字, {f['trace']['chart_series_checked']} 个图表序列), 预览 {len(pngs)} 张")
print("\n".join(report))
if os.environ.get("PPT_SAMPLES_KEEP"):
    print("DATA_DIR", tmp)
else:
    shutil.rmtree(tmp, ignore_errors=True)
