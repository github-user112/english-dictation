"""学习计划：「N 天背完词库」→ 每日新词目标与进度。

目标只存 (user, list, target_days, start_day)：剩余词数、剩余天数、每日新词
全部由它现算，不存在需要回填的派生列，改目标/背了词都即时反映。
daily_new 同时供背单词页的进度环与听打会话的每日新词配额（见 catalog.api_session）。
"""
import math
from datetime import date

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .catalog import now
from .config import MATERIALS
from .db import db
from .materials import load_material

bp = Blueprint("goal", __name__)

# ponytail: 单日配额硬顶 200——计划页展示的 daily_new 照实算，但一天的听打会话
# 最多灌 200 个新词；真要「3 天背完 CET-4」的人超出的部分明天还会排在队首
QUOTA_CAP = 200


def _goal_view(conn, user, list_key, row):
    total = len(load_material(list_key))
    memorized = conn.execute(
        "SELECT COUNT(*) c FROM word_state WHERE user=? AND list=? AND memorized=1",
        (user, list_key)).fetchone()["c"]
    remaining = max(0, total - memorized)
    elapsed = max(0, (date.today() - date.fromisoformat(row["start_day"])).days)
    days_left = max(1, row["target_days"] - elapsed)
    daily_new = math.ceil(remaining / days_left) if remaining else 0
    log = conn.execute(
        "SELECT memorize_right FROM daily_log WHERE day=? AND user=?",
        (date.today().isoformat(), user)).fetchone()
    return {"list": list_key, "target_days": row["target_days"],
            "start_day": row["start_day"], "days_left": days_left,
            "total": total, "memorized": memorized, "remaining": remaining,
            "daily_new": daily_new, "today_done": log["memorize_right"] if log else 0,
            "done": remaining == 0}


def daily_new_quota(conn, user, list_key):
    """有目标时返回今日应学新词数（封顶 QUOTA_CAP），无目标返回 None。"""
    row = conn.execute(
        "SELECT * FROM study_goal WHERE user=? AND list=?", (user, list_key)).fetchone()
    if not row:
        return None
    return min(_goal_view(conn, user, list_key, row)["daily_new"], QUOTA_CAP)


@bp.get("/api/goal")
def api_goal():
    user = get_user()
    with db() as conn:
        rows = conn.execute("SELECT * FROM study_goal WHERE user=?", (user,)).fetchall()
        goals = {r["list"]: _goal_view(conn, user, r["list"], r)
                 for r in rows if r["list"] in MATERIALS}
    return resp({"goals": goals})


@bp.post("/api/goal")
def api_goal_save():
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    list_key = data.get("list")
    if list_key not in MATERIALS or MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "仅词汇素材支持学习计划"}), 400
    days = data.get("target_days")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        return jsonify({"error": "target_days 必须为 1..365 的整数"}), 400
    with db() as conn:
        # 保留原 start_day：改目标天数只改节奏，不把已过去的打卡天数清零
        conn.execute(
            """INSERT INTO study_goal(user,list,target_days,start_day,updated_at) VALUES(?,?,?,?,?)
               ON CONFLICT(user,list) DO UPDATE SET
                   target_days=excluded.target_days, updated_at=excluded.updated_at""",
            (user, list_key, days, date.today().isoformat(), now()))
        row = conn.execute(
            "SELECT * FROM study_goal WHERE user=? AND list=?", (user, list_key)).fetchone()
        view = _goal_view(conn, user, list_key, row)
    return resp({"goal": view})


@bp.delete("/api/goal")
def api_goal_delete():
    user = get_user()
    list_key = request.args.get("list", "")
    with db() as conn:
        conn.execute("DELETE FROM study_goal WHERE user=? AND list=?", (user, list_key))
    return resp({"ok": True})
