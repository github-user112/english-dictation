"""英中配对消消乐接口测试：发牌去重、战果记账不碰记忆状态。"""
import random

from backend.db import db

USER = "b" * 32


def get(client, path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={USER}")


def test_match_session_deals_distinct_words(client):
    random.seed(7)
    body = get(client, "/api/match/session?list=test_words").get_json()
    assert body["list"] == "test_words"
    assert body["total"] == 4   # 素材 5 词条去重后只有 4 个唯一文本
    texts = [i["text"] for i in body["items"]]
    assert len(set(texts)) == len(texts)
    for it in body["items"]:
        assert it["meaning"] and it["audio"].startswith("/audio/")
        assert set(it) >= {"id", "text", "phonetic", "meaning", "audio", "list"}


def test_match_session_n_clamp_and_errors(client):
    # 词库只有 4 个词：n 再大也只发 4 对
    assert get(client, "/api/match/session?list=test_words&n=12").get_json()["total"] == 4
    assert get(client, "/api/match/session?list=test_sents").status_code == 400
    assert get(client, "/api/match/session?list=nope").status_code == 404


def test_match_result_scores_and_keeps_word_state_untouched(client):
    answers = [{"id": "hello", "right": True}, {"id": "world", "right": False},
               {"id": "apple", "right": True}]
    r = client.post(f"/api/match/result?u={USER}",
                    json={"list": "test_words", "answers": answers})
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 3 and body["perfect"] == 2
    # 经验口径：首配即中 10×2 + 配错 2×1 = 22（与 boss 同款系数）
    assert body["profile"]["xp"] == 22

    with db() as conn:
        log = conn.execute(
            "SELECT first_right_count fr,first_wrong_count fw,final_right_count fin "
            "FROM daily_practice_log WHERE user=? AND practice_mode='match'",
            (USER,)).fetchone()
        assert (log["fr"], log["fw"], log["fin"]) == (2, 1, 2)
        # 纯识别玩法不动记忆状态、不计听打
        assert conn.execute(
            "SELECT COUNT(*) c FROM word_state WHERE user=?", (USER,)).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM daily_log WHERE user=?", (USER,)).fetchone()["c"] == 0

    # 同日再玩累计进同一桶
    client.post(f"/api/match/result?u={USER}",
                json={"list": "test_words", "answers": [{"id": "abandon", "right": True}]})
    with db() as conn:
        log = conn.execute(
            "SELECT first_right_count fr,final_right_count fin FROM daily_practice_log "
            "WHERE user=? AND practice_mode='match'", (USER,)).fetchone()
        assert (log["fr"], log["fin"]) == (3, 3)


def test_match_result_rejects_forged_or_malformed_answers(client):
    ok = lambda answers, lst="test_words": client.post(  # noqa: E731
        f"/api/match/result?u={USER}", json={"list": lst, "answers": answers}).status_code
    # 不属于该词库的 id → 拒；重复 → 拒；right 非严格布尔 → 拒；句子库/未知库 → 拒
    assert ok([{"id": "ghost-x", "right": True}]) == 400
    assert ok([{"id": "hello", "right": True}, {"id": "hello", "right": True}]) == 400
    assert ok([{"id": "hello", "right": 1}]) == 400
    assert ok([{"id": "hello", "right": "yes"}]) == 400
    assert ok([{"id": "hello"}]) == 400
    assert ok(["hello"]) == 400
    assert ok([]) == 400
    big = [{"id": "hello", "right": True}] * 13
    assert ok(big) == 400
    assert ok([{"id": "1", "right": True}], lst="test_sents") == 400
    assert ok([{"id": "hello", "right": True}], lst="nope") == 404
    assert client.post(f"/api/match/result?u={USER}", data="not json",
                       content_type="application/json").status_code == 400
    # 以上全部被拒后没有任何记账
    with db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM daily_practice_log WHERE user=? AND practice_mode='match'",
            (USER,)).fetchone()["c"] == 0
