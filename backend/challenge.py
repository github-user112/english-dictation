"""挑战玩法：听音选词出题 / 限时冲刺最佳成绩。

限时冲刺服务端权威判分（与 pk.py 同一哲学：客户端提交答案，不提交成绩）：
GET /api/sprint/session 开局建会话，词流落库；POST .../start 盖开局时间戳；
结算时客户端提交按序答案 [{id, typed}]，服务端对照词流原文重判
score/combo/total，并过两道闸门：时长闸门（不足 55s 的成绩是跳过作答
过程的脚本）与流速闸门（听音+打字有物理下限，快于 1 题/秒是灌答案）。
"""
import json
import random
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from .auth import display_name, get_user, resp
from .catalog import clamp_int, now
from .config import CONFIG, MATERIALS
from .db import db
from .friends import record_activity
from .materials import _material_index, audio_url, load_material
from .misc import local_today

bp = Blueprint("challenge", __name__)


QUIZ_KINDS = {"audio_en", "en_zh", "zh_en"}   # 音→形 / 音→义 / 义→形


@bp.get("/api/quiz/session")
def api_quiz_session():
    """选词出题：到期待复习词优先，其余从未学词里补齐，干扰项同词单随机。

    kind=audio_en 听音选英文（默认）；kind=en_zh 听音选中文释义；
    kind=zh_en 看中文释义选英文。
    """
    user = get_user()
    list_key = request.args.get("list", "cet4")
    n = clamp_int(request.args.get("n"), CONFIG.get("quiz_questions", 10), 1, 30)
    kind = request.args.get("kind", "audio_en")
    if kind not in QUIZ_KINDS:
        return jsonify({"error": "未知出题类型"}), 400
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "听音选词仅支持词汇素材"}), 400

    material = load_material(list_key)
    if len(material) < 2:
        return jsonify({"error": "该素材词太少，无法出题"}), 400
    index = _material_index(list_key)
    today = local_today().isoformat()

    with db() as conn:
        due_ids = [r["item_id"] for r in conn.execute(
            "SELECT item_id FROM word_state WHERE user=? AND list=? "
            "AND status IN ('learning','known') AND next_review<=? ORDER BY next_review LIMIT ?",
            (user, list_key, today, n)).fetchall()]
        seen_ids = {r["item_id"] for r in conn.execute(
            "SELECT item_id FROM word_state WHERE user=? AND list=?", (user, list_key)).fetchall()}

    targets = [index[i] for i in due_ids if i in index]
    chosen = {t["id"] for t in targets}
    # 补齐时未学词优先，其次才是已学词；两个池子按 seen 与否切分，互不相交
    unseen = [i for i in material if i["id"] not in seen_ids and i["id"] not in chosen]
    learned = [i for i in material if i["id"] in seen_ids and i["id"] not in chosen]
    random.shuffle(unseen)
    random.shuffle(learned)
    for item in unseen + learned:
        if len(targets) >= n:
            break
        targets.append(item)
        chosen.add(item["id"])

    # 干扰项按"去重后的文本"抽样：重复单词（如 hello / hello~2）文本相同，
    # 若同时出现在选项里，用户点视觉正确的词也会因 id 不同被判错
    by_text = {}
    for i in material:
        by_text.setdefault(i["text"], i)
    questions = []
    for target in targets:
        pool = [i for t, i in by_text.items() if t != target["text"]]
        if kind == "en_zh":
            # 选项是中文释义：排除与目标同释义的词，避免出现双正确项
            filtered = [i for i in pool
                        if (i.get("meaning") or "") != (target.get("meaning") or "")]
            if len(filtered) >= 3 or len(filtered) >= len(pool):
                pool = filtered
        k = min(3, len(pool))
        distractors = random.sample(pool, k)
        options = [target] + distractors
        random.shuffle(options)
        questions.append({
            "id": target["id"],
            "text": target["text"],   # playWord 靠 text 拼真人发音 URL
            "kind": kind,
            "audio": audio_url(list_key, target["id"], target["text"]),
            "options": [{"id": o["id"], "text": o["text"],
                         "phonetic": o.get("phonetic") or "",
                         "meaning": o.get("meaning") or ""} for o in options],
        })
    return resp({"questions": questions, "total": len(questions), "kind": kind})


SPRINT_DURATION = 60        # 冲刺时长（秒），与前端 DURATION 一致
SPRINT_EARLY_GRACE = 5      # 时长闸门宽限：结算早于 55s 到达 = 没打完时间
MIN_ANSWER_SECONDS = 1.0    # 流速下限（同 pk.py）：听音+打字快不过 1 题/秒
MAX_SPRINT_ANSWERS = 600    # 单次结算答案数上限（60s 物理上限 ~60，留 10 倍余量）
SESSION_TTL_SECONDS = 86400  # 会话惰性清理窗口


def _new_session(conn, user, list_key, items, challenge_id=None):
    _sweep_sessions(conn)
    sid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO sprint_session(id,user,list_key,challenge_id,items,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (sid, user, list_key, challenge_id, json.dumps(items, ensure_ascii=False), now()))
    return sid


def _sweep_sessions(conn):
    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=SESSION_TTL_SECONDS)).isoformat(timespec="seconds")
    conn.execute("DELETE FROM sprint_session WHERE created_at < ?", (cutoff,))


def _elapsed_seconds(iso_start):
    """经过秒数；now() 产出带时区 UTC，裸值按本地时区兼容。"""
    dt = datetime.fromisoformat(iso_start)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()


def _judge_answers(session, answers):
    """对照会话词流重判答案序列。返回 (score, max_combo, answered) 或错误串。

    判对错的标准与前端 WordCells.isCorrect 一致：只比对字母（忽略大小写），
    多打字母（extraInput）由 typed 全文比对自然判错。
    """
    if not isinstance(answers, list) or not answers or len(answers) > MAX_SPRINT_ANSWERS:
        return "答案序列无效"
    texts = {i["id"]: str(i.get("text", "")) for i in json.loads(session["items"])}
    score = combo = max_combo = answered = 0
    for a in answers:
        if not isinstance(a, dict):
            return "答案格式无效"
        item_id, typed = a.get("id"), a.get("typed")
        if not isinstance(item_id, str) or item_id not in texts:
            return "答案与词流不符"
        if typed is None:
            combo = 0   # 跳过：断连击但不计入作答（与前端 skip() 语义一致）
            continue
        if not isinstance(typed, str) or len(typed) > 100:
            return "答案格式无效"
        answered += 1
        expected = "".join(c for c in texts[item_id] if c.isalpha())
        if typed.strip().lower() == expected.lower():
            score += 1
            combo += 1
            max_combo = max(max_combo, combo)
        else:
            combo = 0
    return score, max_combo, answered


def _start_session(conn, sid, user):
    """盖开局时间戳（幂等：重复 start 不刷新计时起点）。返回 (错误串, status) 或 None。"""
    row = conn.execute(
        "SELECT user, started_at, finished_at FROM sprint_session WHERE id=?", (sid,)).fetchone()
    if row is None or row["user"] != user:
        return "会话不存在", 404
    if row["finished_at"]:
        return "本局已结算", 409
    if row["started_at"] is None:
        conn.execute("UPDATE sprint_session SET started_at=? WHERE id=?", (now(), sid))
    return None


def _finish_session(conn, sid, user, answers):
    """校验会话+闸门+重判，盖章结算。返回 (score, combo, answered) 或 (错误串, status)。"""
    row = conn.execute(
        "SELECT * FROM sprint_session WHERE id=?", (sid,)).fetchone()
    if row is None or row["user"] != user:
        return "会话不存在", 404
    if row["finished_at"]:
        return "本局已结算", 409
    if row["started_at"] is None:
        return "本局未开局", 400
    elapsed = _elapsed_seconds(row["started_at"])
    if elapsed < SPRINT_DURATION - SPRINT_EARLY_GRACE:
        return "作答时长不足，成绩无效", 400
    judged = _judge_answers(row, answers)
    if isinstance(judged, str):
        return judged, 400
    score, combo, answered = judged
    # 流速闸门：得分不可能超过流逝时间允许的作答数（+1 仅兜底计时毫秒漂移；
    # 更宽的缓冲会让"挂机 55s 再集中灌答案"钻过去）
    if score > int(elapsed / MIN_ANSWER_SECONDS) + 1:
        return "作答速度异常，成绩无效", 400
    conn.execute("UPDATE sprint_session SET finished_at=? WHERE id=?", (now(), sid))
    return score, combo, answered


def sprint_items(list_key, n):
    """随机抽 n 个词生成冲刺词流；限时冲刺与挑战链接共用同一形状。"""
    material = load_material(list_key)
    pool = random.sample(material, min(n, len(material)))
    return [{"id": i["id"], "text": i["text"], "kind": i["kind"],
             "audio": audio_url(list_key, i["id"], i["text"])} for i in pool]


@bp.get("/api/sprint/session")
def api_sprint_session():
    """限时冲刺词流：建会话落库词流（结算判分的基准），不计每日配额。"""
    user = get_user()
    list_key = request.args.get("list", "cet4")
    n = clamp_int(request.args.get("n"), 40, 1, 100)
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "限时冲刺仅支持词汇素材"}), 400
    items = sprint_items(list_key, n)
    with db() as conn:
        sid = _new_session(conn, user, list_key, items)
    return resp({"session": sid, "items": items})


@bp.post("/api/sprint/session/start")
def api_sprint_session_start():
    """盖开局时间戳：时长闸门的计时起点。重复调用幂等（不刷新起点）。"""
    user = get_user()
    data = request.get_json(silent=True)
    sid = isinstance(data, dict) and data.get("session") or ""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        result = _start_session(conn, sid, user)
        if result:
            return jsonify({"error": result[0]}), result[1]
    return resp({"ok": True})


@bp.get("/api/sprint/best")
def api_sprint_best():
    user = get_user()
    with db() as conn:
        row = conn.execute("SELECT score, combo, total FROM sprint_best WHERE user=?", (user,)).fetchone()
    return resp({"best": {"score": row["score"], "combo": row["combo"], "total": row["total"]}
                 if row else None})


@bp.post("/api/sprint/best")
def api_sprint_best_post():
    """结算冲刺成绩：客户端只交答案序列，score/combo 由服务端重判得出。"""
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    sid = data.get("session") or ""
    answers = data.get("answers")

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        session = conn.execute(
            "SELECT challenge_id FROM sprint_session WHERE id=?", (sid,)).fetchone()
        if session and session["challenge_id"]:
            return jsonify({"error": "挑战局请提交到挑战端点"}), 400
        result = _finish_session(conn, sid, user, answers)
        if len(result) == 2:   # (错误串, status)
            return jsonify({"error": result[0]}), result[1]
        score, combo, total = result

        row = conn.execute("SELECT score, combo FROM sprint_best WHERE user=?", (user,)).fetchone()
        if row is None or (score, combo) > (row["score"], row["combo"]):
            conn.execute("""
                INSERT INTO sprint_best(user, score, combo, total, updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(user) DO UPDATE SET
                    score=excluded.score, combo=excluded.combo,
                    total=excluded.total, updated_at=excluded.updated_at
            """, (user, score, combo, total, now()))
            record_activity(conn, user, "sprint_record", {"score": score, "combo": combo})
        best = conn.execute(
            "SELECT score, combo, total FROM sprint_best WHERE user=?", (user,)).fetchone()
    return resp({"best": {"score": best["score"], "combo": best["combo"], "total": best["total"]},
                 "score": score, "combo": combo, "total": total,
                 "record": row is None or (score, combo) > (row["score"], row["combo"])})


# ---------------- 异步冲刺挑战：同词流、比分榜，无需 WebSocket ----------------

@bp.post("/api/sprint/challenge")
def api_sprint_challenge_create():
    """用当前素材随机抽词生成挑战词流，返回可分享的挑战 id。"""
    user = get_user()
    list_key = request.args.get("list", "cet4")
    n = clamp_int(request.args.get("n"), 40, 5, 100)
    if list_key not in MATERIALS or MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "未知素材"}), 404
    items = sprint_items(list_key, n)
    cid = uuid.uuid4().hex[:10]
    with db() as conn:
        conn.execute(
            "INSERT INTO sprint_challenge(id,owner_user,owner_name,list_key,items,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (cid, user, display_name(conn, user), list_key,
             json.dumps(items, ensure_ascii=False), now()))
    return resp({"id": cid})


@bp.get("/api/sprint/challenge")
def api_sprint_challenge_get():
    cid = request.args.get("id", "")
    with db() as conn:
        row = conn.execute("SELECT * FROM sprint_challenge WHERE id=?", (cid,)).fetchone()
        if not row:
            return jsonify({"error": "挑战不存在或已过期"}), 404
        scores = conn.execute(
            "SELECT name,score,combo,total,updated_at FROM sprint_challenge_score "
            "WHERE challenge_id=? ORDER BY score DESC, combo DESC, updated_at LIMIT 50",
            (cid,)).fetchall()
    return resp({
        "id": row["id"], "list": row["list_key"],
        "owner": row["owner_name"], "created_at": row["created_at"],
        "items": json.loads(row["items"]),
        "scores": [dict(s) for s in scores],
    })


@bp.post("/api/sprint/challenge/<cid>/start")
def api_sprint_challenge_start(cid):
    """挑战开局：以挑战词流建会话并盖时间戳，返回会话 id。"""
    user = get_user()
    with db() as conn:
        row = conn.execute(
            "SELECT list_key, items FROM sprint_challenge WHERE id=?", (cid,)).fetchone()
        if not row:
            return jsonify({"error": "挑战不存在或已过期"}), 404
        sid = _new_session(conn, user, row["list_key"],
                           json.loads(row["items"]), challenge_id=cid)
        # 建会话即开局（前端在按下开始按钮时调用本端点）
        conn.execute("UPDATE sprint_session SET started_at=? WHERE id=?", (now(), sid))
    return resp({"session": sid})


@bp.post("/api/sprint/challenge/<cid>/score")
def api_sprint_challenge_score(cid):
    """挑战结算：只收答案序列，分数服务端对照挑战词流重判。"""
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    sid = data.get("session") or ""
    answers = data.get("answers")

    with db() as conn:
        # BEGIN IMMEDIATE 把读-比-写串行化：并发提交时低分不会在检查后覆盖高分
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM sprint_challenge WHERE id=?", (cid,)).fetchone():
            return jsonify({"error": "挑战不存在或已过期"}), 404
        session = conn.execute(
            "SELECT challenge_id FROM sprint_session WHERE id=?", (sid,)).fetchone()
        if session is None or session["challenge_id"] != cid:
            return jsonify({"error": "会话与本挑战不符"}), 400
        result = _finish_session(conn, sid, user, answers)
        if len(result) == 2:
            return jsonify({"error": result[0]}), result[1]
        score, combo, total = result

        prev = conn.execute(
            "SELECT score, combo FROM sprint_challenge_score WHERE challenge_id=? AND user=?",
            (cid, user)).fetchone()
        # 每人多次作答只保留最好成绩（并列看连击）
        if prev is None or (score, combo) > (prev["score"], prev["combo"]):
            conn.execute(
                """INSERT INTO sprint_challenge_score(challenge_id,user,name,score,combo,total,updated_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(challenge_id,user) DO UPDATE SET
                     name=excluded.name, score=excluded.score, combo=excluded.combo,
                     total=excluded.total, updated_at=excluded.updated_at""",
                (cid, user, display_name(conn, user), score, combo, total, now()))
        scores = conn.execute(
            "SELECT name,score,combo,total FROM sprint_challenge_score "
            "WHERE challenge_id=? ORDER BY score DESC, combo DESC, updated_at LIMIT 50",
            (cid,)).fetchall()
    return resp({"scores": [dict(s) for s in scores],
                 "record": prev is None or (score, combo) > (prev["score"], prev["combo"])})
