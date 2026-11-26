# -*- coding: utf-8 -*-
"""
【只读参考实现 · 请勿运行、请勿修改】
======================================================================
本文件是旧版 auto_submit.py 的逐行副本，唯一改动是移除了内置的真实活动
表单 token（DEFAULT_TOKEN 置空），以满足「仓库与发布包不含敏感数据」的要求。
它不参与桌面版任何运行时逻辑，仅供 tests/test_legacy_parity.py 做等价性
对照：验证 config_to_chosen / chosen_to_config / is_visible /
build_attributes / build_input / parse_form_url 的输出与原版完全一致。

金数据表单开放后自动填写并提交脚本（通用表单链接 + 报名信息可修改版）
======================================================================
★ 每次活动的表单链接不同，运行时粘贴本次链接即可：
  1. 双击「启动自动提交.bat」；
  2. 按提示粘贴本次表单链接（形如 https://jsj.top/f/xxxxx，
     也可只输入链接末尾的 xxxxx），直接回车则复用上次链接；
  3. 按菜单填写/确认姓名、学号、层次、年级、班级、电话等信息，
     会自动保存到「报名信息.json」，同名字段下次自动带出；
  4. 脚本自动校验、校时、等待开放，在开放瞬间毫秒级高频提交，
     成功立即停止，不会重复提交。

原理：
  - 金数据表单【未启用验证码】时，可直接调用网页前端同款 GraphQL 接口
    （createPublishedFormEntry），无需浏览器、无需登录。
  - 表单字段、选项、联动显示规则、开放时间全部在运行时从接口动态拉取，
    按“培养层次→年级→班级”等联动规则，只提交当前实际可见的字段，
    与网页端行为完全一致；换任何同结构活动表都无需改代码。
  - 所有填写、翻译、校验均在等待开放前完成；冲刺阶段是毫秒级纯接口
    提交，填信息不会让提交变慢。

依赖：仅 Python 3 标准库（无需 pip install 任何东西）。
运行：python auto_submit.py                 交互式（输入链接 + 确认/修改信息）
      python auto_submit.py --quick         不询问，直接使用「报名信息.json」
      python auto_submit.py --link 链接     命令行直接指定本次表单链接
      python auto_submit.py --dry-run       只演练（自检+生成数据，不提交）
"""

import json
import os
import re
import sys
import time
import random
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# Windows 控制台中文输入/输出
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ============================================================
# 一、全局配置
# ============================================================
# 北京时间
CST = timezone(timedelta(hours=8))

# 报名信息配置文件（与本脚本放在同一目录）
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "报名信息.json")

# 表单端点（运行时按用户输入的链接设置；下面是首次运行的默认链接）
DEFAULT_BASE_URL = "https://jsj.top"
DEFAULT_TOKEN = ""  # 原版内置的真实活动 token 已移除（隐私要求）
BASE_URL = DEFAULT_BASE_URL
TOKEN = DEFAULT_TOKEN
FORM_URL = f"{BASE_URL}/f/{TOKEN}"
GRAPHQL_URL = f"{BASE_URL}/graphql/f/{TOKEN}"

# 冲刺默认参数（交互模式下每次运行会再问一次，直接回车=用下面默认值；
# --quick 模式不询问，直接使用这里的默认值）
DEFAULT_LEAD_SECONDS = -6      # 开放前多少秒开始高频提交（正数=提前冲，覆盖网络往返）
DEFAULT_INTERVAL = 0.05         # 冲刺期间每次提交间隔（秒）；越小越快，<0.02 易被风控
DEFAULT_RUSH_TIMEOUT = 40      # 开放后最长冲刺秒数（超时则放弃）
# 运行时由 ask_rush_config() 覆盖；这里保留为兜底默认
LEAD_SECONDS = DEFAULT_LEAD_SECONDS
INTERVAL = DEFAULT_INTERVAL
RUSH_TIMEOUT = DEFAULT_RUSH_TIMEOUT
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 这些错误文案表示“还没到点 / 稍等”，应继续重试
RETRY_KEYWORDS = ("暂未开放", "未开放", "还没", "尚未", "未开始", "稍后", "频繁",
                  "请稍后", "再试", "too many", "not open", "closed", "timeout",
                  "超时", "网络", "502", "503", "504")

# 这些字段类型无法用纯文本/选项表达，遇到且为可见必填时需明确提示
UNSUPPORTED_TOKENS = ("matrix", "upload", "file", "image", "payment",
                      "goods", "signature", "address", "department",
                      "location", "idcard", "resume")

# ============================================================
# 二、表单链接解析
# ============================================================
_URL_RE = re.compile(r"https?://([a-zA-Z0-9.\-]+)/f/([A-Za-z0-9]+)")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{4,}$")


def parse_form_url(text):
    """从用户输入解析 (base_url, token, form_url)，无法识别返回 None。
    支持完整链接（任意金数据域名，可带查询参数）或仅输入 token。"""
    t = (text or "").strip()
    m = _URL_RE.search(t)
    if m:
        host, token = m.group(1), m.group(2)
        base = f"https://{host}"
        return base, token, f"{base}/f/{token}"
    if _TOKEN_RE.match(t):
        return DEFAULT_BASE_URL, t, f"{DEFAULT_BASE_URL}/f/{t}"
    return None


def setup_endpoint(base_url, token):
    """根据本次表单链接设置全局提交端点。"""
    global BASE_URL, TOKEN, FORM_URL, GRAPHQL_URL
    BASE_URL = base_url
    TOKEN = token
    FORM_URL = f"{BASE_URL}/f/{TOKEN}"
    GRAPHQL_URL = f"{BASE_URL}/graphql/f/{TOKEN}"


# ============================================================
# 三、HTTP 基础
# ============================================================
def http_post_json(payload, timeout=15):
    """POST GraphQL，返回 (http_status, data_dict, server_date_str)。"""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL, data=body, method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": BASE_URL,
            "Referer": FORM_URL,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(raw), resp.headers.get("Date")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), e.headers.get("Date")
        except Exception:
            return e.code, {"_raw": raw}, e.headers.get("Date")
    except Exception as e:
        # 网络层错误
        return -1, {"_network_error": repr(e)}, None


def gql(query, variables=None, timeout=15):
    return http_post_json({"query": query, "variables": variables or {}}, timeout)


# ============================================================
# 四、动态拉取表单结构（字段 / 选项 / 联动规则 / 开放时间）
# ============================================================
CHECK_QUERY = """
query Q($id: ID!) {
  publishedForm(id: $id) {
    status { key }
    form {
      name
      setting { enableCaptcha }
      fields {
        nodes {
          __typename
          ... on BaseField { label apiCode type validations }
          ... on SelectableField { choices { ... on TextChoice { value name } } }
        }
      }
      fieldRulesGroupByTarget {
        target
        mode
        conditionGroup {
          operator
          conditionGroups {
            operator
            conditions { trigger comparator value }
          }
        }
      }
    }
    interceptionSetting {
      byTimeRangeCloseRule { startTime endTime }
    }
  }
}
"""

MUTATION = """
mutation CreatePublishedFormEntry($input: CreatePublishedFormEntryInput!) {
  createPublishedFormEntry(input: $input) {
    errors { code message }
    redirectUrl
    paymentUrl
    entryToken
    editToken
    submitterExists
    customerExists
    identityFieldLabel
  }
}
"""


def fetch_form():
    """拉取本次表单结构。
    成功返回 dict(ok=True, fields, rules, name, status, captcha, open_dt)；
    失败返回 dict(ok=False, error=说明)。"""
    result = {"ok": False, "error": "", "fields": [], "rules": {},
              "name": "", "status": "", "captcha": False, "open_dt": None}

    status, data, _ = gql(CHECK_QUERY, {"id": TOKEN})
    if status == -1:
        result["error"] = f"网络请求失败：{data.get('_network_error', '')}"
        return result
    if status != 200 or "data" not in data or not data.get("data"):
        result["error"] = f"表单接口返回异常（HTTP {status}）：" \
                          f"{json.dumps(data, ensure_ascii=False)[:300]}"
        return result

    pf = data["data"]["publishedForm"]
    if not pf:
        result["error"] = "找不到该表单（链接或 token 可能有误，或表单已删除）。"
        return result

    form = pf["form"]
    result["ok"] = True
    result["name"] = form.get("name", "")
    result["status"] = (pf.get("status") or {}).get("key", "")
    result["captcha"] = bool(form["setting"].get("enableCaptcha"))

    fields = []
    for n in form["fields"]["nodes"]:
        api = n.get("apiCode")
        typename = n.get("__typename") or n.get("type") or ""
        choices = [(c.get("value"), c.get("name"))
                   for c in (n.get("choices") or [])]
        fields.append({
            "api": api,
            "label": n.get("label") or api,
            "typename": typename,
            "required": "presence" in (n.get("validations") or []),
            "multi": typename == "Checkboxes",   # 多选题
            "choices": choices,                  # 非空=选择类字段
        })
    result["fields"] = fields

    rules = {}
    for r in (form.get("fieldRulesGroupByTarget") or []):
        rules[r["target"]] = r
    result["rules"] = rules

    rule = (pf.get("interceptionSetting") or {}
            ).get("byTimeRangeCloseRule") or {}
    start = rule.get("startTime")
    if start:
        result["open_dt"] = datetime.fromisoformat(start).astimezone(CST)
    return result


# ============================================================
# 五、联动规则求值（决定字段当前是否可见）
# ============================================================
def _eval_branch(branch, chosen):
    """求值一个条件组（组内条件按其 operator 组合，报名表中都是 and）。"""
    conds = branch.get("conditions") or []
    vals = []
    for cond in conds:
        trigger = cond.get("trigger")
        cur = chosen.get(trigger)
        wanted = cond.get("value") or []
        comp = cond.get("comparator")
        if comp == "not_equal":
            vals.append(cur is not None and cur not in wanted)
        else:  # equal（金数据显示规则的默认比较符）
            vals.append(cur is not None and cur in wanted)
    op = (branch.get("operator") or "and").lower()
    return all(vals) if op == "and" else any(vals)


def _branches_contradictory(branches):
    """检测多个条件组在 AND 语义下是否根本不可同时满足：
    即同一触发字段在不同组里被要求取不同的值。
    金数据表单里“在所有情况下都显示”的字段（如电话），设计器会把每种
    路径各存成一个条件组（外层却标记为 and），此时网页端实际按“任一组
    满足即显示”处理。"""
    per_branch = []
    for b in branches:
        m = {}
        for c in b.get("conditions", []):
            if c.get("comparator") == "equal":
                m.setdefault(c.get("trigger"), set()).update(c.get("value") or [])
        per_branch.append(m)
    triggers = set().union(*[set(m) for m in per_branch]) if per_branch else set()
    for t in triggers:
        seen = [m[t] for m in per_branch if t in m]
        if len(seen) >= 2 and any(a != b for a, b in zip(seen, seen[1:])):
            return True
    return False


def is_visible(field, rules, chosen):
    """按联动规则判断字段当前是否显示。无规则=始终显示。
    - 顶层 operator=or：任一组满足即显示；
    - 顶层 operator=and：所有组都满足才显示（如“2024硕士班级”要求
      硕士 AND 2024级）；
    - 但 and 各组互相矛盾（同一触发字段要求不同值）时，按网页端实际
      行为退化为“任一组满足即显示”（如“电话”字段）。"""
    rule = rules.get(field["api"])
    if not rule:
        return True
    group = rule.get("conditionGroup") or {}
    branches = group.get("conditionGroups") or []
    if not branches:
        return True
    results = [_eval_branch(b, chosen) for b in branches]
    op = (group.get("operator") or "and").lower()
    if op == "or":
        return any(results)
    if all(results):
        return True
    if _branches_contradictory(branches):
        return any(results)
    return False


# ============================================================
# 六、报名信息配置文件（按字段中文标签存储）
# ============================================================
def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception as e:
            print(f"⚠ 读取「报名信息.json」失败，将重新填写：{e}")
    return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(cfg, fp, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠ 保存「报名信息.json」失败（不影响本次提交）：{e}")


def config_to_chosen(cfg, fields):
    """把 JSON 中按标签存的中文值，翻译成 {apiCode: 编码/文本}。
    找不到匹配字段或选项的旧值自动忽略（换表单后不会误用）。"""
    chosen = {}
    for f in fields:
        raw = cfg.get(f["label"])
        if raw is None or raw == "":
            continue
        if f["choices"]:
            name_map = {n: v for v, n in f["choices"]}
            if f["multi"]:
                items = raw if isinstance(raw, list) else \
                    [x.strip() for x in str(raw).replace("，", ",").split(",")]
                codes = [name_map[n] for n in items if n in name_map]
                if codes:
                    chosen[f["api"]] = codes
            else:
                if str(raw) in name_map:
                    chosen[f["api"]] = name_map[str(raw)]
        else:
            chosen[f["api"]] = str(raw)
    return chosen


def chosen_to_config(form_url, fields, chosen):
    """把当前选择转回可手编的中文配置（仅保留本次表单字段）。"""
    cfg = {"表单链接": form_url}
    for f in fields:
        v = chosen.get(f["api"])
        if v is None or v == "" or v == []:
            continue
        if f["choices"]:
            name_map = {val: n for val, n in f["choices"]}
            if f["multi"]:
                cfg[f["label"]] = [name_map.get(x, x) for x in v]
            else:
                cfg[f["label"]] = name_map.get(v, v)
        else:
            cfg[f["label"]] = v
    return cfg


# ============================================================
# 七、交互填写
# ============================================================
def _ask(prompt, default=None):
    try:
        s = input(prompt)
    except EOFError:
        print()
        return default if default is not None else ""
    s = s.strip()
    return s if s != "" else (default if default is not None else "")


def ask_text(field, default_code):
    """文本类字段，required 时不允许空。"""
    default = default_code or ""
    tip = f"（回车=保留“{default}”）" if default else ""
    while True:
        val = _ask(f"  请输入【{field['label']}】{tip}：", default)
        if val or not field["required"]:
            return val
        print("    该项为必填，不能为空。")


def ask_single(field, default_code):
    """单选菜单，返回选项 value 编码。"""
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
        raw = _ask(f"  输入序号 1-{len(names)}{hint}：",
                   str(def_idx + 1) if def_idx is not None else None)
        if raw and raw.isdigit() and 1 <= int(raw) <= len(names):
            return choices[int(raw) - 1][0]
        print("    输入无效，请输入菜单上的数字序号。")


def ask_multi(field, default_codes):
    """多选菜单，输入逗号分隔的序号，返回 value 编码列表。"""
    choices = field["choices"]
    default_codes = default_codes or []
    def_idx = {i for i, (v, _n) in enumerate(choices) if v in default_codes}
    print(f"  请选择【{field['label']}】（可多选，序号用逗号分隔，如 1,3）：")
    for i, (_v, n) in enumerate(choices, 1):
        tag = "（默认已选）" if i - 1 in def_idx else ""
        print(f"    {i:>2}. {n}{tag}")
    def_hint = ",".join(str(i + 1) for i in sorted(def_idx))
    while True:
        raw = _ask(f"  输入序号，多个用逗号分隔（回车={def_hint or '不选'}）：",
                   def_hint if def_hint else None)
        if not raw:
            return [choices[i][0] for i in sorted(def_idx)]
        parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
        if all(p.isdigit() and 1 <= int(p) <= len(choices) for p in parts) \
                and len(set(parts)) == len(parts):
            return [choices[int(p) - 1][0] for p in parts]
        print("    输入无效，请输入 1-%d 的数字序号并用逗号分隔。" % len(choices))


def unsupported_field(field):
    return any(tok in field["typename"].lower() for tok in UNSUPPORTED_TOKENS)


def fill_form(fields, rules, chosen, only_missing=False):
    """按表单顺序逐项填写；每填一个选项就重新计算后续字段可见性。
    only_missing=True 时只补填当前缺失/无效的必填项。"""
    for f in fields:
        if not is_visible(f, rules, chosen):
            chosen.pop(f["api"], None)
            continue

        cur = chosen.get(f["api"])
        valid = True
        if f["choices"]:
            valid_codes = {v for v, _n in f["choices"]}
            if f["multi"]:
                valid = isinstance(cur, list) and cur and \
                        all(x in valid_codes for x in cur)
            else:
                valid = cur in valid_codes
        else:
            valid = bool(cur) or not f["required"]
        if only_missing and valid:
            continue

        if unsupported_field(f):
            raise ValueError(
                f"字段【{f['label']}】的类型 {f['typename']} 暂不支持自动填写"
                f"（如附件/矩阵/支付等），请在网页端手动填写或联系脚本维护。")

        if f["choices"]:
            if f["multi"]:
                chosen[f["api"]] = ask_multi(f, cur if isinstance(cur, list) else [])
            else:
                chosen[f["api"]] = ask_single(f, cur)
        else:
            chosen[f["api"]] = ask_text(f, cur if isinstance(cur, str) else "")
    return chosen


def show_info(fields, rules, chosen, form_url, form_name):
    print("=" * 64)
    print(f"表单：{form_name}")
    print(f"链接：{form_url}")
    print("-" * 64)
    shown = 0
    for f in fields:
        if not is_visible(f, rules, chosen):
            continue
        shown += 1
        v = chosen.get(f["api"])
        if f["choices"]:
            name_map = {val: n for val, n in f["choices"]}
            if f["multi"]:
                text = "、".join(name_map.get(x, x) for x in (v or [])) or "（未选）"
            else:
                text = name_map.get(v, "（未选）")
        else:
            text = v if v else "（未填）"
        print(f"  {f['label']:<10}：{text}")
    print("=" * 64)
    return shown


# ============================================================
# 八、构建最终提交数据
# ============================================================
def build_attributes(fields, rules, chosen):
    """只提交当前可见字段，单选交编码、多选交编码数组、文本交字符串。
    返回 (attributes, display)。"""
    attributes, display = {}, {}
    for f in fields:
        if not is_visible(f, rules, chosen):
            continue
        api = f["api"]
        v = chosen.get(api)
        if f["choices"]:
            name_map = {val: n for val, n in f["choices"]}
            if f["multi"]:
                codes = v or []
                bad = [x for x in codes if x not in name_map]
                if bad:
                    raise ValueError(f"【{f['label']}】存在无效选项编码：{bad}")
                attributes[api] = codes
                display[api] = "、".join(name_map.get(x, x) for x in codes)
            else:
                if v not in name_map:
                    raise ValueError(f"【{f['label']}】未选择有效选项。")
                attributes[api] = v
                display[api] = name_map[v]
        else:
            if f["required"] and not v:
                raise ValueError(f"【{f['label']}】为必填项但内容为空。")
            attributes[api] = v if v is not None else ""
            display[api] = str(attributes[api])
    return attributes, display


# ============================================================
# 九、服务器时间校准
# ============================================================
def calibrate_clock(samples=6):
    """通过多次请求用 Date 头估算本地时钟与服务器的偏移（秒）。
    返回 offset = 服务器时间 - 本地时间（正数表示本地钟慢）。"""
    offsets = []
    for _ in range(samples):
        t0 = time.time()
        status, _, date_str = http_post_json(
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
        print("⚠ 无法获取服务器时间，使用本地时钟（请确认本机时间准确）。")
        return 0.0
    offsets.sort()
    offset = offsets[len(offsets) // 2]
    print(f"时间校准完成：本地时钟与服务器偏差 {offset:+.3f} 秒"
          f"（正=本地慢，负=本地快），采样 {len(offsets)} 次。\n")
    return offset


def now_server(offset):
    return time.time() + offset


# ============================================================
# 十、提交判定
# ============================================================
ENTRY_ATTRIBUTES = {}  # 冲刺开始前由 main 填充


def build_input(filling_duration):
    return {
        "formId": TOKEN,
        "entryAttributes": ENTRY_ATTRIBUTES,
        "fillingDuration": round(filling_duration, 2),
        "forceSubmit": False,
        "hasPreferential": False,
    }


def submit_once(filling_duration):
    """提交一次。返回 (状态, 说明)。
    状态：'success' / 'wait'（未开放，继续） / 'fatal'（业务错误，停止） / 'net'（网络错误，重试）。"""
    status, data, _ = gql(MUTATION, {"input": build_input(filling_duration)}, timeout=12)
    if status == -1:
        return "net", data.get("_network_error", "网络错误")

    if "data" not in data:
        return "fatal", "GraphQL错误：" + json.dumps(data.get("errors"), ensure_ascii=False)[:500]

    node = (data.get("data") or {}).get("createPublishedFormEntry") or {}
    errors = node.get("errors")
    token = node.get("entryToken")

    if token and not errors:
        return "success", json.dumps(node, ensure_ascii=False)

    if errors:
        for e in errors:
            msg = str(e.get("message", ""))
            code = e.get("code")
            if node.get("submitterExists") or node.get("customerExists") \
               or any(k in msg for k in ("重复", "已经提交", "已存在", "已有", "提交过")):
                return "maybe", msg
            if any(k in msg.lower() if k.isascii() else k in msg for k in RETRY_KEYWORDS):
                return "wait", msg
            if code in (403, 429, 503):
                return "wait", f"[{code}] {msg}"
        return "fatal", json.dumps(errors, ensure_ascii=False)[:500]

    return "wait", "未拿到成功凭证，继续等待"


# ============================================================
# 十一、链接获取
# ============================================================
def resolve_form(cfg, args):
    """确定本次表单链接并拉取结构。
    返回 (info, form_url)；quick 模式失败直接退出，交互模式允许重输。"""
    saved_url = cfg.get("表单链接") or f"{DEFAULT_BASE_URL}/f/{DEFAULT_TOKEN}"
    candidates = []
    if args.link:
        candidates = [args.link]
    elif args.quick:
        candidates = [saved_url]
    else:
        print("=" * 64)
        print("步骤 1：指定本次活动的表单链接")
        print("=" * 64)
        print("请输入完整链接（如 https://jsj.top/f/xxxxx），")
        print("或只输入链接末尾的 xxxxx；直接回车=使用上次链接。")
        first = _ask(f"本次表单链接（回车={saved_url}）：", saved_url)
        candidates = [first]

    for idx, cand in enumerate(candidates):
        parsed = parse_form_url(cand)
        if not parsed:
            msg = f"无法识别的链接：{cand}"
            if args.quick:
                print("❌", msg)
                return None, None
            print("⚠", msg)
            candidates.append(_ask("请重新输入：", ""))
            continue
        base, token, form_url = parsed
        setup_endpoint(base, token)
        print(f"\n正在获取表单结构：{form_url} …")
        info = fetch_form()
        if info["ok"]:
            return info, form_url
        print("⚠ 获取表单失败：", info["error"])
        if args.quick:
            return None, None
        nxt = _ask("按回车重试，或重新输入表单链接（输入 q 退出）：", "")
        if nxt.strip().lower() in ("q", "quit", "退出"):
            return None, None
        candidates.append(nxt or cand)
    return None, None


# ============================================================
# 十二、开放时间与冲刺速度确认（每次活动可改，不强制固定值）
# ============================================================
def _ask_float(prompt, default):
    """读一个浮点数，空行=默认。"""
    s = _ask(f"{prompt} [默认 {default}]: ", str(default))
    if not s:
        return float(default)
    try:
        return float(s)
    except ValueError:
        print(f"  ⚠ 输入“{s}”不是数字，沿用默认 {default}")
        return float(default)


def _ask_manual_epoch():
    """循环读 YYYY-MM-DD HH:MM:SS（北京时间），返回 epoch。"""
    while True:
        s = _ask("请输入目标开放时间（北京时间，格式 2026-11-05 20:00:00）：", "")
        if not s:
            continue
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                    "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
            try:
                dt = datetime.strptime(s, fmt).replace(tzinfo=CST)
                print(f"  ✓ 已设定目标时间：{dt.strftime('%Y-%m-%d %H:%M:%S')}")
                return dt.timestamp()
            except ValueError:
                continue
        print("  ⚠ 格式不对，请用类似 2026-11-05 20:00:00 的格式重输。")


def ask_rush_config(info, args):
    """确认本次「目标开放时间」和「冲刺速度」。
    返回 (open_epoch, lead_seconds, interval, rush_timeout)。
    open_epoch=None 表示不等待、立即提交。
    --quick 模式跳过所有询问，直接用表单时间 + 默认参数。"""
    lead = DEFAULT_LEAD_SECONDS
    interval = DEFAULT_INTERVAL
    rush_timeout = DEFAULT_RUSH_TIMEOUT

    print("\n" + "=" * 64)
    print("步骤：确认本次「目标开放时间」与「冲刺速度」")
    print("=" * 64)

    form_epoch = info["open_dt"].timestamp() if info["open_dt"] else None

    # ---- 快速模式：不打扰，用默认 ----
    if args.quick:
        if form_epoch is not None:
            open_epoch = form_epoch
            t_txt = info["open_dt"].strftime('%Y-%m-%d %H:%M:%S')
        else:
            open_epoch = None
            t_txt = "立即提交"
        print(f"[--quick] 开放时间：{t_txt}")
        print(f"[--quick] 冲刺参数：提前 {lead}s / 间隔 {interval}s / 时长 {rush_timeout}s\n")
        return open_epoch, lead, interval, rush_timeout

    # ---- 1) 目标开放时间 ----
    if form_epoch is not None:
        print(f"表单返回开放时间：{info['open_dt'].strftime('%Y-%m-%d %H:%M:%S')}（北京时间）")
        print("  [1] 使用表单返回的这个时间")
        print("  [2] 手动指定另一个时间（接口时间不准 / 想演练时选这个）")
        print("  [3] 不等待，立即提交")
        c = _ask("请选择 [1/2/3，默认1]：", "1").strip()
        if c == "2":
            open_epoch = _ask_manual_epoch()
        elif c == "3":
            open_epoch = None
        else:
            open_epoch = form_epoch
    else:
        print("未从表单获取到定时开放时间（表单可能已开放或无需定时）。")
        s = _ask("回车=立即开始提交；如需指定开放时间，请输入北京时间（2026-11-05 20:00:00）：", "")
        if not s:
            open_epoch = None
        else:
            open_epoch = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                        "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
                try:
                    open_epoch = datetime.strptime(s, fmt).replace(tzinfo=CST).timestamp()
                    break
                except ValueError:
                    continue
            if open_epoch is None:
                print("  ⚠ 时间格式无法识别，按立即提交处理。")

    # ---- 2) 冲刺速度 ----
    print("\n当前冲刺参数（直接回车=使用默认，也可逐项改）：")
    print("  · 提前量：开放前多少秒开始高频提交；网络慢/跨网就调大（如 1.5~3）")
    print("  · 提交间隔：每两次提交间隔秒数；越小越快，<0.02 易被风控拦截")
    print("  · 冲刺时长：开放后持续尝试多少秒就停手提示手动填")
    lead = _ask_float("开放前多少秒开始提交", DEFAULT_LEAD_SECONDS)
    interval = _ask_float("每次提交间隔秒数", DEFAULT_INTERVAL)
    rush_timeout = _ask_float("开放后最长冲刺多少秒就停", DEFAULT_RUSH_TIMEOUT)

    if open_epoch is not None:
        print(f"\n✓ 目标开放时间(服务器钟)：{datetime.fromtimestamp(open_epoch, CST).strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print("\n✓ 目标：立即提交（不等待定时）")
    print(f"✓ 本次参数：提前 {lead}s 开始，每 {interval}s 提交一次，最长冲 {rush_timeout}s\n")
    return open_epoch, lead, interval, rush_timeout


# ============================================================
# 十三、主流程
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="金数据表单毫秒级自动提交（通用链接版）")
    parser.add_argument("--quick", "-y", action="store_true",
                        help="不询问，直接使用「报名信息.json」中的链接与信息")
    parser.add_argument("--link", default="",
                        help="本次表单链接（也可直接粘贴 URL 或 token）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只演练：自检+生成提交数据，不实际提交")
    args = parser.parse_args()

    print("=" * 64)
    print("金数据表单自动提交脚本（通用链接 + 报名信息可修改版）")
    print("=" * 64)

    cfg = load_config()
    info, form_url = resolve_form(cfg, args)
    if info is None:
        print("已退出。")
        return

    fields, rules = info["fields"], info["rules"]
    print(f"\n表单名称   : {info['name']}")
    print(f"当前状态   : {info['status']}")
    print(f"验证码     : {'启用' if info['captcha'] else '未启用（可直接提交）'}")
    if info["open_dt"]:
        print(f"开放时间(北京): {info['open_dt'].strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"字段数     : {len(fields)}（含联动字段，将按规则动态取舍）")

    if info["captcha"]:
        print("\n❌ 该表单启用了验证码，纯接口提交无法通过，需改用浏览器方案。")
        return

    # 把已保存配置翻译成选择值
    chosen = config_to_chosen(cfg, fields)

    # 检查必填是否齐全、有效；不齐全则自动进入逐项填写
    try:
        fill_form(fields, rules, chosen, only_missing=True)
    except ValueError as e:
        print("❌", e)
        return

    if not args.quick:
        print()
        show_info(fields, rules, chosen, form_url, info["name"])
        ans = _ask("回车 = 使用以上信息直接开始；输入 m 后回车 = 逐项修改：", "go")
        if ans.strip().lower() in ("m", "mod", "edit", "改", "修改"):
            print("\n开始逐项确认（每项直接回车可保留原值）：")
            try:
                fill_form(fields, rules, chosen, only_missing=False)
            except ValueError as e:
                print("❌", e)
                return
            show_info(fields, rules, chosen, form_url, info["name"])

    # 保存（按本次表单字段重建，旧表单残留字段自动清除）
    new_cfg = chosen_to_config(form_url, fields, chosen)
    save_config(new_cfg)
    print(f"（信息已保存到 {os.path.basename(CONFIG_PATH)}）\n")

    # 构建最终提交数据
    try:
        attributes, display = build_attributes(fields, rules, chosen)
    except ValueError as e:
        print("❌ 报名信息有误：", e)
        return
    global ENTRY_ATTRIBUTES
    ENTRY_ATTRIBUTES = attributes

    print("=" * 64)
    print(f"将提交的信息（共 {len(attributes)} 项，按表单联动自动选取）：")
    for f in fields:
        if f["api"] not in attributes:
            continue
        print(f"  {f['label']:<12}：{display[f['api']]}"
              f"（提交值 {attributes[f['api']]}）")
    print("=" * 64)

    if args.dry_run:
        print("\n[dry-run] 演练结束：自检与提交数据生成均正常，未发送任何提交请求。")
        print("[dry-run] 最终 entryAttributes =",
              json.dumps(attributes, ensure_ascii=False))
        return

    # 时间校准
    offset = calibrate_clock()
    # 确认目标开放时间 + 冲刺速度（交互模式会问；--quick 用默认）
    open_epoch, lead_seconds, interval, rush_timeout = ask_rush_config(info, args)

    if open_epoch is None:
        open_epoch_local = time.time()
        print("🚀 表单无需等待，立即开始冲刺提交…")
    else:
        # 等待到开放前 lead_seconds 秒（心跳逻辑与旧版一致）
        last_beat = 0.0
        while True:
            now = now_server(offset)
            remain = open_epoch - now
            if remain <= lead_seconds:
                break
            ts = datetime.now(CST).strftime("%H:%M:%S")
            if remain > 60:
                if now - last_beat >= 30:
                    mins = int(remain // 60)
                    print(f"[{ts}] 正常运行中，距开放还有 {mins // 60} 小时 {mins % 60} 分，"
                          f"本窗口保持打开即可…")
                    last_beat = now
                time.sleep(5)
            elif remain > 5:
                if now - last_beat >= 5:
                    print(f"[{ts}] 距开放约 {remain:5.1f} 秒，等待中…")
                    last_beat = now
                time.sleep(1)
            else:
                print(f"[{ts}] 距开放约 {remain:5.2f} 秒，进入临战状态…")
                time.sleep(0.05)
        open_epoch_local = open_epoch - offset
        print("\n🚀 开始冲刺提交…")

    # 高频冲刺（毫秒级，逻辑与旧版完全一致）
    rush_start_local = time.time()
    attempt = 0
    success = False
    while time.time() - rush_start_local < rush_timeout:
        attempt += 1
        fd = round(max(0.5, time.time() - open_epoch_local), 2)
        st, info_msg = submit_once(fd)
        rel = (now_server(offset) - open_epoch) if open_epoch is not None else 0.0
        ts = datetime.now(CST).strftime("%H:%M:%S.%f")[:-3]

        if st == "success":
            print(f"[{ts}] 第 {attempt} 次：✅ 提交成功！约在开放后 {rel:.2f} 秒完成。")
            print("返回凭证：", info_msg)
            success = True
            break
        elif st == "maybe":
            print(f"[{ts}] 第 {attempt} 次：⚠ 提示“{info_msg}”。"
                  f"该学号很可能已提交成功（重试命中），停止以防重复。")
            success = True
            break
        elif st == "fatal":
            print(f"[{ts}] 第 {attempt} 次：❌ 业务错误，停止：{info_msg}")
            break
        elif st == "net":
            print(f"[{ts}] 第 {attempt} 次：网络异常，立即重试：{info_msg}")
            time.sleep(0.05)
        else:  # wait
            if attempt <= 6 or attempt % 10 == 0:
                print(f"[{ts}] 第 {attempt} 次：未开放（{info_msg}），开放后 {rel:+.2f}s，继续…")
            time.sleep(interval + random.uniform(0, 0.03))

    print("\n" + "=" * 64)
    if success:
        print("🎉 已完成。请在表单页面/短信/邮件中确认报名结果。")
    else:
        print("⏱ 冲刺超时未成功。请立即手动打开表单填写：", FORM_URL)
    print("=" * 64)


if __name__ == "__main__":
    main()
