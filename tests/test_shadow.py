"""听读模式接口测试：按课顺序出句、素材与课号校验。"""

USER = "b" * 32


def get(client, path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={USER}")


def test_shadow_lesson_in_order(client):
    r = get(client, "/api/shadow/session?list=test_sents&lesson=1")
    assert r.status_code == 200
    d = r.get_json()
    assert d["total"] == 2
    assert [i["text"] for i in d["items"]] == ["Hello world", "This is a test"]  # 按课原序，不打乱
    assert all(i["audio"] and i["zh"] for i in d["items"])


def test_shadow_without_lesson_returns_all(client):
    d = get(client, "/api/shadow/session?list=test_sents").get_json()
    assert d["total"] == 4


def test_shadow_validation(client):
    assert get(client, "/api/shadow/session?list=test_words").status_code == 400   # 词汇素材不收
    assert get(client, "/api/shadow/session?list=nope").status_code == 404         # 未知素材
    assert get(client, "/api/shadow/session?list=test_sents&lesson=99").status_code == 404
    assert get(client, "/api/shadow/session?list=test_sents&lesson=abc").status_code == 400


def post(client, payload):
    return client.post(f"/api/shadow/done?u={USER}", json=payload)


def test_shadow_done_records_and_accumulates(client):
    from backend.db import db
    r = post(client, {"list": "test_sents", "lesson": 1, "good": 2, "total": 2})
    assert r.status_code == 200 and r.get_json()["recorded"] is True
    post(client, {"list": "test_sents", "lesson": 2, "good": 1, "total": 2})
    from datetime import date
    with db() as c:
        row = c.execute(
            "SELECT * FROM daily_practice_log WHERE user=? AND practice_mode='shadow'",
            (USER,)).fetchone()
    assert row["day"] == date.today().isoformat()
    assert row["review_count"] == 3          # 两次完成累加
    # 零经验列全保持 0：客户端断言的分数永远不能变成 XP
    assert row["final_right_count"] == 0 and row["new_count"] == 0
    assert row["first_right_count"] == 0 and row["first_wrong_count"] == 0
    p = client.get(f"/api/profile?u={USER}").get_json()
    assert p["xp"] == 0 and p["streak"] == 1   # 不算经验，但算活跃（浇水/打卡）


def test_shadow_done_validation(client):
    ok = {"list": "test_sents", "lesson": 1, "good": 1, "total": 2}
    assert post(client, {**ok, "good": 3}).status_code == 400        # good > total
    assert post(client, {**ok, "total": 3}).status_code == 400       # total 超该课实际句数
    assert post(client, {**ok, "good": -1}).status_code == 400
    assert post(client, {**ok, "good": True}).status_code == 400     # 布尔不是整数
    assert post(client, {**ok, "good": "1"}).status_code == 400
    assert post(client, {**ok, "lesson": "abc"}).status_code == 400
    assert post(client, {**ok, "lesson": 99}).status_code == 404     # 课不存在
    assert post(client, {**ok, "list": "test_words"}).status_code == 400
    assert post(client, {**ok, "list": "nope"}).status_code == 404
    assert client.post(f"/api/shadow/done?u={USER}", data="x",
                       content_type="application/json").status_code == 400
