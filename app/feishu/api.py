"""飞书开放平台 API 精简客户端（httpx）：tenant_access_token、发消息、上传并发送文件、机器人信息。
全部走 Feishu OpenAPI 公开接口；单测用 FakeAPI 替换，无需真实凭据。"""
import json
import threading
import time

import httpx

from . import config as C


class FeishuError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


class FeishuAPI:
    def __init__(self, cfg=None):
        self.cfg = cfg or C.get()
        self.base = C.base_url(self.cfg) + "/open-apis"
        self._tok, self._exp = None, 0
        self._lock = threading.Lock()

    def _check(self, r):
        try:
            j = r.json()
        except ValueError as e:
            raise FeishuError(f"飞书返回非 JSON（HTTP {r.status_code}）") from e
        if r.status_code >= 400 or j.get("code", 0) != 0:
            raise FeishuError(f"{j.get('msg') or r.text[:200]}（code {j.get('code', r.status_code)}）", j.get("code"))
        return j

    def token(self):
        with self._lock:
            if self._tok and time.time() < self._exp - 60:
                return self._tok
            r = httpx.post(self.base + "/auth/v3/tenant_access_token/internal", timeout=15,
                           json={"app_id": self.cfg["app_id"], "app_secret": C.secret(self.cfg, "app_secret")})
            j = self._check(r)
            self._tok, self._exp = j["tenant_access_token"], time.time() + int(j.get("expire", 7200))
            return self._tok

    def _h(self):
        return {"Authorization": f"Bearer {self.token()}"}

    def bot_info(self):
        j = self._check(httpx.get(self.base + "/bot/v3/info", headers=self._h(), timeout=15))
        b = j.get("bot") or {}
        return {"open_id": b.get("open_id", ""), "name": b.get("app_name", "")}

    def reply_text(self, message_id, text):
        return self._check(httpx.post(f"{self.base}/im/v1/messages/{message_id}/reply", headers=self._h(), timeout=15,
                                      json={"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)}))

    def send_text(self, chat_id, text):
        return self._check(httpx.post(self.base + "/im/v1/messages", params={"receive_id_type": "chat_id"}, headers=self._h(), timeout=15,
                                      json={"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)}))

    def upload_file(self, name, data):
        r = httpx.post(self.base + "/im/v1/files", headers=self._h(), timeout=60, data={"file_type": "stream", "file_name": name},
                       files={"file": (name, data, "application/octet-stream")})
        return self._check(r)["data"]["file_key"]

    def send_file(self, chat_id, file_key):
        return self._check(httpx.post(self.base + "/im/v1/messages", params={"receive_id_type": "chat_id"}, headers=self._h(), timeout=15,
                                      json={"receive_id": chat_id, "msg_type": "file", "content": json.dumps({"file_key": file_key})}))


def get_api():
    """业务代码统一从这里取客户端（测试中替换为 FakeAPI）。"""
    return FeishuAPI()
