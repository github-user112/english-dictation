"""错词 Boss 战：把错得最多的词打包成一只 Boss，集中火力击破。

规则（前端执行，服务端记账）：听音打词，打对一个扣 Boss 一点血，
该词按"从错词本移除"的同款语义斩落清出；打错扣自己一颗心，词排到队尾。
心耗尽即战败，但已答对的战果保留。答题明细只在战斗结束提交一次：
服务端校验 id 确属错词本、right 为严格布尔后落 daily_practice_log(boss)
——喂经验/浇水/首答统计，但不动 FSRS 记忆状态（与 quiz/sprint 同口径）。
"""
from datetime import date

from flask import Blueprint, jsonify, request

from .friends import notify_level
from .auth import get_user, resp
from .catalog import clamp_int
from .config import MATERIALS
from .db import db
from .idempotency import check_and_mark, mark_done, validate_attempt_id
from .materials import audio_url, find_item
from .profile import derive_profile

bp = Blueprint("boss", __name__)

BOSS_MAX_WORDS = 30


@bp.get("/api/boss/session")
def api_boss_session():
    """集结 Boss 部队：错得最多的 n 个词（跨素材库，可 ?list= 聚焦）。"""
    user = get_user()
    n = clamp_int(request.args.get("n"), 8, 3, BOSS_MAX_WORDS)
    list_key = request.args.get("list")
    if list_key is not None:
        if list_key not in MATERIALS:
            return jsonify({"error": "未知素材"}), 404
        if MATERIALS[list_key]["type"] != "words":
            return jsonify({"error": "Boss 战仅支持词汇素材"}), 400

    with db() as conn:
        # 多取一些备过滤（素材缺失/跨库同文去重），排序让最痛的词先上场
        rows = conn.execute(
            "SELECT list,item_id,wrong_count FROM word_state "
            "WHERE user=? AND wrong_count>0 ORDER BY wrong_count DESC, last_seen DESC LIMIT ?",
            (user, n * 6)).fetchall()

    items, texts = [], set()
    for r in rows:
        if list_key is not None and r["list"] != list_key:
            continue
        mat_item = find_item(r["list"], r["item_id"])
        if mat_item is None or mat_item["text"] in texts:
            continue   # 素材已更新的幽灵行 / 跨库同文只打一次
        texts.add(mat_item["text"])
        items.append({
            "id": r["item_id"], "list": r["list"],
            "text": mat_item["text"],
            "phonetic": mat_item.get("phonetic") or "",
            "meaning": mat_item.get("meaning") or "",
            "audio": audio_url(r["list"], r["item_id"], mat_item["text"]),
            "wrong_count": r["wrong_count"],
        })
        if len(items) >= n:
            break
    return resp({"items": items, "total": len(items)})


@bp.post("/api/boss/result")
def api_boss_result():
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    answers = data.get("answers")
    if not isinstance(answers, list) or not answers or len(answers) > BOSS_MAX_WORDS * 2:
        return jsonify({"error": "answers 无效"}), 400

    attempt_id, err = validate_attempt_id(data.get("attempt_id"))
    if err:
        attempt_id = None  # 老客户端兼容

    today = date.today().isoformat()
    with db(immediate=True) as conn:
        # 幂等优先于答案校验：重放不重复校验，避免首次已清除的错词导致重放 400
        if attempt_id:
            status, capped = check_and_mark(conn, user, "boss", attempt_id)
            if status == "duplicate":
                _score = sum(1 for a in answers if isinstance(a, dict) and a.get("right") is True)
                remaining = conn.execute(
                    "SELECT COUNT(*) c FROM word_state WHERE user=? AND wrong_count>0",
                    (user,)).fetchone()["c"]
                return resp({"ok": True, "duplicate": True,
                             "score": _score, "total": len(answers),
                             "cleared": _score, "wrong_remaining": remaining})
            if status == "capped":
                return capped

        wrong_ids = {(r["list"], r["item_id"]) for r in conn.execute(
            "SELECT list, item_id FROM word_state WHERE user=? AND wrong_count>0", (user,))}
        graded, seen = [], set()
        for a in answers:
            # 严格校验：id 必须仍在错词本内、不重复、right 是真布尔
            if not isinstance(a, dict):
                return jsonify({"error": "答案格式无效"}), 400
            qid, right, lkey = a.get("id"), a.get("right"), a.get("list")
            # 先查类型再进集合：dict/list 当 id 会在 key 哈希时抛 TypeError 打成 500
            if not isinstance(qid, str) or not isinstance(lkey, str) \
                    or not isinstance(right, bool):
                return jsonify({"error": "答案与错词本不符"}), 400
            key = (lkey, qid)
            if key not in wrong_ids or key in seen:
                return jsonify({"error": "答案与错词本不符"}), 400
            seen.add(key)
            graded.append((qid, right, lkey))

        cleared = 0
        for qid, right, lkey in graded:
            # 只记模式统计（经验/浇水/首答正确率），不动记忆状态与错词次数
            conn.execute(
                """INSERT INTO daily_practice_log(day,user,practice_mode,new_count,review_count,
                       first_right_count,first_wrong_count,final_right_count,skipped_count)
                   VALUES(?,?,?,0,0,?,?,?,0) ON CONFLICT(day,user,practice_mode) DO UPDATE SET
                   first_right_count=first_right_count+excluded.first_right_count,
                   first_wrong_count=first_wrong_count+excluded.first_wrong_count,
                   final_right_count=final_right_count+excluded.final_right_count""",
                (today, user, "boss", 1 if right else 0,
                 0 if right else 1, 1 if right else 0))
            if right:
                # 与 /api/wrong/remove 同款清除语义：斩落即重置回新词流
                conn.execute(
                    "UPDATE word_state SET wrong_count=0,status='new',next_review=NULL "
                    "WHERE user=? AND item_id=? AND list=?", (user, qid, lkey))
                cleared += 1
        notify_level(conn, user)
        remaining = conn.execute(
            "SELECT COUNT(*) c FROM word_state WHERE user=? AND wrong_count>0",
            (user,)).fetchone()["c"]
        profile = derive_profile(conn, user)
        if attempt_id:
            mark_done(conn, user, "boss", attempt_id)

    return resp({"score": sum(1 for _, right, _ in graded if right),
                 "total": len(graded), "cleared": cleared,
                 "wrong_remaining": remaining, "profile": profile})
