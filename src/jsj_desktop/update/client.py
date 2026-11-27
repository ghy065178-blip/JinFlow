# -*- coding: utf-8 -*-
"""更新通道访问：多来源探测、版本检查、资产下载与 SHA256 校验。

仅使用标准库 urllib/ssl/hashlib；macOS 冻结包通过 SSL_CERT_FILE 使用随包 CA
根证书（见 packaging/entry_point.py），不会关闭证书校验。任何一步失败都会
抛出带中文说明与 code 的 UpdateError，界面据此给出明确的失败提示。
"""
import hashlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .. import __release_revision__, __version__
from . import manifest as mf
from . import version as vmod
from .errors import (AssetError, ChannelError, ChecksumError,
                     ManifestError, NetworkError, UpdateError)

DEFAULT_TIMEOUT = 8.0
DOWNLOAD_TIMEOUT = 45.0
USER_AGENT = "JinFlow-Updater/%s" % __version__


class ReleaseInfo:
    """一次探测得到的规范化发布信息。"""

    def __init__(self, data, source, offline=False, errors=None):
        self.manifest = data
        self.source = source
        self.offline = offline
        self.errors = list(errors or [])
        self.package_version = data["latest_version"]
        self.version = data.get("product_version", self.package_version)
        self.revision = data.get("release_revision", 0)
        self.tag = data.get("tag", "v" + self.version)
        self.notes = data.get("notes", "")
        self.manual_url = data.get("manual_url", mf.RELEASE_PAGE)

    @property
    def has_hashes(self):
        return any(str(e.get("sha256") or "").strip()
                   for e in (self.manifest.get("assets") or {}).values()
                   if isinstance(e, dict))

    def quality(self):
        return (1 if self.has_hashes else 0,
                0 if self.source == "github-api" else 1)


class CheckResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def as_dict(self):
        return dict(self.__dict__)


def _request(url):
    return urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, application/octet-stream, */*",
        "Cache-Control": "no-cache",
    })


def _network_error(url, exc):
    if isinstance(exc, urllib.error.HTTPError):
        hint = ""
        if exc.code in (403, 429):
            hint = "GitHub 匿名接口可能触发限流，程序会自动尝试其它更新通道。"
        return NetworkError("访问更新通道失败（HTTP %s）。" % exc.code,
                            code="http-%s" % exc.code, hint=hint, cause=exc)
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return NetworkError("HTTPS 证书校验失败：%s" % reason,
                            code="tls", hint="请检查系统时间与网络代理；"
                            "macOS 版可用 --check-tls 诊断随包 CA 根证书。",
                            cause=exc)
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return NetworkError("无法连接更新通道：%s" % reason,
                            code="connect", hint="请检查网络、代理与系统时间后重试。",
                            cause=exc)
    return NetworkError("访问更新通道时出现未知错误：%s" % exc,
                        code="unexpected", cause=exc)


def _update_tls_context():
    context = ssl.create_default_context()
    bundle_root = getattr(sys, "_MEIPASS", None)
    if sys.platform == "win32" and bundle_root:
        bundle = Path(bundle_root) / "certs" / "cacert.pem"
        if bundle.is_file() and bundle.stat().st_size > 1000:
            # CPython 已载入 Windows ROOT / CA，随包根证书只作补充。
            context.load_verify_locations(cafile=str(bundle))
    return context


def http_get(url, timeout=DEFAULT_TIMEOUT):
    """读取一个小文本资源（清单 / API 响应 / SHA256SUMS.txt）。"""
    try:
        with urllib.request.urlopen(
                _request(url), timeout=timeout,
                context=_update_tls_context()) as resp:
            return resp.read()
    except Exception as e:  # noqa: BLE001 - 统一转换为带中文说明的异常
        raise _network_error(url, e)


def open_stream(url, timeout=DOWNLOAD_TIMEOUT):
    """打开下载流，返回支持上下文管理的响应对象。"""
    try:
        return urllib.request.urlopen(
            _request(url), timeout=timeout,
            context=_update_tls_context())
    except Exception as e:  # noqa: BLE001
        raise _network_error(url, e)


def fetch_latest(sources=None, fetcher=None, timeout=DEFAULT_TIMEOUT):
    """探测全部来源并取版本号最高的结果；全失败时回退随包清单（离线）。"""
    fetch = fetcher or http_get
    errors, candidates = [], []
    for name, url, kind in (sources or mf.channel_sources()):
        try:
            raw = fetch(url, timeout=timeout)
            text = raw.decode("utf-8-sig") if isinstance(raw, (bytes, bytearray)) \
                else str(raw)
            data = json.loads(text)
            info = (mf.normalize_github_release(data) if kind == "github-api"
                    else mf.validate_manifest(data))
            candidates.append(ReleaseInfo(info, name))
        except UpdateError as e:
            errors.append("%s：%s" % (name, e.message))
        except (ValueError, TypeError) as e:
            errors.append("%s：响应不是合法 JSON（%s）" % (name, e))
        except Exception as e:  # noqa: BLE001
            errors.append("%s：%s" % (name, e))

    if not candidates:
        try:
            bundled = mf.local_manifest()
        except ManifestError as e:
            errors.append("bundled：%s" % e.message)
            raise ChannelError(
                "无法获取最新版本信息，所有更新通道均不可用。",
                code="channel-unavailable",
                hint="请检查网络后重试，或打开 Releases 页面手动下载：%s"
                     % mf.RELEASE_PAGE,
                cause=errors)
        return ReleaseInfo(bundled, "bundled", offline=True, errors=errors)

    best = max(candidates, key=lambda c: (vmod.version_key(c.package_version), c.quality()))
    best.errors = errors + best.errors
    return best


def check_for_update(current_version=None, target=None, info=None,
                     timeout=DEFAULT_TIMEOUT, fetcher=None, sources=None, *,
                     current_revision=None):
    """返回 CheckResult：当前版本、最新版本、是否可升级、资产与失败原因。"""
    current = current_version or __version__
    if current_revision is None:
        current_revision = __release_revision__ if current == __version__ else 0
    try:
        info = info or fetch_latest(sources=sources, fetcher=fetcher,
                                    timeout=timeout)
        asset, asset_error = None, ""
        try:
            tgt = target or mf.platform_target()
        except UpdateError as e:
            # Linux 等没有官方二进制包的平台仍可正常显示版本信息
            tgt, asset_error = "unsupported", e.user_message()
        plan = vmod.upgrade_plan(
            vmod.package_version(current, current_revision), info.package_version,
            info.manifest.get("min_supported_version",
                              vmod.MIN_UPGRADEABLE_VERSION))
        if asset is None and not asset_error:
            try:
                asset = mf.select_asset(info.manifest, tgt)
            except AssetError as e:
                asset_error = e.user_message()
        try:
            matching_tag = vmod.normalize_version(info.tag) == info.version
        except ValueError:
            matching_tag = False
        can_update = bool(plan["update_available"] and plan["supported"] and asset
                          and matching_tag and not info.offline)
        reason = plan["reason"]
        if (info.revision and current == info.version and
                current_revision == info.revision):
            reason = "当前已是最新版本 %s（修订 %d）。" % (info.version, info.revision)
        if info.offline and plan["update_available"]:
            reason = ("无法连接更新通道，当前只显示随包内置的版本信息；"
                      "为避免安装过期版本，请手动下载或联网后重试。")
        elif asset_error and plan["update_available"]:
            reason = asset_error
        elif not matching_tag and plan["update_available"]:
            reason = "更新清单的发布标签与版本不一致，请稍后重新检查。"
        elif info.errors and plan["update_available"] and can_update:
            reason += "（部分更新通道不可用，已自动切换可用来源）"
        return CheckResult(
            ok=True, current_version=vmod.normalize_version(current),
            current_revision=current_revision, latest_revision=info.revision,
            latest_version=info.version, tag=info.tag,
            package_version=info.package_version,
            update_available=plan["update_available"],
            supported=plan["supported"], is_legacy=plan["is_legacy"],
            upgrade_path=plan["path"], target=tgt, asset=asset,
            asset_error=asset_error, info=info, notes=info.notes,
            source=info.source, offline=info.offline,
            channel_errors=list(info.errors), manual_url=info.manual_url,
            can_update=can_update, reason=reason)
    except UpdateError as e:
        return CheckResult(
            ok=False, current_version=str(current), latest_version="",
            current_revision=current_revision, latest_revision=0,
            update_available=False, can_update=False, supported=False,
            is_legacy=False, target=str(target or ""), asset=None,
            info=None, notes="", source="", offline=False,
            channel_errors=[e.message], manual_url=mf.RELEASE_PAGE,
            error=e, reason=e.user_message())
    except Exception as e:  # noqa: BLE001 - 界面不能因为未预期异常崩溃
        wrapped = NetworkError("检查更新时出现未预期错误：%s" % e, cause=e)
        return CheckResult(
            ok=False, current_version=str(current), latest_version="",
            current_revision=current_revision, latest_revision=0,
            update_available=False, can_update=False, supported=False,
            is_legacy=False, target=str(target or ""), asset=None,
            info=None, notes="", source="", offline=False,
            channel_errors=[wrapped.message], manual_url=mf.RELEASE_PAGE,
            error=wrapped, reason=wrapped.user_message())


def download_file(url, dest, progress=None, timeout=DOWNLOAD_TIMEOUT,
                  opener=None):
    """流式下载到 dest；progress(done, total) 用于界面进度条。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    stream = (opener or open_stream)(url, timeout=timeout)
    total = 0
    try:
        total = int(stream.headers.get("Content-Length") or 0)
    except (AttributeError, TypeError, ValueError):
        total = 0
    done = 0
    try:
        with stream, open(dest, "wb") as fp:
            while True:
                chunk = stream.read(256 * 1024)
                if not chunk:
                    break
                fp.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except Exception as e:  # noqa: BLE001
        try:
            dest.unlink()
        except OSError:
            pass
        raise _network_error(url, e)
    return done, total


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_checksums(text):
    """解析 `sha256  filename` 形式的 SHA256SUMS.txt。"""
    out = {}
    for line in str(text).splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and len(parts[0]) == 64:
            out[parts[-1].lstrip("*").split("/")[-1]] = parts[0].lower()
    return out


def resolve_checksum(info, asset, fetcher=None, timeout=DEFAULT_TIMEOUT):
    """优先使用 Release 的 SHA256SUMS.txt；与清单内置哈希交叉核对。"""
    fetch = fetcher or http_get
    declared = str(asset.get("sha256") or "").strip().lower()
    if declared and (len(declared) != 64 or
                     any(c not in "0123456789abcdef" for c in declared)):
        raise ChecksumError("更新清单中的 SHA256 格式不合法，已取消安装。")
    remote = ""
    try:
        raw = fetch(mf.checksums_url(info.manifest), timeout=timeout)
        text = raw.decode("utf-8-sig") if isinstance(raw, (bytes, bytearray)) \
            else str(raw)
        remote = parse_checksums(text).get(asset["name"], "").lower()
    except UpdateError:
        remote = ""   # 清单自带哈希时仍可继续，否则下面会明确报错
    if remote and declared and remote != declared:
        raise ChecksumError(
            "清单与 SHA256SUMS.txt 中 %s 的校验和不一致，已取消安装。"
            % asset["name"],
            hint="可能遇到缓存或镜像不同步，请稍后重试或手动下载。")
    chosen = remote or declared
    if not chosen:
        raise ChecksumError(
            "无法获取 %s 的 SHA256 校验和，已取消安装。" % asset["name"],
            hint="请确认该版本 Release 附带有 SHA256SUMS.txt；"
                 "也可在 Releases 页面手动下载。")
    return {"sha256": chosen,
            "source": "SHA256SUMS.txt" if remote else "更新清单"}


def verify_download(path, expected):
    actual = sha256_file(path)
    if actual != expected.lower():
        try:
            Path(path).unlink()
        except OSError:
            pass
        raise ChecksumError(
            "下载文件校验失败（SHA256 不一致），已删除并取消安装。",
            hint="可能是网络中断、代理篡改或镜像不同步，请重试；"
                 "必要时在 Releases 页面手动下载。")
    return actual
