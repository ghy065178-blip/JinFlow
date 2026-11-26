# -*- coding: utf-8 -*-
"""四平台安装 / 切换与回滚（仅标准库）。

原则：
  1. 先下载到临时目录、校验 SHA256、验证包内 APP_VERSION.txt 与 BUILD_INFO.txt
     的「版本 + 平台」再动安装位置；任何一步失败都保持现有版本原样。
  2. macOS 用「旧 .app 改名备份 → 新 .app 就位 → 重做 ad-hoc 签名 → 去隔离
     属性 → open -n 重启」；替换失败自动恢复备份。
  3. Windows 运行中无法覆盖自身 exe，故先暂存新目录，再写一个独立 .cmd 在
     进程退出后完成替换与重启，脚本内自带失败回滚。
  4. 源码运行 / 无写入权限时切换到 <数据目录>/updates/<版本>/ 并直接启动新版，
     不改动源码与任何报名数据。
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from .. import __version__
from ..data import paths as data_paths
from . import manifest as mf
from .errors import InstallError
from .version import compare_versions, normalize_version

APP = "JinshujuDesktop"
VERSION_MARKER = "APP_VERSION.txt"
VERSION_RE = re.compile(r"(?:JinshujuDesktop\s+)?v?(\d+(?:\.\d+){1,3})")


def platform_target(label=None):
    return mf.platform_target(label)


def _read_version_marker(root):
    root = Path(root)
    for rel in (VERSION_MARKER, "Contents/" + VERSION_MARKER,
                "BUILD_INFO.txt"):
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        m = VERSION_RE.search(text.splitlines()[0] if text.splitlines() else "")
        if m:
            try:
                return normalize_version(m.group(1))
            except ValueError:
                continue
    return ""


def install_context():
    """识别当前运行形态，决定可安全采用的升级方式。"""
    exe = Path(sys.executable).resolve()
    frozen = bool(getattr(sys, "frozen", False))
    system, arch = data_paths.platform_label()
    target = "%s-%s" % (system, arch)
    ctx = {"frozen": frozen, "system": system, "target": target,
           "executable": str(exe), "pid": os.getpid(), "mode": "source",
           "app_bundle": "", "install_root": "",
           "current_version": "",
           "data_dir": str(data_paths.data_dir())}
    if frozen and sys.platform == "darwin" and len(exe.parents) > 2:
        app = exe.parents[2]
        if app.name == APP + ".app":
            ctx["mode"] = "macos-app"
            ctx["app_bundle"] = str(app)
            ctx["install_root"] = str(app.parent)
    elif frozen and sys.platform == "win32":
        root = exe.parent
        if root.name == APP:
            ctx["mode"] = "windows-dir"
            ctx["install_root"] = str(root)
    if ctx["install_root"]:
        ctx["current_version"] = _read_version_marker(
            ctx["app_bundle"] or ctx["install_root"]) or __version__
    return ctx


def find_legacy_installations():
    """扫描常见安装位置，供界面提示「检测到旧版本」（只读，不移动任何文件）。"""
    home = Path.home()
    mac_app = APP + ".app"
    candidates = []
    if sys.platform == "darwin":
        candidates = [Path("/Applications") / mac_app,
                      home / "Applications" / mac_app,
                      home / "Downloads" / mac_app,
                      home / "Desktop" / mac_app]
    elif sys.platform == "win32":
        roots = [os.environ.get("LOCALAPPDATA"), os.environ.get("PROGRAMFILES"),
                 os.environ.get("APPDATA")]
        for raw in roots:
            if raw:
                candidates.append(Path(raw) / APP)
                candidates.append(Path(raw) / APP / (APP + ".exe"))
        candidates += [home / "Downloads" / APP, home / "Desktop" / APP]
    found = []
    seen = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.exists():
            continue
        marker = _read_version_marker(path)
        try:
            legacy = bool(marker) and compare_versions(marker, __version__) < 0
        except ValueError:
            legacy = False
        if legacy or not marker:
            found.append({"path": key,
                          "version": marker or "1.0.x（旧版，无版本标记）",
                          "legacy": True})
    return found


def extract_zip(archive, dest):
    """解包并还原 Unix 符号链接与可执行位（ditto 生成的 macOS 包需要）。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            raw = info.filename
            rel = Path(raw.replace("\\", "/"))
            if rel.is_absolute() or ".." in rel.parts:
                raise InstallError("发布包包含非法路径，已取消安装：%s" % raw)
            if raw.startswith("__MACOSX/") or rel.name.startswith("._"):
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
                    pass   # Windows 无符号链接权限时按普通文件跳过
                continue
            with zf.open(info) as src, open(out, "wb") as fp:
                shutil.copyfileobj(src, fp)
            if mode & 0o111:
                try:
                    os.chmod(out, mode & 0o7777)
                except OSError:
                    pass
    return dest


def _find_build_info(root):
    for rel in ("BUILD_INFO.txt", APP + "/BUILD_INFO.txt",
                (APP + ".app") + "/Contents/BUILD_INFO.txt"):
        p = Path(root) / rel
        if p.is_file():
            return p
    for p in sorted(Path(root).glob("*/BUILD_INFO.txt")):
        return p
    return None


def validate_package(root, target, version):
    """确认包内版本与平台与本次升级一致，且包含可启动的可执行文件。"""
    root = Path(root)
    system = target.split("-")[0]
    if system == "macos":
        app = root / (APP + ".app")
        if not app.is_dir():
            apps = sorted(root.glob("*.app"))
            app = apps[0] if apps else app
        payload = app
        launch = app / "Contents" / "MacOS" / APP
    else:
        exe = root / APP / (APP + ".exe")
        if not exe.is_file():
            exe = root / (APP + ".exe")
        payload = root / APP if (root / APP).is_dir() else root
        launch = exe

    build_info = _find_build_info(root)
    marker_roots = [payload,
                    payload / "Contents" if system == "macos" else payload]
    found_version = ""
    for candidate in marker_roots:
        found_version = _read_version_marker(candidate)
        if found_version:
            break
    if not found_version and build_info:
        try:
            first = build_info.read_text(encoding="utf-8").splitlines()[0]
            m = VERSION_RE.search(first)
            if m:
                found_version = normalize_version(m.group(1))
        except (OSError, UnicodeDecodeError, ValueError):
            found_version = ""
    if not found_version:
        raise InstallError(
            "发布包缺少版本标记（%s / BUILD_INFO.txt），已取消安装。" % VERSION_MARKER,
            hint="请重新下载完整发布包；不要手动修改压缩包内容。")
    if found_version != normalize_version(version):
        raise InstallError(
            "发布包版本不匹配：期望 %s，实际 %s，已取消安装。"
            % (version, found_version),
            hint="可能是下载缓存指向了旧版本，请清理后重试。")
    if build_info:
        try:
            text = build_info.read_text(encoding="utf-8")
            m = re.search(r"^target\s*:\s*(\S+)", text, re.M)
            if m and m.group(1) != target:
                raise InstallError(
                    "发布包平台不匹配：当前 %s，包内 %s，已取消安装。"
                    % (target, m.group(1)),
                    hint="请确认下载的是与本机 CPU 架构一致的安装包，"
                         "不要跨架构混用。")
        except (OSError, UnicodeDecodeError):
            pass
    if not launch.is_file():
        raise InstallError(
            "发布包缺少可执行文件：%s" % launch.name,
            hint="压缩包可能未完整下载，请重新下载后重试。")
    return {"root": str(root), "payload_dir": str(payload),
            "launch_path": str(launch), "version": found_version,
            "target": target, "build_info": str(build_info or "")}


def _unique_path(base):
    path = Path(base)
    if not path.exists():
        return path
    for i in range(2, 100):
        alt = Path(str(path) + "-%d" % i)
        if not alt.exists():
            return alt
    return Path(str(path) + "-final")


def plan_install(ctx, package, version):
    """生成安装计划；不写任何文件，便于单元测试逐平台验证。"""
    version = normalize_version(version)
    updates_root = Path(ctx["data_dir"]) / "updates"
    mode = ctx["mode"]
    if mode == "macos-app":
        old = Path(ctx["app_bundle"])
        if old.parent.exists() and os.access(str(old.parent), os.W_OK):
            return {"ok": True, "mode": "macos-app", "can_auto": True,
                    "target_path": str(old),
                    "backup_path": str(_unique_path(
                        str(old) + ".backup-" + (ctx["current_version"] or "old"))),
                    "new_app": package["payload_dir"],
                    "launch_path": str(Path(old) / "Contents" / "MacOS" / APP),
                    "version": version,
                    "note": "将备份现有 .app，替换后自动重启新版本。"}
        mode = "staged"
    elif mode == "windows-dir":
        old = Path(ctx["install_root"])
        parent = old.parent
        if parent.exists() and os.access(str(parent), os.W_OK):
            return {"ok": True, "mode": "windows-dir", "can_auto": True,
                    "target_path": str(old),
                    "backup_path": str(_unique_path(
                        str(old) + ".backup-" + (ctx["current_version"] or "old"))),
                    "staged_path": str(_unique_path(
                        str(parent / (APP + ".new-" + version)))),
                    "script_path": str(updates_root / ("upgrade-%s.cmd" % version)),
                    "payload_dir": package["payload_dir"],
                    "launch_path": str(old / (APP + ".exe")),
                    "version": version,
                    "note": "程序退出后由独立脚本完成替换并自动重启。"}
        mode = "staged"

    dest = updates_root / version / ctx["target"]
    # 注意：ctx["system"] 来自 platform_label()，取值是 macos/windows/linux，
    # 不是 sys.platform 的 darwin/win32。
    launchable = Path(package["launch_path"]).is_file() and \
        ctx["system"] in ("macos", "windows")
    rel_launch = Path(package["launch_path"]).relative_to(
        package["payload_dir"])
    return {"ok": True, "mode": "staged", "can_auto": launchable,
            "target_path": str(dest), "backup_path": "",
            "payload_dir": package["payload_dir"],
            "launch_path": str(dest / rel_launch),
            "launch_rel": rel_launch.as_posix(),
            "version": version,
            "note": ("新版将解压到本机数据目录并直接启动（不改动源码与报名数据）。"
                     if launchable else
                     "当前平台没有可直接运行的发布包，仅完成下载与校验，"
                     "请在 Releases 页面手动安装。")}


def _best_effort(cmd, runner):
    try:
        runner(cmd, check=False, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL)
    except Exception:
        pass   # 签名/去隔离属性失败不阻断升级，只影响 Gatekeeper 提示


def _popen(cmd, runner, **kwargs):
    try:
        return runner(cmd, **kwargs)
    except Exception as e:
        raise InstallError("无法启动新版本：%s" % e,
                           hint="请手动打开新版本所在目录启动程序。", cause=e)


def _windows_script(plan, pid):
    """生成退出后替换的 .cmd；用 f-string 拼接，避免 cmd 的 %VAR% 与 % 格式化冲突。"""
    exe = APP + ".exe"
    return "\r\n".join([
        "@echo off",
        "setlocal",
        f'set "OLD={plan["target_path"]}"',
        f'set "NEW={plan["staged_path"]}"',
        f'set "BACKUP={plan["backup_path"]}"',
        ":wait",
        f'tasklist /FI "PID eq {pid}" /NH 2>nul | find "{pid}" >nul',
        "if not errorlevel 1 (",
        "  timeout /t 1 /nobreak >nul",
        "  goto wait",
        ")",
        'if exist "%OLD%" move /Y "%OLD%" "%BACKUP%" >nul',
        'move /Y "%NEW%" "%OLD%" >nul',
        f'if not exist "%OLD%\\{exe}" (',
        '  if exist "%BACKUP%" move /Y "%BACKUP%" "%OLD%" >nul',
        "  exit /b 1",
        ")",
        f'start "" "%OLD%\\{exe}"',
        "exit /b 0",
        "",
    ])


def apply_install(plan, relaunch=True, runner=None, pid=None):
    """执行安装计划；失败时回滚并抛 InstallError。runner 可注入便于测试。"""
    runner = runner or subprocess.run
    pid = pid or os.getpid()
    mode = plan["mode"]

    if mode == "macos-app":
        old = Path(plan["target_path"])
        backup = Path(plan["backup_path"])
        new_app = Path(plan["new_app"])
        moved_old = False
        try:
            if old.exists() or old.is_symlink():
                shutil.move(str(old), str(backup))
                moved_old = True
            shutil.move(str(new_app), str(old))
        except Exception as e:
            if moved_old and backup.exists() and not old.exists():
                shutil.move(str(backup), str(old))
            raise InstallError("替换应用失败：%s" % e,
                               hint="现有版本已保留，请重试或手动拖入「应用程序」。",
                               cause=e)
        new_launch = old / "Contents" / "MacOS" / APP
        if not new_launch.is_file():
            shutil.rmtree(str(old), ignore_errors=True)
            if moved_old and backup.exists():
                shutil.move(str(backup), str(old))
            raise InstallError("新版本包结构不完整，已恢复原版本。",
                               hint="请重新下载完整发布包后重试。")
        _best_effort(["codesign", "--force", "--deep", "--sign", "-", str(old)],
                     runner)
        _best_effort(["xattr", "-dr", "com.apple.quarantine", str(old)], runner)
        if relaunch:
            _popen(["open", "-n", str(old)], runner)
        return {"ok": True, "mode": mode, "installed_to": str(old),
                "backup": str(backup) if moved_old else "",
                "launched": bool(relaunch),
                "message": "已安装并切换到 %s（原版本已备份）。" % plan["version"]}

    if mode == "windows-dir":
        staged = Path(plan["staged_path"])
        script = Path(plan["script_path"])
        try:
            script.parent.mkdir(parents=True, exist_ok=True)
            if staged.exists():
                shutil.rmtree(str(staged))
            shutil.copytree(plan["payload_dir"], str(staged), symlinks=True)
            script.write_text(_windows_script(plan, pid), encoding="utf-8")
        except Exception as e:
            raise InstallError("暂存新版本失败：%s" % e,
                               hint="现有版本未改动，请检查磁盘空间与写入权限。",
                               cause=e)
        if relaunch:
            flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_GROUP
            _popen(["cmd.exe", "/c", str(script)], runner,
                   creationflags=flags, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   close_fds=True)
        return {"ok": True, "mode": mode, "installed_to": plan["target_path"],
                "backup": plan["backup_path"], "staged": str(staged),
                "script": str(script), "launched": bool(relaunch),
                "message": "新版已暂存，程序退出后将自动完成替换并重启。"}

    # 源码运行 / 无写入权限 / 手动模式
    dest = Path(plan["target_path"])
    try:
        if dest.exists():
            shutil.rmtree(str(dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(plan["payload_dir"], str(dest), symlinks=True)
    except Exception as e:
        raise InstallError("切换到新版本失败：%s" % e,
                           hint="现有版本与报名数据未改动，请检查写入权限。",
                           cause=e)
    launched = False
    if relaunch and plan.get("can_auto"):
        launch = Path(plan["launch_path"])
        if launch.is_file():
            _popen([str(launch)], runner)
            launched = True
    return {"ok": True, "mode": "staged", "installed_to": str(dest),
            "backup": "", "launched": launched,
            "message": plan["note"]}


def make_workdir():
    return Path(tempfile.mkdtemp(prefix="jsj-update-"))


def cleanup_workdir(path):
    shutil.rmtree(str(path), ignore_errors=True)
