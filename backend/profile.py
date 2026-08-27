"""词力等级 / 单词树：全部从现有学习表实时推导，不建解锁流水（同 achievements 哲学）。

"活跃"口径 = union(daily_log / daily_practice_log / daily_challenge 的日期)，
任何模式的练习都算给树浇水。它与统计页的"连续打卡"（仅 daily_log 的听打/背诵）
刻意区分：选词、冲刺、每日挑战同样维持小树，但不计入听打打卡。
"""
from datetime import date, timedelta

from flask import Blueprint

from .auth import get_user, resp
from .db import db
from .misc import day_streak

bp = Blueprint("profile", __name__)

# 等级累计经验门槛与称号（阈值数据表而非公式，方便单独调整）；超出末级停在"词神"
LEVELS = [
    (0, "词童"), (100, "词苗"), (300, "词芽"), (600, "词木"), (1000, "词林"),
    (1600, "词丘"), (2400, "词峰"), (3500, "词海"), (5000, "词宗"),
    (7500, "词圣"), (10000, "词神"),
]

TREE_ICONS = ["🌰", "🌱", "🌿", "🪴", "🌳", "🌳", "🌸", "🍎"]
TREE_LABELS = ["种子", "发芽", "幼苗", "成株", "小树", "繁茂", "开花", "硕果"]
TREE_MAX_STAGE = len(TREE_LABELS) - 1


def level_of(xp):
    """按累计经验求等级；xp 恒 >= 0 时返回值在 1..len(LEVELS) 内。"""
    level = 1
    for i, (floor, _) in enumerate(LEVELS):
        if xp >= floor:
            level = i + 1
    return level


# 经验权重：答对是主体，背词与新词加权，错题/跳过也给少量"努力分"。
# leaderboard 的全员窗口聚合按字段名引用同一份权重，公式改一处即两处同步。
XP_WEIGHTS = {
    "final_right": 10, "new": 3, "effort": 2,
    "memorize_right": 5, "daily_right": 10, "daily_wrong": 2,
}


def xp_of(conn, user):
    """累计经验值（整史单人口径，与 leaderboard 的窗口聚合共用 XP_WEIGHTS）。

    独立成函数：derive_profile 与 friends 的升级动态探测共用同一公式。
    """
    w = XP_WEIGHTS
    pr = conn.execute(
        "SELECT COALESCE(SUM(final_right_count),0) fr, COALESCE(SUM(new_count),0) nw, "
        "COALESCE(SUM(first_wrong_count),0)+COALESCE(SUM(skipped_count),0) fs "
        "FROM daily_practice_log WHERE user=?", (user,)).fetchone()
    mem = conn.execute(
        "SELECT COALESCE(SUM(memorize_right),0) m FROM daily_log WHERE user=?",
        (user,)).fetchone()
    dc = conn.execute(
        "SELECT COALESCE(SUM(score),0) s, COALESCE(SUM(total-score),0) w "
        "FROM daily_challenge WHERE user=?", (user,)).fetchone()
    return (pr["fr"] * w["final_right"] + pr["nw"] * w["new"] + pr["fs"] * w["effort"]
            + mem["m"] * w["memorize_right"]
            + dc["s"] * w["daily_right"] + dc["w"] * w["daily_wrong"])


def derive_profile(conn, user):
    """在调用方持有的连接上推导等级与树状态；本模块与 daily 共用。"""
    today = date.today()

    xp = xp_of(conn, user)
    daily_count = conn.execute(
        "SELECT COUNT(*) c FROM daily_challenge WHERE user=?", (user,)).fetchone()["c"]

    level = level_of(xp)
    floor, title = LEVELS[level - 1]
    nxt = LEVELS[level][0] if level < len(LEVELS) else None
    span = (nxt - floor) if nxt else 1
    progress = round(min(1.0, (xp - floor) / span), 4)

    days = {r["day"] for r in conn.execute(
        "SELECT day FROM daily_log WHERE user=?", (user,))}
    days |= {r["day"] for r in conn.execute(
        "SELECT DISTINCT day FROM daily_practice_log WHERE user=?", (user,))}
    days |= {r["day"] for r in conn.execute(
        "SELECT day FROM daily_challenge WHERE user=?", (user,))}

    streak = day_streak(days)
    today_iso = today.isoformat()
    total_active = sum(1 for d in days if d <= today_iso)
    today_done = today_iso in days
    last_active = max((d for d in days if d <= today_iso), default=None)
    missed = (today - date.fromisoformat(last_active)).days if last_active else None

    # 树：断水 ≥2 天（今天和昨天都没练）才算枯萎；昨天练过只是"口渴"
    wilted = bool(days) and streak == 0 and (missed or 0) >= 2
    stage = 0 if (wilted or not days) else min(streak, TREE_MAX_STAGE)
    icon = "🥀" if wilted else TREE_ICONS[stage]
    label = "枯萎" if wilted else TREE_LABELS[stage]

    dc_days = [r["day"] for r in conn.execute(
        "SELECT day FROM daily_challenge WHERE user=? ORDER BY day", (user,))]

    monday = today - timedelta(days=today.weekday())
    week = [{"day": (monday + timedelta(days=i)).isoformat(),
             "active": (monday + timedelta(days=i)).isoformat() in days}
            for i in range(7)]

    return {
        "xp": xp, "level": level, "title": title,
        "level_floor": floor, "next_level_xp": nxt, "level_progress": progress,
        "streak": streak, "today_done": today_done,
        "total_active_days": total_active,
        "last_active_day": last_active, "missed_days": missed or 0,
        "tree_stage": stage, "tree_max_stage": TREE_MAX_STAGE,
        "tree_icon": icon, "tree_label": label,
        "tree_wilted": wilted, "tree_needs_water": not today_done and streak > 0,
        "daily_count": daily_count, "daily_streak": day_streak(dc_days),
        "daily_done_today": today.isoformat() in set(dc_days),
        "week": week,
    }


@bp.get("/api/profile")
def api_profile():
    user = get_user()
    with db() as conn:
        return resp(derive_profile(conn, user))
