"""词力等级 / 单词树推导测试。"""
from datetime import date, timedelta

import pytest

from backend.db import db
from backend.profile import level_of

USER = "d" * 32
TODAY = date.today().isoformat()


def get(client, path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={USER}")


def insert_dictation_days(rows):
    with db() as conn:
        for day, right in rows:
            conn.execute(
                "INSERT INTO daily_log(day,user,right_count) VALUES(?,?,?)",
                (day, USER, right))


def insert_daily_challenge(score=4, total=4):
    with db() as conn:
        conn.execute(
            "INSERT INTO daily_challenge(day,user,list_key,score,total,detail,completed_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (TODAY, USER, "test_words", score, total, "[]", TODAY))


def test_empty_user_starts_at_level_one(client):
    p = get(client, "/api/profile").get_json()
    assert p["xp"] == 0 and p["level"] == 1 and p["title"] == "词童"
    assert p["streak"] == 0 and p["today_done"] is False
    assert p["tree_stage"] == 0 and p["tree_wilted"] is False
    assert p["next_level_xp"] == 100 and p["level_progress"] == 0
    assert p["daily_count"] == 0 and p["daily_done_today"] is False
    assert len(p["week"]) == 7


def test_xp_formula_exact(client):
    # 10×对题 + 3×新词 + 2×(错题+跳过) + 5×背词 + 10×每日挑战得分 + 2×每日挑战丢分
    with db() as conn:
        conn.execute(
            "INSERT INTO daily_practice_log(day,user,practice_mode,new_count,"
            "first_wrong_count,final_right_count,skipped_count) VALUES(?,?,?,?,?,?,?)",
            (TODAY, USER, "assisted", 3, 2, 7, 1))
        conn.execute(
            "INSERT INTO daily_log(day,user,memorize_right) VALUES(?,?,?)",
            (TODAY, USER, 4))
        conn.execute(
            "INSERT INTO daily_challenge(day,user,list_key,score,total,detail,completed_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (TODAY, USER, "test_words", 6, 10, "[]", TODAY))
    p = get(client, "/api/profile").get_json()
    assert p["xp"] == 10 * 7 + 3 * 3 + 2 * (2 + 1) + 5 * 4 + 10 * 6 + 2 * 4   # 173
    assert p["level"] == 2 and p["title"] == "词苗"
    assert p["level_floor"] == 100 and p["next_level_xp"] == 300


@pytest.mark.parametrize("xp,want", [
    (0, 1), (99, 1), (100, 2), (299, 2), (300, 3),
    (9999, 10), (10000, 11), (999999, 11),
])
def test_level_thresholds(xp, want):
    assert level_of(xp) == want


def test_streak_unions_all_activity_sources(client):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    insert_dictation_days([(yesterday, 5)])             # 昨天听打打卡
    insert_daily_challenge()                            # 今天完成每日挑战
    p = get(client, "/api/profile").get_json()
    assert p["streak"] == 2                             # 活跃并集口径
    assert p["today_done"] is True
    assert p["tree_stage"] == min(2, p["tree_max_stage"])
    assert p["daily_done_today"] is True and p["daily_streak"] == 1


def test_tree_thirsty_when_only_yesterday_practiced(client):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    insert_dictation_days([(yesterday, 1)])
    p = get(client, "/api/profile").get_json()
    assert p["streak"] == 1 and p["today_done"] is False
    assert p["tree_wilted"] is False                    # 昨天练过只是口渴，不算枯萎
    assert p["tree_needs_water"] is True


def test_tree_wilts_after_two_idle_days(client):
    three_days_ago = (date.today() - timedelta(days=3)).isoformat()
    insert_dictation_days([(three_days_ago, 9)])
    p = get(client, "/api/profile").get_json()
    assert p["tree_wilted"] is True
    assert p["tree_stage"] == 0 and p["tree_icon"] == "🥀" and p["tree_label"] == "枯萎"
    assert p["missed_days"] == 3 and p["last_active_day"] == three_days_ago


def test_max_level_caps_progress(client):
    insert_daily_challenge(score=1500, total=1500)      # 直写库模拟长期积累：15000 XP
    p = get(client, "/api/profile").get_json()
    assert p["level"] == 11 and p["title"] == "词神"
    assert p["next_level_xp"] is None
    assert p["level_progress"] == 1.0


def test_week_aligns_to_current_monday(client):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    p = get(client, "/api/profile").get_json()
    assert p["week"][0]["day"] == monday.isoformat()
    assert p["week"][6]["day"] == (monday + timedelta(days=6)).isoformat()
    assert all(slot["active"] is False for slot in p["week"])
