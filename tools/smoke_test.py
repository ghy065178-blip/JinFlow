#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""无界面整体自检：逻辑自检 + 全量单元测试 + 敏感数据扫描。

    python tools/smoke_test.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def step(name, cmd):
    print("\n=== %s ===" % name, flush=True)
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def main():
    steps = [
        ("逻辑自检（不联网）", [PY, "-m", "jsj_desktop", "--self-test"]),
        ("单元测试", [PY, "-m", "unittest", "discover", "-s", "tests",
                      "-t", ".", "-v"]),
        ("敏感数据扫描", [PY, "tools/check_no_pii.py", "--strict"]),
        ("源码语法编译", [PY, "-m", "compileall", "-q", "src"]),
    ]
    failed = []
    for name, cmd in steps:
        if step(name, cmd) != 0:
            failed.append(name)
    print("\n========================================")
    if failed:
        print("自检未通过：%s" % "、".join(failed))
        return 1
    print("全部自检通过：业务逻辑、测试、隐私扫描、语法编译。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
