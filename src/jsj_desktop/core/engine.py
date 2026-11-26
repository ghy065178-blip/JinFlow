# -*- coding: utf-8 -*-
"""主流程编排：把旧版 main() 的每一步搬到可由 GUI 驱动的后台线程。

业务流程、判定条件、请求体、等待/冲刺节奏与旧版完全一致；差异只有：
  * print()  → sink.log() 事件；
  * input()  → InputProvider（GUI 弹窗 / 自动应答 / 可选控制台）；
  * 无内置活动链接，首次需用户填写；
  * 增加 stop_event，使界面上的「停止」可安全中断等待与冲刺。
"""
import json
import random
import threading
import time
from datetime import datetime

from .constants import (CST, CONFIG_LINK_KEY, DEFAULT_INTERVAL,
                        DEFAULT_LEAD_SECONDS, DEFAULT_RUSH_TIMEOUT,
                        now_beijing)
from .endpoint import Endpoint
from .mapping import (InputProvider, build_attributes, chosen_to_config,
                      config_to_chosen, display_rows, fill_form)
from .submit import calibrate_clock, submit_once

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                 "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M")


def classify(text):
    """日志分级，与旧版 control_panel.classify 一致。"""
    if "✅" in text or "提交成功" in text or "已完成" in text:
        return "ok"
    if "❌" in text or "业务错误" in text or "冲刺超时" in text or "已退出" in text:
        return "error"
    if "⚠" in text or "网络异常" in text or "无法" in text:
        return "warn"
    if "🚀" in text or "开始冲刺" in text or "临战" in text:
        return "rush"
    if "未开放" in text or "等待中" in text:
        return "wait"
    return "info"


class EventSink:
    """默认空实现；GUI / 测试可覆写。"""

    def log(self, level, text):
        pass

    def state(self, **kwargs):
        pass

    def form(self, info):
        pass

    def preview(self, attributes, display, fields):
        pass

    def finished(self, summary):
        pass


class RunConfig:
    """一次运行的参数（与旧版控制面板提交的表单字段一一对应）。"""

    def __init__(self, link="", quick=False, dry=False, time_mode="1",
                 manual_time="", lead=None, interval=None, timeout=None,
                 auto_reply=True, modify=False):
        self.link = str(link or "").strip()
        self.quick = bool(quick)
        self.dry = bool(dry)
        self.time_mode = str(time_mode or "1")
        self.manual_time = str(manual_time or "").strip()
        self.lead = _as_float(lead, DEFAULT_LEAD_SECONDS)
        self.interval = _as_float(interval, DEFAULT_INTERVAL)
        self.timeout = _as_float(timeout, DEFAULT_RUSH_TIMEOUT)
        self.auto_reply = bool(auto_reply)
        self.modify = bool(modify)

    @classmethod
    def from_mapping(cls, data):
        return cls(
            link=data.get("link", ""), quick=data.get("quick", False),
            dry=data.get("dry", False), time_mode=data.get("time_mode", "1"),
            manual_time=data.get("manual_time", ""),
            lead=data.get("lead", DEFAULT_LEAD_SECONDS),
            interval=data.get("interval", DEFAULT_INTERVAL),
            timeout=data.get("timeout", DEFAULT_RUSH_TIMEOUT),
            auto_reply=data.get("auto_reply", True),
            modify=data.get("modify", False))

    def as_dict(self):
        return {"link": self.link, "quick": self.quick, "dry": self.dry,
                "time_mode": self.time_mode, "manual_time": self.manual_time,
                "lead": str(self.lead), "interval": str(self.interval),
                "timeout": str(self.timeout), "auto_reply": self.auto_reply,
                "modify": self.modify}


def _as_float(value, default):
    """与旧版 _ask_float 一致：非数字输入回落到默认值。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _parse_manual_time(text):
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=CST).timestamp()
        except ValueError:
            continue
    return None


class TaskContext:
    """引擎运行所需的全部依赖与运行态。"""

    def __init__(self, task_id, config_store, run, sink=None,
                 provider=None, endpoint=None, stop_event=None):
        self.task_id = task_id
        self.config_store = config_store
        self.run = run
        self.sink = sink or EventSink()
        self.provider = provider or InputProvider()
        self.endpoint = endpoint or Endpoint()
        self.stop_event = stop_event or threading.Event()
        self.attributes = {}
        self.offset = 0.0
        self.success = False
        self.attempt = 0
        self.summary = {}


def _emit_log(ctx, text, level=None):
    ctx.sink.log(level or classify(text), text)


def _emit_state(ctx, **kwargs):
    ctx.sink.state(**kwargs)


def run(ctx):
    """执行一次完整任务；返回 summary dict。等价于旧版 auto_submit.main()。"""
    cfg = ctx.config_store.read()
    run = ctx.run
    info = None
    form_url = ""

    try:
        # ---- 1) 表单链接（不再内置任何活动 token）----
        saved_url = str(cfg.get(CONFIG_LINK_KEY) or "").strip()
        candidate = run.link or saved_url
        if not candidate:
            _emit_log(ctx, "❌ 尚未设置表单链接，请在「运行配置」中填写本次表单链接。")
            return _finish(ctx, "没有表单链接")
        if not ctx.endpoint.set_from_link(candidate):
            _emit_log(ctx, "❌ 无法识别的链接：%s" % candidate)
            return _finish(ctx, "链接格式错误")
        form_url = ctx.endpoint.form_url
        _emit_log(ctx, "正在获取表单结构：%s …" % form_url)

        info = ctx.endpoint.fetch_form()
        if not info["ok"]:
            _emit_log(ctx, "⚠ 获取表单失败：%s" % info["error"])
            return _finish(ctx, info["error"])

        info["_form_url"] = form_url
        ctx.sink.form(info)
        fields, rules = info["fields"], info["rules"]
        _emit_log(ctx, "=" * 64)
        _emit_log(ctx, "金数据表单自动提交（桌面版 · 业务逻辑与旧版一致）")
        _emit_log(ctx, "表单名称   : %s" % info["name"])
        _emit_log(ctx, "当前状态   : %s" % info["status"])
        _emit_log(ctx, "验证码     : %s" %
                  ("启用" if info["captcha"] else "未启用（可直接提交）"))
        open_dt = info["open_dt"]
        if open_dt:
            _emit_log(ctx, "开放时间(北京): %s" %
                      open_dt.strftime("%Y-%m-%d %H:%M:%S"))
        _emit_log(ctx, "字段数     : %d（含联动字段，将按规则动态取舍）" % len(fields))
        _emit_state(ctx, state="preparing", phase="准备中",
                    form_name=info["name"], form_status=info["status"],
                    captcha="启用" if info["captcha"] else "未启用",
                    open_time=open_dt.strftime("%Y-%m-%d %H:%M:%S") if open_dt else "",
                    fields=len(fields))

        if info["captcha"]:
            _emit_log(ctx, "❌ 该表单启用了验证码，纯接口提交无法通过，需改用浏览器方案。")
            return _finish(ctx, "验证码拦截", state="failed", phase="验证码拦截")

        # ---- 2) 配置翻译 + 补填缺失项 ----
        chosen = config_to_chosen(cfg, fields)
        try:
            fill_form(fields, rules, chosen, ctx.provider, only_missing=True)
        except ValueError as e:
            _emit_log(ctx, "❌ %s" % e)
            return _finish(ctx, str(e), state="failed", phase="报名信息有误")

        if run.modify and not run.quick:
            _emit_log(ctx, "开始逐项确认（每项可直接保留原值）：")
            try:
                fill_form(fields, rules, chosen, ctx.provider,
                          only_missing=False)
            except ValueError as e:
                _emit_log(ctx, "❌ %s" % e)
                return _finish(ctx, str(e), state="failed", phase="报名信息有误")

        if not run.quick:
            for label, text in display_rows(fields, rules, chosen):
                _emit_log(ctx, "  %s：%s" % (label, text))

        # ---- 3) 保存配置（按本次表单字段重建，旧字段自动清除）----
        new_cfg = chosen_to_config(form_url, fields, chosen)
        ctx.config_store.write(new_cfg.get(CONFIG_LINK_KEY, ""),
                               {k: v for k, v in new_cfg.items()
                                if k != CONFIG_LINK_KEY})
        _emit_log(ctx, "（信息已保存到本地数据目录的 报名信息.json，并自动备份）")

        # ---- 4) 构建最终提交数据 ----
        try:
            attributes, display = build_attributes(fields, rules, chosen)
        except ValueError as e:
            _emit_log(ctx, "❌ 报名信息有误：%s" % e)
            return _finish(ctx, str(e), state="failed", phase="报名信息有误")
        ctx.attributes = attributes
        ctx.sink.preview(attributes, display, fields)
        _emit_state(ctx, submit_fields=len(attributes))
        _emit_log(ctx, "=" * 64)
        _emit_log(ctx, "将提交的信息（共 %d 项，按表单联动自动选取）：" % len(attributes))
        for f in fields:
            if f["api"] not in attributes:
                continue
            _emit_log(ctx, "  %s：%s（提交值 %s）" %
                      (f["label"], display[f["api"]], attributes[f["api"]]))
        _emit_log(ctx, "=" * 64)

        if run.dry:
            _emit_log(ctx, "[dry-run] 演练结束：自检与提交数据生成均正常，未发送任何提交请求。")
            _emit_log(ctx, "[dry-run] 最终 entryAttributes = " +
                      json.dumps(attributes, ensure_ascii=False))
            return _finish(ctx, "演练完成", state="exited", phase="演练完成")

        # ---- 5) 校时 ----
        offset = calibrate_clock(ctx.endpoint, log=lambda t: _emit_log(ctx, t))
        ctx.offset = offset
        _emit_state(ctx, offset=offset)

        # ---- 6) 目标开放时间与冲刺参数 ----
        form_epoch = open_dt.timestamp() if open_dt else None
        if run.quick:
            open_epoch = form_epoch
            lead, interval, rush_timeout = (DEFAULT_LEAD_SECONDS,
                                            DEFAULT_INTERVAL,
                                            DEFAULT_RUSH_TIMEOUT)
            _emit_log(ctx, "[--quick] 冲刺参数：提前 %ss / 间隔 %ss / 时长 %ss" %
                      (lead, interval, rush_timeout))
        else:
            lead, interval, rush_timeout = run.lead, run.interval, run.timeout
            if form_epoch is not None:
                if run.time_mode == "2":
                    open_epoch = _parse_manual_time(run.manual_time)
                    if open_epoch is None:
                        _emit_log(ctx, "⚠ 手动时间格式无法识别，按表单时间处理。")
                        open_epoch = form_epoch
                elif run.time_mode == "3":
                    open_epoch = None
                else:
                    open_epoch = form_epoch
            else:
                open_epoch = _parse_manual_time(run.manual_time) \
                    if run.time_mode == "2" and run.manual_time else None
            if open_epoch is not None:
                _emit_log(ctx, "✓ 目标开放时间(服务器钟)：%s" %
                          datetime.fromtimestamp(open_epoch, CST)
                          .strftime("%Y-%m-%d %H:%M:%S"))
            else:
                _emit_log(ctx, "✓ 目标：立即提交（不等待定时）")
            _emit_log(ctx, "✓ 本次参数：提前 %ss 开始，每 %ss 提交一次，最长冲 %ss" %
                      (lead, interval, rush_timeout))

        # ---- 7) 等待开放（心跳逻辑与旧版一致）----
        if open_epoch is None:
            open_epoch_local = time.time()
            _emit_log(ctx, "🚀 表单无需等待，立即开始冲刺提交…")
            _emit_state(ctx, state="rushing", phase="冲刺提交中",
                        last="立即开始高频提交")
        else:
            last_beat = 0.0
            while True:
                if ctx.stop_event.is_set():
                    return _finish(ctx, "已手动停止", state="stopped", phase="已手动停止")
                now = time.time() + offset
                remain = open_epoch - now
                if remain <= lead:
                    break
                ts = now_beijing().strftime("%H:%M:%S")
                if remain > 60:
                    if now - last_beat >= 30:
                        mins = int(remain // 60)
                        _emit_log(ctx, "[%s] 正常运行中，距开放还有 %d 小时 %d 分，"
                                  "保持窗口打开即可…" % (ts, mins // 60, mins % 60))
                        last_beat = now
                    wait = 5
                elif remain > 5:
                    if now - last_beat >= 5:
                        _emit_log(ctx, "[%s] 距开放约 %5.1f 秒，等待中…" % (ts, remain))
                        last_beat = now
                    wait = 1
                else:
                    _emit_log(ctx, "[%s] 距开放约 %5.2f 秒，进入临战状态…" % (ts, remain))
                    wait = 0.05
                _emit_state(ctx, state="waiting", phase="等待开放",
                            countdown=remain)
                ctx.stop_event.wait(wait)
            open_epoch_local = open_epoch - offset
            _emit_log(ctx, "🚀 开始冲刺提交…")
            _emit_state(ctx, state="rushing", phase="冲刺提交中",
                        last="开始高频提交", countdown=0.0)

        # ---- 8) 高频冲刺（毫秒级，逻辑与旧版完全一致）----
        rush_start_local = time.time()
        attempt = 0
        success = False
        while time.time() - rush_start_local < rush_timeout:
            if ctx.stop_event.is_set():
                return _finish(ctx, "已手动停止", state="stopped", phase="已手动停止")
            attempt += 1
            ctx.attempt = attempt
            fd = round(max(0.5, time.time() - open_epoch_local), 2)
            st, info_msg = submit_once(ctx.endpoint, ctx.endpoint.token,
                                       attributes, fd)
            rel = (time.time() + offset - open_epoch) if open_epoch is not None else 0.0
            ts = now_beijing().strftime("%H:%M:%S.%f")[:-3]

            if st == "success":
                _emit_log(ctx, "[%s] 第 %d 次：✅ 提交成功！约在开放后 %.2f 秒完成。"
                          % (ts, attempt, rel))
                _emit_log(ctx, "返回凭证：%s" % info_msg)
                success = True
                _emit_state(ctx, state="success", phase="提交成功",
                            attempt=attempt, last="已拿到 entryToken")
                break
            if st == "maybe":
                _emit_log(ctx, "[%s] 第 %d 次：⚠ 提示“%s”。"
                          "该学号很可能已提交成功（重试命中），停止以防重复。"
                          % (ts, attempt, info_msg))
                success = True
                _emit_state(ctx, state="success", phase="疑似已提交",
                            attempt=attempt, last="重复提交保护，已停手")
                break
            if st == "fatal":
                _emit_log(ctx, "[%s] 第 %d 次：❌ 业务错误，停止：%s"
                          % (ts, attempt, info_msg))
                _emit_state(ctx, state="failed", phase="业务错误",
                            attempt=attempt, last="业务错误，脚本停止")
                break
            if st == "net":
                _emit_log(ctx, "[%s] 第 %d 次：网络异常，立即重试：%s"
                          % (ts, attempt, info_msg))
                _emit_state(ctx, attempt=attempt, last="网络异常，重试中")
                ctx.stop_event.wait(0.05)
            else:  # wait
                if attempt <= 6 or attempt % 10 == 0:
                    _emit_log(ctx, "[%s] 第 %d 次：未开放（%s），开放后 %+.2fs，继续…"
                              % (ts, attempt, info_msg, rel))
                _emit_state(ctx, state="rushing", phase="冲刺提交中",
                            attempt=attempt, last="未开放：" + str(info_msg))
                ctx.stop_event.wait(interval + random.uniform(0, 0.03))

        _emit_log(ctx, "=" * 64)
        if success:
            _emit_log(ctx, "🎉 已完成。请在表单页面/短信/邮件中确认报名结果。")
        else:
            _emit_log(ctx, "⏱ 冲刺超时未成功。请立即手动打开表单填写：%s" % form_url)
        _emit_log(ctx, "=" * 64)
        return _finish(ctx, "已完成" if success else "冲刺超时未成功",
                       state="success" if success else "failed",
                       phase="提交成功" if success else "冲刺超时",
                       attempt=attempt, success=success)
    except Exception as e:  # 不让后台线程静默死掉
        import traceback
        _emit_log(ctx, "❌ 运行异常：%s\n%s" % (e, traceback.format_exc(limit=3)))
        return _finish(ctx, str(e), state="failed", phase="运行异常")


def _finish(ctx, reason, state="exited", phase="已结束", attempt=None,
            success=False):
    if attempt is not None:
        ctx.attempt = attempt
    ctx.success = success
    ctx.summary = {"ok": state in ("success", "exited"),
                   "state": state, "phase": phase, "reason": reason,
                   "attempt": ctx.attempt, "success": success,
                   "attributes": ctx.attributes}
    _emit_state(ctx, state=state, phase=phase, last=reason)
    ctx.sink.finished(ctx.summary)
    return ctx.summary
