"""AI 错词串记：词集来源 / 缓存命中 / 重生成限流。"""
import json

import backend.ai as ai


def _seed_wrong(client):
    """听打答错两次 → 错词本有词。"""
    for word in ("hello", "world"):
        client.post("/api/memorize", data=json.dumps({"list": "test_words", "id": word, "right": False}),
                    content_type="application/json")
    # memorize 不写 wrong_count；直接落 word_state
    from backend.db import db
    me = client.get("/api/auth/me").get_json()["user"]
    with db() as conn:
        for word in ("hello", "world"):
            conn.execute(
                "UPDATE word_state SET wrong_count=2, last_seen=date('now') "
                "WHERE user=? AND list='test_words' AND item_id=?", (me, word))


def _mock_chat(monkeypatch):
    calls = []
    monkeypatch.setattr(ai, "_chat", lambda prompt: calls.append(prompt) or "A **hello** story.")
    return calls


def test_story_generates_then_caches(client, monkeypatch):
    _seed_wrong(client)
    calls = _mock_chat(monkeypatch)
    d = client.get("/api/ai/story").get_json()
    assert d["cached"] is False and "hello" in d["story"]
    assert set(d["words"]) == {"hello", "world"}
    assert len(calls) == 1
    # 第二遍走缓存，不再调 LLM
    d2 = client.get("/api/ai/story").get_json()
    assert d2["cached"] is True and len(calls) == 1


def test_story_fresh_regenerates_and_is_capped(client, monkeypatch):
    _seed_wrong(client)
    calls = _mock_chat(monkeypatch)
    client.get("/api/ai/story")
    for i in range(ai.FRESH_PER_DAY):
        r = client.get("/api/ai/story?fresh=1")
        assert r.status_code == 200, i
    assert len(calls) == 1 + ai.FRESH_PER_DAY
    r = client.get("/api/ai/story?fresh=1")
    assert r.status_code == 429
    assert len(calls) == 1 + ai.FRESH_PER_DAY   # 超限不再调 LLM


def test_story_requires_wrong_words(client):
    r = client.get("/api/ai/story")
    assert r.status_code == 400


def test_mnemonic_shared_cache(client, app, monkeypatch):
    calls = _mock_chat(monkeypatch)
    d = client.get("/api/ai/mnemonic?list=test_words&id=hello").get_json()
    assert d["cached"] is False and len(calls) == 1

    # 换一个用户：同一词条命中共享缓存，不再调 LLM
    app.test_client_class = type(client)
    other = app.test_client()
    other.get("/api/auth/me")
    d2 = other.get("/api/ai/mnemonic?list=test_words&id=hello").get_json()
    assert d2["cached"] is True and len(calls) == 1
    assert d2["text"] == d["text"]

    r = client.get("/api/ai/mnemonic?list=test_words&id=nope")
    assert r.status_code == 404
