# -*- coding: utf-8 -*-
"""金数据报名助手 · 桌面版（Jinshuju Registration Desktop）。

运行时只依赖 Python 3.11+ 标准库；图形界面使用 tkinter/ttk。
核心业务逻辑与旧版 auto_submit.py 保持一致，详见 docs/FEATURE_PARITY.md。
"""

import os


def _runtime_version():
    value = os.environ.get("JSJ_RUNTIME_VERSION", "").strip()
    return value or "1.3.0"


__version__ = _runtime_version()
__app_name__ = "金数据报名助手"
__app_id__ = "JinshujuDesktop"
