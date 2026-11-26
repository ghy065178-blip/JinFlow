# -*- coding: utf-8 -*-
"""链接解析与表单结构拉取（含验证码 / 网络异常 / 开放时间解析）。"""
import copy
import unittest

from jsj_desktop.core.endpoint import Endpoint, parse_form_url
from jsj_desktop.core.submit import build_input, submit_once
from tests.helpers import FakeEndpoint, load_fixture


class EndpointTest(unittest.TestCase):
    def test_parse_full_url_and_token(self):
        self.assertEqual(
            parse_form_url("https://jsj.top/f/AbCd12?from=share"),
            ("https://jsj.top", "AbCd12", "https://jsj.top/f/AbCd12"))
        self.assertEqual(
            parse_form_url("https://other.example.com/f/TOKEN9"),
            ("https://other.example.com", "TOKEN9",
             "https://other.example.com/f/TOKEN9"))
        self.assertEqual(parse_form_url("  abcd1234  "),
                         ("https://jsj.top", "abcd1234",
                          "https://jsj.top/f/abcd1234"))
        self.assertIsNone(parse_form_url(""))
        self.assertIsNone(parse_form_url("abc"))
        self.assertIsNone(parse_form_url("https://jsj.top/other/page"))

    def test_fetch_form_fields_and_rules(self):
        ep = FakeEndpoint()
        info = ep.fetch_form()
        self.assertTrue(info["ok"])
        self.assertEqual(info["name"], "示例活动（合成数据）")
        self.assertEqual(info["status"], "not_opened")
        self.assertFalse(info["captcha"])
        self.assertEqual(len(info["fields"]), 8)
        self.assertEqual(set(info["rules"]), {"field_5", "field_6"})
        self.assertEqual(info["open_dt"].strftime("%Y-%m-%d %H:%M:%S"),
                         "2030-01-01 10:00:00")
        self.assertEqual(info["fields"][7]["multi"], True)
        self.assertEqual(info["fields"][0]["required"], True)

    def test_captcha_detected(self):
        payload = copy.deepcopy(load_fixture())
        payload["data"]["publishedForm"]["form"]["setting"]["enableCaptcha"] = True
        self.assertTrue(FakeEndpoint(payload).fetch_form()["captcha"])

    def test_network_error(self):
        class Broken(Endpoint):
            def post_json(self, _payload, timeout=15):
                return -1, {"_network_error": "URLError(...)"}, None
        info = Broken("https://jsj.top", "EXAMPLE").fetch_form()
        self.assertFalse(info["ok"])
        self.assertIn("网络请求失败", info["error"])

    def test_missing_form(self):
        info = FakeEndpoint({"data": {"publishedForm": None}}).fetch_form()
        self.assertFalse(info["ok"])
        self.assertIn("找不到该表单", info["error"])

    def test_build_input_shape(self):
        self.assertEqual(build_input("EXAMPLE", {"field_1": "v"}, 3.456), {
            "formId": "EXAMPLE", "entryAttributes": {"field_1": "v"},
            "fillingDuration": 3.46, "forceSubmit": False,
            "hasPreferential": False})

    def _classify(self, response):
        ep = FakeEndpoint(submit_response=response)
        return submit_once(ep, "EXAMPLE", {}, 1.0)[0]

    def test_submit_classification(self):
        self.assertEqual(self._classify({
            "data": {"createPublishedFormEntry": {"entryToken": "tk-1",
                                                  "errors": []}}}), "success")
        self.assertEqual(self._classify({
            "data": {"createPublishedFormEntry": {
                "errors": [{"code": 400, "message": "暂未开放"}]}}}), "wait")
        self.assertEqual(self._classify({
            "data": {"createPublishedFormEntry": {
                "errors": [{"code": 400, "message": "该学号已经提交过"}],
                "submitterExists": True}}}), "maybe")
        self.assertEqual(self._classify({
            "data": {"createPublishedFormEntry": {
                "errors": [{"code": 400, "message": "字段不合法"}]}}}), "fatal")
        self.assertEqual(self._classify({"errors": [{"message": "bad"}]}), "fatal")


if __name__ == "__main__":
    unittest.main()
