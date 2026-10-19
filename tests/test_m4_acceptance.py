"""M4 验收：导入附件2 后，逐行比对 W、X（以及 J~V 各系数）与工作簿缓存值。

运行：.venv/bin/python -m pytest -q tests/test_m4_acceptance.py -s
"""
import openpyxl
import pytest

from app.config import M4_SAMPLE

COEF_COLS = ["J", "K", "L", "M", "N", "O", "P", "Q", "R", "T", "U", "V", "W"]


@pytest.fixture(scope="module")
def imported(client):
    r = client.post("/api/m4/import-sample")
    assert r.status_code == 200, r.text
    return r.json()


def _excel_rows():
    wv = openpyxl.load_workbook(M4_SAMPLE, data_only=True)["计算表"]
    out = {}
    for r in range(2, wv.max_row + 1):
        name = wv[f"B{r}"].value
        if name:
            out[name.strip()] = {c: wv[f"{c}{r}"].value for c in COEF_COLS + ["X", "AC", "AI", "AJ"]}
    return out


def test_w_x_match_every_row(client, imported):
    s = client.get(f"/api/m4/schemes/{imported['scheme_id']}").json()
    rows = {r["name"]: r for r in s["result"]["rows"]}
    excel = _excel_rows()
    assert len(excel) == 10 and len(rows) == 10
    w_ok = x_ok = 0
    mism = []
    for name, e in excel.items():
        m = rows[name]
        if abs(m["W"] - e["W"]) < 1e-6:
            w_ok += 1
        else:
            mism.append((name, "W", m["W"], e["W"]))
        if m["X"] == e["X"]:
            x_ok += 1
        else:
            mism.append((name, "X", m["X"], e["X"]))
    print(f"\n[M4 验收] W 一致 {w_ok}/10，X 一致 {x_ok}/10（其中 8 家模型测算、2 家固定额度）")
    assert not mism, mism
    assert rows["示例担保公司A"]["X"] == 183478
    assert rows["示例担保公司D"]["X"] == 109395


def test_all_coefficients_match(client, imported):
    s = client.get(f"/api/m4/schemes/{imported['scheme_id']}").json()
    rows = {r["name"]: r for r in s["result"]["rows"]}
    n = 0
    for name, e in _excel_rows().items():
        for c in COEF_COLS:
            ev = e[c]
            if not isinstance(ev, (int, float)):
                continue
            mv = rows[name][c]
            assert mv is not None and abs(mv - ev) <= 1e-9 * max(1, abs(ev)), (name, c, mv, ev)
            n += 1
    print(f"[M4 验收] J~W 系数单元格比对 {n} 个，全部一致（相对误差 ≤1e-9）")


def test_prefilled_scheme_reproduces_final(client, imported):
    """附件2口径方案：第三次调整 = AC − X（合并原表第三~六次调整），最终授信应等于原表 AI 列。"""
    cur = client.get("/api/m4/schemes/current").json()
    rows = {r["name"]: r for r in cur["result"]["rows"]}
    ok = 0
    for name, e in _excel_rows().items():
        assert rows[name]["final"] == pytest.approx(e["AI"]), name
        ok += 1
    print(f"[M4 验收] 附件2口径方案 最终授信(=AC+D) 与原表 AI 列一致 {ok}/10")


def test_adjust_requires_reason_and_is_audited(client, imported):
    sid = client.post(f"/api/m4/schemes/{imported['scheme_id']}/copy", json={"name": "测试调整"}).json()["scheme_id"]
    r = client.post(f"/api/m4/schemes/{sid}/adjust", json={"institution": "示例担保公司D", "value": 5000, "reason": ""})
    assert r.status_code == 400
    r = client.post(f"/api/m4/schemes/{sid}/adjust", json={"institution": "示例担保公司D", "value": 5000, "reason": "业务需求增补"},
                    headers={"X-User": "zhangsan"})
    assert r.status_code == 200
    row = next(x for x in r.json()["rows"] if x["name"] == "示例担保公司D")
    assert row["after_third"] == 109395 + 5000
    hist = client.get(f"/api/m4/schemes/{sid}").json()["history"]
    assert hist[0]["operator"] == "zhangsan" and hist[0]["reason"] == "业务需求增补" and hist[0]["created_at"]
    # 标注已上会后锁定
    assert client.post(f"/api/m4/schemes/{sid}/status", json={"status": "已上会"}).status_code == 200
    assert client.post(f"/api/m4/schemes/{sid}/adjust", json={"institution": "示例担保公司D", "value": 1, "reason": "x"}).status_code == 409
    # 对比 & 回滚
    cmp = client.get(f"/api/m4/compare?a={imported['scheme_id']}&b={sid}").json()
    changed = [x for x in cmp["rows"] if x["changed"]]
    assert len(changed) == 1 and changed[0]["diff"]["third"] == 5000
    nid = client.post(f"/api/m4/schemes/{imported['scheme_id']}/rollback").json()["scheme_id"]
    assert client.get("/api/m4/schemes/current").json()["id"] == nid


def test_weights_must_sum_to_one(client, imported):
    r = client.post("/api/m4/params", json={"weights": {"L": 0.3, "N": 0.2, "P": 0.1, "R": 0.1, "T": 0.4}})
    assert r.status_code == 400 and "合计=1" in r.json()["detail"]


def test_exports(client, imported):
    sid = imported["scheme_id"]
    r = client.get(f"/api/m4/schemes/{sid}/export.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    r = client.post(f"/api/m4/schemes/{sid}/qingshi.docx", json={})
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_institution_role_forbidden(client, imported):
    r = client.get("/api/m4/schemes", headers={"X-Role": "institution"})
    assert r.status_code == 403


def test_selftest_hides_names(client, imported):
    p = client.get("/api/selftest/pool").json()
    assert "rows" not in p and "name" not in str(p)
    r = client.post("/api/selftest/calc", json={"scale": 386680.815798, "emp": 49433, "zxzn": 88.49, "lj": 3.89919,
                                                 "dn": 2.822715, "pj": 92.48, "zc": 9822.81, "mintou": 96885.468643})
    assert r.status_code == 200
    assert r.json()["W"] == pytest.approx(309795.347155)
    assert "X" not in r.json() and "第二次" not in r.text
