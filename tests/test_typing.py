"""打字数据页：WPM 曲线聚合 + 错键对挖掘 + 速度段位。"""
from datetime import date, timedelta

from backend.catalog import now
from backend.db import db


def _user(client):
    return client.get("/api/auth/me").get_json()["user"]


def _session(session_id, user, day):
    stamp = now()
    with db() as conn:
        conn.execute("INSERT INTO study_session VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (session_id, user, "test_words", "pure", "all", "daily", None,
                      day, 0, "active", stamp, stamp, None))


def _item(session_id, seq, item_id, *, final_right=1, first_right=1, duration_ms=None,
          last_typed=None, first_typed=None, day=None):
    stamp = f"{day or date.today().isoformat()}T12:00:00"
    with db() as conn:
        conn.execute(
            "INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,"
            "first_right,final_right,attempt_count,answered_at,first_typed,last_typed,duration_ms) "
            "VALUES(?,?,?,?,?,'completed',?,?,1,?,?,?,?)",
            (session_id, seq, item_id, "word", "new", first_right, final_right,
             stamp, first_typed, last_typed, duration_ms))


def test_wpm_curve_and_tier(client):
    today = date.today().isoformat()
    _session("tp-1", _user(client), today)
    # 100 字符用时 60 秒 → 100/5 = 20 词/分 = 20 WPM → 白银
    _item("tp-1", 0, "hello", duration_ms=30000, last_typed="x" * 50, day=today)
    _item("tp-1", 1, "world", duration_ms=30000, last_typed="y" * 50, day=today)
    d = client.get("/api/stats/typing").get_json()
    assert d["curve"] == [{"day": today, "wpm": 20.0, "n": 2}]
    assert d["wpm7"] == 20.0
    assert d["tier"] == "白银"


def test_heatmap_pairs(client):
    today = date.today().isoformat()
    user = _user(client)
    # 应敲 apple 实敲 aple：delete 分支 → (p, ⌫)；首答错才算错键样本
    for sid in ("tp-2a", "tp-2b"):
        _session(sid, user, today)
        _item(sid, 0, "apple", first_right=0, final_right=1,
              duration_ms=5000, last_typed="apple", first_typed="aple", day=today)
    d = client.get("/api/stats/typing").get_json()
    row = next(h for h in d["heatmap"] if h["expect"] == "p")
    assert row["total"] == 2
    assert row["got"][0] == {"key": "⌫", "count": 2}


def test_typing_empty_for_new_user(client):
    d = client.get("/api/stats/typing").get_json()
    assert d["curve"] == [] and d["heatmap"] == []
    assert d["wpm7"] == 0 and d["tier"] == "青铜"


def test_old_rows_outside_window_ignored(client):
    old = (date.today() - timedelta(days=120)).isoformat()
    _session("tp-3", _user(client), old)
    _item("tp-3", 0, "apple", first_right=0, final_right=1,
          duration_ms=5000, last_typed="apple", first_typed="aple", day=old)
    d = client.get("/api/stats/typing").get_json()
    assert d["curve"] == [] and d["heatmap"] == []
