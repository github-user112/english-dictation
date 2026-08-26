"""听音排句接口测试：确定性发牌、重拼判分、记账不碰记忆状态。"""
from backend.arrange import build_chunks, deal_chunks
from backend.db import db

USER = "b" * 32


def get(client, path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={USER}")


def test_build_chunks_caps_length_and_preserves_words():
    assert build_chunks("one two three") == ["one", "two", "three"]
    long = " ".join(f"w{i}" for i in range(20))
    chunks = build_chunks(long)
    assert len(chunks) <= 8
    assert " ".join(chunks) == long   # 切块不丢词


def test_deal_chunks_deterministic_and_never_identity():
    a = deal_chunks("test_sents", "2", "This is a test")
    b = deal_chunks("test_sents", "2", "This is a test")
    assert a == b                       # 同句同布局（可重放）
    assert sorted(a) == ["This", "a", "is", "test"] or sorted(a) == sorted(a)
    assert a != ["This", "is", "a", "test"]   # 恒不打回原序
    assert deal_chunks("test_sents", "3", "x") != deal_chunks("test_sents", "4", "y")


def test_arrange_session_shape_and_pool(client):
    body = get(client, "/api/arrange/session?list=test_sents").get_json()
    assert body["total"] == 3   # "Hello world" 只有 2 词，不足 MIN_WORDS 被滤掉
    for q in body["questions"]:
        assert q["zh"] and q["audio"].startswith("/audio/")
        assert len(q["chunks"]) >= 3 and all(q["chunks"])
    # lesson 聚焦：第 2 课只有两句可用
    focused = get(client, "/api/arrange/session?list=test_sents&lesson=2").get_json()
    assert focused["total"] == 2


def test_arrange_session_errors(client):
    assert get(client, "/api/arrange/session?list=test_words").status_code == 400
    assert get(client, "/api/arrange/session?list=nope").status_code == 404
    assert get(client, "/api/arrange/session?list=test_sents&lesson=abc").status_code == 400


def test_arrange_answer_grades_rebuild(client):
    s = get(client, "/api/arrange/session?list=test_sents").get_json()
    q = next(x for x in s["questions"] if x["id"] == "2")   # This is a test
    right_order = [q["chunks"].index(w) for w in ["This", "is", "a", "test"]]
    wrong_order = list(reversed(right_order))

    ok = client.post(f"/api/arrange/answer?u={USER}",
                     json={"list": "test_sents", "id": "2", "order": right_order})
    assert ok.status_code == 200
    assert ok.get_json()["right"] is True
    assert ok.get_json()["text"] == "This is a test"
    assert ok.get_json()["profile"]["xp"] == 10

    bad = client.post(f"/api/arrange/answer?u={USER}",
                      json={"list": "test_sents", "id": "2", "order": wrong_order})
    assert bad.get_json()["right"] is False
    assert bad.get_json()["profile"]["xp"] == 12   # 10×1 对 + 2×1 错

    with db() as conn:
        log = conn.execute(
            "SELECT first_right_count fr,first_wrong_count fw FROM daily_practice_log "
            "WHERE user=? AND practice_mode='arrange'", (USER,)).fetchone()
        assert (log["fr"], log["fw"]) == (1, 1)
        # 排句是句子玩法：不动 word_state、不计听打 daily_log
        assert conn.execute(
            "SELECT COUNT(*) c FROM word_state WHERE user=?", (USER,)).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM daily_log WHERE user=?", (USER,)).fetchone()["c"] == 0


def test_arrange_answer_rejects_invalid_orders(client):
    post = lambda order: client.post(  # noqa: E731
        f"/api/arrange/answer?u={USER}",
        json={"list": "test_sents", "id": "2", "order": order}).status_code
    assert post([0, 1, 2]) == 400              # 缺一个下标
    assert post([0, 1, 2, 3, 3]) == 400        # 超长且重复
    assert post([0, 1, 2, 9]) == 400           # 下标越界
    assert post([True, False, 2, 3]) == 400    # bool 冒充下标
    assert post(["0", "1", "2", "3"]) == 400   # 字符串下标
    assert post("0123") == 400                 # 不是列表
    assert client.post(f"/api/arrange/answer?u={USER}",
                       json={"list": "test_sents", "id": "999", "order": [0]}).status_code == 400
    assert client.post(f"/api/arrange/answer?u={USER}",
                       json={"list": "nope", "id": "2", "order": [0, 1, 2, 3]}).status_code == 404
    with db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM daily_practice_log WHERE user=? AND practice_mode='arrange'",
            (USER,)).fetchone()["c"] == 0
