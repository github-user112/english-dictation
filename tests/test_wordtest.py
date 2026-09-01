"""词汇量等级测试：出牌 / 自适应难度 / 结果落表 / 每日限流。"""
import json
from unittest.mock import patch

import backend.wordtest as wt


# ---- 测试用词池：每个难度等级若干词，含独立释义 ----
def _make_bank():
    words = [
        ("a1-1", "cat", "n. 猫"), ("a1-2", "dog", "n. 狗"),
        ("a1-3", "hat", "n. 帽子"), ("a1-4", "bus", "n. 公交车"),
        ("a1-5", "cup", "n. 杯子"), ("a1-6", "dog", "n. 小狗"),
        ("a1-7", "run", "v. 跑"), ("a1-8", "big", "a. 大的"),
        ("a2-1", "apple", "n. 苹果"), ("a2-2", "book", "n. 书"),
        ("a2-3", "city", "n. 城市"), ("a2-4", "door", "n. 门"),
        ("a2-5", "exam", "n. 考试"), ("a2-6", "flag", "n. 旗帜"),
        ("a2-7", "game", "n. 游戏"), ("a2-8", "hill", "n. 小山"),
    ]
    bank = {lv: [] for lv in range(wt.MIN_DIFFICULTY, wt.MAX_DIFFICULTY + 1)}
    for wid, text, meaning in words:
        tier = "a1" if wid.startswith("a1") else "a2"
        lo, hi = (1, 3) if tier == "a1" else (4, 6)
        for lv in range(lo, hi + 1):
            bank[lv].append({"id": wid, "text": text, "meaning": meaning})
        for lv in range(7, wt.MAX_DIFFICULTY + 1):
            bank[lv].append({"id": wid, "text": text, "meaning": meaning})
    return bank


_TEST_BANK = _make_bank()


def _mock_bank():
    return patch.object(wt, "_BANK", _TEST_BANK)


def _mock_today(monkeypatch):
    """固定 today，让种子确定性。"""
    import datetime
    class _FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 1)
    monkeypatch.setattr(wt, "date", _FakeDate)


def _get_correct_option(q):
    for opt in q["options"]:
        if opt["correct"]:
            return opt
    return None


def test_pick_question_returns_four_options():
    with _mock_bank():
        q = wt._pick_question(2, set())
    assert q is not None
    assert len(q["options"]) == 4
    assert any(opt["correct"] for opt in q["options"])
    assert sum(1 for opt in q["options"] if opt["correct"]) == 1


def test_pick_question_deterministic_for_same_state():
    with _mock_bank():
        q1 = wt._pick_question(3, set())
        q2 = wt._pick_question(3, set())
    assert q1["id"] == q2["id"]
    assert q1["options"] == q2["options"]


def test_pick_question_excludes_used_words():
    with _mock_bank():
        q1 = wt._pick_question(2, set())
        q2 = wt._pick_question(2, {q1["id"]})
    assert q2 is not None
    assert q2["id"] != q1["id"]


def test_question_api_returns_question(client):
    with _mock_bank():
        r = client.get("/api/wordtest/question?level=5&answered=0&consecutive_wrong=0&used_ids=")
    assert r.status_code == 200
    d = r.get_json()
    assert not d["done"]
    q = d["question"]
    assert len(q["options"]) == 4
    assert any(opt["correct"] for opt in q["options"])


def test_answer_right_advances_level(client):
    with _mock_bank():
        r = client.get("/api/wordtest/question?level=5&answered=0&consecutive_wrong=0&used_ids=")
        q = r.get_json()["question"]
        correct = _get_correct_option(q)
        r2 = client.post("/api/wordtest/answer",
                         data=json.dumps({"option": correct["text"],
                                          "level": 5, "answered": 0,
                                          "consecutive_wrong": 0, "used_ids": ""}),
                         content_type="application/json")
    d = r2.get_json()
    assert d["right"] is True
    assert d["level"] == 6
    assert d["consecutive_wrong"] == 0


def test_answer_wrong_decreases_level(client):
    with _mock_bank():
        r = client.get("/api/wordtest/question?level=5&answered=0&consecutive_wrong=0&used_ids=")
        q = r.get_json()["question"]
        wrong = next(opt for opt in q["options"] if not opt["correct"])
        r2 = client.post("/api/wordtest/answer",
                         data=json.dumps({"option": wrong["text"],
                                          "level": 5, "answered": 0,
                                          "consecutive_wrong": 0, "used_ids": ""}),
                         content_type="application/json")
    d = r2.get_json()
    assert d["right"] is False
    assert d["level"] == 4
    assert d["consecutive_wrong"] == 1


def test_answer_returns_next_question(client):
    with _mock_bank():
        r = client.get("/api/wordtest/question?level=5&answered=0&consecutive_wrong=0&used_ids=")
        q = r.get_json()["question"]
        correct = _get_correct_option(q)
        r2 = client.post("/api/wordtest/answer",
                         data=json.dumps({"option": correct["text"],
                                          "level": 5, "answered": 0,
                                          "consecutive_wrong": 0, "used_ids": ""}),
                         content_type="application/json")
        d = r2.get_json()
    assert not d["done"]
    assert d["question"] is not None
    assert d["question"]["id"] != q["id"]


def test_test_ends_and_saves_result(client, monkeypatch):
    """达到最大题数后结束并落表。"""
    mock = _mock_bank()
    mock.__enter__()
    _mock_today(monkeypatch)
    try:
        level = 5
        used_ids = set()
        consecutive_wrong = 0
        for i in range(25):
            r = client.get(
                f"/api/wordtest/question?level={level}&answered={i}"
                f"&consecutive_wrong={consecutive_wrong}"
                f"&used_ids={','.join(sorted(used_ids))}")
            q = r.get_json().get("question")
            if q is None:
                break
            correct = _get_correct_option(q)
            used_ids.add(q["id"])
            r2 = client.post("/api/wordtest/answer",
                             data=json.dumps({
                                 "option": correct["text"],
                                 "level": level, "answered": i,
                                 "consecutive_wrong": consecutive_wrong,
                                 "used_ids": ",".join(sorted(used_ids))}),
                             content_type="application/json")
            d = r2.get_json()
            if d.get("done"):
                break
            level = d["level"]
            consecutive_wrong = d["consecutive_wrong"]

        r3 = client.get("/api/wordtest/result")
        result = r3.get_json()["result"]
        assert result is not None
        assert result["cefr"] in ("A1", "A2", "B1", "B2", "C1", "C2")
        assert result["word_count"] > 0
    finally:
        mock.__exit__(None, None, None)


def test_result_endpoint_returns_latest(client):
    """直接灌入结果，验证 /result 返回最近一次。"""
    from backend.db import db as db_ctx
    from backend.catalog import now

    uid = client.get("/api/auth/me").get_json()["user"]
    ts1 = now()
    ts2 = "2099-01-01T00:00:00"

    with db_ctx() as conn:
        conn.execute(
            "INSERT INTO wordtest_result(user, level, questions_answered, "
            "correct_count, cefr, word_count, detail, created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uid, 6, 25, 18, "A2", 1500, "[]", ts1))
        conn.execute(
            "INSERT INTO wordtest_result(user, level, questions_answered, "
            "correct_count, cefr, word_count, detail, created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uid, 10, 25, 20, "B2", 4500, "[]", ts2))

    r = client.get("/api/wordtest/result")
    result = r.get_json()["result"]
    assert result is not None
    assert result["cefr"] == "B2"
    assert result["word_count"] == 4500


def test_daily_limit_enforced(client, monkeypatch):
    """当日测试次数超过 DAILY_LIMIT 返回 429。"""
    from backend.db import db as db_ctx
    from datetime import date
    from backend.wordtest import DAILY_LIMIT

    _mock_today(monkeypatch)
    me = client.get("/api/auth/me").get_json()["user"]
    today = date(2026, 9, 1).isoformat()
    with db_ctx() as conn:
        conn.execute(
            "INSERT INTO push_meta(name, value) VALUES(?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
            (f"wordtest|{me}|{today}", str(DAILY_LIMIT)))

    with _mock_bank():
        r = client.get("/api/wordtest/question?level=5&answered=0&consecutive_wrong=0&used_ids=")
    assert r.status_code == 429