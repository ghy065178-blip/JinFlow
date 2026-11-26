# -*- coding: utf-8 -*-
"""等价性对照：桌面版核心函数与旧版 auto_submit.py 的输出逐项一致。

legacy/auto_submit_reference.py 是旧版的只读副本（仅移除了内置活动 token）。
本测试不联网、不读写任何用户数据。
"""
import importlib.util
import json
import unittest
from pathlib import Path

from jsj_desktop.core import mapping as new_mapping
from jsj_desktop.core import rules as new_rules
from jsj_desktop.core.endpoint import parse_form_url as new_parse
from jsj_desktop.core.submit import build_input as new_build_input
from jsj_desktop.core.submit import submit_once as new_submit_once
from tests import FIXTURES
from tests.helpers import FakeEndpoint, normalized

LEGACY = Path(__file__).resolve().parents[1] / "legacy" / \
    "auto_submit_reference.py"


def load_legacy():
    spec = importlib.util.spec_from_file_location("legacy_auto_submit", LEGACY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LegacyParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = load_legacy()
        cls.fields, cls.rules = normalized()
        with open(FIXTURES / "expected_attributes.json", "r",
                  encoding="utf-8") as fp:
            cls.golden = json.load(fp)

    def test_parse_form_url(self):
        samples = ["https://jsj.top/f/AbCd12?x=1", "abcd1234", "", "abc",
                   "https://other.example.com/f/TOKEN9",
                   "https://jsj.top/other/page"]
        for s in samples:
            self.assertEqual(new_parse(s), self.old.parse_form_url(s), s)

    def test_visibility_matrix(self):
        combos = [{}, {"field_3": "A1"}, {"field_3": "A2"},
                  {"field_3": "A1", "field_4": "B1"},
                  {"field_3": "A1", "field_4": "B2"},
                  {"field_3": "A2", "field_4": "B1"}]
        for chosen in combos:
            for f in self.fields:
                self.assertEqual(new_rules.is_visible(f, self.rules, chosen),
                                 self.old.is_visible(f, self.rules, chosen),
                                 (f["api"], chosen))

    def test_config_to_chosen(self):
        self.assertEqual(
            new_mapping.config_to_chosen(self.golden["config"], self.fields),
            self.old.config_to_chosen(self.golden["config"], self.fields))

    def test_chosen_to_config(self):
        chosen = self.old.config_to_chosen(self.golden["config"], self.fields)
        self.assertEqual(
            new_mapping.chosen_to_config("https://jsj.top/f/EXAMPLE",
                                         self.fields, chosen),
            self.old.chosen_to_config("https://jsj.top/f/EXAMPLE",
                                      self.fields, chosen))

    def test_build_attributes(self):
        chosen = self.old.config_to_chosen(self.golden["config"], self.fields)
        self.assertEqual(
            new_mapping.build_attributes(self.fields, self.rules, chosen),
            self.old.build_attributes(self.fields, self.rules, chosen))
        self.assertEqual(
            new_mapping.build_attributes(self.fields, self.rules, chosen)[0],
            self.golden["attributes"])

    def test_fill_form_only_missing(self):
        cfg = self.golden["config"]
        old_chosen = self.old.config_to_chosen(cfg, self.fields)
        new_chosen = new_mapping.config_to_chosen(cfg, self.fields)
        self.old._ask = lambda prompt, default=None: default
        self.assertEqual(
            new_mapping.fill_form(self.fields, self.rules, new_chosen,
                                  only_missing=True),
            self.old.fill_form(self.fields, self.rules, old_chosen,
                               only_missing=True))

    def test_build_input(self):
        self.old.TOKEN = "EXAMPLE"
        self.old.ENTRY_ATTRIBUTES = self.golden["attributes"]
        self.assertEqual(new_build_input("EXAMPLE", self.golden["attributes"],
                                         3.456),
                         self.old.build_input(3.456))

    def test_submit_once_classification(self):
        responses = [
            {"data": {"createPublishedFormEntry": {"entryToken": "tk", "errors": []}}},
            {"data": {"createPublishedFormEntry": {"errors": [
                {"code": 400, "message": "暂未开放"}]}}},
            {"data": {"createPublishedFormEntry": {"errors": [
                {"code": 400, "message": "已经提交过"}], "submitterExists": True}}},
            {"data": {"createPublishedFormEntry": {"errors": [
                {"code": 400, "message": "字段不合法"}]}}},
            {"errors": [{"message": "bad"}]},
        ]
        for resp in responses:
            self.old.gql = lambda q, v=None, timeout=12, r=resp: (200, r, None)
            old_result = self.old.submit_once(1.0)
            new_result = new_submit_once(
                FakeEndpoint(submit_response=resp), "EXAMPLE", {}, 1.0)
            self.assertEqual(new_result, old_result, resp)


if __name__ == "__main__":
    unittest.main()
