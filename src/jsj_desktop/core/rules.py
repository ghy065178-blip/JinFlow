# -*- coding: utf-8 -*-
"""联动显示规则求值（决定字段当前是否可见）。

与旧版 auto_submit.py 第五节逐行等价；前端旧版 control_panel.html 中的
JS 版 isVisible 也由同一套语义实现，现统一由本模块提供唯一实现。
"""


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
    """检测多个条件组在 AND 语义下是否根本不可同时满足。

    金数据表单里「在所有情况下都显示」的字段（如电话），设计器会把每种
    路径各存成一个条件组（外层却标记为 and），此时网页端实际按「任一组
    满足即显示」处理。
    """
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
    """按联动规则判断字段当前是否显示。无规则=始终显示。"""
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
