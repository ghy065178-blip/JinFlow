# -*- coding: utf-8 -*-
"""界面偏好与任务元信息的轻量持久化（settings.json）。"""
import json
import os
import threading
import uuid
from pathlib import Path

_LOCK = threading.RLock()

DEFAULTS = {
    "mask_logs": False,          # 日志显示脱敏（仅影响显示，不影响提交数据）
    "auto_scroll": True,
    "auto_reply": True,
    "theme_mode": "system",     # dark / light / system
    "tasks": [],                 # 已创建任务的展示名与绑定的档案 id
}


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, dict):
                out = dict(DEFAULTS)
                out.update(data)
                return out
        except Exception:
            pass
        return dict(DEFAULTS)

    def save(self, data):
        with _LOCK:
            tmp = self.path.with_name(self.path.name + ".tmp-" + uuid.uuid4().hex[:8])
            try:
                with open(tmp, "w", encoding="utf-8") as fp:
                    json.dump(data, fp, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            finally:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass
        return data
