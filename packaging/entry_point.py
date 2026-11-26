# -*- coding: utf-8 -*-
"""PyInstaller 冻结入口（不参与源码运行）。

构建时通过 `--paths src` 让 PyInstaller 解析 jsj_desktop 包；冻结后
jsj_desktop 位于打包归档中，直接导入即可。
"""
import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from jsj_desktop.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
