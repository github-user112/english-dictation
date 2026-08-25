"""FSRS-4.5 简化调度器（官方默认权重）。

只负责“下次复习间隔”：输入当前记忆状态与新答题评级，输出更新后的
稳定性/难度与间隔天数。掌握度状态机（learning/known）仍由调用方维护，
本模块保持纯函数、无 IO，便于单元测试。

评级映射（由练习信号推导）：
  grade 1 = Again 本次最终答错
  grade 2 = Hard  重试后答对（首答曾错）
  grade 3 = Good  首答即对
"""
import math
from datetime import date

F = 19.0 / 81.0                    # 幂式衰减因子
DECAY = -0.5                       # FSRS-4.5 固定衰减指数
RETENTION = 0.90                   # 目标记住率
W = [0.4872, 1.4003, 3.7145, 13.8206, 5.1618, 1.2298, 0.8975, 0.031,
     1.6474, 0.1367, 1.0461, 2.1072, 0.0793, 0.3246, 1.587, 0.2224, 2.8955]


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def retrievability(elapsed_days, stability):
    """经过 elapsed_days 后还记得的概率。"""
    if not stability or stability <= 0:
        return 0.0
    if elapsed_days <= 0:
        return 1.0
    return (1 + F * elapsed_days / stability) ** DECAY


def next_interval(stability):
    """达到目标记住率所需的间隔天数（90% 记住率时约等于稳定性天数）。"""
    t = stability / F * (RETENTION ** (1 / DECAY) - 1)
    return int(_clamp(round(t), 1, 365))


def _init(grade):
    g = _clamp(grade, 1, 3)
    return {
        "stability": W[g - 1],
        "difficulty": _clamp(W[4] - (g - 3) * W[5], 1.0, 10.0),
    }


def _mean_revert(difficulty):
    return _clamp(W[5] * W[4] + (1 - W[5]) * difficulty, 1.0, 10.0)


def review(state, grade, elapsed_days):
    """给定旧状态（可为 None）与本次评级，返回 ({stability,difficulty}, 间隔天数)。"""
    grade = _clamp(grade, 1, 3)
    if not state or not state.get("stability"):
        fresh = _init(grade)
        return fresh, next_interval(fresh["stability"])

    s = max(0.1, float(state["stability"]))
    d = _clamp(float(state.get("difficulty") or 5.0), 1.0, 10.0)
    r = retrievability(elapsed_days, s)

    if grade == 1:
        # 遗忘：稳定性坍缩，难度上调
        raw = W[11] * d ** (-W[12]) * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))
        new_s = _clamp(raw, 0.01, s)
        new_d = _mean_revert(d + W[6] * 2)
    else:
        delta_d = -W[6] * (grade - 3)          # Hard(2) 上调一点，Good(3) 不变
        new_d = _mean_revert(d + delta_d)
        # 官方 FSRS-4.5 增长式末项是 (e^{w9(1-r)} - 1)：r=1（当天刚练过）时恰好零增长；
        # 漏掉 -1 会让同日重复刷题把稳定性按 ~1.69 倍连乘，几次就把间隔吹到数百天
        grow = 1 + math.exp(W[7]) * (11 - d) * s ** (-W[8]) * (math.exp(W[9] * (1 - r)) - 1)
        if grade == 2:
            grow *= W[15]                       # Hard 惩罚
        new_s = s * grow

    return {"stability": new_s, "difficulty": new_d}, next_interval(new_s)


def days_between(prev_day, today_iso):
    """last_seen → 今天的自然日差；解析失败返回 0。"""
    try:
        return max(0, (date.fromisoformat(today_iso) - date.fromisoformat(prev_day)).days)
    except (TypeError, ValueError):
        return 0
