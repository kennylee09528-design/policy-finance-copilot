"""首页数据主线：实时数字（内部视角全量；机构视角只给 M2/M5 且不含全网使用率）。"""
from urllib.parse import quote

from app import db


def test_home_story(client):
    if not db.q1("SELECT 1 x FROM m4_schemes WHERE is_current=1 AND deleted_at IS NULL"):
        assert client.post("/api/m4/import-sample").status_code == 200
    client.post("/api/m5/limit-sets/import-sample")
    client.post("/api/m5/snapshots/sample", json={})
    h = client.get("/api/home").json()
    for k in ("m1", "m2", "m3", "m4", "m5", "ppt"):
        assert k in h, k
    assert h["m4"]["sumFinal"] and h["m4"]["count"]
    assert h["m5"]["rate"] is not None and h["m5"]["institutions"] > 0 and "red" in h["m5"]
    inst = db.q1("SELECT full_name FROM institutions WHERE COALESCE(all_access,0)=0 ORDER BY id")["full_name"]
    hi = client.get("/api/home", headers={"X-Role": "institution", "X-Org": quote(inst)}).json()
    assert "m1" not in hi and "m3" not in hi and hi["m4"] is None
    assert hi["m5"]["rate"] is None and hi["m5"]["institutions"] == 1
