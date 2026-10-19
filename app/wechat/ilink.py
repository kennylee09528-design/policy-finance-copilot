"""同步 iLink（微信 ClawBot）客户端。协议对齐 Tencent/openclaw-weixin 2.4.x + spike 实测。"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"
PLUGIN_VERSION = (2, 4, 10)
APP_ID = "bot"
BOT_AGENT = "PuhuiWorkbench/1.0"
BOT_TYPE = "3"
MEDIA_IMAGE, MEDIA_FILE = 1, 3
ITEM_TEXT, ITEM_IMAGE, ITEM_FILE = 1, 2, 4
STALE_ERRCODE = -14


def client_version_int() -> int:
    ma, mi, pa = PLUGIN_VERSION
    return ((ma & 0xFF) << 16) | ((mi & 0xFF) << 8) | (pa & 0xFF)


def plugin_version_str() -> str:
    return ".".join(str(x) for x in PLUGIN_VERSION)


def aes_ecb_encrypt(plain: bytes, key: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    data = padder.update(plain) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(data) + enc.finalize()


def aes_ecb_padded_size(n: int) -> int:
    return ((n + 1 + 15) // 16) * 16


@dataclass
class Resp:
    http_status: int | None = None
    body: dict | None = None
    text: str = ""
    error: str | None = None
    elapsed: float = 0.0

    @property
    def ret(self):
        return (self.body or {}).get("ret")

    @property
    def errcode(self):
        return (self.body or {}).get("errcode")

    @property
    def errmsg(self):
        return (self.body or {}).get("errmsg")

    @property
    def message_id(self) -> str | None:
        v = (self.body or {}).get("message_id")
        return str(v) if v not in (None, "", 0) else None

    @property
    def ok(self) -> bool:
        return (self.error is None and self.http_status == 200
                and self.ret in (None, 0) and self.errcode in (None, 0))

    @property
    def delivered(self) -> bool:
        return self.ok and self.message_id is not None

    @property
    def stale(self) -> bool:
        return self.ret == STALE_ERRCODE or self.errcode == STALE_ERRCODE

    def summary(self) -> dict:
        return {"http": self.http_status, "ret": self.ret, "errcode": self.errcode,
                "errmsg": self.errmsg, "message_id_present": bool(self.message_id), "error": self.error}


@dataclass
class Uploaded:
    ok: bool
    stage: str = ""
    error: str | None = None
    filekey: str = ""
    download_param: str = ""
    aeskey_hex: str = ""
    size: int = 0
    cipher_size: int = 0
    detail: dict = field(default_factory=dict)


class IlinkClient:
    def __init__(self, token: str | None = None, base_url: str = DEFAULT_BASE_URL,
                 cdn_base: str = DEFAULT_CDN_BASE, transport=None, timeout_default: float = 40):
        self.token = token
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.cdn_base = cdn_base.rstrip("/")
        self._http = httpx.Client(transport=transport, follow_redirects=False, timeout=timeout_default)

    def close(self):
        self._http.close()

    @staticmethod
    def app_headers() -> dict:
        return {"iLink-App-Id": APP_ID, "iLink-App-ClientVersion": str(client_version_int())}

    def post_headers(self, token: str | None) -> dict:
        h = {"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
             "X-WECHAT-UIN": base64.b64encode(str(random.getrandbits(32)).encode()).decode(),
             **self.app_headers()}
        if token:
            h["Authorization"] = f"Bearer {token.strip()}"
        return h

    @staticmethod
    def base_info() -> dict:
        return {"channel_version": plugin_version_str(), "bot_agent": BOT_AGENT}

    def _post(self, endpoint: str, body: dict, *, token: str | None, timeout: float,
              base_url: str | None = None, with_base_info: bool = True) -> Resp:
        url = f"{(base_url or self.base_url).rstrip('/')}/{endpoint.lstrip('/')}"
        payload = dict(body)
        if with_base_info:
            payload["base_info"] = self.base_info()
        t0 = time.monotonic()
        try:
            r = self._http.post(url, content=json.dumps(payload, ensure_ascii=False).encode(),
                                headers=self.post_headers(token), timeout=timeout)
        except httpx.TimeoutException as e:
            return Resp(error=f"timeout: {type(e).__name__}", elapsed=time.monotonic() - t0)
        except Exception as e:  # noqa: BLE001
            return Resp(error=f"transport: {type(e).__name__}: {e}", elapsed=time.monotonic() - t0)
        resp = Resp(http_status=r.status_code, text=r.text, elapsed=time.monotonic() - t0)
        txt = r.text.strip()
        if not txt:
            resp.body = {}
        else:
            try:
                resp.body = json.loads(txt)
            except ValueError:
                resp.error = "non-json response"
        return resp

    def get_bot_qrcode(self, local_tokens: list[str] | None = None) -> Resp:
        return self._post(f"ilink/bot/get_bot_qrcode?bot_type={BOT_TYPE}",
                          {"local_token_list": local_tokens or []}, token=None,
                          timeout=30, base_url=DEFAULT_BASE_URL, with_base_info=False)

    def get_qrcode_status(self, qrcode: str, verify_code: str | None = None,
                          base_url: str | None = None, timeout: float = 40) -> Resp:
        url = f"{(base_url or DEFAULT_BASE_URL).rstrip('/')}/ilink/bot/get_qrcode_status?qrcode={quote(qrcode, safe='')}"
        if verify_code:
            url += f"&verify_code={quote(verify_code, safe='')}"
        t0 = time.monotonic()
        try:
            r = self._http.get(url, headers=self.app_headers(), timeout=timeout)
        except httpx.TimeoutException:
            return Resp(body={"status": "wait"}, elapsed=time.monotonic() - t0, text="client-timeout")
        except Exception:  # noqa: BLE001
            return Resp(body={"status": "wait"}, elapsed=time.monotonic() - t0, text="neterr")
        resp = Resp(http_status=r.status_code, text=r.text, elapsed=time.monotonic() - t0)
        try:
            resp.body = json.loads(r.text) if r.text.strip() else {"status": "wait"}
        except ValueError:
            resp.body = {"status": "wait"}
        return resp

    def notify(self, start: bool) -> Resp:
        return self._post("ilink/bot/msg/notifystart" if start else "ilink/bot/msg/notifystop",
                          {}, token=self.token, timeout=10)

    def get_updates(self, cursor: str, timeout: float = 40, token: str | None = None) -> Resp:
        r = self._post("ilink/bot/getupdates", {"get_updates_buf": cursor},
                       token=token or self.token, timeout=timeout)
        if r.error and r.error.startswith("timeout"):
            return Resp(http_status=200, body={"ret": 0, "msgs": [], "get_updates_buf": cursor},
                        text="client-timeout", elapsed=r.elapsed)
        return r

    def send_item(self, to_user_id: str, item: dict, context_token: str | None) -> Resp:
        msg = {"from_user_id": "", "to_user_id": to_user_id,
               "client_id": f"ph-{secrets.token_hex(8)}", "message_type": 2,
               "message_state": 2, "item_list": [item]}
        if context_token:
            msg["context_token"] = context_token
        return self._post("ilink/bot/sendmessage", {"msg": msg}, token=self.token, timeout=20)

    def send_text(self, to_user_id: str, text: str, context_token: str | None) -> Resp:
        return self.send_item(to_user_id, {"type": ITEM_TEXT, "text_item": {"text": text}}, context_token)

    def upload_media(self, data: bytes, media_type: int, to_user_id: str) -> Uploaded:
        key = secrets.token_bytes(16)
        filekey = secrets.token_hex(16)
        up = Uploaded(ok=False, stage="getuploadurl", filekey=filekey, aeskey_hex=key.hex(),
                      size=len(data), cipher_size=aes_ecb_padded_size(len(data)))
        r = self._post("ilink/bot/getuploadurl", {
            "filekey": filekey, "media_type": media_type, "to_user_id": to_user_id,
            "rawsize": len(data), "rawfilemd5": hashlib.md5(data).hexdigest(),
            "filesize": up.cipher_size, "no_need_thumb": True, "aeskey": key.hex()},
            token=self.token, timeout=20)
        up.detail["getuploadurl"] = r.summary()
        if not r.ok or not r.body or not (r.body.get("upload_full_url") or r.body.get("upload_param")):
            up.error = f"getuploadurl failed: ret={r.ret} errmsg={r.errmsg} err={r.error}"
            return up
        full = (r.body.get("upload_full_url") or "").strip()
        url = full or (f"{self.cdn_base}/upload?encrypted_query_param={quote(r.body['upload_param'], safe='')}"
                       f"&filekey={quote(filekey, safe='')}")
        cipher = aes_ecb_encrypt(data, key)
        up.stage = "cdn"
        last = ""
        for attempt in range(1, 4):
            try:
                cr = self._http.post(url, content=cipher, timeout=300,
                                     headers={"Content-Type": "application/octet-stream"})
            except Exception as e:  # noqa: BLE001
                last = f"transport {type(e).__name__}: {e}"
                continue
            if 400 <= cr.status_code < 500:
                up.error = f"cdn client error {cr.status_code}"
                return up
            if cr.status_code != 200:
                last = f"cdn status {cr.status_code}"
                continue
            dl = cr.headers.get("x-encrypted-param")
            if not dl:
                last = "cdn response missing x-encrypted-param"
                continue
            up.download_param, up.ok, up.stage = dl, True, "done"
            return up
        up.error = f"cdn upload failed: {last}"
        return up

    @staticmethod
    def media_ref(up: Uploaded) -> dict:
        return {"encrypt_query_param": up.download_param,
                "aes_key": base64.b64encode(up.aeskey_hex.encode()).decode(), "encrypt_type": 1}

    def send_file(self, to: str, up: Uploaded, file_name: str, ctx: str | None) -> Resp:
        return self.send_item(to, {"type": ITEM_FILE, "file_item": {
            "media": self.media_ref(up), "file_name": file_name, "len": str(up.size)}}, ctx)

    def send_image(self, to: str, up: Uploaded, ctx: str | None) -> Resp:
        return self.send_item(to, {"type": ITEM_IMAGE, "image_item": {
            "media": self.media_ref(up), "mid_size": up.cipher_size}}, ctx)
