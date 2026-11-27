# -*- coding: utf-8 -*-
"""启动只检查，用户打开面板并确认后才执行升级。"""
import json
import os
import threading
import time
import unittest
import webbrowser
from pathlib import Path
from tempfile import TemporaryDirectory
from tkinter import TclError
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
        self.addCleanup(window.destroy)
        return window

    def _wait_for(self, window, condition):
        deadline = time.monotonic() + 4
        while not condition() and time.monotonic() < deadline:
            window.update()
            time.sleep(0.01)
        self.assertTrue(condition())

    @staticmethod
    def _manifest(version, tag):
        return {"schema": 1, "latest_version": version, "tag": tag,
                "assets": {t: manifest.asset_names(t) for t in manifest.TARGETS}}

    def test_startup_button_opens_dialog_and_requires_explicit_confirmation(self):
        threads = []

        def fetch(url, timeout):
            threads.append(threading.current_thread())
            return json.dumps(self._manifest("99.0.0", "v99.0.0+build.1"))

        with patch.object(client, "http_get", side_effect=fetch), \
                patch.object(service, "apply_update") as apply_update:
            window = self._open_window()
            self.assertTrue(window.update_var.get(), "默认应检查更新")
            banner = window.update_banner
            self._wait_for(window, banner.winfo_ismapped)
            self.assertIs(banner.master, window.header)
            self.assertEqual(banner.cget("text"), "更新")
            self.assertEqual(str(banner.cget("takefocus")), "1")
            self.assertTrue(banner.bind("<Return>"))
            apply_update.assert_not_called()
            banner.invoke()
            dialog = window.update_window
            self.assertEqual(dialog.latest_var.get(), "99.0.0")
            apply_update.assert_not_called()
            with patch("jsj_desktop.ui.update_dialog.messagebox.askyesno", return_value=False):
                dialog.update_btn.invoke()
            apply_update.assert_not_called()

            def complete(check, progress, relaunch):
                progress("download", 25, "正在下载")
                progress("install", 95, "正在安装")
                return {"latest_version": check.latest_version, "message": "更新完成"}

            apply_update.side_effect = complete
            with patch("jsj_desktop.ui.update_dialog.messagebox.askyesno", return_value=True), \
                    patch("jsj_desktop.ui.update_dialog.messagebox.showinfo") as success:
                dialog.update_btn.invoke()
                self._wait_for(window, lambda: success.called)
            self.assertEqual(dialog.state_var.get(), "更新成功")
            self.assertFalse(banner.winfo_ismapped())
            apply_update.assert_called_once()
        self.assertEqual(len(threads), 1)
        self.assertIsNot(threads[0], threading.current_thread())
        self.browser.assert_not_called()

    def test_explicit_startup_opt_out_does_not_check(self):
        with patch.object(MainWindow, "_auto_check_update") as check:
            window = self._open_window(check_update_on_startup=False)
            window.update()
        self.assertFalse(window.update_var.get())
        check.assert_not_called()
        self.assertFalse(window.update_banner.winfo_ismapped())

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
            available = service.check_for_update(info=client.ReleaseInfo(bundled, "release-asset"))
            window._show_update_banner(available)
            self._wait_for(window, window.update_banner.winfo_ismapped)
            for result in (current, offline, mismatched):
                window.event_queue.put(("startup_update", None, result))
            self._wait_for(window, window.event_queue.empty)
            window.update_idletasks()
            toast.assert_not_called()
        self.assertFalse(window.update_banner.winfo_ismapped())
        self.browser.assert_not_called()

    def test_relaunched_app_waits_for_installer_success_log(self):
        window = self._open_window(check_update_on_startup=False)
        log = self.data_dir / "install.log"
        log.write_text("Waiting for the running application to close.\n", encoding="utf-8")
        with patch.dict(os.environ, {"JSJ_UPDATE_RESULT_LOG": str(log)}), \
                patch.object(window, "_toast") as toast:
            window._report_update_result()
            toast.assert_not_called()
            log.write_text("2026-11-27T12:00:00 Installed. Backup: example\n", encoding="utf-8")
            self._wait_for(window, lambda: toast.called)
        toast.assert_called_once_with("更新成功，已启动 v" + __version__, "ok")

    def test_windows_handoff_is_pending_until_the_relaunched_app_reports_result(self):
        window = self._open_window(check_update_on_startup=False)
        result = service.check_for_update(info=client.ReleaseInfo(
            manifest.local_manifest(), "release-asset"), current_revision=0)
        window._show_update_banner(result)
        window.update_banner.invoke()
        dialog = window.update_window
        with patch.object(dialog, "_toast") as toast, patch.object(window, "close") as close:
            dialog._on_done({"latest_version": "2.0.0", "pending": True,
                             "message": "退出后替换"})
            self.assertEqual(dialog.state_var.get(), "正在安装…")
            toast.assert_not_called()
            close.assert_called_once()

    def test_failed_install_reports_error_and_keeps_update_available(self):
        window = self._open_window(check_update_on_startup=False)
        result = service.check_for_update(current_version="2.0.0", info=client.ReleaseInfo(
            manifest.local_manifest(), "release-asset"), current_revision=0)
        window._show_update_banner(result)
        window.update_banner.invoke()
        dialog = window.update_window
        with patch.object(service, "apply_update", side_effect=NetworkError("下载失败")), \
                patch("jsj_desktop.ui.update_dialog.messagebox.askyesno", return_value=True), \
                patch("jsj_desktop.ui.update_dialog.messagebox.showerror") as failure:
            dialog.update_btn.invoke()
            self._wait_for(window, lambda: failure.called)
        self.assertIn("更新失败", dialog.state_var.get())
        self.assertTrue(window.update_banner.winfo_ismapped())
        self.assertFalse(dialog.update_btn.instate(("disabled",)))
