"""权威发布方规则：按域名（含子域）+ 可选路径正则判定发布方与来源等级。首条命中生效。"""
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from .config import OFFICIAL


def norm_url(u):
    p = urlparse(u.strip())
    qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith(("utm_", "spm", "from"))]
    return urlunparse((p.scheme.lower(), (p.hostname or "").lower() + (f":{p.port}" if p.port else ""), p.path or "/", "", urlencode(qs), ""))


def classify(url, cfg):
    try:
        p = urlparse(url)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    path = p.path or "/"
    for r in cfg["rules"]:
        d = r["domain"]
        if host == d or host.endswith("." + d):
            if r.get("path_regex") and not re.search(r["path_regex"], path, re.I):
                continue
            lvl = r["level"]
            if lvl == OFFICIAL:
                lvl = "A1" if re.search(cfg["a1_path_regex"], path, re.I) else "A2"
            pub = r["publisher"] if r["domain"] != "gov.cn" else f"政府网站（{host}）"
            return {"publisher": pub, "level": lvl, "layer": r.get("layer") or "", "rule": d}
    return {"publisher": host, "level": "C2", "layer": "", "rule": None}
