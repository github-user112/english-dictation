"""素材目录 / 稳定学习会话 / 首答与最终结果。"""
import random
import uuid
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .config import AUDIO, CONFIG, MATERIALS, PRACTICE_MODES
from .db import db
from .friends import notify_level
from .materials import audio_url, find_item, iter_material, load_material
from .scheduler import review as fsrs_review, days_between

bp = Blueprint("catalog", __name__)

# 缓存：素材元信息（total / lesson_count）和音频文件数，避免每次请求遍历磁盘
_material_meta_cache = {}    # list_key -> {total, lesson_count}
_audio_count_cache = {}      # list_key -> (mtime, count)


def _material_meta(list_key):
    """获取素材总数和课数（缓存，因为素材不变）"""
    if list_key not in _material_meta_cache:
        material = load_material(list_key)
        _material_meta_cache[list_key] = {
            "total": len(material),
            "lesson_count": len({i.get("lesson") for i in material if i.get("lesson") is not None}),
        }
    return _material_meta_cache[list_key]


def _audio_done(list_key):
    """获取已生成音频数（按目录 mtime 缓存，只在变化时重新计数）"""
    audio_dir = AUDIO / list_key
    if not audio_dir.exists():
        return 0
    try:
        mtime = audio_dir.stat().st_mtime
    except OSError:
        return 0
    cached = _audio_count_cache.get(list_key)
    if cached and cached[0] == mtime:
        return cached[1]
    count = sum(1 for _ in audio_dir.glob("*.mp3"))
    _audio_count_cache[list_key] = (mtime, count)
    return count


def now():
    return datetime.now().isoformat(timespec="seconds")


def clamp_int(raw, default, minimum=0, maximum=100):
    # 与 challenge._int_or_none 同口径：int(True)==1、int(3.9)==3 不是合法输入
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def int_arg(name, default, minimum=0, maximum=100):
    return clamp_int(request.args.get(name), default, minimum, maximum)


def session_context():
    list_key = request.args.get("list", "cet4")
    mode = request.args.get("mode", "assisted")
    scope = request.args.get("scope", "all")
    lesson = request.args.get("lesson")
    lesson = int(lesson) if lesson and lesson.isdigit() else None
    strategy = "lesson" if lesson is not None else "daily"
    return list_key, mode, scope, lesson, strategy


def active_session(conn, user, list_key, mode, scope, strategy, lesson):
    # 按课学习不受词汇 scope 影响，但练习模式必须一致，确保界面行为、掌握度和统计口径一致。
    if strategy == "lesson":
        return conn.execute(
            "SELECT * FROM study_session WHERE user=? AND list=? AND practice_mode=? AND strategy='lesson' "
            "AND IFNULL(lesson,-1)=IFNULL(?,-1) AND state='active' "
            "ORDER BY created_at DESC LIMIT 1",
            (user, list_key, mode, lesson),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM study_session WHERE user=? AND list=? AND practice_mode=? AND scope=? "
        "AND strategy=? AND IFNULL(lesson,-1)=IFNULL(?,-1) AND state='active' "
        "ORDER BY created_at DESC LIMIT 1",
        (user, list_key, mode, scope, strategy, lesson),
    ).fetchone()


def serialize_item(list_key, row):
    item = find_item(list_key, row["item_id"])
    if not item:
        return None
    return {**item, "phase": row["phase"], "seq": row["seq"],
            "first_right": None if row["first_right"] is None else bool(row["first_right"]),
            "attempt_count": row["attempt_count"],
            "audio": audio_url(list_key, item["id"], item["text"])}


def serialize_session(conn, row, resumed=False, quota=None):
    all_rows = conn.execute(
        "SELECT * FROM study_session_item WHERE session_id=? ORDER BY seq", (row["id"],)
    ).fetchall()
    pending = [candidate for candidate in all_rows if candidate["state"] == "pending"]
    serialized = [(candidate, serialize_item(row["list"], candidate)) for candidate in pending]
    missing = [candidate for candidate, item in serialized if item is None]
    session_state = row["state"]
    if missing:
        # 素材更新后题目可能被移除；不能让用户卡在不可见的 pending 项上。
        stamp = now()
        conn.executemany(
            """UPDATE study_session_item SET state='skipped',answered_at=?
               WHERE session_id=? AND item_id=? AND state='pending'""",
            [(stamp, row["id"], candidate["item_id"]) for candidate in missing],
        )
        all_rows = conn.execute(
            "SELECT * FROM study_session_item WHERE session_id=? ORDER BY seq", (row["id"],)
        ).fetchall()
        pending = [candidate for candidate in all_rows if candidate["state"] == "pending"]
        serialized = [(candidate, serialize_item(row["list"], candidate)) for candidate in pending]
        if not pending and row["state"] == "active":
            session_state = "completed"
            conn.execute(
                "UPDATE study_session SET state='completed',updated_at=?,completed_at=? WHERE id=?",
                (stamp, stamp, row["id"]),
            )
    items = [item for _, item in serialized if item]
    completed = sum(candidate["state"] == "completed" for candidate in all_rows)
    skipped = sum(candidate["state"] == "skipped" for candidate in all_rows)
    return {
        "session": {"id": row["id"], "list": row["list"],
                    "practice_mode": row["practice_mode"], "scope": row["scope"],
                    "strategy": row["strategy"], "lesson": row["lesson"],
                    "assigned_day": row["assigned_day"], "state": session_state,
                    "resumed": resumed},
        "quota": quota,
        "progress": {"total": len(all_rows), "completed": completed,
                     "skipped": skipped, "pending": len(pending)},
        "items": items,
        "total": len(items),
    }


@bp.get("/api/lists")
def api_lists():
    user = get_user()
    today = date.today().isoformat()
    with db() as conn:
        rows = conn.execute(
            "SELECT list, status, COUNT(*) c FROM word_state WHERE user=? GROUP BY list,status", (user,)
        ).fetchall()
        mem_rows = conn.execute(
            "SELECT list, COUNT(*) c FROM word_state WHERE user=? AND memorized=1 GROUP BY list", (user,)
        ).fetchall()
        today_row = conn.execute(
            "SELECT * FROM daily_log WHERE day=? AND user=?", (today, user)
        ).fetchone()
        sessions = conn.execute(
            "SELECT s.*, COUNT(i.item_id) total, "
            "SUM(CASE WHEN i.state='pending' THEN 1 ELSE 0 END) pending "
            "FROM study_session s JOIN study_session_item i ON i.session_id=s.id "
            "WHERE s.user=? AND s.state='active' GROUP BY s.id ORDER BY s.updated_at DESC", (user,)
        ).fetchall()
    stat_map = {(r["list"], r["status"]): r["c"] for r in rows}
    mem_map = {r["list"]: r["c"] for r in mem_rows}
    result = []
    for key, meta in MATERIALS.items():
        m = _material_meta(key)
        result.append({
            "key": key, "title": meta["title"], "type": meta["type"],
            "total": m["total"],
            "audio_done": _audio_done(key),
            "new": max(0, m["total"] - sum(r["c"] for r in rows if r["list"] == key)),
            "learning": stat_map.get((key, "learning"), 0),
            "known": stat_map.get((key, "known"), 0),
            "memorized": mem_map.get(key, 0),
            "lesson_count": m["lesson_count"],
        })
    today_log = {k: 0 for k in ("new", "review", "right", "wrong", "memorize_right", "memorize_wrong")}
    if today_row:
        today_log.update({"new": today_row["new_count"], "review": today_row["review_count"],
                          "right": today_row["right_count"], "wrong": today_row["wrong_count"],
                          "memorize_right": today_row["memorize_right"],
                          "memorize_wrong": today_row["memorize_wrong"]})
    active = [{"id": s["id"], "list": s["list"], "mode": s["practice_mode"],
               "scope": s["scope"], "strategy": s["strategy"], "lesson": s["lesson"],
               "total": s["total"], "pending": s["pending"]} for s in sessions]
    return resp({"lists": result, "today": today_log, "active_sessions": active})


@bp.get("/api/lessons")
def api_lessons():
    user = get_user()
    list_key = request.args.get("list", "")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 400
    if _material_meta(list_key)["lesson_count"] == 0:
        return jsonify({"error": "该素材不支持按课学习"}), 400
    groups = {}
    for item in load_material(list_key):
        groups.setdefault(item.get("lesson"), []).append(item)
    with db() as conn:
        states = conn.execute(
            "SELECT item_id,status FROM word_state WHERE user=? AND list=?", (user, list_key)
        ).fetchall()
    state_map = {r["item_id"]: r["status"] for r in states}
    lessons = []
    for number, items in sorted(groups.items()):
        counts = {"learning": 0, "known": 0}
        for item in items:
            status = state_map.get(item["id"])
            if status in counts:
                counts[status] += 1
        lessons.append({"lesson": number, "total": len(items),
                        "known": counts["known"], "learning": counts["learning"],
                        "unseen": len(items) - counts["known"] - counts["learning"]})
    return resp({"list": list_key, "title": MATERIALS[list_key]["title"], "lessons": lessons})


@bp.get("/api/session")
def api_session():
    user = get_user()
    list_key, mode, scope, lesson, strategy = session_context()
    new_quota = int_arg("new", CONFIG["new_per_day"], 0, 50)
    today = date.today().isoformat()
    stamp = now()
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if mode not in PRACTICE_MODES:
        return jsonify({"error": "未知练习模式"}), 400
    if scope not in {"all", "memorized"}:
        return jsonify({"error": "未知练习范围"}), 400
    if request.args.get("lesson") is not None and lesson is None:
        return jsonify({"error": "lesson 必须为正整数"}), 400
    # 素材在进程内不可变（lru_cache）：lesson 列表只具体化一次，校验与建会话复用，
    # 避免把重复的全量扫描压进写事务。
    lesson_material = list(iter_material(list_key, lesson)) if strategy == "lesson" else None
    if strategy == "lesson" and not lesson_material:
        return jsonify({"error": "课程不存在"}), 404

    with db() as conn:
        # 先用只读事务检查是否已有活跃会话（避免在读路径上不必要的 IMMEDIATE 锁）
        existing = active_session(conn, user, list_key, mode, scope, strategy, lesson)
        if existing:
            plan = conn.execute(
                "SELECT * FROM daily_plan WHERE day=? AND user=? AND list=?", (today, user, list_key)
            ).fetchone()
            quota = {"new_quota": plan["new_quota"],
                     "allocated_today": plan["allocated_new"],
                     "remaining_today": max(0, plan["new_quota"] - plan["allocated_new"])} if plan else None
            return resp(serialize_session(conn, existing, resumed=True, quota=quota))

        # 确认需要写入，升级为 IMMEDIATE 并二次检查（double-check locking）
        conn.execute("BEGIN IMMEDIATE")
        existing = active_session(conn, user, list_key, mode, scope, strategy, lesson)
        if existing:
            plan = conn.execute(
                "SELECT * FROM daily_plan WHERE day=? AND user=? AND list=?", (today, user, list_key)
            ).fetchone()
            quota = {"new_quota": plan["new_quota"],
                     "allocated_today": plan["allocated_new"],
                     "remaining_today": max(0, plan["new_quota"] - plan["allocated_new"])} if plan else None
            return resp(serialize_session(conn, existing, resumed=True, quota=quota))

        session_id = uuid.uuid4().hex
        if strategy == "lesson":
            # 一次批量查询代替逐题 SELECT（NCE 每课几十句，逐题查会在写锁里放大事务）
            seen = {r["item_id"] for r in conn.execute(
                "SELECT item_id FROM word_state WHERE user=? AND list=? AND status!='new'",
                (user, list_key)).fetchall()}
            item_rows = [(item, "review" if item["id"] in seen else "new")
                         for item in lesson_material]
            quota = None
        else:
            plan = conn.execute(
                "SELECT * FROM daily_plan WHERE day=? AND user=? AND list=?", (today, user, list_key)
            ).fetchone()
            if not plan:
                conn.execute("INSERT INTO daily_plan VALUES(?,?,?,?,?,?,?)",
                             (today, user, list_key, new_quota, 0, stamp, stamp))
                plan = conn.execute(
                    "SELECT * FROM daily_plan WHERE day=? AND user=? AND list=?", (today, user, list_key)
                ).fetchone()
            remaining = max(0, plan["new_quota"] - plan["allocated_new"])
            q = ("SELECT item_id FROM word_state WHERE user=? AND list=? AND next_review<=? "
                 "AND status IN ('learning','known')")
            params = [user, list_key, today]
            if scope == "memorized":
                q += " AND memorized=1"
            review_ids = [r["item_id"] for r in conn.execute(
                q + " ORDER BY next_review LIMIT ?", (*params, CONFIG["max_review"])
            ).fetchall()]
            introduced = {r["item_id"] for r in conn.execute(
                "SELECT item_id FROM word_state WHERE user=? AND list=? AND status!='new'", (user, list_key)
            ).fetchall()}
            if scope == "memorized":
                candidates = {r["item_id"] for r in conn.execute(
                    "SELECT item_id FROM word_state WHERE user=? AND list=? AND memorized=1 AND status='new'",
                    (user, list_key)).fetchall()}
                pool = [i for i in load_material(list_key) if i["id"] in candidates]
            else:
                pool = [i for i in load_material(list_key) if i["id"] not in introduced]
            review_items = [find_item(list_key, item_id) for item_id in review_ids]
            review_items = [i for i in review_items if i]
            remaining = min(remaining, len(pool))
            fresh = random.sample(pool, remaining)  # 无放回均匀抽样，替代全量洗牌
            random.shuffle(review_items)
            item_rows = [(i, "review") for i in review_items] + [(i, "new") for i in fresh]
            conn.execute(
                "UPDATE daily_plan SET allocated_new=allocated_new+?,updated_at=? WHERE day=? AND user=? AND list=?",
                (len(fresh), stamp, today, user, list_key))
            quota = {"new_quota": plan["new_quota"],
                     "allocated_today": plan["allocated_new"] + len(fresh),
                     "remaining_today": max(0, remaining - len(fresh))}

        conn.execute(
            "INSERT INTO study_session VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, user, list_key, mode, scope, strategy, lesson, today,
             new_quota if strategy == "daily" else 0, "active", stamp, stamp, None))
        conn.executemany(
            "INSERT INTO study_session_item(session_id,seq,item_id,kind,phase) VALUES(?,?,?,?,?)",
            [(session_id, seq, item["id"], item["kind"], phase)
             for seq, (item, phase) in enumerate(item_rows)])
        if not item_rows:
            conn.execute("UPDATE study_session SET state='completed',completed_at=? WHERE id=?", (stamp, session_id))
        row = conn.execute("SELECT * FROM study_session WHERE id=?", (session_id,)).fetchone()
        return resp(serialize_session(conn, row, resumed=False, quota=quota))


def update_word_state(conn, user, list_key, item_id, first_right, final_right, mode, today):
    # 跟打不另计掌握度；选词/冲刺是"再认"而非拼写，不能拿点选结果驱动
    # 听写状态机与 FSRS（否则答错一次就把 memorized 清零、把词踢回复习队列）
    if mode in ("follow", "quiz", "sprint"):
        return
    row = conn.execute(
        "SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?", (user, list_key, item_id)
    ).fetchone()
    if row:
        state = dict(row)
        # 兼容历史 NULL 值：.get(key, 0) 在 key 存在但值为 NULL 时仍返回 None
        for k in ("memorized", "memorize_count", "wrong_count", "right_count", "consecutive_right"):
            if state.get(k) is None:
                state[k] = 0
        if state.get("last_memorize") is None:
            state["last_memorize"] = ""
    else:
        state = {"kind": "sentence" if MATERIALS[list_key]["type"] == "sentences" else "word",
                 "status": "new", "wrong_count": 0, "right_count": 0,
                 "consecutive_right": 0, "memorized": 0, "memorize_count": 0,
                 "last_memorize": ""}
    if final_right:
        state["right_count"] += 1
        state["consecutive_right"] += 1
        if not first_right:
            state["wrong_count"] += 1
        if state["consecutive_right"] >= CONFIG["known_threshold"]:
            state["status"] = "known"
        else:
            state["status"] = "learning"
    else:
        state["wrong_count"] += 1
        state["consecutive_right"] = 0
        state["status"] = "learning"
        if state["kind"] == "word":
            state["memorized"] = 0
            state["memorize_count"] = 0

    # ---- FSRS 间隔：由首答/重试/答错推导评级，结合记忆状态算下次间隔 ----
    grade = 3 if (final_right and first_right) else (2 if final_right else 1)
    prev_mem = None
    if row and row["stability"] is not None:
        prev_mem = {"stability": row["stability"], "difficulty": row["difficulty"]}
    elapsed = days_between(row["last_seen"], today) if row else 0
    mem_state, days = fsrs_review(prev_mem, grade, elapsed)
    state["stability"] = mem_state["stability"]
    state["difficulty"] = mem_state["difficulty"]

    state["last_seen"] = today
    state["next_review"] = (date.fromisoformat(today) + timedelta(days=days)).isoformat()
    conn.execute(
        """INSERT INTO word_state(user,list,item_id,kind,status,wrong_count,right_count,
               consecutive_right,last_seen,next_review,memorized,memorize_count,last_memorize,
               stability,difficulty)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(user,list,item_id) DO UPDATE SET status=excluded.status,
               wrong_count=excluded.wrong_count,right_count=excluded.right_count,
               consecutive_right=excluded.consecutive_right,last_seen=excluded.last_seen,
               next_review=excluded.next_review,memorized=excluded.memorized,
               memorize_count=excluded.memorize_count,last_memorize=excluded.last_memorize,
               stability=excluded.stability,difficulty=excluded.difficulty""",
        (user, list_key, item_id, state["kind"], state["status"], state["wrong_count"],
         state["right_count"], state["consecutive_right"], state["last_seen"],
         state["next_review"], state.get("memorized", 0), state.get("memorize_count", 0),
         state.get("last_memorize", ""), state["stability"], state["difficulty"]))


def _opt_bool(v):
    """显式 null 表示"没有作答"，不能与 False（答错）混为一谈。"""
    return None if v is None else bool(v)


@bp.post("/api/result")
def api_result():
    user = get_user()
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    raw_id = data.get("id")
    if raw_id is None:
        return jsonify({"error": "缺少 id 参数"}), 400
    item_id = str(raw_id)
    outcome = data.get("outcome", "completed" if data.get("right") else "skipped")
    if outcome not in {"attempt", "completed", "skipped"}:
        return jsonify({"error": "outcome 无效"}), 400
    if "first_right" in data:
        first_right = _opt_bool(data["first_right"])
    else:
        r = data.get("right")
        first_right = None if r is None else bool(r and not data.get("retried"))
    if "final_right" in data:
        final_right = _opt_bool(data["final_right"])
    else:
        r = data.get("right")
        final_right = None if r is None else bool(r)
    try:
        attempt_count = int(data.get("attempt_count", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "attempt_count 无效"}), 400
    if attempt_count < 1:
        return jsonify({"error": "attempt_count 无效"}), 400
    # 可选：本题作答耗时（毫秒），用于打字速度曲线；仅接受合理区间
    duration_ms = None
    raw_ms = data.get("ms")
    if isinstance(raw_ms, (int, float)) and not isinstance(raw_ms, bool):
        duration_ms = max(200, min(600000, int(raw_ms)))
    # 可选：用户实际敲入的内容（词模式），用于易混词挖掘；截断到 64 字符
    typed = None
    raw_typed = data.get("typed")
    if isinstance(raw_typed, str):
        typed = raw_typed.strip()[:64] or None
    today = date.today().isoformat()
    stamp = now()
    if not session_id:
        return legacy_result(user, data, item_id, first_right, final_right, outcome, today)
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        session = conn.execute(
            "SELECT * FROM study_session WHERE id=? AND user=?", (session_id, user)
        ).fetchone()
        item = conn.execute(
            "SELECT * FROM study_session_item WHERE session_id=? AND item_id=?", (session_id, item_id)
        ).fetchone()
        if not session or not item:
            return jsonify({"error": "会话或题目不存在"}), 404
        if item["state"] != "pending":
            return resp({"ok": True, "duplicate": True})
        if outcome == "attempt":
            if item["first_right"] is None:
                conn.execute(
                    "UPDATE study_session_item SET first_right=?,attempt_count=?,first_answer_at=?,"
                    "last_typed=COALESCE(?,last_typed),first_typed=COALESCE(?,first_typed) "
                    "WHERE session_id=? AND item_id=?",
                    (1 if first_right else 0, attempt_count, stamp, typed, typed,
                     session_id, item_id))
                update_mode_log(conn, today, user, session["practice_mode"], item["phase"],
                                first_right, None, False)
            return resp({"ok": True, "pending": True})
        effective_first = bool(item["first_right"]) if item["first_right"] is not None else first_right
        skipped = outcome == "skipped"
        state = "skipped" if skipped else "completed"
        conn.execute(
            "UPDATE study_session_item SET state=?,first_right=COALESCE(first_right,?),final_right=?,"
            "attempt_count=?,first_answer_at=COALESCE(first_answer_at,?),answered_at=?,duration_ms=?,"
            "last_typed=COALESCE(?,last_typed),first_typed=COALESCE(?,first_typed) "
            "WHERE session_id=? AND item_id=? AND state='pending'",
            (state, None if skipped else (1 if effective_first else 0),
             None if skipped else (1 if final_right else 0), attempt_count,
             None if skipped else stamp, stamp,
             None if skipped else duration_ms, typed, typed, session_id, item_id))
        if skipped:
            update_mode_log(conn, today, user, session["practice_mode"],
                            item["phase"] if item["first_right"] is None else None,
                            None, None, True)
        elif item["first_right"] is None:
            update_mode_log(conn, today, user, session["practice_mode"], item["phase"],
                            effective_first, final_right, False)
        else:
            update_mode_log(conn, today, user, session["practice_mode"], None,
                            None, final_right, False)
        if not skipped and final_right is not None:
            update_word_state(conn, user, session["list"], item_id, effective_first,
                              final_right, session["practice_mode"], today)
        if session["practice_mode"] != "follow":
            # new/review 统计记录当日已分配并处理过的题目，跳过也计入；
            # right/wrong 与掌握度统计则只记录实际作答。
            conn.execute(
                """INSERT INTO daily_log(day,user,new_count,review_count,right_count,wrong_count)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(day,user) DO UPDATE SET
                   new_count=new_count+excluded.new_count,review_count=review_count+excluded.review_count,
                   right_count=right_count+excluded.right_count,wrong_count=wrong_count+excluded.wrong_count""",
                (today, user, 1 if item["phase"] == "new" else 0,
                 1 if item["phase"] == "review" else 0,
                 0 if skipped else (1 if effective_first else 0),
                 0 if skipped or effective_first else 1))
        pending = conn.execute(
            "SELECT COUNT(*) c FROM study_session_item WHERE session_id=? AND state='pending'", (session_id,)
        ).fetchone()["c"]
        if pending == 0:
            conn.execute(
                "UPDATE study_session SET state='completed',updated_at=?,completed_at=? WHERE id=?",
                (stamp, stamp, session_id))
        else:
            conn.execute("UPDATE study_session SET updated_at=? WHERE id=?", (stamp, session_id))
        return resp({"ok": True, "duplicate": False, "pending": pending})


def update_mode_log(conn, day, user, mode, phase, first_right, final_right, skipped):
    # 语义：daily_practice_log 记"末答对错"(final_right)，与 daily_log 的"首答对错"是刻意分离的双指标。
    values = {
        "new": 1 if phase == "new" else 0,
        "review": 1 if phase == "review" else 0,
        "first_right": 1 if first_right is True else 0,
        "first_wrong": 1 if first_right is False else 0,
        "final_right": 1 if final_right is True else 0,
        "skipped": 1 if skipped else 0,
    }
    conn.execute(
        """INSERT INTO daily_practice_log(day,user,practice_mode,new_count,review_count,
               first_right_count,first_wrong_count,final_right_count,skipped_count)
           VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(day,user,practice_mode) DO UPDATE SET
           new_count=new_count+excluded.new_count,review_count=review_count+excluded.review_count,
           first_right_count=first_right_count+excluded.first_right_count,
           first_wrong_count=first_wrong_count+excluded.first_wrong_count,
           final_right_count=final_right_count+excluded.final_right_count,
           skipped_count=skipped_count+excluded.skipped_count""",
        (day, user, mode, values["new"], values["review"], values["first_right"],
         values["first_wrong"], values["final_right"], values["skipped"]))
    notify_level(conn, user)   # 每题经验入账后探测升级，好友动态由此保持及时


def legacy_result(user, data, item_id, first_right, final_right, outcome, today):
    """兼容错词本自定义重练等旧调用；新练习页一律传 session_id。"""
    list_key = data.get("list")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    skipped = outcome == "skipped"
    with db() as conn:
        # 只为素材里真实存在的条目记听写状态：自定义文章的 s0/s1 等伪 id
        # 在这里被挡下，不再生成幽灵 word_state 行污染错词数/到期复习统计
        if not skipped and final_right is not None and find_item(list_key, item_id) is not None:
            update_word_state(conn, user, list_key, item_id, first_right, final_right,
                              data.get("mode", "assisted"), today)
        update_mode_log(conn, today, user, data.get("mode", "assisted"), "review",
                        None if skipped else first_right, None if skipped else final_right, skipped)
    return resp({"ok": True, "legacy": True})
