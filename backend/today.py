"""今日动线：把五环任务聚合成一个接口，前端首页纯渲染。

判据全部从现有学习表实时推导，不建任务表（与 achievements/profile 同一哲学）。

按课模式（主线，NCE）：词库和句库都带课次时启用，每天学当前课——
- 背单词/单词听打：本课的单词；句子听写/听读跟读：本课的句子
- "当前课"从句库 study_session 推导：最后一课会话已完成且不是今天完成的 → 明天起推进下一课；
  今天完成的留在本课，保证"每天一课"打卡节奏；学完整册停在最后一课
- nce1 词汇按双课合并（课号 1,3,5…），对应句库课号 2L-1；其余册课号与句库一致

配额模式（回退，CET 等无课词库）：
- 背新词：今日 last_memorize=today 且 memorized=1 的词数 ≥ 学习计划配额
- 听打巩固：今日在目标词库上 final_right 的题数 ≥ min(15, 配额)

跨午夜的会话按 assigned_day 归属；会话在创建日之后某天被打完时，完成那一刻
assigned_day 会重挂到完成日（catalog.py /api/result），保证「今天完成」的判定跟得上。
"""
from datetime import date, timedelta

from flask import Blueprint, request

from .auth import get_user, resp
from .config import CONFIG, MATERIALS
from .db import db
from .goal import _goal_view
from .materials import iter_material, load_material
from .misc import local_today, user_streak

bp = Blueprint("today", __name__)

# 词测 CEFR → 推荐词库/句库（P1：测完一键建计划也用这个映射）
# 今日主线只走新概念 1-4：词汇册配同册课文，保证五环既有单词也有句子；
# 其他词库（CET 等）留在素材库自由练习
CEFR_TO_LIST = {
    "A1": ("nce1", "nc1"), "A2": ("nce1", "nc1"), "B1": ("nce2", "nc2"),
    "B2": ("nce3", "nc3"), "C1": ("nce4", "nc4"), "C2": ("nce4", "nc4"),
}
# 默认主线：新概念 1 册词汇 + 第 1 册课文，由低到高顺着学
DEFAULT_WORD_LIST = "nce1"
DEFAULT_SENT_LIST = "nc1"
SHADOW_TARGET = 5   # 跟读环：今日跟读优秀（≥85 分）句数达标即完成
WRONG_TARGET = 10   # 错词回收一组的词数：今日错词优先，不够从错词本补满
# 今日可选词库池：nce 素材缺失时退到全部词库（测试环境）。
# 每次调用现算——测试会按用例 patch 本模块的 MATERIALS，import 时固化会被绕过
def _word_pool():
    nce = [k for k in ("nce1", "nce2", "nce3", "nce4")
           if MATERIALS.get(k, {}).get("type") == "words"]
    return nce or [k for k, m in MATERIALS.items() if m["type"] == "words"]


def _first_of_type(kind):
    return next((k for k, m in MATERIALS.items() if m["type"] == kind), None)


def _pick_lists(conn, user, cefr, want_word=None):
    """目标词库/句库：用户选择 > 学习计划 > 词测推荐 > 默认 nce1，词库限定在今日主线池。"""
    goals = conn.execute(
        "SELECT * FROM study_goal WHERE user=? ORDER BY updated_at DESC", (user,)).fetchall()
    rec_word, rec_sent = CEFR_TO_LIST.get(cefr, (None, None))
    pool = _word_pool()
    word = want_word or next((g["list"] for g in goals if g["list"] in pool), None) or rec_word
    if word not in pool:
        word = DEFAULT_WORD_LIST if DEFAULT_WORD_LIST in pool else (pool[0] if pool else None)
    # 句库跟着词库走：nceN 词汇配 ncN 课文；否则用词测推荐
    sent = None
    if word and word.startswith("nce") and "nc" + word[3:] in MATERIALS:
        sent = "nc" + word[3:]
    sent = sent or rec_sent
    if sent not in MATERIALS or MATERIALS.get(sent, {}).get("type") != "sentences":
        sent = DEFAULT_SENT_LIST if MATERIALS.get(DEFAULT_SENT_LIST, {}).get("type") == "sentences" \
            else _first_of_type("sentences")
    return word, sent


def _lessons(list_key):
    return sorted({i.get("lesson") for i in load_material(list_key)
                   if i.get("lesson") is not None})


def _word_lesson(word_lessons, sent_lessons, sent_no):
    """句库课号 → 词库课号。nce1 词汇按双课合并（1,3,5…），课号是句课的 2L-1；
    其余册课号一致。词库缺该课（如 nce4 第 21 课无生词）返回 None。"""
    if not word_lessons or not sent_lessons:
        return None
    w = 2 * sent_no - 1 if max(word_lessons) > max(sent_lessons) else sent_no
    return w if w in set(word_lessons) else None


def _current_lesson(conn, user, list_key, today):
    """当前应学的课号与该课条目数；无课素材返回 (None, 0)。
    今天完成的课当天不跳（今天的打卡对象还是它），明天起才推进到下一课。
    按最高课号定位：假设顺序学习——回炉低课是自由练习，不应把主线进度拽回去。"""
    lessons = _lessons(list_key)
    if not lessons:
        return None, 0
    row = conn.execute(
        "SELECT lesson, state, assigned_day FROM study_session WHERE user=? AND list=? "
        "AND lesson IS NOT NULL ORDER BY lesson DESC, rowid DESC LIMIT 1", (user, list_key)).fetchone()
    lesson = lessons[0]
    if row and row["lesson"] in lessons:
        lesson = row["lesson"]
        if row["state"] == "completed" and row["assigned_day"] != today:
            later = [n for n in lessons if n > lesson]
            lesson = later[0] if later else lesson   # 学完整册：停在最后一课复习
    total = sum(1 for i in load_material(list_key) if i.get("lesson") == lesson)
    return lesson, total


def _lesson_options(conn, user, sent_list, today):
    """返回该句库所有课的完成状态，前端用来渲染课程下拉。"""
    lessons = _lessons(sent_list)
    if not lessons:
        return []
    done_today = {r["lesson"] for r in conn.execute(
        "SELECT DISTINCT lesson FROM study_session WHERE user=? AND list=? "
        "AND state='completed' AND assigned_day=?",
        (user, sent_list, today))}
    done_ever = {r["lesson"] for r in conn.execute(
        "SELECT DISTINCT lesson FROM study_session WHERE user=? AND list=? "
        "AND state='completed'", (user, sent_list))}
    return [{"n": n, "done_today": n in done_today, "done_ever": n in done_ever}
            for n in lessons]


def _lesson_steps(conn, user, word_list, sent_list, today, shadow_done_n, wrong_pool, wrong_done_n, want_lesson=None):
    """按课五环：背本课单词 → 听打本课单词 → 听写本课句子 → 跟读 → 错词回收。

    want_lesson：用户显式选择的课号；有效时覆盖自动推导。
    返回 (steps, lesson, review_mode)。review_mode 为 true 时前端不锁任何一环。
    """
    lessons = _lessons(sent_list)
    if want_lesson and want_lesson in lessons:
        lesson = want_lesson
        sent_total = sum(1 for i in load_material(sent_list) if i.get("lesson") == lesson)
    else:
        lesson, sent_total = _current_lesson(conn, user, sent_list, today)
    wl = _word_lesson(_lessons(word_list), _lessons(sent_list), lesson)
    w_ids = [i["id"] for i in iter_material(word_list, wl)] if wl is not None else []

    # review_mode：该课句库有完成会话 → 所有环节可自由练习
    review_mode = bool(conn.execute(
        "SELECT 1 FROM study_session WHERE user=? AND list=? AND lesson=? "
        "AND state='completed' LIMIT 1",
        (user, sent_list, lesson)).fetchone())

    steps = []
    if w_ids:
        memorized = {r["item_id"] for r in conn.execute(
            "SELECT item_id FROM word_state WHERE user=? AND list=? AND memorized=1",
            (user, word_list))}
        mem_done_n = sum(1 for i in w_ids if i in memorized)
        steps.append({
            "key": "memorize", "title": "背单词", "minutes": 5,
            "desc": f"第 {lesson} 课 · {len(w_ids)} 个单词",
            "target": len(w_ids), "progress": mem_done_n, "done": mem_done_n >= len(w_ids),
            "link": f"#/memorize?list={word_list}&lesson={wl}&n={min(len(w_ids), 100)}&from=today"
                    + ("&review=1" if review_mode else ""),
        })
        dic_done_n = conn.execute(
            "SELECT COUNT(DISTINCT i.item_id) c FROM study_session s "
            "JOIN study_session_item i ON i.session_id=s.id "
            "WHERE s.user=? AND s.list=? AND s.lesson=? AND i.final_right=1",
            (user, word_list, wl)).fetchone()["c"]
        # 整课会话打完即算完成——个别没拼对的词已进错词本，由回收环节兜底
        dic_session_done = bool(conn.execute(
            "SELECT 1 FROM study_session WHERE user=? AND list=? AND lesson=? "
            "AND state='completed' LIMIT 1", (user, word_list, wl)).fetchone())
        steps.append({
            "key": "dictation", "title": "单词听打", "minutes": 5,
            "desc": f"第 {lesson} 课 · 听音拼写",
            "target": len(w_ids), "progress": min(dic_done_n, len(w_ids)),
            "done": dic_session_done or dic_done_n >= len(w_ids),
            "link": f"#/word?list={word_list}&lesson={wl}&from=today",
        })
    sent_done_n = conn.execute(
        "SELECT COUNT(*) c FROM study_session s JOIN study_session_item i ON i.session_id=s.id "
        "WHERE s.user=? AND s.list=? AND s.lesson=? AND s.assigned_day=? AND i.state='completed'",
        (user, sent_list, lesson, today)).fetchone()["c"]
    # 完成判定限定今天：同课若有更早的完成会话（重练场景），不该把今天的步骤标成已完成
    sent_finished = bool(conn.execute(
        "SELECT 1 FROM study_session WHERE user=? AND list=? AND lesson=? "
        "AND state='completed' AND assigned_day=? LIMIT 1", (user, sent_list, lesson, today)).fetchone())
    q = f"?list={sent_list}&lesson={lesson}&from=today"
    steps.append({
        "key": "sentence", "title": "句子听写", "minutes": 5,
        "desc": f"第 {lesson} 课 · {sent_total} 个句子",
        "target": sent_total, "progress": min(sent_done_n, sent_total),
        "done": sent_finished,
        "link": f"#/sentence{q}",
    })
    steps.append({
        "key": "shadow", "title": "听读跟读", "minutes": 5,
        "desc": f"第 {lesson} 课 · 跟读优秀 {SHADOW_TARGET} 句",
        "target": SHADOW_TARGET, "progress": min(shadow_done_n, SHADOW_TARGET),
        "done": shadow_done_n >= SHADOW_TARGET,
        "link": f"#/shadow{q}",
    })
    steps.append(_wrong_step(wrong_pool, wrong_done_n))
    return steps, lesson, review_mode


def _wrong_step(pool_n, done_n):
    """错词回收：一组 10 个，今天答错的优先、不够从错词本补；练完一组即完成。"""
    target = min(WRONG_TARGET, pool_n)
    return {
        "key": "wrong", "title": "错词回收", "minutes": 3,
        "desc": f"今日错词优先，凑满 {target} 个一组" if target else "错词本是空的，干得漂亮",
        "target": target, "progress": min(done_n, target),
        "done": target == 0 or done_n >= target,
        "link": "#/wrong?from=today",
    }


def build_today(conn, user, want_word=None, want_lesson=None):
    """聚合今日任务卡；独立成函数便于单测直接喂连接。want_word 为用户手动选的词库。"""
    today = local_today().isoformat()

    wt = conn.execute(
        "SELECT cefr, word_count FROM wordtest_result WHERE user=? "
        "ORDER BY created_at DESC LIMIT 1", (user,)).fetchone()
    cefr = wt["cefr"] if wt else None
    word_list, sent_list = _pick_lists(conn, user, cefr, want_word)

    # 跟读环进度：今日 shadow 桶的良好句数（review_count 零经验列，见 shadow.py）
    sh_row = conn.execute(
        "SELECT review_count c FROM daily_practice_log "
        "WHERE day=? AND user=? AND practice_mode='shadow'", (today, user)).fetchone()
    shadow_done_n = sh_row["c"] if sh_row else 0

    # 错词回收：池 = 错词本全部单词；进度 = 今日「wrong」桶已练题数（错词回收练习专用模式）
    wrong_pool = conn.execute(
        "SELECT COUNT(*) c FROM word_state WHERE user=? AND wrong_count>0 AND kind='word'",
        (user,)).fetchone()["c"]
    wrong_row = conn.execute(
        "SELECT new_count+review_count c FROM daily_practice_log "
        "WHERE day=? AND user=? AND practice_mode='wrong'", (today, user)).fetchone()
    wrong_done_n = wrong_row["c"] if wrong_row else 0

    lesson_mode = bool(word_list and sent_list and _lessons(word_list) and _lessons(sent_list))
    goal = None
    review_mode = False
    if lesson_mode:
        steps, lesson, review_mode = _lesson_steps(conn, user, word_list, sent_list, today,
                                       shadow_done_n, wrong_pool, wrong_done_n, want_lesson)
    else:
        # 配额模式：无课词库（CET 等）按学习计划定量推进
        quota = CONFIG["new_per_day"]
        if word_list:
            grow = conn.execute(
                "SELECT * FROM study_goal WHERE user=? AND list=?", (user, word_list)).fetchone()
            if grow:
                goal = _goal_view(conn, user, word_list, grow)
                quota = goal["daily_new"] if not goal["done"] else 0

        mem_done_n = conn.execute(
            "SELECT COUNT(*) c FROM word_state WHERE user=? AND list=? AND memorized=1 "
            "AND last_memorize=?", (user, word_list, today)).fetchone()["c"] if word_list else 0
        mem_finished = quota == 0 or mem_done_n >= quota

        dic_done_n = conn.execute(
            "SELECT COUNT(*) c FROM study_session s JOIN study_session_item i ON i.session_id=s.id "
            "WHERE s.user=? AND s.list=? AND s.assigned_day=? AND i.state='completed' AND i.final_right=1",
            (user, word_list, today)).fetchone()["c"] if word_list else 0
        dic_target = min(15, max(1, quota))

        lesson, lesson_total = _current_lesson(conn, user, sent_list, today) if sent_list else (None, 0)
        if sent_list:
            # 进度只算当前课；但"完成"放宽到今天完成过本素材任意一课会话——
            # 刚学完上一课推进到当前课时，不该立刻又欠一课
            sent_done_n = conn.execute(
                "SELECT COUNT(*) c FROM study_session s JOIN study_session_item i ON i.session_id=s.id "
                "WHERE s.user=? AND s.list=? AND s.lesson=? AND s.assigned_day=? AND i.state='completed'",
                (user, sent_list, lesson, today)).fetchone()["c"] if lesson is not None else conn.execute(
                "SELECT COUNT(*) c FROM study_session s JOIN study_session_item i ON i.session_id=s.id "
                "WHERE s.user=? AND s.list=? AND s.assigned_day=? AND i.state='completed'",
                (user, sent_list, today)).fetchone()["c"]
            sent_session_done = bool(conn.execute(
                "SELECT 1 FROM study_session WHERE user=? AND list=? AND assigned_day=? "
                "AND state='completed' LIMIT 1", (user, sent_list, today)).fetchone())
        else:
            sent_done_n, sent_session_done = 0, False
        sent_target = lesson_total or 10
        sent_finished = sent_session_done or sent_done_n >= sent_target

        steps = []
        if word_list:
            steps.append({
                "key": "memorize", "title": "背新词", "minutes": 5,
                "desc": f"{MATERIALS[word_list]['title']} · 今日 {quota} 个",
                "target": quota, "progress": min(mem_done_n, quota), "done": bool(mem_finished),
                "link": f"#/memorize?list={word_list}&n={min(quota, 100)}&from=today",
            })
            steps.append({
                "key": "dictation", "title": "听打巩固", "minutes": 5,
                "desc": "听音拼写今天背过的词",
                "target": dic_target, "progress": min(dic_done_n, dic_target),
                "done": dic_done_n >= dic_target,
                "link": f"#/word?list={word_list}&scope=memorized&from=today",
            })
        if sent_list:
            suffix = f" · 第 {lesson} 课" if lesson else ""
            q = f"?list={sent_list}" + (f"&lesson={lesson}" if lesson else "") + "&from=today"
            steps.append({
                "key": "sentence", "title": "句子听写", "minutes": 5,
                "desc": f"{MATERIALS[sent_list]['title']}{suffix}",
                "target": sent_target, "progress": min(sent_done_n, sent_target),
                "done": bool(sent_finished),
                "link": f"#/sentence{q}",
            })
            steps.append({
                "key": "shadow", "title": "听读跟读", "minutes": 5,
                "desc": f"跟读优秀 {SHADOW_TARGET} 句{suffix}",
                "target": SHADOW_TARGET, "progress": min(shadow_done_n, SHADOW_TARGET),
                "done": shadow_done_n >= SHADOW_TARGET,
                "link": f"#/shadow{q}",
            })
        steps.append(_wrong_step(wrong_pool, wrong_done_n))

    dc_done = bool(conn.execute(
        "SELECT 1 FROM daily_challenge WHERE user=? AND day=? LIMIT 1", (user, today)).fetchone())

    return {
        "date": today,
        "streak": user_streak(user, conn),   # 与 profile 同口径（含每日挑战、不截断长连胜）
        "has_wordtest": bool(wt),
        "wordtest": {"cefr": cefr, "word_count": wt["word_count"]} if wt else None,
        "word_list": {"key": word_list, "title": MATERIALS[word_list]["title"]} if word_list else None,
        "sent_list": {"key": sent_list, "title": MATERIALS[sent_list]["title"]} if sent_list else None,
        "word_options": [{"key": k, "title": MATERIALS[k]["title"]} for k in _word_pool()],
        "lesson": lesson,
        "lesson_total": len(_lessons(sent_list)) if sent_list else 0,
        "lesson_mode": lesson_mode,
        "lesson_options": _lesson_options(conn, user, sent_list, today) if sent_list else [],
        "review_mode": review_mode,
        "goal": goal,
        "steps": steps,
        "done_count": sum(1 for s in steps if s["done"]),
        "all_done": bool(steps) and all(s["done"] for s in steps),
        "daily_done": dc_done,
    }


@bp.get("/api/today")
def api_today():
    user = get_user()
    # ?list= 手动切换主线词库（前端存 localStorage，服务端不落库）；限定今日主线池
    want = request.args.get("list") or None
    if want and want not in _word_pool():
        want = None
    # ?lesson= 手动选择课程（回看已学课，全部环节可自由练习）
    want_lesson = request.args.get("lesson", type=int) or None
    with db() as conn:
        return resp(build_today(conn, user, want, want_lesson))
