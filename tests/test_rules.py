# -*- coding: utf-8 -*-
"""联动显示规则：and / or / 矛盾分支退化 / not_equal。"""
import unittest

from jsj_desktop.core.rules import (_branches_contradictory, _eval_branch,
                                    is_visible)
from tests.helpers import normalized


class RulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fields, cls.rules = normalized()
        cls.by_api = {f["api"]: f for f in cls.fields}

    def test_no_rule_always_visible(self):
        self.assertTrue(is_visible(self.by_api["field_1"], self.rules, {}))

    def test_and_rule_requires_both(self):
        f = self.by_api["field_5"]
        self.assertTrue(is_visible(f, self.rules,
                                   {"field_3": "A1", "field_4": "B1"}))
        self.assertFalse(is_visible(f, self.rules,
                                    {"field_3": "A1", "field_4": "B2"}))
        self.assertFalse(is_visible(f, self.rules, {"field_3": "A1"}))

    def test_contradictory_branches_degrade_to_any(self):
        f = self.by_api["field_6"]
        self.assertTrue(_branches_contradictory(
            self.rules["field_6"]["conditionGroup"]["conditionGroups"]))
        self.assertTrue(is_visible(f, self.rules, {"field_3": "A1"}))
        self.assertTrue(is_visible(f, self.rules, {"field_3": "A2"}))

    def test_or_operator(self):
        rules = {"field_9": {"conditionGroup": {
            "operator": "or",
            "conditionGroups": [
                {"operator": "and", "conditions": [
                    {"trigger": "field_3", "comparator": "equal", "value": ["A1"]}]},
                {"operator": "and", "conditions": [
                    {"trigger": "field_3", "comparator": "equal", "value": ["A2"]}]},
            ]}}}
        f = {"api": "field_9"}
        self.assertTrue(is_visible(f, rules, {"field_3": "A2"}))
        self.assertFalse(is_visible(f, rules, {"field_3": "ZZ"}))

    def test_not_equal(self):
        branch = {"operator": "and", "conditions": [
            {"trigger": "f", "comparator": "not_equal", "value": ["X"]}]}
        self.assertTrue(_eval_branch(branch, {"f": "Y"}))
        self.assertFalse(_eval_branch(branch, {"f": "X"}))
        self.assertFalse(_eval_branch(branch, {}))


if __name__ == "__main__":
    unittest.main()
