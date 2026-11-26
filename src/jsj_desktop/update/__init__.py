# -*- coding: utf-8 -*-
"""应用内检查更新与升级（1.2.0 新增，纯标准库）。

独立于 core/ 业务逻辑：不参与表单读取、联动规则、校时与提交，也不修改
报名信息.json / profiles.json。历史版本 1.0.0～1.0.3 的用户数据格式与
本模块完全兼容，可直接升级到 1.2.0。
"""
from . import client, installer, manifest, service, version
from .errors import (AssetError, ChannelError, ChecksumError, InstallError,
                     ManifestError, NetworkError, UnsupportedPlatformError,
                     UpdateError)
from .service import apply_update, check_for_update

__all__ = [
    "client", "installer", "manifest", "service", "version",
    "check_for_update", "apply_update",
    "UpdateError", "NetworkError", "ChannelError", "ManifestError",
    "AssetError", "ChecksumError", "InstallError",
    "UnsupportedPlatformError",
]
