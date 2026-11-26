# -*- coding: utf-8 -*-
"""macOS HTTPS 证书链回归测试。

背景：macOS 的 Python/OpenSSL 不读系统钥匙串；PyInstaller 冻结包若不携带
CA 根证书，所有 HTTPS 请求都会 CERTIFICATE_VERIFY_FAILED，表现为「能打开
窗口但读取表单失败」。本测试保证构建脚本与冻结入口始终带上 CA bundle。
"""
import os
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
import build  # noqa: E402

BUILD_SRC = (ROOT / "packaging" / "build.py").read_text(encoding="utf-8")
ENTRY_SRC = (ROOT / "packaging" / "entry_point.py").read_text(encoding="utf-8")
APP_SRC = (ROOT / "src" / "jsj_desktop" / "app.py").read_text(encoding="utf-8")


class CaBundleTest(unittest.TestCase):
    def test_locate_ca_bundle_prefers_certifi(self):
        with tempfile.TemporaryDirectory() as tmp:
            ca = Path(tmp) / "cacert.pem"
            ca.write_text("-----BEGIN CERTIFICATE-----\n" + "x" * 2048,
                          encoding="utf-8")
            fake = types.ModuleType("certifi")
            fake.where = lambda: str(ca)
            with patch.dict(sys.modules, {"certifi": fake}):
                self.assertEqual(build.locate_ca_bundle(), str(ca))

    def test_verify_ca_in_archive_accepts_mac_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ok.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(
                    "JinshujuDesktop.app/Contents/Resources/certs/cacert.pem",
                    "-----BEGIN CERTIFICATE-----")
            build.verify_ca_in_archive(archive)  # 不应抛异常

    def test_verify_ca_in_archive_accepts_windows_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "ok-win.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("JinshujuDesktop/_internal/certs/cacert.pem",
                            "-----BEGIN CERTIFICATE-----")
            build.verify_ca_in_archive(archive)

    def test_verify_ca_in_archive_rejects_missing_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("JinshujuDesktop/BUILD_INFO.txt", "x")
            with self.assertRaises(SystemExit):
                build.verify_ca_in_archive(archive)

    def test_build_adds_cert_data_and_verifies(self):
        for needle in ("locate_ca_bundle()", "%s%scerts",
                       "verify_ca_in_archive(archive)", "certs/cacert.pem"):
            self.assertIn(needle, BUILD_SRC, "构建脚本缺少：%s" % needle)

    def test_frozen_entry_sets_ssl_cert_file_on_macos(self):
        for needle in ("_ensure_ca_bundle", "SSL_CERT_FILE", "darwin",
                       "certs", "cacert.pem"):
            self.assertIn(needle, ENTRY_SRC, "冻结入口缺少：%s" % needle)

    def test_certifi_is_build_dependency(self):
        req = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
        self.assertIn("certifi", req)

    def test_check_tls_diagnostic_exists(self):
        self.assertIn("--check-tls", APP_SRC)
        self.assertIn("def run_tls_check", APP_SRC)
        from jsj_desktop.app import build_parser
        args = build_parser().parse_args(["--check-tls"])
        self.assertTrue(args.check_tls)

    def test_cli_still_defaults_to_gui(self):
        from jsj_desktop.app import build_parser
        args = build_parser().parse_args([])
        self.assertFalse(args.cli)
        self.assertFalse(args.check_tls)
        self.assertFalse(args.self_test)

    def test_frozen_macos_sets_ssl_cert_file(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "jsj_entry_point", ROOT / "packaging" / "entry_point.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            certs = Path(tmp) / "certs"
            certs.mkdir()
            ca = certs / "cacert.pem"
            ca.write_text("-----BEGIN CERTIFICATE-----\n" + "x" * 2048,
                          encoding="utf-8")
            fake_sys = types.SimpleNamespace(frozen=True, platform="darwin",
                                             _MEIPASS=tmp)
            with patch.object(module, "sys", fake_sys), \
                    patch.dict(os.environ, {}, clear=True):
                module._ensure_ca_bundle()
                self.assertEqual(os.environ.get("SSL_CERT_FILE"), str(ca))

    def test_ca_bundle_in_release_package_is_not_false_positive(self):
        """CA 证书里的 Base64/长数字不能被误判为 PII；私钥 .pem 仍须拦截。"""
        sys.path.insert(0, str(ROOT / "tools"))
        import check_no_pii
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "release.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(
                    "JinshujuDesktop.app/Contents/Resources/certs/cacert.pem",
                    "-----BEGIN CERTIFICATE-----\n"
                    "MIIF996312345678901234567890123456789012345678\n")
                zf.writestr(
                    "JinshujuDesktop.app/Contents/Resources/certs/private.pem",
                    "-----BEGIN PRIVATE KEY-----\n")
            findings = check_no_pii.scan_artifact(archive)
            self.assertFalse([f for f in findings if "cacert.pem" in f[0]],
                             "随包 CA 证书不应被误报")
            self.assertTrue([f for f in findings if "private.pem" in f[0]],
                            "私钥 .pem 仍必须被拦截")

    def test_frozen_windows_keeps_system_cert_store(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "jsj_entry_point_win", ROOT / "packaging" / "entry_point.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fake_sys = types.SimpleNamespace(frozen=True, platform="win32",
                                         _MEIPASS="/tmp/nonexistent")
        with patch.object(module, "sys", fake_sys), \
                patch.dict(os.environ, {}, clear=True):
            module._ensure_ca_bundle()
            self.assertIsNone(os.environ.get("SSL_CERT_FILE"))


if __name__ == "__main__":
    unittest.main()
