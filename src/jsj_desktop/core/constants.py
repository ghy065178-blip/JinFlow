# -*- coding: utf-8 -*-
"""全局常量：与旧版 auto_submit.py 的常量逐项一致。

唯一差异：旧版内置了一个具体活动的表单 token（DEFAULT_TOKEN）。
出于隐私与通用性要求，桌面版不再内置任何活动链接，首次使用必须由用户
填写表单链接或在本地「报名信息.json」中保留上次链接；解析裸 token 时
仍使用公开的默认域名 DEFAULT_BASE_URL。
"""
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python 3.11+ always provides zoneinfo
    ZoneInfo = None
    ZoneInfoNotFoundError = LookupError

# 北京时间（所有开放时间、倒计时、手动时间均按此时区解释）
try:
    CST = ZoneInfo("Asia/Shanghai") if ZoneInfo else timezone(timedelta(hours=8))
except ZoneInfoNotFoundError:
    CST = timezone(timedelta(hours=8))


def now_beijing(value=None):
    """将当前或传入的带时区时间转换为 Asia/Shanghai。"""
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=CST)
    return value.astimezone(CST)


def format_beijing_time(value=None):
    return now_beijing(value).strftime("%H:%M:%S")

DEFAULT_BASE_URL = "https://jsj.top"

# 冲刺默认参数：与旧版默认值一致，可在界面中逐任务修改
DEFAULT_LEAD_SECONDS = -6      # 开放前多少秒起跑；负数=开放后再跑
DEFAULT_INTERVAL = 0.05         # 冲刺期间每次提交间隔（秒）
DEFAULT_RUSH_TIMEOUT = 40      # 开放后最长冲刺秒数

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

RETRY_KEYWORDS = ("暂未开放", "未开放", "还没", "尚未", "未开始", "稍后", "频繁",
                  "请稍后", "再试", "too many", "not open", "closed", "timeout",
                  "超时", "网络", "502", "503", "504")

UNSUPPORTED_TOKENS = ("matrix", "upload", "file", "image", "payment",
                      "goods", "signature", "address", "department",
                      "location", "idcard", "resume")

# 表单结构查询：与旧版 CHECK_QUERY 完全一致
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

# 提交变更：与旧版 MUTATION 完全一致
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

CONFIG_LINK_KEY = "表单链接"
MAX_TASKS = 8
