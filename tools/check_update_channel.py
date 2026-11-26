#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新通道静态校验（不联网，供 CI / Release / 本地发布前检查）。

    python tools/check_update_channel.py --offline
    python tools/check_update_channel.py --offline --checksums dist/SHA256SUMS.txt

校验：三处版本号一致、与清单 1.3.0 一致、清单 schema / 历史版本兼容表 /
四平台资产名 / 校验和文件名合法；传入 SHA256SUMS.txt 时还确认每个平台包
都有对应校验和。失败即返回非零，防止发出「版本号不对 / 旧版本升不上来」的 Release。
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jsj_desktop import __version__                       # noqa: E402
from jsj_desktop.update import manifest as mf             # noqa: E402
from jsj_desktop.update import version as vmod            # noqa: E402


def _pyproject_version():
    try:
        import tomllib
        with open(ROOT / "pyproject.toml", "rb") as fp:
            return str(tomllib.load(fp)["project"]["version"])
    except (ImportError, KeyError, OSError, ValueError) as e:
        return "读取失败：%s" % e


def _windows_version():
    text = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    m = re.search(r"StringStruct\('FileVersion', '([^']+)'\)", text)
    return m.group(1) if m else "读取失败"


def _checksums(path):
    out = {}
    if not path:
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and len(parts[0]) == 64:
            out[parts[-1].lstrip("*")] = parts[0].lower()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="校验应用内更新通道配置")
    ap.add_argument("--offline", action="store_true", help="只做本地静态校验")
    ap.add_argument("--checksums", default="", help="SHA256SUMS.txt 路径")
    args = ap.parse_args(argv)

    errors = []
    manifest_path = ROOT / "update" / "latest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        data = mf.validate_manifest(raw)
    except Exception as e:
        print("更新清单不可用：%s" % e, file=sys.stderr)
        return 1

    pyproject = _pyproject_version()
    win_version = _windows_version()
    win_core = ".".join(win_version.split(".")[:3])
    print("=== 更新通道静态校验 ===")
    print("源码版本   : %s" % __version__)
    print("包元数据   : %s" % pyproject)
    print("Windows 版 : %s" % win_version)
    print("清单版本   : %s（tag %s，目标 %s）"
          % (data["latest_version"], data["tag"], data["upgrade_target"]))
    for label, value in (("pyproject.toml", pyproject),
                         ("version_info.txt", win_core),
                         ("latest.json", data["latest_version"]),
                         ("upgrade_target", data["upgrade_target"])):
        if value != __version__:
            errors.append("%s 的版本 %s 与 __version__ %s 不一致"
                          % (label, value, __version__))
    if __version__ != vmod.UPGRADE_TARGET:
        errors.append("代码中的升级目标 %s 不是 %s"
                      % (vmod.UPGRADE_TARGET, __version__))

    legacy = list(data.get("legacy_versions") or [])
    missing = [v for v in vmod.LEGACY_VERSIONS if v not in legacy]
    if missing:
        errors.append("历史版本兼容表缺少：%s" % "、".join(missing))
    paths = data.get("legacy_upgrade_paths") or {}
    for v in vmod.LEGACY_VERSIONS:
        entry = paths.get(v) or {}
        if entry.get("upgrade_to") != data["latest_version"]:
            errors.append("历史版本 %s 未指向最新版 %s"
                          % (v, data["latest_version"]))
        if not entry.get("data_compatible"):
            errors.append("历史版本 %s 未标记数据兼容" % v)
    try:
        if vmod.compare_versions(data["min_supported_version"], "1.0.0") > 0:
            errors.append("min_supported_version 高于 1.0.0，旧版本将无法升级")
    except ValueError as e:
        errors.append("min_supported_version 不合法：%s" % e)

    expected = []
    for target in mf.TARGETS:
        names = mf.asset_names(target)
        expected.append(names["zip"])
        if "dmg" in names:
            expected.append(names["dmg"])
        print("平台资产   : %-18s %s" % (target, names["zip"]))
        asset = mf.select_asset(data, target)
        if not asset["url"].startswith("https://"):
            errors.append("%s 的下载地址不是 HTTPS" % target)
    if data.get("checksums_asset") != "SHA256SUMS.txt":
        errors.append("checksums_asset 不是 SHA256SUMS.txt")
    for v in vmod.LEGACY_VERSIONS:
        plan = vmod.upgrade_plan(v, data["latest_version"],
                                 data["min_supported_version"])
        if not (plan["update_available"] and plan["supported"]):
            errors.append("历史版本 %s 无法升级到 %s" %
                          (v, data["latest_version"]))
    print("历史兼容   : %s → %s（%d 个版本）"
          % ("、".join(vmod.LEGACY_VERSIONS), data["latest_version"],
             len(vmod.LEGACY_VERSIONS)))

    if args.checksums:
        sums = _checksums(args.checksums)
        for name in expected:
            if name not in sums:
                errors.append("SHA256SUMS.txt 缺少 %s" % name)
        print("校验和覆盖 : %d/%d 个发布资产"
              % (sum(1 for n in expected if n in sums), len(expected)))

    if errors:
        print("\n校验失败：", file=sys.stderr)
        for e in errors:
            print("  - %s" % e, file=sys.stderr)
        return 1
    print("\n校验通过：版本号、四平台资产、历史版本升级路径与校验和配置一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
