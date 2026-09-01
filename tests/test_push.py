"""Web Push：订阅 CRUD 校验 + 到期提醒查询 + 每日一轮认领。"""
import json
from datetime import date, datetime

from backend.db import db
from backend.push import due_reminders, remind_today


def _sub(client, endpoint="https://push.example.com/abc123"):
    body = {"endpoint": endpoint, "keys": {"p256dh": "B" * 87, "auth": "a" * 22}}
    return client.post("/api/push/subscribe", data=json.dumps(body), content_type="application/json")


def test_subscribe_and_unsubscribe(client):
    assert _sub(client).status_code == 200
    me = client.get("/api/auth/me").get_json()
    with db() as conn:
        rows = conn.execute("SELECT * FROM push_subscription").fetchall()
        assert len(rows) == 1 and rows[0]["user"] == me["user"]

    r = client.delete("/api/push/subscribe",
                      data=json.dumps({"endpoint": "https://push.example.com/abc123"}),
                      content_type="application/json")
    assert r.status_code == 200
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM push_subscription").fetchone()["c"] == 0


def test_subscribe_validates(client):
    bad = [
        {"endpoint": "http://insecure.com/x", "keys": {"p256dh": "B" * 87, "auth": "a" * 22}},
        {"endpoint": "https://ok.com/x", "keys": {"p256dh": "short", "auth": "a" * 22}},
        {"endpoint": "https://ok.com/x", "keys": {}},
        "not-a-dict",
    ]
    for body in bad:
        r = client.post("/api/push/subscribe", data=json.dumps(body), content_type="application/json")
        assert r.status_code == 400, body


def test_due_reminders(client):
    # 目标 2 天背完 5 词 → 每天 3 词；还没背 → 到期
    client.post("/api/goal", data=json.dumps({"list": "test_words", "target_days": 2}),
                content_type="application/json")
    me = client.get("/api/auth/me").get_json()
    with db() as conn:
        due = due_reminders(conn)
        assert due == [{"user": me["user"], "list": "test_words", "missing": 3}]

        # 模拟今天已背够 → 不再提醒
        conn.execute(
            "INSERT INTO daily_log(day,user,memorize_right) VALUES(?,?,?)",
            (date.today().isoformat(), me["user"], 3))
        assert due_reminders(conn) == []


def test_remind_claimed_once_per_day(client, monkeypatch, tmp_path):
    key = tmp_path / "vapid_key.pem"
    key.write_text("dummy")
    monkeypatch.setattr("backend.push.VAPID_KEY_FILE", key)
    sent = []
    monkeypatch.setattr("backend.push.send_payload", lambda sub, payload: sent.append(sub) or True)

    client.post("/api/goal", data=json.dumps({"list": "test_words", "target_days": 2}),
                content_type="application/json")
    _sub(client)

    at21 = datetime.now().replace(hour=21, minute=0)
    assert remind_today(now_dt=at21) is True
    assert len(sent) == 1
    # 同日第二轮：认领行已写，不再发送（多 worker 竞态也由 BEGIN IMMEDIATE 兜住）
    assert remind_today(now_dt=at21) is False
    assert len(sent) == 1
    # 未到点不发
    assert remind_today(now_dt=datetime.now().replace(hour=9, minute=0)) is False
