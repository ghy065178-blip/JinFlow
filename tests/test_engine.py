# -*- coding: utf-8 -*-
"""引擎演练、验证码拦截、任务管理与预览（全程不联网）。"""
import copy
import json
import queue
import tempfile
import unittest
from pathlib import Path

from jsj_desktop.core.engine import EventSink, RunConfig, TaskContext, run
from jsj_desktop.tasks.manager import TaskManager
from tests import FIXTURES
from tests.helpers import FakeEndpoint, load_fixture


class CollectSink(EventSink):
    def __init__(self):
        self.lines = []
        self.attributes = None
        self.display = None
        self.states = []
        self.summary = None

    def log(self, level, text):
        self.lines.append(text)

    def state(self, **kwargs):
        self.states.append(kwargs)

    def preview(self, attributes, display, fields):
        self.attributes = attributes
        self.display = display

    def finished(self, summary):
        self.summary = summary


class EngineDryRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURES / "expected_attributes.json", "r",
                  encoding="utf-8") as fp:
            cls.golden = json.load(fp)

    def _ctx(self, payload=None, run_cfg=None):
        from jsj_desktop.data.config_store import ConfigStore
        self.tmp = tempfile.TemporaryDirectory()
        store = ConfigStore(Path(self.tmp.name) / "报名信息.json")
        store.write("https://jsj.top/f/EXAMPLE",
                    {k: v for k, v in self.golden["config"].items()
                     if k != "表单链接"})
        ep = FakeEndpoint(payload=payload or load_fixture())
        sink = CollectSink()
        cfg = run_cfg or RunConfig(link="https://jsj.top/f/EXAMPLE",
                                   dry=True, auto_reply=True)
        ctx = TaskContext("t1", store, cfg, sink=sink, endpoint=ep)
        return ctx, sink, ep, store

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_dry_run_generates_identical_attributes(self):
        ctx, sink, ep, _store = self._ctx()
        summary = run(ctx)
        self.assertEqual(sink.attributes, self.golden["attributes"])
        self.assertEqual(sink.display, self.golden["display"])
        self.assertEqual(summary["state"], "exited")
        self.assertTrue(sink.summary["ok"])
        self.assertFalse(any("createPublishedFormEntry" in
                             c.get("query", "") for c in ep.calls),
                         "演练模式不得发送提交请求")
        self.assertTrue(any("[dry-run]" in line for line in sink.lines))
        self.assertIn("最终 entryAttributes", "\n".join(sink.lines))

    def test_no_builtin_link_aborts(self):
        ctx, sink, _ep, store = self._ctx(
            run_cfg=RunConfig(link="", dry=True))
        store.write("", {})
        summary = run(ctx)
        self.assertEqual(summary["state"], "exited")
        self.assertTrue(any("尚未设置表单链接" in x for x in sink.lines))
        self.assertIsNone(sink.attributes)

    def test_captcha_blocks(self):
        payload = copy.deepcopy(load_fixture())
        payload["data"]["publishedForm"]["form"]["setting"]["enableCaptcha"] = True
        ctx, sink, _ep, _store = self._ctx(payload=payload)
        summary = run(ctx)
        self.assertEqual(summary["state"], "failed")
        self.assertTrue(any("验证码" in x for x in sink.lines))

    def test_invalid_choice_aborts(self):
        ctx, sink, _ep, store = self._ctx()
        store.write("https://jsj.top/f/EXAMPLE",
                    {"培养层次": "不存在的选项"})
        summary = run(ctx)
        self.assertEqual(summary["state"], "failed")
        self.assertTrue(any("报名信息有误" in x for x in sink.lines))


class TaskManagerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = queue.Queue()
        self.manager = TaskManager(self.q, data_dir=Path(self.tmp.name))

    def tearDown(self):
        self.manager.stop_all()
        self.tmp.cleanup()

    def test_create_and_close_task(self):
        self.assertEqual(len(self.manager.list()), 1)
        r = self.manager.create("")
        self.assertTrue(r["ok"])
        self.assertEqual(len(self.manager.list()), 2)
        self.assertTrue(self.manager.close(r["id"])["ok"])
        self.assertEqual(len(self.manager.list()), 1)
        self.assertFalse(self.manager.close("t1")["ok"])

    def test_task_config_isolated(self):
        r = self.manager.create("")
        tid = r["id"]
        self.manager.write_config("t1", "https://jsj.top/f/EXAMPLE",
                                  {"姓名": "<占位甲>"})
        self.manager.write_config(tid, "https://jsj.top/f/EXAMPLE",
                                  {"姓名": "<占位乙>"})
        self.assertEqual(self.manager.read_config("t1")["姓名"], "<占位甲>")
        self.assertEqual(self.manager.read_config(tid)["姓名"], "<占位乙>")
        self.assertTrue(Path(self.tmp.name, "tasks", tid, "报名信息.json").exists())

    def test_profiles_apply_to_task(self):
        r = self.manager.profiles.add("档案甲", {"姓名": "<占位>"})
        pid = r["active"]
        t = self.manager.get("t1")
        applied = self.manager.profiles.apply(pid, t.config_store,
                                              "https://jsj.top/f/EXAMPLE")
        self.assertTrue(applied["ok"])
        self.assertEqual(self.manager.read_config("t1")["姓名"], "<占位>")
        self.manager.bind_profile("t1", pid)
        self.assertEqual(self.manager.list()[0]["profile"], pid)

    def test_preview_uses_same_rules(self):
        from tests.helpers import normalized
        fields, _ = normalized()
        form = {"fields": fields, "rules": {
            r["target"]: r for r in
            load_fixture()["data"]["publishedForm"]["form"]
            ["fieldRulesGroupByTarget"]}}
        self.manager.write_config("t1", "https://jsj.top/f/EXAMPLE", {
            k: v for k, v in self.golden_config().items() if k != "表单链接"})
        r = self.manager.preview_attributes("t1", form)
        self.assertTrue(r["ok"])
        self.assertEqual(r["attributes"], self.golden_attributes())

    @staticmethod
    def golden_config():
        with open(FIXTURES / "expected_attributes.json", "r",
                  encoding="utf-8") as fp:
            return json.load(fp)["config"]

    @staticmethod
    def golden_attributes():
        with open(FIXTURES / "expected_attributes.json", "r",
                  encoding="utf-8") as fp:
            return json.load(fp)["attributes"]


if __name__ == "__main__":
    unittest.main()
