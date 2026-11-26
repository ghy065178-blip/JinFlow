# -*- coding: utf-8 -*-
"""本地数据层：报名信息读写备份、多人档案 CRUD / 切换 / 导入导出。"""
import json
import tempfile
import unittest
from pathlib import Path

from jsj_desktop.data.config_store import ConfigStore
from jsj_desktop.data.profile_store import ProfileStore
from jsj_desktop.data.settings_store import Settings

PLACEHOLDER = {"姓名": "<姓名占位>", "学号": "<学号占位>",
               "电话": "<电话占位>", "培养层次": "硕士"}


class ConfigStoreTest(unittest.TestCase):
    def test_write_read_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "报名信息.json"
            store = ConfigStore(p)
            store.write("https://jsj.top/f/EXAMPLE", PLACEHOLDER)
            self.assertEqual(store.link(), "https://jsj.top/f/EXAMPLE")
            self.assertEqual(store.values(), PLACEHOLDER)
            store.write("https://jsj.top/f/EXAMPLE", {"姓名": "<另一个占位>"})
            self.assertEqual(store.values(), {"姓名": "<另一个占位>"})
            self.assertTrue(store.backup_path.exists())
            backup = json.loads(store.backup_path.read_text(encoding="utf-8"))
            self.assertEqual(backup["姓名"], "<姓名占位>")

    def test_empty_values_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(Path(tmp) / "报名信息.json")
            cfg = store.write("", {"姓名": "<占位>", "电话": "",
                                   "备注": [], "空": None})
            self.assertEqual(cfg, {"表单链接": "", "姓名": "<占位>"})


class ProfileStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = ProfileStore(self.root / "profiles.json")
        self.config = ConfigStore(self.root / "报名信息.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_crud_and_switch(self):
        r = self.store.add("档案甲", PLACEHOLDER)
        pid = r["active"]
        self.assertEqual(len(r["profiles"]), 1)
        self.assertEqual(self.store.get(pid)["values"], PLACEHOLDER)

        self.store.update(pid, {"姓名": "<占位乙>"})
        self.assertEqual(self.store.get(pid)["values"], {"姓名": "<占位乙>"})
        self.store.rename(pid, "改名后")
        self.assertEqual(self.store.get(pid)["name"], "改名后")

        second = self.store.add("档案乙", {"姓名": "<占位丙>"})["active"]
        self.assertEqual(len(self.store.load()["profiles"]), 2)
        self.config.write("https://jsj.top/f/EXAMPLE", {})
        applied = self.store.apply(second, self.config)
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["cfg"]["姓名"], "<占位丙>")
        self.assertEqual(applied["cfg"]["表单链接"],
                         "https://jsj.top/f/EXAMPLE")
        self.assertEqual(self.store.load()["active"], second)

        self.assertTrue(self.store.delete(pid)["ok"])
        self.assertEqual(len(self.store.load()["profiles"]), 1)
        self.assertTrue(self.store.backup_path.exists())

    def test_export_import_merge(self):
        self.store.add("档案甲", PLACEHOLDER)
        out = self.root / "export.json"
        self.store.export(out)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(data["profiles"]), 1)

        other = ProfileStore(self.root / "other.json")
        r = other.import_file(out, merge=True)
        self.assertTrue(r["ok"])
        self.assertEqual(len(other.load()["profiles"]), 1)
        r = other.import_file(out, merge=True)
        self.assertEqual(len(other.load()["profiles"]), 2)  # id 去重后追加

    def test_legacy_shape_compatibility(self):
        legacy = {"active": "p1", "profiles": [
            {"id": "p1", "name": "旧版档案", "values": PLACEHOLDER}]}
        f = self.root / "个人档案.json"
        f.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        r = self.store.import_file(f)
        self.assertTrue(r["ok"])
        self.assertEqual(r["active"], "p1")
        self.assertEqual(self.store.get("p1")["name"], "旧版档案")

    def test_apply_missing_profile(self):
        r = self.store.apply("不存在", self.config)
        self.assertFalse(r["ok"])


class SettingsTest(unittest.TestCase):
    def test_defaults_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Settings(Path(tmp) / "settings.json")
            self.assertFalse(s.load()["mask_logs"])
            self.assertEqual(s.load()["theme_mode"], "system")
            data = s.load()
            data["mask_logs"] = True
            data["theme_mode"] = "light"
            s.save(data)
            self.assertTrue(s.load()["mask_logs"])
            self.assertEqual(s.load()["theme_mode"], "light")


if __name__ == "__main__":
    unittest.main()
