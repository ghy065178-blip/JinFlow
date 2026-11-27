# -*- coding: utf-8 -*-
"""版本号解析、比较与历史版本兼容判定（纯函数，仅标准库）。

兼容 1.0.0 / 1.0.1 / 1.0.2 / 1.0.3 历史修复版本，以及 Windows
版本资源常用的四段式写法（1.0.3.0）、tag 前缀（v1.3.0）与预发布后缀。
历史版本的用户数据目录与配置格式与 2.0.0 完全一致，因此可直接升级。
"""
import re

# 已发布的历史版本全部可直接升到 2.0.0
LEGACY_VERSIONS = ("1.0.0", "1.0.1", "1.0.2", "1.0.3")
MIN_UPGRADEABLE_VERSION = "1.0.0"
UPGRADE_TARGET = "2.0.0"


def parse_version(text):
    """返回 (数字元组, 预发布字符串)；非法版本号抛 ValueError。"""
    if not isinstance(text, str):
        raise ValueError("版本号必须是字符串")
    s = text.strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    s = s.split("+", 1)[0].strip()
    pre = ""
    if "-" in s:
        s, pre = s.split("-", 1)
    parts = s.split(".")
    if not parts or len(parts) > 4:
        raise ValueError("版本号格式不合法：%s" % text)
    nums = []
    for part in parts:
        if not part.isdigit():
            raise ValueError("版本号格式不合法：%s" % text)
        nums.append(int(part))
    nums = tuple(nums + [0] * (4 - len(nums)))
    return nums, pre.strip().lower()


def normalize_version(text):
    nums, pre = parse_version(text)
    base = ".".join(str(n) for n in nums[:3])
    if nums[3]:
        base += ".%d" % nums[3]
    return base + ("-" + pre if pre else "")


def version_key(text):
    """可直接用于 max()/排序的键：正式版高于同数字预发布版。"""
    nums, pre = parse_version(text)
    if pre:
        pre_parts = tuple(
            (0, int(p)) if p.isdigit() else (1, p)
            for p in re.split(r"[._-]", pre) if p
        )
    else:
        pre_parts = ()
    return (nums, 0 if pre else 1, pre_parts)


def compare_versions(left, right):
    """left > right 返回 1；相等返回 0；否则返回 -1。"""
    a, b = version_key(left), version_key(right)
    return (a > b) - (a < b)


def is_newer(candidate, current):
    return compare_versions(candidate, current) > 0


def is_legacy(version, latest=UPGRADE_TARGET):
    try:
        return (normalize_version(version) in LEGACY_VERSIONS
                or compare_versions(version, latest) < 0)
    except ValueError:
        return False


def legacy_versions():
    return tuple(LEGACY_VERSIONS)


def upgrade_plan(current, latest, min_supported=MIN_UPGRADEABLE_VERSION,
                 current_revision=0, latest_revision=0):
    """判定从 current 能否升级到 latest，并给出升级路径与原因。"""
    try:
        cur = normalize_version(current)
        new = normalize_version(latest)
        floor = normalize_version(min_supported)
    except ValueError as e:
        return {"current": str(current), "latest": str(latest),
                "current_revision": 0, "latest_revision": 0,
                "update_available": False, "supported": False,
                "is_legacy": False, "path": "none",
                "reason": "版本号无法解析：%s" % e}

    try:
        current_revision = max(0, int(current_revision or 0))
        latest_revision = max(0, int(latest_revision or 0))
    except (TypeError, ValueError):
        return {"current": cur, "latest": new, "min_supported": floor,
                "current_revision": 0, "latest_revision": 0,
                "update_available": False, "supported": False,
                "is_legacy": False, "path": "none",
                "reason": "发布修订号无法解析。"}
    result = {"current": cur, "latest": new, "min_supported": floor,
              "current_revision": current_revision,
              "latest_revision": latest_revision,
              "update_available": False, "supported": True,
              "is_legacy": False, "path": "none", "reason": ""}
    if compare_versions(cur, floor) < 0:
        result["supported"] = False
        result["reason"] = ("当前版本 %s 低于可升级下限 %s，无法自动升级，"
                            "请手动下载完整安装包覆盖安装。" % (cur, floor))
        return result
    if compare_versions(cur, new) > 0:
        result["reason"] = ("当前版本 %s 高于发布通道版本 %s（开发/预览构建），"
                            "无需升级。" % (cur, new))
        return result
    comparison = compare_versions(cur, new)
    if comparison == 0 and latest_revision > current_revision:
        result["update_available"] = True
        result["path"] = "direct"
        result["reason"] = ("发现同版本新发布修订版 %s（当前修订版 %s），可直接升级；"
                             "本机报名信息与档案不会被修改。"
                             % (latest_revision, current_revision))
        return result
    if comparison == 0:
        result["reason"] = "当前已是最新版本 %s。" % new
        return result
    result["update_available"] = True
    result["is_legacy"] = is_legacy(cur, new) or cur in LEGACY_VERSIONS
    result["path"] = "direct" if result["is_legacy"] else "direct"
    result["reason"] = ("发现新版本 %s（当前 %s），可直接升级；本机报名信息与"
                        "档案不会被修改。" % (new, cur))
    return result
