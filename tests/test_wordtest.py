"""词汇量等级测试：出牌 / 自适应难度 / 结果落表 / 每日限流。"""
import json
from unittest.mock import patch

import backend.wordtest as wt


# ---- 测试用词池：每个难度等级若干词，含独立释义（40 词，够答满 25 题） ----
def _make_bank():
    words = ([(f"a1-{i}", f"cat{i}", f"n. 猫{i}") for i in range(1, 21)]
             + [(f"a2-{i}", f"apple{i}", f"n. 苹果{i}") for i in range(1, 21)])
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


def _correct_text(level, used_ids):
    """服务端视角复算当前题的正确选项文本（API 题面不下发 correct 标志）。"""
    q = wt._pick_question(level, set(used_ids))
    return _get_correct_option(q)["text"]


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


def test_pick_question_dedupes_overlapping_tiers():
    """词池不足向外扩层时相邻 offset 区间重叠，同一词不得重复进选项。"""
    bank = {lv: [] for lv in range(wt.MIN_DIFFICULTY, wt.MAX_DIFFICULTY + 1)}
    for i in range(4):
        for lv in (5, 6):
            bank[lv].append({"id": f"w{i}", "text": f"word{i}", "meaning": f"n. 词{i}"})
    with patch.object(wt, "_BANK", bank):
        q = wt._pick_question(5, set())
    # lv5 只有 4 词 → 扩到 lv6（同样 4 词）：候选按 id 去重后恰好 4 个，
    # 选项不得出现重复释义
    assert q is not None
    texts = [o["text"] for o in q["options"]]
    assert len(texts) == 4 and len(set(texts)) == 4


def test_question_api_returns_question(client):
    with _mock_bank():
        r = client.get("/api/wordtest/question?level=5&answered=0&consecutive_wrong=0&used_ids=")
    assert r.status_code == 200
    d = r.get_json()
    assert not d["done"]
    q = d["question"]
    assert len(q["options"]) == 4
    # 答案标志不下发：判分在服务端复算，客户端拿不到哪个选项对
    assert all("correct" not in opt for opt in q["options"])


def test_answer_right_advances_level(client):
    with _mock_bank():
        r2 = client.post("/api/wordtest/answer",
                         data=json.dumps({"option": _correct_text(5, set()),
                                          "level": 5, "answered": 0,
                                          "consecutive_wrong": 0, "used_ids": ""}),
                         content_type="application/json")
    d = r2.get_json()
    assert d["right"] is True
    assert d["level"] == 6
    assert d["consecutive_wrong"] == 0
    assert d["correct_count"] == 1


def test_answer_wrong_decreases_level(client):
    with _mock_bank():
        correct = _correct_text(5, set())
        wrong = next(o["text"] for o in wt._pick_question(5, set())["options"]
                     if o["text"] != correct)
        r2 = client.post("/api/wordtest/answer",
                         data=json.dumps({"option": wrong,
                                          "level": 5, "answered": 0,
                                          "consecutive_wrong": 0, "used_ids": ""}),
                         content_type="application/json")
    d = r2.get_json()
    assert d["right"] is False
    assert d["level"] == 4
    assert d["consecutive_wrong"] == 1
    assert d["correct_count"] == 0


def test_answer_correct_count_clamps(client):
    """correct_count 由客户端回传（无状态协议），但钳到 [0, answered] 防胡填。"""
    with _mock_bank():
        r = client.post("/api/wordtest/answer",
                        data=json.dumps({"option": _correct_text(5, set()),
                                         "level": 5, "answered": 3,
                                         "consecutive_wrong": 0, "correct_count": 99,
                                         "used_ids": ""}),
                        content_type="application/json")
    assert r.get_json()["correct_count"] == 4   # 99 钳到 answered=3，+本题 1


def test_answer_returns_next_question(client):
    with _mock_bank():
        r = client.get("/api/wordtest/question?level=5&answered=0&consecutive_wrong=0&used_ids=")
        q = r.get_json()["question"]
        r2 = client.post("/api/wordtest/answer",
                         data=json.dumps({"option": _correct_text(5, set()),
                                          "level": 5, "answered": 0,
                                          "consecutive_wrong": 0, "used_ids": ""}),
                         content_type="application/json")
        d = r2.get_json()
    assert not d["done"]
    assert d["question"] is not None
    assert d["question"]["id"] != q["id"]
    assert all("correct" not in opt for opt in d["question"]["options"])


def test_test_ends_and_saves_result(client, monkeypatch):
    """按前端协议答满 25 题：结束落表，correct_count 累计正确。"""
    mock = _mock_bank()
    mock.__enter__()
    _mock_today(monkeypatch)
    try:
        level, answered, consecutive_wrong = 5, 0, 0
        used_ids, correct_count = set(), 0
        r = client.get(f"/api/wordtest/question?level={level}&answered=0"
                       "&consecutive_wrong=0&used_ids=")
        q = r.get_json()["question"]
        d = {}
        for _ in range(25):
            r2 = client.post("/api/wordtest/answer",
                             data=json.dumps({
                                 "option": _correct_text(level, used_ids),
                                 "level": level, "answered": answered,
                                 "consecutive_wrong": consecutive_wrong,
                                 "correct_count": correct_count,
                                 "used_ids": ",".join(sorted(used_ids))}),
                             content_type="application/json")
            d = r2.get_json()
            assert d["right"] is True
            correct_count += 1
            used_ids.add(q["id"])
            if d.get("done"):
                break
            level = d["level"]
            answered = d["answered"]
            consecutive_wrong = d["consecutive_wrong"]
            q = d["question"]
        assert d["done"] and correct_count == 25

        r3 = client.get("/api/wordtest/result")
        result = r3.get_json()["result"]
        assert result is not None
        assert result["cefr"] in ("A1", "A2", "B1", "B2", "C1", "C2")
        assert result["word_count"] > 0
        assert result["correct_count"] == 25
        assert result["questions_answered"] == 25
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
    """当日完成次数达 DAILY_LIMIT 后，开局预检 429。"""
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


def test_daily_limit_enforced_on_finish(client, monkeypatch):
    """额度在完成落表时原子扣减：绕过开局直接刷 /answer 也 429，且不写结果行。"""
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
        r = client.post("/api/wordtest/answer",
                        data=json.dumps({"option": _correct_text(5, set()),
                                         "level": 5, "answered": wt.MAX_QUESTIONS - 1,
                                         "consecutive_wrong": 0, "used_ids": ""}),
                        content_type="application/json")
    assert r.status_code == 429
    with db_ctx() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM wordtest_result WHERE user=?",
                         (me,)).fetchone()["c"]
    assert n == 0