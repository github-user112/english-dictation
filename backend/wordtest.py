"""词汇量等级测试：自适应难度阶梯，估算 CEFR 等级与词汇量。

出牌规则：
- 难度等级 1~18，对应 CEFR A1→C2。
- 每次从当前等级所在区间的词池中挑一道「听音选义」题（4 选项）。
- 答对 +1 级，答错 -1 级，最低 1 级。
- 满 25 题或连续 5 题答错即结束。

服务端无状态：客户端携带 level + used_ids（已见词集合）+ correct_count，
服务端用确定性种子复算当前题，判断正确后推进到下一题。
词汇量估算基于最终等级；结果落 wordtest_result 表；
每日每人限完成 5 次（push_meta 计数，开局只预检、完成时才扣额）。
"""
import json
import random
from datetime import date

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .catalog import now
from .config import MATERIALS
from .db import db
from .materials import load_material, audio_url

bp = Blueprint("wordtest", __name__)

MAX_DIFFICULTY = 18
MIN_DIFFICULTY = 1
MAX_QUESTIONS = 25
CONSECUTIVE_WRONG_LIMIT = 5
DAILY_LIMIT = 5

# 素材库 → 难度区间（按大致 CEFR 分布）
TIER_MAP = [
    ("cet4", 6, 11),
    ("cet6", 11, 15),
    ("kaoyan", 9, 14),
    ("tuofu", 13, 18),
]

LEVEL_TO_CEFR = {
    (1, 3): "A1", (4, 6): "A2", (7, 9): "B1",
    (10, 12): "B2", (13, 15): "C1", (16, 18): "C2",
}
LEVEL_TO_WORD_COUNT = {
    1: 200, 2: 300, 3: 500, 4: 750, 5: 1000, 6: 1500,
    7: 2000, 8: 2500, 9: 3500, 10: 4500, 11: 5500, 12: 7000,
    13: 8000, 14: 9000, 15: 10000, 16: 11000, 17: 12000, 18: 15000,
}
CEFR_TITLE = {
    "A1": "入门", "A2": "基础", "B1": "中级",
    "B2": "中高级", "C1": "高级", "C2": "精通",
}


# ---- 词池：一次性加载，难度等级 → 词条列表 ----
def _build_bank():
    bank = {lv: [] for lv in range(MIN_DIFFICULTY, MAX_DIFFICULTY + 1)}
    for list_key, lo, hi in TIER_MAP:
        try:
            items = load_material(list_key)
        except Exception:
            continue
        for it in items:
            if not it.get("meaning"):
                continue
            for lv in range(lo, hi + 1):
                bank[lv].append(it)
    return bank


_BANK = _build_bank()


def _cefr_of(level):
    for (lo, hi), cefr in LEVEL_TO_CEFR.items():
        if lo <= level <= hi:
            return cefr
    return "A1"


def _pick_question(level, used_ids):
    """确定性出牌：从 level 区间词池中挑一道 4 选项题。

    used_ids：已出现过的词 id 集合（用于去重）。
    返回 {word, phonetic, audio, options: [{text, correct}], id}
    或 None（词池不足）。
    """
    # 收集候选：从 level 向外扩，攒够 6 个。按 id 去重——相邻 offset 的
    # 区间互相重叠（offset=0 扫 level，offset=1 又扫 level-1..level+1），
    # 不去重同一词会重复进 candidates，rng.sample 可能抽出两个相同选项。
    # 注意只能加进局部 seen：seed 须等于客户端携带的 used_ids 原样。
    candidates = []
    seen = set(used_ids)
    for offset in range(0, 4):
        for lv in range(max(MIN_DIFFICULTY, level - offset),
                        min(MAX_DIFFICULTY, level + offset) + 1):
            for it in _BANK[lv]:
                if it["id"] not in seen and it["meaning"]:
                    seen.add(it["id"])
                    candidates.append(it)
            if len(candidates) >= 6:
                break
        if len(candidates) >= 6:
            break
    if len(candidates) < 4:
        return None

    # 种子含 level + used_ids 排序后字符串 → 确定性
    seed = f"wt|{date.today().isoformat()}|{level}|{sorted(used_ids)}"
    rng = random.Random(seed)
    correct = rng.choice(candidates)
    used_ids.add(correct["id"])

    # 干扰项按释义去重：两个同义词条并排出现，「听音选义」就有两个都对
    pool_left = []
    seen_meanings = {correct["meaning"]}
    for c in candidates:
        if c["meaning"] not in seen_meanings:
            seen_meanings.add(c["meaning"])
            pool_left.append(c)
    if len(pool_left) < 3:
        return None
    distractors = rng.sample(pool_left, 3)
    options = [correct] + distractors
    rng.shuffle(options)

    # 音频：尝试用正确词所在素材库的音频
    audio = ""
    for lk, lo, hi in TIER_MAP:
        if lo <= level <= hi:
            audio = audio_url(lk, correct["id"], correct["text"])
            break

    return {
        "id": correct["id"],
        "word": correct["text"],
        "phonetic": correct.get("phonetic", ""),
        "audio": audio,
        "options": [
            {"text": o["meaning"].strip(), "correct": (o is correct)}
            for o in options
        ],
    }


def _public(q):
    """下发给客户端的题面：剥离 correct 标志。判分在服务端复算，
    正确选项随题面下发等于把答案送给会开 devtools 的人。"""
    if q is None:
        return None
    return {**q, "options": [{"text": o["text"]} for o in q["options"]]}


def _daily_used(conn, user, today):
    row = conn.execute(
        "SELECT value FROM push_meta WHERE name=?", (f"wordtest|{user}|{today}",)).fetchone()
    return int(row["value"]) if row else 0


@bp.get("/api/wordtest/question")
def api_wordtest_question():
    """获取当前题。参数：level, used_ids（逗号分隔），客户端首次调此接口开局。"""
    user = get_user()
    try:
        level = int(request.args.get("level", (MIN_DIFFICULTY + MAX_DIFFICULTY) // 2))
        answered = int(request.args.get("answered", 0))
        consecutive_wrong = int(request.args.get("consecutive_wrong", 0))
    except ValueError:
        return jsonify({"error": "参数无效"}), 400

    used_ids = set(request.args.get("used_ids", "").split(",")) if request.args.get("used_ids") else set()
    level = max(MIN_DIFFICULTY, min(MAX_DIFFICULTY, level))

    # 首次开局（answered=0 且 used_ids 为空）预检每日限流——只读不扣额，
    # 额度在完成落表时原子扣减（否则中途弃测也占一次，脚本刷 /answer 却不占）
    if answered == 0 and not used_ids:
        with db() as conn:
            if _daily_used(conn, user, date.today().isoformat()) >= DAILY_LIMIT:
                return jsonify({"error": f"今天已测 {DAILY_LIMIT} 次，明天再来"}), 429

    q = _pick_question(level, used_ids)
    if q is None:
        return resp({"done": True})

    return resp({"question": _public(q), "done": False,
                 "level": level, "answered": answered,
                 "consecutive_wrong": consecutive_wrong})


@bp.post("/api/wordtest/answer")
def api_wordtest_answer():
    """提交答案，服务端复算当前题判断正确，返回下一题或最终结果。"""
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400

    option_text = data.get("option", "")
    if not isinstance(option_text, str):
        return jsonify({"error": "选项无效"}), 400

    try:
        level = int(data.get("level", (MIN_DIFFICULTY + MAX_DIFFICULTY) // 2))
        answered = int(data.get("answered", 0))
        consecutive_wrong = int(data.get("consecutive_wrong", 0))
        prev_correct = int(data.get("correct_count", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "参数无效"}), 400

    used_ids = set(data.get("used_ids", "").split(",")) if data.get("used_ids") else set()
    level = max(MIN_DIFFICULTY, min(MAX_DIFFICULTY, level))

    # 复算当前题（同 seed → 同问题）
    q = _pick_question(level, used_ids)
    if q is None:
        return resp({"done": True})

    # 判分
    right = False
    for opt in q["options"]:
        if opt["text"] == option_text:
            right = opt["correct"]
            break

    used_ids.add(q["id"])

    if right:
        new_level = min(MAX_DIFFICULTY, level + 1)
        new_consec = 0
    else:
        new_level = max(MIN_DIFFICULTY, level - 1)
        new_consec = consecutive_wrong + 1

    new_answered = answered + 1
    # correct_count 是客户端回传的前序答对数（无状态协议的一部分），
    # 钳到 [0, answered] 防胡填，再加本题
    correct_count = max(0, min(prev_correct, answered)) + int(right)
    done = new_answered >= MAX_QUESTIONS or new_consec >= CONSECUTIVE_WRONG_LIMIT

    if not done:
        # 出下一题
        next_q = _pick_question(new_level, used_ids)
        return resp({
            "right": right, "level": new_level,
            "question": _public(next_q),
            "answered": new_answered,
            "consecutive_wrong": new_consec,
            "correct_count": correct_count,
            "done": False,
        })

    # 结束：限流扣额与落表同事务——脚本直接刷 /answer 也每天最多 DAILY_LIMIT 行
    final_cefr = _cefr_of(new_level)
    final_word_count = LEVEL_TO_WORD_COUNT[new_level]
    detail = json.dumps([
        {"level": level, "word": q["id"], "right": right}
    ], ensure_ascii=False)

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        today = date.today().isoformat()
        used = _daily_used(conn, user, today)
        if used >= DAILY_LIMIT:
            conn.rollback()
            return jsonify({"error": f"今天已测 {DAILY_LIMIT} 次，明天再来"}), 429
        conn.execute(
            "INSERT INTO push_meta(name,value) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (f"wordtest|{user}|{today}", str(used + 1)))
        conn.execute(
            "INSERT INTO wordtest_result(user, level, questions_answered, "
            "correct_count, cefr, word_count, detail, created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (user, new_level, new_answered,
             correct_count, final_cefr, final_word_count,
             detail, now()))

    return resp({
        "done": True, "right": right,
        "level": new_level, "cefr": final_cefr,
        "cefr_title": CEFR_TITLE[final_cefr],
        "word_count": final_word_count,
        "answered": new_answered, "correct_count": correct_count,
    })


@bp.get("/api/wordtest/result")
def api_wordtest_result():
    """最近一次测试结果。"""
    user = get_user()
    with db() as conn:
        row = conn.execute(
            "SELECT level, questions_answered, correct_count, cefr, "
            "word_count, created_at FROM wordtest_result "
            "WHERE user=? ORDER BY created_at DESC LIMIT 1",
            (user,)).fetchone()
    if not row:
        return resp({"result": None})
    return resp({
        "result": {
            "level": row["level"],
            "questions_answered": row["questions_answered"],
            "correct_count": row["correct_count"],
            "cefr": row["cefr"],
            "cefr_title": CEFR_TITLE.get(row["cefr"], ""),
            "word_count": row["word_count"],
            "created_at": row["created_at"],
        }
    })


@bp.get("/api/wordtest/history")
def api_wordtest_history():
    """最近 10 次测试历史。"""
    user = get_user()
    with db() as conn:
        rows = conn.execute(
            "SELECT level, questions_answered, correct_count, cefr, "
            "word_count, created_at FROM wordtest_result "
            "WHERE user=? ORDER BY created_at DESC LIMIT 10",
            (user,)).fetchall()
    return resp({
        "history": [
            {"level": r["level"], "questions_answered": r["questions_answered"],
             "correct_count": r["correct_count"], "cefr": r["cefr"],
             "word_count": r["word_count"], "created_at": r["created_at"]}
            for r in rows
        ]
    })