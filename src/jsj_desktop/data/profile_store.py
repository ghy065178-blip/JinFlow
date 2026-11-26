# -*- coding: utf-8 -*-
"""多人信息档案库：本地保存、管理、读取与切换。

文件格式与旧版「个人档案.json」完全兼容：
    {"active": "p1", "profiles": [{"id": "p1", "name": "…",
                                   "values": {"姓名": "…", "学号": "…"}}]}
所有文件只存在于用户数据目录，仓库与发布包内不含任何真实档案。
"""
import json
import os
import shutil
import threading
import uuid
from pathlib import Path

from ..core.constants import CONFIG_LINK_KEY

_LOCK = threading.RLock()


def _placeholder_profile():
    """无档案时返回的空壳（不含任何真实或仿真个人信息）。"""
    return {"id": "", "name": "", "values": {}}


class ProfileStore:
    def __init__(self, path, backup_path=None):
        self.path = Path(path)
        self.backup_path = Path(backup_path) if backup_path else \
            self.path.with_name(self.path.stem + ".backup.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ---------- 读写 ----------
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, dict) and isinstance(data.get("profiles"), list):
                profiles = [p for p in data["profiles"]
                            if isinstance(p, dict) and isinstance(p.get("values"), dict)]
                return {"ok": True, "profiles": profiles,
                        "active": str(data.get("active") or ""), "exists": True}
        except Exception:
            pass
        return {"ok": True, "profiles": [], "active": "", "exists": False}

    def _write(self, profiles, active, only_active=False):
        with _LOCK:
            if only_active:
                profiles = self.load()["profiles"]
            cleaned = []
            for i, p in enumerate(profiles or []):
                if not isinstance(p, dict) or not isinstance(p.get("values"), dict):
                    continue
                pid = str(p.get("id") or ("p%d" % i)).strip() or ("p%d" % i)
                name = str(p.get("name") or ("档案 %d" % (i + 1))).strip() \
                    or ("档案 %d" % (i + 1))
                cleaned.append({"id": pid, "name": name,
                                "values": {str(k): v for k, v in p["values"].items()}})
            if active not in [p["id"] for p in cleaned]:
                active = cleaned[0]["id"] if cleaned else ""
            data = {"active": active, "profiles": cleaned}
            tmp = self.path.with_name(
                self.path.name + ".tmp-%d-%s" % (threading.get_ident(),
                                                 uuid.uuid4().hex[:8]))
            try:
                if self.path.exists():
                    shutil.copy2(self.path, self.backup_path)
                with open(tmp, "w", encoding="utf-8") as fp:
                    json.dump(data, fp, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            finally:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass
            return {"ok": True, "active": active, "profiles": cleaned}

    def save(self, profiles, active):
        return self._write(profiles, active)

    def set_active(self, active):
        return self._write(None, active, only_active=True)

    # ---------- 管理 ----------
    def add(self, name, values, profile_id=None):
        lib = self.load()
        pid = profile_id or ("p" + uuid.uuid4().hex[:12])
        lib["profiles"].append({"id": pid, "name": name,
                                "values": dict(values)})
        res = self._write(lib["profiles"], pid)
        return res

    def update(self, profile_id, values, name=None):
        lib = self.load()
        for p in lib["profiles"]:
            if p["id"] == str(profile_id):
                p["values"] = dict(values)
                if name:
                    p["name"] = name
                return self._write(lib["profiles"], lib["active"])
        return {"ok": False, "error": "找不到该档案"}

    def rename(self, profile_id, name):
        lib = self.load()
        for p in lib["profiles"]:
            if p["id"] == str(profile_id):
                p["name"] = name
                return self._write(lib["profiles"], lib["active"])
        return {"ok": False, "error": "找不到该档案"}

    def delete(self, profile_id):
        lib = self.load()
        kept = [p for p in lib["profiles"] if p["id"] != str(profile_id)]
        if len(kept) == len(lib["profiles"]):
            return {"ok": False, "error": "找不到该档案"}
        active = lib["active"] if lib["active"] != str(profile_id) else \
            (kept[0]["id"] if kept else "")
        return self._write(kept, active)

    def get(self, profile_id):
        return next((p for p in self.load()["profiles"]
                     if p["id"] == str(profile_id)), None)

    def apply(self, profile_id, config_store, link=None):
        """把某套档案整批写入指定任务的 报名信息.json（表单链接保持当前值）。"""
        with _LOCK:
            prof = self.get(profile_id)
            if not prof:
                return {"ok": False, "error": "找不到该个人档案"}
            keep_link = str(link if link else
                            (config_store.read().get(CONFIG_LINK_KEY) or "")).strip()
            cfg = config_store.write(keep_link, prof["values"])
            saved = self.set_active(prof["id"])
            return {"ok": True, "cfg": cfg,
                    "active": saved.get("active", prof["id"]),
                    "profile": {"id": prof["id"], "name": prof["name"]}}

    # ---------- 导入 / 导出 ----------
    def export(self, target):
        with open(target, "w", encoding="utf-8") as fp:
            json.dump({"active": self.load()["active"],
                       "profiles": self.load()["profiles"]},
                      fp, ensure_ascii=False, indent=2)

    def import_file(self, source, merge=True):
        """导入旧版「个人档案.json」或本应用导出的档案文件。"""
        with open(source, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        incoming = data.get("profiles") if isinstance(data, dict) else None
        if not isinstance(incoming, list):
            return {"ok": False, "error": "档案格式错误（profiles 应为数组）"}
        lib = self.load()
        profiles = list(lib["profiles"]) if merge else []
        seen = {p["id"] for p in profiles}
        for i, p in enumerate(incoming):
            if not isinstance(p, dict) or not isinstance(p.get("values"), dict):
                continue
            pid = str(p.get("id") or ("import-%d" % i))
            if pid in seen:
                pid = pid + "-" + uuid.uuid4().hex[:6]
            seen.add(pid)
            profiles.append({"id": pid, "name": str(p.get("name") or pid),
                             "values": {str(k): v for k, v in p["values"].items()}})
        return self._write(profiles, data.get("active") or lib["active"])

    def create_from_legacy_config(self, config_store):
        """旧版迁移：用当前「报名信息.json」生成第一套档案（不含链接）。"""
        values = config_store.values()
        if not values:
            return {"ok": False, "error": "当前报名信息为空"}
        name = str(values.get("姓名") or "").strip() or "从旧版导入的档案"
        return self.add(name, values, profile_id="legacy-default")
