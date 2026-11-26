# -*- coding: utf-8 -*-
"""测试公共工具：加载合成样例，构造与旧版一致的字段/规则结构。"""
import json

from jsj_desktop.core.endpoint import Endpoint
from tests import FIXTURES


def load_fixture(name="sample_form.json"):
    with open(FIXTURES / name, "r", encoding="utf-8") as fp:
        return json.load(fp)


def normalized(payload=None):
    """把 GraphQL 响应转成 fetch_form() 产出的 fields/rules 结构。"""
    payload = payload or load_fixture()
    pf = payload["data"]["publishedForm"]
    form = pf["form"]
    fields = []
    for n in form["fields"]["nodes"]:
        fields.append({
            "api": n["apiCode"],
            "label": n.get("label") or n["apiCode"],
            "typename": n["__typename"],
            "required": "presence" in (n.get("validations") or []),
            "multi": n["__typename"] == "Checkboxes",
            "choices": [(c["value"], c["name"])
                        for c in (n.get("choices") or [])],
        })
    rules = {r["target"]: r
             for r in form.get("fieldRulesGroupByTarget", [])}
    return fields, rules


class FakeEndpoint(Endpoint):
    """不联网的端点：可预置 CHECK_QUERY / 校时 / 提交的响应。"""

    def __init__(self, payload=None, submit_response=None, date=""):
        super().__init__("https://jsj.top", "EXAMPLE")
        self.payload = payload or load_fixture()
        self.submit_response = submit_response
        self.date = date
        self.calls = []

    def post_json(self, body, timeout=15):
        self.calls.append(body)
        query = body.get("query", "")
        if "createPublishedFormEntry" in query:
            return 200, self.submit_response or {"data": {}}, self.date
        if "__typename" in query and "publishedForm" not in query:
            return 200, {"data": {"__typename": "Query"}}, self.date
        return 200, self.payload, self.date
