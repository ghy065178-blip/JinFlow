# -*- coding: utf-8 -*-
"""界面一致性回归测试：主窗口与旧版 control_panel.html 逐项对齐。

静态检查（不需要显示器 / tkinter）：
  * 原面板的全部标签、按钮、复选框、提示文案都在主窗口源码中出现；
  * 原面板的全部交互行为都有对应的实现方法；
  * 主题配色逐项复刻原 CSS 变量。
"""
import json
import unittest
from pathlib import Path

from tests import FIXTURES

ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = ROOT / "src" / "jsj_desktop" / "ui" / "main_window.py"
THEME_SOURCE = ROOT / "src" / "jsj_desktop" / "ui" / "theme.py"


class UiParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURES / "panel_ui_spec.json", "r",
                  encoding="utf-8") as fp:
            cls.spec = json.load(fp)
        cls.ui = UI_SOURCE.read_text(encoding="utf-8")
        cls.theme = THEME_SOURCE.read_text(encoding="utf-8")

    def test_all_labels_present(self):
        missing = [s for s in self.spec["labels"] if s not in self.ui]
        self.assertEqual(missing, [], "主界面缺少原面板文案：%s" % missing)

    def test_all_buttons_present(self):
        missing = [s for s in self.spec["buttons"] if s not in self.ui]
        self.assertEqual(missing, [], "主界面缺少原面板按钮：%s" % missing)

    def test_all_checkboxes_present(self):
        missing = [s for s in self.spec["checkboxes"] if s not in self.ui]
        self.assertEqual(missing, [], "主界面缺少原面板复选框：%s" % missing)

    def test_all_toasts_present(self):
        missing = [s for s in self.spec["toasts"] if s not in self.ui]
        self.assertEqual(missing, [], "主界面缺少原面板反馈文案：%s" % missing)

    def test_all_behaviors_implemented(self):
        missing = [name for name in self.spec["behaviors"]
                   if ("def %s(" % name) not in self.ui]
        self.assertEqual(missing, [], "缺少原面板交互实现：%s" % missing)

    def test_layout_regions_present(self):
        widgets = {"header": "_build_header", "taskbar": "_build_taskbar",
                   "cards": "_build_cards", "left_scroll": "self.left_scroll",
                   "term_frame": "self.term_frame", "toast": "_build_toast"}
        for region, marker in widgets.items():
            self.assertIn(marker, self.ui, "缺少布局区域：%s" % region)
        self.assertNotIn("ttk.Notebook", self.ui,
                          "主界面应为单页面板，不应再使用标签页切换")

    def test_theme_control_and_beijing_clock_remain_in_existing_regions(self):
        for marker in ("theme_mode", "theme_buttons", "clock_var",
                       "apply_theme", "format_beijing_time"):
            self.assertIn(marker, self.ui,
                          "主题或北京时间入口缺少：%s" % marker)

    def test_theme_defines_dark_palette_semantic_tokens(self):
        for key in ("bg", "surface", "surface2", "border", "text",
                    "muted", "dim", "teal", "blue", "green", "amber",
                    "red", "purple"):
            self.assertIn('"%s":' % key, self.theme,
                          "主题缺少语义令牌：%s" % key)
        self.assertIn("_DARK_PALETTE", self.theme)
        self.assertIn("_LIGHT_PALETTE", self.theme)

    def test_single_page_no_local_server(self):
        for forbidden in ("ThreadingHTTPServer", "127.0.0.1:8765", "EventSource"):
            self.assertNotIn(forbidden, self.ui,
                              "主界面不应依赖本地 HTTP 服务：%s" % forbidden)


if __name__ == "__main__":
    unittest.main()
