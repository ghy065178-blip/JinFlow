# -*- coding: utf-8 -*-
"""覆盖左栏滚动输入、区域隔离及不同窗口尺寸下的档案按钮。"""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from jsj_desktop.ui.widgets import ScrollableFrame
    HAS_TK = True
except ImportError:          # 精简版 Python（无 Tcl/Tk）仍可跑静态检查
    ScrollableFrame = None
    HAS_TK = False

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = ROOT / "src" / "jsj_desktop" / "ui" / "widgets.py"
MAIN = ROOT / "src" / "jsj_desktop" / "ui" / "main_window.py"


def frame_with(yview=(0.0, 0.5), windowing_system="win32"):
    """不创建 Tk 窗口，只构造事件处理所需的最小对象。"""
    frame = ScrollableFrame.__new__(ScrollableFrame)
    frame.canvas = MagicMock()
    frame.canvas.yview.return_value = yview
    frame._pan_active = False
    frame._windowing_system = windowing_system
    frame._wheel_pixels = 0
    frame._wheel_after = None
    frame.after = MagicMock(return_value="wheel-frame")
    return frame


def wheel_event(delta=0, num=None):
    return SimpleNamespace(delta=delta, num=num)


@unittest.skipUnless(HAS_TK, "当前 Python 未安装 Tcl/Tk，跳过事件逻辑测试")
class ScrollInputTest(unittest.TestCase):
    def test_mouse_wheel_down(self):
        f = frame_with()
        self.assertEqual(f._on_wheel(wheel_event(delta=-120)), "break")
        f._flush_wheel()
        f.canvas.yview_scroll.assert_called_once_with(60, "units")

    def test_mouse_wheel_up(self):
        f = frame_with((0.4, 0.9))
        f._on_wheel(wheel_event(delta=120))
        f._flush_wheel()
        f.canvas.yview_scroll.assert_called_once_with(-60, "units")

    def test_mac_trackpad_deltas_accumulate_in_one_frame(self):
        f = frame_with(windowing_system="aqua")
        for delta in (-1, -4, 2):
            f._on_wheel(wheel_event(delta=delta))
        f.after.assert_called_once()
        f.canvas.yview_scroll.assert_not_called()
        f._flush_wheel()
        f.canvas.yview_scroll.assert_called_once_with(24, "units")

    def test_windows_fractional_deltas_are_not_lost(self):
        f = frame_with()
        f._on_wheel(wheel_event(delta=-1))
        f._flush_wheel()
        f.canvas.yview_scroll.assert_not_called()
        f._on_wheel(wheel_event(delta=-1))
        f._flush_wheel()
        f.canvas.yview_scroll.assert_called_once_with(1, "units")

    def test_linux_button_4_and_5(self):
        f = frame_with((0.4, 0.9))
        f._on_wheel(wheel_event(num=4))
        f._flush_wheel()
        f.canvas.yview_scroll.assert_called_with(-60, "units")
        f2 = frame_with()
        f2._on_wheel(wheel_event(num=5))
        f2._flush_wheel()
        f2.canvas.yview_scroll.assert_called_with(60, "units")

    def test_zero_delta_is_ignored(self):
        f = frame_with()
        f._on_wheel(wheel_event(delta=0))
        f.canvas.yview_scroll.assert_not_called()

    def test_scroll_stops_at_boundaries(self):
        f = frame_with((0.0, 0.5))
        f._on_wheel(wheel_event(delta=120))     # 已到顶部
        f._flush_wheel()
        f.canvas.yview_scroll.assert_not_called()
        g = frame_with((0.5, 1.0))
        g._on_wheel(wheel_event(delta=-120))   # 已到底部
        g._flush_wheel()
        g.canvas.yview_scroll.assert_not_called()

    def test_touch_pan_drag(self):
        f = frame_with()
        start = SimpleNamespace(y_root=300)
        move = SimpleNamespace(y_root=220)     # 手指上滑 → 查看下方内容
        end = SimpleNamespace(y_root=220)
        f._on_pan_start(start)
        result = f._on_pan_move(move)
        self.assertEqual(result, "break")
        f.canvas.yview_scroll.assert_called_once_with(80, "units")
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

    def test_touch_pan_tracks_each_pixel_after_start_threshold(self):
        f = frame_with()
        f._on_pan_start(SimpleNamespace(y_root=100))
        f._on_pan_move(SimpleNamespace(y_root=98))
        f._on_pan_move(SimpleNamespace(y_root=97))
        f._on_pan_move(SimpleNamespace(y_root=96))
        self.assertEqual([call.args[0] for call in f.canvas.yview_scroll.call_args_list],
                         [3, 1])


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

    def test_scroll_reflow_is_coalesced_for_dynamic_fields(self):
        self.assertIn("yscrollincrement=1", self.widgets)
        self.assertIn("after_idle(self._apply_scrollregion)", self.widgets)
        self.assertIn("self._canvas_width", self.widgets)
        self.assertIn("_canvas_width_after", self.widgets)

    def test_left_panel_tree_is_rebound(self):
        # _build_main 1 处 + _render_fields 2 处（空字段分支与正常分支）
        self.assertGreaterEqual(
            self.main.count("self.left_scroll.bind_wheel_tree()"), 3,
            "动态重建字段后必须重新挂滚动支持")

    def test_right_terminal_is_not_in_left_tree(self):
        self.assertIn("self.term_frame", self.main)
        self.assertNotIn("self.log_view.bind_wheel_tree", self.main)


@unittest.skipUnless(HAS_TK, "需要 Tcl/Tk")
class ProfilePanelTest(unittest.TestCase):
    def test_resize_keeps_rename_and_delete_inside_the_visible_panel(self):
        from tkinter import TclError
        from jsj_desktop.ui.main_window import MainWindow

        data = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"JSJ_DATA_DIR": data}))
        Path(data, "settings.json").write_text(
            '{"check_update_on_startup":false,"theme_mode":"dark"}', encoding="utf-8")
        try:
            window = MainWindow(data_dir=Path(data))
        except TclError as exc:
            if "display" in str(exc).lower():
                self.skipTest(str(exc))
            raise
        self.addCleanup(window.destroy)
        window.manager.profiles.add("示例档案", {})
        window._load_profiles()
        window.update()
        pane = window.main_pane
        self.assertGreaterEqual(pane.sash_coord(0)[0], 410)
        rename = window.profile_btns["rename"]
        delete = window.profile_btns["delete"]
        for width in (1080, 1360, 1600, 1080):
            with self.subTest(width=width):
                window.geometry(f"{width}x700")
                window.update()
                x, y = pane.sash_coord(0)
                x += 2
                for event, target in (("<Button-1>", x), ("<B1-Motion>", 30),
                                      ("<ButtonRelease-1>", 30)):
                    pane.event_generate(event, x=target, y=y + 20)
                window.update()
                self.assertEqual(window.left_scroll.winfo_width(),
                                 int(pane.panecget(window.left_scroll, "minsize")))
                self.assertGreater(delete.winfo_x(), rename.winfo_x())
                for button in window.profile_btns.values():
                    self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                         window.left_scroll.canvas.winfo_rootx() +
                                         window.left_scroll.canvas.winfo_width())
                self.assertFalse(delete.instate(("disabled",)))
                pane.sash_place(0, 485, y)
                window.update()
                self.assertGreater(window.left_scroll.winfo_width(), 360)


if __name__ == "__main__":
    unittest.main()
