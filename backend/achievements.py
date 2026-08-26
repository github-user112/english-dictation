"""成就徽章：从现有学习表实时推导，不额外建表、不存解锁流水。

前端用 localStorage 记住"已见过的已解锁集合"，新解锁时弹庆祝。
"""
from flask import Blueprint

from .auth import get_user, resp
from .db import db
from .misc import day_streak

bp = Blueprint("achievements", __name__)


@bp.get("/api/achievements")
def api_achievements():
    user = get_user()
    with db() as conn:
        daily = conn.execute(
            "SELECT day,right_count,wrong_count,new_count+review_count AS total "
            "FROM daily_log WHERE user=? ORDER BY day", (user,)).fetchall()
        total = sum(r["right_count"] + r["wrong_count"] for r in daily)
        streak = day_streak(r["day"] for r in daily)
        perfect = max(
            (r["right_count"] for r in daily if r["wrong_count"] == 0), default=0)
        lists_touched = conn.execute(
            "SELECT COUNT(DISTINCT list) c FROM word_state WHERE user=?", (user,)).fetchone()["c"]
        first = conn.execute(
            "SELECT COALESCE(SUM(first_right_count),0) fr, COALESCE(SUM(first_wrong_count),0) fw "
            "FROM daily_practice_log WHERE user=?", (user,)).fetchone()
        memorized = conn.execute(
            "SELECT COUNT(*) c FROM word_state WHERE user=? AND memorized=1", (user,)).fetchone()["c"]
        sprint = conn.execute(
            "SELECT score, combo FROM sprint_best WHERE user=?", (user,)).fetchone()
        dc_days = [r["day"] for r in conn.execute(
            "SELECT day FROM daily_challenge WHERE user=? ORDER BY day", (user,)).fetchall()]
        dc_best = conn.execute(
            "SELECT COALESCE(MAX(score),0) m FROM daily_challenge WHERE user=?",
            (user,)).fetchone()["m"]
        practice_days = {r["day"] for r in conn.execute(
            "SELECT DISTINCT day FROM daily_practice_log WHERE user=?", (user,))}

    first_attempts = (first["fr"] or 0) + (first["fw"] or 0)
    accuracy = (first["fr"] / first_attempts) if first_attempts else 0
    sprint_score = sprint["score"] if sprint else 0
    sprint_combo = sprint["combo"] if sprint else 0
    dc_streak = day_streak(dc_days)
    # 树的成长口径：听打/背诵打卡与选词、冲刺、每日挑战活跃日的 union（见 backend/profile.py）
    activity_streak = day_streak(set(dc_days) | {r["day"] for r in daily} | practice_days)

    # id, 图标, 标题, 描述, 当前进度, 目标（进度>=目标 即解锁）
    defs = [
        ("first-word", "🌱", "启程", "完成第 1 个词", total, 1),
        ("words-100", "💯", "百词斩", "累计听打 100 词", total, 100),
        ("words-500", "🪓", "五百流沙", "累计听打 500 词", total, 500),
        ("words-2000", "🏔️", "两千词海", "累计听打 2000 词", total, 2000),
        ("streak-7", "🔥", "七日之约", "连续打卡 7 天", streak, 7),
        ("streak-30", "🌙", "卅日不辍", "连续打卡 30 天", streak, 30),
        ("perfect-day", "✨", "完美一天", "单日答对 20 词且零错", perfect, 20),
        ("sprint-30", "⚡", "冲刺新手", "限时冲刺得 30 分", sprint_score, 30),
        ("sprint-80", "🏆", "冲刺大师", "限时冲刺得 80 分", sprint_score, 80),
        ("combo-20", "🎯", "连击之王", "冲刺连击 ×20", sprint_combo, 20),
        ("explorer-3", "🧭", "博闻强识", "在 3 个素材库留下足迹", lists_touched, 3),
        ("sniper-90", "🎖️", "神射手", "首答正确率 ≥90%（≥100 次首答）",
         round(accuracy * 100) if first_attempts >= 100 else 0, 90),
        ("memorize-100", "🧠", "背词机器", "背下 100 个词", memorized, 100),
        ("daily-streak-7", "🗓️", "每日之约", "每日挑战连续 7 天", dc_streak, 7),
        ("daily-perfect", "🌟", "十全十美", "每日挑战一次全对（≥10 题）", dc_best, 10),
        ("tree-full", "🌳", "枝繁叶茂", "连续活跃 7 天让小树结果",
         min(activity_streak, 7), 7),
    ]
    return resp({"badges": [
        {"id": bid, "icon": icon, "title": title, "desc": desc,
         "progress": min(progress, target), "target": target, "unlocked": progress >= target}
        for bid, icon, title, desc, progress, target in defs
    ]})
