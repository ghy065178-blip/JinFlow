#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由仓库模板 + 本次 Release 的 SHA256SUMS.txt 生成随 Release 发布的 latest.json。

    python tools/generate_update_manifest.py \
        --checksums release-assets/SHA256SUMS.txt \
        --output release-assets/latest.json

发布前由 Release 工作流调用：把真实 SHA256 写进清单，供应用内更新做校验；
仓库中的 update/latest.json 保持为人类可读的模板（哈希为空）。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jsj_desktop import __version__                       # noqa: E402
from jsj_desktop.update import manifest as mf             # noqa: E402


def parse_checksums(path):
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and len(parts[0]) == 64:
            out[parts[-1].lstrip("*")] = parts[0].lower()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成带 SHA256 的发布更新清单")
    ap.add_argument("--checksums", required=True, help="SHA256SUMS.txt 路径")
    ap.add_argument("--output", required=True, help="输出 latest.json 路径")
    ap.add_argument("--timestamp", default="", help="生成时间（ISO 8601）")
    args = ap.parse_args(argv)

    template = json.loads((ROOT / "update" / "latest.json")
                          .read_text(encoding="utf-8"))
    data = mf.validate_manifest(template)
    if data["latest_version"] != __version__:
        print("失败：清单版本 %s 与源码版本 %s 不一致"
              % (data["latest_version"], __version__), file=sys.stderr)
        return 1
    sums = parse_checksums(args.checksums)
    missing = []
    for target in mf.TARGETS:
        names = mf.asset_names(target)
        entry = data["assets"][target]
        zip_name = names["zip"]
        if zip_name not in sums:
            missing.append(zip_name)
        else:
            entry["sha256"] = sums[zip_name]
        if "dmg" in names:
            if names["dmg"] not in sums:
                missing.append(names["dmg"])
            else:
                entry["dmg_sha256"] = sums[names["dmg"]]
        if "SHA256SUMS.txt" not in sums:
            entry.pop("checksum_url", None)
    if missing:
        print("失败：SHA256SUMS.txt 缺少以下资产：\n  - %s"
              % "\n  - ".join(missing), file=sys.stderr)
        return 1

    data["generated_at"] = (args.timestamp or
                            datetime.now().isoformat(timespec="seconds"))
    data["generated_from"] = "SHA256SUMS.txt"
    data["checksum_filled"] = True
    # 再校验一次，确保生成物仍能被客户端解析
    mf.validate_manifest(data)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print("已生成 %s（版本 %s，%d 个平台，校验和已填充）"
          % (out, data["latest_version"], len(mf.TARGETS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
