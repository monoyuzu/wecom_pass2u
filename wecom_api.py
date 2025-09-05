# -*- coding: utf-8 -*-
# wecom_api.py
from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

import os
import time
import requests
from functools import lru_cache
from typing import Optional, Dict, Any

CORP_ID: str = os.getenv("WECHAT_CORP_ID", "")
CORP_SECRET: str = os.getenv("WECHAT_CORP_SECRET", "")
OPEN_KFID: str = os.getenv("WECHAT_OPEN_KFID", "")
WELCOME_TPL_ID: str = os.getenv("WECOM_GROUP_WELCOME_TEMPLATE_ID", "")


class WeComAPI:
    def __init__(self):
        self.s = requests.Session()

    # ---------- token ----------
    @lru_cache(maxsize=1)
    def _cached_token(self) -> Dict[str, Any]:
        return {"token": self._fetch_token(), "expire_at": time.time() + 6600}

    def _fetch_token(self) -> str:
        r = self.s.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": CORP_ID, "corpsecret": CORP_SECRET},
            timeout=10,
        )
        data = r.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"gettoken failed: {data}")
        return data["access_token"]

    def access_token(self) -> str:
        c = self._cached_token()
        if time.time() >= c["expire_at"]:
            self._cached_token.cache_clear()
            c = self._cached_token()
        return c["token"]

    # ---------- 客服：1:1 发文本 ----------
    def kf_send_text(self, external_userid: str, content: str) -> Dict[str, Any]:
        if not OPEN_KFID:
            return {"errcode": -1, "errmsg": "OPEN_KFID not set (env WECHAT_OPEN_KFID)"}
        url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg?access_token={self.access_token()}"
        payload = {
            "touser": external_userid,
            "open_kfid": OPEN_KFID,
            "msgid": str(int(time.time() * 1000)),
            "msgtype": "text",
            "text": {"content": content},
        }
        return self.s.post(url, json=payload, timeout=10).json()

    # ---------- 客服：生成“开启会话”链接 ----------
    def kf_add_contact_url(self, external_userid: str, scene: str = "wecom_pass2u") -> Optional[str]:
        if not OPEN_KFID:
            raise RuntimeError("OPEN_KFID not set (env WECHAT_OPEN_KFID)")

        url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/add_contact?access_token={self.access_token()}"
        payload = {"open_kfid": OPEN_KFID, "external_userid": external_userid, "scene": scene}
        r = self.s.post(url, json=payload, timeout=10)
        try:
            data = r.json()
        except ValueError:
            # 返回了非 JSON（例如 401/403/502 的 HTML 等），直接抛原文以便定位
            raise RuntimeError(
                f"kf.add_contact non-JSON response: status={r.status_code}, text={r.text[:200]!r}"
            )
        if data.get("errcode") != 0:
            # 常见：40096 invalid external_userid
            raise RuntimeError(f"kf.add_contact failed: {data}")
        return data.get("url")

    # ---------- 客户群欢迎语模板（固定文案场景） ----------
    def create_group_welcome_template(
        self,
        text: Optional[str] = None,
        link: Optional[Dict[str, str]] = None,
        miniprogram: Optional[Dict[str, str]] = None,
    ) -> str:
        url = f"https://qyapi.weixin.qq.com/cgi-bin/externalcontact/group_welcome_template/add?access_token={self.access_token()}"
        payload: Dict[str, Any] = {}
        if text:
            payload["text"] = {"content": text}
        if link:
            payload["link"] = link
        if miniprogram:
            payload["miniprogram"] = miniprogram
        data = self.s.post(url, json=payload, timeout=10).json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"create welcome template failed: {data}")
        return data["template_id"]

    def list_group_welcome_templates(self, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        url = f"https://qyapi.weixin.qq.com/cgi-bin/externalcontact/group_welcome_template/get?access_token={self.access_token()}"
        return self.s.post(url, json={"offset": offset, "limit": limit}, timeout=10).json()

    def delete_group_welcome_template(self, template_id: str) -> Dict[str, Any]:
        url = f"https://qyapi.weixin.qq.com/cgi-bin/externalcontact/group_welcome_template/del?access_token={self.access_token()}"
        return self.s.post(url, json={"template_id": template_id}, timeout=10).json()

    def send_group_welcome(self, chat_id: str, external_userid: str, template_id: Optional[str] = None) -> Dict[str, Any]:
        tpl_id = template_id or WELCOME_TPL_ID
        if not tpl_id:
            return {"errcode": -1, "errmsg": "WELCOME_TPL_ID not set"}
        url = f"https://qyapi.weixin.qq.com/cgi-bin/externalcontact/group_welcome_template/send?access_token={self.access_token()}"
        payload = {"template_id": tpl_id, "chat_id": chat_id, "external_userid": external_userid}
        return self.s.post(url, json=payload, timeout=10).json()
