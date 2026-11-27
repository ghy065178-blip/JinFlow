# -*- coding: utf-8 -*-
"""Windows runners exercise the actual detached PowerShell installer."""
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tests.test_update import EndToEndUpdateTest, fake_ctx
from jsj_desktop.update import installer, manifest as mf, service


FIXTURE_SOURCE = r"""
using System;
using System.IO;
using System.Threading;

class Fixture {
    static int Main(string[] args) {
        string control = Environment.GetEnvironmentVariable("JSJ_HANDOFF_TEST_DIR");
        string flavor = File.ReadAllText("flavor.txt");
        if (args.Length == 0) {
            string log = Environment.GetEnvironmentVariable("JSJ_UPDATE_FAILURE_LOG");
            if (string.IsNullOrEmpty(log))
                log = Environment.GetEnvironmentVariable("JSJ_UPDATE_RESULT_LOG");
            File.WriteAllText(Path.Combine(control, "restarted"), flavor + "\n" + log);
            return flavor == "broken" ? 7 : 0;
        }
        using (File.Open(@"_internal\locked.dll", FileMode.Open, FileAccess.Read, FileShare.None)) {
            File.WriteAllText(Path.Combine(control, "locked"), "1");
            for (int i = 0; i < 1200; i++) {
                if (File.Exists(Path.Combine(control, "close"))) return 0;
                Thread.Sleep(50);
            }
        }
        return 1;
    }
}
"""


@unittest.skipUnless(sys.platform == "win32", "需要 Windows PowerShell 与 Windows 文件锁")
class WindowsHandoffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory(prefix="jsj-windows-fixture-")
        cls.addClassCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "Fixture.cs").write_text(FIXTURE_SOURCE, encoding="ascii")
        powershell = Path(os.environ["SystemRoot"]) / (
            "System32/WindowsPowerShell/v1.0/powershell.exe")
        subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command",
                        "Add-Type -Path ./Fixture.cs -OutputAssembly ./fixture.exe "
                       "-OutputType ConsoleApplication -ErrorAction Stop"],
                       cwd=root, timeout=120, check=True)
        cls.exe = (root / "fixture.exe").read_bytes()
        cls.target = mf.platform_target()
        EndToEndUpdateTest.setUpClass()
        cls.addClassCleanup(EndToEndUpdateTest.tearDownClass)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "中文 [示例] %TEMP% ' & 空格"
        self.old = self.root / "JinshujuDesktop"
        runtime = self.old / "_internal"
        runtime.mkdir(parents=True)
        (self.old / "JinshujuDesktop.exe").write_bytes(self.exe)
        (self.old / "APP_VERSION.txt").write_text("JinshujuDesktop 1.2.0\n")
        (self.old / "flavor.txt").write_text("old")
        (runtime / "locked.dll").write_bytes(b"old runtime")
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "profiles.json").write_text("{}")

    def _archive(self, flavor):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as pkg:
            app = "JinshujuDesktop/"
            pkg.writestr(app + "JinshujuDesktop.exe", self.exe)
            pkg.writestr(app + "APP_VERSION.txt", "JinshujuDesktop 2.1.0\n")
            pkg.writestr(app + "BUILD_INFO.txt", "JinshujuDesktop 2.1.0\n
                         "target    : %s\n" % self.target)
            pkg.writestr(app + "flavor.txt", flavor)
            pkg.writestr(app + "_internal/locked.dll", "new runtime")
        return buf.getvalue()

    def _run_update(self, flavor, relaunch=True):
        fixture = EndToEndUpdateTest
        archive = self._archive(flavor)
        fixture._fill(archive, hashlib.sha256(archive).hexdigest())
        sources = [("local-release", fixture.base + "latest.json", "manifest")]
        workers = []

        def capture_worker(argv, **kwargs):
            worker = subprocess.Popen(argv, **kwargs)
            workers.append(worker)
            return worker

        with patch.dict(os.environ, {"JSJ_HANDOFF_TEST_DIR": str(self.root)}):
            parent = subprocess.Popen([str(self.old / "JinshujuDesktop.exe"), "hold"],
                                      cwd=self.old, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                # Fixture holds a runtime file open until explicitly released.
                locked = self.root / "locked"
                import time
                deadline = time.monotonic() + 10
                while not locked.is_file() and parent.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(locked.is_file(), "fixture did not acquire its lock")
                ctx = fake_ctx("windows-dir", system="windows", target=self.target,
                               data_dir=str(self.data))
                ctx.update(install_root=str(self.old), pid=parent.pid, current_version="1.2.0")
                with patch.object(installer, "install_context", return_value=ctx):
                    outcome = service.apply_update(current_version="1.2.0", target=self.target,
                                                   sources=sources, relaunch=relaunch,
                                                   runner=capture_worker)
                self.assertTrue(outcome["pending"])
                self.assertEqual(outcome["sha256"], hashlib.sha256(archive).hexdigest())
                self.assertIsNone(parent.poll())
                self.assertEqual((self.old / "flavor.txt").read_text(), "old")
                self.assertFalse(Path(outcome["backup"]).exists())
            finally:
                (self.root / "close").touch()
                try:
                    parent.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    parent.kill()
                    parent.wait(timeout=5)
                for worker in workers:
                    try:
                        worker.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        worker.wait(timeout=5)
                        raise
        return outcome, workers[0].returncode

    def test_checked_windows_package_replaces_after_exit_and_restarts(self):
        result, status = self._run_update("new")
        log = Path(result["log"]).read_text(encoding="utf-8-sig")
        self.assertEqual(status, 0, log)
        new, log_path = (self.root / "restarted").read_text(encoding="utf-8").splitlines()
        self.assertEqual(new, "new")
        self.assertEqual(log_path, result["log"])
        self.assertEqual((self.old / "_internal/locked.dll").read_bytes(), b"new runtime")
        self.assertEqual((Path(result["backup"]) / "_internal/locked.dll").read_bytes(),
                         b"old runtime")
        self.assertEqual((self.data / "profiles.json").read_text(), "{}")

    def test_rolls_back_and_restarts_old_app_on_new_app_startup_failure(self):
        result, status = self._run_update("broken")
        log = Path(result["log"]).read_text(encoding="utf-8-sig")
        self.assertEqual(status, 1, log)
        self.assertIn("Restored the original installation", log)
        old, log_path = (self.root / "restarted").read_text(encoding="utf-8").splitlines()
        self.assertEqual(old, "old")
        self.assertEqual(log_path, result["log"])
        self.assertEqual((self.old / "_internal/locked.dll").read_bytes(), b"old runtime")
        self.assertEqual((self.data / "profiles.json").read_text(), "{}")

    def test_no_relaunch_still_installs_after_exit(self):
        result, status = self._run_update("new", relaunch=False)
        self.assertEqual(status, 0, Path(result["log"]).read_text(encoding="utf-8-sig"))
        self.assertFalse((self.root / "restarted").exists())
        self.assertEqual((self.old / "flavor.txt").read_text(), "new")
