# -*- coding: utf-8 -*-
"""应用内更新面板。后台线程执行下载和安装，主线程反馈进度。"""
import queue
import sys
import threading
import tkinter as tk
from tkinter import BOTH, LEFT, RIGHT, X, Y, StringVar, messagebox, ttk

from .. import __release_revision__, __version__
from ..update import client, service
from ..update.errors import UpdateError
from .theme import PALETTE, font_family


PROGRESS_LABELS = {
    "checksum": "正在获取校验信息…", "download": "正在下载…",
    "verify": "正在验证下载…", "extract": "正在解包…",
    "validate": "正在核对安装包…", "install": "正在安装…",
}


def version_label(version, revision):
    return "%s（修订 %d）" % (version, revision) if revision else version


class UpdateDialog(tk.Toplevel):
    def __init__(self, parent, result=None):
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
        self.installing = False
        self.check = None
        self._drain_after = None

        self.cur_var = StringVar(value=version_label(__version__, __release_revision__))
        self.latest_var = StringVar(value="尚未检查")
        self.state_var = StringVar(value="尚未检查更新")
        self.platform_var = StringVar(value="—")
        self.channel_var = StringVar(value="—")
        self.asset_format_var = tk.StringVar(value="zip")
        self.format_hint_var = StringVar(value="")
        self.progress_var = StringVar(value="等待操作")

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._hide)
        self._drain_after = self.after(80, self._drain)
        self.show(result)

    def retheme(self):
        """刷新更新说明文本的直接 tkinter 颜色，控件顺序保持不变。"""
        self.configure(bg=PALETTE["bg"])
        self.notes.configure(bg=PALETTE["surface2"],
                             fg=PALETTE["text"],
                             insertbackground=PALETTE["text"])

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
        ttk.Label(grid, text="下载格式", style="CardKey.TLabel", width=12) \
            .grid(row=5, column=0, sticky="nw", pady=(7, 2))
        self.format_frame = ttk.Frame(grid, style="Card.TFrame")
        self.format_frame.grid(row=5, column=1, sticky="w", pady=(4, 0))
        self.format_zip = ttk.Radiobutton(
            self.format_frame, text="ZIP（应用内更新）", value="zip",
            variable=self.asset_format_var, style="Theme.TRadiobutton",
            command=self._on_format_changed)
        self.format_zip.pack(side=LEFT, padx=(0, 14))
        self.format_dmg = ttk.Radiobutton(
            self.format_frame, text="DMG（挂载后更新）", value="dmg",
            variable=self.asset_format_var, style="Theme.TRadiobutton",
            command=self._on_format_changed,
            state="normal" if sys.platform == "darwin" else "disabled")
        self.format_dmg.pack(side=LEFT)
        ttk.Label(grid, textvariable=self.format_hint_var,
                  style="CardHint.TLabel").grid(row=6, column=1,
                                                  sticky="w", pady=(0, 2))
        grid.columnconfigure(1, weight=1)

        note_box = ttk.LabelFrame(self, text="版本说明", padding=8)
        note_box.pack(fill=BOTH, expand=True, padx=16, pady=(0, 8))
        self.notes = tk.Text(note_box, height=8, wrap="word",
                             state="disabled",
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

    def _sync_asset_controls(self, result):
        """按当前平台和清单同步 ZIP/DMG 选择，保持版本结果只检查一次。"""
        assets = getattr(result, "assets", {}) or {}
        target = str(getattr(result, "target", "") or "")
        is_macos = target.startswith("macos") or sys.platform == "darwin"
        has_zip = "zip" in assets
        has_dmg = is_macos and "dmg" in assets
        self.format_zip.configure(state="normal" if has_zip else "disabled")
        self.format_dmg.configure(state="normal" if has_dmg else "disabled")
        requested = str(getattr(result, "asset_kind", "zip") or "zip")
        if requested not in assets or (requested == "dmg" and not has_dmg):
            requested = "zip" if has_zip else ("dmg" if has_dmg else "zip")
        self.asset_format_var.set(requested)
        if requested != getattr(result, "asset_kind", "zip"):
            result = client.select_asset(result, requested)
        if has_dmg:
            self.format_hint_var.set("ZIP 直接解压更新，DMG 会挂载并替换应用。")
        elif has_zip:
            self.format_hint_var.set("当前平台提供 ZIP 更新包。")
        else:
            self.format_hint_var.set("当前发布未提供可用的自动更新包。")
        return result

    def _on_format_changed(self):
        if self.busy or not self.check:
            return
        selected = self.asset_format_var.get()
        result = client.select_asset(self.check, selected)
        self.check = result
        self.parent._show_update_banner(result)
        self.state_var.set(result.reason)
        self.progress_var.set(result.reason)
        self._set_busy(False)

    # -------------------- 线程与事件 --------------------
    def _drain(self):
        self._drain_after = None
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "checked":
                    self._on_checked(payload)
                elif kind == "progress":
                    stage, pct, text = payload
                    self.bar["value"] = pct
                    self.progress_var.set(text)
                    if stage in PROGRESS_LABELS:
                        self.state_var.set(PROGRESS_LABELS[stage])
                elif kind == "done":
                    self._on_done(payload)
                    if payload.get("pending") or payload.get("launched"):
                        return
                elif kind == "check_failed":
                    self.parent._show_update_banner(None)
                    self._on_failed(payload)
                elif kind == "failed":
                    self._on_failed(payload)
        except queue.Empty:
            pass
        self._drain_after = self.after(80, self._drain)

    def destroy(self):
        if self._drain_after is not None:
            self.after_cancel(self._drain_after)
        super().destroy()

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
        self.check = None
        self._set_busy(True)
        self.bar["value"] = 0
        self.progress_var.set("正在检查最新版本…")
        self.state_var.set("正在检查…")

        def work():
            try:
                self.events.put(("checked", service.check_for_update()))
            except Exception as e:  # noqa: BLE001
                self.events.put(("check_failed", UpdateError(
                    "检查更新时出现未预期错误：%s" % e, cause=e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_checked(self, result):
        result = self._sync_asset_controls(result)
        self.check = result
        self.parent._show_update_banner(result)
        self.latest_var.set(version_label(result.latest_version, result.latest_revision)
                            if result.latest_version else "获取失败")
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
        self.cur_var.set(version_label(result.current_version, result.current_revision))

        if not result.ok:
            self._set_busy(False)
            self._toast("检查更新失败", "err")
            messagebox.showerror("检查更新失败", result.reason, parent=self)
            return
        if result.update_available and result.can_update:
            self.update_btn.configure(text="立即更新")
        elif result.update_available:
            self.update_btn.configure(text="暂不可更新")
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
        running = [t for t in self.parent.manager.list() if t.get("running")]
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
            % version_label(self.check.latest_version, self.check.latest_revision), parent=self)
        if not ok:
            return
        self.installing = True
        self._set_busy(True)
        self.bar["value"] = 0
        self.state_var.set("正在准备更新…")
        self.progress_var.set("正在获取校验信息…")
        check = self.check

        def progress(stage, pct, text):
            self.events.put(("progress", (stage, pct, text)))

        def work():
            try:
                result = service.apply_update(check=check,
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
        self.progress_var.set(result["message"])
        self.parent._show_update_banner(None)
        if result.get("pending"):
            self.state_var.set("正在安装…")
            self.update_idletasks()
            self.installing = False
            self.parent.close()
            return
        self.check = None
        self._set_busy(False)
        self.update_btn.configure(text="已完成")
        self.bar["value"] = 100
        self.state_var.set("更新成功")
        label = version_label(result["latest_version"], result.get("latest_revision", 0))
        self._toast("已更新到 v%s" % label, "ok")
        messagebox.showinfo(
            "更新成功",
            "%s\n\n目标版本：v%s\n校验来源：%s\n安装位置：%s\n%s"
            % (result["message"], label,
               result.get("checksum_source", "-"),
               result.get("installed_to", "-"),
               "程序即将退出并启动新版本。" if result.get("launched") else
               "请手动打开上述目录中的新版程序。"), parent=self)
        self.installing = False
        if result.get("launched"):
            self.parent.close()

    def _on_failed(self, error):
        self.installing = False
        self._set_busy(False)
        self.bar["value"] = 0
        self.state_var.set("更新失败")
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
        if not self.installing:
            self.withdraw()

    def show(self, result=None):
        self.deiconify()
        self.lift()
        if not self.busy:
            if result is not None:
                self._on_checked(result)
            else:
                self.start_check()
