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
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from jsj_desktop import __version__                      # noqa: E402
from jsj_desktop.data.paths import platform_label        # noqa: E402
import check_no_pii                                      # noqa: E402

APP = "JinshujuDesktop"
VALID_TARGETS = {"macos-x86_64", "macos-arm64",
                 "windows-x86_64", "windows-arm64"}


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
        if sign_identity:
            sign_macos(dest, sign_identity)
        inner = stage
    else:
        inner = stage / APP
        shutil.copytree(source, inner, symlinks=True)

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
        "data      : no bundled personal information; user data is created at runtime\n"
        % (APP, version, target, sys.version.split()[0], sys.platform,
           datetime.now().isoformat(timespec="seconds"), commit))
    (inner / "BUILD_INFO.txt").write_text(build_info, encoding="utf-8")
    shutil.copy2(ROOT / "LICENSE", inner / "LICENSE.txt")
    (inner / "README-RELEASE.txt").write_text(
        "双击 %s%s 启动；首次运行请在左侧「运行配置」填写本次表单链接。\n"
        "所有报名信息与多人档案只保存在本机用户数据目录，本包不含任何个人信息。\n"
        "详见仓库 README.md / docs/USER_GUIDE.md / docs/RELEASE.md。\n"
        % (APP, ".app" if is_bundle else ".exe"), encoding="utf-8")

    archive = out_root / ("%s-%s.zip" % (APP, target))
    if archive.exists():
        archive.unlink()
    if is_bundle:
        # ditto 保留 .app 内符号链接，普通 zip 会破坏签名与体积
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
             str(stage / (APP + ".app")), str(archive)])
        with zipfile.ZipFile(archive, "a") as zf:
            for extra in ("BUILD_INFO.txt", "LICENSE.txt", "README-RELEASE.txt"):
                zf.write(inner / extra, extra)
    else:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(stage.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    zf.write(path, path.relative_to(stage).as_posix())
    return archive


def write_checksums(out_root):
    lines = []
    for archive in sorted(out_root.glob("*.zip")):
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
    verify_ca_in_archive(archive)
    print("发布包 CA 根证书检查 OK（certs/cacert.pem）")

    findings = check_no_pii.scan_artifact(archive)
    if findings:
        print("发布包敏感数据扫描失败：")
        for rel, line, reason in findings[:20]:
            print("  - %s%s : %s" % (rel, (":%d" % line) if line else "", reason))
        raise SystemExit(1)
    print("发布包 PII 扫描 OK")

    lines = write_checksums(out_root)
    print("\n完成：%s" % archive)
    for line in lines:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
