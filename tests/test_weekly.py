"""周报：本周汇总 + 上周对比增量口径。"""
import json
from datetime import date, timedelta


def _seed_week(client):
    """本周一 +1 次背诵、听打 4 对 1 错；上周听打 1 对 3 错。"""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    last_monday = monday - timedelta(days=7)
    # 每日挑战接口不写 daily_log，直接通过背诵接口落今天的 memorize_right
    client.post("/api/memorize", data=json.dumps({"list": "test_words", "id": "hello", "right": True}),
                content_type="application/json")
    from backend.db import db
    me = client.get("/api/auth/me").get_json()["user"]
    with db() as conn:
        conn.execute(
            "INSERT INTO daily_practice_log(day,user,practice_mode,new_count,first_right_count,first_wrong_count) "
            "VALUES(?,?,?,?,?,?)", (monday.isoformat(), me, "assisted", 5, 4, 1))
        conn.execute(
            "INSERT INTO daily_practice_log(day,user,practice_mode,new_count,first_right_count,first_wrong_count) "
            "VALUES(?,?,?,?,?,?)", (last_monday.isoformat(), me, "assisted", 4, 1, 3))


def test_weekly_report(client):
    _seed_week(client)
    d = client.get("/api/report/weekly").get_json()
    assert d["items"] == 5
    assert d["accuracy"] == 80            # 4/5 本周
    assert d["accuracy_delta"] == 55      # 上周 25% → +55 个百分点
    assert d["memorize_right"] == 1
    assert d["days_active"] == 1
    assert d["streak"] >= 1


def test_weekly_report_no_history(client):
    d = client.get("/api/report/weekly").get_json()
    assert d["items"] == 0 and d["accuracy"] == 0
    assert d["accuracy_delta"] is None    # 无上周数据时不报增量
    assert d["days_active"] == 0
