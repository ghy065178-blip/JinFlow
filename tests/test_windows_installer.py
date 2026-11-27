# -*- coding: utf-8 -*-
"""Windows setup.exe and focus-safe UI wiring checks that run on every host."""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsInstallerSpecTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.iss = (ROOT / "packaging" / "windows_installer.iss").read_text(
            encoding="utf-8")
        cls.build = (ROOT / "packaging" / "build.py").read_text(encoding="utf-8")
        cls.workflow = (ROOT / ".github" / "workflows" /
                        "release.yml").read_text(encoding="utf-8")
        cls.ui = (ROOT / "src" / "jsj_desktop" / "ui" /
                  "main_window.py").read_text(encoding="utf-8")

    def test_setup_registers_install_launch_and_uninstall(self):
        for marker in ("AppName=JinFlow", "DefaultDirName={localappdata}",
                       "[Files]", "[Icons]", "[Run]", "[UninstallDelete]",
                       "UninstallDisplayName=JinFlow"):
            self.assertIn(marker, self.iss)

    def test_build_and_release_workflow_include_setup_exe(self):
        for marker in ("def make_windows_setup", "OutputBaseName",
                       "*.exe", "write_checksums"):
            self.assertIn(marker, self.build)
        for marker in ("Install Inno Setup", "JinFlow-${{ matrix.target }}-Setup.exe",
                       "JinFlow-*.exe"):
            self.assertIn(marker, self.workflow)

    def test_toast_does_not_create_a_second_window(self):
        section = self.ui.split("def _build_toast", 1)[1].split(
            "def _build_preview_window", 1)[0]
        self.assertNotIn("tk.Toplevel", section)
        self.assertIn("place_forget", section)

    def test_brand_and_removed_copy_are_current(self):
        self.assertIn('text="JinFlow"', self.ui)
        self.assertIn('text="配置编辑 · 实时终端监控"', self.ui)
        self.assertNotIn("原脚本零改动 · 配置编辑", self.ui)
        self.assertNotIn("本平台不修改任何原有代码", self.ui)


if __name__ == "__main__":
    unittest.main()
