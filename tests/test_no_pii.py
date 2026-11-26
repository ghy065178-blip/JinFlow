# -*- coding: utf-8 -*-
"""仓库与发布包隐私守卫：确保没有内置个人信息 / 真实活动链接 / 凭据。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_no_pii  # noqa: E402


class PiiTest(unittest.TestCase):
    def test_detector_self_test(self):
        self.assertEqual(check_no_pii.self_test(), 0,
                         "检测器自检失败：检测规则未覆盖样例")

    def test_repo_is_clean(self):
        findings = check_no_pii.scan_tree(ROOT)
        self.assertEqual(findings, [], "仓库中发现敏感数据：%s" % findings[:5])

    def test_forbidden_filenames_detected(self):
        found = []
        for name in ["报名信息.json", "个人档案.json", "报名信息.backup.json",
                     "panel_url.txt", ".env", "server.pem"]:
            check_no_pii._check_name(name, "somewhere/" + name, found)
        self.assertGreaterEqual(len(found), 6)

    def test_placeholder_json_is_allowed(self):
        text = (ROOT / "tests" / "fixtures" /
                "expected_attributes.json").read_text(encoding="utf-8")
        found = []
        check_no_pii._scan_json("fixture.json", text, found)
        self.assertEqual(found, [])

    def test_synthetic_paths_with_zip_prefix_are_exempt(self):
        found = []
        check_no_pii._scan_text(
            "jinshuju-registration-desktop/tests/test_endpoint.py",
            'link = "https://jsj.top/f/AbCd12"', found)
        self.assertEqual(found, [])
        check_no_pii._scan_text(
            "docs/GUIDE.md", 'link = "https://jsj.top/f/AbCd12"', found)
        self.assertTrue(found, "非合成目录中的真实链接必须被检出")


if __name__ == "__main__":
    unittest.main()
