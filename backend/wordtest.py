"""词汇量等级测试：自适应难度阶梯，估算 CEFR 等级与词汇量。

出牌规则：
- 难度等级 1~18，对应 CEFR A1→C2。
- 每次从当前等级所在区间的词池中挑一道「听音选义」题（4 选项）。
- 答对 +1 级，答错 -1 级，最低 1 级。
- 满 25 题或连续 5 题答错即结束。

服务端会话（wordtest_session）：level / answered / correct_count / used_ids /
当前题（含答案）全部存服务端，客户端只持 session_id——无状态协议时代
客户端自带 level 随便填，C2 一点就有。每日每人限开 DAILY_LIMIT 局；
结果落 wordtest_result 表，detail 为逐题记录。
"""
import json
import random
from datetime import date
from uuid import uuid4

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .catalog import now
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
    """从 level 区间词池中挑一道 4 选项题。

    used_ids：已出现过的词 id 集合（会被加入本题正确词）。
    返回 {word, phonetic, audio, options: [{text, correct}], id}
    或 None（词池不足）。
    """
    # 收集候选：从 level 向外扩，攒够 6 个。按 id 去重——相邻 offset 的
    # 区间互相重叠（offset=0 扫 level，offset=1 又扫 level-1..level+1），
    # 不去重同一词会重复进 candidates，rng.sample 可能抽出两个相同选项。
    # 注意只能加进局部 seen：used_ids 只收入题的词。
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

    # 种子含 level + used_ids 排序后字符串：同一天同一状态出同一题，
    # 仅供调试复现，正确性不依赖它（当前题存在会话行里，不靠复算）
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
    """下发给客户端的题面：剥离 correct 标志。判分在服务端，
    正确选项随题面下发等于把答案送给会开 devtools 的人。"""
    if q is None:
        return None
    return {**q, "options": [{"text": o["text"]} for o in q["options"]]}


@bp.post("/api/wordtest/start")
def api_wordtest_start():
    """开局：服务端建会话，客户端只拿 session_id 与题面。"""
    user = get_user()
    today = date.today().isoformat()
    with db(immediate=True) as conn:   # 计数-判-写须原子：并发开局不能双双绕过日限
        started = conn.execute(
            "SELECT COUNT(*) c FROM wordtest_session "
            "WHERE user=? AND substr(created_at,1,10)=?",
            (user, today)).fetchone()["c"]
        if started >= DAILY_LIMIT:
            return jsonify({"error": f"今天已测 {DAILY_LIMIT} 次，明天再来"}), 429
        level = (MIN_DIFFICULTY + MAX_DIFFICULTY) // 2
        used_ids = set()
        q = _pick_question(level, used_ids)
        if q is None:
            return jsonify({"error": "词池不可用"}), 503
        sid = uuid4().hex
        conn.execute(
            "INSERT INTO wordtest_session(id,user,level,answered,correct_count,"
            "consecutive_wrong,used_ids,question,history,done,created_at) "
            "VALUES(?,?,?,0,0,0,?,?,?,0,?)",
            (sid, user, level, json.dumps(sorted(used_ids)),
             json.dumps(q, ensure_ascii=False), "[]", now()))
    return resp({"session_id": sid, "question": _public(q), "level": level,
                 "answered": 0, "consecutive_wrong": 0, "done": False})


@bp.post("/api/wordtest/answer")
def api_wordtest_answer():
    """提交答案：会话状态全在服务端行里，判分、推进、落表一事务完成。"""
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    sid = data.get("session_id")
    option_text = data.get("option", "")
    if not isinstance(sid, str) or not sid or not isinstance(option_text, str):
        return jsonify({"error": "参数无效"}), 400

    with db(immediate=True) as conn:
        row = conn.execute(
            "SELECT * FROM wordtest_session WHERE id=?", (sid,)).fetchone()
        if not row or row["user"] != user:
            return jsonify({"error": "会话不存在或已过期"}), 404
        if row["done"]:
            return jsonify({"error": "本场测试已结束"}), 409

        q = json.loads(row["question"])
        level = row["level"]
        used_ids = set(json.loads(row["used_ids"]))
        history = json.loads(row["history"])

        right = any(o["text"] == option_text and o["correct"] for o in q["options"])
        history.append({"level": level, "word": q["word"], "right": right})

        if right:
            new_level = min(MAX_DIFFICULTY, level + 1)
            new_consec = 0
        else:
            new_level = max(MIN_DIFFICULTY, level - 1)
            new_consec = row["consecutive_wrong"] + 1
        new_answered = row["answered"] + 1
        correct_count = row["correct_count"] + int(right)
        done = new_answered >= MAX_QUESTIONS or new_consec >= CONSECUTIVE_WRONG_LIMIT

        next_q = None if done else _pick_question(new_level, used_ids)
        if not done and next_q is None:
            done = True   # 词池见底（生产词库不会，小词池兜底）：按当前成绩完赛

        if done:
            final_cefr = _cefr_of(new_level)
            final_word_count = LEVEL_TO_WORD_COUNT[new_level]
            conn.execute(
                "UPDATE wordtest_session SET level=?, answered=?, correct_count=?, "
                "consecutive_wrong=?, used_ids=?, question=NULL, history=?, done=1 "
                "WHERE id=?",
                (new_level, new_answered, correct_count, new_consec,
                 json.dumps(sorted(used_ids)), json.dumps(history, ensure_ascii=False), sid))
            conn.execute(
                "INSERT INTO wordtest_result(user, level, questions_answered, "
                "correct_count, cefr, word_count, detail, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (user, new_level, new_answered, correct_count, final_cefr,
                 final_word_count, json.dumps(history, ensure_ascii=False), now()))
            return resp({
                "done": True, "right": right,
                "level": new_level, "cefr": final_cefr,
                "cefr_title": CEFR_TITLE[final_cefr],
                "word_count": final_word_count,
                "answered": new_answered, "correct_count": correct_count,
            })

        conn.execute(
            "UPDATE wordtest_session SET level=?, answered=?, correct_count=?, "
            "consecutive_wrong=?, used_ids=?, question=?, history=? WHERE id=?",
            (new_level, new_answered, correct_count, new_consec,
             json.dumps(sorted(used_ids)), json.dumps(next_q, ensure_ascii=False),
             json.dumps(history, ensure_ascii=False), sid))
        return resp({
            "right": right, "level": new_level,
            "question": _public(next_q),
            "answered": new_answered,
            "consecutive_wrong": new_consec,
            "correct_count": correct_count,
            "done": False,
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
