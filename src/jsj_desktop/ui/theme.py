# -*- coding: utf-8 -*-
"""跨平台主题令牌与 tkinter/ttk 样式。

窗体使用极光色分层表面、圆角和顶部高光，终端保留独立的深色底。
"""
import base64
import math
import struct
import subprocess
import sys
import tkinter as tk
import zlib
from tkinter import ttk


THEME_MODES = ("dark", "light", "system")

_DARK_PALETTE = {
    "bg": "#080c19",
    "ambient": "#192839",
    "surface": "#0e1728",
    "surface2": "#202844",
    "border": "#3d4968",
    "control_border": "#515d7e",
    "text": "#f3f4fa",
    "muted": "#b7c1d5",
    "dim": "#a4b1ca",
    "teal": "#2dd4bf",
    "teal_text": "#7ae4d0",
    "action": "#67e2db",
    "on_action": "#082f30",
    "selected": "#233c58",
    "blue": "#79baff",
    "green": "#65e0af",
    "amber": "#e7b358",
    "red": "#ff827d",
    "purple": "#c9a0ff",
    "log_bg": "#090f1d",
    "log_text": "#cdd7e4",
    "log_ts": "#94a4bb",
    "glass": "#1a2339",
    "glass_highlight": "#8296b1",
    "highlight": "#303c5a",
    "shadow": "#060a15",
    "input": "#10182b",
    "notice": "#1c3441",
    "warnbox": "#33281a",
}

_LIGHT_PALETTE = {
    "bg": "#e7edf8",
    "ambient": "#e3ebf7",
    "surface": "#f1f6fb",
    "surface2": "#e9effa",
    "border": "#bbcae0",
    "control_border": "#a1b0c8",
    "text": "#162535",
    "muted": "#475970",
    "dim": "#566981",
    "teal": "#2dd4bf",
    "teal_text": "#006558",
    "action": "#54d6c0",
    "on_action": "#082f30",
    "selected": "#d4ede9",
    "blue": "#255ca4",
    "green": "#11694a",
    "amber": "#865300",
    "red": "#9f342c",
    "purple": "#6644a0",
    "log_bg": "#101a28",
    "log_text": "#e4edf8",
    "log_ts": "#9faec3",
    "glass": "#f8fbfe",
    "glass_highlight": "#ffffff",
    "highlight": "#dbe6f8",
    "shadow": "#c1cede",
    "input": "#ffffff",
    "notice": "#e5f1f4",
    "warnbox": "#fff2dc",
}

_PALETTES = {"dark": _DARK_PALETTE, "light": _LIGHT_PALETTE}
for _palette in _PALETTES.values():
    _palette.update(aurora_cyan="#00f2fe", aurora_purple="#a855f7",
                    aurora_emerald="#34d399")
PALETTE = dict(_DARK_PALETTE)

LEVEL_COLORS = {
    "ok": "#61d59d", "error": "#ff837c", "warn": "#efc56a",
    "rush": "#81aaff", "wait": "#9caabd", "reply": "#cfadfb",
    "prompt": "#bac9d8", "info": PALETTE["log_text"],
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
    LEVEL_COLORS["info"] = PALETTE["log_text"]


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


def _color_mix(start, end, amount):
    return tuple(round(a + (b - a) * amount) for a, b in zip(start, end))


def _tint(start, end, amount):
    color = _color_mix(bytes.fromhex(start[1:]), bytes.fromhex(end[1:]), amount)
    return "#%02x%02x%02x" % color


def _glass_tile(radius, fill, edge, glint):
    """小型 RGBA 圆角底图，ttk 拉伸中间像素，保留半透明边缘。"""
    # ttk 实际会重复中间区域。使用宽一些的中心，避免 Aqua 按像素绘制。
    center = 32
    size = radius * 2 + center
    face, border, shine = (tuple(bytes.fromhex(color[1:])) for color in
                           (fill, edge, glint))
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG 行过滤器
        sheen = max(0, 1 - y / radius)
        rim = _color_mix(border, shine, 0.86 if y <= 1 else sheen * 0.36)
        body = _color_mix(face, shine, sheen * 0.18)
        dy = max(radius - y, 0, y - (radius + center - 1))
        for x in range(size):
            dx = max(radius - x, 0, x - (radius + center - 1))
            distance = math.hypot(dx, dy)
            # 角落的 1 像素透明过渡避免出现锯齿。
            alpha = round(255 * max(0, min(1, radius + 0.5 - distance)))
            fill_amount = max(0, min(1, radius - 0.5 - distance))
            pixel = _color_mix(rim, body, fill_amount)
            rows.extend((*pixel, alpha))

    def chunk(name, data):
        return (struct.pack(">I", len(data)) + name + data +
                struct.pack(">I", zlib.crc32(name + data)))

    return base64.b64encode(b"\x89PNG\r\n\x1a\n" +
                            chunk(b"IHDR", struct.pack(">IIBBBBB", size, size,
                                                       8, 6, 0, 0, 0)) +
                            chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _apply_surfaces(root, style):
    p = PALETTE
    if not hasattr(root, "_base_button_layout"):
        root._base_button_layout = style.layout("TButton")
    # 每个元素的图片对象保留到窗口销毁，切换主题只替换像素。
    if not hasattr(root, "_surface_images"):
        root._surface_images = {}

    def element(name, radius, normal):
        if name not in root._surface_images:
            image = tk.PhotoImage(master=root)
            root._surface_images[name] = image
            style.element_create(name, "image", image,
                                 width=2 * radius, height=2 * radius, border=radius, padding=1,
                                 sticky="nsew")
        root._surface_images[name].configure(data=_glass_tile(radius, *normal), format="png")

    for role, radius, fill, accent in (
            ("Header", 16, p["ambient"], p["aurora_cyan"]),
            ("Glass", 14, p["glass"], p["aurora_purple"]),
            ("Pill", 10, p["glass"], p["aurora_emerald"]),
            ("Inset", 8, p["surface"], p["aurora_cyan"])):
        name = role + ".surface"
        element(name, radius, (fill, _tint(p["border"], accent, 0.13),
                               _tint(p["glass_highlight"], accent, 0.22)))
        style.layout(role + ".TFrame", [(name, {"sticky": "nsew"})])

    element("Brand.face", 10, (p["action"], "#1e759d", "#8ff1df"))
    style.layout("Brand.TLabel", [
        ("Brand.face", {"sticky": "nsew", "children": [
            ("Label.padding", {"sticky": "nsew", "children": [
                ("Label.label", {"sticky": "nsew"})]})]})])

    for name in ("TButton", "Primary.TButton", "SmPrimary.TButton",
                 "TabActive.TButton", "Update.Primary.TButton",
                 "Segment.TButton", "SegmentActive.TButton"):
        style.layout(name, root._base_button_layout)


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
    _apply_surfaces(root, style)
    style.configure(".", background=p["bg"], foreground=p["text"],
                    font=(family, 10), fieldbackground=p["input"],
                    bordercolor=p["border"], insertcolor=p["text"],
                    troughcolor=p["surface2"], focuscolor=p["teal_text"],
                    selectbackground=p["selected"], selectforeground=p["text"],
                    lightcolor=p["control_border"], darkcolor=p["control_border"])
    style.configure("TFrame", background=p["bg"])
    style.configure("HeaderFill.TFrame", background=p["ambient"])
    style.configure("Card.TFrame", background=p["glass"])
    style.configure("CardHead.TFrame", background=p["surface2"])
    style.configure("Inset.TLabel", background=p["surface"], foreground=p["text"],
                    font=(family, 9))
    style.configure("InsetKey.TLabel", background=p["surface"], foreground=p["dim"],
                    font=(family, 9))

    style.configure("TLabel", background=p["bg"], foreground=p["text"],
                    font=(family, 10))
    style.configure("Card.TLabel", background=p["glass"],
                    foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"],
                    font=(family, 9))
    style.configure("Brand.TLabel", foreground=p["on_action"],
                    font=(family, 13, "bold"), anchor="center", padding=(9, 3))
    style.configure("Connected.TLabel", background=p["glass"],
                    foreground=p["green"], font=(family, 9))
    style.configure("Clock.TLabel", background=p["glass"], foreground=p["text"],
                    font=("TkFixedFont", 10, "bold"), anchor="center")
    style.configure("CardMuted.TLabel", background=p["glass"],
                    foreground=p["muted"], font=(family, 9))
    style.configure("Key.TLabel", background=p["glass"], foreground=p["dim"],
                    font=(family, 9))
    style.configure("CardKey.TLabel", background=p["glass"], foreground=p["dim"],
                    font=(family, 9))
    style.configure("Value.TLabel", background=p["glass"],
                    foreground=p["text"], font=(family, 16, "bold"))
    style.configure("Title.TLabel", background=p["bg"], foreground=p["text"],
                    font=(family, 14, "bold"))
    style.configure("Header.TLabel", background=p["ambient"], foreground=p["text"])
    style.configure("HeaderTitle.TLabel", background=p["ambient"], foreground=p["text"],
                    font=(family, 16, "bold"))
    style.configure("HeaderMuted.TLabel", background=p["ambient"], foreground=p["muted"],
                    font=(family, 9))
    style.configure("PanelTitle.TLabel", background=p["surface2"],
                    foreground=p["text"], font=(family, 11, "bold"))
    style.configure("PanelTag.TLabel", background=p["surface2"],
                    foreground=p["dim"], font=(family, 9))
    style.configure("PanelWarn.TLabel", background=p["surface2"],
                    foreground=p["amber"], font=(family, 9))
    style.configure("Hint.TLabel", background=p["bg"], foreground=p["dim"],
                    font=(family, 9))
    style.configure("CardHint.TLabel", background=p["glass"],
                    foreground=p["dim"], font=(family, 9))
    style.configure("Warn.TLabel", background=p["glass"],
                    foreground=p["amber"], font=(family, 9))
    style.configure("Notice.TLabel", background=p["notice"],
                    foreground=p["muted"], font=(family, 9))
    style.configure("Warnbox.TLabel", background=p["warnbox"],
                    foreground=p["amber"], font=(family, 9))
    style.configure("Teal.TLabel", background=p["glass"], foreground=p["teal_text"],
                    font=(family, 10, "bold"))
    style.configure("Head.TLabel", background=p["surface2"],
                    foreground=p["muted"], font=(family, 10, "bold"))

    style.configure("TLabelframe", background=p["glass"],
                    bordercolor=p["border"], relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=p["glass"],
                    foreground=p["teal_text"], font=(family, 10, "bold"))

    style.configure("TButton", background=p["surface2"], foreground=p["text"],
                    bordercolor=p["border"], font=(family, 10), padding=(10, 5), width=0)
    style.map("TButton", background=[("disabled", p["glass"]), ("active", p["highlight"])],
              foreground=[("disabled", p["dim"])])
    style.configure("Primary.TButton", background=p["action"],
                    foreground=p["on_action"], focuscolor=p["on_action"],
                    font=(family, 10, "bold"))
    active_action = _tint(p["action"], "#ffffff", 0.19)
    style.map("Primary.TButton", background=[("disabled", p["glass"]), ("active", active_action)])
    style.configure("Update.Primary.TButton", background=p["action"],
                    foreground=p["on_action"], focuscolor=p["on_action"],
                    font=(family, 10, "bold"))
    style.map("Update.Primary.TButton", background=[("disabled", p["glass"]),
                                                      ("active", active_action)])
    style.configure("Danger.TButton", background=p["surface2"],
                    foreground=p["red"], bordercolor="#6e3030")
    style.configure("Sm.TButton", background=p["surface2"],
                    foreground=p["text"], bordercolor=p["border"],
                    font=(family, 9), padding=(6, 3))
    style.configure("SmPrimary.TButton", background=p["action"],
                    foreground=p["on_action"], focuscolor=p["on_action"],
                    font=(family, 9, "bold"), padding=(6, 3))
    style.configure("SmDanger.TButton", background=p["surface2"],
                    foreground=p["red"], bordercolor="#6e3030",
                    font=(family, 9), padding=(6, 3))
    style.configure("Tab.TButton", background=p["bg"], foreground=p["muted"],
                    bordercolor=p["border"], font=(family, 10), padding=(8, 3))
    style.configure("TabActive.TButton", background=p["selected"],
                    foreground=p["teal_text"], bordercolor=p["teal_text"],
                    font=(family, 10, "bold"), padding=(8, 3))
    style.configure("Refresh.TButton", background=p["bg"],
                    foreground=p["dim"], bordercolor=p["bg"],
                    font=(family, 9), padding=(2, 1), width=2)
    style.map("Refresh.TButton", foreground=[("active", p["teal_text"])])

    style.configure("TCheckbutton", background=p["bg"], foreground=p["text"],
                    font=(family, 10), indicatorforeground=p["text"],
                    indicatorbackground=p["input"])
    check_map = {
        "indicatorbackground": [("selected", p["action"]),
                                ("pressed", p["highlight"]),
                                ("active", p["highlight"])],
        "indicatorforeground": [("selected", p["on_action"]),
                                ("pressed", p["text"])],
        "foreground": [("disabled", p["dim"]), ("active", p["text"])],
    }
    style.map("TCheckbutton", **check_map)
    style.configure("Card.TCheckbutton", background=p["glass"],
                    foreground=p["text"], font=(family, 10),
                    indicatorforeground=p["text"],
                    indicatorbackground=p["input"])
    style.map("Card.TCheckbutton", **check_map)
    style.configure("Head.TCheckbutton", background=p["surface2"],
                    foreground=p["text"], font=(family, 10))
    style.configure("Theme.TRadiobutton", background=p["glass"],
                    foreground=p["text"], font=(family, 10),
                    indicatorforeground=p["text"],
                    indicatorbackground=p["surface2"])
    style.map("Theme.TRadiobutton", indicatorbackground=[("pressed", p["highlight"])])
    style.configure("Segment.TButton", background=p["glass"],
                    foreground=p["muted"], bordercolor=p["border"],
                    font=(family, 9, "bold"), padding=(9, 5))
    style.map("Segment.TButton", background=[("active", p["highlight"])],
              foreground=[("active", p["text"])])
    style.configure("SegmentActive.TButton", background=p["action"],
                    foreground=p["on_action"], bordercolor=p["action"],
                    font=(family, 9, "bold"), padding=(9, 5))
    style.map("SegmentActive.TButton", background=[("active", active_action)])

    style.configure("TEntry", fieldbackground=p["input"], foreground=p["text"],
                    bordercolor=p["control_border"], padding=4, insertcolor=p["text"])
    style.configure("TCombobox", fieldbackground=p["input"],
                    foreground=p["text"], bordercolor=p["control_border"],
                    background=p["surface2"],
                    arrowcolor=p["muted"], padding=4)
    style.map("TEntry", bordercolor=[("focus", p["teal_text"])],
              lightcolor=[("focus", p["teal_text"])])
    # clam 的只读和选中状态配色会覆盖 configure 中的颜色。
    style.map("TCombobox",
              fieldbackground=[("readonly", "focus", p["highlight"]),
                               ("readonly", p["input"])],
              foreground=[("disabled", p["muted"]),
                          ("readonly", p["text"])],
              background=[("active", p["highlight"])],
              bordercolor=[("focus", p["teal_text"])],
              selectbackground=[("readonly", p["surface2"]),
                                *style.map(".", "selectbackground")],
              selectforeground=[("readonly", p["text"]),
                                *style.map(".", "selectforeground")])
    style.configure("Treeview", background=p["input"], fieldbackground=p["input"],
                    foreground=p["text"], bordercolor=p["border"],
                    font=(family, 10))
    style.configure("Treeview.Heading", background=p["surface2"],
                    foreground=p["muted"], font=(family, 9, "bold"))
    style.configure("TScrollbar", background=p["control_border"],
                    troughcolor=p["surface"], bordercolor=p["surface"],
                    lightcolor=p["control_border"], darkcolor=p["control_border"],
                    arrowcolor=p["muted"], arrowsize=9, gripcount=0)
    style.map("TScrollbar", background=[("active", p["muted"])])
    style.configure("Log.Vertical.TScrollbar", troughcolor=p["log_bg"],
                    bordercolor=p["log_bg"])
    return resolved
