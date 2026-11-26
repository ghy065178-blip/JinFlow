# -*- coding: utf-8 -*-
"""PyInstaller 冻结入口（不参与源码运行）。

构建时通过 `--paths src` 让 PyInstaller 解析 jsj_desktop 包；冻结后
jsj_desktop 位于打包归档中，直接导入即可。

macOS 的 Python/OpenSSL 不读取系统钥匙串，冻结后又找不到构建机上的 CA 路径，
会导致所有 HTTPS 请求报 CERTIFICATE_VERIFY_FAILED。构建脚本已把
certs/cacert.pem 打进包，这里在冻结 + macOS 下显式指向它。
"""
import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _find_ca_bundle(base):
    """PyInstaller 6 的 macOS .app 会把数据放在 Resources 或 Frameworks，
    这里把常见布局都覆盖到，避免因目录组织差异找不到证书。"""
    candidates = [
        os.path.join(base, "certs", "cacert.pem"),
        os.path.join(base, "Resources", "certs", "cacert.pem"),
        os.path.join(base, "..", "Resources", "certs", "cacert.pem"),
        "/etc/ssl/cert.pem",                       # macOS 系统兜底
        "/usr/local/etc/openssl/cert.pem",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 1000:
            return os.path.abspath(candidate)
    return None


def _ensure_ca_bundle():
    """让 OpenSSL 使用随包分发的 CA 根证书（仅冻结版 macOS 需要）。"""
    if not getattr(sys, "frozen", False) or sys.platform != "darwin":
        return
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return
    bundle = _find_ca_bundle(base)
    if bundle:
        os.environ.setdefault("SSL_CERT_FILE", bundle)


_ensure_ca_bundle()

from jsj_desktop.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
