#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台发布包构建（PyInstaller 6.10+）。

必须在目标架构的机器上原生运行；不支持交叉编译。
    python packaging/build.py
    python packaging/build.py --target macos-arm64 --sign-identity "-"
"""
import argparse
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from jsj_desktop import __version__                      # noqa: E402
from jsj_desktop.data.paths import platform_label        # noqa: E402
import check_no_pii                                      # noqa: E402

APP = "JinshujuDesktop"  # 保留内部可执行文件名，兼容 1.x 更新与数据目录
PRODUCT_NAME = "JinFlow"
VALID_TARGETS = {"macos-x86_64", "macos-arm64",
                 "windows-x86_64", "windows-arm64"}

# 随包说明：macOS 从浏览器下载的 zip 会带 com.apple.quarantine，双击解压目录
# 里的 .app 会触发 Gatekeeper / App Translocation；若目录位于 iCloud 云盘且
# 同步未完成（bundle 里的文件只是云端占位符），LaunchServices 会直接报
# 「应用程序 … 无法打开」。DMG + 拖入「应用程序」是标准规避方式。
RELEASE_NOTES_MACOS = """JinFlow · macOS 首次运行必读
=========================================

【不要】直接在下载的压缩包、解压出来的文件夹、iCloud 桌面 / 云盘目录里
双击 JinFlow.app。macOS 会给下载的 app 加上隔离属性并从随机只读
路径运行；若该目录还在 iCloud 同步中，.app 内部的几百个文件可能尚未下载
到本地，这两种情况都会出现「应用程序 "JinshujuDesktop.app" 无法打开」。

正确做法（任选其一）：
1) 推荐：打开同目录的 .dmg，把 JinshujuDesktop.app 拖到卷内的「应用程序」
   图标上（即复制到 /Applications），再从「应用程序」启动。
   DMG 是单个只读映像，不会被云同步拆散，也不需要解压工具还原 .app 内的
   符号链接。
2) 或：把 zip 解压到本机「下载」文件夹（不要放在 iCloud 桌面 / 云盘），
   等同步完成，再把 .app 拖到「应用程序」或任意本地文件夹后打开。

若仍提示「无法打开」或「已损坏」，在「终端」执行：
   xattr -dr com.apple.quarantine /Applications/JinFlow.app
也可右键 .app →「打开」→「仍要打开」。

本包为 ad-hoc 签名、未经 Apple 公证（没有 Developer ID），系统提示属正常现象。
网络 / 证书诊断（只读，不会提交任何数据）：
   /Applications/JinFlow.app/Contents/MacOS/JinshujuDesktop --check-tls

检查更新：菜单「帮助 → 检查更新与升级…」可查看当前/最新版本并一键升级；
升级只替换程序文件，不改动本机报名信息与档案；失败会提示原因并保留当前版本。

所有报名信息与多人档案只保存在本机用户数据目录，本包不含任何个人信息。
首次运行请在左侧「运行配置」填写本次表单链接。
详见仓库 README.md / docs/USER_GUIDE.md / docs/RELEASE.md。
"""

RELEASE_NOTES_WINDOWS = """双击 JinshujuDesktop/%s.exe 启动；建议先解压到本地文件夹再运行。
首次运行请在左侧「运行配置」填写本次表单链接。
所有报名信息与多人档案只保存在本机用户数据目录，本包不含任何个人信息。
若出现 SmartScreen 提示，点「更多信息 → 仍要运行」。
检查更新：菜单「帮助 → 检查更新与升级…」，升级失败会提示原因并保留当前版本。
详见仓库 README.md / docs/USER_GUIDE.md / docs/RELEASE.md。
""" % APP


def locate_ca_bundle():
    """返回可随包分发的 CA 根证书文件。

    macOS 上的 Python/OpenSSL 不读取系统钥匙串；PyInstaller 冻结后
    ssl.get_default_verify_paths() 指向构建机上的绝对路径，在用户机器上不存在，
    所有 HTTPS 请求会报 CERTIFICATE_VERIFY_FAILED / unable to get local issuer
    certificate。因此必须把一份 CA bundle 打进发布包。找不到就构建失败，
    避免再次发布「能打开窗口但无法联网」的包。
    """
    candidates = []
    try:
        import certifi
        candidates.append(certifi.where())
    except ImportError:
        pass
    import ssl
    paths = ssl.get_default_verify_paths()
    candidates.append(paths.cafile)
    candidates += [
        "/etc/ssl/cert.pem",
        "/etc/ssl/certs/ca-certificates.crt",
        "/usr/local/etc/openssl/cert.pem",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) \
                and os.path.getsize(candidate) > 1000:
            return candidate
    raise SystemExit(
        "构建失败：找不到 CA 根证书，无法生成可联网的 macOS 发布包。"
        "请执行 pip install certifi 后重试。")


def verify_ca_in_archive(archive):
    """确保归档里确实带有 certs/cacert.pem（macOS 在 .app/Contents/Resources 下）。"""
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    if not any(name.endswith("certs/cacert.pem") for name in names):
        raise SystemExit("发布包缺少 certs/cacert.pem，macOS 端 HTTPS 会失败")


def verify_manifest_in_archive(archive):
    """确保冻结包带有随包更新清单（全部在线通道失败时的只读兜底）。"""
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    if not any(name.endswith("update/latest.json") for name in names):
        raise SystemExit("发布包缺少 update/latest.json，应用内更新无法离线兜底")
    if not any(name.endswith("APP_VERSION.txt") for name in names):
        raise SystemExit("发布包缺少 APP_VERSION.txt，升级后无法确认版本")


def run(cmd, **kwargs):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def check_prerequisites():
    try:
        import tkinter  # noqa: F401
    except ImportError as e:
        raise SystemExit("构建失败：当前 Python 缺少 Tcl/Tk（%s）。"
                         "请使用官方 Python 安装包并勾选 tcl/tk 组件。" % e)
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("构建失败：请先 pip install -r requirements-dev.txt")
    print("环境检查 OK：tkinter / PyInstaller 可用")


def host_target():
    system, arch = platform_label()
    if system == "linux":
        return "linux-" + arch
    return "%s-%s" % (system, arch)


def make_version_file(work, version):
    """由 packaging/version_info.txt 模板生成 Windows 版本资源。

    用正则替换，模板里的版本号可以是任意历史版本，不受硬编码字符串限制。
    """
    import re
    template = (ROOT / "packaging" / "version_info.txt").read_text(
        encoding="utf-8")
    parts = (version.split(".") + ["0", "0", "0", "0"])[:4]
    nums = [int(p) if p.isdigit() else 0 for p in parts]
    tuple_text = "(%s)" % ", ".join(str(n) for n in nums)
    text = re.sub(r"(filevers=)\([^)]*\)",
                  lambda m: m.group(1) + tuple_text, template)
    text = re.sub(r"(prodvers=)\([^)]*\)",
                  lambda m: m.group(1) + tuple_text, text)
    text = re.sub(
        r"(StringStruct\('(?:FileVersion|ProductVersion)', ')[^']*(')",
        lambda m: m.group(1) + ".".join(str(n) for n in nums) + m.group(2),
        text)
    out = work / "version_info.txt"
    out.write_text(text, encoding="utf-8")
    return out


def build_frozen(target, out_root, version):
    work = out_root / "build" / target
    raw = out_root / "raw" / target
    for p in (work, raw):
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True, exist_ok=True)

    sep = ";" if os.name == "nt" else ":"
    ca_bundle = locate_ca_bundle()
    print("随包 CA 根证书：%s" % ca_bundle)
    version_marker = work / "APP_VERSION.txt"
    version_marker.write_text("%s %s\n" % (APP, version), encoding="utf-8")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", APP,
        "--distpath", str(raw),
        "--workpath", str(work),
        "--specpath", str(work),
        "--paths", str(ROOT / "src"),
        "--hidden-import", "tkinter",
        "--collect-submodules", "jsj_desktop",
        "--add-data", "%s%stests/fixtures" %
        (str(ROOT / "tests" / "fixtures" / "sample_form.json"), sep),
        "--add-data", "%s%s." % (str(ROOT / "LICENSE"), sep),
        "--add-data", "%s%scerts" % (ca_bundle, sep),
        # 1.3.0：随包内置更新清单，在线通道全部不可用时可显示版本信息
        "--add-data", "%s%supdate" %
        (str(ROOT / "update" / "latest.json"), sep),
        "--add-data", "%s%s." % (str(version_marker), sep),
        "--add-data", "%s%spackaging/icons" %
        (str(ROOT / "packaging" / "icons" / "app.png"), sep),
    ]
    if target.startswith("macos"):
        cmd += ["--osx-bundle-identifier", "cn.jinshuju.desktop"]
        icon = ROOT / "packaging" / "icons" / "app.icns"
        if icon.exists():
            cmd += ["--icon", str(icon)]
    elif target.startswith("windows"):
        cmd += ["--version-file", str(make_version_file(work, version))]
        icon = ROOT / "packaging" / "icons" / "app.ico"
        if icon.exists():
            cmd += ["--icon", str(icon)]
    cmd.append(str(ROOT / "packaging" / "entry_point.py"))
    run(cmd, cwd=str(ROOT))
    return raw


def set_macos_bundle_version(app_bundle, version):
    """写入 Finder / LaunchServices 使用的 macOS 版本字段。"""
    info = Path(app_bundle) / "Contents" / "Info.plist"
    with info.open("rb") as fp:
        data = plistlib.load(fp)
    data["CFBundleShortVersionString"] = str(version)
    data["CFBundleVersion"] = str(version)
    data["CFBundleDisplayName"] = PRODUCT_NAME
    data["CFBundleName"] = PRODUCT_NAME
    data["CFBundleIdentifier"] = "cn.jinflow.desktop"
    with info.open("wb") as fp:
        plistlib.dump(data, fp, fmt=plistlib.FMT_XML, sort_keys=False)


def locate_app(raw):
    app_bundle = raw / (APP + ".app")
    if app_bundle.is_dir():
        return app_bundle, True
    folder = raw / APP
    if folder.is_dir():
        return folder, False
    raise SystemExit("构建失败：未在 %s 找到 %s.app 或 %s/" % (raw, APP, APP))


def sign_macos(app_bundle, identity):
    cmd = ["codesign", "--force", "--deep", "--sign", identity,
           "--entitlements", str(ROOT / "packaging" / "entitlements.plist"),
           "--options", "runtime"]
    run(cmd + [str(app_bundle)])
    run(["codesign", "--verify", "--deep", "--strict", str(app_bundle)])


def stage_and_pack(target, out_root, version, sign_identity):
    raw = out_root / "raw" / target
    source, is_bundle = locate_app(raw)
    stage = out_root / "stage" / target
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    if is_bundle:
        dest = stage / (APP + ".app")
        shutil.copytree(source, dest, symlinks=True)
        set_macos_bundle_version(dest, version)
        # 版本标记写在签名之前，并放在 Contents/Resources（由 CodeResources
        # 封签）。放在 Contents 根目录会被 codesign --verify --deep --strict
        # 判定为「code object is not signed at all」，导致 DMG 校验失败。
        (dest / "Contents" / "Resources" / "APP_VERSION.txt").write_text(
            "%s %s\n" % (APP, version), encoding="utf-8")
        if sign_identity:
            sign_macos(dest, sign_identity)
        elif sys.platform == "darwin":
            # 复制后重做 ad-hoc 签名：CodeResources 必须与最终 bundle 内容一致，
            # 否则 Gatekeeper / LaunchServices 可能判定签名损坏而拒绝启动。
            run(["codesign", "--force", "--deep", "--sign", "-", str(dest)])
            run(["codesign", "--verify", "--deep", "--strict", str(dest)])
        inner = stage
    else:
        inner = stage / APP
        shutil.copytree(source, inner, symlinks=True)

    # 压缩包根目录也放一份版本标记（包外文件，不参与签名），供升级时
    # 在解包后直接核对版本；Windows 版它就位于 JinshujuDesktop/ 目录内。
    (inner / "APP_VERSION.txt").write_text(
        "%s %s\n" % (APP, version), encoding="utf-8")

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        commit = "unknown"
    build_info = (
        "%s %s\n"
        "target    : %s\n"
        "python    : %s (%s)\n"
        "built_at  : %s\n"
        "commit    : %s\n"
        "runtime   : Python standard library only (tkinter + urllib)\n"
        "update    : in-app check + upgrade via help menu; channel v1.3.0\n"
        "data      : no bundled personal information; user data is created at runtime\n"
        % (APP, version, target, sys.version.split()[0], sys.platform,
           datetime.now().isoformat(timespec="seconds"), commit))
    (inner / "BUILD_INFO.txt").write_text(build_info, encoding="utf-8")
    shutil.copy2(ROOT / "LICENSE", inner / "LICENSE.txt")
    (inner / "README-RELEASE.txt").write_text(
        RELEASE_NOTES_MACOS if is_bundle else RELEASE_NOTES_WINDOWS,
        encoding="utf-8")

    archive = out_root / ("%s-%s.zip" % (PRODUCT_NAME, target))
    if archive.exists():
        archive.unlink()
    if is_bundle:
        # ditto 保留 .app 内符号链接，普通 zip 会破坏签名与体积
        # Keep the historical bundle directory for updater compatibility while
        # publishing the user-facing JinFlow archive name.
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
             str(stage / (APP + ".app")), str(archive)])
        with zipfile.ZipFile(archive, "a") as zf:
            for extra in ("BUILD_INFO.txt", "LICENSE.txt",
                         "README-RELEASE.txt", "APP_VERSION.txt"):
                zf.write(inner / extra, extra)
    else:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    zf.write(path, path.relative_to(stage).as_posix())
    return archive


def make_dmg(target, out_root):
    """生成 macOS 单文件只读磁盘映像，供用户拖入「应用程序」后运行。

    相比 zip：DMG 不会被 iCloud Drive 按文件拆散同步，也不需要解压工具
    还原 .app 内的符号链接，从根源上避免「第一次解压的 .app 打不开」。
    """
    stage = out_root / "stage" / target
    dmg = out_root / ("%s-%s.dmg" % (PRODUCT_NAME, target))
    if dmg.exists():
        dmg.unlink()
    with tempfile.TemporaryDirectory(prefix="jsj-dmg-stage-") as tmp:
        root = Path(tmp) / "volume"
        shutil.copytree(stage, root, symlinks=True)
        # 卷内提供「应用程序」快捷方式，用户直接把 .app 拖过去即可
        try:
            (root / "Applications").symlink_to("/Applications")
        except (OSError, NotImplementedError):
            pass
        run(["hdiutil", "create", "-volname", PRODUCT_NAME, "-srcfolder", str(root),
             "-ov", "-format", "UDZO", str(dmg)])
    return dmg


def _find_iscc():
    """Locate Inno Setup's compiler on a Windows build runner."""
    candidates = []
    if os.environ.get("ISCC_PATH"):
        candidates.append(Path(os.environ["ISCC_PATH"]))
    candidates += [
        Path(os.environ.get("PROGRAMFILES(X86)", "")) /
        "Inno Setup 6/ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", "")) /
        "Inno Setup 6/ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        "构建 Windows 安装版失败：找不到 Inno Setup ISCC.exe。"
        "请在 Windows 构建机安装 Inno Setup 6，或设置 ISCC_PATH。")


def make_windows_setup(target, out_root, version):
    """Build a per-architecture setup.exe with a normal uninstall entry."""
    if not target.startswith("windows"):
        return None
    iscc = _find_iscc()
    source = out_root / "stage" / target
    output_name = "%s-%s-Setup" % (PRODUCT_NAME, target)
    run([
        str(iscc), "/Q", "/DAppVersion=%s" % version,
        "/DSourceDir=%s" % source,
        "/DOutputDir=%s" % out_root,
        "/DOutputBaseName=%s" % output_name,
        str(ROOT / "packaging" / "windows_installer.iss"),
    ], cwd=str(ROOT))
    setup = out_root / (output_name + ".exe")
    if not setup.is_file():
        raise SystemExit("构建 Windows 安装版失败：未生成 %s" % setup.name)
    return setup


def write_checksums(out_root):
    lines = []
    archives = sorted(list(out_root.glob("*.zip")) +
                      list(out_root.glob("*.dmg")) +
                      list(out_root.glob("*.exe")))
    for archive in archives:
        h = hashlib.sha256()
        with open(archive, "rb") as fp:
            for chunk in iter(lambda: fp.read(1024 * 1024), b""):
                h.update(chunk)
        lines.append("%s  %s" % (h.hexdigest(), archive.name))
    if lines:
        (out_root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n",
                                                 encoding="utf-8")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="构建跨平台发布包")
    ap.add_argument("--target", default="",
                    help="目标标签；留空=自动识别本机（禁止交叉编译）")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="输出目录")
    ap.add_argument("--version", default=__version__, help="版本号（写入构建信息）")
    ap.add_argument("--sign-identity", default="",
                    help="macOS 签名身份；- 表示 ad-hoc 签名")
    args = ap.parse_args(argv)

    check_prerequisites()
    host = host_target()
    target = args.target or host
    if args.target and args.target != host:
        raise SystemExit("拒绝交叉编译：请求 %s，但本机是 %s。"
                         "请在对应架构的机器/CI runner 上构建。" % (args.target, host))
    if target not in VALID_TARGETS and not target.startswith("linux-"):
        raise SystemExit("未知目标：%s（合法值：%s）" %
                         (target, ", ".join(sorted(VALID_TARGETS))))
    out_root = Path(args.out).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    print("本机目标：%s，输出：%s" % (target, out_root))

    build_frozen(target, out_root, args.version)
    archive = stage_and_pack(target, out_root, args.version,
                             args.sign_identity)
    setup = make_windows_setup(target, out_root, args.version)
    verify_ca_in_archive(archive)
    verify_manifest_in_archive(archive)
    print("发布包 CA 根证书与更新清单检查 OK")

    findings = check_no_pii.scan_artifact(archive)
    if findings:
        print("发布包敏感数据扫描失败：")
        for rel, line, reason in findings[:20]:
            print("  - %s%s : %s" % (rel, (":%d" % line) if line else "", reason))
        raise SystemExit(1)
    print("发布包 PII 扫描 OK")

    if target.startswith("macos"):
        dmg = make_dmg(target, out_root)
        dmg_findings = check_no_pii.scan_artifact(dmg)
        if dmg_findings:
            print("DMG 敏感数据扫描失败：")
            for rel, line, reason in dmg_findings[:20]:
                print("  - %s%s : %s" %
                      (rel, (":%d" % line) if line else "", reason))
            raise SystemExit(1)
        print("DMG 生成并扫描 OK：%s" % dmg.name)

    if setup:
        print("Windows 安装版生成 OK：%s" % setup.name)

    lines = write_checksums(out_root)
    print("\n完成：%s" % archive)
    for line in lines:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
