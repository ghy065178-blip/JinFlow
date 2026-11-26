# -*- coding: utf-8 -*-
"""检查更新与升级过程的异常分类。

所有异常都携带面向用户的中文说明（message）、机器可读的 code 与可操作的
建议（hint）；界面层统一用 user_message() 渲染失败提示，不会把堆栈直接抛给
用户。更新失败时安装位置保持原样，不破坏本机报名数据。
"""


class UpdateError(Exception):
    code = "unknown"

    def __init__(self, message, code=None, hint="", cause=None):
        super().__init__(message)
        self.message = str(message)
        self.code = code or self.code
        self.hint = hint or ""
        self.cause = cause

    def user_message(self):
        if self.hint:
            return "%s\n\n建议：%s" % (self.message, self.hint)
        return self.message

    def __str__(self):
        return "[%s] %s" % (self.code, self.message)


class NetworkError(UpdateError):
    code = "network"


class ChannelError(UpdateError):
    code = "channel"


class ManifestError(UpdateError):
    code = "manifest"


class AssetError(UpdateError):
    code = "asset"


class ChecksumError(UpdateError):
    code = "checksum"


class InstallError(UpdateError):
    code = "install"


class UnsupportedPlatformError(UpdateError):
    code = "unsupported-platform"


class IncompatibleVersionError(UpdateError):
    code = "incompatible-version"
