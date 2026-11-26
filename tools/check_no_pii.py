#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敏感数据扫描器：保证 Git 仓库与发布包内不含内置个人信息 / 活动链接。

用法：
    python tools/check_no_pii.py --strict                 # 扫描仓库
    python tools/check_no_pii.py --strict --artifact dist/xxx.zip
    python tools/check_no_pii.py --strict --artifact dist/xxx.dmg   # 仅 macOS
    python tools/check_no_pii.py --self-test              # 自检检测规则

检查项：
  1. 禁止出现的个人数据文件名（报名信息.json / 个人档案.json / 备份 / 日志等）；
  2. 文本中的真实活动链接、内置 token、手机号、身份证号；
  3. JSON 中「姓名 / 学号 / 电话 / 手机号 / 身份证」等键对应的非占位值；
  4. 明显的凭据文件（.env、私钥、密钥等）。

允许：明确的占位值（<…>、示例、x、EXAMPLE、placeholder 等）与合成测试数据。
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv",
             "venv", "build", "dist", ".workbuddy", "node_modules",
             ".idea", ".vscode", "site-packages"}
SKIP_FILES = {"check_no_pii.py", "test_no_pii.py", "package-lock.json"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".icns", ".pdf",
              ".zip", ".7z", ".exe", ".dll", ".so", ".dylib", ".pyd",
              ".pyc", ".woff", ".ttf", ".otf", ".mp4", ".wasm", ".enc"}

# PyInstaller 冻结后随包携带的运行时数据：Tcl/Tk 编码表（.enc）与 CA 根证书
# （cacert.pem）含大量纯数字/Base64 文本，不是用户数据；跳过内容模式匹配，
# 但仍执行文件名禁用检查（私钥 .pem 依旧会被拦截）。
RUNTIME_DATA_MARKERS = ("/_tcl_data/", "/_tk_data/", "/tcl8/", "/tk8/",
                        "/_internal/tcl/", "/_internal/tk/",
                        "/certs/cacert.pem")

# 随包 CA 根证书是可信文件，豁免 .pem 私钥规则；仅在 certs/ 目录下生效
TRUSTED_CA_FILES = {"cacert.pem"}

FORBIDDEN_NAMES = [
    re.compile(r"^报名信息.*\.json$", re.I),
    re.compile(r"^个人档案.*\.json$", re.I),
    re.compile(r".*\.backup\.json$", re.I),
    re.compile(r"^panel_url\.txt$", re.I),
    re.compile(r".*control_panel_error\.log$", re.I),
    re.compile(r"^多开任务$"),
    re.compile(r"^auto_submit\.py\.bak", re.I),
    re.compile(r"^control_panel\.html\.bak", re.I),
    re.compile(r"^\.env$", re.I),
    re.compile(r".*_rsa$", re.I),
    re.compile(r".*\.pem$", re.I),
]
FORBIDDEN_DIRS = {re.compile(r"^多开任务$"), re.compile(r"^task_t\d+$")}

PII_KEYS = {"姓名", "学号", "电话", "手机号", "手机", "联系电话", "身份证",
            "身份证号"}
PII_KEYS_EN = {"name", "student_id", "student_no", "phone", "mobile",
               "id_card", "id_number"}
PLACEHOLDER_MARKERS = ("<", "占位", "示例", "example", "placeholder", "xxxx",
                       "xxx", "***", "dummy", "sample", "示例姓名", "demo")
# 合成测试数据 / 示例中允许出现形似链接的字符串；其它路径一律按真实链接检查
SYNTHETIC_PREFIXES = ("tests/", "examples/")

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
IDCARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
FORM_LINK_RE = re.compile(r"https?://[a-zA-Z0-9.\-]+/f/([A-Za-z0-9]{4,})")
TOKEN_ASSIGN_RE = re.compile(
    r"DEFAULT_TOKEN\s*=\s*[\"']([A-Za-z0-9]{4,})[\"']")
SAFE_TOKENS = {"xxxxx", "XXXX", "EXAMPLE", "example", "token", "TOKEN",
               "placeholder", "SAMPLE", "sample", "abc123", "abcdef",
               "yourtoken", "demo123", "TESTTOKEN"}
SECRET_HINT_RE = re.compile(
    r"(api[_-]?key|secret[_-]?key|password|access[_-]?token)\s*[:=]\s*[\"'][^\"'<>{}\s]{12,}",
    re.I)


def _is_placeholder(value):
    if not isinstance(value, str):
        return False
    low = value.strip().lower()
    if not low:
        return True
    if low.startswith("<") or low in ("-", "--", "n/a", "none", "null"):
        return True
    return any(m.lower() in low for m in PLACEHOLDER_MARKERS)


def _is_runtime_data(rel):
    normalized = "/" + str(rel).replace("\\", "/")
    return any(marker in normalized for marker in RUNTIME_DATA_MARKERS)


def _scan_text(rel, text, findings):
    if _is_runtime_data(rel):
        return
    normalized = rel.replace("\\", "/")
    parts = normalized.split("/")[:-1]
    # 允许 tests/ 与 examples/ 作为任意层级下的目录（例如源码压缩包带顶层目录名）
    synthetic = (normalized.startswith(SYNTHETIC_PREFIXES)
                 or any(p in ("tests", "examples") for p in parts))
    for i, line in enumerate(text.splitlines(), 1):
        for m in PHONE_RE.finditer(line):
            findings.append((rel, i, "疑似手机号 %s…" % m.group(0)[:3]))
        for m in IDCARD_RE.finditer(line):
            findings.append((rel, i, "疑似身份证号 %s…" % m.group(0)[:4]))
        for m in FORM_LINK_RE.finditer(line):
            if not synthetic and m.group(1) not in SAFE_TOKENS:
                findings.append((rel, i, "疑似真实活动链接 token：" + m.group(1)))
        for m in TOKEN_ASSIGN_RE.finditer(line):
            if m.group(1) not in SAFE_TOKENS:
                findings.append((rel, i, "内置表单 token：" + m.group(1)))
        for m in SECRET_HINT_RE.finditer(line):
            findings.append((rel, i, "疑似硬编码凭据"))


def _scan_json(rel, text, findings):
    if _is_runtime_data(rel):
        return
    try:
        data = json.loads(text)
    except Exception:
        return
    stack = [data]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                key = str(k)
                if isinstance(v, (str, int, float)) and not _is_placeholder(str(v)):
                    value = str(v)
                    if key in PII_KEYS:
                        findings.append((rel, 0, "JSON 中键「%s」含非占位值" % key))
                    elif key in PII_KEYS_EN and (
                            PHONE_RE.search(value) or IDCARD_RE.search(value)
                            or __import__("re").fullmatch(r"\d{8,18}", value)):
                        findings.append((rel, 0, "JSON 中键「%s」含疑似标识号" % key))
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(x for x in cur if isinstance(x, (dict, list)))


def _check_name(name, rel, findings, is_dir=False):
    normalized = "/" + str(rel).replace("\\", "/")
    if (not is_dir and name.lower() in TRUSTED_CA_FILES
            and "/certs/" in normalized):
        return  # 随包 CA 根证书，不是私钥文件
    patterns = FORBIDDEN_DIRS if is_dir else FORBIDDEN_NAMES
    for pat in patterns:
        if pat.match(name):
            findings.append((rel, 0, "禁止出现的%s：%s" %
                             ("目录" if is_dir else "文件", name)))
            return


def scan_tree(root):
    findings = []
    root = Path(root)
    for dirpath, dirnames, filenames in __import__("os").walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and d != "__MACOSX"]
        rel_dir = Path(dirpath).relative_to(root)
        for d in dirnames:
            _check_name(d, str(rel_dir / d), findings, is_dir=True)
        for name in filenames:
            if name.startswith("._"):
                continue
            rel = str(rel_dir / name) if str(rel_dir) != "." else name
            _check_name(name, rel, findings)
            if name in SKIP_FILES or Path(name).suffix.lower() in BINARY_EXT:
                continue
            try:
                text = Path(dirpath, name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            _scan_text(rel, text, findings)
            if name.lower().endswith(".json"):
                _scan_json(rel, text, findings)
    return findings


def scan_dmg(path):
    """挂载 DMG 后按目录扫描；仅 macOS 可用（Windows 上不会生成 DMG）。

    DMG 是二进制映像，无法像 zip 一样按条目读取，因此真实挂载后复用
    scan_tree；挂载失败视为扫描失败，绝不放行未检查的发布包。
    """
    if sys.platform != "darwin":
        return []
    mount = Path(tempfile.mkdtemp(prefix="jsj-dmg-"))
    proc = None
    try:
        proc = subprocess.run(
            ["hdiutil", "attach", "-nobrowse", "-readonly",
             "-mountpoint", str(mount), str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            return [(str(path), 0, "DMG 挂载失败：" +
                     proc.stderr.decode("utf-8", "replace").strip()[:200])]
        return scan_tree(mount)
    finally:
        if proc is not None and proc.returncode == 0:
            subprocess.run(["hdiutil", "detach", str(mount)],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        shutil.rmtree(mount, ignore_errors=True)


def scan_artifact(path):
    """扫描发布包（zip / DMG / 已解包目录）。"""
    path = Path(path)
    if path.is_dir():
        return scan_tree(path)
    if path.suffix.lower() == ".dmg":
        return scan_dmg(path)
    findings = []
    if not zipfile.is_zipfile(path):
        return [(str(path), 0, "发布包既不是目录也不是有效 zip")]
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.startswith("__MACOSX/") or "/._" in name or name.startswith("._"):
                continue
            parts = name.rstrip("/").split("/")
            leaf = parts[-1] if parts else name
            if any(p in SKIP_DIRS for p in parts[:-1]):
                continue
            _check_name(leaf, name, findings, is_dir=info.is_dir())
            if info.is_dir() or leaf in SKIP_FILES or \
                    Path(leaf).suffix.lower() in BINARY_EXT:
                continue
            try:
                text = zf.read(info).decode("utf-8")
            except UnicodeDecodeError:
                continue
            _scan_text(name, text, findings)
            if leaf.lower().endswith(".json"):
                _scan_json(name, text, findings)
    return findings


def self_test():
    cases = [
        ('{"姓名": "张三"}', True),
        ('{"姓名": "<姓名占位>"}', False),
        ('电话：13800000000', True),
        ('DEFAULT_TOKEN = "AbCdEf9"', True),
        ('DEFAULT_TOKEN = ""', False),
        ('https://jsj.top/f/xxxxx', False),
        ('https://jsj.top/f/AbCdEf9', True),
    ]
    ok = True
    for text, should_hit in cases:
        found = []
        _scan_text("inline", text, found)
        if text.lstrip().startswith("{"):
            _scan_json("inline", text, found)
        hit = bool(found)
        status = "OK" if hit == should_hit else "FAIL"
        if hit != should_hit:
            ok = False
        print("  [%s] %-42s 检出=%s 预期=%s" % (status, text[:42], hit, should_hit))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="扫描仓库/发布包中的个人信息与敏感数据")
    ap.add_argument("--root", default=str(ROOT), help="要扫描的仓库根目录")
    ap.add_argument("--artifact", default="", help="额外扫描发布包（zip 或目录）")
    ap.add_argument("--strict", action="store_true", help="发现问题时返回退出码 1")
    ap.add_argument("--self-test", action="store_true", help="自检检测规则")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    findings = scan_tree(args.root)
    if args.artifact:
        findings += scan_artifact(args.artifact)
    seen, unique = set(), []
    for f in findings:
        key = tuple(f)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    if unique:
        print("发现 %d 处潜在敏感数据：" % len(unique))
        for rel, line, reason in unique:
            print("  - %s%s : %s" % (rel, (":%d" % line) if line else "", reason))
    else:
        print("PII scan OK：未发现内置个人信息、真实活动链接或凭据。")
    return 1 if (unique and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
