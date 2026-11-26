#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把旧版脚本文件夹的数据导入到桌面版本地数据目录（只复制，不改动旧目录）。

    python tools/migrate_legacy.py --source "D:/path/to/旧脚本文件夹"
    python tools/migrate_legacy.py --source ... --data-dir "D:/my-data"
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="导入旧版报名信息 / 个人档案 / 多开任务")
    ap.add_argument("--source", required=True, help="旧版脚本所在文件夹")
    ap.add_argument("--data-dir", default="", help="目标数据目录（默认平台标准目录）")
    args = ap.parse_args(argv)

    if args.data_dir:
        os.environ["JSJ_DATA_DIR"] = str(Path(args.data_dir).resolve())

    from jsj_desktop.data.config_store import ConfigStore
    from jsj_desktop.data.paths import (data_dir, profiles_path,
                                        task_config_backup_path,
                                        task_config_path)
    from jsj_desktop.data.profile_store import ProfileStore

    source = Path(args.source).resolve()
    if not source.is_dir():
        print("源目录不存在：%s" % source, file=sys.stderr)
        return 2

    store = ConfigStore(task_config_path("t1"), task_config_backup_path("t1"))
    profiles = ProfileStore(profiles_path())
    count = 0

    cfg_file = source / "报名信息.json"
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        if isinstance(data, dict):
            store.replace_from(data)
            count += 1
            print("已导入 报名信息.json → %s" % store.path)

    prof_file = source / "个人档案.json"
    if prof_file.exists():
        res = profiles.import_file(prof_file, merge=True)
        if res.get("ok"):
            count += 1
            print("已导入 个人档案.json → %s（共 %d 套）" %
                  (profiles.path, len(res["profiles"])))
        else:
            print("个人档案导入失败：%s" % res.get("error"), file=sys.stderr)

    multi = source / "多开任务"
    if multi.is_dir():
        for sub in sorted(p for p in multi.iterdir() if p.is_dir()):
            f = sub / "报名信息.json"
            if not f.exists():
                continue
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if not isinstance(data, dict):
                continue
            values = {str(k): v for k, v in data.items() if k != "表单链接"}
            name = str(values.get("姓名") or sub.name)
            profiles.add(name, values)
            count += 1
            print("已把 %s 转为档案「%s」" % (sub.name, name))

    print("\n完成：共导入 %d 份数据；数据目录：%s" % (count, data_dir()))
    print("旧目录保持原样。请在图形界面「读取表单」并用「演练自检」核对字段。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
