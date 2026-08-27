"""全局排行榜：全部从现有学习表实时聚合，不建中间表、不需要各玩法上报。

不落 leaderboard 物化表的理由：本站规模下源表聚合是毫秒级查询，物化反而引入
"什么时候同步、怎么算周月窗口"两类陈旧性问题；sprint_best 没有逐局历史，
周期维度对它天然不成立，前端对该两个 scope 隐藏日/周筛选。

周期窗口按"当天日期"切：weekly 取本周一，monthly 取本月 1 号（本地时区）。
"""
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from .auth import display_names, get_user, resp
from .catalog import clamp_int
from .db import db
from .misc import day_streak
from .profile import LEVELS, XP_WEIGHTS, level_of

bp = Blueprint("leaderboard", __name__)

SCOPES = {"sprint", "daily", "xp", "streak", "accuracy"}
PERIODS = {"all", "monthly", "weekly"}
# 这两个 scope 的数值本身没有时间窗口（历史最高 / 当前连续），给别的 period 也只能等价于 all
PERIODLESS_SCOPES = {"sprint", "streak"}
DEFAULT_LIMIT = 50
ACCURACY_MIN_ATTEMPTS = 20   # 少于该首答数不参与正确率榜，避免 1/1 = 100% 刷榜


def _cutoff(period):
    """周期的统计起点（含）；all 返回 None 表示不限。"""
    today = date.today()
    if period == "weekly":
        return today - timedelta(days=today.weekday())
    if period == "monthly":
        return today.replace(day=1)
    return None


def _sprint_rows(conn):
    """冲刺历史最高分：sprint_best 每人一行，直接读。无周期口径。"""
    return {
        r["user"]: (r["score"], r["combo"], r["total"])
        for r in conn.execute("SELECT user, score, combo, total FROM sprint_best").fetchall()
    }


def _daily_rows(conn, cutoff):
    cond = "WHERE day>=?" if cutoff else ""
    args = ((cutoff.isoformat(),) if cutoff else ())
    vals = {}
    for r in conn.execute(
            f"SELECT user, MAX(score) best FROM daily_challenge {cond} GROUP BY user", args):
        vals[r["user"]] = r["best"]
    return vals


def _xp_rows(conn, cutoff):
    """经验值聚合。权重公式与 profile.xp_of 同源（XP_WEIGHTS），改这里必须同步那里，
    反之亦然——两处共用常量但查询形状不同（整史单人 vs 窗口全员）。"""
    day_cond = "AND day>=?" if cutoff else ""
    iso = (cutoff.isoformat(),) if cutoff else ()
    w = XP_WEIGHTS
    xs = defaultdict(float)
    for r in conn.execute(
            f"""SELECT user,
                       SUM(final_right_count)*{w['final_right']}
                     + SUM(new_count)*{w['new']}
                     + (SUM(first_wrong_count)+SUM(skipped_count))*{w['effort']} v
                FROM daily_practice_log
               WHERE user IS NOT NULL {day_cond} GROUP BY user""", iso):
        xs[r["user"]] += r["v"] or 0
    for r in conn.execute(
            f"""SELECT user, SUM(memorize_right)*{w['memorize_right']} v
                  FROM daily_log
                 WHERE user IS NOT NULL {day_cond} GROUP BY user""", iso):
        xs[r["user"]] += r["v"] or 0
    for r in conn.execute(
            f"""SELECT user,
                       SUM(score)*{w['daily_right']} + SUM(total-score)*{w['daily_wrong']} v
                  FROM daily_challenge
                 WHERE user IS NOT NULL {day_cond} GROUP BY user""", iso):
        xs[r["user"]] += r["v"] or 0
    return {u: int(v) for u, v in xs.items()}


# 连续打卡只回看这么多天：超过一年的断档必然清零，无需更久的历史
_STREAK_LOOKBACK_DAYS = 400


def _streak_rows(conn):
    """当前连续活跃天数，口径与 profile 一致：三类练习日期的并集。"""
    floor = (date.today() - timedelta(days=_STREAK_LOOKBACK_DAYS)).isoformat()
    days = defaultdict(set)
    for sql in ("SELECT DISTINCT user, day FROM daily_log WHERE day>=?",
                "SELECT DISTINCT user, day FROM daily_practice_log WHERE day>=?",
                "SELECT DISTINCT user, day FROM daily_challenge WHERE day>=?"):
        for r in conn.execute(sql, (floor,)):
            days[r["user"]].add(r["day"])
    return {u: day_streak(d) for u, d in days.items()}


def _accuracy_rows(conn, cutoff):
    cond = "WHERE 1=1" + (" AND day>=?" if cutoff else "")
    args = ((cutoff.isoformat(),) if cutoff else ())
    rows = conn.execute(
        f"""SELECT user, SUM(first_right_count) fr, SUM(first_wrong_count) fw
              FROM daily_practice_log {cond} GROUP BY user
             HAVING fr + fw >= ?""", (*args, ACCURACY_MIN_ATTEMPTS)).fetchall()
    return {r["user"]: r["fr"] / (r["fr"] + r["fw"]) for r in rows}


@bp.get("/api/leaderboard")
def api_leaderboard():
    scope = request.args.get("scope", "sprint")
    if scope not in SCOPES:
        return jsonify({"error": f"未知榜单：{scope}"}), 400
    period = request.args.get("period", "all")
    if period not in PERIODS:
        return jsonify({"error": f"未知周期：{period}"}), 400
    if scope in PERIODLESS_SCOPES:
        period = "all"
    limit = clamp_int(request.args.get("limit"), DEFAULT_LIMIT, 1, 100)
    cutoff = _cutoff(period)

    with db() as conn:
        if scope == "sprint":
            by_user = _sprint_rows(conn)   # {user: (score, combo, total)}
            keyed = {u: v[0] for u, v in by_user.items()}
        elif scope == "daily":
            keyed = _daily_rows(conn, cutoff)
        elif scope == "xp":
            keyed = _xp_rows(conn, cutoff)
        elif scope == "streak":
            keyed = _streak_rows(conn)
        else:
            keyed = _accuracy_rows(conn, cutoff)

        names = display_names(conn, keyed.keys())

    # 并列分数次序稳定：分数降序后按用户 id 兜底，避免同分名次抖动
    ordered = sorted(keyed.items(), key=lambda kv: (-kv[1], kv[0]))
    out, my_rank = [], None
    me = get_user()
    for i, (uid, val) in enumerate(ordered[:limit], start=1):
        entry = {"rank": i, "user": uid, "name": names.get(uid, "？"), "scope": scope}
        if scope == "sprint":
            score, combo, total = by_user[uid]
            entry.update({"value": score, "score": score, "combo": combo, "total": total})
        elif scope == "accuracy":
            entry["value"] = round(val * 100, 1)
        else:
            entry["value"] = int(val)
        if scope == "xp":
            entry["level"] = level_of(val)
            entry["level_title"] = LEVELS[level_of(val) - 1][1]
        if uid == me:
            my_rank = i
        out.append(entry)

    return resp({
        "scope": scope, "period": period, "limit": limit,
        "rows": out, "me_rank": my_rank,
        "total_players": len(ordered),
    })
