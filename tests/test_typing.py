"""打字数据页：WPM 曲线聚合 + 错键对挖掘 + 速度段位。"""
from datetime import date, datetime, timedelta, timezone

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


def test_stats_use_local_day_boundary(client):
    """answered_at 存 UTC：UTC+8 用户的晚间练习应聚合到本地次日/本地小时，
    无 X-Tz-Offset 头时保持原 UTC 口径（兼容老客户端）。"""
    today = date.today().isoformat()
    user = _user(client)
    _session("tp-tz", user, today)
    # UTC 20:00 = 北京（UTC+8，偏移 -480）次日凌晨 4 点
    stamp = f"{today}T20:00:00"
    with db() as conn:
        conn.execute(
            "INSERT INTO study_session_item(session_id,seq,item_id,kind,phase,state,"
            "first_right,final_right,attempt_count,answered_at,first_typed,last_typed,duration_ms) "
            "VALUES(?,?,?,?,?,'completed',1,1,1,?,NULL,?,?)",
            ("tp-tz", 0, "hello", "word", "new", stamp, "x" * 50, 30000))
    tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()

    d = client.get("/api/stats/typing", headers={"X-Tz-Offset": "-480"}).get_json()
    assert d["curve"][0]["day"] == tomorrow
    s = client.get("/api/stats", headers={"X-Tz-Offset": "-480"}).get_json()
    assert s["speed"][0]["day"] == tomorrow
    assert s["hours"][4] == 1 and s["hours"][20] == 0

    d2 = client.get("/api/stats/typing").get_json()   # 无头：UTC 日界，行为不变
    assert d2["curve"][0]["day"] == today
    s2 = client.get("/api/stats").get_json()
    assert s2["hours"][20] == 1
    # wpm7 只计本地近 7 日：班次后若已跨入 UTC+8 次日（UTC 深夜跑测试时），
    # 该点落在窗口内 → 20.0/白银；否则被排除 → 0/青铜
    local_today = (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()
    if tomorrow <= local_today:
        assert d["wpm7"] == 20.0 and d["tier"] == "白银"
    else:
        assert d["wpm7"] == 0 and d["tier"] == "青铜"


def test_old_rows_outside_window_ignored(client):
    old = (date.today() - timedelta(days=120)).isoformat()
    _session("tp-3", _user(client), old)
    _item("tp-3", 0, "apple", first_right=0, final_right=1,
          duration_ms=5000, last_typed="apple", first_typed="aple", day=old)
    d = client.get("/api/stats/typing").get_json()
    assert d["curve"] == [] and d["heatmap"] == []
