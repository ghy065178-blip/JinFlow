# -*- coding: utf-8 -*-
"""四平台安装 / 切换与回滚（仅标准库）。

原则：
  1. 先下载到临时目录、校验 SHA256、验证包内 APP_VERSION.txt 与 BUILD_INFO.txt
     的「版本 + 平台」再动安装位置；任何一步失败都保持现有版本原样。
  2. macOS 用「旧 .app 改名备份 → 新 .app 就位 → 重做 ad-hoc 签名 → 去隔离
     属性 → open -n 重启」；替换失败自动恢复备份。
  3. Windows 先暂存新目录，独立 PowerShell 进程在旧程序退出后替换与重启。
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
import time
import zipfile
from pathlib import Path

from .. import __app_name__, __version__
from ..data import paths as data_paths
from . import manifest as mf
from .errors import InstallError
from .version import compare_versions, normalize_version

APP = "JinshujuDesktop"
VERSION_MARKER = "APP_VERSION.txt"
VERSION_RE = re.compile(
    r"(?:JinFlow|JinshujuDesktop)?\s*v?(\d+(?:\.\d+){1,3})")


def platform_target(label=None):
    return mf.platform_target(label)


def _read_version_marker(root):
    root = Path(root)
    for rel in (VERSION_MARKER, "Contents/" + VERSION_MARKER,
                "Contents/Resources/" + VERSION_MARKER, "BUILD_INFO.txt"):
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
        if app.suffix.lower() == ".app" and exe.parent.name == "MacOS":
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
    candidates = []
    if sys.platform == "darwin":
        roots = (Path("/Applications"), home / "Applications",
                 home / "Downloads", home / "Desktop")
        candidates = [root / (name + ".app") for root in roots
                      for name in (__app_name__, APP)]
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


def extract_dmg(archive, dest, runner=None):
    """挂载 DMG、复制其中的 .app 并卸载，返回可校验的本地目录。"""
    if sys.platform != "darwin":
        raise InstallError("DMG 更新包只能在 macOS 上安装。",
                           hint="请在 macOS 设备上选择 DMG，或下载 ZIP 包。")
    runner = runner or subprocess.run
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    mount = Path(tempfile.mkdtemp(prefix="jinflow-dmg-mount-"))
    attached = False
    try:
        runner(["hdiutil", "attach", "-nobrowse", "-readonly",
                "-mountpoint", str(mount), str(archive)], check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        attached = True
        apps = sorted(path for path in mount.glob("*.app") if path.is_dir())
        if not apps:
            raise InstallError("DMG 中未找到可安装的 JinFlow.app。",
                               hint="请重新下载完整的 DMG 安装包。")
        shutil.copytree(apps[0], dest / apps[0].name, symlinks=True)
        return dest
    except InstallError:
        raise
    except Exception as e:
        raise InstallError("挂载或读取 DMG 失败：%s" % e,
                           hint="请确认 macOS 磁盘映像可正常打开后重试。", cause=e)
    finally:
        if attached:
            try:
                runner(["hdiutil", "detach", "-force", str(mount)],
                       check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
            except Exception:
                pass
        shutil.rmtree(mount, ignore_errors=True)


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
    marker_roots = [payload]
    if system == "macos":
        marker_roots += [payload / "Contents",
                         payload / "Contents" / "Resources"]
    marker_roots.append(root)
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
        if (not updates_root.resolve().is_relative_to(old.resolve()) and
                old.parent.exists() and os.access(str(old.parent), os.W_OK)):
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
        data_inside_app = updates_root.resolve().is_relative_to(old.resolve())
        if not data_inside_app and parent.exists() and os.access(str(parent), os.W_OK):
            return {"ok": True, "mode": "windows-dir", "can_auto": True,
                    "target_path": str(old),
                    "backup_path": str(_unique_path(
                        str(old) + ".backup-" + (ctx["current_version"] or "old"))),
                    "updates_root": str(updates_root),
                    "pid": ctx.get("pid") or os.getpid(),
                    "payload_dir": package["payload_dir"],
                    "launch_path": str(old / (APP + ".exe")),
                    "version": version,
                    "note": "程序退出后由独立脚本完成替换并自动重启。"}
        mode = "staged"

    leaf = __app_name__ + ".app" if ctx["system"] == "macos" else APP
    dest = updates_root / version / ctx["target"] / leaf
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


WINDOWS_SCRIPT = r"""param(
    [string]$Target, [string]$Staged, [string]$Backup,
    [int]$ParentId, [int]$Relaunch
)
$ErrorActionPreference = 'Stop'
$Target = $env:JSJ_UPDATE_TARGET
$Staged = $env:JSJ_UPDATE_STAGED
$Backup = $env:JSJ_UPDATE_BACKUP
$log = $env:JSJ_UPDATE_LOG
if (-not $log) { $log = Join-Path $PSScriptRoot 'install.log' }
$movedOld = $false
$movedNew = $false
$parentExited = $false

function Write-Log([string]$Message) {
    try {
        [IO.File]::AppendAllText($log, "$(Get-Date -Format s) $Message`r`n", [Text.Encoding]::UTF8)
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
    }
}

function Open-App {
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $exe
    $start.WorkingDirectory = $Target
    $start.UseShellExecute = $false
    if ($env:JSJ_UPDATE_FAILURE_LOG) {
        $start.EnvironmentVariables['JSJ_UPDATE_FAILURE_LOG'] =
            $env:JSJ_UPDATE_FAILURE_LOG
    } else {
        $start.EnvironmentVariables['JSJ_UPDATE_RESULT_LOG'] = $log
    }
    [Diagnostics.Process]::Start($start)
}

try {
    $ParentId = [int]$env:JSJ_UPDATE_PARENT_ID
    $Relaunch = [int]$env:JSJ_UPDATE_RELAUNCH
    $exe = Join-Path $Target 'JinshujuDesktop.exe'
    $parent = [Diagnostics.Process]::GetProcessById($ParentId)
    $null = $parent.Handle
    if (-not [IO.File]::Exists($exe) -or
        -not [IO.File]::Exists((Join-Path $Staged 'JinshujuDesktop.exe'))) {
        throw 'The old or staged executable is missing.'
    }
    Write-Log 'Waiting for the running application to close.'
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'ready'), '')
    if (-not $parent.WaitForExit(300000)) { throw 'The application did not close in time.' }
    $parentExited = $true
    $parent.Dispose()

    [IO.Directory]::Move($Target, $Backup)
    $movedOld = $true
    [IO.Directory]::Move($Staged, $Target)
    $movedNew = $true
    if ($Relaunch -eq 1) {
        $app = Open-App
        if ($app.WaitForExit(1500) -and $app.ExitCode -ne 0) {
            throw "The new application exited with error $($app.ExitCode)."
        }
        $app.Dispose()
    }
    Write-Log "Installed. Backup: $Backup"
    exit 0
} catch {
    Write-Log "Installation failed: $($_.Exception.Message)"
    try {
        if ($movedNew) { [IO.Directory]::Move($Target, $Staged) }
        if ($movedOld) {
            [IO.Directory]::Move($Backup, $Target)
            Write-Log 'Restored the original installation.'
        }
        if ($parentExited -and $Relaunch -eq 1) {
            $env:JSJ_UPDATE_FAILURE_LOG = $log
            $app = Open-App
            $null = $app.WaitForExit(5000)
            $app.Dispose()
        }
    } catch {
        Write-Log "Could not restore or reopen the old application: $($_.Exception.Message). Backup: $Backup"
    }
    exit 1
}
"""


def _windows_popen(cmd, runner, **kwargs):
    env_overrides = kwargs.pop("env_overrides", None) or {}
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("_PYI_") and key != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    env.update(env_overrides)
    # PyInstaller's DLL search directory otherwise carries over to PowerShell.
    bundle = getattr(sys, "_MEIPASS", None)
    if sys.platform == "win32" and bundle:
        import ctypes
        set_dll_directory = ctypes.windll.kernel32.SetDllDirectoryW
        if not set_dll_directory(None):
            raise ctypes.WinError()
        try:
            return _popen(cmd, runner, env=env, **kwargs)
        finally:
            set_dll_directory(ctypes.c_wchar_p(bundle))
    return _popen(cmd, runner, env=env, **kwargs)


def _apply_windows_install(plan, relaunch, runner, pid):
    old = Path(plan["target_path"])
    updates = Path(plan["updates_root"])
    staged = None
    try:
        updates.mkdir(parents=True, exist_ok=True)
        # Keep the script itself in the system temp directory.  Windows
        # PowerShell parses script paths before the script can read its
        # environment, so an install path containing ``&`` or a quote must
        # not also be used as the script path.
        handoff = Path(tempfile.mkdtemp(prefix="jsj-upgrade-%s-" %
                                       plan["version"]))
        staged = Path(tempfile.mkdtemp(prefix=old.name + ".new-", dir=str(old.parent)))
        shutil.copytree(plan["payload_dir"], staged, symlinks=True, dirs_exist_ok=True)
        script = handoff / "install.ps1"
        script.write_text(WINDOWS_SCRIPT, encoding="utf-8-sig")
    except OSError as e:
        if staged is not None:
            shutil.rmtree(staged, ignore_errors=True)
        raise InstallError("暂存新版本失败：%s" % e,
                           hint="请检查磁盘空间和安装目录的写入权限。", cause=e)

    log = handoff / "install.log"
    startup_log = handoff / "startup.log"
    ready = handoff / "ready"
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe")
    cmd = [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
           "-ExecutionPolicy", "Bypass", "-File", str(script)]
    env_overrides = {
        "JSJ_UPDATE_TARGET": str(old),
        "JSJ_UPDATE_STAGED": str(staged),
        "JSJ_UPDATE_BACKUP": plan["backup_path"],
        "JSJ_UPDATE_LOG": str(log),
        "JSJ_UPDATE_PARENT_ID": str(pid),
        "JSJ_UPDATE_RELAUNCH": "1" if relaunch else "0",
    }
    try:
        with startup_log.open("wb") as output:
            worker = _windows_popen(cmd, runner, cwd=str(handoff),
                                    creationflags=0x08000000 | 0x00000200,
                                    stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=subprocess.STDOUT, close_fds=True,
                                    env_overrides=env_overrides)
            # Windows ARM runners and first-run PowerShell startup can take
            # longer than the x64 path.  Keep the handoff alive long enough
            # to observe its ready marker before reporting a launch failure.
            deadline = time.monotonic() + 60
            while not ready.is_file():
                if worker.poll() is not None:
                    output.flush()
                    try:
                        details = startup_log.read_text(
                            encoding="utf-8-sig").strip()
                    except OSError:
                        details = ""
                    try:
                        install_details = log.read_text(
                            encoding="utf-8-sig").strip()
                    except OSError:
                        install_details = ""
                    if install_details:
                        details = "\n".join(
                            part for part in (details, install_details) if part)
                    message = (" 日志：" + details[-2000:]) if details else ""
                    raise RuntimeError(
                        "PowerShell 进程已退出（代码 %s）。%s" %
                        (worker.returncode, message))
                if time.monotonic() >= deadline:
                    worker.kill()
                    worker.wait()
                    raise RuntimeError("等待 PowerShell 就绪超时。")
                time.sleep(0.05)
    except Exception as e:
        shutil.rmtree(staged, ignore_errors=True)
        raise InstallError("无法启动 Windows 更新程序：%s" % e,
                           hint="当前版本仍可使用。日志：%s" %
                                (log if log.is_file() else startup_log), cause=e)
    return {"ok": True, "mode": "windows-dir", "pending": True,
            "installed_to": str(old), "backup": plan["backup_path"],
            "staged": str(staged), "script": str(script), "log": str(log),
            "launched": bool(relaunch),
            "message": "新版已暂存，程序退出后将完成替换%s。" %
                       ("并重启" if relaunch else "")}


def apply_install(plan, relaunch=True, runner=None, pid=None):
    """执行安装计划；失败时回滚并抛 InstallError。runner 可注入便于测试。"""
    pid = pid or plan.get("pid") or os.getpid()
    mode = plan["mode"]

    if mode == "macos-app":
        runner = runner or subprocess.run
        old = Path(plan["target_path"])
        backup = Path(plan["backup_path"])
        new_app = Path(plan["new_app"])
        moved_old = False
        replaced = False
        try:
            if old.exists() or old.is_symlink():
                shutil.move(str(old), str(backup))
                moved_old = True
            shutil.move(str(new_app), str(old))
            replaced = True
            if not (old / "Contents" / "MacOS" / APP).is_file():
                raise InstallError("新版本包结构不完整。")
            _best_effort(["codesign", "--force", "--deep", "--sign", "-", str(old)],
                         runner)
            _best_effort(["xattr", "-dr", "com.apple.quarantine", str(old)], runner)
            if relaunch:
                runner(["open", "-n", str(old)], check=True)
        except Exception as e:
            try:
                if replaced or (moved_old and old.exists()):
                    shutil.rmtree(old)
                if moved_old:
                    shutil.move(str(backup), str(old))
            except OSError as restore_error:
                raise InstallError("恢复原版本失败：%s" % restore_error,
                                   hint="原程序备份位于 %s" % backup,
                                   cause=restore_error) from e
            raise InstallError("替换应用失败：%s" % e,
                               hint="现有版本已保留，请重试或手动拖入「应用程序」。",
                               cause=e) from e
        return {"ok": True, "mode": mode, "installed_to": str(old),
                "backup": str(backup) if moved_old else "",
                "launched": bool(relaunch),
                "message": "已安装并切换到 %s（原版本已备份）。" % plan["version"]}

    if mode == "windows-dir":
        return _apply_windows_install(plan, relaunch, runner or subprocess.Popen, pid)

    # 源码运行 / 无写入权限 / 手动模式
    dest = Path(plan["target_path"])
    if dest.exists():
        dest = _unique_path(dest.parent) / dest.name
    try:
        dest.mkdir(parents=True)
    except Exception as e:
        raise InstallError("切换到新版本失败：%s" % e,
                           hint="现有版本与报名数据未改动，请检查写入权限。",
                           cause=e)
    launched = False
    try:
        shutil.copytree(plan["payload_dir"], dest, symlinks=True, dirs_exist_ok=True)
        if relaunch and plan.get("can_auto"):
            rel_launch = Path(plan["launch_path"]).relative_to(plan["target_path"])
            launch = dest / rel_launch
            if sys.platform == "win32":
                _windows_popen([str(launch)], runner or subprocess.Popen,
                               cwd=str(launch.parent))
            else:
                _popen([str(launch)], runner or subprocess.Popen)
            launched = True
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        if isinstance(e, InstallError):
            raise
        raise InstallError("切换到新版本失败：%s" % e,
                           hint="现有版本与报名数据仍可使用。", cause=e) from e
    return {"ok": True, "mode": "staged", "installed_to": str(dest),
            "backup": "", "launched": launched,
            "message": plan["note"]}


def make_workdir():
    return Path(tempfile.mkdtemp(prefix="jsj-update-"))


def cleanup_workdir(path):
    shutil.rmtree(str(path), ignore_errors=True)
