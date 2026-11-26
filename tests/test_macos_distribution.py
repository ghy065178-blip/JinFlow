# -*- coding: utf-8 -*-
"""macOS 分发方式回归测试：避免再发布「解压后 .app 打不开」的包。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "packaging"))

import build as packaging_build          # noqa: E402
import check_no_pii                       # noqa: E402

BUILD_PY = (ROOT / "packaging" / "build.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" /
            "release.yml").read_text(encoding="utf-8")


class MacOsDistributionTest(unittest.TestCase):

    def test_macos_release_notes_explain_root_cause(self):
        notes = packaging_build.RELEASE_NOTES_MACOS
        for keyword in ("iCloud", "quarantine", "xattr -dr", "dmg",
                        "应用程序", "无法打开", "符号链接"):
            self.assertIn(keyword, notes, "首次运行说明缺少：%s" % keyword)

    def test_windows_release_notes_do_not_contain_mac_commands(self):
        notes = packaging_build.RELEASE_NOTES_WINDOWS
        self.assertIn("SmartScreen", notes)
        self.assertNotIn("hdiutil", notes)
        self.assertNotIn("xattr", notes)

    def test_build_re_signs_app_after_copy(self):
        # 复制 .app 后必须重做 ad-hoc 签名，保证 CodeResources 与内容一致
        self.assertIn('"codesign", "--force", "--deep", "--sign", "-"',
                      BUILD_PY)
        self.assertIn('"codesign", "--verify", "--deep", "--strict"', BUILD_PY)

    def test_scheme_b_icon_assets_are_present_and_wired(self):
        icons = ROOT / "packaging" / "icons"
        for name in ("app.svg", "app.icns", "app.ico"):
            path = icons / name
            self.assertTrue(path.exists(), "缺少图标资源：%s" % name)
            self.assertGreater(path.stat().st_size, 0)
        source = (icons / "app.svg").read_text(encoding="utf-8")
        for marker in ("linearGradient", "stroke=\"#ffffff\"", "circle"):
            self.assertIn(marker, source)
        self.assertIn('"packaging" / "icons" / "app.icns"', BUILD_PY)
        self.assertIn('"packaging" / "icons" / "app.ico"', BUILD_PY)

    def test_make_dmg_uses_hdiutil_readonly_image(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dist"
            stage = out / "stage" / "macos-arm64"
            (stage / "JinshujuDesktop.app").mkdir(parents=True)
            (stage / "README-RELEASE.txt").write_text("ok", encoding="utf-8")
            with patch.object(packaging_build, "run") as run:
                dmg = packaging_build.make_dmg("macos-arm64", out)
            cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "hdiutil")
        self.assertIn("create", cmd)
        self.assertIn("-srcfolder", cmd)
        self.assertIn("UDZO", cmd)
        self.assertTrue(str(dmg).endswith("JinshujuDesktop-macos-arm64.dmg"))

    def test_checksums_cover_both_zip_and_dmg(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "a.zip").write_bytes(b"zip")
            (out / "a.dmg").write_bytes(b"dmg")
            lines = packaging_build.write_checksums(out)
        names = [line.split()[-1] for line in lines]
        self.assertIn("a.zip", names)
        self.assertIn("a.dmg", names)

    def test_scan_artifact_dispatches_dmg(self):
        sentinel = [("x.dmg", 0, "sentinel")]
        with patch.object(check_no_pii, "scan_dmg", return_value=sentinel) as m:
            result = check_no_pii.scan_artifact(ROOT / "dist-test" / "x.dmg")
        self.assertEqual(result, sentinel)
        m.assert_called_once()

    @unittest.skipIf(sys.platform == "darwin", "仅在非 macOS 上验证跳过逻辑")
    def test_scan_dmg_is_noop_when_not_building_on_macos(self):
        with patch.object(check_no_pii.subprocess, "run") as run:
            self.assertEqual(check_no_pii.scan_dmg("x.dmg"), [])
        run.assert_not_called()

    def test_release_workflow_uploads_and_verifies_dmg(self):
        for keyword in ("dist/*.dmg", "JinshujuDesktop-*.dmg",
                        "Verify macOS distribution (user flow)",
                        "ditto -x -k", "hdiutil attach",
                        "codesign --verify --deep --strict",
                        "--check-tls"):
            self.assertIn(keyword, WORKFLOW, "Release 工作流缺少：%s" % keyword)

    def test_build_main_scans_dmg_before_publishing(self):
        self.assertIn("dmg = make_dmg(target, out_root)", BUILD_PY)
        self.assertIn("check_no_pii.scan_artifact(dmg)", BUILD_PY)

    def test_pii_scanner_rejects_unknown_non_zip_artifact(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "weird.bin"
            p.write_bytes(b"\x00\x01")
            findings = check_no_pii.scan_artifact(p)
        self.assertTrue(findings, "非 zip/DMG 的发布包必须报错而不是静默放行")


if __name__ == "__main__":
    unittest.main()
