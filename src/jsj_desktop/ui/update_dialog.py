# -*- coding: utf-8 -*-
"""「帮助 → 检查更新与升级…」弹窗（1.2.0 新增，不占主界面）。

沿用主窗口同一套深色主题；网络与安装都在后台线程执行，Tk 控件只由主线程
通过 queue + after() 更新。任何失败都用 messagebox 明确提示原因与处理建议，
并保持当前版本与报名数据不变。
"""
import queue
import threading
import tkinter as tk
from tkinter import BOTH, LEFT, RIGHT, X, Y, StringVar, messagebox, ttk

from .. import __version__
from ..update import service
from ..update.errors import UpdateError
from .theme import PALETTE, font_family


class UpdateDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("检查更新与升级")
        self.geometry("640x580")
        self.minsize(600, 520)
        self.configure(bg=PALETTE["bg"])
        self.resizable(True, True)
        self.transient(parent)

        self.events = queue.Queue()
        self.busy = False
        self.check = None
        self._alive = True

        self.cur_var = StringVar(value=__version__)
        self.latest_var = StringVar(value="尚未检查")
        self.state_var = StringVar(value="尚未检查更新")
        self.platform_var = StringVar(value="—")
        self.channel_var = StringVar(value="—")
        self.progress_var = StringVar(value="等待操作")
        self.progress = None

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._hide)
        self.after(80, self._drain)
        self.after(250, self.start_check)

    # -------------------- 界面 --------------------
    def _build(self):
        head = ttk.Frame(self, padding=(16, 14, 16, 8))
        head.pack(fill=X)
        ttk.Label(head, text="检查更新与升级", style="Title.TLabel").pack(anchor="w")
        ttk.Label(head, text="仅在执行检查/升级时访问 GitHub；下载包会校验 SHA256，"
                  "不会上传任何报名信息。", style="Muted.TLabel") \
            .pack(anchor="w", pady=(4, 0))

        grid = ttk.LabelFrame(self, text="版本信息", padding=12)
        grid.pack(fill=X, padx=16, pady=(4, 8))
        rows = (("当前版本", self.cur_var), ("最新版本", self.latest_var),
                ("更新状态", self.state_var), ("适用平台", self.platform_var),
                ("更新通道", self.channel_var))
        for i, (key, var) in enumerate(rows):
            ttk.Label(grid, text=key, style="CardKey.TLabel", width=12) \
                .grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(grid, textvariable=var, style="Card.TLabel",
                      wraplength=440, justify=LEFT) \
                .grid(row=i, column=1, sticky="w", pady=2)
        grid.columnconfigure(1, weight=1)

        note_box = ttk.LabelFrame(self, text="版本说明", padding=8)
        note_box.pack(fill=BOTH, expand=True, padx=16, pady=(0, 8))
        self.notes = tk.Text(note_box, height=8, wrap="word",
                             bg=PALETTE["surface2"], fg=PALETTE["text"],
                             insertbackground=PALETTE["text"],
                             font=(font_family(), 10), relief="flat",
                             padx=8, pady=6)
        sb = ttk.Scrollbar(note_box, command=self.notes.yview)
        self.notes.configure(yscrollcommand=sb.set)
        sb.pack(side=RIGHT, fill=Y)
        self.notes.pack(side=LEFT, fill=BOTH, expand=True)

        prog = ttk.Frame(self, padding=(16, 0, 16, 8))
        prog.pack(fill=X)
        self.bar = ttk.Progressbar(prog, mode="determinate", maximum=100)
        self.bar.pack(fill=X)
        ttk.Label(prog, textvariable=self.progress_var, style="Muted.TLabel") \
            .pack(anchor="w", pady=(4, 0))

        bar = ttk.Frame(self, padding=(16, 0, 16, 14))
        bar.pack(fill=X)
        self.check_btn = ttk.Button(bar, text="检查更新",
                                    command=self.start_check)
        self.check_btn.pack(side=LEFT)
        self.update_btn = ttk.Button(bar, text="立即更新",
                                     style="Primary.TButton",
                                     command=self.start_update, state="disabled")
        self.update_btn.pack(side=LEFT, padx=8)
        self.copy_btn = ttk.Button(bar, text="复制下载链接",
                                   command=self.copy_link)
        self.copy_btn.pack(side=LEFT)
        ttk.Button(bar, text="关闭", command=self._hide).pack(side=RIGHT)

    # -------------------- 线程与事件 --------------------
    def _drain(self):
        if not self._alive:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "checked":
                    self._on_checked(payload)
                elif kind == "progress":
                    stage, pct, text = payload
                    self.bar["value"] = pct
                    self.progress_var.set(text)
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "failed":
                    self._on_failed(payload)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _set_busy(self, value):
        self.busy = value
        state = "disabled" if value else "normal"
        self.check_btn.configure(state=state)
        self.update_btn.configure(state=state if self.check and
                                  self.check.can_update else "disabled")
        self.copy_btn.configure(state="normal" if not value else "disabled")

    def start_check(self):
        if self.busy:
            return
        self._set_busy(True)
        self.bar["value"] = 0
        self.progress_var.set("正在检查最新版本…")
        self.state_var.set("正在检查…")

        def work():
            try:
                self.events.put(("checked", service.check_for_update()))
            except Exception as e:  # noqa: BLE001
                self.events.put(("failed", UpdateError(
                    "检查更新时出现未预期错误：%s" % e, cause=e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_checked(self, result):
        self.check = result
        self.latest_var.set(result.latest_version or "获取失败")
        self.platform_var.set(result.target or "—")
        self.channel_var.set(
            "%s%s" % (result.source or "不可用",
                      "（离线兜底）" if result.offline else ""))
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", result.notes or "该版本未提供更新说明。")
        self.notes.configure(state="disabled")
        self.bar["value"] = 100 if result.ok else 0
        self.progress_var.set(result.reason)
        self.state_var.set(result.reason)
        self.cur_var.set(result.current_version)

        if not result.ok:
            self._set_busy(False)
            self._toast("检查更新失败", "err")
            messagebox.showerror("检查更新失败", result.reason, parent=self)
            return
        if result.update_available and result.can_update:
            self.update_btn.configure(text="立即更新到 v%s" % result.latest_version)
        elif result.update_available:
            self.update_btn.configure(text="暂不可自动升级")
        else:
            self.update_btn.configure(text="已是最新版本")
        self._set_busy(False)
        if result.channel_errors:
            self.notes.configure(state="normal")
            self.notes.insert("end", "\n\n部分更新通道不可用：\n· " +
                              "\n· ".join(result.channel_errors[:4]))
            self.notes.configure(state="disabled")
        legacy = self._legacy_hint()
        if legacy:
            self.notes.configure(state="normal")
            self.notes.insert("end", "\n\n" + legacy)
            self.notes.configure(state="disabled")

    def _legacy_hint(self):
        try:
            from ..update.installer import find_legacy_installations
            found = find_legacy_installations()
        except Exception:
            return ""
        if not found:
            return ""
        return ("检测到本机仍有旧版本安装：\n· " +
                "\n· ".join("%s（%s）" % (x["path"], x["version"])
                            for x in found[:3]) +
                "\n升级不会删除这些文件；确认新版可用后可自行清理。")

    def start_update(self):
        if self.busy or not self.check or not self.check.can_update:
            return
        try:
            running = [t for t in self.parent.manager.list() if t.get("running")]
        except Exception:
            running = []
        if running:
            messagebox.showerror(
                "更新失败",
                "还有 %d 个任务正在运行。请先点「停止」结束全部任务，再执行升级；"
                "本次未做任何改动。" % len(running), parent=self)
            return
        ok = messagebox.askyesno(
            "确认升级",
            "即将下载并安装 v%s。\n\n"
            "· 当前版本会先备份，失败自动恢复；\n"
            "· 报名信息、档案与任务配置不会被修改；\n"
            "· 安装完成后程序会自动退出并启动新版本。\n\n继续？"
            % self.check.latest_version, parent=self)
        if not ok:
            return
        self._set_busy(True)
        self.bar["value"] = 0
        self.state_var.set("正在升级…")

        def progress(stage, pct, text):
            self.events.put(("progress", (stage, pct, text)))

        def work():
            try:
                result = service.apply_update(check=self.check,
                                              progress=progress,
                                              relaunch=True)
                self.events.put(("done", result))
            except UpdateError as e:
                self.events.put(("failed", e))
            except Exception as e:  # noqa: BLE001
                self.events.put(("failed", UpdateError(
                    "升级过程中出现未预期错误：%s" % e,
                    code="unexpected", hint="当前版本未改动，请重试或手动下载。",
                    cause=e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, result):
        self._set_busy(False)
        self.bar["value"] = 100
        self.state_var.set("升级完成")
        self.progress_var.set(result["message"])
        self._toast("已升级到 v%s" % result["latest_version"], "ok")
        messagebox.showinfo(
            "升级完成",
            "%s\n\n目标版本：v%s\n校验来源：%s\n安装位置：%s\n%s"
            % (result["message"], result["latest_version"],
               result.get("checksum_source", "-"),
               result.get("installed_to", "-"),
               "程序即将退出并启动新版本。" if result.get("launched") else
               "请手动打开上述目录中的新版程序。"), parent=self)
        if result.get("launched"):
            self.after(400, self.parent.close)

    def _on_failed(self, error):
        self._set_busy(False)
        self.bar["value"] = 0
        self.state_var.set("更新失败（当前版本保持不变）")
        self.progress_var.set(error.message)
        self._toast("更新失败：" + error.message[:40], "err")
        messagebox.showerror("更新失败", error.user_message(), parent=self)

    def copy_link(self):
        url = (self.check.asset["url"] if self.check and self.check.asset
               else (self.check.manual_url if self.check else ""))
        if not url:
            self._toast("暂无可复制的下载链接", "err")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
            self._toast("下载链接已复制", "ok")
        except Exception as e:
            self._toast("复制失败：%s" % e, "err")

    def _toast(self, text, kind):
        try:
            self.parent._toast(text, kind)
        except Exception:
            pass

    def _hide(self):
        self.withdraw()

    def show(self):
        self.deiconify()
        self.lift()
        if not self.busy and self.check is None:
            self.start_check()
