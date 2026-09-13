"""错词本 / 统计 / TTS 懒生成 / 音频服务"""
import asyncio
import hashlib
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone

import edge_tts
from flask import Blueprint, abort, has_request_context, jsonify, request, send_from_directory

from .auth import get_user, resp
from .config import AUDIO, CONFIG
from .db import db
from .materials import audio_filename, audio_url, find_item

bp = Blueprint("misc", __name__)

_tts_rate_lock = threading.Lock()
_tts_requests = defaultdict(deque)
_tts_file_locks = {}
_tts_file_locks_lock = threading.Lock()
_tts_slots = threading.BoundedSemaphore(CONFIG["tts_max_concurrency"])


def _lazy_audio_filename(text, voice):
    """默认音色保持旧文件名；其他音色进入独立缓存键。"""
    if voice == CONFIG["tts_default_voice"]:
        return audio_filename(text)
    return hashlib.md5(f"{voice}\0{text}".encode()).hexdigest() + ".mp3"


_TTS_LOCKS_MAX = 4096      # 文件锁表上限：超出时回收空闲锁，防止随文件名无限增长
_TTS_USERS_MAX = 1024      # 限流表上限：超出时清掉已整批过期的用户（游客 UUID 会不断新增）


def _allow_tts_request(user):
    limit = CONFIG["tts_rate_limit_per_hour"]
    if limit <= 0:
        return True
    now = time.monotonic()
    cutoff = now - 3600
    with _tts_rate_lock:
        if len(_tts_requests) >= _TTS_USERS_MAX:
            expired_users = [key for key, recent in _tts_requests.items()
                             if not recent or recent[-1] <= cutoff]
            for key in expired_users:
                del _tts_requests[key]
        recent = _tts_requests[user]
        while recent and recent[0] <= cutoff:
            recent.popleft()
        if len(recent) >= limit:
            return False
        recent.append(now)
    return True


def _tts_file_lock(filename):
    with _tts_file_locks_lock:
        lock = _tts_file_locks.get(filename)
        if lock is None:
            if len(_tts_file_locks) >= _TTS_LOCKS_MAX:
                # 只回收当前无人持有的锁；极端并发下同文件可能重复生成，
                # 但写入是原子替换且内容确定，无一致性风险。
                for key, value in list(_tts_file_locks.items()):
                    if not value.locked():
                        _tts_file_locks.pop(key, None)
            lock = _tts_file_locks.setdefault(filename, threading.Lock())
        return lock


def _prune_lazy_audio(directory, reserve=1):
    """写入新文件前腾出空间；缓存文件本身可再生成。"""
    limit = CONFIG["tts_lazy_max_files"]
    if limit <= 0:
        return False
    files = list(directory.glob("*.mp3"))
    overflow = len(files) + reserve - limit
    if overflow <= 0:
        return True
    for path in sorted(files, key=lambda item: item.stat().st_mtime)[:overflow]:
        try:
            path.unlink()
        except OSError:
            continue
    return len(list(directory.glob("*.mp3"))) + reserve <= limit


@bp.get("/api/wrong")
def api_wrong():
    u = get_user()
    list_key = request.args.get("list", "")
    cond = "WHERE user=? AND wrong_count > 0" + (" AND list=?" if list_key else "")
    args = (u, list_key) if list_key else (u,)
    with db() as conn:
        rows = conn.execute(
            f"SELECT list, item_id, wrong_count, right_count, last_seen, next_review FROM word_state {cond} "
            "ORDER BY last_seen DESC LIMIT 500", args).fetchall()
    items = []
    for r in rows:
        m = find_item(r["list"], r["item_id"])
        if m:
            items.append({**m, "list": r["list"], "wrong_count": r["wrong_count"],
                          "right_count": r["right_count"], "last_seen": r["last_seen"],
                          "next_review": r["next_review"],
                          "audio": audio_url(r["list"], r["item_id"], m["text"])})
    return resp({"items": items})


@bp.get("/api/wrong/today")
def api_wrong_today():
    """今日错词回收题组：今天答错过、且仍在错词本的单词优先，不够 10 个按到期从错词本补满。
    与 today.py 的错词回收步同口径（target = min(10, 错词池)）。"""
    u = get_user()
    today = local_today().isoformat()
    with db() as conn:
        picked = [(r["list"], r["item_id"]) for r in conn.execute(
            """SELECT DISTINCT s.list, i.item_id FROM study_session s
               JOIN study_session_item i ON i.session_id=s.id
               JOIN word_state w ON w.user=s.user AND w.list=s.list AND w.item_id=i.item_id
               WHERE s.user=? AND s.assigned_day=? AND i.first_right=0
               AND w.wrong_count>0 AND w.kind='word' LIMIT 10""", (u, today)).fetchall()]
        if len(picked) < 10:
            have = set(picked)
            for r in conn.execute(
                    "SELECT list, item_id FROM word_state "
                    "WHERE user=? AND wrong_count>0 AND kind='word' "
                    "ORDER BY next_review IS NULL, next_review, wrong_count DESC LIMIT 20",
                    (u,)).fetchall():
                key = (r["list"], r["item_id"])
                if key not in have:
                    picked.append(key)
                    if len(picked) >= 10:
                        break
    items = []
    for list_key, item_id in picked:
        m = find_item(list_key, item_id)
        if m:
            items.append({**m, "list": list_key, "phase": "review",
                          "audio": audio_url(list_key, item_id, m["text"])})
    return resp({"items": items})


@bp.post("/api/wrong/remove")
def api_wrong_remove():
    u = get_user()
    data = request.get_json(force=True)
    with db() as conn:
        conn.execute("UPDATE word_state SET wrong_count=0, status='new', next_review=NULL "
                     "WHERE user=? AND list=? AND item_id=?", (u, data.get("list"), data.get("id")))
    return resp({"ok": True})


def _tz_offset_minutes():
    """请求头 X-Tz-Offset 里的时区偏移（JS getTimezoneOffset 分钟，西正东负）；
    无请求上下文（定时任务）或头缺失/非法时返回 None。"""
    if not has_request_context():
        return None
    try:
        return max(-840, min(840, int(request.headers.get("X-Tz-Offset", ""))))   # UTC-12..+14
    except (TypeError, ValueError):
        return None


def local_today():
    """用户本地的「今天」：用 UTC 时刻减偏移得到用户本地日期；头缺失/非法时退回
    date.today()（服务器本地）——与改动前的行为完全一致，老测试/非 UTC 部署不受影响。
    返回 date 对象，调用处的减法/isoformat/weekday 用法与 date.today() 完全一致。"""
    off = _tz_offset_minutes()
    if off is None:
        return date.today()
    return (datetime.now(timezone.utc) - timedelta(minutes=off)).date()


def day_streak(days):
    """连续打卡天数：days 为 ISO 日期字符串可迭代；今天还没练则从昨天起算。"""
    known = set(days)
    d = local_today()
    if d.isoformat() not in known:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in known:
        n += 1
        d -= timedelta(days=1)
    return n


# 连续打卡只回看这么多天：超过一年的断档必然清零，无需更久的历史
STREAK_LOOKBACK_DAYS = 400


def streak_days(user, conn):
    """活跃日集合：听打/分模式练习/每日挑战三类记录的并集（全站 streak 统一口径）。"""
    floor = (local_today() - timedelta(days=STREAK_LOOKBACK_DAYS)).isoformat()
    days = {r["day"] for r in conn.execute(
        "SELECT day FROM daily_log WHERE user=? AND day>=?", (user, floor))}
    days |= {r["day"] for r in conn.execute(
        "SELECT DISTINCT day FROM daily_practice_log WHERE user=? AND day>=?", (user, floor))}
    days |= {r["day"] for r in conn.execute(
        "SELECT day FROM daily_challenge WHERE user=? AND day>=?", (user, floor))}
    return days


def user_streak(user, conn):
    return day_streak(streak_days(user, conn))


@bp.get("/api/stats")
def api_stats():
    u = get_user()
    # 报告口径是"这一年"（ReportPage 文案），速度/时段统计同样只扫近一年，
    # 避免 study_session_item 全历史随练习量线性拖慢每次请求。
    # answered_at 是 UTC 时间戳，窗口下界也用 UTC 日界，不与 local_today 混用
    since = (datetime.now(timezone.utc) - timedelta(days=370)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute("SELECT * FROM daily_log WHERE user=? ORDER BY day", (u,)).fetchall()
        mode_rows = conn.execute(
            "SELECT practice_mode,SUM(first_right_count) first_right,"
            "SUM(first_wrong_count) first_wrong,SUM(final_right_count) final_right,"
            "SUM(skipped_count) skipped FROM daily_practice_log WHERE user=? GROUP BY practice_mode",
            (u,)).fetchall()
        wrong = conn.execute("SELECT COUNT(*) c FROM word_state WHERE user=? AND wrong_count>0", (u,)).fetchone()["c"]
        # 打字速度曲线：按天聚合正确完成题的平均耗时（秒）
        # answered_at 存的是 UTC；速度曲线/黄金时段按用户本地日界聚合，
        # 否则 UTC+8 用户的晚间练习会落到图表的"第二天"（与热力图 daily_log 的本地日界不一致）
        off = _tz_offset_minutes()
        shift = f"{-off} minutes" if off is not None else None
        day_col = "substr(datetime(si.answered_at, ?),1,10)" if shift else "substr(si.answered_at,1,10)"
        hour_col = "CAST(strftime('%H', datetime(si.answered_at, ?)) AS INT)" if shift \
            else "CAST(substr(si.answered_at,12,2) AS INT)"
        sp = (shift,) if shift else ()
        speed = [{"day": r["d"], "sec": round(r["sec"], 2), "n": r["n"]} for r in conn.execute(
            f"SELECT {day_col} d, AVG(si.duration_ms)/1000.0 sec, COUNT(*) n "
            "FROM study_session_item si JOIN study_session s ON s.id=si.session_id "
            "WHERE s.user=? AND si.state='completed' AND si.final_right=1 "
            "AND si.duration_ms IS NOT NULL AND si.answered_at>=? GROUP BY d ORDER BY d",
            (*sp, u, since)).fetchall()]
        # 按小时作答分布（用于学习报告的“黄金时段”）：只算实际完成的题，与速度曲线同口径
        hours = [0] * 24
        for r in conn.execute(
            f"SELECT {hour_col} h, COUNT(*) c "
            "FROM study_session_item si JOIN study_session s ON s.id=si.session_id "
            "WHERE s.user=? AND si.answered_at>=? AND si.state='completed' GROUP BY h",
            (*sp, u, since)).fetchall():
            if 0 <= r["h"] <= 23:
                hours[r["h"]] = r["c"]
        due_soon = _due_soon_count(u, conn)
        streak = user_streak(u, conn)   # 与 profile/today 同口径：三类练习记录并集
    days = [{"day": r["day"], "new": r["new_count"], "review": r["review_count"],
             "right": r["right_count"], "wrong": r["wrong_count"],
             "memorize_right": r["memorize_right"], "memorize_wrong": r["memorize_wrong"]}
            for r in rows]
    total_r = sum(d["right"] for d in days)
    total_w = sum(d["wrong"] for d in days)
    total_mr = sum(d["memorize_right"] for d in days)
    total_mw = sum(d["memorize_wrong"] for d in days)
    practice_modes = {}
    for row in mode_rows:
        total = row["first_right"] + row["first_wrong"]
        practice_modes[row["practice_mode"]] = {
            "first_right": row["first_right"], "first_wrong": row["first_wrong"],
            "first_accuracy": row["first_right"] / total if total else 0,
            "final_right": row["final_right"], "skipped": row["skipped"],
        }
    return resp({"days": days, "total_right": total_r, "total_wrong": total_w,
                 "total_memorize_right": total_mr, "total_memorize_wrong": total_mw,
                 "speed": speed, "hours": hours, "due_soon": due_soon,
                 "streak": streak, "wrong_words": wrong,
                 "practice_modes": practice_modes})


@bp.get("/api/report/weekly")
def api_report_weekly():
    """周报分享卡数据：本周（周一起）听打/背诵汇总 + 与上周的首答正确率差。"""
    u = get_user()
    monday = local_today() - timedelta(days=local_today().weekday())
    week_end = (monday + timedelta(days=7)).isoformat()
    this_week, last_week = monday.isoformat(), (monday - timedelta(days=7)).isoformat()

    def practice(conn, day_from, day_to):
        r = conn.execute(
            "SELECT SUM(new_count+review_count) items, SUM(first_right_count) fr, "
            "SUM(first_wrong_count) fw FROM daily_practice_log WHERE user=? AND day>=? AND day<?",
            (u, day_from, day_to)).fetchone()
        return {"items": r["items"] or 0, "fr": r["fr"] or 0, "fw": r["fw"] or 0}

    def accuracy(p):
        total = p["fr"] + p["fw"]
        return p["fr"] / total if total else 0.0

    with db() as conn:
        cur, prev = practice(conn, this_week, week_end), practice(conn, last_week, this_week)
        mem = conn.execute(
            "SELECT SUM(memorize_right) mr FROM daily_log WHERE user=? AND day>=? AND day<?",
            (u, this_week, week_end)).fetchone()
        days_active = conn.execute(
            "SELECT COUNT(DISTINCT day) c FROM daily_practice_log WHERE user=? AND day>=? AND day<?",
            (u, this_week, week_end)).fetchone()["c"]
        streak = user_streak(u, conn)   # 与 today/profile/leaderboard 同口径（三表并集）
    acc, prev_acc = accuracy(cur), accuracy(prev)
    # 上周没练过时不显示增量（+100% 之类的数字没有意义）
    delta = round((acc - prev_acc) * 100) if prev["fr"] + prev["fw"] > 0 else None
    return resp({
        "week_start": this_week, "week_end": (local_today()).isoformat(),
        "items": cur["items"], "accuracy": round(acc * 100), "accuracy_delta": delta,
        "memorize_right": mem["mr"] or 0, "days_active": days_active, "streak": streak,
    })


@bp.get("/api/stats/typing")
def api_stats_typing():
    """打字数据页：WPM 曲线（近 30 天）+ 错键对（近 90 天）+ 近 7 天速度段位。

    WPM 口径：完成题的正确文本字符数 / 5 词 ÷ 作答分钟（按天先加总再相除，
    长短句混练时比逐题平均 WPM 更稳）。字符数取 completed 行的 last_typed
    （改对重输后等于正确文本），不反查素材文件。
    """
    u = get_user()
    # answered_at 存 UTC：窗口下界用 UTC 日界（与 WHERE 比较类型一致），聚合再按本地日界
    off = _tz_offset_minutes()
    shift = f"{-off} minutes" if off is not None else None
    since30 = (datetime.now(timezone.utc) - timedelta(days=29)).strftime("%Y-%m-%d")
    since90 = (datetime.now(timezone.utc) - timedelta(days=89)).strftime("%Y-%m-%d")
    day_col = "substr(datetime(si.answered_at, ?),1,10)" if shift else "substr(si.answered_at,1,10)"
    with db() as conn:
        curve = [{"day": r["d"],
                  "wpm": round(r["chars"] / 5 / (r["ms"] / 60000), 1) if r["ms"] else 0,
                  "n": r["n"]}
                 for r in conn.execute(
            f"SELECT {day_col} d, SUM(LENGTH(si.last_typed)) chars, "
            "SUM(si.duration_ms) ms, COUNT(*) n "
            "FROM study_session_item si JOIN study_session s ON s.id=si.session_id "
            "WHERE s.user=? AND si.state='completed' AND si.final_right=1 "
            "AND si.duration_ms>0 AND si.last_typed IS NOT NULL AND si.answered_at>=? "
            "GROUP BY d ORDER BY d", (*((shift,) if shift else ()), u, since30)).fetchall()]
        typo_rows = conn.execute(
            "SELECT s.list, si.item_id, si.first_typed "
            "FROM study_session_item si JOIN study_session s ON s.id=si.session_id "
            "WHERE s.user=? AND si.state='completed' AND si.first_right=0 "
            "AND si.first_typed IS NOT NULL AND si.answered_at>=? "
            "ORDER BY si.answered_at DESC LIMIT 5000", (u, since90)).fetchall()

    # 错键对：difflib 对齐 expected/typed，统计 (应敲, 实敲) 计数
    from collections import Counter
    import difflib
    pairs = Counter()
    for r in typo_rows:
        item = find_item(r["list"], r["item_id"])
        if not item:
            continue
        expected = item["text"].lower()
        typed = (r["first_typed"] or "").lower()
        if not expected or not typed or expected == typed:
            continue
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, expected, typed).get_opcodes():
            if op == "replace":
                for k in range(max(i2 - i1, j2 - j1)):
                    e = expected[i1 + k] if i1 + k < i2 else "␣"
                    t = typed[j1 + k] if j1 + k < j2 else "⌫"
                    pairs[(e, t)] += 1
            elif op == "delete":
                for c in expected[i1:i2]:
                    pairs[(c, "⌫")] += 1
    # 每个应敲字母保留前 3 个错法，总体取错得最多的 12 个字母
    by_char = defaultdict(Counter)
    for (e, t), n in pairs.items():
        by_char[e][t] += n
    heat = [{"expect": e, "total": sum(c.values()),
             "got": [{"key": t, "count": n} for t, n in c.most_common(3)]}
            for e, c in sorted(by_char.items(), key=lambda kv: -sum(kv[1].values()))[:12]]

    today_iso = local_today().isoformat()
    recent7 = [p["wpm"] for p in curve
               if (local_today() - timedelta(days=6)).isoformat() <= p["day"] <= today_iso]
    wpm7 = round(sum(recent7) / len(recent7), 1) if recent7 else 0
    tier = next((label for limit, label in
                 [(45, "钻石"), (35, "铂金"), (25, "黄金"), (15, "白银"), (0, "青铜")] if wpm7 >= limit))
    return resp({"curve": curve, "heatmap": heat, "wpm7": wpm7, "tier": tier})


def _due_soon_count(user, conn, within_days=2):
    """未来 N 天内（含已逾期）到期的复习词数量，用于遗忘预警。复用调用方的连接。"""
    cutoff = (local_today() + timedelta(days=within_days)).isoformat()
    return conn.execute(
        "SELECT COUNT(*) c FROM word_state WHERE user=? AND status IN ('learning','known') "
        "AND next_review IS NOT NULL AND next_review<=?", (user, cutoff)).fetchone()["c"]


# ---------------- 易混词特训：从真实错拼记录里挖最小对立体 ----------------

def _levenshtein(a, b):
    """编辑距离。注意：与前端 lib/speech.js 的 levenshtein 归一化不同——
    前端先剥掉非 a-z 字符再比较，这里用原始小写串（含撇号/连字符）。
    阈值 ≤3 的口径两侧需保持一致，调整时两处同步。
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if not la or not lb:
        return la + lb
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[lb]


@bp.get("/api/confusions")
def api_confusions():
    """聚合最近的错拼：word → 常被错打成什么。只保留编辑距离 ≤3 的近似对。"""
    user = get_user()
    # 只看近 90 天：错拼本来就是"最近"的才有训练价值；也挡住随练习量增长的全史扫描
    since90 = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    with db() as conn:
        rows = conn.execute(
            "SELECT s.list list_key, si.item_id item_id, si.state state, "
            "si.first_typed first_typed, si.last_typed typed "
            "FROM study_session_item si JOIN study_session s ON s.id=si.session_id "
            "WHERE s.user=? AND si.answered_at>=? "
            "AND (si.last_typed IS NOT NULL OR si.first_typed IS NOT NULL) "
            "ORDER BY si.answered_at DESC LIMIT 2000", (user, since90)).fetchall()

    agg = {}   # (list,text) -> {"meta", "typos": {typed: count}}
    for r in rows:
        # completed 行的 last_typed 一定已被"改对重输"覆盖成正确拼写，
        # 只有不可覆盖的 first_typed（第一次敲入）才是真错拼；
        # 未完成行（跳过/中途放弃）的 last_typed 是最后实际输入，仍可参考
        typed = r["first_typed"] or (r["typed"] if r["state"] != "completed" else None)
        typed = (typed or "").strip()
        tl = typed.lower()
        if len(tl) < 3 or len(tl) > 40:
            continue
        m = find_item(r["list_key"], r["item_id"])
        if not m or m.get("kind") != "word":
            continue
        word = m["text"]
        wl = word.lower()
        if tl == wl:
            continue
        if abs(len(wl) - len(tl)) > 3:   # 长度差已超阈值，省掉整张编辑距离矩阵
            continue
        if _levenshtein(wl, tl) > 3:
            continue
        key = (r["list_key"], wl)
        slot = agg.setdefault(key, {"meta": m, "list": r["list_key"], "typos": {}})
        # 记录原始大小写形式中出现最多的拼法
        slot["typos"][typed] = slot["typos"].get(typed, 0) + 1

    # 先按总次数排序取前 40，再为入选词补 meta/audio（audio_url 涉及磁盘 stat）
    entries = []
    for list_key, slot in ((k[0], v) for k, v in agg.items()):
        typos = sorted(slot["typos"].items(), key=lambda kv: -kv[1])[:4]
        total = sum(c for _, c in typos)
        entries.append((total, slot["meta"]["text"], list_key, slot["meta"], typos))
    entries.sort(key=lambda e: (-e[0], e[1]))
    items = [{
        "id": m["id"], "word": m["text"], "list": list_key,
        "kind": "word",
        "phonetic": m.get("phonetic") or "", "meaning": (m.get("meaning") or "")[:40],
        "audio": audio_url(list_key, m["id"], m["text"]),
        "total": total,
        "typos": [{"typed": t, "count": c} for t, c in typos],
    } for total, _text, list_key, m, typos in entries[:40]]
    return resp({"items": items, "total": len(entries)})


@bp.post("/api/tts")
def api_tts():
    """受限的按需 TTS：同音频串行生成、缓存有上限、请求可限流。"""
    user = get_user()
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    voice = data.get("voice") or CONFIG["tts_default_voice"]
    # 上限须覆盖自定义文章的单句长度（custom.MAX_SENTENCE_LEN=280）
    if not text or len(text) > 320:
        return jsonify({"error": "text 无效"}), 400
    if voice not in CONFIG["tts_allowed_voices"]:
        return jsonify({"error": "voice 不受支持"}), 400

    filename = _lazy_audio_filename(text, voice)
    out_dir = AUDIO / "lazy"
    out = out_dir / filename
    out_dir.mkdir(parents=True, exist_ok=True)
    if out.exists():
        return jsonify({"url": f"/audio/lazy/{filename}", "cached": True})
    if not _allow_tts_request(user):
        return jsonify({"error": "TTS 请求过于频繁，请稍后再试"}), 429

    lock = _tts_file_lock(filename)
    with lock:
        if out.exists():
            return jsonify({"url": f"/audio/lazy/{filename}", "cached": True})
        if not _prune_lazy_audio(out_dir):
            return jsonify({"error": "TTS 缓存空间已满"}), 503
        if not _tts_slots.acquire(blocking=False):
            return jsonify({"error": "TTS 正在忙，请稍后重试"}), 429
        temp = out_dir / f".tmp_{uuid.uuid4().hex}_{filename}"
        try:
            asyncio.run(edge_tts.Communicate(text, voice).save(str(temp)))
            os.replace(temp, out)
            out.chmod(0o644)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        finally:
            _tts_slots.release()
    return jsonify({"url": f"/audio/lazy/{filename}", "cached": False})


@bp.get("/audio/<path:subpath>")
def serve_audio(subpath):
    p = (AUDIO / subpath).resolve()
    if not p.is_relative_to(AUDIO.resolve()):
        abort(403)
    if not p.exists():
        abort(404)
    return send_from_directory(AUDIO, subpath, mimetype="audio/mpeg")
