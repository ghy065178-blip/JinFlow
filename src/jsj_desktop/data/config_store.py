# -*- coding: utf-8 -*-
"""「报名信息.json」读写：保持旧版按字段中文标签存储的格式。

写入前自动生成 报名信息.backup.json，并用临时文件 + os.replace 原子替换
（与旧版 control_panel.write_config 一致）。每个任务使用独立目录，互不覆盖。
"""
import json
import os
import shutil
import threading
import uuid
from pathlib import Path

from ..core.constants import CONFIG_LINK_KEY

_LOCK = threading.RLock()


class ConfigStore:
    def __init__(self, path, backup_path=None):
        self.path = Path(path)
        self.backup_path = Path(backup_path) if backup_path else \
            self.path.with_name(self.path.stem + ".backup.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def write(self, link, values):
        """按本次表单字段重建配置；空值不写入；返回新的 cfg。"""
        cfg = {CONFIG_LINK_KEY: str(link or "").strip()}
        for k, v in (values or {}).items():
            if v is None or v == "" or v == []:
                continue
            cfg[str(k)] = v
        with _LOCK:
            try:
                if self.path.exists():
                    shutil.copy2(self.path, self.backup_path)
                tmp = self.path.with_name(
                    self.path.name + ".tmp-" + uuid.uuid4().hex[:8])
                with open(tmp, "w", encoding="utf-8") as fp:
                    json.dump(cfg, fp, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            finally:
                try:
                    if tmp and tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass
        return cfg

    def link(self):
        return str(self.read().get(CONFIG_LINK_KEY) or "")

    def values(self):
        cfg = self.read()
        return {str(k): v for k, v in cfg.items() if str(k) != CONFIG_LINK_KEY}

    def replace_from(self, cfg):
        """整批导入一份旧版配置（保留 表单链接）。"""
        link = cfg.get(CONFIG_LINK_KEY, self.link())
        return self.write(link, {k: v for k, v in cfg.items()
                                 if k != CONFIG_LINK_KEY})
