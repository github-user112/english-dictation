"""错词本 / 统计 / TTS 懒生成 / 音频服务"""
import hashlib
from datetime import date, timedelta

import edge_tts
from flask import Blueprint, abort, jsonify, request, send_from_directory

from .auth import get_user, resp
from .config import AUDIO
from .db import db
from .materials import audio_url, find_item

bp = Blueprint("misc", __name__)


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
    return jsonify({"items": items})


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
    return resp({"days": days, "total_right": total_r, "total_wrong": total_w,
                 "total_memorize_right": total_mr, "total_memorize_wrong": total_mw,
                 "streak": streak, "wrong_words": wrong})


@bp.post("/api/tts")
def api_tts():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    voice = data.get("voice") or "en-US-JennyNeural"
    if not text or len(text) > 200:
        return jsonify({"error": "text 无效"}), 400
    fname = hashlib.md5(f"{voice}:{text}".encode()).hexdigest()[:16] + ".mp3"
    out = AUDIO / "lazy" / fname
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        import asyncio
        asyncio.run(edge_tts.Communicate(text, voice).save(str(out)))
    return jsonify({"url": f"/audio/lazy/{fname}"})


@bp.get("/audio/<path:subpath>")
def serve_audio(subpath):
    p = (AUDIO / subpath).resolve()
    if not p.is_relative_to(AUDIO.resolve()):
        abort(403)
    if not p.exists():
        abort(404)
    return send_from_directory(AUDIO, subpath, mimetype="audio/mpeg")
