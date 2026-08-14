"""背单词：任务生成 / 结果记录"""
import random
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .config import CONFIG, MATERIALS
from .db import db
from .materials import audio_url, find_item, iter_material

bp = Blueprint("memorize", __name__)


@bp.get("/api/memorize/session")
def api_memorize_session():
    """背单词任务：到期待重背的词优先 + 未背过的新词补齐"""
    u = get_user()
    list_key = request.args.get("list", "cet4")
    try:
        batch = int(request.args.get("n", CONFIG["memorize_batch"]))
    except (TypeError, ValueError):
        return jsonify({"error": "n 无效"}), 400
    if not 1 <= batch <= 100:
        return jsonify({"error": "n 必须在 1..100 之间"}), 400
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "句子素材不支持背诵"}), 400
    cutoff = (date.today() - timedelta(days=CONFIG["memorize_review_days"])).isoformat()

    with db() as conn:
        reviews = conn.execute(
            "SELECT item_id FROM word_state WHERE user=? AND list=? AND kind='word' AND memorized=1 "
            "AND last_memorize < ? ORDER BY last_memorize LIMIT ?",
            (u, list_key, cutoff, batch)).fetchall()
        memorized_ids = {r["item_id"] for r in conn.execute(
            "SELECT item_id FROM word_state WHERE user=? AND list=? AND memorized=1",
            (u, list_key)).fetchall()}
    pool = [m for m in iter_material(list_key) if m["id"] not in memorized_ids]
    random.shuffle(pool)
    fresh = pool[: max(0, batch - len(reviews))]

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


@bp.post("/api/memorize")
def api_memorize():
    """记录背诵结果：连续答对 memorize_threshold 次 → 已背"""
    u = get_user()
    data = request.get_json(force=True)
    list_key = data.get("list")
    item_id = str(data.get("id"))
    right = bool(data.get("right"))
    today = date.today().isoformat()
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                           (u, list_key, item_id)).fetchone()
        sr = dict(row) if row else {"kind": "word", "memorized": 0, "memorize_count": 0,
                                    "last_memorize": ""}
        if right:
            sr["memorize_count"] += 1
            if sr["memorize_count"] >= CONFIG["memorize_threshold"]:
                sr["memorized"] = 1
                sr["last_memorize"] = today
        else:
            sr["memorize_count"] = 0
            sr["memorized"] = 0
            sr["last_memorize"] = None

        conn.execute("""
            INSERT INTO word_state(user, list, item_id, kind, memorized, memorize_count, last_memorize)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(user, list, item_id) DO UPDATE SET
                memorized=excluded.memorized, memorize_count=excluded.memorize_count,
                last_memorize=excluded.last_memorize
        """, (u, list_key, item_id, sr["kind"], sr["memorized"], sr["memorize_count"],
              sr["last_memorize"]))

        conn.execute("""
            INSERT INTO daily_log(day, user, memorize_right, memorize_wrong)
            VALUES(?,?,?,?)
            ON CONFLICT(day, user) DO UPDATE SET
                memorize_right=memorize_right+excluded.memorize_right,
                memorize_wrong=memorize_wrong+excluded.memorize_wrong
        """, (today, u, 1 if right else 0, 0 if right else 1))
    return resp({"ok": True, "memorized": sr["memorized"], "memorize_count": sr["memorize_count"]})
