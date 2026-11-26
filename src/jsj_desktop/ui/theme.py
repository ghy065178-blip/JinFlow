# -*- coding: utf-8 -*-
"""跨平台主题令牌与 tkinter/ttk 样式。

深色主题保留 1.2.0 的语义颜色，浅色主题只调整背景、表面、边框和文字层级。
玻璃质感使用标准库可控的分层表面、内侧高光和轻薄描边实现，不改变窗口透明度。
"""
import subprocess
import sys
import tkinter as tk
from tkinter import ttk


THEME_MODES = ("dark", "light", "system")

_DARK_PALETTE = {
    "bg": "#0d1117",
    "surface": "#161b22",
    "surface2": "#1c2128",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#8b949e",
    "dim": "#6e7681",
    "teal": "#2dd4bf",
    "blue": "#58a6ff",
    "green": "#3fb950",
    "amber": "#d29922",
    "red": "#f85149",
    "purple": "#bc8cff",
    "log_bg": "#080b10",
    "log_text": "#c9d1d9",
    "log_ts": "#56606d",
    "glass": "#1a222d",
    "glass_highlight": "#2a3542",
    "highlight": "#405064",
    "shadow": "#080b10",
    "input": "#101620",
    "notice": "#1b2430",
    "warnbox": "#2a2115",
}

_LIGHT_PALETTE = {
    "bg": "#f3f6fa",
    "surface": "#ffffff",
    "surface2": "#e8edf4",
    "border": "#d5dde8",
    "text": "#1d2733",
    "muted": "#617085",
    "dim": "#8290a3",
    "teal": "#2dd4bf",
    "blue": "#2f6fce",
    "green": "#1b8e5a",
    "amber": "#a06a00",
    "red": "#c0392b",
    "purple": "#7650b5",
    "log_bg": "#17202b",
    "log_text": "#e4edf8",
    "log_ts": "#9caabd",
    "glass": "#f8fbff",
    "glass_highlight": "#ffffff",
    "highlight": "#dbe5f1",
    "shadow": "#b6c1cf",
    "input": "#ffffff",
    "notice": "#e8f1f2",
    "warnbox": "#fff3df",
}

_PALETTES = {"dark": _DARK_PALETTE, "light": _LIGHT_PALETTE}
PALETTE = dict(_DARK_PALETTE)

LEVEL_COLORS = {
    "ok": PALETTE["green"], "error": PALETTE["red"],
    "warn": PALETTE["amber"], "rush": PALETTE["blue"],
    "wait": "#7d8590", "reply": PALETTE["purple"],
    "prompt": "#9aa7b4", "info": PALETTE["log_text"],
}


def normalize_mode(value):
    value = str(value or "").strip().lower()
    return value if value in THEME_MODES else "system"


def resolve_mode(mode, system_mode="light"):
    mode = normalize_mode(mode)
    return normalize_mode(system_mode) if mode == "system" else mode


def palette_for(mode):
    return dict(_PALETTES[resolve_mode(mode, system_mode="light")])


def detect_system_mode():
    """读取系统外观，失败时返回浅色，确保启动过程不被主题探测阻断。"""
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=0.5, check=False)
            return "dark" if result.stdout.strip().lower() == "dark" else "light"
        if sys.platform == "win32":
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "dark" if int(value) == 0 else "light"
    except Exception:
        pass
    return "light"


def _set_active_palette(resolved):
    PALETTE.clear()
    PALETTE.update(_PALETTES[resolved])
    LEVEL_COLORS.clear()
    LEVEL_COLORS.update({
        "ok": PALETTE["green"], "error": PALETTE["red"],
        "warn": PALETTE["amber"], "rush": PALETTE["blue"],
        "wait": "#7d8590", "reply": PALETTE["purple"],
        "prompt": "#9aa7b4", "info": PALETTE["log_text"],
    })


def refresh_tree(root, old_palette, new_palette):
    """按旧令牌值刷新已创建的直接 tkinter 控件，不重建布局。"""
    replacements = {
        old_palette[key]: new_palette[key]
        for key in old_palette.keys() & new_palette.keys()
        if old_palette[key] != new_palette[key]
    }
    options = ("background", "foreground", "insertbackground",
               "highlightbackground", "highlightcolor", "selectbackground",
               "selectforeground", "troughcolor", "arrowcolor")

    def visit(widget):
        for option in options:
            try:
                value = widget.cget(option)
                if value in replacements:
                    widget.configure(**{option: replacements[value]})
            except (tk.TclError, TypeError):
                pass
        for child in widget.winfo_children():
            visit(child)

    visit(root)


def font_family():
    """与原 HTML 的 font-family 顺序一致。"""
    if sys.platform == "win32":
        return "Microsoft YaHei"
    if sys.platform == "darwin":
        return "PingFang SC"
    return "Segoe UI"


def apply(root, mode="system", system_mode=None):
    """应用主题并返回实际使用的浅色或深色模式。"""
    resolved = resolve_mode(mode, system_mode or detect_system_mode())
    _set_active_palette(resolved)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    p = PALETTE
    family = font_family()
    root.configure(background=p["bg"])
    style.configure(".", background=p["bg"], foreground=p["text"],
                    font=(family, 10), fieldbackground=p["input"],
                    bordercolor=p["border"], insertcolor=p["text"],
                    troughcolor=p["surface2"], focuscolor=p["teal"])
    style.configure("TFrame", background=p["bg"])
    style.configure("Card.TFrame", background=p["glass"], relief="solid",
                    borderwidth=1, bordercolor=p["border"],
                    lightcolor=p["glass_highlight"], darkcolor=p["shadow"])
    style.configure("CardHead.TFrame", background=p["surface2"],
                    lightcolor=p["glass_highlight"], darkcolor=p["shadow"])
    style.configure("Pill.TFrame", background=p["glass"], relief="solid",
                    borderwidth=1, bordercolor=p["border"],
                    lightcolor=p["glass_highlight"], darkcolor=p["shadow"])

    style.configure("TLabel", background=p["bg"], foreground=p["text"],
                    font=(family, 10))
    style.configure("Card.TLabel", background=p["glass"],
                    foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"],
                    font=(family, 9))
    style.configure("CardMuted.TLabel", background=p["glass"],
                    foreground=p["muted"], font=(family, 9))
    style.configure("Key.TLabel", background=p["bg"], foreground=p["dim"],
                    font=(family, 9))
    style.configure("CardKey.TLabel", background=p["bg"], foreground=p["dim"],
                    font=(family, 9))
    style.configure("Value.TLabel", background=p["glass"],
                    foreground=p["text"], font=(family, 16, "bold"))
    style.configure("Title.TLabel", background=p["bg"], foreground=p["text"],
                    font=(family, 14, "bold"))
    style.configure("PanelTitle.TLabel", background=p["surface2"],
                    foreground=p["text"], font=(family, 11, "bold"))
    style.configure("Hint.TLabel", background=p["bg"], foreground=p["dim"],
                    font=(family, 9))
    style.configure("CardHint.TLabel", background=p["glass"],
                    foreground=p["dim"], font=(family, 9))
    style.configure("Warn.TLabel", background=p["glass"],
                    foreground="#e3c07b", font=(family, 9))
    style.configure("Notice.TLabel", background=p["notice"],
                    foreground="#a9bccd", font=(family, 9))
    style.configure("Warnbox.TLabel", background=p["warnbox"],
                    foreground="#e3c07b", font=(family, 9))
    style.configure("Teal.TLabel", background=p["bg"], foreground=p["teal"],
                    font=(family, 10, "bold"))
    style.configure("Head.TLabel", background=p["surface2"],
                    foreground=p["muted"], font=(family, 10, "bold"))

    style.configure("TLabelframe", background=p["glass"],
                    bordercolor=p["border"], relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=p["glass"],
                    foreground=p["teal"], font=(family, 10, "bold"))

    style.configure("TButton", background=p["surface2"], foreground=p["text"],
                    bordercolor=p["border"], font=(family, 10), padding=(9, 5))
    style.map("TButton", background=[("active", p["highlight"])],
              foreground=[("active", p["teal"])])
    style.configure("Primary.TButton", background=p["teal"],
                    bordercolor=p["teal"], foreground="#042f2e",
                    font=(family, 10, "bold"))
    style.map("Primary.TButton", background=[("active", "#5eead4")],
              foreground=[("active", "#042f2e")])
    style.configure("Danger.TButton", background=p["surface2"],
                    foreground=p["red"], bordercolor="#6e3030")
    style.configure("Sm.TButton", background=p["surface2"],
                    foreground=p["text"], bordercolor=p["border"],
                    font=(family, 9), padding=(6, 3))
    style.configure("SmPrimary.TButton", background=p["teal"],
                    foreground="#042f2e", bordercolor=p["teal"],
                    font=(family, 9, "bold"), padding=(6, 3))
    style.configure("SmDanger.TButton", background=p["surface2"],
                    foreground=p["red"], bordercolor="#6e3030",
                    font=(family, 9), padding=(6, 3))
    style.configure("Tab.TButton", background=p["bg"], foreground=p["muted"],
                    bordercolor=p["border"], font=(family, 10), padding=(8, 3))
    style.configure("TabActive.TButton", background="#102a2a",
                    foreground=p["teal"], bordercolor=p["teal"],
                    font=(family, 10, "bold"), padding=(8, 3))
    style.configure("Refresh.TButton", background=p["bg"],
                    foreground=p["dim"], bordercolor=p["bg"],
                    font=(family, 9), padding=(2, 1), width=2)
    style.map("Refresh.TButton", foreground=[("active", p["teal"])])

    style.configure("TCheckbutton", background=p["bg"], foreground=p["text"],
                    font=(family, 10), indicatorcolor=p["bg"],
                    indicatorbackground=p["surface2"])
    style.configure("Card.TCheckbutton", background=p["glass"],
                    foreground=p["text"], font=(family, 10))
    style.configure("Head.TCheckbutton", background=p["surface2"],
                    foreground=p["text"], font=(family, 10))
    style.configure("Theme.TRadiobutton", background=p["glass"],
                    foreground=p["text"], font=(family, 10),
                    indicatorcolor=p["surface2"],
                    indicatorbackground=p["surface2"])

    style.configure("TEntry", fieldbackground=p["input"], foreground=p["text"],
                    bordercolor=p["border"], padding=4, insertcolor=p["text"])
    style.configure("TCombobox", fieldbackground=p["input"],
                    foreground=p["text"], bordercolor=p["border"],
                    arrowcolor=p["muted"], padding=4)
    style.configure("Treeview", background=p["input"], fieldbackground=p["input"],
                    foreground=p["text"], bordercolor=p["border"],
                    font=(family, 10))
    style.configure("Treeview.Heading", background=p["surface2"],
                    foreground=p["muted"], font=(family, 9, "bold"))
    style.configure("TScrollbar", background=p["surface2"],
                    troughcolor=p["bg"], bordercolor=p["border"],
                    arrowcolor=p["muted"])
    return resolved
