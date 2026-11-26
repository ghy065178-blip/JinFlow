# -*- coding: utf-8 -*-
"""多开任务：最多 8 个，各自独立的报名信息、表单链接、时间与日志。

旧版用「子进程 + 复制 auto_submit.py + 抓取 stdout」实现多开；桌面版改为
「独立线程 + 独立配置目录 + 结构化事件」：
  * 每个任务仍完全隔离，互不覆盖配置与统计；
  * 不再依赖终端管道与正则猜测提示语，启动/停止/应答更可靠；
  * 提交请求、等待节奏与判定逻辑由 core.engine 保持一致。
"""
import json
import threading
import time
import uuid
from collections import OrderedDict

from ..core.constants import MAX_TASKS
from ..core.engine import EventSink, InputProvider, RunConfig, TaskContext, run
from ..core.mapping import fill_form
from ..data.config_store import ConfigStore
from ..data.paths import (task_config_backup_path, task_config_path)
from ..data.profile_store import ProfileStore
from ..data.settings_store import Settings
from ..data import paths as data_paths


def blank_stats():
    return {
        "state": "idle", "phase": "空闲", "attempt": 0, "last": "",
        "offset": None, "countdown": None, "form_name": "", "form_status": "",
        "captcha": "", "open_time": "", "fields": 0, "submit_fields": 0,
        "waiting": False, "replies": 0,
    }


def blank_cfg():
    return RunConfig.from_mapping({
        "time_mode": "1", "lead": "-6", "interval": "0.05", "timeout": "40",
        "auto_reply": True,
    }).as_dict()


class GuiInputProvider(InputProvider):
    """缺项应答：自动模式沿用配置值，交互模式向 GUI 发出弹窗请求。"""

    def __init__(self, on_question, auto_reply=True):
        self.on_question = on_question
        self.auto_reply = auto_reply
        self.pending = {}
        self.lock = threading.RLock()

    def _ask(self, kind, field, default):
        if self.auto_reply:
            return default
        req_id = uuid.uuid4().hex
        ev = threading.Event()
        req = {"id": req_id, "kind": kind, "label": field["label"],
               "required": field.get("required", False),
               "choices": [[v, n] for v, n in field.get("choices", [])],
               "default": default, "task_id": ""}
        with self.lock:
            self.pending[req_id] = {"event": ev, "answer": None}
        self.on_question(req)
        ev.wait(180)
        with self.lock:
            item = self.pending.pop(req_id, None)
        if item is None or item["answer"] is None:
            return default
        return item["answer"]

    def answer(self, req_id, value):
        with self.lock:
            item = self.pending.get(req_id)
        if not item:
            return False
        item["answer"] = value
        item["event"].set()
        return True

    def pending_requests(self):
        with self.lock:
            return list(self.pending.keys())

    def ask_text(self, field, default_code):
        return self._ask("text", field, default_code or "")

    def ask_single(self, field, default_code):
        ans = self._ask("single", field, default_code)
        return ans if ans else default_code

    def ask_multi(self, field, default_codes):
        ans = self._ask("multi", field, default_codes or [])
        return ans if ans else (default_codes or [])


class QueueSink(EventSink):
    """把引擎事件写入线程安全队列，由 GUI 主循环消费。"""

    def __init__(self, queue, task_id):
        self.queue = queue
        self.task_id = task_id

    def _put(self, kind, payload):
        self.queue.put((kind, self.task_id, payload))

    def log(self, level, text):
        self._put("log", {"level": level, "text": text,
                          "ts": time.strftime("%H:%M:%S") + ".%03d" %
                          (int(time.time() * 1000) % 1000)})

    def state(self, **kwargs):
        self._put("state", kwargs)

    def form(self, info):
        open_dt = info.get("open_dt")
        data = {"ok": bool(info.get("ok")), "name": info.get("name", ""),
                "status": info.get("status", ""),
                "captcha": bool(info.get("captcha")),
                "open_time": open_dt.strftime("%Y-%m-%d %H:%M:%S") if open_dt else "",
                "fields": info.get("fields", []), "rules": info.get("rules", {}),
                "form_url": info.get("_form_url", "")}
        self._put("form", data)

    def preview(self, attributes, display, fields):
        rows = [(f["label"], display[f["api"]], attributes[f["api"]])
                for f in fields if f["api"] in attributes]
        self._put("preview", {"rows": rows, "attributes": attributes})

    def finished(self, summary):
        self._put("finished", summary)


class Task:
    def __init__(self, task_id, name, config_store):
        self.id = task_id
        self.name = name
        self.config_store = config_store
        self.profile_id = ""
        self.stats = blank_stats()
        self.cfg = blank_cfg()
        self.form = {"ok": False, "fields": [], "rules": {}, "name": "",
                     "status": "", "captcha": False, "open_time": ""}
        self.logs = []
        self.thread = None
        self.stop_event = threading.Event()
        self.provider = None
        self.start_time = None
        self.exit_code = None
        self.attributes = {}

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def snapshot(self):
        stats = dict(self.stats)
        stats["running"] = self.running
        stats["pid"] = self.thread.ident if self.running else None
        stats["uptime"] = round(time.time() - self.start_time, 1) \
            if self.start_time and self.running else 0
        stats["exit_code"] = self.exit_code
        return {"id": self.id, "name": self.name, "stats": stats,
                "cfg": dict(self.cfg), "form": dict(self.form),
                "profile_id": self.profile_id, "log_count": len(self.logs)}


class TaskManager:
    def __init__(self, event_queue, data_dir=None):
        self.queue = event_queue
        self.lock = threading.RLock()
        self.tasks = OrderedDict()
        self.seq = 1
        self._override = bool(data_dir)
        if data_dir:
            self.root = data_dir / "tasks"
            self.root.mkdir(parents=True, exist_ok=True)
        else:
            self.root = data_paths.tasks_root()
        self.settings = Settings(data_dir / "settings.json" if data_dir
                                 else data_paths.settings_path())
        self.profiles = ProfileStore(
            data_dir / "profiles.json" if data_dir
            else data_paths.profiles_path())
        self._restore()

    def _restore(self):
        saved = self.settings.load().get("tasks") or []
        with self.lock:
            for item in saved[:MAX_TASKS]:
                tid = str(item.get("id") or ("t%d" % (self.seq + 1)))
                self._add(tid, str(item.get("name") or tid))
                self.tasks[tid].profile_id = str(item.get("profile_id") or "")
                try:
                    self.seq = max(self.seq, int(tid.lstrip("t") or 1))
                except ValueError:
                    pass
            if "t1" not in self.tasks:
                self._add("t1", "任务 1")
                self.tasks.move_to_end("t1", last=False)
        self._persist_meta()

    def _add(self, tid, name):
        # 默认使用平台数据目录；测试注入 data_dir 时改用注入目录
        task = Task(tid, name, self._task_store(tid))
        task.cfg["link"] = task.config_store.link()
        self.tasks[tid] = task
        return task

    def _task_store(self, tid):
        override = getattr(self, "_override", False)
        if override:
            return ConfigStore(self.root / tid / "报名信息.json",
                               self.root / tid / "报名信息.backup.json")
        return ConfigStore(task_config_path(tid), task_config_backup_path(tid))

    def _persist_meta(self):
        meta = [{"id": t.id, "name": t.name, "profile_id": t.profile_id}
                for t in self.tasks.values()]
        s = self.settings.load()
        s["tasks"] = meta
        self.settings.save(s)

    # ---------- 任务管理 ----------
    def list(self):
        with self.lock:
            return [{"id": t.id, "name": t.name, "state": t.stats["state"],
                     "phase": t.stats["phase"], "running": t.running,
                     "pid": t.thread.ident if t.running else None,
                     "uptime": round(time.time() - t.start_time, 1)
                     if t.running and t.start_time else 0,
                     "attempt": t.stats["attempt"], "last": t.stats["last"],
                     "profile": t.profile_id}
                    for t in self.tasks.values()]

    def get(self, task_id):
        with self.lock:
            return self.tasks.get(str(task_id)) or self.tasks.get("t1")

    def create(self, name=""):
        with self.lock:
            if len(self.tasks) >= MAX_TASKS:
                return {"ok": False, "error": "最多同时开 %d 个任务" % MAX_TASKS}
            self.seq += 1
            tid = "t%d" % self.seq
            while tid in self.tasks:
                self.seq += 1
                tid = "t%d" % self.seq
            label = str(name or "").strip() or ("任务 %d" % (len(self.tasks) + 1))
            base = self.get("t1")
            t = self._add(tid, label)
            if base:
                # 新任务继承主任务的报名信息（旧版行为：复制主任务配置）
                cfg = base.config_store.read()
                t.config_store.replace_from(cfg)
                t.cfg["link"] = t.config_store.link()
            self._persist_meta()
        self.log(tid, "info", "[平台] 已创建「%s」，独立配置目录：tasks/%s" % (label, tid))
        return {"ok": True, "id": tid, "tasks": self.list()}

    def close(self, task_id):
        tid = str(task_id)
        if tid == "t1":
            return {"ok": False, "error": "主任务不能关闭"}
        t = self.get(tid)
        if not t:
            return {"ok": False, "error": "任务不存在"}
        if t.running:
            return {"ok": False, "error": "该任务仍在运行，请先停止"}
        with self.lock:
            self.tasks.pop(tid, None)
            self._persist_meta()
        return {"ok": True, "tasks": self.list()}

    def rename(self, task_id, name):
        t = self.get(task_id)
        if not t:
            return {"ok": False, "error": "任务不存在"}
        t.name = str(name or t.name)
        self._persist_meta()
        return {"ok": True, "tasks": self.list()}

    def bind_profile(self, task_id, profile_id):
        t = self.get(task_id)
        if not t:
            return {"ok": False, "error": "任务不存在"}
        t.profile_id = str(profile_id or "")
        self._persist_meta()
        return {"ok": True}

    def log(self, task_id, level, text):
        t = self.get(task_id)
        item = {"ts": time.strftime("%H:%M:%S"), "level": level, "text": text}
        if t:
            t.logs.append(item)
            if len(t.logs) > 5000:
                del t.logs[:1500]
        self.queue.put(("log", str(task_id), item))

    def clear_logs(self, task_id):
        t = self.get(task_id)
        if t:
            t.logs.clear()

    # ---------- 表单结构（GUI 主动读取）----------
    def load_form(self, task_id, link):
        from ..core.endpoint import Endpoint
        t = self.get(task_id)
        ep = Endpoint()
        if not ep.set_from_link(link):
            return {"ok": False, "error": "链接格式无法识别，请粘贴完整 URL 或末尾 token"}
        info = ep.fetch_form()
        if not info["ok"]:
            return info
        open_dt = info.get("open_dt")
        data = {"ok": True, "name": info["name"], "status": info["status"],
                "captcha": info["captcha"],
                "open_time": open_dt.strftime("%Y-%m-%d %H:%M:%S") if open_dt else "",
                "fields": info["fields"], "rules": info["rules"],
                "form_url": ep.form_url}
        t.form = dict(data)
        t.stats.update({"form_name": data["name"], "form_status": data["status"],
                        "captcha": "启用" if data["captcha"] else "未启用",
                        "open_time": data["open_time"],
                        "fields": len(data["fields"])})
        t.cfg["link"] = link
        self.log(task_id, "info", "[平台] 已读取表单「%s」，共 %d 个字段" %
                 (data["name"], len(data["fields"])))
        self.queue.put(("state", t.id, dict(t.stats)))
        return data

    # ---------- 运行 ----------
    def start(self, task_id, payload):
        t = self.get(task_id)
        if not t:
            return {"ok": False, "error": "任务不存在"}
        if t.running:
            return {"ok": False, "error": "该任务已在运行中"}
        cfg = RunConfig.from_mapping(payload)
        t.cfg = cfg.as_dict()
        t.stop_event = threading.Event()
        t.provider = GuiInputProvider(
            lambda req: self.queue.put(("question", t.id, req)),
            auto_reply=cfg.auto_reply)
        sink = QueueSink(self.queue, t.id)
        ctx = TaskContext(t.id, t.config_store, cfg, sink=sink,
                          provider=t.provider, stop_event=t.stop_event)
        t.stats.update({"state": "starting", "phase": "正在启动", "attempt": 0,
                        "last": "", "countdown": None, "offset": None,
                        "submit_fields": 0, "waiting": False, "replies": 0})
        t.exit_code = None
        t.thread = threading.Thread(target=self._worker, args=(t, ctx),
                                    daemon=True, name="jsj-engine-" + t.id)
        t.start_time = time.time()
        t.thread.start()
        self.log(t.id, "info", "[平台] 启动「%s」：%s%s%s" %
                 (t.name, cfg.link, " --quick" if cfg.quick else "",
                  " --dry-run" if cfg.dry else ""))
        return {"ok": True, "task_id": t.id}

    def _worker(self, task, ctx):
        try:
            summary = run(ctx)
            task.exit_code = 0 if summary.get("ok") else 1
            task.attributes = summary.get("attributes", {})
        except Exception as e:
            task.exit_code = 2
            self.log(task.id, "error", "[平台] 引擎异常：%s" % e)

    def stop(self, task_id):
        t = self.get(task_id)
        if not t or not t.running:
            return {"ok": False, "error": "当前没有运行中的脚本"}
        t.stop_event.set()
        t.stats.update({"state": "stopped", "phase": "已手动停止",
                        "waiting": False})
        self.log(t.id, "warn", "[平台] 已手动停止「%s」" % t.name)
        self.queue.put(("state", t.id, dict(t.stats)))
        return {"ok": True}

    def stop_all(self):
        for tid in list(self.tasks.keys()):
            try:
                self.stop(tid)
            except Exception:
                pass

    # ---------- 事件入队（供 GUI 刷新）----------
    def apply_event(self, kind, task_id, payload):
        t = self.get(task_id)
        if not t:
            return
        if kind == "log":
            t.logs.append(payload)
            if len(t.logs) > 5000:
                del t.logs[:1500]
        elif kind == "state":
            t.stats.update(payload)
        elif kind == "form":
            t.form = dict(payload)
        elif kind == "finished":
            t.exit_code = 0 if payload.get("ok") else 1
            t.attributes = payload.get("attributes", {})

    def send_input(self, task_id, text):
        """等价于旧版「向脚本终端发送一行」：优先应答待处理的问题。"""
        t = self.get(task_id)
        if not t:
            return {"ok": False, "error": "任务不存在"}
        if t.provider and t.provider.pending_requests():
            t.provider.answer(t.provider.pending_requests()[0], str(text))
            t.stats["replies"] += 1
            self.log(t.id, "info", "[平台] 手动应答 → " +
                     ("回车" if text == "" else text))
            return {"ok": True}
        if t.running:
            self.log(t.id, "info", "[平台] 当前没有等待应答的提问，已记录输入：" +
                     ("回车" if text == "" else text))
            return {"ok": True, "note": "当前无待应答提问"}
        return {"ok": False, "error": "当前没有运行中的脚本"}

    def write_config(self, task_id, link, values):
        t = self.get(task_id)
        if not t:
            return {"ok": False, "error": "任务不存在"}
        cfg = t.config_store.write(link, values)
        t.cfg["link"] = link
        self.log(t.id, "ok", "[平台] 报名信息已保存（%d 项，写入前已备份）" %
                 (len(cfg) - 1))
        return {"ok": True, "cfg": cfg}

    def read_config(self, task_id):
        t = self.get(task_id)
        return t.config_store.read() if t else {}

    def preview_attributes(self, task_id, form=None):
        """界面预览「本次将提交的信息」，与引擎用同一套函数。"""
        from ..core.mapping import build_attributes, config_to_chosen
        t = self.get(task_id)
        if not t:
            return {"ok": False, "error": "任务不存在"}
        form = form or t.form
        fields = form.get("fields") or []
        if not fields:
            return {"ok": False, "error": "尚未读取表单结构"}
        try:
            chosen = config_to_chosen(t.config_store.read(), fields)
            fill_form(fields, form.get("rules") or {}, chosen, only_missing=True)
            attributes, display = build_attributes(
                fields, form.get("rules") or {}, chosen)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        rows = [(f["label"], display[f["api"]], attributes[f["api"]])
                for f in fields if f["api"] in attributes]
        return {"ok": True, "rows": rows, "attributes": attributes}
