"""背单词：任务生成 / 结果记录"""
import random
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from .friends import notify_level
from .auth import get_user, resp
from .config import CONFIG, MATERIALS
from .db import db
from .idempotency import SCORE_CAPS, validate_attempt_id
from .materials import audio_url, find_item, iter_material
from .misc import local_today

bp = Blueprint("memorize", __name__)


@bp.get("/api/memorize/session")
def api_memorize_session():
    """背单词任务：到期待重背的词优先 + 未背过的新词补齐。带 lesson 时只出该课的词。"""
    u = get_user()
    list_key = request.args.get("list", "cet4")
    try:
        batch = int(request.args.get("n", CONFIG["memorize_batch"]))
    except (TypeError, ValueError):
        return jsonify({"error": "n 无效"}), 400
    if not 1 <= batch <= 100:
        return jsonify({"error": "n 必须在 1..100 之间"}), 400
    lesson = None
    if request.args.get("lesson") is not None:
        try:
            lesson = int(request.args.get("lesson"))
            assert lesson >= 1
        except (TypeError, ValueError, AssertionError):
            return jsonify({"error": "lesson 必须为正整数"}), 400
        if request.args.get("n") is None:
            batch = 100   # 按课背：默认整课出完（上限 100）
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "句子素材不支持背诵"}), 400
    cutoff = (local_today() - timedelta(days=CONFIG["memorize_review_days"])).isoformat()

    pool_source = list(iter_material(list_key, lesson)) if lesson else None
    if lesson and not pool_source:
        return jsonify({"error": "课程不存在"}), 404
    lesson_ids = {m["id"] for m in pool_source} if lesson else None

    # review=1（仅按课时生效）：今日动线"已学课重学"入口，整课重出，不按已背过滤
    review_all = request.args.get("review") == "1" and lesson_ids is not None

    with db() as conn:
        reviews = [] if review_all else conn.execute(
            "SELECT item_id FROM word_state WHERE user=? AND list=? AND kind='word' AND memorized=1 "
            "AND last_memorize < ? ORDER BY last_memorize LIMIT ?",
            (u, list_key, cutoff, batch)).fetchall()
        if lesson_ids is not None:
            reviews = [r for r in reviews if r["item_id"] in lesson_ids]
        memorized_ids = set() if review_all else {r["item_id"] for r in conn.execute(
            "SELECT item_id FROM word_state WHERE user=? AND list=? AND memorized=1",
            (u, list_key)).fetchall()}
    pool = [m for m in (pool_source if lesson else iter_material(list_key))
            if m["id"] not in memorized_ids]
    random.shuffle(pool)
    fresh = pool[: max(0, batch - len(reviews))]

    items = []
    for r in reviews:
        m = find_item(list_key, r["item_id"])
        if m:
            items.append({**m, "phase": "review"})
    for m in fresh:
        items.append({**m, "phase": "review" if review_all else "new"})
    random.shuffle(items)
    for it in items:
        it["audio"] = audio_url(list_key, it["id"], it["text"])
    return resp({"items": items, "total": len(items)})


@bp.post("/api/memorize")
def api_memorize():
    """记录背诵结果；带 attempt_id 的新客户端请求可安全重试。"""
    u = get_user()
    data = request.get_json(force=True)
    list_key = data.get("list")
    raw_id = data.get("id")
    right = data.get("right")
    attempt_id = data.get("attempt_id")
    today = local_today().isoformat()

    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "句子素材不支持背诵"}), 400
    if raw_id is None:
        return jsonify({"error": "缺少 id 参数"}), 400
    item_id = str(raw_id)
    item = find_item(list_key, item_id)
    if not item or item["kind"] != "word":
        return jsonify({"error": "词条不存在"}), 404
    if type(right) is not bool:
        return jsonify({"error": "right 必须为布尔值"}), 400
    # 与其他计分端点同口径：缺 attempt_id 兼容放行（无幂等），非法值 400
    attempt_id, err = validate_attempt_id(attempt_id)
    if err:
        return jsonify({"error": err[0]}), err[1]

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if attempt_id:
            previous = conn.execute(
                "SELECT memorized,memorize_count FROM memorize_attempt WHERE user=? AND attempt_id=?",
                (u, attempt_id),
            ).fetchone()
            if previous:
                return resp({"ok": True, "duplicate": True,
                             "memorized": bool(previous["memorized"]),
                             "memorize_count": previous["memorize_count"]})

        # 当日封顶看 daily_log 实际入账数而非 attempt 表——不带 attempt_id 的
        # 循环 POST 也撞同一堵墙（重放已在上面提前 return，不会误伤重试）
        log = conn.execute(
            "SELECT memorize_right, memorize_wrong FROM daily_log WHERE day=? AND user=?",
            (today, u)).fetchone()
        if log and log["memorize_right"] + log["memorize_wrong"] >= SCORE_CAPS["memorize"]:
            return jsonify({"error": "今日背诵次数已达上限"}), 429

        row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                           (u, list_key, item_id)).fetchone()
        state = dict(row) if row else {"kind": "word", "memorized": 0, "memorize_count": 0,
                                       "last_memorize": ""}
        if right:
            state["memorize_count"] += 1
            if state["memorize_count"] >= CONFIG["memorize_threshold"]:
                state["memorized"] = 1
                state["last_memorize"] = today
        else:
            state["memorize_count"] = 0
            state["memorized"] = 0
            state["last_memorize"] = None

        conn.execute("""
            INSERT INTO word_state(user, list, item_id, kind, memorized, memorize_count, last_memorize)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(user, list, item_id) DO UPDATE SET
                memorized=excluded.memorized, memorize_count=excluded.memorize_count,
                last_memorize=excluded.last_memorize
        """, (u, list_key, item_id, state["kind"], state["memorized"], state["memorize_count"],
              state["last_memorize"]))

        conn.execute("""
            INSERT INTO daily_log(day, user, memorize_right, memorize_wrong)
            VALUES(?,?,?,?) ON CONFLICT(day, user) DO UPDATE SET
                memorize_right=memorize_right+excluded.memorize_right,
                memorize_wrong=memorize_wrong+excluded.memorize_wrong
        """, (today, u, 1 if right else 0, 0 if right else 1))
        notify_level(conn, u)
        if attempt_id:
            conn.execute("""
                INSERT INTO memorize_attempt(user,attempt_id,list,item_id,right,memorized,memorize_count,created_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, (u, attempt_id, list_key, item_id, 1 if right else 0, state["memorized"],
                  state["memorize_count"], today))
    return resp({"ok": True, "duplicate": False,
                 "memorized": state["memorized"], "memorize_count": state["memorize_count"]})
