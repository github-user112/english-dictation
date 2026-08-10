"""英语听打系统 - Flask 后端"""
import hashlib
import json
import random
import sqlite3
import uuid as uuid_mod
from datetime import date, timedelta
from pathlib import Path

import edge_tts
from flask import Flask, jsonify, request, send_from_directory, abort, make_response

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "learn.db"
AUDIO = BASE / "audio"
app = Flask(__name__, static_folder="static")

COOKIE = "dict_u"

CONFIG = {
    "new_per_day": 10,
    "max_review": 30,
    "known_threshold": 3,
}

MATERIALS = {
    "cet4": {"type": "words", "title": "CET-4 词汇"},
    "cet6": {"type": "words", "title": "CET-6 词汇"},
    "kaoyan": {"type": "words", "title": "考研词汇"},
    "tuofu": {"type": "words", "title": "托福词汇"},
    "oral900": {"type": "sentences", "title": "口语900句"},
}


def db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    DB.parent.mkdir(exist_ok=True)
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS word_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL DEFAULT 'default',
            list TEXT NOT NULL,
            item_id TEXT NOT NULL,
            kind TEXT DEFAULT 'word',
            status TEXT DEFAULT 'new',
            wrong_count INTEGER DEFAULT 0,
            right_count INTEGER DEFAULT 0,
            consecutive_right INTEGER DEFAULT 0,
            last_seen TEXT,
            next_review TEXT,
            UNIQUE(user, list, item_id)
        );
        CREATE TABLE IF NOT EXISTS daily_log (
            day TEXT NOT NULL,
            user TEXT NOT NULL DEFAULT 'default',
            new_count INTEGER DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            right_count INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0,
            PRIMARY KEY(day, user)
        );
        """)


def migrate():
    """旧库（无 user 列）迁移"""
    with db() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(word_state)").fetchall()]
        if "user" not in cols:
            conn.executescript("""
            ALTER TABLE word_state RENAME TO word_state_old;
            CREATE TABLE word_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL DEFAULT 'default',
                list TEXT NOT NULL, item_id TEXT NOT NULL, kind TEXT DEFAULT 'word',
                status TEXT DEFAULT 'new', wrong_count INTEGER DEFAULT 0,
                right_count INTEGER DEFAULT 0, consecutive_right INTEGER DEFAULT 0,
                last_seen TEXT, next_review TEXT,
                UNIQUE(user, list, item_id)
            );
            INSERT INTO word_state (user, list, item_id, kind, status, wrong_count, right_count,
                                    consecutive_right, last_seen, next_review)
            SELECT 'default', list, item_id, kind, status, wrong_count, right_count,
                   consecutive_right, last_seen, next_review FROM word_state_old;
            DROP TABLE word_state_old;
            """)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(daily_log)").fetchall()]
        if "user" not in cols:
            conn.executescript("""
            ALTER TABLE daily_log RENAME TO daily_log_old;
            CREATE TABLE daily_log (
                day TEXT NOT NULL, user TEXT NOT NULL DEFAULT 'default',
                new_count INTEGER DEFAULT 0, review_count INTEGER DEFAULT 0,
                right_count INTEGER DEFAULT 0, wrong_count INTEGER DEFAULT 0,
                PRIMARY KEY(day, user)
            );
            INSERT INTO daily_log (day, user, new_count, review_count, right_count, wrong_count)
            SELECT day, 'default', new_count, review_count, right_count, wrong_count FROM daily_log_old;
            DROP TABLE daily_log_old;
            """)
        print("migrate ok")


def get_user():
    """取用户：URL ?u= 优先，cookie 兜底；无则生成"""
    u = request.args.get("u")
    if u and len(u) == 32 and u.isalnum():
        return u
    u = request.cookies.get(COOKIE)
    if u and len(u) == 32 and u.isalnum():
        return u
    return uuid_mod.uuid4().hex


def resp(obj):
    """将 user 写入响应（cookie 记住 + JSON 返回，前端拼到 URL 后面）"""
    u = get_user()
    r = make_response(jsonify({**obj, "user": u}))
    r.set_cookie(COOKIE, u, max_age=31536000, httponly=False, samesite="Lax")
    return r


def iter_material(list_key):
    meta = MATERIALS.get(list_key)
    if not meta:
        return None
    if meta["type"] == "words":
        p = BASE / "wordlists" / f"{list_key}.json"
        data = json.loads(p.read_text("utf-8"))
        for w in data["words"]:
            yield {
                "id": w["word"],
                "text": w["word"],
                "phonetic": w.get("phonetic") or "",
                "meaning": w.get("meaning") or "",
                "kind": "word",
            }
    else:
        p = BASE / "sentences" / f"{list_key}.json"
        data = json.loads(p.read_text("utf-8"))
        for s in data["items"]:
            yield {
                "id": str(s["id"]),
                "text": s["en"],
                "phonetic": "",
                "meaning": s.get("zh") or "",
                "kind": "sentence",
            }


def audio_url(list_key, item_id, text):
    if list_key == "oral900":
        fname = f"{item_id}.mp3"
    else:
        fname = hashlib.md5(text.encode()).hexdigest() + ".mp3"
    if (AUDIO / list_key / fname).exists():
        return f"/audio/{list_key}/{fname}"
    return f"/audio/lazy/{list_key}/{fname}"


@app.get("/api/lists")
def api_lists():
    u = get_user()
    today = date.today().isoformat()
    with db() as conn:
        rows = conn.execute("SELECT list, kind, status, COUNT(*) c FROM word_state WHERE user=? GROUP BY list, status", (u,)).fetchall()
        today_row = conn.execute("SELECT * FROM daily_log WHERE day=? AND user=?", (today, u)).fetchone()
    stat_map = {(r["list"], r["status"]): r["c"] for r in rows}
    result = []
    for key, meta in MATERIALS.items():
        total = sum(1 for _ in iter_material(key))
        audio_done = len(list((AUDIO / key).glob("*.mp3"))) if (AUDIO / key).exists() else 0
        result.append({
            "key": key,
            "title": meta["title"],
            "type": meta["type"],
            "total": total,
            "audio_done": audio_done,
            "new": stat_map.get((key, "new"), 0),
            "learning": stat_map.get((key, "learning"), 0),
            "known": stat_map.get((key, "known"), 0),
        })
    today_log = {
        "new": today_row["new_count"] if today_row else 0,
        "review": today_row["review_count"] if today_row else 0,
        "right": today_row["right_count"] if today_row else 0,
        "wrong": today_row["wrong_count"] if today_row else 0,
    }
    return resp({"lists": result, "today": today_log})


@app.get("/api/session")
def api_session():
    u = get_user()
    list_key = request.args.get("list", "cet4")
    new_n = int(request.args.get("new", CONFIG["new_per_day"]))
    today = date.today().isoformat()
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404

    with db() as conn:
        # 复习队列
        reviews = conn.execute(
            "SELECT item_id, kind FROM word_state WHERE user=? AND list=? AND (status='learning' "
            "OR (status='known' AND next_review<=?)) ORDER BY next_review LIMIT ?",
            (u, list_key, today, CONFIG["max_review"]),
        ).fetchall()

        # 新词
        if len(reviews) < new_n:
            known_ids = {r["item_id"] for r in conn.execute(
                "SELECT item_id FROM word_state WHERE user=? AND list=?", (u, list_key)).fetchall()}
            pool = [m for m in iter_material(list_key) if m["id"] not in known_ids]
            random.shuffle(pool)
            fresh = pool[: new_n - len(reviews)]
        else:
            fresh = []

    items = []
    for r in reviews:
        m = find_item(list_key, r["item_id"])
        if m:
            items.append({**m, "phase": "review"})
    for m in fresh:
        items.append({**m, "phase": "new"})
    random.shuffle(items)
    for it in items:
        it["audio"] = audio_url(list_key, it["id"], it["text"])
    return resp({"items": items, "total": len(items)})


def find_item(list_key, item_id):
    for m in iter_material(list_key):
        if m["id"] == item_id:
            return m
    return None


@app.post("/api/result")
def api_result():
    u = get_user()
    data = request.get_json(force=True)
    list_key = data.get("list")
    item_id = str(data.get("id"))
    right = bool(data.get("right"))
    today = date.today().isoformat()
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404

    with db() as conn:
        row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                           (u, list_key, item_id)).fetchone()
        if row:
            sr = dict(row)
        else:
            kind = "sentence" if MATERIALS[list_key]["type"] == "sentences" else "word"
            sr = {"status": "new", "wrong_count": 0, "right_count": 0,
                  "consecutive_right": 0, "last_seen": "", "next_review": "", "kind": kind}

        is_new = sr["status"] == "new"
        if right:
            sr["right_count"] += 1
            sr["consecutive_right"] += 1
            if sr["consecutive_right"] >= CONFIG["known_threshold"]:
                sr["status"] = "known"
                sr["next_review"] = (date.today() + timedelta(days=7)).isoformat()
            else:
                sr["status"] = "learning"
                sr["next_review"] = (date.today() + timedelta(days=1)).isoformat()
        else:
            sr["wrong_count"] += 1
            sr["consecutive_right"] = 0
            sr["status"] = "learning"
            sr["next_review"] = (date.today() + timedelta(days=1)).isoformat()
        sr["last_seen"] = today

        conn.execute("""
            INSERT INTO word_state(user, list, item_id, kind, status, wrong_count, right_count,
                                   consecutive_right, last_seen, next_review)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user, list, item_id) DO UPDATE SET
                status=excluded.status, wrong_count=excluded.wrong_count,
                right_count=excluded.right_count, consecutive_right=excluded.consecutive_right,
                last_seen=excluded.last_seen, next_review=excluded.next_review
        """, (u, list_key, item_id, sr["kind"], sr["status"], sr["wrong_count"], sr["right_count"],
              sr["consecutive_right"], sr["last_seen"], sr["next_review"]))

        conn.execute("""
            INSERT INTO daily_log(day, user, new_count, review_count, right_count, wrong_count)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(day, user) DO UPDATE SET
                new_count=new_count+excluded.new_count,
                review_count=review_count+excluded.review_count,
                right_count=right_count+excluded.right_count,
                wrong_count=wrong_count+excluded.wrong_count
        """, (today, u, 1 if is_new else 0, 0 if is_new else 1, 1 if right else 0, 0 if right else 1))
    return resp({"ok": True})


@app.get("/api/wrong")
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


@app.post("/api/wrong/remove")
def api_wrong_remove():
    u = get_user()
    data = request.get_json(force=True)
    with db() as conn:
        conn.execute("UPDATE word_state SET wrong_count=0, status='new', next_review=NULL "
                     "WHERE user=? AND list=? AND item_id=?", (u, data.get("list"), data.get("id")))
    return resp({"ok": True})


@app.get("/api/stats")
def api_stats():
    u = get_user()
    with db() as conn:
        rows = conn.execute("SELECT * FROM daily_log WHERE user=? ORDER BY day", (u,)).fetchall()
    days = [{"day": r["day"], "new": r["new_count"], "review": r["review_count"],
             "right": r["right_count"], "wrong": r["wrong_count"]} for r in rows]
    total_r = sum(d["right"] for d in days)
    total_w = sum(d["wrong"] for d in days)
    # 连续打卡
    streak = 0
    d = date.today()
    known = {r["day"] for r in rows}
    while d.isoformat() in known:
        streak += 1
        d -= timedelta(days=1)
    if d.isoformat() not in known:
        today_str = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if not today_str in known and yesterday in known:
            pass  # 今天还没练，昨天连续则不算断
    wrong = 0
    with db() as conn:
        wrong = conn.execute("SELECT COUNT(*) c FROM word_state WHERE user=? AND wrong_count>0", (u,)).fetchone()["c"]
    return resp({"days": days, "total_right": total_r, "total_wrong": total_w,
                 "streak": streak, "wrong_words": wrong})


@app.post("/api/tts")
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


@app.get("/audio/<path:subpath>")
def serve_audio(subpath):
    p = (AUDIO / subpath).resolve()
    if not p.is_relative_to(AUDIO.resolve()):
        abort(403)
    if not p.exists():
        abort(404)
    return send_from_directory(AUDIO, subpath, mimetype="audio/mpeg")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)


init_db()
migrate()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8200, debug=False)