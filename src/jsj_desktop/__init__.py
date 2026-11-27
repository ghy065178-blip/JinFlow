# -*- coding: utf-8 -*-
"""JinFlow 桌面版。

运行时只依赖 Python 3.11+ 标准库；图形界面使用 tkinter/ttk。
核心业务逻辑与旧版 auto_submit.py 保持一致，详见 docs/FEATURE_PARITY.md。
"""

import os

_PRODUCT_VERSION = "2.0.0"
__version__ = os.environ.get("JSJ_RUNTIME_VERSION", "").strip() or _PRODUCT_VERSION
# 发布标签与界面使用产品版本，旧客户端以四段式安装包版本识别修订。
__release_revision__ = 1 if __version__ == _PRODUCT_VERSION else 0
# 用户可见产品名称。__app_id__ 保留旧值，确保升级不会改变既有用户数据目录。
__app_name__ = "JinFlow"
__app_id__ = "JinshujuDesktop"
