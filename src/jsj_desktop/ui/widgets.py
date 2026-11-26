# -*- coding: utf-8 -*-
"""通用界面组件：可滚动容器、状态卡片、彩色日志视图。"""
import re
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from .theme import LEVEL_COLORS, PALETTE, font_family


class ScrollableFrame(ttk.Frame):
    """带纵向滚动条的容器；内容放 self.body。"""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, background=PALETTE["bg"],
                                highlightthickness=0, borderwidth=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical",
                                 command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, style="Card.TFrame")
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.body.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Configure>", self._on_canvas)
        self._bind_wheel(self)

    def _bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._on_wheel, add="+")
        widget.bind("<Button-4>", self._on_wheel, add="+")
        widget.bind("<Button-5>", self._on_wheel, add="+")

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            self.canvas.yview_scroll(-3, "units")
        elif getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
            self.canvas.yview_scroll(3, "units")

    def _on_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        self.canvas.itemconfig(self._win, width=event.width)

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()


class StatusCard(ttk.Frame):
    def __init__(self, parent, key, note=""):
        super().__init__(parent, style="Card.TFrame", padding=(12, 10))
        ttk.Label(self, text=key, style="Key.TLabel").pack(anchor="w")
        self.value = ttk.Label(self, text="--", style="Value.TLabel")
        self.value.pack(anchor="w", pady=(3, 0))
        self.note = ttk.Label(self, text=note, style="CardMuted.TLabel")
        self.note.pack(anchor="w")
        self._color = PALETTE["text"]

    def set(self, value, note=None, color=None):
        self.value.configure(text=str(value))
        if note is not None:
            self.note.configure(text=str(note))
        color = color or PALETTE["text"]
        if color != self._color:
            self.value.configure(foreground=color)
            self._color = color


class LogView(ScrolledText):
    LEVELS = list(LEVEL_COLORS.keys())

    def __init__(self, parent, **kwargs):
        super().__init__(parent, wrap="word", background=PALETTE["log_bg"],
                         foreground=PALETTE["log_text"],
                         insertbackground=PALETTE["log_text"],
                         borderwidth=0, font=("Consolas", 10), height=18,
                         **kwargs)
        self.configure(state="disabled")
        for level, color in LEVEL_COLORS.items():
            self.tag_configure("lv-" + level, foreground=color)
        self.tag_configure("ts", foreground=PALETTE["log_ts"])
        self._lines = []

    def append(self, ts, level, text, mask=False):
        shown = mask_text(text) if mask else text
        self._lines.append("%s  %s" % (ts, shown))
        if len(self._lines) > 3000:
            self._lines.pop(0)
        self.configure(state="normal")
        while int(self.index("end-1c").split(".")[0]) > 1200:
            self.delete("1.0", "2.0")
        self.insert("end", ts + "  ", "ts")
        self.insert("end", shown + "\n", "lv-" + (level if level in self.LEVELS else "info"))
        self.configure(state="disabled")
        self.see("end")

    def clear(self):
        self._lines.clear()
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")

    def text(self):
        return "\n".join(self._lines)


_MASK_PATTERNS = [
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),          # 手机号
    re.compile(r"(?<!\d)\d{15,18}(?!\d)"),             # 学号 / 证件号
]


def mask_text(text):
    """日志显示脱敏：只影响显示，不影响任何提交数据。"""
    out = str(text)
    for pattern in _MASK_PATTERNS:
        out = pattern.sub(lambda m: m.group(0)[:2] + "*" * (len(m.group(0)) - 4)
                          + m.group(0)[-2:], out)
    return out
