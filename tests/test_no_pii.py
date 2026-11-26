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

    def test_runtime_tcl_encoding_tables_are_not_false_positives(self):
        """PyInstaller 随包的 Tcl/Tk 编码表含大量长数字，不能误判为个人信息。"""
        import os
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "release.zip")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(
                    "JinshujuDesktop/_internal/_tcl_data/encoding/big5.enc",
                    "0x8140 123456789012345678\n0x8141 13800000000\n")
                zf.writestr(
                    "JinshujuDesktop.app/Contents/Resources/_tcl_data/"
                    "encoding/macJapan.enc",
                    "0000 908456789012345678\n18000000000\n")
            self.assertEqual(check_no_pii.scan_artifact(archive), [])

    def test_macos_archive_metadata_is_ignored(self):
        import os
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "metadata.zip")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("__MACOSX/JinshujuDesktop.app/._cacert.pem", "metadata")
                zf.writestr("._JinshujuDesktop", "metadata")
            self.assertEqual(check_no_pii.scan_artifact(archive), [])

    def test_release_package_with_real_personal_file_still_blocked(self):
        import os
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "bad-release.zip")
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("JinshujuDesktop/_internal/报名信息.json",
                            '{"姓名": "张三"}')
            findings = check_no_pii.scan_artifact(archive)
            self.assertTrue(findings, "真实个人信息文件仍必须被拦截")

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
