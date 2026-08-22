"""挑战玩法：听音选词出题 / 限时冲刺最佳成绩。"""
import random
from datetime import date

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .config import CONFIG, MATERIALS
from .db import db
from .materials import _material_index, audio_url, load_material

bp = Blueprint("challenge", __name__)


def _clamp_int(raw, default, lo, hi):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


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
    n = _clamp_int(request.args.get("n"), CONFIG.get("quiz_questions", 10), 1, 30)
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


@bp.get("/api/sprint/session")
def api_sprint_session():
    """限时冲刺词流：随机抽词，不建会话、不计每日配额。"""
    list_key = request.args.get("list", "cet4")
    n = _clamp_int(request.args.get("n"), 40, 1, 100)
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "限时冲刺仅支持词汇素材"}), 400
    material = load_material(list_key)
    pool = random.sample(material, min(n, len(material)))
    items = [{"id": i["id"], "text": i["text"], "kind": i["kind"],
              "audio": audio_url(list_key, i["id"], i["text"])} for i in pool]
    return resp({"items": items})


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
    combo = _clamp_int(data.get("combo"), 0, 0, 999)
    total = _clamp_int(data.get("total"), 0, 0, 9999)

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
