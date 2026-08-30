"""错词 Boss 战接口测试：集结最痛的词、斩落清出、记账不碰记忆状态。"""
from backend.db import db

USER = "b" * 32


def get(client, path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={USER}")


def _seed_wrong(rows):
    """rows: [(list, item_id, wrong_count)]，last_seen 随序递增以便排序可断言。"""
    with db() as conn:
        for i, (list_key, item_id, wc) in enumerate(rows):
            conn.execute(
                "INSERT INTO word_state(user,list,item_id,wrong_count,last_seen) "
                "VALUES(?,?,?,?,?)",
                (USER, list_key, item_id, wc, f"2026-08-{10 + i:02d}T10:00:00"))


def test_boss_session_orders_most_wrong_first_and_dedupes(client):
    # hello 与 hello~2 同文：只保留 wrong_count 更高的那个
    _seed_wrong([("test_words", "hello", 5), ("test_words", "hello~2", 9),
                 ("test_words", "world", 3), ("test_words", "apple", 2),
                 ("test_words", "abandon", 1)])
    body = get(client, "/api/boss/session").get_json()
    assert body["total"] == 4
    assert [i["text"] for i in body["items"]] == ["hello", "world", "apple", "abandon"]
    top = body["items"][0]
    assert top["wrong_count"] == 9 and top["id"] == "hello~2"
    for it in body["items"]:
        assert it["list"] == "test_words"
        assert it["phonetic"].startswith("/") or it["phonetic"] == ""
        assert it["audio"].startswith("/audio/")
    # hello 有真人音频文件（conftest 里按 md5 落盘）
    assert body["items"][0]["audio"].endswith(".mp3")


def test_boss_session_n_clamp(client):
    _seed_wrong([("test_words", "world", 4), ("test_words", "apple", 3),
                 ("test_words", "abandon", 2), ("test_words", "hello", 1)])
    assert get(client, "/api/boss/session?n=2").get_json()["total"] == 3   # 下限钳到 3
    assert get(client, "/api/boss/session").get_json()["total"] == 4      # 默认 8
    assert get(client, "/api/boss/session?n=999").get_json()["total"] == 4  # 钳到 30 但只有 4
    assert get(client, "/api/boss/session?n=0").get_json()["total"] == 3   # 下限钳到 3
    assert get(client, "/api/boss/session?n=abc").get_json()["total"] == 4  # 非法回默认


def test_boss_session_skips_ghost_rows_and_filters_list(client):
    _seed_wrong([("test_words", "world", 5), ("test_words", "ghost-x", 9),
                 ("other_words", "apple", 7)])
    body = get(client, "/api/boss/session").get_json()
    assert [i["text"] for i in body["items"]] == ["world"]   # 幽灵行与缺素材库都被滤掉
    focused = get(client, "/api/boss/session?list=test_words").get_json()
    assert [i["text"] for i in focused["items"]] == ["world"]
    assert get(client, "/api/boss/session?list=test_sents").status_code == 400
    assert get(client, "/api/boss/session?list=nope").status_code == 404


def test_boss_result_clears_slain_words_only(client):
    _seed_wrong([("test_words", "hello", 6), ("test_words", "world", 4),
                 ("test_words", "apple", 2)])
    answers = [{"id": "hello", "list": "test_words", "right": True},
               {"id": "world", "list": "test_words", "right": False},
               {"id": "apple", "list": "test_words", "right": True}]
    r = client.post(f"/api/boss/result?u={USER}", json={"answers": answers})
    assert r.status_code == 200
    body = r.get_json()
    assert body["score"] == 2 and body["total"] == 3
    assert body["cleared"] == 2 and body["wrong_remaining"] == 1
    # 经验口径：答对 10×2 + 打空 2×1 = 22
    assert body["profile"]["xp"] == 22

    with db() as conn:
        rows = {r["item_id"]: r for r in conn.execute(
            "SELECT item_id,wrong_count,status,right_count,next_review FROM word_state "
            "WHERE user=?", (USER,)).fetchall()}
        assert rows["hello"]["wrong_count"] == 0 and rows["hello"]["status"] == "new"
        assert rows["hello"]["next_review"] is None
        assert rows["apple"]["wrong_count"] == 0 and rows["apple"]["status"] == "new"
        # 未斩落的词保持原样，且不虚增 right_count（boss 不动记忆状态）
        assert rows["world"]["wrong_count"] == 4
        assert all(r["right_count"] == 0 for r in rows.values())
        log = conn.execute(
            "SELECT first_right_count fr,first_wrong_count fw,final_right_count fin "
            "FROM daily_practice_log WHERE user=? AND practice_mode='boss'",
            (USER,)).fetchone()
        assert (log["fr"], log["fw"], log["fin"]) == (2, 1, 2)

    # 全歼后 Boss 无兵可点
    followup = client.post(f"/api/boss/result?u={USER}",
                           json={"answers": [{"id": "world", "list": "test_words", "right": True}]})
    assert followup.get_json()["wrong_remaining"] == 0
    assert get(client, "/api/boss/session").get_json()["total"] == 0


def test_boss_result_rejects_forged_or_malformed_answers(client):
    _seed_wrong([("test_words", "hello", 3), ("test_words", "world", 1)])
    ok = lambda answers: client.post(  # noqa: E731
        f"/api/boss/result?u={USER}", json={"answers": answers}).status_code
    L = "test_words"
    # 素材里存在但不在错词本 → 拒；重复 id → 拒；right 非严格布尔 → 拒
    assert ok([{"id": "abandon", "list": L, "right": True}]) == 400
    assert ok([{"id": "hello", "list": L, "right": True},
               {"id": "hello", "list": L, "right": True}]) == 400
    assert ok([{"id": "hello", "list": L, "right": 1}]) == 400
    assert ok([{"id": "hello", "list": L, "right": "yes"}]) == 400
    assert ok([{"id": "hello", "list": L}]) == 400
    assert ok(["hello"]) == 400
    assert ok([]) == 400
    assert client.post(f"/api/boss/result?u={USER}",
                       json={}).status_code == 400
    assert client.post(f"/api/boss/result?u={USER}", data="not json",
                       content_type="application/json").status_code == 400
    big = [{"id": "hello", "list": L, "right": True}] * 61
    assert ok(big) == 400
    # 以上全部被拒后错词本分毫未动
    with db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM word_state WHERE user=? AND wrong_count>0",
            (USER,)).fetchone()["c"] == 2
