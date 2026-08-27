"""每日挑战「今日词力」：日期+词库做随机种子，全站同词库同题、服务端判分。

出题与判分共用同一份确定性重建：客户端只提交所选选项 id，正确与否由服务端
重放当日题组比对得出，分数无法伪造。成绩每人每天只记第一次（PK(day,user)），
之后可重玩但不再记录。题目不写 daily_log / word_state / daily_practice_log，
听打统计口径保持纯净（与 quiz/sprint 一致）。
"""
import json
import random
from datetime import date

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .catalog import clamp_int, now
from .config import MATERIALS
from .db import db
from .friends import notify_level, record_activity
from .materials import audio_url, load_material
from .profile import derive_profile

bp = Blueprint("daily", __name__)

DAILY_QUESTIONS = 10
KIND_PLAN = ["audio_en"] * 5 + ["en_zh"] * 3 + ["zh_en"] * 2   # 音→形 / 音→义 / 义→形


def _rng(day, list_key, round_no=0):
    # 练习局（round_no>=1）在种子里追加轮次：同一天每一轮都是另一批题，
    # 且同一轮次在任何进程重放仍完全一致
    seed = f"daily|{day}|{list_key}" + (f"|r{round_no}" if round_no else "")
    return random.Random(seed)


def _kind_plan(rng, n):
    """按配额取题型前缀再洗牌；题数不足 10 时截断前缀（仍确定）。"""
    plan = KIND_PLAN[:n] if n <= len(KIND_PLAN) else [
        KIND_PLAN[i % len(KIND_PLAN)] for i in range(n)]
    rng.shuffle(plan)
    return plan


def _build_questions(list_key, day, round_no=0):
    """确定性生成题组：同一种子在任何进程/时间重放都得到完全一致的题。"""
    material = load_material(list_key)
    rng = _rng(day, list_key, round_no)

    # 目标池按文本去重后按 id 排序再洗牌：重复单词（hello / hello~2）只留一个，
    # 排序保证不依赖字典插入序；干扰项同样按"去重后的文本"抽样，
    # 避免同文异 id 选项让用户点视觉正确的词也被判错
    by_text = {}
    for i in material:
        by_text.setdefault(i["text"], i)
    pool = sorted(by_text.values(), key=lambda x: x["id"])
    rng.shuffle(pool)
    targets = pool[:min(DAILY_QUESTIONS, len(pool))]
    kinds = _kind_plan(rng, len(targets))

    questions = []
    for target, kind in zip(targets, kinds):
        if kind == "zh_en" and not (target.get("meaning") or "").strip():
            kind = "audio_en"   # 无释义的词退化为听音选形，数据驱动仍确定
        others = [i for t, i in by_text.items() if t != target["text"]]
        if kind == "en_zh":
            # 选项是中文释义：排除与目标同释义的词，避免出现双正确项
            filtered = [i for i in others
                        if (i.get("meaning") or "") != (target.get("meaning") or "")]
            if len(filtered) >= 3 or len(filtered) >= len(others):
                others = filtered
        options = [target] + rng.sample(others, min(3, len(others)))
        rng.shuffle(options)
        questions.append({
            "id": target["id"],
            "text": target["text"],   # playWord 靠 text 拼真人发音 URL
            "kind": kind,
            "audio": audio_url(list_key, target["id"], target["text"]),
            "options": [{"id": o["id"], "text": o["text"],
                         "phonetic": o.get("phonetic") or "",
                         "meaning": o.get("meaning") or ""} for o in options],
        })
    return questions


def _stored_result(conn, day, user):
    row = conn.execute(
        "SELECT list_key,score,total,detail FROM daily_challenge WHERE day=? AND user=?",
        (day, user)).fetchone()
    if row is None:
        return None
    return {"list": row["list_key"], "score": row["score"], "total": row["total"],
            "detail": json.loads(row["detail"])}


@bp.get("/api/daily")
def api_daily():
    """当日题组。已完成时附带 my_result，前端直接进结算页（可重玩但不计分）。

    ?r=<n> 请求练习局：种子加轮次后缀出另一批题，不读也不产生正式成绩；
    判分端点只认无轮次的正式题组，练习局的答案提交会被原样拒绝。
    """
    list_key = request.args.get("list", "cet4")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "每日挑战仅支持词汇素材"}), 400
    round_no = clamp_int(request.args.get("r"), 0, 0, 99)

    day = date.today().isoformat()
    questions = _build_questions(list_key, day, round_no)
    if len(questions) < 2:
        return jsonify({"error": "该素材词太少，无法出题"}), 400

    payload = {
        "day": day, "list": list_key,
        "list_title": MATERIALS[list_key]["title"],
        "total": len(questions), "questions": questions,
        "practice": bool(round_no),
    }
    if round_no:
        payload.update({"completed": False, "my_result": None})
        return resp(payload)

    user = get_user()
    with db() as conn:
        result = _stored_result(conn, day, user)
    payload.update({"completed": result is not None, "my_result": result})
    return resp(payload)


@bp.post("/api/daily/result")
def api_daily_result():
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    list_key = data.get("list")
    if list_key not in MATERIALS or MATERIALS[list_key]["type"] != "words":
        return jsonify({"error": "未知素材"}), 400
    answers = data.get("answers")
    if not isinstance(answers, list):
        return jsonify({"error": "answers 无效"}), 400

    day = date.today().isoformat()
    questions = _build_questions(list_key, day)
    option_ids = {qd["id"]: {o["id"] for o in qd["options"]} for qd in questions}

    # 逐项严格校验：id 属于当日题组且不重复、picked 必须是其选项之一的字符串。
    # 正确性不在客户端提交里——picked 是否等于目标 id 由服务端判定。
    seen, picks = set(), []
    for a in answers:
        if not isinstance(a, dict):
            return jsonify({"error": "答案格式无效"}), 400
        qid, picked = a.get("id"), a.get("picked")
        if qid not in option_ids or qid in seen \
                or not isinstance(picked, str) or picked not in option_ids[qid]:
            return jsonify({"error": "答案与今日题目不符"}), 400
        seen.add(qid)
        picks.append((qid, picked))
    if len(seen) != len(option_ids):
        return jsonify({"error": "答案数量与题目不符"}), 400

    # 判分并按当日题组的规范顺序落 detail：乱序提交不影响存储与分享网格的次序
    pick_map = dict(picks)
    detail = [{"id": qd["id"], "kind": qd["kind"], "right": pick_map[qd["id"]] == qd["id"]}
              for qd in questions]
    score = sum(1 for d in detail if d["right"])

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        stored = _stored_result(conn, day, user)
        if stored is not None:
            # 双检兜底：并发重复提交也只会保留第一次成绩
            return resp({"duplicate": True, **stored})
        conn.execute(
            """INSERT INTO daily_challenge(day,user,list_key,score,total,detail,completed_at)
               VALUES(?,?,?,?,?,?,?)""",
            (day, user, list_key, score, len(questions),
             json.dumps(detail, ensure_ascii=False), now()))
        record_activity(conn, user, "daily_complete", {"score": score, "total": len(questions)})
        # 每日挑战计入经验：首个正式成绩是升级探测的天然检查点
        notify_level(conn, user)
        payload = {"duplicate": False, "day": day, "score": score,
                   "total": len(questions), "detail": detail,
                   "profile": derive_profile(conn, user)}
    return resp(payload)
