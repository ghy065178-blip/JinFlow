import os
import queue
import sys
import time
import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from jsj_desktop.ui.main_window import MainWindow


class WindowTransitionTest(unittest.TestCase):
    def setUp(self):
        self.window = window = MainWindow.__new__(MainWindow)
        window._configured_size = None
        window._window_transition_after = None
        window._poll_after = None
        window._toast_after = None
        window._update_result_after = None
        window._startup_update_after = None
        window._closed = False
        window.after = Mock(side_effect=("first", "last", "poll"))
        window.after_cancel = Mock()
        window._render_task_tabs = Mock()
        window._tick_countdown = Mock(return_value=False)
        window._render_state = Mock()

    def test_only_changed_root_sizes_restart_the_transition(self):
        window = self.window
        window._on_window_configure(SimpleNamespace(widget=object(), width=1200, height=800))
        event = SimpleNamespace(widget=window, width=1200, height=800)
        window._on_window_configure(event)
        window._on_window_configure(event)
        window._on_window_configure(SimpleNamespace(widget=window, width=1600, height=900))
        self.assertEqual(window.after.call_count, 2)
        window.after_cancel.assert_called_once_with("first")
        self.assertEqual(window._window_transition_after, "last")
        window._finish_window_transition()
        self.assertIsNone(window._window_transition_after)
        window._render_task_tabs.assert_called_once()
        window._render_state.assert_called_once()

    def test_poll_consumes_task_state_and_defers_cosmetic_refresh(self):
        window = self.window
        window._window_transition_after = "resize"
        window.event_queue = queue.Queue()
        window.active_task = "t1"
        window._manual_update_check = False
        window.manager = Mock()
        window._update_buttons = Mock()
        window.event_queue.put(("state", "t1", {"attempt": 42}))
        window.clock_var = Mock()
        window._last_clock = ""
        window.theme_mode = "dark"
        window._poll()
        window.manager.apply_event.assert_called_once_with("state", "t1", {"attempt": 42})
        window.clock_var.set.assert_called_once()
        window._render_task_tabs.assert_not_called()
        window._render_state.assert_not_called()
        window._tick_countdown.assert_not_called()

    def test_destroy_cancels_resize_and_poll_callbacks(self):
        window = self.window
        window._window_transition_after = "resize"
        window._poll_after = "poll"
        with patch.object(tk.Tk, "destroy") as destroy:
            window.destroy()
        self.assertEqual([call.args[0] for call in window.after_cancel.call_args_list],
                         ["resize", "poll"])
        destroy.assert_called_once()


@unittest.skipUnless(sys.platform == "win32", "需要 Windows 原生窗口")
class WindowsWindowModesTest(unittest.TestCase):
    def test_resize_maximize_restore_and_fullscreen_keep_widget_state(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"JSJ_DATA_DIR": directory}))
        Path(directory, "settings.json").write_text(
            '{"check_update_on_startup":false,"theme_mode":"dark"}', encoding="utf-8")
        window = MainWindow(data_dir=Path(directory))
        self.addCleanup(window.destroy)
        errors = MagicMock()
        window.report_callback_exception = errors
        window.link_var.set("示例链接")
        form_entry = window.link_entry
        window.log_view.append("12:00:00", "info", "界面测试")

        def settle():
            window.update()
            deadline = time.monotonic() + 3
            while window._window_transition_after and time.monotonic() < deadline:
                time.sleep(0.01)
                window.update()
            self.assertIsNone(window._window_transition_after)

        settle()
        for _ in range(2):
            window.geometry("1080x700")
            settle()
            before = window.winfo_width(), window.winfo_height()
            window.geometry("1360x860")
            settle()
            self.assertNotEqual((window.winfo_width(), window.winfo_height()), before)
            window.state("zoomed")
            settle()
            self.assertEqual(window.state(), "zoomed")
            window.state("normal")
            settle()
            self.assertEqual(window.state(), "normal")
            window._toggle_fullscreen()
            settle()
            self.assertTrue(window.attributes("-fullscreen"))
            window._leave_fullscreen()
            settle()
            self.assertFalse(window.attributes("-fullscreen"))
            self.assertEqual(window.state(), "normal")
        self.assertIs(window.link_entry, form_entry)
        self.assertEqual(window.link_var.get(), "示例链接")
        self.assertIn("界面测试", window.log_view.text())
        errors.assert_not_called()
