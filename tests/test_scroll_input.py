# -*- coding: utf-8 -*-
"""左栏滚动输入回归测试：鼠标滚轮 / 触控板 / 触摸屏 / 滚动条 / 区域隔离。

不需要显示器：用轻量桩对象直接测试 ScrollableFrame 的事件处理逻辑，
再静态校验主窗口确实把滚动支持挂到整棵左栏子树（含动态重建的字段）。
"""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

try:
    from jsj_desktop.ui.widgets import ScrollableFrame
    HAS_TK = True
except ImportError:          # 精简版 Python（无 Tcl/Tk）仍可跑静态检查
    ScrollableFrame = None
    HAS_TK = False

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "src" / "jsj_desktop" / "ui" / "widgets.py"
MAIN = ROOT / "src" / "jsj_desktop" / "ui" / "main_window.py"


def frame_with(yview=(0.0, 0.5)):
    """不创建 Tk 窗口，只构造事件处理所需的最小对象。"""
    frame = ScrollableFrame.__new__(ScrollableFrame)
    frame.canvas = MagicMock()
    frame.canvas.yview.return_value = yview
    frame._pan_active = False
    frame._pan_y = 0
    return frame


def wheel_event(delta=0, num=None):
    return SimpleNamespace(delta=delta, num=num)


@unittest.skipUnless(HAS_TK, "当前 Python 未安装 Tcl/Tk，跳过事件逻辑测试")
class ScrollInputTest(unittest.TestCase):
    def test_mouse_wheel_down(self):
        f = frame_with()
        self.assertEqual(f._on_wheel(wheel_event(delta=-120)), "break")
        f.canvas.yview_scroll.assert_called_once_with(3, "units")

    def test_mouse_wheel_up(self):
        f = frame_with((0.4, 0.9))
        f._on_wheel(wheel_event(delta=120))
        f.canvas.yview_scroll.assert_called_once_with(-3, "units")

    def test_trackpad_fine_delta_scrolls_one_line(self):
        f = frame_with()
        f._on_wheel(wheel_event(delta=-1))
        f.canvas.yview_scroll.assert_called_once_with(1, "units")
        f2 = frame_with((0.4, 0.9))       # 不在顶部，才允许向上滚
        f2._on_wheel(wheel_event(delta=40))
        f2.canvas.yview_scroll.assert_called_once_with(-1, "units")

    def test_linux_button_4_and_5(self):
        f = frame_with((0.4, 0.9))
        f._on_wheel(wheel_event(num=4))
        f.canvas.yview_scroll.assert_called_with(-3, "units")
        f2 = frame_with()
        f2._on_wheel(wheel_event(num=5))
        f2.canvas.yview_scroll.assert_called_with(3, "units")

    def test_zero_delta_is_ignored(self):
        f = frame_with()
        f._on_wheel(wheel_event(delta=0))
        f.canvas.yview_scroll.assert_not_called()

    def test_scroll_stops_at_boundaries(self):
        f = frame_with((0.0, 0.5))
        f._on_wheel(wheel_event(delta=120))     # 已到顶部
        f.canvas.yview_scroll.assert_not_called()
        g = frame_with((0.5, 1.0))
        g._on_wheel(wheel_event(delta=-120))   # 已到底部
        g.canvas.yview_scroll.assert_not_called()

    def test_touch_pan_drag(self):
        f = frame_with()
        start = SimpleNamespace(y_root=300)
        move = SimpleNamespace(y_root=220)     # 手指上滑 → 查看下方内容
        end = SimpleNamespace(y_root=220)
        f._on_pan_start(start)
        result = f._on_pan_move(move)
        self.assertEqual(result, "break")
        self.assertGreater(f.canvas.yview_scroll.call_args[0][0], 0)
        f._on_pan_end(end)
        self.assertFalse(f._pan_active)
        before = f.canvas.yview_scroll.call_count
        f._on_pan_move(SimpleNamespace(y_root=100))  # 松手后不再滚动
        self.assertEqual(f.canvas.yview_scroll.call_count, before)

    def test_small_touch_jitter_is_ignored(self):
        f = frame_with()
        f._on_pan_start(SimpleNamespace(y_root=100))
        f._on_pan_move(SimpleNamespace(y_root=98))
        f.canvas.yview_scroll.assert_not_called()


class ScrollWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.widgets = WIDGETS.read_text(encoding="utf-8")
        cls.main = MAIN.read_text(encoding="utf-8")

    def test_all_input_sources_bound(self):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>",
                    "<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>"):
            self.assertIn(seq, self.widgets, "缺少事件绑定：%s" % seq)

    def test_bindtags_used_instead_of_global_binding(self):
        self.assertIn("bind_class(self._wheel_tag", self.widgets)
        self.assertIn("bindtags(", self.widgets)
        self.assertNotIn("bind_all(", self.widgets,
                         "全局滚轮绑定会影响右侧实时终端，必须避免")

    def test_scrollable_frame_scrollbar_unchanged(self):
        self.assertIn("yscrollcommand=self.vsb.set", self.widgets)
        self.assertIn("command=self.canvas.yview", self.widgets)

    def test_left_panel_tree_is_rebound(self):
        # _build_main 1 处 + _render_fields 2 处（空字段分支与正常分支）
        self.assertGreaterEqual(
            self.main.count("self.left_scroll.bind_wheel_tree()"), 3,
            "动态重建字段后必须重新挂滚动支持")

    def test_right_terminal_is_not_in_left_tree(self):
        self.assertIn("self.term_frame", self.main)
        self.assertNotIn("self.log_view.bind_wheel_tree", self.main)


if __name__ == "__main__":
    unittest.main()
