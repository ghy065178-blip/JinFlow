# -*- coding: utf-8 -*-
"""黄金数据测试：配置翻译与最终 entryAttributes 与预期完全一致。"""
import json
import unittest

from jsj_desktop.core.mapping import (build_attributes, chosen_to_config,
                                      config_to_chosen, display_rows)
from tests import FIXTURES
from tests.helpers import normalized


class MappingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURES / "expected_attributes.json", "r",
                  encoding="utf-8") as fp:
            cls.golden = json.load(fp)
        cls.fields, cls.rules = normalized()

    def test_build_attributes_golden(self):
        chosen = config_to_chosen(self.golden["config"], self.fields)
        attributes, display = build_attributes(self.fields, self.rules, chosen)
        self.assertEqual(attributes, self.golden["attributes"])
        self.assertEqual(display, self.golden["display"])

    def test_chosen_to_config_roundtrip(self):
        """按中文标签存储的格式与旧版一致：往返后仍能生成同样的提交数据。"""
        cfg = self.golden["config"]
        chosen = config_to_chosen(cfg, self.fields)
        rebuilt = chosen_to_config(cfg["表单链接"], self.fields, chosen)
        again = config_to_chosen(rebuilt, self.fields)
        self.assertEqual(build_attributes(self.fields, self.rules, again)[0],
                         self.golden["attributes"])
        self.assertEqual(rebuilt["表单链接"], cfg["表单链接"])
        self.assertEqual(rebuilt["培养层次"], "硕士")
        self.assertEqual(rebuilt["可多选"], ["选项甲"])

    def test_unmatched_old_values_are_dropped(self):
        cfg = dict(self.golden["config"])
        cfg["旧表单残留字段"] = "不应出现"
        chosen = config_to_chosen(cfg, self.fields)
        self.assertNotIn("cfg:旧表单残留字段", chosen)
        self.assertNotIn("旧表单残留字段",
                         chosen_to_config(cfg["表单链接"], self.fields, chosen))

    def test_invalid_choice_is_rejected(self):
        cfg = dict(self.golden["config"])
        cfg["培养层次"] = "不存在的选项"
        chosen = config_to_chosen(cfg, self.fields)
        self.assertNotIn("field_3", chosen)
        with self.assertRaises(ValueError):
            build_attributes(self.fields, self.rules, chosen)

    def test_hidden_field_not_submitted(self):
        """培养层次=博士 时，「班级」因联动规则隐藏，不应出现在提交数据里。"""
        cfg = dict(self.golden["config"])
        cfg["培养层次"] = "博士"
        cfg["年级"] = "2025级"
        chosen = config_to_chosen(cfg, self.fields)
        attributes, _ = build_attributes(self.fields, self.rules, chosen)
        self.assertNotIn("field_5", attributes)
        self.assertIn("field_6", attributes)  # 矛盾分支退化后电话仍可见

    def test_display_rows(self):
        chosen = config_to_chosen(self.golden["config"], self.fields)
        rows = dict(display_rows(self.fields, self.rules, chosen))
        self.assertEqual(rows["培养层次"], "硕士")
        self.assertEqual(rows["可多选"], "选项甲")


if __name__ == "__main__":
    unittest.main()
