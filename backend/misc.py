"""错词本 / 统计 / TTS 懒生成 / 音频服务"""
import asyncio
import hashlib
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import date, timedelta

import edge_tts
from flask import Blueprint, abort, jsonify, request, send_from_directory

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


def _allow_tts_request(user):
    limit = CONFIG["tts_rate_limit_per_hour"]
    if limit <= 0:
        return True
    now = time.monotonic()
    cutoff = now - 3600
    with _tts_rate_lock:
        recent = _tts_requests[user]
        while recent and recent[0] <= cutoff:
            recent.popleft()
        if len(recent) >= limit:
            return False
        recent.append(now)
    return True


def _tts_file_lock(filename):
    with _tts_file_locks_lock:
        return _tts_file_locks.setdefault(filename, threading.Lock())


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
            f"SELECT list, item_id, wrong_count, right_count, last_seen FROM word_state {cond} "
            "ORDER BY last_seen DESC LIMIT 500", args).fetchall()
    items = []
    for r in rows:
        m = find_item(r["list"], r["item_id"])
        if m:
            items.append({**m, "list": r["list"], "wrong_count": r["wrong_count"],
                          "right_count": r["right_count"], "last_seen": r["last_seen"],
                          "audio": audio_url(r["list"], r["item_id"], m["text"])})
    return resp({"items": items})


@bp.post("/api/wrong/remove")
def api_wrong_remove():
    u = get_user()
    data = request.get_json(force=True)
    with db() as conn:
        conn.execute("UPDATE word_state SET wrong_count=0, status='new', next_review=NULL "
                     "WHERE user=? AND list=? AND item_id=?", (u, data.get("list"), data.get("id")))
    return resp({"ok": True})


@bp.get("/api/stats")
def api_stats():
    u = get_user()
    with db() as conn:
        rows = conn.execute("SELECT * FROM daily_log WHERE user=? ORDER BY day", (u,)).fetchall()
        mode_rows = conn.execute(
            "SELECT practice_mode,SUM(first_right_count) first_right,"
            "SUM(first_wrong_count) first_wrong,SUM(final_right_count) final_right,"
            "SUM(skipped_count) skipped FROM daily_practice_log WHERE user=? GROUP BY practice_mode",
            (u,)).fetchall()
    days = [{"day": r["day"], "new": r["new_count"], "review": r["review_count"],
             "right": r["right_count"], "wrong": r["wrong_count"],
             "memorize_right": r["memorize_right"], "memorize_wrong": r["memorize_wrong"]}
            for r in rows]
    total_r = sum(d["right"] for d in days)
    total_w = sum(d["wrong"] for d in days)
    total_mr = sum(d["memorize_right"] for d in days)
    total_mw = sum(d["memorize_wrong"] for d in days)
    # 连续打卡（今天还没练则从昨天算）
    streak = 0
    d = date.today()
    known = {r["day"] for r in rows}
    if d.isoformat() not in known:
        d -= timedelta(days=1)
    while d.isoformat() in known:
        streak += 1
        d -= timedelta(days=1)
    wrong = 0
    with db() as conn:
        wrong = conn.execute("SELECT COUNT(*) c FROM word_state WHERE user=? AND wrong_count>0", (u,)).fetchone()["c"]
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
                 "streak": streak, "wrong_words": wrong,
                 "practice_modes": practice_modes})


@bp.post("/api/tts")
def api_tts():
    """受限的按需 TTS：同音频串行生成、缓存有上限、请求可限流。"""
    user = get_user()
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    voice = data.get("voice") or CONFIG["tts_default_voice"]
    if not text or len(text) > 200:
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
