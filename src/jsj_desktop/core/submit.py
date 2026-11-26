# -*- coding: utf-8 -*-
"""服务器校时、提交请求体构造与提交结果判定。

与旧版 auto_submit.py 第九、十节逐行等价：同样的 GraphQL 变更、同样的
fillingDuration 计算方式、同样的 success / wait / fatal / net / maybe 判定。
"""
import json
import time
from datetime import datetime, timezone

from .constants import MUTATION, RETRY_KEYWORDS


def calibrate_clock(endpoint, samples=6, log=None):
    """通过多次请求用 Date 头估算本地时钟与服务器的偏移（秒）。

    返回 offset = 服务器时间 - 本地时间（正数表示本地钟慢）。
    注意：与原脚本一致，校时请求体只有 query 字段，不带 variables。
    """
    log = log or (lambda _text: None)
    offsets = []
    for _ in range(samples):
        t0 = time.time()
        status, _, date_str = endpoint.post_json(
            {"query": "{ __typename }"}, timeout=10)
        t1 = time.time()
        if not date_str:
            continue
        try:
            srv = datetime.strptime(
                date_str, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        rtt = t1 - t0
        local_mid = t0 + rtt / 2
        offsets.append(srv.timestamp() - local_mid)
        time.sleep(0.15)
    if not offsets:
        log("⚠ 无法获取服务器时间，使用本地时钟（请确认本机时间准确）。")
        return 0.0
    offsets.sort()
    offset = offsets[len(offsets) // 2]
    log(f"时间校准完成：本地时钟与服务器偏差 {offset:+.3f} 秒"
        f"（正=本地慢，负=本地快），采样 {len(offsets)} 次。")
    return offset


def build_input(token, attributes, filling_duration):
    """构造 CreatePublishedFormEntry 的 input，与旧版完全一致。"""
    return {
        "formId": token,
        "entryAttributes": attributes,
        "fillingDuration": round(filling_duration, 2),
        "forceSubmit": False,
        "hasPreferential": False,
    }


def submit_once(endpoint, token, attributes, filling_duration):
    """提交一次。返回 (状态, 说明)。

    状态：'success' / 'wait' / 'fatal' / 'net' / 'maybe'。
    """
    status, data, _ = endpoint.gql(
        MUTATION, {"input": build_input(token, attributes, filling_duration)},
        timeout=12)
    if status == -1:
        return "net", data.get("_network_error", "网络错误")

    if "data" not in data:
        return "fatal", "GraphQL错误：" + json.dumps(
            data.get("errors"), ensure_ascii=False)[:500]

    node = (data.get("data") or {}).get("createPublishedFormEntry") or {}
    errors = node.get("errors")
    entry_token = node.get("entryToken")

    if entry_token and not errors:
        return "success", json.dumps(node, ensure_ascii=False)

    if errors:
        for e in errors:
            msg = str(e.get("message", ""))
            code = e.get("code")
            if node.get("submitterExists") or node.get("customerExists") \
               or any(k in msg for k in ("重复", "已经提交", "已存在", "已有", "提交过")):
                return "maybe", msg
            if any(k in msg.lower() if k.isascii() else k in msg
                   for k in RETRY_KEYWORDS):
                return "wait", msg
            if code in (403, 429, 503):
                return "wait", f"[{code}] {msg}"
        return "fatal", json.dumps(errors, ensure_ascii=False)[:500]

    return "wait", "未拿到成功凭证，继续等待"
