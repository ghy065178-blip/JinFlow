# -*- coding: utf-8 -*-
"""主窗口：与旧版 control_panel.html 完全一致的单页可视化操控面板。

布局、文案、操作入口、交互逻辑与功能行为逐项对齐原面板：
    header（品牌 / 连接状态 / 北京时间）
    taskbar（多开任务标签 + 每任务独立刷新 + 新建/关闭/刷新）
    cards（运行状态 / 倒计时 / 提交尝试 / 时钟偏差 / 最新反馈）
    main 左栏（运行配置 + 报名信息/个人信息档案）  右栏（实时终端）
    toast（右下角浮动提示）
差异只在实现机制：本地 HTTP + SSE + 子进程 stdout 抓取 → 原生窗口 +
线程安全事件队列 + 结构化应答。附加的高级设置/预览/迁移入口放在菜单与弹窗。
启动检查发现新版本时，在顶部显示可点击的发布页入口。
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import (BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, StringVar,
                     Tk, filedialog, messagebox, simpledialog, ttk)
from urllib.parse import quote

from .. import __app_name__, __version__
from ..core.constants import (CONFIG_LINK_KEY, CST, MAX_TASKS,
                              format_beijing_time, now_beijing)
from ..core.rules import is_visible
from ..data import paths as data_paths
from ..tasks.manager import TaskManager
from ..update.manifest import REPO_URL
from ..update.version import normalize_version
from .theme import (PALETTE, apply as apply_theme, detect_system_mode,
                    font_family, normalize_mode, refresh_tree)
from .widgets import LogView, ScrollableFrame, StatusCard

TIME_MODE_TEXTS = ["使用表单返回的开放时间",
                   "手动指定另一个时间",
                   "不等待，立即提交"]
THEME_CHOICES = (("dark", "黑色"), ("system", "跟随系统"), ("light", "白色"))


class MainWindow(Tk):
    def __init__(self, data_dir=None, start_task="t1"):
        super().__init__()
        self.title("JinFlow")
        self.geometry("1360x860")
        self.minsize(1080, 700)

        self.event_queue = queue.Queue()
        self.manager = TaskManager(self.event_queue, data_dir=data_dir)
        saved = self.manager.settings.load()
        self.theme_mode = normalize_mode(saved.get("theme_mode", "system"))
        self.theme_mode_var = StringVar(value=self.theme_mode)
        self.system_mode = detect_system_mode()
        self._resolved_theme = apply_theme(self, self.theme_mode,
                                           self.system_mode)
        self.configure(bg=PALETTE["bg"])
        self.active_task = start_task if self.manager.get(start_task) else "t1"
        self.task_ui = {}
        self.form = {"ok": False, "fields": [], "rules": {}, "name": "",
                     "status": "", "captcha": False, "open_time": ""}
        self.cfg = {}
        self.profiles_lib = {"profiles": [], "active": "", "exists": False}
        self.profile_ids = []
        self.field_defs = []
        self.field_widgets = {}
        self.field_rows = {}
        self._profiles_loading = False
        self._question_dialog = None
        self._question_req = None
        self._last_clock = ""
        self._last_theme_probe = 0.0
        self._toast_after = None
        self._tab_sig = None
        self._task_buttons_map = {}

        self._build_menu()
        self._build_header()
        self._build_taskbar()
        self._build_cards()
        self._build_main()
        self._build_overlays()

        self.mask_var.set(bool(saved.get("mask_logs", False)))
        self.autoscroll_var.set(bool(saved.get("auto_scroll", True)))
        self.update_var.set(bool(saved.get("check_update_on_startup", True)))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(80, self._poll)
        self._init_task(replay=True)
        if self.update_var.get():
            self.after_idle(self._auto_check_update)

    # ==================== 通用小组件 ====================
    def _panel(self, parent, title, tag=""):
        """复刻原 HTML 的 .panel / .panel-h / .panel-b。"""
        outer = ttk.Frame(parent, style="Glass.TFrame")
        head = ttk.Frame(outer, style="CardHead.TFrame", padding=(8, 6))
        head.pack(fill=X, padx=7, pady=(6, 0))
        ttk.Label(head, text=title, style="PanelTitle.TLabel").pack(side=LEFT)
        tag_label = ttk.Label(head, text=tag, style="PanelTag.TLabel")
        tag_label.pack(side=RIGHT)
        body = ttk.Frame(outer, style="Card.TFrame", padding=(7, 7))
        body.pack(fill=X, padx=7, pady=(0, 6))
        return outer, body, tag_label

    # ==================== 布局 ====================
    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="导入旧版数据…", command=self._import_legacy)
        file_menu.add_command(label="导入档案文件…", command=self._import_profiles)
        file_menu.add_command(label="导出当前档案库…", command=self._export_profiles)
        file_menu.add_separator()
        file_menu.add_command(label="打开本地数据目录", command=self._open_data_dir)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.close)
        menubar.add_cascade(label="文件", menu=file_menu)

        task_menu = tk.Menu(menubar, tearoff=0)
        task_menu.add_command(label="新建任务", command=self._new_task)
        task_menu.add_command(label="重命名当前任务", command=self._rename_task)
        task_menu.add_command(label="关闭当前任务", command=self._close_task)
        task_menu.add_separator()
        task_menu.add_command(label="预览提交数据…", command=self._preview)
        task_menu.add_command(label="停止全部任务", command=self._stop_all)
        menubar.add_cascade(label="任务", menu=task_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._show_guide)
        help_menu.add_command(label="设置与关于…", command=self._show_settings)
        help_menu.add_command(label="隐私与数据安全", command=self._show_privacy)
        help_menu.add_separator()
        help_menu.add_command(label="检查更新与升级…", command=self._show_update)
        help_menu.add_command(label="关于", command=self._about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.config(menu=menubar)

    def _build_header(self):
        top = ttk.Frame(self, padding=(20, 14, 20, 10))
        top.pack(fill=X)
        self.header = top
        ttk.Style(self).configure("Update.Primary.TButton", focuscolor="#042f2e")
        self.update_banner = ttk.Button(self, style="Update.Primary.TButton",
                                        takefocus=True, cursor="hand2")

        def activate_banner(_event):
            self.update_banner.invoke()
            return "break"

        self.update_banner.bind("<Return>", activate_banner)
        self._brand_icon = None
        try:
            icon_path = data_paths.resource_path("packaging/icons/app.png")
            self._brand_icon = tk.PhotoImage(master=self, file=icon_path)
            ttk.Label(top, image=self._brand_icon).pack(side=LEFT, padx=(0, 10))
        except (OSError, tk.TclError):
            ttk.Label(top, text="JF", style="Brand.TLabel").pack(
                side=LEFT, padx=(0, 10))
        brand = ttk.Frame(top)
        brand.pack(side=LEFT)
        ttk.Label(brand, text="JinFlow",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(brand, text="配置编辑 · 实时终端监控",
                  style="Muted.TLabel").pack(anchor="w")

        spacer = ttk.Frame(top)
        spacer.pack(side=LEFT, fill=X, expand=True)

        conn = ttk.Frame(top, style="Pill.TFrame", padding=(10, 6))
        conn.pack(side=LEFT, padx=(0, 8))
        self.conn_text = ttk.Label(conn, text="●  实时监控已连接", style="Connected.TLabel")
        self.conn_text.pack(side=LEFT)

        clock = ttk.Frame(top, style="Pill.TFrame", padding=(10, 6))
        clock.pack(side=LEFT, padx=(0, 8))
        self.clock_var = StringVar(value="--:--:--")
        ttk.Label(clock, text="北京时间 ", style="CardMuted.TLabel").pack(side=LEFT, padx=(0, 6))
        ttk.Label(clock, textvariable=self.clock_var,
                  style="Clock.TLabel", width=8).pack(side=LEFT)

        self.header_theme_buttons = ttk.Frame(top, style="Pill.TFrame", padding=4)
        self.header_theme_buttons.pack(side=LEFT)
        self.header_theme_widgets = {}
        for value, label in THEME_CHOICES:
            button = ttk.Button(
                self.header_theme_buttons, text=label,
                style="SegmentActive.TButton" if value == self.theme_mode
                else "Segment.TButton",
                command=lambda selected=value: self._set_header_theme(selected))
            button.pack(side=LEFT, padx=1)
            self.header_theme_widgets[value] = button

    def _build_taskbar(self):
        inner = ttk.Frame(self, style="Glass.TFrame", padding=(12, 8))
        inner.pack(fill=X, padx=20, pady=(0, 12))
        ttk.Label(inner, text="多开任务", style="Teal.TLabel").pack(
            side=LEFT, padx=(0, 8))
        self.task_buttons = ttk.Frame(inner, style="Card.TFrame")
        self.task_buttons.pack(side=LEFT)
        self.btn_task_add = ttk.Button(inner, text="+ 新建任务",
                                        style="SmPrimary.TButton",
                                        command=self._new_task)
        self.btn_task_add.pack(side=LEFT, padx=(10, 4))
        self.btn_task_close = ttk.Button(inner, text="关闭当前",
                                         style="Sm.TButton",
                                         command=self._close_task)
        self.btn_task_close.pack(side=LEFT, padx=4)
        self.btn_task_refresh = ttk.Button(
            inner, text="↻ 刷新状态", style="Sm.TButton",
            command=self._refresh_all)
        self.btn_task_refresh.pack(side=LEFT, padx=4)
        self.task_hint = ttk.Label(inner, text="", style="CardHint.TLabel")
        self.task_hint.pack(side=RIGHT)

    def _build_cards(self):
        cards = ttk.Frame(self)
        cards.pack(fill=X, padx=20, pady=(0, 12))
        self.cards = {}
        specs = [("state", "运行状态", "空闲", "尚未启动脚本"),
                 ("count", "距开放 / 倒计时", "--", "开放时间未知"),
                 ("attempt", "提交尝试", "0", "待提交字段 0 项"),
                 ("offset", "服务器时钟偏差", "--", "进程未启动"),
                 ("last", "最新反馈", "--", "自动应答 0 次")]
        for i, (key, label, value, note) in enumerate(specs):
            c = StatusCard(cards, label, note)
            c.value.configure(text=value)
            c.grid(row=0, column=i, sticky="nsew",
                   padx=(0 if i == 0 else 5, 0 if i == len(specs) - 1 else 5))
            cards.columnconfigure(i, weight=1, uniform="status")
            self.cards[key] = c

    def _build_main(self):
        main = ttk.Frame(self)
        main.pack(fill=BOTH, expand=True, padx=20, pady=(0, 16))
        self.main_pane = tk.PanedWindow(
            main, orient=tk.HORIZONTAL, borderwidth=0, sashwidth=7,
            sashrelief="flat", opaqueresize=True, background=PALETTE["border"])
        self.main_pane.pack(fill=BOTH, expand=True)
        self.left_scroll = ScrollableFrame(self.main_pane)
        self.term_frame = ttk.Frame(self.main_pane)
        self.main_pane.add(self.left_scroll, width=420, minsize=360,
                           stretch="never")
        self.main_pane.add(self.term_frame, minsize=390, stretch="always")
        self._build_console()
        self._build_info()
        self._build_logs()
        # 所有左栏控件创建完成后，统一挂上滚轮/触控板/触摸滚动支持
        self.left_scroll.bind_wheel_tree()

    def _build_overlays(self):
        self._build_toast()
        self._build_preview_window()
        self._build_settings()

    # -------------------- 运行配置（左栏） --------------------
    def _build_console(self):
        outer, body, _tag = self._panel(self.left_scroll.body, "运行配置",
                                       "原脚本参数")
        outer.pack(fill=X, pady=(0, 12))
        ttk.Label(body, text="本次表单链接（完整 URL 或末尾 token）",
                  style="CardMuted.TLabel").pack(anchor="w")
        row = ttk.Frame(body, style="Card.TFrame")
        row.pack(fill=X, pady=(4, 0))
        self.link_var = StringVar()
        self.link_entry = ttk.Entry(row, textvariable=self.link_var)
        self.link_entry.pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row, text="读取表单",
                   command=lambda: self._load_form(False)).pack(side=LEFT, padx=(6, 0))
        ttk.Label(body, text="每次活动链接不同，读取后自动按本次表单结构生成下方填写项。"
                  "粘贴完整 URL（如 https://jsj.top/f/xxxxx）或末尾 token。",
                  style="CardHint.TLabel", wraplength=390).pack(anchor="w", pady=(4, 10))

        grid = ttk.Frame(body, style="Inset.TFrame", padding=(10, 8))
        grid.pack(fill=X)
        self.form_labels = {}
        for i, (k, label, initial) in enumerate([
                ("name", "表单名称", "未读取"), ("status", "状态", "--"),
                ("open", "开放时间", "--"), ("captcha", "验证码", "--"),
                ("fields", "字段数", "--")]):
            ttk.Label(grid, text=label, style="InsetKey.TLabel").grid(
                row=i, column=0, sticky="w", pady=2)
            v = ttk.Label(grid, text=initial, style="Inset.TLabel",
                          wraplength=280, justify=LEFT)
            v.grid(row=i, column=1, sticky="w", padx=10, pady=2)
            self.form_labels[k] = v
        self.warn_label = ttk.Label(body, text="", style="Warnbox.TLabel",
                                    wraplength=350, justify=LEFT, padding=(10, 8))

        ttk.Label(body, text="运行方式", style="CardMuted.TLabel").pack(
            anchor="w", pady=(12, 4))
        opts = ttk.Frame(body, style="Card.TFrame")
        opts.pack(fill=X)
        self._warn_anchor = opts
        self.quick_var = BooleanVar(value=False)
        self.dry_var = BooleanVar(value=False)
        self.auto_reply_var = BooleanVar(value=True)
        for text, var in [("快速模式 --quick", self.quick_var),
                          ("仅演练 --dry-run", self.dry_var),
                          ("自动应答终端提问", self.auto_reply_var)]:
            ttk.Checkbutton(opts, text=text, variable=var,
                            style="Card.TCheckbutton").pack(side=LEFT, padx=(0, 10))

        ttk.Label(body, text="目标开放时间来源（交互模式由平台自动应答）",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(12, 4))
        self.time_mode_var = StringVar(value="1")
        self.time_mode_cb = ttk.Combobox(body, values=TIME_MODE_TEXTS,
                                          state="readonly")
        self.time_mode_cb.bind("<<ComboboxSelected>>", self._on_time_mode)
        self.time_mode_cb.pack(fill=X)
        self.manual_time_var = StringVar()
        ttk.Entry(body, textvariable=self.manual_time_var).pack(fill=X, pady=(6, 0))
        ttk.Label(body, text="手动时间：2026-11-20 20:00:00（北京时间）",
                  style="CardHint.TLabel").pack(anchor="w")
        self._set_time_mode("1")

        ttk.Label(body, text="冲刺参数", style="CardMuted.TLabel").pack(
            anchor="w", pady=(12, 4))
        grid3 = ttk.Frame(body, style="Card.TFrame")
        grid3.pack(fill=X)
        self.lead_var = StringVar(value="-6")
        self.interval_var = StringVar(value="0.05")
        self.timeout_var = StringVar(value="40")
        for i, (label, var) in enumerate([("提前量(秒)", self.lead_var),
                                          ("间隔(秒)", self.interval_var),
                                          ("时长(秒)", self.timeout_var)]):
            cell = ttk.Frame(grid3, style="Card.TFrame")
            cell.grid(row=0, column=i, sticky="ew", padx=(0, 6))
            grid3.columnconfigure(i, weight=1)
            ttk.Entry(cell, textvariable=var).pack(fill=X)
            ttk.Label(cell, text=label, style="CardHint.TLabel").pack(anchor="w")
        ttk.Label(body, text="提前量为正数＝开放前开始冲；默认 -6 表示开放后 6 秒起跑"
                  "（原脚本默认值）。", style="CardHint.TLabel",
                  wraplength=390).pack(anchor="w", pady=(6, 10))

        btns = ttk.Frame(body, style="Card.TFrame")
        btns.pack(fill=X)
        self.btn_start = ttk.Button(btns, text="启动脚本",
                                    style="Primary.TButton",
                                    command=lambda: self._start(False))
        self.btn_start.pack(side=LEFT)
        self.btn_dry = ttk.Button(btns, text="演练自检",
                                  command=lambda: self._start(True))
        self.btn_dry.pack(side=LEFT, padx=6)
        self.btn_stop = ttk.Button(btns, text="停止", style="Danger.TButton",
                                   command=self._stop, state="disabled")
        self.btn_stop.pack(side=LEFT)

    def _on_time_mode(self, _event=None):
        idx = self.time_mode_cb.current()
        if 0 <= idx < len(TIME_MODE_TEXTS):
            self.time_mode_var.set(str(idx + 1))

    def _set_time_mode(self, value):
        try:
            idx = int(str(value)) - 1
        except (TypeError, ValueError):
            idx = 0
        idx = max(0, min(len(TIME_MODE_TEXTS) - 1, idx))
        self.time_mode_var.set(str(idx + 1))
        self.time_mode_cb.current(idx)

    # -------------------- 报名信息（左栏） --------------------
    def _build_info(self):
        outer, body, tag_label = self._panel(self.left_scroll.body, "报名信息",
                                             "按表单结构动态生成")
        outer.pack(fill=X)
        self.field_tag = tag_label

        prof = tk.Frame(body, bg=PALETTE["bg"],
                        highlightbackground=PALETTE["border"], highlightthickness=1,
                        padx=10, pady=9)
        prof.pack(fill=X, pady=(0, 12))
        tk.Label(prof, text="个人信息档案 · 保存多套，一键切换",
                 bg=PALETTE["bg"], fg=PALETTE["teal"],
                 font=(font_family(), 9, "bold")).pack(anchor="w", pady=(0, 8))

        profile_select_row = ttk.Frame(prof, style="Card.TFrame")
        profile_select_row.pack(fill=X)
        self.profile_sel = ttk.Combobox(profile_select_row, state="readonly", values=[])
        self.profile_sel.pack(side=LEFT, fill=X, expand=True)
        self.profile_sel.bind("<<ComboboxSelected>>", self._on_profile_select)

        profile_button_row = ttk.Frame(prof, style="Card.TFrame")
        profile_button_row.pack(fill=X, pady=(6, 0))
        for column in range(4):
            profile_button_row.columnconfigure(column, weight=1,
                                                uniform="profile-actions")
        self.profile_btns = {}
        for column, (key, text, cmd) in enumerate([
                ("apply", "应用", self._apply_profile),
                ("update", "更新", self._update_profile),
                ("rename", "重命名", self._rename_profile),
                ("delete", "删除", self._delete_profile)]):
            b = ttk.Button(profile_button_row, text=text,
                           style=("SmDanger.TButton"
                                  if key == "delete" else "Sm.TButton"),
                           command=cmd)
            b.grid(row=0, column=column, sticky="ew", padx=2)
            self.profile_btns[key] = b

        row2 = ttk.Frame(prof, style="Card.TFrame")
        row2.pack(fill=X, pady=(8, 0))
        self.profile_name_var = StringVar()
        ttk.Entry(row2, textvariable=self.profile_name_var).pack(
            side=LEFT, fill=X, expand=True)
        ttk.Button(row2, text="把当前信息存为新档案",
                   style="SmPrimary.TButton",
                   command=self._add_profile).pack(side=LEFT, padx=(6, 0))
        self.profile_hint = ttk.Label(prof, text="", style="CardHint.TLabel",
                                      wraplength=390, justify=LEFT)
        self.profile_hint.pack(anchor="w", pady=(8, 0))

        self.fields_box = ttk.Frame(body, style="Card.TFrame")
        self.fields_box.pack(fill=X)
        self.fields_box.columnconfigure(0, weight=1)

        bottom = ttk.Frame(body, style="Card.TFrame")
        bottom.pack(fill=X, pady=(12, 0))
        ttk.Button(bottom, text="保存信息", style="Primary.TButton",
                   command=lambda: self._save_config(False)).pack(side=LEFT)
        ttk.Button(bottom, text="重新载入", command=self._reload_config) \
            .pack(side=LEFT, padx=6)
        ttk.Label(body, text="保存后写入「报名信息.json」；联动隐藏的字段不会写入，"
                 "与原脚本行为一致。", style="CardHint.TLabel",
                 wraplength=390).pack(anchor="w", pady=(8, 0))

    # -------------------- 实时终端（右栏） --------------------
    def _build_logs(self):
        outer = ttk.Frame(self.term_frame, style="Glass.TFrame", padding=(7, 6))
        outer.pack(fill=BOTH, expand=True)
        head = ttk.Frame(outer, style="CardHead.TFrame", padding=(8, 6))
        head.pack(fill=X)
        ttk.Label(head, text="实时终端", style="PanelTitle.TLabel").pack(side=LEFT)
        self.wait_label = ttk.Label(head, text="", style="PanelWarn.TLabel")
        self.wait_label.pack(side=LEFT, padx=(8, 0))
        spacer = ttk.Frame(head, style="CardHead.TFrame")
        spacer.pack(side=LEFT, fill=X, expand=True)
        self.autoscroll_var = BooleanVar(value=True)
        ttk.Checkbutton(head, text="自动滚动", variable=self.autoscroll_var,
                        style="Head.TCheckbutton").pack(side=LEFT, padx=(8, 4))
        ttk.Button(head, text="清空", style="Sm.TButton",
                   command=self._clear_logs).pack(side=LEFT, padx=4)
        ttk.Button(head, text="导出日志", style="Sm.TButton",
                   command=self._export_logs).pack(side=LEFT)

        self.log_view = LogView(outer)
        self.log_view.frame.pack(fill=BOTH, expand=True, pady=(5, 0))

        send_bar = ttk.Frame(outer, style="CardHead.TFrame", padding=(10, 8))
        send_bar.pack(fill=X)
        self.stdin_var = StringVar()
        entry = ttk.Entry(send_bar, textvariable=self.stdin_var)
        entry.pack(side=LEFT, fill=X, expand=True)
        entry.bind("<Return>", lambda _e: self._send_entry())
        ttk.Button(send_bar, text="发送", style="Primary.TButton",
                   command=self._send_entry).pack(side=LEFT, padx=6)
        for label, value in [("回车", ""), ("1", "1"), ("2", "2"), ("3", "3"),
                             ("m", "m"), ("q", "q")]:
            ttk.Button(send_bar, text=label, style="Sm.TButton",
                       command=lambda v=value: self._send_quick(v)) \
                .pack(side=LEFT, padx=2)
        self.stdin_hint = tk.Label(
            outer, bg=PALETTE["glass"], fg=PALETTE["dim"],
            font=(font_family(), 9), anchor="w", justify=LEFT,
            text="向脚本终端发送一行（回车发送）；自动应答关闭时在此手动回复。")
        self.stdin_hint.pack(fill=X, padx=12, pady=(0, 8))

    # -------------------- 浮层：toast / 预览 / 设置 --------------------
    def _build_toast(self):
        # Toast remains inside the main toplevel. A separate overrideredirect
        # window can become a new macOS Space/focus target in full-screen mode.
        outer = tk.Frame(self, bg=PALETTE["glass"],
                         highlightbackground=PALETTE["border"],
                         highlightthickness=1)
        outer.pack(fill=BOTH, expand=True)
        accent = tk.Frame(outer, bg=PALETTE["teal"], width=3)
        accent.pack(side=LEFT, fill=Y)
        label = tk.Label(outer, text="", bg=PALETTE["surface2"],
                         fg=PALETTE["text"], font=(font_family(), 10),
                         wraplength=360, justify=LEFT, padx=12, pady=10)
        label.pack(side=LEFT, fill=BOTH, expand=True)
        self.toast_win = outer
        self.toast_win.place_forget()
        self.toast_accent = accent
        self.toast_label = label

    def _build_preview_window(self):
        win = tk.Toplevel(self)
        win.title("本次将提交的信息（按联动规则自动选取）")
        win.geometry("640x420")
        win.configure(bg=PALETTE["bg"])
        win.withdraw()
        cols = ("field", "display", "value")
        self.preview_tree = ttk.Treeview(win, columns=cols, show="headings")
        for col, name, width in [("field", "字段", 140),
                                 ("display", "显示值", 200),
                                 ("value", "提交值", 220)]:
            self.preview_tree.heading(col, text=name)
            self.preview_tree.column(col, width=width, anchor="w")
        sb = ttk.Scrollbar(win, orient="vertical",
                           command=self.preview_tree.yview)
        self.preview_tree.configure(yscrollcommand=sb.set)
        self.preview_tree.pack(side=LEFT, fill=BOTH, expand=True, padx=12, pady=12)
        sb.pack(side=RIGHT, fill=Y, pady=12)
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        self.preview_window = win

    def _build_settings(self):
        """附加设置与关于：不占用主界面，从「帮助」菜单打开。"""
        win = tk.Toplevel(self)
        win.title("设置与关于")
        win.geometry("660x560")
        win.configure(bg=PALETTE["bg"])
        win.withdraw()
        parent = ttk.Frame(win, padding=14)
        parent.pack(fill=BOTH, expand=True)
        parent.columnconfigure(0, weight=1)

        box = ttk.LabelFrame(parent, text="本地数据与隐私", padding=12)
        box.pack(fill=X)
        self.datadir_var = StringVar(value=str(data_paths.data_dir()))
        row = ttk.Frame(box)
        row.pack(fill=X, pady=(4, 8))
        ttk.Entry(row, textvariable=self.datadir_var,
                  state="readonly").pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row, text="打开目录", command=self._open_data_dir) \
            .pack(side=LEFT, padx=6)
        ttk.Label(box, text=(
            "· 报名信息按任务隔离保存于 tasks/<任务>/报名信息.json，写入前自动生成备份；\n"
            "· 多人档案保存于 profiles.json，支持新建 / 更新 / 重命名 / 删除 / 切换 / 导入导出；\n"
            "· 仓库与发布包不包含任何真实姓名、学号、电话、表单 token 或运行日志；\n"
            "· 运行日志默认只存在于内存，导出文件由用户自行选择保存位置。"),
            style="CardHint.TLabel", justify=LEFT).pack(anchor="w")

        adv = ttk.LabelFrame(parent, text="高级选项", padding=12)
        adv.pack(fill=X, pady=(10, 0))
        theme_row = ttk.Frame(adv, style="Card.TFrame")
        theme_row.pack(fill=X, pady=(0, 8))
        ttk.Label(theme_row, text="界面主题", style="CardMuted.TLabel") \
            .pack(side=LEFT, padx=(0, 12))
        self.theme_buttons = ttk.Frame(theme_row, style="Card.TFrame")
        self.theme_buttons.pack(side=LEFT)
        for value, label in THEME_CHOICES:
            ttk.Radiobutton(
                self.theme_buttons, text=label, value=value,
                variable=self.theme_mode_var, style="Theme.TRadiobutton",
                command=self._on_theme_changed).pack(side=LEFT, padx=(0, 10))
        self.mask_var = BooleanVar(value=False)
        self.modify_var = BooleanVar(value=False)
        ttk.Checkbutton(adv, text="日志脱敏显示（仅影响显示，不影响提交数据）",
                        variable=self.mask_var, command=self._on_mask_changed,
                        style="Card.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(adv, text="启动时逐项确认信息（等价于终端输入 m）",
                        variable=self.modify_var,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(6, 0))
        self.update_var = BooleanVar(value=True)
        ttk.Checkbutton(adv, text="启动时自动检查新版本（需联网访问 GitHub）",
                        variable=self.update_var,
                        command=self._on_update_check_changed,
                        style="Card.TCheckbutton").pack(anchor="w", pady=(6, 0))

        env = ttk.LabelFrame(parent, text="运行环境", padding=12)
        env.pack(fill=X, pady=(10, 0))
        system, arch = data_paths.platform_label()
        self.env_text = (
            "应用版本：%s %s\n"
            "操作系统：%s · 架构：%s\n"
            "Python  ：%s（%s）\n"
            "界面    ：tkinter/ttk %s（原生窗口，无需终端）\n"
            "数据目录：%s" % (__app_name__, __version__, system, arch,
                             sys.version.split()[0], sys.platform,
                             getattr(tk, "TkVersion", "?"),
                             data_paths.data_dir()))
        ttk.Label(env, text=self.env_text, style="Card.TLabel",
                  justify=LEFT).pack(anchor="w")

        about = ttk.LabelFrame(parent, text="说明与合规", padding=12)
        about.pack(fill=X, pady=(10, 0))
        ttk.Label(about, text=(
            "本工具沿用原有业务逻辑：动态读取表单字段与联动规则、只提交当前可见字段、"
            "按服务器时间校准、开放瞬间高频提交、重复提交保护。\n"
            "仅适用于未启用验证码的表单。请遵守目标平台服务条款与活动规则，"
            "仅用于本人合法报名，勿用于批量刷单或干扰服务。\n"
            "本项目为开源桌面客户端，与表单平台官方无关联。"),
            style="CardHint.TLabel", justify=LEFT, wraplength=600).pack(anchor="w")
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        self.settings_window = win

    def _show_settings(self):
        self.settings_window.deiconify()
        self.settings_window.lift()

    def _show_preview(self):
        self.preview_window.deiconify()
        self.preview_window.lift()

    # ==================== 事件循环 ====================
    def _poll(self):
        try:
            while True:
                kind, tid, payload = self.event_queue.get_nowait()
                if kind == "startup_update":
                    self._show_update_banner(payload)
                    continue
                self.manager.apply_event(kind, tid, payload)
                self._handle_event(kind, tid, payload)
        except queue.Empty:
            pass
        now = now_beijing()
        clock = now.strftime("%Y-%m-%d %H:%M:%S")
        if clock != self._last_clock:
            self.clock_var.set(format_beijing_time(now))
            self._last_clock = clock
            self._render_task_tabs()
            self._tick_countdown()
        if (self.theme_mode == "system" and
                time.monotonic() - self._last_theme_probe >= 2.0):
            self._last_theme_probe = time.monotonic()
            system_mode = detect_system_mode()
            if system_mode != self.system_mode:
                self.system_mode = system_mode
                self._apply_theme(persist=False)
        self.after(100, self._poll)

    def _handle_event(self, kind, tid, payload):
        if kind == "question":
            self._show_question(tid, payload)
            return
        if kind == "form_result":
            if tid == self.active_task:
                self._handle_form_result(payload)
            return
        if kind in ("tasks", "state", "finished"):
            self._render_task_tabs()
        if tid != self.active_task:
            return
        if kind == "log":
            self._append_log(payload)
        elif kind == "state":
            self._render_state()
        elif kind == "form":
            self.form = dict(payload)
            self._render_form_info()
            self._render_fields()
        elif kind == "preview":
            self._render_preview(payload)
        elif kind == "finished":
            self._render_state()
            self._toast("任务结束：%s（共尝试 %s 次）" %
                        (payload.get("phase", ""), payload.get("attempt", 0)),
                        "ok" if payload.get("success") else "warn")
        self._update_buttons()

    def _tick_countdown(self):
        t = self.manager.get(self.active_task)
        if not t or t.stats["state"] not in ("waiting", "starting", "preparing"):
            return
        open_time = t.stats.get("open_time") or ""
        if not open_time:
            return
        try:
            dt = datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S") \
                .replace(tzinfo=CST)
            remain = max(0.0, (dt - datetime.now(CST)).total_seconds())
            t.stats["countdown"] = remain
            self._render_state()
        except ValueError:
            pass

    def _toast(self, text, kind="info"):
        color = {"ok": PALETTE["green"], "err": PALETTE["red"],
                 "warn": PALETTE["amber"]}.get(kind, PALETTE["teal"])
        self.toast_accent.configure(bg=color)
        self.toast_label.configure(text=text)
        self.toast_win.place(relx=1.0, rely=1.0, anchor="se", x=-22, y=-22)
        self.toast_win.tkraise()
        self.update_idletasks()
        if self._toast_after:
            try:
                self.after_cancel(self._toast_after)
            except Exception:
                pass
        self._toast_after = self.after(3200, self.toast_win.place_forget)

    # ==================== 任务切换与刷新 ====================
    def _render_task_tabs(self):
        tasks = self.manager.list()
        sig = tuple((t["id"], t["name"]) for t in tasks)
        if sig != self._tab_sig:
            for child in self.task_buttons.winfo_children():
                child.destroy()
            self._task_buttons_map = {}
            for t in tasks:
                w = ttk.Frame(self.task_buttons, style="Card.TFrame")
                w.pack(side=LEFT, padx=3)
                main = ttk.Button(
                    w, command=lambda tid=t["id"]: self._switch_task(tid))
                main.pack(side=LEFT)
                state = ttk.Label(w, text="", style="CardHint.TLabel")
                state.pack(side=LEFT, padx=(4, 2))
                rf = ttk.Button(
                    w, text="↻", style="Refresh.TButton",
                    command=lambda tid=t["id"]: self._refresh_task(tid, True))
                rf.pack(side=LEFT)
                self._task_buttons_map[t["id"]] = (w, main, state, rf)
            self._tab_sig = sig
        for t in tasks:
            item = self._task_buttons_map.get(t["id"])
            if item is None:
                continue
            _w, main, state, _rf = item
            active = t["id"] == self.active_task
            try:
                main.configure(text=t["name"], style="TabActive.TButton"
                              if active else "Tab.TButton")
                state.configure(
                    text=("运行 PID %s" % t.get("pid")) if t["running"]
                    else (t.get("phase") or t.get("state") or "空闲"),
                    foreground=PALETTE["green"] if t["running"] else PALETTE["dim"])
            except tk.TclError:
                pass
        try:
            self.btn_task_add.configure(state="disabled" if len(tasks) >= MAX_TASKS
                                        else "normal")
            self.btn_task_close.configure(state="disabled" if len(tasks) <= 1
                                          else "normal")
        except tk.TclError:
            pass
        self.task_hint.configure(
            text="已开 %d/%d 个任务 · 每个任务独立进程、独立报名信息与抢票时间，"
                 "可同时运行；要分别设时间请勿勾选 --quick。" %
            (len(tasks), MAX_TASKS))
        self._update_buttons()

    def _refresh_task(self, tid, is_tab=False):
        """等价于原面板 refreshTask：可只刷新某个任务，不切换、不影响其它任务。"""
        item = self._task_buttons_map.get(tid)
        rf = item[3] if item else None
        if rf:
            old = rf.cget("text")

            def restore(button=rf, label=old):
                try:
                    if button.winfo_exists():
                        button.configure(text=label, state="normal")
                except tk.TclError:
                    pass  # 任务标签在刷新期间被重建，旧按钮已销毁

            try:
                rf.configure(text="…", state="disabled")
            except tk.TclError:
                pass
            self.after(450, restore)
        t = self.manager.get(tid)
        if not t:
            return
        self._render_task_tabs()
        if tid == self.active_task:
            self._render_state()
            self._replay_logs()
            self._toast("已刷新「%s」的状态与终端日志" % t.name, "ok")
        else:
            s = t.stats
            self._toast("已刷新「%s」：%s · %s · 尝试 %s 次" %
                        (t.name, s.get("phase") or "空闲",
                         "运行中" if t.running else "未运行", s.get("attempt", 0)),
                        "ok")

    def _refresh_all(self):
        self._refresh_task(self.active_task, False)

    def _update_buttons(self):
        t = self.manager.get(self.active_task)
        running = bool(t and t.running)
        try:
            self.btn_start.configure(state="disabled" if running else "normal")
            self.btn_dry.configure(state="disabled" if running else "normal")
            self.btn_stop.configure(state="normal" if running else "disabled")
        except tk.TclError:
            pass

    def _save_ui(self):
        self.task_ui[self.active_task] = {
            "link": self.link_var.get(), "quick": self.quick_var.get(),
            "dry": self.dry_var.get(), "auto_reply": self.auto_reply_var.get(),
            "modify": self.modify_var.get(),
            "time_mode": self.time_mode_var.get(),
            "manual_time": self.manual_time_var.get(),
            "lead": self.lead_var.get(), "interval": self.interval_var.get(),
            "timeout": self.timeout_var.get(),
            "profile_sel": self._selected_profile_id(),
            "form": json.loads(json.dumps(self.form, default=str)),
            "cfg": json.loads(json.dumps(self.cfg, default=str)),
        }

    def _apply_ui(self, u):
        self.link_var.set(u.get("link", ""))
        self.quick_var.set(bool(u.get("quick")))
        self.dry_var.set(bool(u.get("dry")))
        self.auto_reply_var.set(u.get("auto_reply", True))
        self.modify_var.set(bool(u.get("modify")))
        self._set_time_mode(u.get("time_mode", "1"))
        self.manual_time_var.set(u.get("manual_time", ""))
        self.lead_var.set(u.get("lead", "-6"))
        self.interval_var.set(u.get("interval", "0.05"))
        self.timeout_var.set(u.get("timeout", "40"))
        self.form = u.get("form", self.form)
        self.cfg = u.get("cfg", {})

    def _switch_task(self, tid):
        if tid == self.active_task:
            return
        self._save_ui()
        self.active_task = tid
        self._init_task(replay=True)
        self._toast("已切换到「%s」" % self.manager.get(tid).name)

    def _init_task(self, replay=False):
        t = self.manager.get(self.active_task)
        self.cfg = self.manager.read_config(t.id)
        u = self.task_ui.get(t.id)
        if u:
            self._apply_ui(u)
        else:
            self.link_var.set(t.cfg.get("link") or
                              str(self.cfg.get(CONFIG_LINK_KEY) or ""))
            self.quick_var.set(bool(t.cfg.get("quick")))
            self.dry_var.set(bool(t.cfg.get("dry")))
            self.auto_reply_var.set(t.cfg.get("auto_reply", True))
            self._set_time_mode(str(t.cfg.get("time_mode", "1")))
            self.manual_time_var.set(str(t.cfg.get("manual_time", "")))
            self.lead_var.set(str(t.cfg.get("lead", "-6")))
            self.interval_var.set(str(t.cfg.get("interval", "0.05")))
            self.timeout_var.set(str(t.cfg.get("timeout", "40")))
            self.form = dict(t.form)
        self._render_form_info()
        self._render_fields()
        self._load_profiles()
        if u and u.get("profile_sel"):
            self._select_profile(u["profile_sel"])
        if replay:
            self._replay_logs()
        if self.link_var.get().strip() and not self.form.get("ok"):
            self.after(200, lambda: self._load_form(True))
        self._render_task_tabs()
        self._render_state()

    def _replay_logs(self):
        t = self.manager.get(self.active_task)
        self.log_view.clear()
        for item in t.logs[-1200:]:
            self._append_log(item)

    def _new_task(self):
        r = self.manager.create("")
        if not r["ok"]:
            self._toast(r["error"], "err")
            return
        self._switch_task(r["id"])
        self._toast("已创建「%s」：可为它选另一位报名人并单独设时间" %
                    self.manager.get(r["id"]).name, "ok")

    def _close_task(self):
        if self.active_task == "t1":
            self._toast("主任务不能关闭", "err")
            return
        if not messagebox.askyesno("关闭任务", "确定关闭当前任务？\n"
                                  "（必须先停止该任务；其目录与配置会保留，不会删除）"):
            return
        r = self.manager.close(self.active_task)
        if not r["ok"]:
            self._toast(r["error"], "err")
            return
        self.task_ui.pop(self.active_task, None)
        self.active_task = "t1"
        self._init_task(replay=True)
        self._toast("已关闭任务", "ok")

    def _rename_task(self):
        t = self.manager.get(self.active_task)
        name = simpledialog.askstring("重命名任务", "任务名称：",
                                      initialvalue=t.name, parent=self)
        if name and name.strip():
            self.manager.rename(t.id, name.strip())
            self._render_task_tabs()

    def _stop_all(self):
        self.manager.stop_all()
        self._toast("已向所有运行中的任务发送停止信号", "warn")

    # ==================== 运行状态 ====================
    def _render_state(self):
        t = self.manager.get(self.active_task)
        s = t.stats
        color_map = {"success": PALETTE["green"], "failed": PALETTE["red"],
                     "waiting": PALETTE["amber"], "rushing": PALETTE["blue"]}
        self.cards["state"].set(s["phase"] or "空闲",
                                "PID %s · 运行 %.0fs" % (s.get("pid") or "—",
                                                       s.get("uptime") or 0)
                                if t.running else "尚未启动脚本",
                                color_map.get(s["state"], PALETTE["muted"]))
        cd = s.get("countdown")
        if cd is None or cd == "":
            text = "--"
        elif float(cd) < 0:
            text = "已开放 %.1fs" % abs(float(cd))
        else:
            v = float(cd)
            h, m, sec = int(v // 3600), int((v % 3600) // 60), int(v % 60)
            text = (("%02d:" % h) if h else "") + "%02d:%02d" % (m, sec)
        self.cards["count"].set(text, ("开放 " + s["open_time"])
                                if s.get("open_time") else "开放时间未知",
                                PALETTE["amber"])
        self.cards["attempt"].set(s.get("attempt", 0),
                                  "待提交字段 %s 项" % s.get("submit_fields", 0),
                                  PALETTE["blue"])
        off = s.get("offset")
        self.cards["offset"].set("--" if off is None else "%+.3fs" % float(off),
                                 "线程运行中" if t.running else
                                 ("退出码 %s" % t.exit_code if t.exit_code is not None
                                  else "进程未启动"), PALETTE["teal"])
        self.cards["last"].set(s.get("last") or "--",
                               "自动应答 %s 次" % s.get("replies", 0),
                               color_map.get(s["state"], PALETTE["muted"]))
        self.wait_label.configure(
            text="  脚本等待输入  " if s.get("waiting") else "")
        self._update_buttons()

    def _render_form_info(self):
        f = self.form
        self.form_labels["name"].configure(text=f.get("name") or "未读取")
        self.form_labels["status"].configure(text=f.get("status") or "--")
        self.form_labels["open"].configure(text=f.get("open_time") or "--")
        self.form_labels["captcha"].configure(
            text=("启用（纯接口不可用）" if f.get("captcha") else "未启用（可直接提交）")
            if f.get("ok") else "--")
        self.form_labels["fields"].configure(
            text=("%d 个（含联动字段）" % len(f.get("fields") or []))
            if f.get("ok") else "--")
        self._show_warn(
            "该表单启用了验证码，原脚本会直接退出，需改用浏览器方案。"
            if f.get("captcha") else "")

    def _show_warn(self, text):
        """等价于原面板 warnbox 的 display:block / none。"""
        if text:
            try:
                self.warn_label.pack_forget()
            except tk.TclError:
                pass
            self.warn_label.configure(text=text)
            self.warn_label.pack(fill=X, pady=(8, 0),
                                 before=self._warn_anchor)
        else:
            self.warn_label.configure(text="")
            try:
                self.warn_label.pack_forget()
            except tk.TclError:
                pass

    def _append_log(self, item):
        self.log_view.append(item.get("ts", ""), item.get("level", "info"),
                             item.get("text", ""), mask=self.mask_var.get())
        if self.autoscroll_var.get():
            self.log_view.see(END)

    def _render_preview(self, payload):
        self.preview_tree.delete(*self.preview_tree.get_children())
        for label, shown, value in payload.get("rows", []):
            self.preview_tree.insert("", END, values=(label, shown,
                                                      json.dumps(value, ensure_ascii=False)
                                                      if isinstance(value, (list, dict))
                                                      else str(value)))

    # ==================== 表单 / 字段 ====================
    def _load_form(self, silent=False):
        link = self.link_var.get().strip()
        if not link:
            if not silent:
                self._toast("请先填写表单链接", "err")
            return
        self._toast("正在读取表单结构…")

        def worker():
            try:
                result = self.manager.load_form(self.active_task, link)
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            result = dict(result)
            result["silent"] = bool(silent)
            self.event_queue.put(("form_result", self.active_task, result))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_form_result(self, result):
        if result.get("ok"):
            t = self.manager.get(self.active_task)
            self.form = dict(t.form)
            self._render_form_info()
            self._render_fields()
            self._toast("已读取表单：%s" % result.get("name", ""), "ok")
        else:
            self.form = {"ok": False, "fields": [], "rules": {}, "name": "",
                         "status": "", "captcha": False, "open_time": ""}
            self._show_warn(str(result.get("error", "")) +
                            "（已切换为离线纯文本编辑，原脚本启动时仍会自行读取结构）")
            self._render_fields()
            if not result.get("silent"):
                self._toast("读取失败：" + str(result.get("error", "")), "err")

    def _render_fields(self):
        for child in self.fields_box.winfo_children():
            child.destroy()
        self.field_widgets = {}
        self.field_rows = {}
        fields = self.form.get("fields") or []
        if fields:
            self.field_defs = fields
            self.field_tag.configure(text="在线结构 · %d 字段" % len(fields))
        else:
            self.field_defs = [{"api": "cfg:" + k, "label": k,
                                "typename": "NameField", "required": True,
                                "multi": False, "choices": []}
                               for k in self.cfg if k != CONFIG_LINK_KEY]
            self.field_tag.configure(text="离线模式 · 纯文本字段")
        if not self.field_defs:
            ttk.Label(self.fields_box,
                      text="暂无字段，请先在上方「读取表单」。",
                      style="CardHint.TLabel").grid(row=0, column=0, sticky="w")
            self.left_scroll.bind_wheel_tree()
            return
        for i, f in enumerate(self.field_defs):
            row = ttk.Frame(self.fields_box, style="Card.TFrame", padding=(6, 5))
            row.grid(row=i, column=0, sticky="ew", pady=2)
            ttk.Label(row, text=f["label"] + ("  *" if f["required"] else ""),
                      style="Card.TLabel").grid(row=0, column=0, sticky="w")
            choices = f.get("choices") or []
            var = StringVar()
            if choices and not f["multi"]:
                w = ttk.Combobox(row, textvariable=var, state="normal",
                                 values=[n for _v, n in choices])
                w.bind("<<ComboboxSelected>>",
                       lambda _e: self._refresh_visibility())
            else:
                w = ttk.Entry(row, textvariable=var)
                w.bind("<KeyRelease>", lambda _e: self._refresh_visibility())
            w.grid(row=1, column=0, sticky="ew", pady=(3, 0))
            row.columnconfigure(0, weight=1)
            if choices:
                ttk.Label(row, text="可选项：" + " / ".join(n for _v, n in choices),
                          style="CardHint.TLabel", wraplength=380) \
                    .grid(row=2, column=0, sticky="w", pady=(2, 0))
            self.field_widgets[f["api"]] = {"widget": w, "field": f, "var": var}
            self.field_rows[f["api"]] = row
        # 动态字段控件是新建的，需要重新挂滚动支持
        self.left_scroll.bind_wheel_tree()
        self._load_values()
        self._refresh_visibility()

    def _codes(self):
        out = {}
        for api, item in self.field_widgets.items():
            f = item["field"]
            choices = f.get("choices") or []
            if not choices:
                continue
            raw = item["var"].get().strip()
            name_map = {n: v for v, n in choices}
            if f["multi"]:
                codes = [name_map[x.strip()] for x in raw.replace("，", ",").split(",")
                         if x.strip() in name_map]
                if codes:
                    out[api] = codes
            elif raw in name_map:
                out[api] = name_map[raw]
        return out

    def _refresh_visibility(self):
        codes = self._codes()
        rules = self.form.get("rules") or {}
        for api, row in self.field_rows.items():
            f = next((x for x in self.field_defs if x["api"] == api), None)
            if f is None:
                continue
            if is_visible(f, rules, codes):
                row.grid()
            else:
                row.grid_remove()

    def _load_values(self):
        for api, item in self.field_widgets.items():
            v = self.cfg.get(item["field"]["label"])
            if v is None:
                continue
            item["var"].set("，".join(str(x) for x in v)
                            if isinstance(v, list) else str(v))
        self._refresh_visibility()

    def _collect_values(self):
        codes = self._codes()
        rules = self.form.get("rules") or {}
        values = {}
        for api, item in self.field_widgets.items():
            f = item["field"]
            if not is_visible(f, rules, codes):
                continue
            raw = item["var"].get().strip()
            if not raw:
                continue
            if f["multi"]:
                values[f["label"]] = [x.strip() for x in
                                      raw.replace("，", ",").split(",")
                                      if x.strip()]
            else:
                values[f["label"]] = raw
        return values

    def _save_config(self, silent=False):
        r = self.manager.write_config(self.active_task,
                                      self.link_var.get().strip(),
                                      self._collect_values())
        if r["ok"]:
            self.cfg = r["cfg"]
            self.manager.get(self.active_task).cfg["link"] = self.link_var.get().strip()
            if not silent:
                self._toast("报名信息已保存并备份", "ok")
        elif not silent:
            self._toast("保存失败：%s" % r.get("error"), "err")
        return r["ok"]

    def _reload_config(self):
        self.cfg = self.manager.read_config(self.active_task)
        self._load_values()
        self._toast("已重新载入报名信息.json")

    def _preview(self):
        r = self.manager.preview_attributes(self.active_task, self.form)
        if not r["ok"]:
            self._toast("预览失败：" + r["error"], "err")
            return
        self._render_preview(r)
        self._show_preview()
        self._toast("已按联动规则生成 %d 项提交数据（未发送）" %
                    len(r["attributes"]), "ok")

    # ==================== 启动 / 停止 ====================
    def _start(self, dry):
        if not self._save_config(True):
            self._toast("配置保存失败，已取消启动", "err")
            return
        dry = bool(dry) or self.dry_var.get()
        if self.form.get("ok"):
            check = self.manager.preview_attributes(self.active_task, self.form)
            if not check["ok"]:
                self._toast("报名信息有误，已取消启动：" + check["error"], "err")
                return
            self._render_preview(check)
        payload = {
            "link": self.link_var.get().strip(),
            "quick": self.quick_var.get(), "dry": dry,
            "time_mode": self.time_mode_var.get(),
            "manual_time": self.manual_time_var.get().strip(),
            "lead": self.lead_var.get().strip(),
            "interval": self.interval_var.get().strip(),
            "timeout": self.timeout_var.get().strip(),
            "auto_reply": self.auto_reply_var.get(),
            "modify": self.modify_var.get(),
        }
        r = self.manager.start(self.active_task, payload)
        if r["ok"]:
            self._toast("演练已启动（不会提交）" if dry else "脚本已启动", "ok")
            self.log_view.focus_set()
        else:
            self._toast("启动失败：" + r["error"], "err")
        self._update_buttons()

    def _stop(self):
        r = self.manager.stop(self.active_task)
        self._toast("已停止脚本" if r["ok"] else r["error"],
                    "warn" if r["ok"] else "err")
        self._update_buttons()

    # ==================== 多人档案 ====================
    def _load_profiles(self):
        self.profiles_lib = self.manager.profiles.load()
        self._render_profiles()

    def _render_profiles(self, prefer=None):
        self._profiles_loading = True
        cur = prefer if prefer is not None else self._selected_profile_id()
        profiles = self.profiles_lib["profiles"]
        self.profile_ids = [p["id"] for p in profiles]
        labels = ["%s（%d 项）" % (p["name"], len(p.get("values") or {}))
                  for p in profiles]
        self.profile_sel.configure(values=labels)
        ids = self.profile_ids
        target = cur if cur in ids else (
            self.profiles_lib["active"] if self.profiles_lib["active"] in ids
            else (ids[0] if ids else None))
        if target:
            self.profile_sel.current(ids.index(target))
        else:
            self.profile_sel.set("")
        self._profiles_loading = False
        n = len(ids)
        for b in self.profile_btns.values():
            try:
                b.configure(state="normal" if n else "disabled")
            except tk.TclError:
                pass
        cur_prof = self.manager.profiles.get(target) if target else None
        self.profile_hint.configure(text=(
            "当前档案：%s · 共 %d 套。选择下拉即自动填入全部字段并写入"
            "「报名信息.json」；手动改动后点「更新」才会同步回档案。" %
            (cur_prof["name"] if cur_prof else "—", n))
            if n else "还没有档案：填好下方信息，输入名称后点「存为新档案」即可。")

    def _selected_profile_id(self):
        idx = self.profile_sel.current()
        return self.profile_ids[idx] if 0 <= idx < len(self.profile_ids) else ""

    def _select_profile(self, pid):
        if pid in self.profile_ids:
            self.profile_sel.current(self.profile_ids.index(pid))

    def _on_profile_select(self, _event):
        if not self._profiles_loading:
            self._apply_profile()

    def _apply_profile(self):
        pid = self._selected_profile_id()
        if not pid:
            self._toast("请先选择一套档案", "err")
            return
        t = self.manager.get(self.active_task)
        r = self.manager.profiles.apply(pid, t.config_store,
                                        self.link_var.get().strip())
        if not r["ok"]:
            self._toast("应用失败：" + r["error"], "err")
            return
        self.cfg = r["cfg"]
        self.manager.bind_profile(t.id, pid)
        self.profiles_lib["active"] = r["active"]
        if str(self.cfg.get(CONFIG_LINK_KEY) or ""):
            self.link_var.set(str(self.cfg[CONFIG_LINK_KEY]))
        self._load_values()
        self._render_profiles(pid)
        missing = []
        for api, item in self.field_widgets.items():
            v = self.cfg.get(item["field"]["label"])
            if v in (None, "") or not item["var"].get().strip():
                if v not in (None, ""):
                    missing.append(item["field"]["label"])
        self._toast("已切换到「%s」，%d 项信息已填入并保存%s" %
                    (r["profile"]["name"], len(r["cfg"]) - 1,
                     "；%d 项未匹配当前表单选项：%s" %
                     (len(missing), "、".join(missing)) if missing else ""),
                    "err" if missing else "ok")

    def _add_profile(self):
        values = self._collect_values()
        if not values:
            self._toast("当前没有可保存的报名信息", "err")
            return
        name = self.profile_name_var.get().strip() or \
            str(values.get("姓名") or "") or \
            ("档案 %d" % (len(self.profiles_lib["profiles"]) + 1))
        r = self.manager.profiles.add(name, values)
        self.profile_name_var.set("")
        self._load_profiles()
        self._render_profiles(r.get("active"))
        self._toast("已保存档案「%s」（%d 项）" % (name, len(values)), "ok")

    def _update_profile(self):
        pid = self._selected_profile_id()
        if not pid:
            self._toast("请先选择一套档案", "err")
            return
        values = self._collect_values()
        if not values and not messagebox.askyesno(
                "更新档案", "当前字段全为空，确定要清空这套档案吗？"):
            return
        self.manager.profiles.update(pid, values)
        self._save_config(True)
        self._load_profiles()
        self._render_profiles(pid)
        self._toast("档案「%s」已更新（%d 项）" %
                    (self.manager.profiles.get(pid)["name"], len(values)), "ok")

    def _rename_profile(self):
        pid = self._selected_profile_id()
        prof = self.manager.profiles.get(pid) if pid else None
        if not prof:
            self._toast("请先选择一套档案", "err")
            return
        name = simpledialog.askstring("重命名", "输入新的档案名称",
                                      initialvalue=prof["name"], parent=self)
        if name and name.strip() and name.strip() != prof["name"]:
            self.manager.profiles.rename(pid, name.strip())
            self._load_profiles()
            self._render_profiles(pid)

    def _delete_profile(self):
        pid = self._selected_profile_id()
        prof = self.manager.profiles.get(pid) if pid else None
        if not prof:
            self._toast("请先选择一套档案", "err")
            return
        if not messagebox.askyesno("删除档案",
                                   "确定删除档案「%s」？\n（只从档案库移除，"
                                   "不会改动当前 报名信息.json）" % prof["name"]):
            return
        self.manager.profiles.delete(pid)
        self._load_profiles()
        self._toast("已删除档案「%s」" % prof["name"], "ok")

    def _export_profiles(self):
        path = filedialog.asksaveasfilename(
            title="导出档案库", defaultextension=".json",
            initialfile="profiles-export.json",
            filetypes=[("JSON 文件", "*.json")])
        if not path:
            return
        self.manager.profiles.export(path)
        self._toast("档案已导出（请妥善保管，文件含个人信息）", "warn")

    def _import_profiles(self):
        path = filedialog.askopenfilename(
            title="导入档案文件", filetypes=[("JSON 文件", "*.json")])
        if not path:
            return
        try:
            r = self.manager.profiles.import_file(path, merge=True)
        except Exception as e:
            self._toast("导入失败：%s" % e, "err")
            return
        if not r["ok"]:
            self._toast("导入失败：%s" % r.get("error"), "err")
            return
        self._load_profiles()
        self._toast("档案已导入（合并到现有档案库）", "ok")

    def _import_legacy(self):
        folder = filedialog.askdirectory(title="选择旧版脚本所在文件夹")
        if not folder:
            return
        root = Path(folder)
        count = 0
        try:
            legacy_cfg = root / "报名信息.json"
            if legacy_cfg.exists():
                with open(legacy_cfg, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                t = self.manager.get(self.active_task)
                t.config_store.replace_from(data)
                self.cfg = t.config_store.read()
                count += 1
            legacy_profiles = root / "个人档案.json"
            if legacy_profiles.exists():
                self.manager.profiles.import_file(legacy_profiles, merge=True)
                count += 1
            multi = root / "多开任务"
            if multi.is_dir():
                for sub in sorted(multi.iterdir()):
                    f = sub / "报名信息.json"
                    if not f.exists():
                        continue
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    values = {k: v for k, v in data.items() if k != CONFIG_LINK_KEY}
                    name = str(values.get("姓名") or sub.name)
                    self.manager.profiles.add(name, values)
                    count += 1
        except Exception as e:
            self._toast("导入失败：%s" % e, "err")
            return
        self._load_profiles()
        self._reload_config()
        self._toast("已从旧版文件夹导入 %d 份数据（仅写入本机数据目录）" % count, "ok")

    # ==================== 日志 / 应答 ====================
    def _clear_logs(self):
        self.manager.clear_logs(self.active_task)
        self.log_view.clear()
        self._toast("已清空当前任务的日志显示")

    def _export_logs(self):
        path = filedialog.asksaveasfilename(
            title="导出运行日志", defaultextension=".txt",
            initialfile="报名脚本运行日志.txt", filetypes=[("文本文件", "*.txt")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(self.log_view.text())
        self._toast("日志已导出（可能包含报名信息，请妥善保管）", "warn")

    def _send_entry(self):
        text = self.stdin_var.get().strip()
        self.stdin_var.set("")
        self._send_quick(text)

    def _send_quick(self, value):
        r = self.manager.send_input(self.active_task, str(value))
        if not r["ok"]:
            self._toast(r["error"], "err")

    def _show_question(self, tid, req):
        if self._question_dialog is not None:
            return
        t = self.manager.get(tid)
        provider = t.provider if t else None

        def answer(value):
            if provider:
                provider.answer(req["id"], value)
            try:
                self._question_dialog.grab_release()
                self._question_dialog.destroy()
            except Exception:
                pass
            self._question_dialog = None
            self._question_req = None

        dlg = tk.Toplevel(self)
        dlg.title("需要补充信息 · %s" % t.name)
        dlg.transient(self)
        dlg.geometry("420x190")
        dlg.configure(bg=PALETTE["bg"])
        ttk.Label(dlg, text="字段【%s】%s" %
                  (req["label"], "（必填）" if req.get("required") else ""),
                  style="Title.TLabel").pack(anchor="w", padx=16, pady=(14, 6))
        choices = req.get("choices") or []
        names = [n for _v, n in choices]
        name_to_code = {n: v for v, n in choices}
        var = StringVar()
        if req["kind"] == "single" and names:
            ttk.Label(dlg, text="请选择一个选项：",
                      style="Muted.TLabel").pack(anchor="w", padx=16)
            cb = ttk.Combobox(dlg, textvariable=var, values=names,
                              state="readonly")
            cb.pack(fill=X, padx=16, pady=6)
            cb.current(0)
            var.set(names[0])
        else:
            ttk.Label(dlg, text=("多个值用逗号分隔；可选项：" + " / ".join(names[:12]))
                      if names else "请输入内容：", style="Hint.TLabel",
                      wraplength=380).pack(anchor="w", padx=16)
            e = ttk.Entry(dlg, textvariable=var)
            e.pack(fill=X, padx=16, pady=6)
            default = req.get("default")
            code_to_name = {v: n for v, n in choices}
            if default:
                if isinstance(default, list):
                    var.set("，".join(code_to_name.get(str(x), str(x))
                                     for x in default))
                else:
                    var.set(code_to_name.get(str(default), str(default)))
            e.focus_set()
        bar = ttk.Frame(dlg)
        bar.pack(fill=X, padx=16, pady=12)

        def ok():
            if req["kind"] == "single" and names:
                answer(name_to_code.get(var.get(), ""))
            elif req["kind"] == "multi":
                answer([name_to_code[x.strip()] for x in
                        var.get().replace("，", ",").split(",")
                        if x.strip() in name_to_code])
            else:
                answer(var.get())

        ttk.Button(bar, text="确定", style="Primary.TButton",
                   command=ok).pack(side=RIGHT, padx=4)
        ttk.Button(bar, text="沿用原值",
                   command=lambda: answer(req.get("default"))).pack(side=RIGHT)
        dlg.protocol("WM_DELETE_WINDOW",
                     lambda: answer(req.get("default")))
        dlg.grab_set()
        self._question_dialog = dlg
        self._question_req = req
        self._toast("「%s」有缺项等待补充，请在弹窗中填写" % t.name, "warn")

    # ==================== 杂项 ====================
    def _apply_theme(self, persist=True):
        old_palette = dict(PALETTE)
        self._resolved_theme = apply_theme(self, self.theme_mode,
                                           self.system_mode)
        refresh_tree(self, old_palette, PALETTE)
        if hasattr(self, "log_view"):
            self.log_view.retheme()
            self._render_state()
        for window_name in ("preview_window", "settings_window", "update_window"):
            window = getattr(self, window_name, None)
            try:
                if window is not None and window.winfo_exists():
                    refresh_tree(window, old_palette, PALETTE)
                    retheme = getattr(window, "retheme", None)
                    if retheme:
                        retheme()
            except tk.TclError:
                pass
        self._sync_header_theme_widgets()
        if persist:
            settings = self.manager.settings.load()
            settings["theme_mode"] = self.theme_mode
            self.manager.settings.save(settings)

    def _on_theme_changed(self):
        self.theme_mode = normalize_mode(self.theme_mode_var.get())
        if self.theme_mode == "system":
            self.system_mode = detect_system_mode()
        self._apply_theme()
        self._sync_header_theme_widgets()
        self._toast("界面主题已切换为%s" % {
            "dark": "黑色", "light": "白色", "system": "跟随系统"
        }[self.theme_mode])

    def _set_header_theme(self, mode):
        self.theme_mode_var.set(mode)
        self._on_theme_changed()

    def _sync_header_theme_widgets(self):
        for value, button in getattr(self, "header_theme_widgets", {}).items():
            button.configure(style=("SegmentActive.TButton" if value == self.theme_mode
                                     else "Segment.TButton"))

    def _on_mask_changed(self):
        s = self.manager.settings.load()
        s["mask_logs"] = self.mask_var.get()
        self.manager.settings.save(s)
        self._replay_logs()
        self._toast("日志脱敏显示已" + ("开启" if self.mask_var.get() else "关闭") +
                    "（仅影响显示，不影响提交数据）")

    def _open_data_dir(self):
        path = str(data_paths.data_dir())
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self._toast("无法打开目录：%s" % e, "err")

    def _show_guide(self):
        messagebox.showinfo("使用说明", (
            "1) 在左侧「运行配置」粘贴本次表单链接并点「读取表单」；\n"
            "2) 在左侧「报名信息」填写或切换档案，点「保存信息」；\n"
            "3) 确认开放时间来源与冲刺参数，先用「演练自检」验证；\n"
            "4) 点「启动脚本」，在右侧「实时终端」观察等待、冲刺与结果；\n"
            "5) 多人报名用顶部「+ 新建任务」，每个任务独立配置与时间，最多 8 个。"))

    def _show_privacy(self):
        messagebox.showinfo("隐私与数据安全", (
            "· 仓库与发布包不含任何真实个人信息、活动链接或日志文件；\n"
            "· 所有档案、报名信息、日志导出均只写入本机用户数据目录；\n"
            "· 可通过「文件 → 导出档案」自行备份，导入导出由用户显式触发；\n"
            "· 可在「帮助 → 设置与关于」勾选「日志脱敏显示」隐藏手机号与长数字；\n"
            "· 详情见 docs/PRIVACY.md。"))

    # -------------------- 应用内检查更新 --------------------
    def _show_update(self):
        """「帮助 → 检查更新与升级…」：独立弹窗，主界面布局与功能保持不变。"""
        try:
            from .update_dialog import UpdateDialog
            win = getattr(self, "update_window", None)
            if win is not None and win.winfo_exists():
                win.show()
            else:
                self.update_window = UpdateDialog(self)
        except Exception as e:
            self._toast("无法打开更新窗口：%s" % e, "err")

    def _on_update_check_changed(self):
        s = self.manager.settings.load()
        s["check_update_on_startup"] = self.update_var.get()
        self.manager.settings.save(s)
        self._toast("启动时自动检查更新已" +
                    ("开启" if self.update_var.get() else "关闭"))

    def _auto_check_update(self):
        """后台检查更新，由主线程消费结果。"""
        events = self.event_queue

        def work():
            try:
                from ..update import service
                events.put(("startup_update", None, service.check_for_update()))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _show_update_banner(self, result):
        if not result.ok or result.offline or not result.update_available:
            return
        try:
            if normalize_version(result.tag) != result.latest_version:
                return
        except ValueError:
            return
        url = REPO_URL + "/releases/tag/" + quote(result.tag, safe="")
        self.update_banner.configure(
            text="发现新版本 v%s · 打开 GitHub 发布页" % result.latest_version,
            command=lambda: webbrowser.open_new_tab(url))
        self.update_banner.pack(after=self.header, fill=X, padx=20, pady=(0, 10))

    def _about(self):
        messagebox.showinfo("关于", "%s · 桌面版 v%s\n\n%s" %
                            (__app_name__, __version__, self.env_text))

    def close(self):
        try:
            self.manager.stop_all()
            self._save_ui()
        except Exception:
            pass
        self.destroy()
