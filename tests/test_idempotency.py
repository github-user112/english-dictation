"""计分接口幂等 + 单日上限：防重放刷分。

覆盖五个计分写接口：
  /api/result         → endpoint="result"   (legacy sprint/quiz/wrong)
  /api/match/result   → endpoint="match"
  /api/boss/result    → endpoint="boss"
  /api/arrange/answer → endpoint="arrange"
  /api/memorize/*     → 已有 memorize_attempt 表，此处不测

每个接口在收到 attempt_id 时以 (user, endpoint, attempt_id) 三元组做去重：
重复请求不再记账并返回 duplicate=True；新 attempt_id 则正常记账。
当日累计次数达到该 endpoint 的 SCORE_CAPS 上限时返回 429。
老客户端未传 attempt_id 时照旧记（兼容路径）。
"""
from unittest.mock import patch

import pytest

from backend.db import db
from backend.idempotency import SCORE_CAPS, check_and_mark, mark_done, validate_attempt_id

USER = "b" * 32
TINY_CAPS = {"result": 3, "match": 2, "boss": 2, "arrange": 3}

# 素材侧准备：/match 与 /boss 需要 seed word_state
_MATCH_ANSWERS = [
    {"id": "hello", "right": True},
    {"id": "world", "right": False},
    {"id": "apple", "right": True},
]

_BOSS_ANSWERS = [
    {"id": "hello", "list": "test_words", "right": True},
    {"id": "world", "list": "test_words", "right": False},
]


def _seed_boss_wrong(client):
    with db() as conn:
        for i, (item_id, wc) in enumerate([("hello", 5), ("world", 4), ("apple", 2)]):
            conn.execute(
                "INSERT OR IGNORE INTO word_state(user,list,item_id,wrong_count,last_seen) "
                "VALUES(?,?,?,?,?)",
                (USER, "test_words", item_id, wc, f"2026-08-{10 + i:02d}T10:00:00"))


def _post(client, path, payload):
    return client.post(f"{path}?u={USER}", json=payload)


# ---------------------------------------------------------------------------
# validate_attempt_id
# ---------------------------------------------------------------------------

def test_validate_attempt_id_accepts_normal_and_rejects_bad():
    assert validate_attempt_id("abc123")[0] == "abc123"
    assert validate_attempt_id("a-b-c")[0] == "a-b-c"    # 含横杠的 UUID 通过
    assert validate_attempt_id("a" * 128)[0] is not None  # 上界

    assert validate_attempt_id(None)[0] is None
    assert validate_attempt_id("")[0] is None
    assert validate_attempt_id(123)[1] is not None        # 非 str
    assert validate_attempt_id("a" * 129)[1] is not None  # 超上限
    assert validate_attempt_id("abc def")[1] is not None  # 空格
    assert validate_attempt_id("abc@def")[1] is not None  # 特殊字符


# ---------------------------------------------------------------------------
# /api/result  幂等 + 上限
# ---------------------------------------------------------------------------

def test_result_replay_same_attempt_id_is_deduped(client):
    aid = "rpl1"
    payload = {
        "list": "test_words", "id": "hello", "mode": "assisted",
        "first_right": True, "final_right": True, "right": True,
        "outcome": "completed", "attempt_id": aid,
    }
    r1 = _post(client, "/api/result", payload)
    assert r1.status_code == 200
    b1 = r1.get_json()
    assert b1["legacy"] is True and b1.get("duplicate") is not True

    r2 = _post(client, "/api/result", payload)
    assert r2.status_code == 200 and r2.get_json()["duplicate"] is True

    # 重放不重复记账：daily_practice_log 只记一次
    with db() as conn:
        log = conn.execute(
            "SELECT first_right_count fr,final_right_count fin "
            "FROM daily_practice_log WHERE user=? AND practice_mode='assisted'",
            (USER,)).fetchone()
        assert (log["fr"], log["fin"]) == (1, 1)


def test_result_new_attempt_ids_both_count(client):
    """两把不同的 attempt_id 视为两笔独立记录。"""
    payload = {
        "list": "test_words", "id": "hello", "mode": "assisted",
        "first_right": True, "final_right": True, "right": True,
        "outcome": "completed",
    }
    for aid in ("u1", "u2"):
        payload["attempt_id"] = aid
        assert _post(client, "/api/result", payload).status_code == 200
        assert _post(client, "/api/result", payload).get_json()["duplicate"] is True

    with db() as conn:
        log = conn.execute(
            "SELECT first_right_count fr FROM daily_practice_log "
            "WHERE user=? AND practice_mode='assisted'", (USER,)).fetchone()
        assert log["fr"] == 2


def test_result_hits_daily_cap_returns_429(client):
    with patch("backend.idempotency.SCORE_CAPS", TINY_CAPS):
        payload = {
            "list": "test_words", "id": "hello", "mode": "assisted",
            "first_right": True, "final_right": True, "right": True,
            "outcome": "completed",
        }
        for i in range(TINY_CAPS["result"]):
            payload["attempt_id"] = f"c{i}"
            assert _post(client, "/api/result", payload).status_code == 200
        payload["attempt_id"] = f"c{99}"
        r = _post(client, "/api/result", payload)
        assert r.status_code == 429
        assert "上限" in r.get_json()["error"]


# ---------------------------------------------------------------------------
# /api/match/result
# ---------------------------------------------------------------------------

def test_match_replay_same_attempt_id_is_deduped(client):
    aid = "m1"
    payload = {
        "list": "test_words",
        "answers": _MATCH_ANSWERS,
        "attempt_id": aid,
    }
    r1 = _post(client, "/api/match/result", payload)
    assert r1.status_code == 200
    assert r1.get_json().get("duplicate") is not True
    assert r1.get_json()["total"] == 3 and r1.get_json()["perfect"] == 2

    r2 = _post(client, "/api/match/result", payload)
    assert r2.status_code == 200 and r2.get_json()["duplicate"] is True
    # 重放返回与首次一致的分
    assert r2.get_json()["perfect"] == 2

    # daily_practice_log 只记一次
    with db() as conn:
        log = conn.execute(
            "SELECT first_right_count fr,final_right_count fin "
            "FROM daily_practice_log WHERE user=? AND practice_mode='match'",
            (USER,)).fetchone()
        assert (log["fr"], log["fin"]) == (2, 2)


def test_match_hits_cap_returns_429(client):
    with patch("backend.idempotency.SCORE_CAPS", TINY_CAPS):
        payload = {"list": "test_words", "answers": _MATCH_ANSWERS}
        for i in range(TINY_CAPS["match"]):
            payload["attempt_id"] = f"m{i}"
            assert _post(client, "/api/match/result", payload).status_code == 200
        payload["attempt_id"] = "m99"
        r = _post(client, "/api/match/result", payload)
        assert r.status_code == 429


# ---------------------------------------------------------------------------
# /api/boss/result
# ---------------------------------------------------------------------------

def test_boss_replay_same_attempt_id_is_deduped(client):
    _seed_boss_wrong(client)
    aid = "b1"
    payload = {"answers": _BOSS_ANSWERS, "attempt_id": aid}

    r1 = _post(client, "/api/boss/result", payload)
    assert r1.status_code == 200 and r1.get_json().get("duplicate") is not True
    assert r1.get_json()["score"] == 1 and r1.get_json()["cleared"] == 1

    # 重放不重复记账、不重复清除
    r2 = _post(client, "/api/boss/result", payload)
    assert r2.status_code == 200 and r2.get_json()["duplicate"] is True
    assert r2.get_json()["score"] == 1

    with db() as conn:
        log = conn.execute(
            "SELECT first_right_count fr FROM daily_practice_log "
            "WHERE user=? AND practice_mode='boss'", (USER,)).fetchone()
        assert log["fr"] == 1


def test_boss_hits_cap_returns_429(client):
    _seed_boss_wrong(client)
    # 全 wrong 答案，避免 boss clearing 副作用污染多轮尝试
    _BOSS_ALL_WRONG = [{"id": "hello", "list": "test_words", "right": False},
                       {"id": "world", "list": "test_words", "right": False}]
    with patch("backend.idempotency.SCORE_CAPS", TINY_CAPS):
        payload = {"answers": _BOSS_ALL_WRONG}
        for i in range(TINY_CAPS["boss"]):
            payload["attempt_id"] = f"b{i}"
            assert _post(client, "/api/boss/result", payload).status_code == 200
        payload["attempt_id"] = "b99"
        r = _post(client, "/api/boss/result", payload)
        assert r.status_code == 429


# ---------------------------------------------------------------------------
# /api/arrange/answer
# ---------------------------------------------------------------------------

def test_arrange_replay_same_attempt_id_is_deduped(client):
    s = client.get(f"/api/arrange/session?list=test_sents&u={USER}").get_json()
    q = next(x for x in s["questions"] if x["id"] == "2")   # "This is a test"
    right_order = [q["chunks"].index(w) for w in ["This", "is", "a", "test"]]

    payload = {
        "list": "test_sents", "id": "2", "order": right_order,
        "attempt_id": "a1",
    }
    r1 = _post(client, "/api/arrange/answer", payload)
    assert r1.status_code == 200 and r1.get_json()["right"] is True
    assert r1.get_json().get("duplicate") is not True

    r2 = _post(client, "/api/arrange/answer", payload)
    assert r2.status_code == 200 and r2.get_json()["duplicate"] is True
    assert r2.get_json()["right"] is True

    with db() as conn:
        log = conn.execute(
            "SELECT final_right_count fin FROM daily_practice_log "
            "WHERE user=? AND practice_mode='arrange'", (USER,)).fetchone()
        assert log["fin"] == 1


def test_arrange_hits_cap_returns_429(client):
    s = client.get(f"/api/arrange/session?list=test_sents&u={USER}").get_json()
    q = next(x for x in s["questions"] if x["id"] == "2")
    right_order = [q["chunks"].index(w) for w in ["This", "is", "a", "test"]]

    with patch("backend.idempotency.SCORE_CAPS", TINY_CAPS):
        payload = {"list": "test_sents", "id": "2", "order": right_order}
        for i in range(TINY_CAPS["arrange"]):
            payload["attempt_id"] = f"a{i}"
            assert _post(client, "/api/arrange/answer", payload).status_code == 200
        payload["attempt_id"] = "a99"
        r = _post(client, "/api/arrange/answer", payload)
        assert r.status_code == 429


# ---------------------------------------------------------------------------
# 老客户端兼容：未传 attempt_id 时照旧记
# ---------------------------------------------------------------------------

def test_legacy_clients_without_attempt_id_still_score(client):
    payload = {
        "list": "test_words", "id": "hello", "mode": "assisted",
        "first_right": True, "final_right": True, "right": True,
        "outcome": "completed",
    }
    for _ in range(3):
        r = _post(client, "/api/result", payload)
        assert r.status_code == 200 and r.get_json().get("duplicate") is not True
    with db() as conn:
        log = conn.execute(
            "SELECT first_right_count fr FROM daily_practice_log "
            "WHERE user=? AND practice_mode='assisted'", (USER,)).fetchone()
        assert log["fr"] == 3
    # 没传 attempt_id 时 score_attempt 表应无记录
    with db() as conn:
        c = conn.execute(
            "SELECT COUNT(*) c FROM score_attempt WHERE user=?",
            (USER,)).fetchone()["c"]
        assert c == 0


# ---------------------------------------------------------------------------
# check_and_mark / mark_done 直接单测
# ---------------------------------------------------------------------------

def test_check_and_mark_returns_expected_status(client):
    with db() as conn:
        assert check_and_mark(conn, USER, "result", "u1") == ("ok", None)
        mark_done(conn, USER, "result", "u1")

    # 同一 attempt_id → duplicate
    with db() as conn:
        status, _ = check_and_mark(conn, USER, "result", "u1")
        assert status == "duplicate"

    # 不同 endpoint 互不影响
    with db() as conn:
        status, _ = check_and_mark(conn, USER, "match", "u1")
        assert status == "ok"
        mark_done(conn, USER, "match", "u1")

    # 不同 user 互不影响
    with db() as conn:
        status, _ = check_and_mark(conn, "x" * 32, "result", "u1")
        assert status == "ok"
