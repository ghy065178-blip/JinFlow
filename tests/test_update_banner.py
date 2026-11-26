# -*- coding: utf-8 -*-
"""启动更新提醒回归测试：原生 Tk 窗口，替换网络访问和浏览器调用。"""
import json
import os
import threading
import time
import unittest
import webbrowser
from pathlib import Path
from tempfile import TemporaryDirectory
from tkinter import TclError, ttk
from unittest.mock import patch

from jsj_desktop import __version__
from jsj_desktop.ui.main_window import MainWindow
from jsj_desktop.update import client, manifest, service
from jsj_desktop.update.errors import NetworkError


class UpdateBannerTest(unittest.TestCase):
    def setUp(self):
        data = TemporaryDirectory()
        self.addCleanup(data.cleanup)
        self.data_dir = Path(data.name)
        self.enterContext(patch.dict(os.environ, {
            "JSJ_DATA_DIR": data.name,
            "JSJ_UPDATE_MANIFEST_URL": "https://example.invalid/latest.json",
        }))
        self.enterContext(patch.object(client, "http_get", side_effect=NetworkError("离线")))
        self.browser = self.enterContext(patch.object(webbrowser, "open_new_tab"))

    def _open_window(self, **settings):
        (self.data_dir / "settings.json").write_text(json.dumps({
            "theme_mode": "dark", **settings,
        }), encoding="utf-8")
        try:
            window = MainWindow(data_dir=self.data_dir)
        except TclError as exc:
            if "display" in str(exc).lower():
                self.skipTest(str(exc))
            raise
        self.addCleanup(self._close_window, window)
        return window

    @staticmethod
    def _close_window(window):
        for timer in window.tk.splitlist(window.tk.call("after", "info")):
            window.after_cancel(timer)
        window.destroy()

    @staticmethod
    def _banners(window):
        return [w for w in window.pack_slaves() if isinstance(w, ttk.Button)
                and "发现新版本" in w.cget("text")]

    @staticmethod
    def _manifest(version, tag):
        return {"schema": 1, "latest_version": version, "tag": tag,
                "assets": {t: manifest.asset_names(t) for t in manifest.TARGETS}}

    def test_startup_opens_exact_release_page_only_on_click(self):
        threads = []

        def fetch(url, timeout):
            threads.append(threading.current_thread())
            return json.dumps(self._manifest("99.0.0", "v99.0.0+build.1"))

        with patch.object(client, "http_get", side_effect=fetch):
            window = self._open_window()
            self.assertTrue(window.update_var.get(), "默认应检查更新")
            deadline = time.monotonic() + 4
            while not self._banners(window) and time.monotonic() < deadline:
                window.update()
                time.sleep(0.01)
        self.assertEqual(len(threads), 1)
        self.assertIsNot(threads[0], threading.current_thread())
        self.assertEqual(len(self._banners(window)), 1, "启动后应显示更新提醒")
        banner, = self._banners(window)
        self.assertEqual(window.pack_slaves().index(banner), 1)
        self.assertTrue(banner.winfo_ismapped())
        self.assertEqual(str(banner.cget("takefocus")), "1")
        self.assertTrue(banner.bind("<Return>"))
        style = ttk.Style(window)
        for state in (("focus",), ("focus", "active")):
            name = banner.cget("style")
            self.assertNotEqual(style.lookup(name, "focuscolor", state),
                                style.lookup(name, "background", state))
        self.assertIn("v99.0.0", banner.cget("text"))
        self.browser.assert_not_called()
        banner.invoke()
        self.browser.assert_called_once_with(
            manifest.REPO_URL + "/releases/tag/v99.0.0%2Bbuild.1")

    def test_explicit_startup_opt_out_does_not_check(self):
        with patch.object(MainWindow, "_auto_check_update") as check:
            window = self._open_window(check_update_on_startup=False)
            window.update()
        self.assertFalse(window.update_var.get())
        check.assert_not_called()
        self.assertEqual(self._banners(window), [])

    def test_unverified_or_current_results_leave_window_quiet(self):
        with patch.object(client, "http_get", return_value=json.dumps(
                self._manifest(__version__, "v" + __version__))):
            current = service.check_for_update()
        with patch.object(client, "http_get", return_value=json.dumps(
                self._manifest("99.0.0", "v98.0.0"))):
            mismatched = service.check_for_update()
        bundled = manifest.validate_manifest(self._manifest("99.0.0", "v99.0.0"))
        with patch.object(client, "http_get", side_effect=NetworkError("离线")), \
                patch.object(manifest, "local_manifest", return_value=bundled):
            offline = service.check_for_update()
        self.assertFalse(current.update_available)
        self.assertTrue(offline.update_available)
        self.assertTrue(offline.offline)
        window = self._open_window(check_update_on_startup=False)
        with patch.object(window, "_toast") as toast:
            for result in (current, offline, mismatched):
                window.event_queue.put(("startup_update", None, result))
            window._poll()
            window.update_idletasks()
            toast.assert_not_called()
        self.assertEqual(self._banners(window), [])
        self.browser.assert_not_called()
