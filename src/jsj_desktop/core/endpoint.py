# -*- coding: utf-8 -*-
"""表单链接解析、GraphQL 通信与表单结构拉取。

与旧版 auto_submit.py 的第 二/三/四 节逐行等价，仅把模块级全局变量
（BASE_URL / TOKEN / GRAPHQL_URL）改为 Endpoint 实例属性，使多任务可以
各自持有独立端点而逻辑完全一致。
"""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime

from .constants import (CHECK_QUERY, CST, DEFAULT_BASE_URL, USER_AGENT)

_URL_RE = re.compile(r"https?://([a-zA-Z0-9.\-]+)/f/([A-Za-z0-9]+)")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{4,}$")


def parse_form_url(text):
    """从用户输入解析 (base_url, token, form_url)，无法识别返回 None。

    支持完整链接（任意金数据域名，可带查询参数）或仅输入 token。
    与旧版 parse_form_url 完全一致。
    """
    t = (text or "").strip()
    m = _URL_RE.search(t)
    if m:
        host, token = m.group(1), m.group(2)
        base = f"https://{host}"
        return base, token, f"{base}/f/{token}"
    if _TOKEN_RE.match(t):
        return DEFAULT_BASE_URL, t, f"{DEFAULT_BASE_URL}/f/{t}"
    return None


class Endpoint:
    """一次任务的表单端点。所有网络请求都经过 post_json，便于测试注入。"""

    def __init__(self, base_url=DEFAULT_BASE_URL, token=""):
        self.setup(base_url, token)

    def setup(self, base_url, token):
        self.base_url = base_url
        self.token = token
        self.form_url = f"{base_url}/f/{token}"
        self.graphql_url = f"{base_url}/graphql/f/{token}"

    def set_from_link(self, text):
        parsed = parse_form_url(text)
        if parsed is None:
            return False
        self.setup(parsed[0], parsed[1])
        return True

    def post_json(self, payload, timeout=15):
        """POST GraphQL，返回 (http_status, data_dict, server_date_str)。"""
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.graphql_url, data=body, method="POST",
            headers={
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": self.base_url,
                "Referer": self.form_url,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, json.loads(raw), resp.headers.get("Date")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw), e.headers.get("Date")
            except Exception:
                return e.code, {"_raw": raw}, e.headers.get("Date")
        except Exception as e:
            return -1, {"_network_error": repr(e)}, None

    def gql(self, query, variables=None, timeout=15):
        return self.post_json({"query": query, "variables": variables or {}}, timeout)

    def fetch_form(self):
        """拉取本次表单结构。

        成功返回 dict(ok=True, fields, rules, name, status, captcha, open_dt)；
        失败返回 dict(ok=False, error=说明)。字段/规则结构与旧版完全相同。
        """
        result = {"ok": False, "error": "", "fields": [], "rules": {},
                  "name": "", "status": "", "captcha": False, "open_dt": None}

        status, data, _ = self.gql(CHECK_QUERY, {"id": self.token})
        if status == -1:
            result["error"] = f"网络请求失败：{data.get('_network_error', '')}"
            return result
        if status != 200 or "data" not in data or not data.get("data"):
            result["error"] = f"表单接口返回异常（HTTP {status}）：" \
                              f"{json.dumps(data, ensure_ascii=False)[:300]}"
            return result

        pf = data["data"]["publishedForm"]
        if not pf:
            result["error"] = "找不到该表单（链接或 token 可能有误，或表单已删除）。"
            return result

        form = pf["form"]
        result["ok"] = True
        result["name"] = form.get("name", "")
        result["status"] = (pf.get("status") or {}).get("key", "")
        result["captcha"] = bool((form.get("setting") or {}).get("enableCaptcha"))

        fields = []
        for n in form["fields"]["nodes"]:
            api = n.get("apiCode")
            typename = n.get("__typename") or n.get("type") or ""
            choices = [(c.get("value"), c.get("name"))
                       for c in (n.get("choices") or [])]
            fields.append({
                "api": api,
                "label": n.get("label") or api,
                "typename": typename,
                "required": "presence" in (n.get("validations") or []),
                "multi": typename == "Checkboxes",
                "choices": choices,
            })
        result["fields"] = fields

        rules = {}
        for r in (form.get("fieldRulesGroupByTarget") or []):
            rules[r["target"]] = r
        result["rules"] = rules

        rule = (pf.get("interceptionSetting") or {}
                ).get("byTimeRangeCloseRule") or {}
        start = rule.get("startTime")
        if start:
            result["open_dt"] = datetime.fromisoformat(start).astimezone(CST)
        return result
