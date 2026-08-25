"""挑战玩法：听音选词出题 / 限时冲刺最佳成绩。"""
import json
import random
import uuid
from datetime import date

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .catalog import clamp_int, now
from .config import CONFIG, MATERIALS
from .db import db
from .materials import _material_index, audio_url, load_material

bp = Blueprint("challenge", __name__)


def _int_or_none(raw):
    # 显式拒绝 bool/float：int(True)==1、int(3.9)==3 都不是合法成绩
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


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
    today = date.today().isoformat()

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


def _sprint_items(list_key, n):
    """随机抽 n 个词生成冲刺词流；限时冲刺与挑战链接共用同一形状。"""
    material = load_material(list_key)
    pool = random.sample(material, min(n, len(material)))
    return [{"id": i["id"], "text": i["text"], "kind": i["kind"],
             "audio": audio_url(list_key, i["id"], i["text"])} for i in pool]


@bp.get("/api/sprint/session")
def api_sprint_session():
    """限时冲刺词流：随机抽词，不建会话、不计每日配额。"""
    list_key = request.args.get("list", "cet4")
    n = clamp_int(request.args.get("n"), 40, 1, 100)
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "限时冲刺仅支持词汇素材"}), 400
    return resp({"items": _sprint_items(list_key, n)})


@bp.get("/api/sprint/best")
def api_sprint_best():
    user = get_user()
    with db() as conn:
        row = conn.execute("SELECT score, combo, total FROM sprint_best WHERE user=?", (user,)).fetchone()
    return resp({"best": {"score": row["score"], "combo": row["combo"], "total": row["total"]}
                 if row else None})


@bp.post("/api/sprint/best")
def api_sprint_best_post():
    """上报冲刺成绩；只保留历史最高分（并列最高时保留更高连击）。"""
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    score = _int_or_none(data.get("score"))
    if score is None or not 0 <= score <= 999:
        return jsonify({"error": "score 无效"}), 400
    combo = clamp_int(data.get("combo"), 0, 0, 999)
    total = clamp_int(data.get("total"), 0, 0, 9999)

    stamp = date.today().isoformat()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT score, combo FROM sprint_best WHERE user=?", (user,)).fetchone()
        if row is None or (score, combo) > (row["score"], row["combo"]):
            conn.execute("""
                INSERT INTO sprint_best(user, score, combo, total, updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(user) DO UPDATE SET
                    score=excluded.score, combo=excluded.combo,
                    total=excluded.total, updated_at=excluded.updated_at
            """, (user, score, combo, total, stamp))
        best = conn.execute(
            "SELECT score, combo, total FROM sprint_best WHERE user=?", (user,)).fetchone()
    return resp({"best": {"score": best["score"], "combo": best["combo"], "total": best["total"]},
                 "record": score > (row["score"] if row else -1)})


# ---------------- 异步冲刺挑战：同词流、比分榜，无需 WebSocket ----------------

def _display_name(conn, user):
    """登录用户显示用户名；游客显示 游客xxxx。"""
    row = conn.execute("SELECT username FROM account WHERE user_id=?", (user,)).fetchone()
    if row:
        return row["username"]
    tail = "".join(ch for ch in user if ch.isalnum())[:4] or "0000"
    return f"游客{tail}"


@bp.post("/api/sprint/challenge")
def api_sprint_challenge_create():
    """用当前素材随机抽词生成挑战词流，返回可分享的挑战 id。"""
    user = get_user()
    list_key = request.args.get("list", "cet4")
    n = clamp_int(request.args.get("n"), 40, 5, 100)
    if list_key not in MATERIALS or MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "未知素材"}), 404
    items = _sprint_items(list_key, n)
    cid = uuid.uuid4().hex[:10]
    with db() as conn:
        conn.execute(
            "INSERT INTO sprint_challenge(id,owner_user,owner_name,list_key,items,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (cid, user, _display_name(conn, user), list_key,
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


@bp.post("/api/sprint/challenge/<cid>/score")
def api_sprint_challenge_score(cid):
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    score = _int_or_none(data.get("score"))
    if score is None or not 0 <= score <= 999:
        return jsonify({"error": "score 无效"}), 400
    combo = clamp_int(data.get("combo"), 0, 0, 999)
    total = clamp_int(data.get("total"), 0, 0, 9999)

    with db() as conn:
        if not conn.execute("SELECT 1 FROM sprint_challenge WHERE id=?", (cid,)).fetchone():
            return jsonify({"error": "挑战不存在或已过期"}), 404
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
                (cid, user, _display_name(conn, user), score, combo, total, now()))
        scores = conn.execute(
            "SELECT name,score,combo,total FROM sprint_challenge_score "
            "WHERE challenge_id=? ORDER BY score DESC, combo DESC, updated_at LIMIT 50",
            (cid,)).fetchall()
    return resp({"scores": [dict(s) for s in scores],
                 "record": prev is None or (score, combo) > (prev["score"], prev["combo"])})
