# -*- coding: utf-8 -*-
"""跨平台用户数据目录解析（仅标准库，无第三方 appdirs 依赖）。

Windows : %APPDATA%\\JinshujuDesktop
macOS   : ~/Library/Application Support/JinshujuDesktop
Linux   : $XDG_DATA_HOME/jinshuju-desktop 或 ~/.local/share/jinshuju-desktop
可用环境变量 JSJ_DATA_DIR 覆盖（便于测试、便携版与 CI）。
"""
import os
import sys
from pathlib import Path

from .. import __app_id__


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def resource_path(relative):
    """打包后读取随包静态资源；源码运行时读取仓库内路径。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return str(Path(base) / relative)
    return str(Path(__file__).resolve().parents[3] / relative)


def data_dir():
    override = os.environ.get("JSJ_DATA_DIR", "").strip()
    if override:
        root = Path(override).expanduser()
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        root = Path(base) / __app_id__
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / __app_id__
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        root = Path(base) / "jinshuju-desktop"
    root.mkdir(parents=True, exist_ok=True)
    return root


def profiles_path():
    return data_dir() / "profiles.json"


def profiles_backup_path():
    return data_dir() / "profiles.backup.json"


def settings_path():
    return data_dir() / "settings.json"


def tasks_root():
    p = data_dir() / "tasks"
    p.mkdir(parents=True, exist_ok=True)
    return p


def task_dir(task_id):
    p = tasks_root() / str(task_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def task_config_path(task_id):
    return task_dir(task_id) / "报名信息.json"


def task_config_backup_path(task_id):
    return task_dir(task_id) / "报名信息.backup.json"


def logs_dir():
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def platform_label():
    """返回 (系统, 架构) 标签，用于发布包命名与「关于」页。"""
    import platform
    machine = (platform.machine() or "").lower()
    if sys.platform == "win32":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return "windows", arch
    if sys.platform == "darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return "macos", arch
    return "linux", machine or "unknown"
