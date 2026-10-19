"""抓取正文：httpx + lxml 轻量正文抽取（readability 思路）。带 SSRF 防护、大小/超时限制。
如需渲染 JS 页面，可替换为 Crawl4AI（见 README），接口保持 fetch(url) -> dict。"""
import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
from lxml import html as LH

UA = "Mozilla/5.0 (compatible; PuhuiWorkbench/1.0; +policy-research)"
MAX_BYTES = 3 * 1024 * 1024
DATE_META = ["PubDate", "pubdate", "publishdate", "PublishDate", "article:published_time", "OriginalPublishDate", "firstpublishedtime", "og:release_date"]
DATE_RE = re.compile(r"(20\d{2})\s*[-年/.]\s*(\d{1,2})\s*[-月/.]\s*(\d{1,2})")
CAND = re.compile(r"(TRS_Editor|article|content|zw|detail|main|text|con_)", re.I)


def _safe(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("仅支持 http/https")
    for info in socket.getaddrinfo(p.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("拒绝访问内网地址")


def _date(doc, text):
    for n in DATE_META:
        v = doc.xpath(f'//meta[@name="{n}" or @property="{n}"]/@content')
        if v:
            m = DATE_RE.search(v[0])
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = DATE_RE.search(text[:3000])
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def _decode(raw: bytes, charset=None):
    cands = [charset] if charset else []
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', raw[:4096])
    if m:
        cands.append(m.group(1).decode("ascii", "ignore"))
    cands += ["utf-8", "gb18030"]
    for c in cands:
        try:
            c = "gb18030" if c.lower() in ("gb2312", "gbk") else c
            return raw.decode(c)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def extract(raw: bytes, charset=None):
    txt = re.sub(r"^\s*<\?xml[^>]*\?>", "", _decode(raw, charset))
    doc = LH.fromstring(txt or "<html></html>")
    for bad in doc.xpath("//script|//style|//noscript|//header|//footer|//nav|//form|//iframe"):
        bad.drop_tree()
    title = (doc.xpath("string(//title)") or "").strip()
    h1 = (doc.xpath("string(//h1)") or "").strip()
    best, best_len = None, 0
    for el in doc.xpath("//div|//article|//td|//section"):
        if not CAND.search((el.get("class") or "") + " " + (el.get("id") or "")):
            continue
        t = el.text_content()
        if len(t) > best_len:
            best, best_len = el, len(t)
    node = best if best is not None and best_len > 200 else (doc.find("body") if doc.find("body") is not None else doc)
    text = re.sub(r"[ \t\u3000\xa0]+", " ", node.text_content())
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    from .clean import clean_text
    text = clean_text(text)  # 去导航/元数据字段/竖排单字
    full = doc.text_content()
    return {"title": h1 or title, "page_title": title, "text": text[:20000], "date": _date(doc, full)}


def fetch(url, timeout=15):
    with httpx.Client(follow_redirects=False, timeout=timeout, headers={"User-Agent": UA}) as c:
        for _ in range(6):  # 手动跟随跳转，每一跳都做内网地址校验
            _safe(url)
            with c.stream("GET", url) as r:
                if r.is_redirect:
                    url = str(r.url.join(r.headers.get("location", "")))
                    continue
                r.raise_for_status()
                ct = r.headers.get("content-type", "")
                if "pdf" in ct or url.lower().endswith(".pdf"):
                    return {"title": "", "text": "", "date": None, "kind": "pdf", "final_url": url}
                charset = r.charset_encoding
                buf = b""
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        break
                break
        else:
            raise ValueError("跳转次数过多")
    out = extract(buf, charset)
    out.update(kind="html", final_url=url)
    return out
