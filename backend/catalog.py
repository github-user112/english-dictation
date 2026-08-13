"""素材目录 / 听打任务 / 答题结果"""
import random
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .config import AUDIO, CONFIG, MATERIALS
from .db import db
from .materials import audio_url, find_item, iter_material

bp = Blueprint("catalog", __name__)


@bp.get("/api/lists")
def api_lists():
    u = get_user()
    today = date.today().isoformat()
    with db() as conn:
        rows = conn.execute("SELECT list, kind, status, COUNT(*) c FROM word_state WHERE user=? GROUP BY list, status", (u,)).fetchall()
        mem_rows = conn.execute("SELECT list, COUNT(*) c FROM word_state WHERE user=? AND memorized=1 GROUP BY list", (u,)).fetchall()
        today_row = conn.execute("SELECT * FROM daily_log WHERE day=? AND user=?", (today, u)).fetchone()
    stat_map = {(r["list"], r["status"]): r["c"] for r in rows}
    mem_map = {r["list"]: r["c"] for r in mem_rows}
    result = []
    for key, meta in MATERIALS.items():
        total = sum(1 for _ in iter_material(key))
        audio_done = len(list((AUDIO / key).glob("*.mp3"))) if (AUDIO / key).exists() else 0
        result.append({
            "key": key,
            "title": meta["title"],
            "type": meta["type"],
            "total": total,
            "audio_done": audio_done,
            "new": stat_map.get((key, "new"), 0),
            "learning": stat_map.get((key, "learning"), 0),
            "known": stat_map.get((key, "known"), 0),
            "memorized": mem_map.get(key, 0),
        })
    today_log = {
        "new": today_row["new_count"] if today_row else 0,
        "review": today_row["review_count"] if today_row else 0,
        "right": today_row["right_count"] if today_row else 0,
        "wrong": today_row["wrong_count"] if today_row else 0,
        "memorize_right": today_row["memorize_right"] if today_row else 0,
        "memorize_wrong": today_row["memorize_wrong"] if today_row else 0,
    }
    return resp({"lists": result, "today": today_log})


@bp.get("/api/session")
def api_session():
    u = get_user()
    list_key = request.args.get("list", "cet4")
    new_n = int(request.args.get("new", CONFIG["new_per_day"]))
    scope = request.args.get("scope", "all")
    today = date.today().isoformat()
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404

    with db() as conn:
        # 复习队列（学习中的词也要等到复习日；只看已背时过滤 memorized）
        q = ("SELECT item_id, kind FROM word_state WHERE user=? AND list=? "
             "AND next_review<=? AND status IN ('learning','known')")
        if scope == "memorized":
            q += " AND memorized=1"
        reviews = conn.execute(q + " ORDER BY next_review LIMIT ?",
                               (u, list_key, today, CONFIG["max_review"])).fetchall()

        # 新词
        if len(reviews) < new_n:
            known_ids = {r["item_id"] for r in conn.execute(
                "SELECT item_id FROM word_state WHERE user=? AND list=?", (u, list_key)).fetchall()}
            if scope == "memorized":
                # 只看已背：新词池 = 已背但还没听打过的词
                fresh_ids = {r["item_id"] for r in conn.execute(
                    "SELECT item_id FROM word_state WHERE user=? AND list=? AND memorized=1 "
                    "AND status='new'", (u, list_key)).fetchall()}
                pool = [m for m in iter_material(list_key) if m["id"] in fresh_ids]
            else:
                pool = [m for m in iter_material(list_key) if m["id"] not in known_ids]
            random.shuffle(pool)
            fresh = pool[: new_n - len(reviews)]
        else:
            fresh = []

    items = []
    for r in reviews:
        m = find_item(list_key, r["item_id"])
        if m:
            items.append({**m, "phase": "review"})
    for m in fresh:
        items.append({**m, "phase": "new"})
    random.shuffle(items)
    for it in items:
        it["audio"] = audio_url(list_key, it["id"], it["text"])
    return resp({"items": items, "total": len(items)})


@bp.post("/api/result")
def api_result():
    u = get_user()
    data = request.get_json(force=True)
    list_key = data.get("list")
    item_id = str(data.get("id"))
    right = bool(data.get("right"))
    retried = bool(data.get("retried"))   # 本题答错过但最终提交（最终答对 or 放弃）
    today = date.today().isoformat()
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404

    with db() as conn:
        row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                           (u, list_key, item_id)).fetchone()
        if row:
            sr = dict(row)
        else:
            kind = "sentence" if MATERIALS[list_key]["type"] == "sentences" else "word"
            sr = {"status": "new", "wrong_count": 0, "right_count": 0,
                  "consecutive_right": 0, "last_seen": "", "next_review": "", "kind": kind}

        is_new = sr["status"] == "new"
        if right:
            sr["right_count"] += 1
            sr["consecutive_right"] += 1
            if retried:
                # 曾答错但最终答对：进错词本复习，掌握度照常推进
                sr["wrong_count"] += 1
            if sr["consecutive_right"] >= CONFIG["known_threshold"]:
                sr["status"] = "known"
                sr["next_review"] = (date.today() + timedelta(days=7)).isoformat()
            else:
                sr["status"] = "learning"
                days = 1 if sr["consecutive_right"] == 1 else 3   # 间隔 1/3/7 天
                sr["next_review"] = (date.today() + timedelta(days=days)).isoformat()
        else:
            sr["wrong_count"] += 1
            sr["consecutive_right"] = 0
            sr["status"] = "learning"
            sr["next_review"] = (date.today() + timedelta(days=1)).isoformat()
        if sr["kind"] == "word" and not right and not retried:
            # 直接答错（未重试成功）→ 退回背诵队列，需重新背过才能再进"只看已背"听打
            sr["memorized"] = 0
            sr["memorize_count"] = 0
        sr["last_seen"] = today

        conn.execute("""
            INSERT INTO word_state(user, list, item_id, kind, status, wrong_count, right_count,
                                   consecutive_right, last_seen, next_review, memorized,
                                   memorize_count, last_memorize)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user, list, item_id) DO UPDATE SET
                status=excluded.status, wrong_count=excluded.wrong_count,
                right_count=excluded.right_count, consecutive_right=excluded.consecutive_right,
                last_seen=excluded.last_seen, next_review=excluded.next_review,
                memorized=excluded.memorized, memorize_count=excluded.memorize_count,
                last_memorize=excluded.last_memorize
        """, (u, list_key, item_id, sr["kind"], sr["status"], sr["wrong_count"], sr["right_count"],
              sr["consecutive_right"], sr["last_seen"], sr["next_review"], sr.get("memorized", 0),
              sr.get("memorize_count", 0), sr.get("last_memorize", "")))

        conn.execute("""
            INSERT INTO daily_log(day, user, new_count, review_count, right_count, wrong_count)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(day, user) DO UPDATE SET
                new_count=new_count+excluded.new_count,
                review_count=review_count+excluded.review_count,
                right_count=right_count+excluded.right_count,
                wrong_count=wrong_count+excluded.wrong_count
        """, (today, u, 1 if is_new else 0, 0 if is_new else 1, 1 if right else 0, 0 if right else 1))
    return resp({"ok": True})
