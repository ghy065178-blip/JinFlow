# -*- coding: utf-8 -*-
"""通用界面组件：可滚动容器、状态卡片、彩色日志视图。"""
import re
import tkinter as tk
from tkinter import ttk

from .theme import LEVEL_COLORS, PALETTE


class ScrollableFrame(ttk.Frame):
    """带纵向滚动条的容器；内容放 self.body。

    滚动输入支持三种来源：
      * 鼠标滚轮 / 触控板：<MouseWheel>（Windows、macOS），<Button-4/5>（Linux）；
      * 触摸屏：在面板空白处按住拖动（Button-1 拖拽平移）；
      * 原有滚动条拖动保持不变。

    实现要点：滚轮事件由 Tk 派发给指针下的最深层控件，不会自动冒泡到父容器，
    因此不能只在容器自身绑定。这里给整棵子树追加一个唯一的 bindtag，再在 tag
    上统一绑定处理函数；tag 只作用于本容器内的控件，右侧实时终端等区域不受影响。
    bind_wheel_tree() 幂等，动态重建字段控件后重新调用即可。
    """

    # 这些是非交互容器/标签，才接管拖拽平移；输入、下拉、复选、按钮等不接管，
    # 避免破坏选择文本、下拉选择、点击等原有交互。
    PANNABLE = (tk.Frame, ttk.Frame, tk.Label, ttk.Label, tk.Canvas)

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, background=PALETTE["bg"],
                                highlightthickness=0, borderwidth=0,
                                yscrollincrement=1)
        self.vsb = ttk.Scrollbar(self, orient="vertical",
                                 command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.body,
                                              anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.body.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Configure>", self._on_canvas)

        suffix = str(id(self))
        self._wheel_tag = "JSJWheel_" + suffix
        self._pan_tag = "JSJPan_" + suffix
        self.bind_class(self._wheel_tag, "<MouseWheel>", self._on_wheel)
        self.bind_class(self._wheel_tag, "<Button-4>", self._on_wheel)
        self.bind_class(self._wheel_tag, "<Button-5>", self._on_wheel)
        self.bind_class(self._pan_tag, "<ButtonPress-1>", self._on_pan_start)
        self.bind_class(self._pan_tag, "<B1-Motion>", self._on_pan_move)
        self.bind_class(self._pan_tag, "<ButtonRelease-1>", self._on_pan_end)
        self._pan_active = False
        self._pan_y = 0
        self._pan_moved = False
        self._windowing_system = self.tk.call("tk", "windowingsystem")
        self._wheel_pixels = 0
        self._wheel_after = None
        self._scrollregion_after = None
        self._scrollregion = None
        self._canvas_width = None
        self._canvas_width_after = None
        self._pending_canvas_width = None
        self.bind_wheel_tree()

    @classmethod
    def _is_pannable(cls, widget):
        return isinstance(widget, cls.PANNABLE)

    def bind_wheel_tree(self):
        """给本容器及所有后代挂上滚动支持；可重复调用，不会重复叠加绑定。"""
        self._apply_tags(self)
        self._on_configure(None)

    def _apply_tags(self, widget):
        tags = list(widget.bindtags())
        if self._wheel_tag not in tags:
            tags.append(self._wheel_tag)
        if self._is_pannable(widget) and self._pan_tag not in tags:
            tags.append(self._pan_tag)
        widget.bindtags(tuple(tags))
        for child in widget.winfo_children():
            self._apply_tags(child)

    def _scroll(self, units):
        if not units:
            return
        top, bottom = self.canvas.yview()
        if (units < 0 and top <= 0) or (units > 0 and bottom >= 1):
            return
        self.canvas.yview_scroll(units, "units")

    def _on_wheel(self, event):
        num = getattr(event, "num", None)
        if num in (4, 5):
            pixels = -60 if num == 4 else 60
        else:
            # Aqua 提供小幅原生增量，Windows 的一格滚轮为 120。
            scale = 8 if self._windowing_system == "aqua" else 0.5
            pixels = -event.delta * scale
        if pixels:
            self._wheel_pixels += pixels
            if self._wheel_after is None:
                self._wheel_after = self.after(8, self._flush_wheel)
        return "break"

    def _flush_wheel(self):
        self._wheel_after = None
        pixels = int(self._wheel_pixels)
        self._wheel_pixels -= pixels
        self._scroll(pixels)

    def _on_pan_start(self, event):
        self._pan_active = True
        self._pan_y = event.y_root
        self._pan_moved = False

    def _on_pan_move(self, event):
        if not self._pan_active:
            return
        dy = event.y_root - self._pan_y
        if not self._pan_moved and abs(dy) < 3:
            return
        self._pan_moved = True
        self._scroll(-dy)
        self._pan_y = event.y_root
        return "break"

    def _on_pan_end(self, _event):
        self._pan_active = False

    def _on_configure(self, _event):
        # Dynamic profile/field rebuilds emit many Configure events. Coalesce
        # them into one idle callback so scrolling never competes with layout
        # recalculation on macOS trackpads.
        if self._scrollregion_after is None:
            self._scrollregion_after = self.after_idle(self._apply_scrollregion)

    def _apply_scrollregion(self):
        self._scrollregion_after = None
        region = self.canvas.bbox(self._win)
        if region and region != self._scrollregion:
            self._scrollregion = region
            self.canvas.configure(scrollregion=region)

    def _on_canvas(self, event):
        self._pending_canvas_width = event.width
        if event.width != self._canvas_width and self._canvas_width_after is None:
            if self._windowing_system == "win32":
                self._canvas_width_after = self.after(16, self._apply_canvas_width)
            else:
                self._canvas_width_after = self.after_idle(
                    self._apply_canvas_width)

    def _apply_canvas_width(self):
        self._canvas_width_after = None
        width = self._pending_canvas_width
        self._pending_canvas_width = None
        if width is None or width == self._canvas_width:
            return
        self._canvas_width = width
        self.canvas.itemconfig(self._win, width=width)

    def destroy(self):
        for timer in (self._wheel_after, self._scrollregion_after,
                      self._canvas_width_after):
            if timer is not None:
                self.after_cancel(timer)
        super().destroy()

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()


class StatusCard(ttk.Frame):
    def __init__(self, parent, key, note=""):
        super().__init__(parent, style="Glass.TFrame", padding=(12, 10))
        ttk.Label(self, text=key, style="Key.TLabel").pack(anchor="w")
        self.value = ttk.Label(self, text="--", style="Value.TLabel")
        self.value.pack(anchor="w", pady=(3, 0))
        self.note = ttk.Label(self, text=note, style="CardMuted.TLabel")
        self.note.pack(anchor="w")
        self._color = PALETTE["text"]

    def set(self, value, note=None, color=None):
        value = str(value)
        if self.value.cget("text") != value:
            self.value.configure(text=value)
        if note is not None and self.note.cget("text") != note:
            self.note.configure(text=str(note))
        color = color or PALETTE["text"]
        if color != self._color:
            self.value.configure(foreground=color)
            self._color = color


class LogView(tk.Text):
    LEVELS = list(LEVEL_COLORS.keys())

    def __init__(self, parent, **kwargs):
        self.frame = ttk.Frame(parent)
        super().__init__(self.frame, wrap="word", state="disabled", borderwidth=0,
                         highlightthickness=0, font="TkFixedFont", height=18,
                         padx=13, pady=10, **kwargs)
        scrollbar = ttk.Scrollbar(self.frame, command=self.yview,
                                  style="Log.Vertical.TScrollbar")
        self.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.pack(side="left", fill="both", expand=True)
        self.retheme()
        self._lines = []

    def retheme(self):
        self.configure(background=PALETTE["log_bg"],
                       foreground=PALETTE["log_text"],
                       insertbackground=PALETTE["log_text"])
        for level, color in LEVEL_COLORS.items():
            self.tag_configure("lv-" + level, foreground=color)
        self.tag_configure("ts", foreground=PALETTE["log_ts"])

    def append(self, ts, level, text, mask=False, scroll=True):
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
        if scroll:
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
