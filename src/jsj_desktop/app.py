# -*- coding: utf-8 -*-
"""程序入口：默认启动原生图形界面；保留可选的终端模式与无头自检。

    python -m jsj_desktop                     # 图形界面（默认，推荐）
    python -m jsj_desktop --cli --link URL    # 可选终端模式（自动化/CI）
    python -m jsj_desktop --self-test         # 无界面自检（不联网）
"""
import argparse
import os
import sys
from pathlib import Path

from .core.mapping import InputProvider


def _reconfigure_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


class ConsoleSink:
    """可选终端模式的事件输出。"""

    def __init__(self):
        self.attributes = {}

    def log(self, level, text):
        print(text, flush=True)

    def state(self, **kwargs):
        pass

    def form(self, info):
        pass

    def preview(self, attributes, display, fields):
        self.attributes = attributes

    def finished(self, summary):
        pass


class ConsoleInputProvider(InputProvider):
    """与旧版 auto_submit.py 的交互菜单完全一致的终端应答。"""

    @staticmethod
    def _ask(prompt, default=None):
        try:
            s = input(prompt)
        except EOFError:
            print()
            return default if default is not None else ""
        s = s.strip()
        return s if s != "" else (default if default is not None else "")

    def ask_text(self, field, default_code):
        default = default_code or ""
        tip = f"（回车=保留“{default}”）" if default else ""
        while True:
            val = self._ask(f"  请输入【{field['label']}】{tip}：", default)
            if val or not field["required"]:
                return val
            print("    该项为必填，不能为空。")

    def ask_single(self, field, default_code):
        choices = field["choices"]
        names = [n for _v, n in choices]
        def_idx = next((i for i, (v, _n) in enumerate(choices)
                        if v == default_code), None)
        print(f"  请选择【{field['label']}】：")
        for i, n in enumerate(names, 1):
            tag = "（回车=默认）" if def_idx == i - 1 else ""
            print(f"    {i:>2}. {n}{tag}")
        hint = f"（回车={names[def_idx]}）" if def_idx is not None else ""
        while True:
            raw = self._ask(f"  输入序号 1-{len(names)}{hint}：",
                            str(def_idx + 1) if def_idx is not None else None)
            if raw and raw.isdigit() and 1 <= int(raw) <= len(names):
                return choices[int(raw) - 1][0]
            print("    输入无效，请输入菜单上的数字序号。")

    def ask_multi(self, field, default_codes):
        choices = field["choices"]
        default_codes = default_codes or []
        def_idx = {i for i, (v, _n) in enumerate(choices) if v in default_codes}
        print(f"  请选择【{field['label']}】（可多选，序号用逗号分隔，如 1,3）：")
        for i, (_v, n) in enumerate(choices, 1):
            tag = "（默认已选）" if i - 1 in def_idx else ""
            print(f"    {i:>2}. {n}{tag}")
        def_hint = ",".join(str(i + 1) for i in sorted(def_idx))
        while True:
            raw = self._ask(f"  输入序号，多个用逗号分隔（回车={def_hint or '不选'}）：",
                            def_hint if def_hint else None)
            if not raw:
                return [choices[i][0] for i in sorted(def_idx)]
            parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
            if all(p.isdigit() and 1 <= int(p) <= len(choices) for p in parts) \
                    and len(set(parts)) == len(parts):
                return [choices[int(p) - 1][0] for p in parts]
            print("    输入无效，请输入 1-%d 的数字序号并用逗号分隔。" % len(choices))


def run_cli(args):
    from .core.engine import RunConfig, TaskContext, run
    from .data.config_store import ConfigStore
    from .data import paths as data_paths

    if args.data_dir:
        os.environ["JSJ_DATA_DIR"] = str(Path(args.data_dir).resolve())
    store = ConfigStore(data_paths.task_config_path("t1"),
                        data_paths.task_config_backup_path("t1"))
    cfg = RunConfig(link=args.link, quick=args.quick, dry=args.dry_run,
                    auto_reply=True, modify=args.modify,
                    time_mode=args.time_mode, manual_time=args.manual_time,
                    lead=args.lead, interval=args.interval, timeout=args.timeout)
    ctx = TaskContext("t1", store, cfg, sink=ConsoleSink(),
                      provider=ConsoleInputProvider())
    summary = run(ctx)
    return 0 if summary.get("ok") else 1


def run_gui(args):
    if args.data_dir:
        os.environ["JSJ_DATA_DIR"] = str(Path(args.data_dir).resolve())
    try:
        from .ui.main_window import MainWindow
    except ImportError as e:
        print("无法启动图形界面：%s" % e)
        print("请使用官方 Python 安装包并勾选 Tcl/Tk 组件，或改用 --cli 模式。",
              file=sys.stderr)
        return 2
    app = MainWindow()
    app.mainloop()
    return 0


def run_self_test():
    """无界面、无网络的逻辑自检（合成数据，不涉及任何个人信息）。"""
    from .core.endpoint import Endpoint
    from .core.engine import EventSink, RunConfig, TaskContext, run
    from .core.mapping import (build_attributes, config_to_chosen)
    from .data.config_store import ConfigStore
    from .data.paths import resource_path
    import tempfile

    fixture = Path(resource_path("tests/fixtures/sample_form.json"))
    with open(fixture, "r", encoding="utf-8") as fp:
        import json
        payload = json.load(fp)

    class FakeEndpoint(Endpoint):
        def post_json(self, _payload, timeout=15):
            return 200, payload, None

    class CollectSink(EventSink):
        def __init__(self):
            self.lines, self.attributes = [], None

        def log(self, level, text):
            self.lines.append(text)

        def preview(self, attributes, display, fields):
            self.attributes = attributes

    with tempfile.TemporaryDirectory() as tmp:
        store = ConfigStore(Path(tmp) / "报名信息.json")
        store.write("https://jsj.top/f/EXAMPLE", {
            "姓名": "<姓名占位>", "学号": "<学号占位>",
            "培养层次": "硕士", "年级": "2024级", "班级": "甲班",
            "电话": "<电话占位>"})
        cfg = RunConfig(link="https://jsj.top/f/EXAMPLE", dry=True,
                        auto_reply=True)
        sink = CollectSink()
        ctx = TaskContext("t1", store, cfg, sink=sink,
                          endpoint=FakeEndpoint())
        summary = run(ctx)
        fields = payload["data"]["publishedForm"]["form"]["fields"]["nodes"]
        normalized = [{"api": n["apiCode"], "label": n["label"],
                       "typename": n["__typename"],
                       "required": "presence" in (n.get("validations") or []),
                       "multi": n["__typename"] == "Checkboxes",
                       "choices": [(c["value"], c["name"])
                                   for c in (n.get("choices") or [])]}
                      for n in fields]
        expected, _ = build_attributes(
            normalized,
            {r["target"]: r for r in payload["data"]["publishedForm"]["form"]
             .get("fieldRulesGroupByTarget", [])},
            config_to_chosen(store.read(), normalized))
        assert sink.attributes == expected, "自检失败：演练输出与预期不一致"
        assert summary["state"] == "exited", "自检失败：演练状态异常"
    print("self-test OK: 核心逻辑、联动规则、演练数据生成均正常（未联网）。")
    return 0


def run_tls_check():
    """诊断 HTTPS 证书链与网络连通性（只读 GET，不会提交任何报名数据）。

    macOS 命令行用法：
        JinshujuDesktop.app/Contents/MacOS/JinshujuDesktop --check-tls
    """
    import ssl
    import urllib.error
    import urllib.request
    print("=== HTTPS / 证书链诊断 ===")
    print("Python      : %s | 平台: %s | 冻结: %s" %
          (sys.version.split()[0], sys.platform,
           getattr(sys, "frozen", False)))
    print("SSL_CERT_FILE: %s" %
          (os.environ.get("SSL_CERT_FILE") or "(未设置，使用系统默认)"))
    paths = ssl.get_default_verify_paths()
    print("默认 CA 路径 : cafile=%s capath=%s" % (paths.cafile, paths.capath))
    url = "https://jsj.top/"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            print("HTTPS 连通   : HTTP %s（TLS 证书验证通过）" % resp.status)
    except urllib.error.HTTPError as e:
        # 只要 TLS 握手成功，服务器返回 4xx/5xx 也说明证书链正常
        print("HTTPS 连通   : HTTP %s（TLS 证书验证通过）" % e.code)
    except Exception as e:
        print("HTTPS 失败   : %s: %s" % (type(e).__name__, str(e)[:300]))
        print("提示：若为 CERTIFICATE_VERIFY_FAILED，说明缺少 CA 根证书；"
              "请确认使用随包分发的 certs/cacert.pem。")
        return 1
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        description="金数据报名助手 · 桌面版（默认图形界面）")
    p.add_argument("--cli", action="store_true",
                   help="使用可选终端模式（默认启动图形界面）")
    p.add_argument("--self-test", action="store_true",
                   help="无界面逻辑自检（不联网）")
    p.add_argument("--check-tls", action="store_true",
                   help="诊断 HTTPS 证书链与网络连通性（只读，不提交数据）")
    p.add_argument("--version", action="version",
                   version="%(prog)s " + __import__(
                       "jsj_desktop", fromlist=["__version__"]).__version__)
    p.add_argument("--data-dir", default="", help="覆盖本地数据目录（测试/便携版）")
    p.add_argument("--link", default="", help="本次表单链接或末尾 token")
    p.add_argument("--quick", "-y", action="store_true", help="快速模式，不询问")
    p.add_argument("--dry-run", action="store_true", help="只演练，不提交")
    p.add_argument("--modify", action="store_true", help="启动时逐项确认信息")
    p.add_argument("--time-mode", default="1", choices=["1", "2", "3"])
    p.add_argument("--manual-time", default="", help="手动开放时间（北京时间）")
    p.add_argument("--lead", default="-6")
    p.add_argument("--interval", default="0.05")
    p.add_argument("--timeout", default="40")
    return p


def main(argv=None):
    _reconfigure_stdout()
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()
    if args.check_tls:
        return run_tls_check()
    if args.cli:
        return run_cli(args)
    return run_gui(args)
