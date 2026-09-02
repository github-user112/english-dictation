"""词汇量等级测试：出牌 / 服务端会话 / 自适应难度 / 结果落表 / 每日限流。"""
import json
from unittest.mock import patch

import backend.wordtest as wt
from backend.db import db as db_ctx


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


def _get_correct_option(q):
    for opt in q["options"]:
        if opt["correct"]:
            return opt
    return None


def _start(client):
    r = client.post("/api/wordtest/start", data="{}", content_type="application/json")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _session_row(sid):
    with db_ctx() as conn:
        return conn.execute(
            "SELECT * FROM wordtest_session WHERE id=?", (sid,)).fetchone()


def _session_correct_text(sid):
    """从服务端会话行读当前题的正确选项（API 题面已不带 correct 标志）。"""
    q = json.loads(_session_row(sid)["question"])
    return _get_correct_option(q)["text"]


def _answer(client, sid, option):
    return client.post("/api/wordtest/answer",
                       data=json.dumps({"session_id": sid, "option": option}),
                       content_type="application/json")


# ---- _pick_question 单元 ----

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


# ---- 会话 API ----

def test_start_creates_session_and_hides_answers(client):
    with _mock_bank():
        d = _start(client)
    assert d["session_id"]
    q = d["question"]
    assert len(q["options"]) == 4
    # 答案标志不下发：判分在服务端，客户端拿不到哪个选项对
    assert all("correct" not in opt for opt in q["options"])
    row = _session_row(d["session_id"])
    assert row is not None and row["done"] == 0 and row["answered"] == 0


def test_answer_right_advances_level(client):
    with _mock_bank():
        d = _start(client)
        sid = d["session_id"]
        r = _answer(client, sid, _session_correct_text(sid))
    d2 = r.get_json()
    assert d2["right"] is True
    assert d2["level"] == d["level"] + 1
    assert d2["consecutive_wrong"] == 0
    assert d2["correct_count"] == 1
    assert all("correct" not in opt for opt in d2["question"]["options"])


def test_answer_wrong_decreases_level(client):
    with _mock_bank():
        d = _start(client)
        sid = d["session_id"]
        correct = _session_correct_text(sid)
        wrong = next(o["text"] for o in d["question"]["options"] if o["text"] != correct)
        r = _answer(client, sid, wrong)
    d2 = r.get_json()
    assert d2["right"] is False
    assert d2["level"] == d["level"] - 1
    assert d2["consecutive_wrong"] == 1
    assert d2["correct_count"] == 0


def test_answer_rejects_bad_session(client):
    r = _answer(client, "nonexistent", "x")
    assert r.status_code == 404


def test_full_run_saves_result_and_seals_session(client):
    """答满 25 题：落结果表（含逐题 detail），会话封盘不可再答。"""
    with _mock_bank():
        d = _start(client)
        sid = d["session_id"]
        d2 = {}
        for _ in range(wt.MAX_QUESTIONS):
            r = _answer(client, sid, _session_correct_text(sid))
            d2 = r.get_json()
            assert d2["right"] is True
            if d2["done"]:
                break
        assert d2["done"] and d2["correct_count"] == 25 and d2["answered"] == 25

        row = _session_row(sid)
        assert row["done"] == 1 and row["question"] is None
        # 已结束的会话拒收答案
        assert _answer(client, sid, "x").status_code == 409

        r3 = client.get("/api/wordtest/result")
        result = r3.get_json()["result"]
        assert result is not None
        assert result["cefr"] == "C2"           # 全对一路升到 L18
        assert result["word_count"] == 15000
        assert result["correct_count"] == 25
        assert result["questions_answered"] == 25

        with db_ctx() as conn:
            detail = conn.execute(
                "SELECT detail FROM wordtest_result ORDER BY id DESC LIMIT 1"
            ).fetchone()["detail"]
        assert len(json.loads(detail)) == 25    # 逐题记录完整


def test_daily_limit_on_start(client):
    """每日限开 DAILY_LIMIT 局（弃测也占额度：会话行即计量，无刷行通道）。"""
    with _mock_bank():
        for _ in range(wt.DAILY_LIMIT):
            _start(client)
        r = client.post("/api/wordtest/start", data="{}",
                        content_type="application/json")
    assert r.status_code == 429
    with db_ctx() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM wordtest_session").fetchone()["c"]
    assert n == wt.DAILY_LIMIT


def test_result_endpoint_returns_latest(client):
    """直接灌入结果，验证 /result 返回最近一次。"""
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
