# -*- coding: utf-8 -*-
"""1.3.0 应用内检查更新与升级的回归测试（含本地 HTTP 端到端演练）。

覆盖：三个以上历史版本 → 1.3.0、四平台资产选择、多通道容错、SHA256 校验、
安装/切换与回滚、界面与 CLI 入口、发布配置一致性。全部测试不依赖真实网络，
使用合成清单与合成发布包。
"""
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import jsj_desktop                                        # noqa: E402
from jsj_desktop import __version__                       # noqa: E402
from jsj_desktop.update import client, installer, manifest as mf  # noqa: E402
from jsj_desktop.update import service, version as vmod   # noqa: E402
from jsj_desktop.update.errors import (ChannelError, ChecksumError,  # noqa: E402
                                       InstallError, ManifestError,
                                       UnsupportedPlatformError, UpdateError)

LEGACY = ("1.0.0", "1.0.1", "1.0.2", "1.0.3")
TARGET = "macos-arm64"


def synthetic_manifest(download_base="https://example.invalid/v1.3.0/"):
    data = json.loads((ROOT / "update" / "latest.json").read_text(
        encoding="utf-8"))
    data["download_base"] = download_base
    return mf.validate_manifest(data)


def synthetic_package_bytes(version="1.3.0", target=TARGET):
    """构造与真实发布包同结构的 macos 合成 zip（无个人信息）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("JinshujuDesktop.app/Contents/MacOS/JinshujuDesktop",
                    "#!/bin/sh\nexit 0\n")
        zf.writestr("JinshujuDesktop.app/Contents/APP_VERSION.txt",
                    "JinshujuDesktop %s\n" % version)
        zf.writestr("BUILD_INFO.txt",
                    "JinshujuDesktop %s\ntarget    : %s\n"
                    "runtime   : Python standard library only\n"
                    % (version, target))
        zf.writestr("README-RELEASE.txt", "synthetic release package\n")
    return buf.getvalue()


def run_py(args, env=None, timeout=90):
    """跨平台运行子进程：强制 UTF-8，避免 Windows 中文输出用 cp1252 解码失败。"""
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        child_env.update(env)
    return subprocess.run(args, cwd=str(ROOT), env=child_env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def fake_ctx(mode="source", system="macos", target=TARGET, data_dir="/tmp/x"):
    return {"frozen": mode != "source", "system": system, "target": target,
            "executable": "/tmp/x/JinshujuDesktop", "pid": 0, "mode": mode,
            "app_bundle": "/tmp/x/JinshujuDesktop.app" if mode == "macos-app" else "",
            "install_root": "/tmp/x/JinshujuDesktop" if mode == "windows-dir" else "",
            "current_version": "1.0.3", "data_dir": data_dir}


class VersionCompatibilityTest(unittest.TestCase):
    def test_every_legacy_version_upgrades_to_130(self):
        for old in LEGACY:
            plan = vmod.upgrade_plan(old, "1.3.0")
            self.assertTrue(plan["update_available"], old)
            self.assertTrue(plan["supported"], old)
            self.assertTrue(plan["is_legacy"], old)
            self.assertEqual(plan["latest"], "1.3.0")
            self.assertEqual(plan["path"], "direct")

    def test_tag_prefix_and_four_part_windows_version(self):
        self.assertEqual(vmod.normalize_version("v1.0.3"), "1.0.3")
        self.assertEqual(vmod.normalize_version("1.0.3.0"), "1.0.3")
        self.assertTrue(vmod.is_newer("1.3.0", "1.0.3"))
        self.assertFalse(vmod.is_newer("1.0.3", "1.3.0"))

    def test_prerelease_is_older_than_release(self):
        self.assertTrue(vmod.is_newer("1.3.0", "1.3.0-rc1"))
        self.assertEqual(vmod.compare_versions("1.3.0", "1.3.0"), 0)

    def test_invalid_version_is_rejected(self):
        with self.assertRaises(ValueError):
            vmod.parse_version("not-a-version")
        plan = vmod.upgrade_plan("bad", "1.3.0")
        self.assertFalse(plan["supported"])

    def test_current_version_is_already_latest(self):
        plan = vmod.upgrade_plan("1.3.0", "1.3.0")
        self.assertFalse(plan["update_available"])
        self.assertIn("已是最新", plan["reason"])

    def test_version_below_floor_cannot_auto_upgrade(self):
        plan = vmod.upgrade_plan("0.9.0", "1.3.0", "1.0.0")
        self.assertFalse(plan["supported"])
        self.assertIn("手动", plan["reason"])

    def test_development_build_is_not_downgraded(self):
        plan = vmod.upgrade_plan("1.3.0", "1.3.0")
        self.assertFalse(plan["update_available"])
        self.assertIn("已是最新", plan["reason"])

    def test_manifest_declares_legacy_upgrade_paths(self):
        data = mf.local_manifest()
        self.assertEqual(data["latest_version"], "1.3.0")
        self.assertEqual(data["upgrade_target"], "1.3.0")
        for old in LEGACY:
            self.assertIn(old, data["legacy_versions"])
            self.assertEqual(data["legacy_upgrade_paths"][old]["upgrade_to"],
                             "1.3.0")
            self.assertTrue(data["legacy_upgrade_paths"][old]["data_compatible"])


class ManifestTest(unittest.TestCase):
    def test_bundled_manifest_is_valid(self):
        data = mf.local_manifest()
        self.assertEqual(data["schema"], mf.MANIFEST_SCHEMA)
        self.assertEqual(data["latest_version"], "1.3.0")
        self.assertEqual(data["checksums_asset"], "SHA256SUMS.txt")

    def test_all_four_platform_assets_resolve(self):
        data = mf.local_manifest()
        for target in mf.TARGETS:
            asset = mf.select_asset(data, target)
            self.assertEqual(asset["name"], mf.asset_names(target)["zip"])
            self.assertTrue(asset["url"].startswith("https://"))
        self.assertIn("dmg", mf.asset_names("macos-arm64"))

    def test_unsupported_platform_raises(self):
        with self.assertRaises(UnsupportedPlatformError):
            mf.platform_target(("linux", "x86_64"))

    def test_manifest_rejects_bad_schema(self):
        with self.assertRaises(ManifestError):
            mf.validate_manifest(dict(synthetic_manifest(), schema=99))

    def test_manifest_rejects_wrong_asset_name(self):
        data = synthetic_manifest()
        data["assets"]["macos-arm64"]["zip"] = "JinshujuDesktop-macos-x86_64.zip"
        with self.assertRaises(ManifestError):
            mf.validate_manifest(data)

    def test_manifest_rejects_missing_target(self):
        data = synthetic_manifest()
        del data["assets"]["windows-arm64"]
        with self.assertRaises(ManifestError):
            mf.validate_manifest(data)

    def test_github_api_release_is_normalized(self):
        payload = {"tag_name": "v1.3.0", "body": "notes",
                   "html_url": "https://example.invalid/release",
                   "assets": [{"name": "JinshujuDesktop-%s.zip" % t,
                               "browser_download_url":
                               "https://example.invalid/%s.zip" % t}
                              for t in mf.TARGETS]}
        data = mf.normalize_github_release(payload)
        self.assertEqual(data["latest_version"], "1.3.0")
        self.assertIn("macos-arm64", data["assets"])
        self.assertIn("JinshujuDesktop-macos-arm64.zip", data["urls"])

    def test_channel_sources_honor_env_override(self):
        with patch.dict(os.environ, {mf.ENV_MANIFEST_URL: "http://127.0.0.1/m.json"}):
            sources = mf.channel_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0][0], "manifest-override")
        with patch.dict(os.environ, {}, clear=True):
            regular = mf.channel_sources()
        self.assertIn("raw.githubusercontent.com", regular[0][1])
        self.assertIn("api.github.com", regular[1][1])


class ClientTest(unittest.TestCase):
    def test_fetch_latest_picks_highest_version(self):
        low = dict(synthetic_manifest(), latest_version="1.0.3",
                   upgrade_target="1.0.3", tag="v1.0.3")
        high = synthetic_manifest()

        def fetcher(url, timeout=8):
            return json.dumps(low if "raw.githubusercontent" in url else high)\
                .encode("utf-8")

        info = client.fetch_latest(fetcher=fetcher)
        self.assertEqual(info.version, "1.3.0")
        self.assertFalse(info.offline)

    def test_all_sources_fail_falls_back_to_bundled_offline(self):
        def fetcher(url, timeout=8):
            raise OSError("offline")

        info = client.fetch_latest(fetcher=fetcher)
        self.assertTrue(info.offline)
        self.assertEqual(info.source, "bundled")
        self.assertEqual(info.version, "1.3.0")
        self.assertTrue(info.errors)

    def test_all_sources_and_bundle_fail_raises_channel_error(self):
        def offline(url, timeout=8):
            raise OSError("offline")

        with patch.object(mf, "local_manifest",
                          side_effect=ManifestError("missing")):
            with self.assertRaises(ChannelError):
                client.fetch_latest(fetcher=offline)

    def test_check_from_every_legacy_version_reports_130(self):
        info = client.ReleaseInfo(synthetic_manifest(), "test")
        for old in LEGACY:
            result = client.check_for_update(current_version=old, target=TARGET,
                                             info=info)
            self.assertTrue(result.ok, old)
            self.assertEqual(result.current_version, old)
            self.assertEqual(result.latest_version, "1.3.0")
            self.assertTrue(result.update_available)
            self.assertTrue(result.is_legacy)
            self.assertTrue(result.can_update)
            self.assertEqual(result.asset["name"],
                             "JinshujuDesktop-macos-arm64.zip")

    def test_offline_info_disallows_auto_install(self):
        info = client.ReleaseInfo(synthetic_manifest(), "bundled", offline=True)
        result = client.check_for_update(current_version="1.0.3",
                                         target=TARGET, info=info)
        self.assertFalse(result.can_update)
        self.assertIn("手动下载", result.reason)

    def test_missing_platform_asset_is_reported(self):
        data = synthetic_manifest()
        data["assets"].pop("macos-arm64")
        info = client.ReleaseInfo(
            mf.validate_manifest(data, strict_assets=False), "test")
        result = client.check_for_update(current_version="1.0.1",
                                         target=TARGET, info=info)
        self.assertFalse(result.can_update)
        self.assertTrue(result.asset_error)

    def test_parse_checksums_and_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.bin"
            p.write_bytes(b"synthetic")
            digest = hashlib.sha256(b"synthetic").hexdigest()
            self.assertEqual(client.sha256_file(p), digest)
            parsed = client.parse_checksums("%s  a.bin\n%s *b.bin\n"
                                            % (digest, digest.replace("0", "1")))
            self.assertEqual(parsed["a.bin"], digest)
            self.assertEqual(len(parsed), 2)

    def test_verify_download_mismatch_removes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.zip"
            p.write_bytes(b"bad")
            with self.assertRaises(ChecksumError):
                client.verify_download(p, "0" * 64)
            self.assertFalse(p.exists())

    def test_resolve_checksum_detects_conflict(self):
        info = client.ReleaseInfo(synthetic_manifest(), "test")
        asset = mf.select_asset(info.manifest, TARGET)
        asset["sha256"] = "1" * 64
        sums = "%s  %s\n" % ("2" * 64, asset["name"])
        with self.assertRaises(ChecksumError):
            client.resolve_checksum(info, asset,
                                    fetcher=lambda u, timeout=8: sums.encode())

    def test_resolve_checksum_without_any_hash_fails(self):
        info = client.ReleaseInfo(synthetic_manifest(), "test")
        asset = mf.select_asset(info.manifest, TARGET)
        with self.assertRaises(ChecksumError):
            client.resolve_checksum(info, asset,
                                    fetcher=lambda u, timeout=8: b"garbage")

    def test_download_file_reports_progress(self):
        class Stream:
            headers = {"Content-Length": "4"}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, size):
                if not hasattr(self, "done"):
                    self.done = True
                    return b"data"
                return b""

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "asset.zip"
            calls = []
            client.download_file("http://example.invalid/a.zip", dest,
                                 progress=lambda d, t: calls.append((d, t)),
                                 opener=lambda url, timeout=45: Stream())
            self.assertEqual(dest.read_bytes(), b"data")
            self.assertEqual(calls, [(4, 4)])


class InstallerTest(unittest.TestCase):
    def test_platform_target_for_all_supported(self):
        for system, arch in (("macos", "x86_64"), ("macos", "arm64"),
                             ("windows", "x86_64"), ("windows", "arm64")):
            self.assertEqual(installer.platform_target((system, arch)),
                             "%s-%s" % (system, arch))

    def test_extract_zip_restores_symlink_and_executable_bit(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("app/Contents/MacOS/runner")
            info.external_attr = (0o100755 << 16)
            zf.writestr(info, "#!/bin/sh\n")
            link = zipfile.ZipInfo("app/Contents/Resources/lib")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(link, "../MacOS/runner")
        with tempfile.TemporaryDirectory() as tmp:
            dest = installer.extract_zip(io.BytesIO(buf.getvalue()),
                                         Path(tmp) / "out")
            runner = dest / "app/Contents/MacOS/runner"
            self.assertTrue(runner.is_file())
            self.assertTrue(os.access(str(runner), os.X_OK))
            link_path = dest / "app/Contents/Resources/lib"
            self.assertTrue(link_path.is_symlink() or link_path.is_file())

    def test_extract_zip_rejects_path_traversal(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../escape.txt", "x")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(InstallError):
                installer.extract_zip(io.BytesIO(buf.getvalue()),
                                      Path(tmp) / "out")

    def test_validate_package_accepts_correct_version_and_target(self):
        buf = io.BytesIO(synthetic_package_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            root = installer.extract_zip(buf, Path(tmp) / "pkg")
            pkg = installer.validate_package(root, TARGET, "1.3.0")
            self.assertEqual(pkg["version"], "1.3.0")
            self.assertTrue(Path(pkg["launch_path"]).is_file())

    def test_validate_package_rejects_wrong_version(self):
        buf = io.BytesIO(synthetic_package_bytes(version="1.0.3"))
        with tempfile.TemporaryDirectory() as tmp:
            root = installer.extract_zip(buf, Path(tmp) / "pkg")
            with self.assertRaises(InstallError):
                installer.validate_package(root, TARGET, "1.3.0")

    def test_validate_package_rejects_wrong_architecture(self):
        buf = io.BytesIO(synthetic_package_bytes(target="macos-x86_64"))
        with tempfile.TemporaryDirectory() as tmp:
            root = installer.extract_zip(buf, Path(tmp) / "pkg")
            with self.assertRaises(InstallError):
                installer.validate_package(root, TARGET, "1.3.0")

    def _package(self, tmp):
        root = installer.extract_zip(io.BytesIO(synthetic_package_bytes()),
                                     Path(tmp) / "pkg")
        return installer.validate_package(root, TARGET, "1.3.0")

    def test_plan_install_macos_keeps_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = fake_ctx("macos-app", data_dir=tmp)
            ctx["app_bundle"] = str(Path(tmp) / "install" / "JinshujuDesktop.app")
            Path(ctx["app_bundle"]).mkdir(parents=True)
            plan = installer.plan_install(ctx, self._package(tmp), "1.3.0")
            self.assertEqual(plan["mode"], "macos-app")
            self.assertIn("backup-1.0.3", plan["backup_path"])
            self.assertTrue(plan["can_auto"])

    def test_plan_install_windows_stages_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = fake_ctx("windows-dir", system="windows",
                           target="windows-x86_64", data_dir=tmp)
            ctx["install_root"] = str(Path(tmp) / "install" / "JinshujuDesktop")
            Path(ctx["install_root"]).mkdir(parents=True)
            plan = installer.plan_install(ctx, self._package(tmp), "1.3.0")
            self.assertEqual(plan["mode"], "windows-dir")
            self.assertTrue(plan["script_path"].endswith(".cmd"))

    def test_plan_install_source_mode_is_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = installer.plan_install(fake_ctx(data_dir=tmp),
                                          self._package(tmp), "1.3.0")
            self.assertEqual(plan["mode"], "staged")
            self.assertIn("updates/1.3.0", plan["target_path"].replace("\\", "/"))
            # platform_label() 返回 macos/windows/linux，不能与 sys.platform 混用
            self.assertTrue(plan["can_auto"])
            self.assertNotIn("没有可直接运行", plan["note"])

    def test_apply_install_macos_replaces_and_backs_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "Applications"
            base.mkdir()
            old = base / "JinshujuDesktop.app"
            (old / "Contents" / "MacOS").mkdir(parents=True)
            (old / "Contents" / "MacOS" / "JinshujuDesktop").write_text("old")
            new = Path(tmp) / "new" / "JinshujuDesktop.app"
            (new / "Contents" / "MacOS").mkdir(parents=True)
            (new / "Contents" / "MacOS" / "JinshujuDesktop").write_text("new")
            plan = {"mode": "macos-app", "target_path": str(old),
                    "backup_path": str(base / "JinshujuDesktop.app.backup-1.0.3"),
                    "new_app": str(new), "launch_path": "", "version": "1.3.0"}
            calls = []
            result = installer.apply_install(plan, relaunch=False,
                                             runner=lambda *a, **k: calls.append(a[0]))
            self.assertTrue(result["ok"])
            self.assertEqual((old / "Contents/MacOS/JinshujuDesktop")
                             .read_text(), "new")
            self.assertEqual(Path(result["backup"]).exists(), True)
            self.assertTrue(any(c[0] == "codesign" for c in calls))

    def test_apply_install_macos_rolls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "JinshujuDesktop.app"
            old.mkdir()
            (old / "marker").write_text("old")
            plan = {"mode": "macos-app", "target_path": str(old),
                    "backup_path": str(Path(tmp) / "backup.app"),
                    "new_app": str(Path(tmp) / "missing.app"),
                    "launch_path": "", "version": "1.3.0"}

            real_move = installer.shutil.move

            def broken_move(src, dst):
                if str(src).endswith("missing.app"):
                    raise OSError("copy failed")
                return real_move(src, dst)

            with patch.object(installer.shutil, "move", side_effect=broken_move):
                with self.assertRaises(InstallError):
                    installer.apply_install(plan, relaunch=False,
                                            runner=lambda *a, **k: None)
            self.assertTrue(old.exists())
            self.assertEqual((old / "marker").read_text(), "old")

    def test_apply_install_windows_writes_replacement_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / "payload"
            payload.mkdir()
            (payload / "JinshujuDesktop.exe").write_bytes(b"exe")
            plan = {"mode": "windows-dir", "target_path": str(Path(tmp) / "old"),
                    "backup_path": str(Path(tmp) / "old.backup-1.0.3"),
                    "staged_path": str(Path(tmp) / "staged"),
                    "script_path": str(Path(tmp) / "upgrades" / "switch.cmd"),
                    "payload_dir": str(payload), "launch_path": "",
                    "version": "1.3.0"}
            launched = []
            result = installer.apply_install(plan, relaunch=True,
                                             runner=lambda *a, **k: launched.append(a[0]))
            self.assertTrue(result["ok"])
            text = Path(plan["script_path"]).read_text(encoding="utf-8")
            self.assertIn("tasklist", text)
            self.assertIn("move /Y", text)
            self.assertIn("JinshujuDesktop.exe", text)
            self.assertTrue(Path(plan["staged_path"], "JinshujuDesktop.exe").is_file())
            self.assertTrue(launched)

    def test_apply_install_staged_copies_new_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / "payload"
            (payload / "Contents" / "MacOS").mkdir(parents=True)
            (payload / "Contents" / "MacOS" / "JinshujuDesktop").write_text("new")
            (payload / "Contents" / "APP_VERSION.txt").write_text(
                "JinshujuDesktop 1.3.0\n")
            dest = Path(tmp) / "updates" / "1.3.0"
            plan = {"mode": "staged", "target_path": str(dest),
                    "payload_dir": str(payload), "can_auto": False,
                    "launch_path": str(dest / "Contents/MacOS/JinshujuDesktop"),
                    "version": "1.3.0", "note": "staged"}
            result = installer.apply_install(plan, relaunch=False,
                                             runner=lambda *a, **k: None)
            self.assertTrue(result["ok"])
            self.assertTrue((dest / "Contents" / "APP_VERSION.txt").is_file())

    def test_windows_script_contains_rollback(self):
        plan = {"target_path": "C:/old", "staged_path": "C:/new",
                "backup_path": "C:/backup"}
        text = installer._windows_script(plan, 4242)
        self.assertIn("4242", text)
        self.assertIn('move /Y "%BACKUP%" "%OLD%"', text)


class EndToEndUpdateTest(unittest.TestCase):
    """本地 HTTP 服务器模拟 Release：真实走完检查→下载→校验→解包→切换。"""

    @classmethod
    def setUpClass(cls):
        cls.package = synthetic_package_bytes()
        cls.digest = hashlib.sha256(cls.package).hexdigest()
        cls.asset = mf.asset_names(TARGET)["zip"]
        cls.resources = {}

        outer = cls

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                name = self.path.split("?")[0].lstrip("/")
                body = outer.resources.get(name)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.base = "http://127.0.0.1:%d/" % cls.port
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls._fill(cls.package, cls.digest)

    @classmethod
    def _fill(cls, package, digest):
        data = synthetic_manifest(cls.base)
        for target in mf.TARGETS:
            data["assets"][target]["sha256"] = ""
            # 各平台共用同一份合成包，保证 intel/arm64 macOS runner 都能下载
            cls.resources[mf.asset_names(target)["zip"]] = package
        cls.resources["latest.json"] = json.dumps(
            data, ensure_ascii=False).encode("utf-8")
        cls.resources["SHA256SUMS.txt"] = "".join(
            "%s  %s\n" % (digest, mf.asset_names(t)["zip"])
            for t in mf.TARGETS).encode("utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _sources(self):
        return [("local-test", self.base + "latest.json", "manifest")]

    def _check(self, current="1.0.3"):
        with patch.object(mf, "channel_sources", return_value=self._sources()):
            return service.check_for_update(current_version=current,
                                            target=TARGET)

    def test_check_detects_130_from_every_legacy_version(self):
        for old in LEGACY:
            result = self._check(old)
            self.assertTrue(result.ok, old)
            self.assertEqual(result.latest_version, "1.3.0")
            self.assertTrue(result.update_available)
            self.assertTrue(result.can_update)
            self.assertEqual(result.asset["name"], self.asset)

    def test_full_upgrade_switches_to_130_without_touching_user_data(self):
        result = self._check("1.0.3")
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            cfg = data_dir / "tasks" / "t1" / "报名信息.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text('{"表单链接": "<占位>"}', encoding="utf-8")
            before = cfg.read_text(encoding="utf-8")
            with patch.dict(os.environ, {"JSJ_DATA_DIR": str(data_dir)}), \
                    patch.object(mf, "channel_sources",
                                 return_value=self._sources()):
                outcome = service.apply_update(check=result, relaunch=False,
                                               runner=lambda *a, **k: None)
            self.assertTrue(outcome["ok"])
            self.assertFalse(outcome.get("noop", False))
            self.assertEqual(outcome["latest_version"], "1.3.0")
            self.assertEqual(outcome["target"], TARGET)
            self.assertEqual(outcome["checksum_source"], "SHA256SUMS.txt")
            marker = Path(outcome["installed_to"]) / "Contents" / "APP_VERSION.txt"
            self.assertTrue(marker.is_file())
            self.assertIn("1.3.0", marker.read_text(encoding="utf-8"))
            self.assertEqual(cfg.read_text(encoding="utf-8"), before)

    def test_checksum_mismatch_aborts_and_keeps_current_version(self):
        corrupted = self.package[:-8] + b"corrupt!!"
        self._fill(corrupted, self.digest)   # 校验和仍指向原始包
        try:
            result = self._check("1.0.2")
            with tempfile.TemporaryDirectory() as tmp, \
                    patch.dict(os.environ, {"JSJ_DATA_DIR": str(Path(tmp) / "data")}), \
                    patch.object(mf, "channel_sources",
                                 return_value=self._sources()):
                with self.assertRaises(ChecksumError):
                    service.apply_update(check=result, relaunch=False,
                                         runner=lambda *a, **k: None)
                self.assertFalse((Path(tmp) / "data" / "updates").exists())
        finally:
            self._fill(self.package, self.digest)

    def test_noop_when_already_130(self):
        result = self._check("1.3.0")
        with patch.object(mf, "channel_sources", return_value=self._sources()):
            outcome = service.apply_update(check=result, relaunch=False,
                                           runner=lambda *a, **k: None)
        self.assertTrue(outcome["noop"])
        self.assertIn("已是最新", outcome["message"])

    def test_cli_check_update_uses_manifest_override(self):
        env = {"PYTHONPATH": str(ROOT / "src"),
               mf.ENV_MANIFEST_URL: (ROOT / "update" / "latest.json").as_uri()}
        proc = run_py([sys.executable, "-m", "jsj_desktop", "--check-update"],
                      env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("最新版本   : 1.3.0", proc.stdout)
        self.assertIn("当前版本   : 1.3.0", proc.stdout)

    def test_legacy_helper_checks_all_old_versions(self):
        helper = ROOT / "tools" / "upgrade_legacy.py"
        url = (ROOT / "update" / "latest.json").as_uri()
        for old in LEGACY:
            proc = run_py([sys.executable, str(helper), "--check",
                           "--current-version", old, "--manifest-url", url])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("直接升级到 1.3.0", proc.stdout)

    @unittest.skipUnless(sys.platform == "darwin",
                         "合成发布包为 macOS .app 结构")
    def test_legacy_helper_full_upgrade_against_local_release(self):
        helper = ROOT / "tools" / "upgrade_legacy.py"
        with tempfile.TemporaryDirectory() as tmp:
            env = {"JSJ_DATA_DIR": str(Path(tmp) / "data")}
            proc = run_py(
                [sys.executable, str(helper), "--upgrade",
                 "--current-version", "1.0.1", "--no-relaunch",
                 "--manifest-url", self.base + "latest.json"],
                env=env, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("已切换到 v1.3.0", proc.stdout)
            marker = (Path(tmp) / "data" / "updates" / "1.3.0" /
                      "JinshujuDesktop.app" / "Contents" / "APP_VERSION.txt")
            self.assertTrue(marker.is_file())
            self.assertIn("1.3.0", marker.read_text(encoding="utf-8"))


class ReleaseConfigTest(unittest.TestCase):
    def test_version_number_is_130_everywhere(self):
        self.assertEqual(__version__, "1.3.0")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('version = "1.3.0"', pyproject)
        version_info = (ROOT / "packaging" / "version_info.txt").read_text(
            encoding="utf-8")
        self.assertIn("(1, 3, 0, 0)", version_info)
        self.assertIn("'1.3.0.0'", version_info)
        self.assertEqual(mf.local_manifest()["latest_version"], "1.3.0")

    def test_pyproject_urls_point_to_real_repository(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(mf.REPO_OWNER, text)
        self.assertNotIn("your-org", text)

    def test_build_script_bundles_manifest_and_version_marker(self):
        text = (ROOT / "packaging" / "build.py").read_text(encoding="utf-8")
        for needle in ("update/latest.json", "APP_VERSION.txt",
                       "verify_manifest_in_archive(archive)",
                       "检查更新与升级"):
            self.assertIn(needle, text)

    def test_macos_version_marker_is_inside_sealed_resources(self):
        # 放在 Contents/ 根目录会被 codesign --verify --deep --strict 判为
        # "code object is not signed at all"（CI 的 DMG 用户流程验证会失败）
        text = (ROOT / "packaging" / "build.py").read_text(encoding="utf-8")
        self.assertIn('"Contents" / "Resources" / "APP_VERSION.txt"', text)
        self.assertNotIn('"Contents" / "APP_VERSION.txt"', text)

    def test_release_workflow_publishes_channel_assets(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8")
        for needle in ("generate_update_manifest.py",
                       "check_update_channel.py --offline",
                       "release-assets/latest.json",
                       "JinshujuDesktop-Upgrade-Helper.py",
                       "Verify release tag matches package version"):
            self.assertIn(needle, text)

    def test_ci_validates_update_channel(self):
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8")
        self.assertIn("check_update_channel.py --offline", text)

    def test_help_menu_has_update_entry_and_failure_prompt(self):
        ui = (ROOT / "src" / "jsj_desktop" / "ui" /
              "main_window.py").read_text(encoding="utf-8")
        dialog = (ROOT / "src" / "jsj_desktop" / "ui" /
                  "update_dialog.py").read_text(encoding="utf-8")
        self.assertIn("检查更新与升级…", ui)
        self.assertIn("def _show_update(", ui)
        for needle in ("当前版本", "最新版本", "立即更新", "更新失败",
                       "messagebox.showerror", "SHA256"):
            self.assertIn(needle, dialog)

    def test_cli_flags_exist_without_changing_defaults(self):
        from jsj_desktop.app import build_parser
        args = build_parser().parse_args([])
        self.assertFalse(args.cli)
        self.assertFalse(args.check_tls)
        self.assertFalse(args.self_test)
        self.assertFalse(args.check_update)
        self.assertFalse(args.apply_update)
        args = build_parser().parse_args(
            ["--apply-update", "--no-relaunch", "--manifest-url", "http://x"])
        self.assertTrue(args.apply_update)
        self.assertTrue(args.no_relaunch)
        self.assertEqual(args.manifest_url, "http://x")

    def test_privacy_doc_discloses_update_network_requests(self):
        text = (ROOT / "docs" / "PRIVACY.md").read_text(encoding="utf-8")
        self.assertIn("api.github.com", text)
        self.assertIn("检查更新", text)

    def test_channel_validator_succeeds(self):
        proc = run_py([sys.executable, "tools/check_update_channel.py",
                       "--offline"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("校验通过", proc.stdout)


if __name__ == "__main__":
    unittest.main()
