#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""历史版本独立升级助手（1.0.0～1.0.3 → 2.0.0），零第三方依赖。

2.0.0 已内置「帮助 → 检查更新与升级…」；但已发布的 1.0.x 冻结包里没有
更新代码，无法凭空获得应用内检查能力。本脚本作为发布资产
`JinFlow-Upgrade-Helper.py` 随 2.0.0 一起提供，旧版用户只需用
本机 Python 运行一次即可完成检测、下载、SHA256 校验与切换到 2.0.0。

    python JinFlow-Upgrade-Helper.py --check
    python JinFlow-Upgrade-Helper.py --upgrade
    python JinFlow-Upgrade-Helper.py --upgrade --app "/Applications/JinshujuDesktop.app"
    python JinFlow-Upgrade-Helper.py --upgrade --no-relaunch
    python JinFlow-Upgrade-Helper.py --repair --app "C:\\Apps\\JinshujuDesktop"

脚本与桌面版共用同一份 update/latest.json 清单与 SHA256SUMS.txt；不读取、
不上传、不修改任何报名信息或个人档案文件。
"""
import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from datetime import datetime

REPO = "https://github.com/ghy065178-blip/JinFlow"
RAW_MANIFEST = ("https://raw.githubusercontent.com/ghy065178-blip/"
                "JinFlow/master/update/latest.json")
LATEST_ASSET = REPO + "/releases/latest/download/latest.json"
RELEASE_PAGE = REPO + "/releases/latest"
TARGETS = ("macos-x86_64", "macos-arm64", "windows-x86_64", "windows-arm64")
APP = "JinshujuDesktop"  # 兼容历史可执行文件和本机数据目录
PACKAGE_NAME = "JinFlow"
VERSION_RE = re.compile(
    r"(?:JinFlow|JinshujuDesktop)?\s*v?(\d+(?:\.\d+){1,3})")


def fail(message):
    print("升级失败：%s" % message, file=sys.stderr)
    print("当前版本与报名数据保持不变。手动下载：%s" % RELEASE_PAGE,
          file=sys.stderr)
    return 1


def platform_target():
    system = {"Darwin": "macos", "Windows": "windows"}.get(platform.system(), "")
    machine = (platform.machine() or "").lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
    target = "%s-%s" % (system, arch)
    if target not in TARGETS:
        raise ValueError("当前平台 %s 没有官方发布包，请在 Releases 页面手动下载。" % target)
    return target


def vkey(text):
    s = str(text).strip().lstrip("vV").split("+")[0].split("-")[0]
    parts = [int(p) for p in s.split(".") if p.isdigit()]
    return tuple(parts + [0] * (4 - len(parts)))[:4]


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "JinFlow-Upgrade-Helper/2.0.0",
        "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout,
                                context=ssl.create_default_context()) as resp:
        return resp.read()


def load_manifest(override="", require_online=False):
    urls = ([override] if override else []) + [RAW_MANIFEST, LATEST_ASSET]
    errors = []
    for url in urls:
        try:
            data = json.loads(fetch(url).decode("utf-8-sig"))
            if not isinstance(data, dict) or not data.get("latest_version"):
                raise ValueError("清单缺少 latest_version")
            if int(data.get("schema", 0)) != 1:
                raise ValueError("清单 schema 不兼容")
            return data
        except Exception as e:
            errors.append("%s：%s" % (url, e))
    local = Path(__file__).resolve().parent / "update" / "latest.json"
    if not local.is_file():
        local = Path(__file__).resolve().parents[1] / "update" / "latest.json"
    if local.is_file() and not require_online:
        print("提示：在线更新通道不可用，使用随附清单（仅显示信息）。")
        return json.loads(local.read_text(encoding="utf-8"))
    raise ValueError("无法读取更新清单：" + "；".join(errors[:3]))


def detect_version(app_path):
    if not app_path:
        return ""
    root = Path(app_path)
    for rel in ("APP_VERSION.txt", "Contents/APP_VERSION.txt",
                "Contents/Resources/APP_VERSION.txt", "BUILD_INFO.txt"):
        p = root / rel
        if p.is_file():
            m = VERSION_RE.search(p.read_text(encoding="utf-8", errors="replace")
                                  .split("\n", 1)[0])
            if m:
                return m.group(1)
    return ""


def asset_info(manifest, target):
    entry = (manifest.get("assets") or {}).get(target) or {}
    name = entry.get("zip")
    if name != "%s-%s.zip" % (PACKAGE_NAME, target):
        raise ValueError("最新版本没有可用的 %s 安装包" % target)
    base = str(manifest.get("download_base")
               or (REPO + "/releases/download/%s/" % manifest.get("tag", "v2.0.0")))
    return name, base.rstrip("/") + "/" + name, str(entry.get("sha256") or "")


def checksums(manifest, name):
    base = str(manifest.get("download_base")
               or (REPO + "/releases/download/%s/" % manifest.get("tag", "v2.0.0")))
    url = base.rstrip("/") + "/" + str(manifest.get("checksums_asset")
                                       or "SHA256SUMS.txt")
    try:
        text = fetch(url).decode("utf-8-sig")
    except Exception:
        return ""
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and len(parts[0]) == 64 and parts[-1].lstrip("*") == name:
            return parts[0].lower()
    return ""


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract(archive, dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            rel = Path(info.filename.replace("\\", "/"))
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("发布包含非法路径：%s" % info.filename)
            if info.filename.startswith("__MACOSX/") or rel.name.startswith("._"):
                continue
            out = dest / rel
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                target = zf.read(info).decode("utf-8", "replace")
                if out.exists() or out.is_symlink():
                    out.unlink()
                try:
                    out.symlink_to(target)
                except (OSError, NotImplementedError):
                    pass
                continue
            with zf.open(info) as src, open(out, "wb") as fp:
                shutil.copyfileobj(src, fp)
            if mode & 0o111:
                try:
                    os.chmod(out, mode & 0o7777)
                except OSError:
                    pass
    return dest


def verify_package(root, target, version):
    root = Path(root)
    if target.startswith("macos"):
        app = root / (APP + ".app")
        if not app.is_dir():
            apps = sorted(root.glob("*.app"))
            if not apps:
                raise ValueError("发布包内没有 macOS 应用（.app）")
            app = apps[0]
        payload, launch = app, app / "Contents" / "MacOS" / APP
    else:
        payload = root / APP
        launch = payload / (APP + ".exe")
    marker = detect_version(payload) or detect_version(root)
    if not marker or vkey(marker) != vkey(version):
        raise ValueError("发布包版本不匹配：期望 %s，实际 %s" % (version, marker))
    for info in (payload / "BUILD_INFO.txt", root / "BUILD_INFO.txt"):
        if info.is_file():
            platform_marker = re.search(r"^target\s*:\s*(\S+)",
                                        info.read_text(encoding="utf-8"), re.M)
            if not platform_marker or platform_marker.group(1) != target:
                raise ValueError("发布包平台不匹配：期望 %s" % target)
            break
    else:
        raise ValueError("发布包缺少平台标记 BUILD_INFO.txt")
    if not launch.is_file():
        raise ValueError("发布包缺少可执行文件，可能下载不完整")
    return payload, launch


def _launch(exe, target):
    if target.startswith("macos"):
        subprocess.run(["open", "-n", str(exe.parents[2])], check=True)
    else:
        app = subprocess.Popen([str(exe)], cwd=str(exe.parent))
        try:
            status = app.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            return
        if status:
            raise OSError("新程序启动失败（退出码 %s）。" % status)


def switch(payload, launch, target, version, app_path, no_relaunch):
    """优先原位替换旧安装，否则在数据目录中安装并启动。"""
    home = Path.home()
    override = os.environ.get("JSJ_DATA_DIR", "").strip()
    if override:
        data_root = Path(override).expanduser()
    elif sys.platform == "darwin":
        data_root = home / "Library" / "Application Support" / APP
    elif sys.platform == "win32":
        data_root = Path(os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")) / APP
    else:
        data_root = Path(os.environ.get("XDG_DATA_HOME")
                         or str(home / ".local" / "share")) / "jinshuju-desktop"
    rel = launch.relative_to(payload)
    if app_path:
        old = Path(app_path).resolve()
        if data_root.resolve().is_relative_to(old):
            raise ValueError("报名数据目录位于旧程序目录内。请另选位置安装新版。")
        version_before = detect_version(old) or "old"
        backup = old.with_name(old.name + ".backup-" + version_before)
        suffix = 2
        while backup.exists():
            backup = old.with_name(old.name + ".backup-" + version_before + "-%d" % suffix)
            suffix += 1
        with tempfile.TemporaryDirectory(prefix=old.name + ".new-", dir=old.parent) as tmp:
            staged = Path(tmp) / old.name
            shutil.copytree(payload, staged, symlinks=True)
            try:
                old.rename(backup)
            except OSError as exc:
                raise OSError("无法备份原安装。请关闭所有使用该目录的程序，"
                              "并检查写入权限：%s" % exc) from exc
            moved_new = False
            try:
                staged.rename(old)
                moved_new = True
                if target.startswith("macos"):
                    subprocess.run(["codesign", "--force", "--deep", "--sign", "-",
                                    str(old)], check=False, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(old)],
                                   check=False, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                if not no_relaunch:
                    _launch(old / rel, target)
            except Exception:
                try:
                    if moved_new:
                        old.rename(staged)
                    backup.rename(old)
                except OSError as exc:
                    raise OSError("恢复安装失败。原程序备份位于 %s：%s" %
                                  (backup, exc)) from exc
                raise
        print("旧版本已备份：%s" % backup)
        return str(old)

    leaf = (PACKAGE_NAME + ".app") if target.startswith("macos") else APP
    dest_root = data_root / "updates" / version / leaf
    dest_root.parent.mkdir(parents=True, exist_ok=True)
    if dest_root.exists():
        dest_root = Path(tempfile.mkdtemp(prefix="install-", dir=dest_root.parent)) / leaf
    shutil.copytree(payload, dest_root, symlinks=True)
    if not no_relaunch:
        _launch(dest_root / rel, target)
    return str(dest_root)


def main(argv=None):
    ap = argparse.ArgumentParser(description="独立升级与修复助手")
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="只检查版本，不下载")
    modes.add_argument("--upgrade", action="store_true", help="下载校验并切换到新版")
    modes.add_argument("--repair", action="store_true",
                       help="关闭应用后重新安装当前发布版本，须指定 --app")
    ap.add_argument("--app", default="", help="旧版本安装路径（可选，用于原位替换）")
    ap.add_argument("--current-version", default="", help="显式指定当前旧版本号")
    ap.add_argument("--manifest-url", default="", help="覆盖更新清单地址")
    ap.add_argument("--no-relaunch", action="store_true", help="不自动启动新版本")
    args = ap.parse_args(argv)
    if not args.upgrade and not args.repair:
        args.check = True
    if args.repair and not args.app:
        ap.error("--repair 需要 --app 指定当前安装目录。请先关闭程序。")

    try:
        if args.app:
            old = Path(args.app).expanduser().resolve()
            if sys.platform == "win32" and old.name.lower() == (APP + ".exe").lower():
                old = old.parent
            if not old.is_dir() or (sys.platform == "win32" and
                                     not (old / (APP + ".exe")).is_file()) or (
                    sys.platform == "darwin" and old.suffix != ".app"):
                raise ValueError("找不到指定的旧版程序：%s" % old)
            args.app = str(old)
        manifest = load_manifest(args.manifest_url, require_online=not args.check)
        latest = str(manifest["latest_version"])
        minimum = str(manifest.get("min_supported_version") or "1.0.0")
        legacy = list(manifest.get("legacy_versions") or [])
        current = args.current_version or detect_version(args.app) or "1.0.3"
        try:
            target = platform_target()
            name, url, declared = asset_info(manifest, target)
        except ValueError:
            target, name, url, declared = "unsupported", "", "", ""
    except Exception as e:
        return fail(str(e))

    print("=== JinFlow · 版本检查 ===")
    print("当前版本   : %s" % current)
    print("最新版本   : %s" % latest)
    print("适用平台   : %s" % target)
    print("可升级范围 : >= %s；历史版本 %s" % (minimum, "、".join(legacy) or "-"))
    print("目标安装包 : %s" % name)
    print("手动下载   : %s" % RELEASE_PAGE)
    if vkey(current) < vkey(minimum):
        return fail("当前版本 %s 低于可升级下限 %s" % (current, minimum))
    if vkey(current) > vkey(latest) and args.repair:
        return fail("当前版本 %s 高于发布版本 %s，不能修复为更早版本。" % (current, latest))
    if vkey(current) >= vkey(latest) and not args.repair:
        print("结论       : 当前已是最新版本，无需升级。")
        return 0
    if legacy and current not in legacy and vkey(current) < vkey(minimum):
        return fail("当前版本不在兼容列表中")
    if args.repair and vkey(current) == vkey(latest):
        print("结论       : 可重新安装当前发布版本 %s。" % latest)
    else:
        print("结论       : 可从 %s 直接升级到 %s（报名数据保持原样）。"
              % (current, latest))
    if args.check:
        print("下载地址   : %s" % (url or "（当前平台无对应安装包，请手动下载）"))
        return 0
    if not name:
        return fail("当前平台没有官方发布包，请在 Releases 页面手动下载。")

    work = Path(tempfile.mkdtemp(prefix="jsj-legacy-upgrade-"))
    try:
        print("\n正在下载 %s …" % name)
        archive = work / name
        with urllib.request.urlopen(
                urllib.request.Request(url, headers={
                    "User-Agent": "JinFlow-Upgrade-Helper/2.0.0"}),
                timeout=60, context=ssl.create_default_context()) as resp, \
                open(archive, "wb") as fp:
            shutil.copyfileobj(resp, fp)
        expected = checksums(manifest, name) or declared
        if not expected:
            return fail("无法获取 %s 的 SHA256 校验和" % name)
        if declared and expected != declared.lower():
            return fail("清单与 SHA256SUMS.txt 的校验和不一致")
        if sha256_of(archive) != expected.lower():
            return fail("下载文件 SHA256 校验失败，已取消安装")
        print("SHA256 校验通过：%s" % expected)
        root = extract(archive, work / "package")
        payload, launch = verify_package(root, target, latest)
        installed = switch(payload, launch, target, latest, args.app, args.no_relaunch)
        print("\n升级完成：已切换到 v%s" % latest)
        print("安装位置   : %s" % installed)
        print("本机报名信息、档案与任务配置均未改动。")
        print("完成时间   : %s" % datetime.now().isoformat(timespec="seconds"))
        return 0
    except Exception as e:
        return fail(str(e))
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
