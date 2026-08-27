"""英中配对消消乐：词与释义翻牌配对，配上一对消一对。

出题从指定词库随机抽 n 个词（同文去重，避免 hello 两种释义的歧义），
洗牌交给前端——每局重开都是新布局。战果在通关时一次性提交：
right 表示该词"首配即中"（没配错过任何一次），服务端校验 id 确属该词库、
right 为严格布尔后落 daily_practice_log(match)——喂经验/浇水/首答统计
（识别口径与听打混计，同 quiz/sprint 先例），不动 FSRS 记忆状态。
"""
import random
from datetime import date

from flask import Blueprint, jsonify, request

from .friends import notify_level
from .auth import get_user, resp
from .catalog import clamp_int
from .config import MATERIALS
from .db import db
from .materials import _material_index, audio_url, load_material
from .profile import derive_profile

bp = Blueprint("match", __name__)

MATCH_MAX_PAIRS = 12


@bp.get("/api/match/session")
def api_match_session():
    """发一副牌：n 个词的英中配对（默认 8 对）。"""
    user = get_user()
    n = clamp_int(request.args.get("n"), 8, 3, MATCH_MAX_PAIRS)
    list_key = request.args.get("list", "cet4")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "配对消消乐仅支持词汇素材"}), 400

    # 同文去重：hello 与 hello~2 释义不同，同时上桌会变成无解歧义
    pool, texts = [], set()
    for item in load_material(list_key):
        if item["text"] in texts:
            continue
        texts.add(item["text"])
        pool.append(item)
    if len(pool) < 3:
        return jsonify({"error": "该素材词太少，无法开局"}), 400

    items = [{
        "id": it["id"], "list": list_key,
        "text": it["text"],
        "phonetic": it.get("phonetic") or "",
        "meaning": it.get("meaning") or "",
        "audio": audio_url(list_key, it["id"], it["text"]),
    } for it in random.sample(pool, min(n, len(pool)))]
    return resp({"list": list_key, "items": items, "total": len(items)})


@bp.post("/api/match/result")
def api_match_result():
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    answers = data.get("answers")
    if not isinstance(answers, list) or not answers or len(answers) > MATCH_MAX_PAIRS:
        return jsonify({"error": "answers 无效"}), 400
    list_key = data.get("list")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "配对消消乐仅支持词汇素材"}), 400
    index = _material_index(list_key)

    graded, seen = [], set()
    for a in answers:
        # 严格校验：id 必须属于该词库、不重复、right 是真布尔
        if not isinstance(a, dict):
            return jsonify({"error": "答案格式无效"}), 400
        qid, right = a.get("id"), a.get("right")
        if qid not in index or qid in seen or not isinstance(right, bool):
            return jsonify({"error": "答案与素材不符"}), 400
        seen.add(qid)
        graded.append((qid, right))

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
            (today, user, "match", 0, 0,
             sum(1 for _, right in graded if right),
             sum(1 for _, right in graded if not right),
             sum(1 for _, right in graded if right), 0))
        notify_level(conn, user)
        profile = derive_profile(conn, user)

    return resp({"total": len(graded),
                 "perfect": sum(1 for _, right in graded if right),
                 "profile": profile})
