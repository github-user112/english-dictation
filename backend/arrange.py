"""听音排句：听句子音频，把打乱的词块点回正确顺序。

发牌是确定性的（种子含素材 id）：同一句子的乱序布局可重放，
判分端按客户端提交的下标顺序重拼词块、与原句比对。词块是原句的
精确子串，拼对即逐字还原，无需服务端存会话状态。
每句提交一次 /api/arrange/answer：落 daily_practice_log(arrange)
——喂经验/浇水/首答统计（与 quiz/sprint 同口径），不动记忆状态。
"""
import random
from datetime import date

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .catalog import clamp_int
from .config import MATERIALS
from .db import db
from .materials import audio_url, find_item, load_material
from .profile import derive_profile

bp = Blueprint("arrange", __name__)

ARRANGE_MAX_SENTENCES = 10
MAX_CHUNKS = 8          # 长句切成至多 8 块，手机上也好点
MIN_WORDS = 3           # 两三个词的句子没有"排"的意义


def build_chunks(en):
    """把句子切成 ≤MAX_CHUNKS 个词块：短句按词切，长句就近均分。"""
    tokens = en.split()
    size = -(-len(tokens) // MAX_CHUNKS)   # ceil(len/MAX_CHUNKS)
    return [" ".join(tokens[i:i + size]) for i in range(0, len(tokens), size)]


def deal_chunks(list_key, item_id, en):
    """确定性发牌：同一句子全站同一布局、可重放；绝不等于原句顺序。"""
    chunks = build_chunks(en)
    display = list(chunks)
    rng = random.Random(f"arrange|{list_key}|{item_id}")
    for _ in range(6):
        rng.shuffle(display)
        if display != chunks:
            break
    return display


def _sentence_pool(list_key, lesson):
    pool = []
    for it in load_material(list_key):
        if len(it["text"].split()) < MIN_WORDS:
            continue
        if lesson is not None and it.get("lesson") != lesson:
            continue
        pool.append(it)
    return pool


@bp.get("/api/arrange/session")
def api_arrange_session():
    """出 n 道排句题（默认 5），可选 ?lesson= 聚焦某一课。"""
    user = get_user()
    n = clamp_int(request.args.get("n"), 5, 2, ARRANGE_MAX_SENTENCES)
    list_key = request.args.get("list", "nc1")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "sentences":
        return jsonify({"error": "听音排句仅支持句子素材"}), 400
    raw_lesson = request.args.get("lesson")
    try:
        lesson = int(raw_lesson) if raw_lesson else None
    except ValueError:
        return jsonify({"error": "课号无效"}), 400

    pool = _sentence_pool(list_key, lesson)
    if len(pool) < 2:
        return jsonify({"error": "可用句子太少，无法开局"}), 400

    questions = [{
        "id": it["id"],
        "zh": it.get("meaning") or "",
        "audio": audio_url(list_key, it["id"], it["text"]),
        "chunks": deal_chunks(list_key, it["id"], it["text"]),
    } for it in random.sample(pool, min(n, len(pool)))]
    return resp({"list": list_key, "questions": questions, "total": len(questions)})


@bp.post("/api/arrange/answer")
def api_arrange_answer():
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    list_key = data.get("list")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "sentences":
        return jsonify({"error": "听音排句仅支持句子素材"}), 400
    item = find_item(list_key, str(data.get("id") or ""))
    if item is None:
        return jsonify({"error": "未知句子"}), 400

    order = data.get("order")
    chunks = build_chunks(item["text"])
    k = len(chunks)
    # order 必须是 0..k-1 的严格排列；bool 是 int 的子类，须显式排除
    if not isinstance(order, list):
        return jsonify({"error": "排句顺序无效"}), 400
    seen = set()
    for pos in order:
        if isinstance(pos, bool) or not isinstance(pos, int) or not 0 <= pos < k or pos in seen:
            return jsonify({"error": "排句顺序无效"}), 400
        seen.add(pos)
    if len(seen) != k:
        return jsonify({"error": "排句顺序无效"}), 400

    display = deal_chunks(list_key, str(item["id"]), item["text"])
    built = " ".join(display[p] for p in order)
    right = built == " ".join(item["text"].split())

    today = date.today().isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO daily_practice_log(day,user,practice_mode,new_count,review_count,
                   first_right_count,first_wrong_count,final_right_count,skipped_count)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(day,user,practice_mode) DO UPDATE SET
               first_right_count=first_right_count+excluded.first_right_count,
               first_wrong_count=first_wrong_count+excluded.first_wrong_count,
               final_right_count=final_right_count+excluded.final_right_count""",
            (today, user, "arrange", 0, 0, 1 if right else 0,
             0 if right else 1, 1 if right else 0, 0))
        profile = derive_profile(conn, user)

    return resp({"right": right, "score": 1 if right else 0,
                 "text": item["text"], "profile": profile})
