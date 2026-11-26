# -*- coding: utf-8 -*-
"""测试包：把 src/ 加入导入路径，使 CI 无需先 pip install。"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = Path(__file__).resolve().parent / "fixtures"
