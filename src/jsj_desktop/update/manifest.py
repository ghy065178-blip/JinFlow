# -*- coding: utf-8 -*-
"""版本无关的更新通道：清单格式、GitHub Releases 适配与平台资产选择。

通道设计要点：
  * 静态清单 update/latest.json 是权威来源，不含个人信息，旧版本与 1.3.0
    使用同一格式；GitHub Releases API 作为交叉校验来源，取两者中版本号更高者；
  * 任一来源失败不影响其它来源（例如 API 触发匿名限流）；全部失败才回退到
    随包内置清单，并明确标记 offline，禁止基于离线信息自动安装；
  * 资产名按「系统 + 架构」精确匹配，绝不把 x86_64 包装到 arm64 机器上。
"""
import json
import os
import re
from pathlib import Path

from ..data import paths as data_paths
from .errors import AssetError, ManifestError, UnsupportedPlatformError
from .version import (LEGACY_VERSIONS, MIN_UPGRADEABLE_VERSION,
                      normalize_version)

REPO_OWNER = "ghy065178-blip"
REPO_NAME = "jinshuju-registration-desktop"
REPO_URL = "https://github.com/%s/%s" % (REPO_OWNER, REPO_NAME)
API_LATEST = "https://api.github.com/repos/%s/%s/releases/latest" % (
    REPO_OWNER, REPO_NAME)
API_RELEASES = "https://api.github.com/repos/%s/%s/releases" % (
    REPO_OWNER, REPO_NAME)
RAW_MANIFEST = ("https://raw.githubusercontent.com/%s/%s/master/update/"
                "latest.json" % (REPO_OWNER, REPO_NAME))
LATEST_ASSET_URL = REPO_URL + "/releases/latest/download/latest.json"
RELEASE_PAGE = REPO_URL + "/releases/latest"
MANIFEST_SCHEMA = 1
ENV_MANIFEST_URL = "JSJ_UPDATE_MANIFEST_URL"

APP = "JinshujuDesktop"
TARGETS = ("macos-x86_64", "macos-arm64",
           "windows-x86_64", "windows-arm64")
ASSET_RE = re.compile(
    r"^JinshujuDesktop-(macos-x86_64|macos-arm64|windows-x86_64|"
    r"windows-arm64)\.(zip|dmg)$")


def platform_target(label=None):
    """把 (系统, 架构) 转成发布包标签；不支持的平台抛异常。"""
    system, arch = label or data_paths.platform_label()
    target = "%s-%s" % (system, arch)
    if target not in TARGETS:
        raise UnsupportedPlatformError(
            "当前平台 %s 没有对应的官方发布包。" % target,
            hint="请在 Releases 页面手动下载对应系统的安装包，"
                 "或改用源码运行（PYTHONPATH=src python -m jsj_desktop）。")
    return target


def asset_names(target):
    if target not in TARGETS:
        raise UnsupportedPlatformError("未知发布目标：%s" % target)
    names = {"zip": "%s-%s.zip" % (APP, target)}
    if target.startswith("macos"):
        names["dmg"] = "%s-%s.dmg" % (APP, target)
    return names


def validate_manifest(data, strict_assets=True):
    """校验并规范化清单；不合法一律抛 ManifestError，绝不静默放行。"""
    if not isinstance(data, dict):
        raise ManifestError("更新清单格式错误：不是 JSON 对象。")
    try:
        schema = int(data.get("schema", 0))
    except (TypeError, ValueError):
        schema = 0
    if schema != MANIFEST_SCHEMA:
        raise ManifestError(
            "更新清单版本不兼容（schema=%s，期望 %s）。" % (schema, MANIFEST_SCHEMA),
            hint="请升级到最新版的桌面程序，或在 Releases 页面手动下载。")

    version_raw = str(data.get("latest_version", "")).strip()
    try:
        latest = normalize_version(version_raw)
    except ValueError as e:
        raise ManifestError("更新清单缺少合法的最新版本号：%s" % e)

    tag = str(data.get("tag") or ("v" + latest)).strip()
    min_supported = str(data.get("min_supported_version")
                        or MIN_UPGRADEABLE_VERSION)
    try:
        normalize_version(min_supported)
    except ValueError as e:
        raise ManifestError("更新清单的最低可升级版本不合法：%s" % e)
    upgrade_target = str(data.get("upgrade_target") or latest)
    try:
        if normalize_version(upgrade_target) != latest:
            raise ManifestError(
                "更新清单的 upgrade_target(%s) 与 latest_version(%s) 不一致。"
                % (upgrade_target, latest))
    except ValueError as e:
        raise ManifestError("更新清单的 upgrade_target 不合法：%s" % e)

    assets = data.get("assets")
    if not isinstance(assets, dict):
        raise ManifestError("更新清单缺少 assets 平台资产表。")
    expected = {t: asset_names(t) for t in TARGETS}
    for target in TARGETS:
        entry = assets.get(target)
        if entry is None:
            if strict_assets:
                raise ManifestError("更新清单缺少 %s 平台的安装包。" % target)
            continue
        if not isinstance(entry, dict):
            raise ManifestError("更新清单中 %s 的资产格式错误。" % target)
        want = expected[target]["zip"]
        if entry.get("zip") != want:
            raise ManifestError(
                "%s 平台的压缩包名与预期不一致：%s != %s"
                % (target, entry.get("zip"), want),
                hint="可能拿到了其它架构的包，已阻止安装以避免架构不匹配。")
        if "dmg" in entry and target.startswith("macos"):
            if entry["dmg"] != expected[target]["dmg"]:
                raise ManifestError("%s 平台的 DMG 包名不合法。" % target)

    legacy = data.get("legacy_versions", list(LEGACY_VERSIONS))
    if not isinstance(legacy, list) or not all(isinstance(x, str) for x in legacy):
        raise ManifestError("更新清单的 legacy_versions 格式错误。")

    out = dict(data)
    out.update({
        "schema": schema,
        "latest_version": latest,
        "tag": tag,
        "min_supported_version": min_supported,
        "upgrade_target": latest,
        "legacy_versions": list(legacy),
        "notes": str(data.get("notes") or ""),
        "checksums_asset": str(data.get("checksums_asset") or "SHA256SUMS.txt"),
        "download_base": str(data.get("download_base")
                             or (REPO_URL + "/releases/download/%s/" % tag)),
        "manual_url": str(data.get("manual_url") or RELEASE_PAGE),
        "assets": assets,
        "urls": data.get("urls") if isinstance(data.get("urls"), dict) else {},
    })
    return out


def normalize_github_release(payload):
    """把 GitHub Releases API 的响应转换成与静态清单相同的结构。"""
    if isinstance(payload, list):
        candidates = [p for p in payload
                      if isinstance(p, dict) and not p.get("draft")
                      and not p.get("prerelease")]
        if not candidates:
            raise ManifestError("GitHub Releases 中没有可用版本。")
        payload = max(candidates, key=lambda p: str(p.get("tag_name", "")))
    if not isinstance(payload, dict):
        raise ManifestError("GitHub Releases 响应格式错误。")
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise ManifestError("GitHub Release 缺少 tag_name。")
    try:
        latest = normalize_version(tag)
    except ValueError as e:
        raise ManifestError("GitHub Release 的 tag 不是合法版本号：%s" % e)

    assets, urls = {}, {}
    for item in payload.get("assets") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        m = ASSET_RE.match(name)
        if m:
            target, kind = m.group(1), m.group(2)
            assets.setdefault(target, {})[kind] = name
        url = item.get("browser_download_url")
        if name and url:
            urls[name] = str(url)
    for target, entry in list(assets.items()):
        entry.setdefault("zip", asset_names(target)["zip"])
        entry.setdefault("sha256", "")

    data = {
        "schema": MANIFEST_SCHEMA,
        "channel": "github-api",
        "latest_version": latest,
        "tag": tag,
        "notes": str(payload.get("body") or "")[:1200],
        "min_supported_version": MIN_UPGRADEABLE_VERSION,
        "upgrade_target": latest,
        "legacy_versions": list(LEGACY_VERSIONS),
        "download_base": REPO_URL + "/releases/download/%s/" % tag,
        "checksums_asset": "SHA256SUMS.txt",
        "manual_url": str(payload.get("html_url") or RELEASE_PAGE),
        "assets": assets,
        "urls": urls,
    }
    return validate_manifest(data, strict_assets=False)


def asset_url(info, name):
    url = (info.get("urls") or {}).get(name)
    if url:
        return url
    for entry in (info.get("assets") or {}).values():
        if isinstance(entry, dict) and entry.get("url") and \
                entry.get("zip") == name:
            return entry["url"]
    return info["download_base"].rstrip("/") + "/" + name


def checksums_url(info):
    name = info.get("checksums_asset") or "SHA256SUMS.txt"
    return asset_url(info, name)


def select_asset(info, target):
    """返回当前平台可自动安装的 zip 资产（含 URL 与可选 sha256）。"""
    if target not in TARGETS:
        raise UnsupportedPlatformError("未知发布目标：%s" % target)
    entry = (info.get("assets") or {}).get(target)
    if not isinstance(entry, dict) or not entry.get("zip"):
        raise AssetError(
            "最新版本 %s 尚未提供 %s 平台的安装包。"
            % (info.get("latest_version", "?"), target),
            hint="请稍后重试，或在 Releases 页面手动下载对应系统的包。")
    name = entry["zip"]
    asset = {"name": name, "url": asset_url(info, name),
             "sha256": str(entry.get("sha256") or ""),
             "size": entry.get("size") or 0, "kind": "zip"}
    if target.startswith("macos") and entry.get("dmg"):
        asset["manual_name"] = entry["dmg"]
        asset["manual_url"] = asset_url(info, entry["dmg"])
    return asset


def channel_sources():
    """返回 (名称, URL, 类型)；环境变量可用于镜像/离线测试。"""
    override = os.environ.get(ENV_MANIFEST_URL, "").strip()
    if override:
        # 显式指定（镜像 / 内网 / 离线验证）时作为唯一来源，避免在无外网
        # 环境下仍逐条等待 GitHub 超时。
        return [("manifest-override", override, "manifest")]
    sources = [
        ("static-manifest", RAW_MANIFEST, "manifest"),
        ("github-api", API_LATEST, "github-api"),
        ("release-asset", LATEST_ASSET_URL, "manifest"),
    ]
    return sources


def local_manifest():
    """读取随包内置的清单（全部在线来源失败时的只读兜底）。"""
    path = Path(data_paths.resource_path("update/latest.json"))
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, ValueError) as e:
        raise ManifestError("随包内置的更新清单不可用：%s" % e)
    return validate_manifest(data)
