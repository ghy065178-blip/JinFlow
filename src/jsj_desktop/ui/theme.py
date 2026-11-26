# -*- coding: utf-8 -*-
"""界面主题：逐项复刻旧版 control_panel.html 的 CSS 变量（GitHub 风格深色）。

    --bg:#0d1117; --surface:#161b22; --surface2:#1c2128; --border:#30363d;
    --text:#e6edf3; --muted:#8b949e; --dim:#6e7681;
    --teal:#2dd4bf; --blue:#58a6ff; --green:#3fb950; --amber:#d29922;
    --red:#f85149; --purple:#bc8cff;
这样主窗口与文件夹内的可视化操控面板在配色、层次与视觉呈现上保持一致。
"""
import tkinter as tk
from tkinter import ttk

PALETTE = {
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
}

LEVEL_COLORS = {
    "ok": PALETTE["green"], "error": PALETTE["red"],
    "warn": PALETTE["amber"], "rush": PALETTE["blue"],
    "wait": "#7d8590", "reply": PALETTE["purple"],
    "prompt": "#9aa7b4", "info": PALETTE["log_text"],
}


def font_family():
    """与原 HTML 的 font-family 顺序一致。"""
    import sys
    if sys.platform == "win32":
        return "Microsoft YaHei"
    if sys.platform == "darwin":
        return "PingFang SC"
    return "Segoe UI"


def apply(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    p = PALETTE
    family = font_family()
    root.configure(background=p["bg"])
    style.configure(".", background=p["bg"], foreground=p["text"],
                    font=(family, 10), fieldbackground=p["bg"],
                    bordercolor=p["border"], insertcolor=p["text"],
                    troughcolor=p["surface2"], focuscolor=p["teal"])
    style.configure("TFrame", background=p["bg"])
    style.configure("Card.TFrame", background=p["surface"], relief="solid",
                     borderwidth=1, bordercolor=p["border"])
    style.configure("CardHead.TFrame", background=p["surface2"])
    style.configure("Pill.TFrame", background=p["surface"], relief="solid",
                    borderwidth=1, bordercolor=p["border"])

    style.configure("TLabel", background=p["bg"], foreground=p["text"],
                    font=(family, 10))
    style.configure("Card.TLabel", background=p["surface"],
                    foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"],
                    font=(family, 9))
    style.configure("CardMuted.TLabel", background=p["surface"],
                    foreground=p["muted"], font=(family, 9))
    style.configure("Key.TLabel", background=p["bg"], foreground=p["dim"],
                    font=(family, 9))
    style.configure("CardKey.TLabel", background=p["bg"], foreground=p["dim"],
                    font=(family, 9))
    style.configure("Value.TLabel", background=p["surface"],
                    foreground=p["text"], font=(family, 16, "bold"))
    style.configure("Title.TLabel", background=p["bg"], foreground=p["text"],
                    font=(family, 14, "bold"))
    style.configure("PanelTitle.TLabel", background=p["surface2"],
                    foreground=p["text"], font=(family, 11, "bold"))
    style.configure("Hint.TLabel", background=p["bg"], foreground=p["dim"],
                    font=(family, 9))
    style.configure("CardHint.TLabel", background=p["surface"],
                    foreground=p["dim"], font=(family, 9))
    style.configure("Warn.TLabel", background=p["surface"],
                    foreground="#e3c07b", font=(family, 9))
    style.configure("Notice.TLabel", background="#1b2430",
                    foreground="#a9bccd", font=(family, 9))
    style.configure("Warnbox.TLabel", background="#2a2115",
                    foreground="#e3c07b", font=(family, 9))
    style.configure("Teal.TLabel", background=p["bg"], foreground=p["teal"],
                    font=(family, 10, "bold"))
    style.configure("Head.TLabel", background=p["surface2"],
                    foreground=p["muted"], font=(family, 10, "bold"))

    style.configure("TLabelframe", background=p["surface"],
                    bordercolor=p["border"], relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=p["surface"],
                    foreground=p["teal"], font=(family, 10, "bold"))

    style.configure("TButton", background=p["surface2"], foreground=p["text"],
                    bordercolor=p["border"], font=(family, 10), padding=(9, 5))
    style.map("TButton", background=[("active", "#26303c")],
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
    style.configure("Card.TCheckbutton", background=p["surface"],
                    foreground=p["text"], font=(family, 10))
    style.configure("Head.TCheckbutton", background=p["surface2"],
                    foreground=p["text"], font=(family, 10))

    style.configure("TEntry", fieldbackground=p["bg"], foreground=p["text"],
                    bordercolor=p["border"], padding=4, insertcolor=p["text"])
    style.configure("TCombobox", fieldbackground=p["bg"],
                    foreground=p["text"], bordercolor=p["border"],
                    arrowcolor=p["muted"], padding=4)
    style.configure("Treeview", background=p["bg"], fieldbackground=p["bg"],
                    foreground=p["text"], bordercolor=p["border"],
                    font=(family, 10))
    style.configure("Treeview.Heading", background=p["surface2"],
                    foreground=p["muted"], font=(family, 9, "bold"))
    style.configure("TScrollbar", background=p["surface2"],
                    troughcolor=p["bg"], bordercolor=p["border"],
                    arrowcolor=p["muted"])
    return style
