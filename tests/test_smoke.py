# -*- coding: utf-8 -*-
"""入口自检与跨平台路径（不启动窗口、不联网）。"""
import os
import tempfile
import unittest
from pathlib import Path

from jsj_desktop.app import main
from jsj_desktop.data import paths


class SmokeTest(unittest.TestCase):
    def test_self_test_entry(self):
        self.assertEqual(main(["--self-test"]), 0)

    def test_data_dir_override(self):
        old = os.environ.get("JSJ_DATA_DIR")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["JSJ_DATA_DIR"] = tmp
                self.assertEqual(Path(paths.data_dir()), Path(tmp))
                self.assertEqual(paths.profiles_path().name, "profiles.json")
                self.assertEqual(paths.task_config_path("t1").name,
                                 "报名信息.json")
        finally:
            if old is None:
                os.environ.pop("JSJ_DATA_DIR", None)
            else:
                os.environ["JSJ_DATA_DIR"] = old

    def test_platform_label(self):
        system, arch = paths.platform_label()
        self.assertIn(system, ("windows", "macos", "linux"))
        self.assertTrue(arch)

    def test_version(self):
        import jsj_desktop
        self.assertTrue(jsj_desktop.__version__)


if __name__ == "__main__":
    unittest.main()
