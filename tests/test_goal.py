"""学习计划：目标 CRUD / daily_new 推算 / 会话配额联动。"""
import json
import math
from datetime import date


def _set_goal(client, days=2):
    r = client.post("/api/goal", data=json.dumps({"list": "test_words", "target_days": days}),
                    content_type="application/json")
    assert r.status_code == 200
    return r.get_json()["goal"]


def test_goal_save_and_get(client):
    goal = _set_goal(client, days=2)
    # test_words 共 5 条（hello 重复文本占 2 行），2 天背完 → 每天至少 3 词
    assert goal["total"] == 5 and goal["remaining"] == 5
    assert goal["daily_new"] == math.ceil(5 / 2)
    assert goal["days_left"] == 2

    r = client.get("/api/goal")
    assert r.get_json()["goals"]["test_words"]["target_days"] == 2


def test_goal_validates_input(client):
    bad = [("nope", 10), ("test_sents", 10), ("test_words", 0), ("test_words", 400), ("test_words", "7")]
    for list_key, days in bad:
        r = client.post("/api/goal", data=json.dumps({"list": list_key, "target_days": days}),
                        content_type="application/json")
        assert r.status_code == 400, (list_key, days)


def test_goal_progress_shrinks_daily_new(client):
    _set_goal(client, days=5)
    # 背过 4 词（memorize_threshold=2，连对两次 → memorized）
    for word in ("hello", "world", "apple", "abandon"):
        for _ in range(2):
            r = client.post("/api/memorize", data=json.dumps({"list": "test_words", "id": word, "right": True}),
                            content_type="application/json")
            assert r.status_code == 200
    goal = client.get("/api/goal").get_json()["goals"]["test_words"]
    assert goal["memorized"] == 4 and goal["remaining"] == 1
    assert goal["daily_new"] == 1 and goal["today_done"] == 8


def test_goal_drives_session_quota(client, app):
    _set_goal(client, days=2)   # daily_new = ceil(5/2) = 3，取代默认 new_per_day=10
    r = client.get("/api/session?list=test_words&mode=assisted")
    assert r.get_json()["quota"]["new_quota"] == 3

    # 新用户：显式 new 参数优先于目标（当天 plan 只建一次，须换身份验证）
    app.test_client_class = type(client)
    other = app.test_client()
    other.get("/api/auth/me")
    _set_goal(other, days=2)
    r = other.get("/api/session?list=test_words&mode=assisted&new=1")
    assert r.get_json()["quota"]["new_quota"] == 1


def test_goal_delete(client):
    _set_goal(client)
    r = client.delete("/api/goal?list=test_words")
    assert r.status_code == 200
    assert client.get("/api/goal").get_json()["goals"] == {}
