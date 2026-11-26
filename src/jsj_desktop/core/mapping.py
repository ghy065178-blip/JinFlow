# -*- coding: utf-8 -*-
"""报名信息配置 ↔ 提交数据的翻译、校验与最终 entryAttributes 构建。

与旧版 auto_submit.py 第六、七、八节逐行等价：
  * config_to_chosen / chosen_to_config 保持按「字段中文标签」存储的格式；
  * build_attributes 是提交数据的唯一出口，输出与旧版完全一致；
  * fill_form 的填写算法不变，仅把 input() 换成可注入的 InputProvider。
"""
from .constants import CONFIG_LINK_KEY, UNSUPPORTED_TOKENS
from .rules import is_visible


class InputProvider:
    """填写缺失字段时的应答来源（GUI 弹窗 / 自动应答 / 控制台）。"""

    def ask_text(self, field, default_code):
        return default_code or ""

    def ask_single(self, field, default_code):
        return default_code

    def ask_multi(self, field, default_codes):
        return default_codes or []


class DefaultProvider(InputProvider):
    """自动应答：一律沿用配置文件中的旧值/默认值，不弹窗。"""


def load_config(path):
    import json
    import os
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return {}
    return {}


def save_config(path, cfg):
    import json
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(cfg, fp, ensure_ascii=False, indent=2)


def config_to_chosen(cfg, fields):
    """把 JSON 中按标签存的中文值，翻译成 {apiCode: 编码/文本}。

    找不到匹配字段或选项的旧值自动忽略（换表单后不会误用）。
    """
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
    cfg = {CONFIG_LINK_KEY: form_url}
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


def unsupported_field(field):
    return any(tok in field["typename"].lower() for tok in UNSUPPORTED_TOKENS)


def fill_form(fields, rules, chosen, provider=None, only_missing=False):
    """按表单顺序逐项填写；每填一个选项就重新计算后续字段可见性。

    only_missing=True 时只补填当前缺失/无效的必填项。
    """
    provider = provider or DefaultProvider()
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
                chosen[f["api"]] = provider.ask_multi(
                    f, cur if isinstance(cur, list) else [])
            else:
                chosen[f["api"]] = provider.ask_single(f, cur)
        else:
            chosen[f["api"]] = provider.ask_text(
                f, cur if isinstance(cur, str) else "")
    return chosen


def display_rows(fields, rules, chosen):
    """等价于旧版 show_info()，以数据形式返回当前可见字段的展示值。"""
    rows = []
    for f in fields:
        if not is_visible(f, rules, chosen):
            continue
        v = chosen.get(f["api"])
        if f["choices"]:
            name_map = {val: n for val, n in f["choices"]}
            if f["multi"]:
                text = "、".join(name_map.get(x, x) for x in (v or [])) or "（未选）"
            else:
                text = name_map.get(v, "（未选）")
        else:
            text = v if v else "（未填）"
        rows.append((f["label"], text))
    return rows


def build_attributes(fields, rules, chosen):
    """只提交当前可见字段，单选交编码、多选交编码数组、文本交字符串。

    返回 (attributes, display)；attributes 即最终 entryAttributes。
    """
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
