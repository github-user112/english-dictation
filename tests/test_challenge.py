"""听音选词 / 限时冲刺接口测试。"""
from datetime import datetime, timedelta, timezone

from flask.testing import FlaskClient

from backend.db import db

USER = "b" * 32


class CsrfClient(FlaskClient):
    """并发测试用：写请求自动携带 dict_csrf cookie 中的 token。"""
    def open(self, *args, **kwargs):
        method = kwargs.get("method", "GET").upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = self.get_cookie("dict_csrf")
            if token:
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("X-CSRF-Token", token.value)
                kwargs["headers"] = headers
        return super().open(*args, **kwargs)


def get(client, path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={USER}")


def test_quiz_session_builds_options_with_answer(client):
    d = get(client, "/api/quiz/session?list=test_words&n=4").get_json()
    assert d["total"] == 4
    for q in d["questions"]:
        assert len(q["options"]) == 4
        assert len({o["id"] for o in q["options"]}) == 4
        assert q["id"] in {o["id"] for o in q["options"]}
        assert q["audio"]
        assert q["text"]    # playWord 需要 text 拼真人发音 URL
        target = next(o for o in q["options"] if o["id"] == q["id"])
        assert target["text"] == q["text"]


def test_quiz_session_caps_at_material_size(client):
    d = get(client, "/api/quiz/session?list=test_words&n=30").get_json()
    assert d["total"] == 5  # 测试素材共 5 个词条（含重名去重后的 hello~2）


def test_quiz_options_have_distinct_texts(client):
    # 回归：hello 与 hello~2 文本相同，干扰项不能与目标同文，选项间也不能重复
    d = get(client, "/api/quiz/session?list=test_words&n=30").get_json()
    for q in d["questions"]:
        texts = [o["text"] for o in q["options"]]
        assert len(set(texts)) == len(texts)
        assert texts.count(q["text"]) == 1


def test_quiz_session_prioritizes_due_reviews(client):
    with db() as conn:
        conn.execute(
            "INSERT INTO word_state(user,list,item_id,kind,status,next_review) "
            "VALUES(?,?,?,?,?,?)",
            (USER, "test_words", "apple", "word", "learning", "2000-01-01"))
    d = get(client, "/api/quiz/session?list=test_words&n=1").get_json()
    assert d["questions"][0]["id"] == "apple"


def test_quiz_session_rejects_sentence_material(client):
    assert get(client, "/api/quiz/session?list=test_sents").status_code == 400


def test_quiz_kind_en_zh_options_are_distinct_meanings(client):
    d = get(client, "/api/quiz/session?list=test_words&n=5&kind=en_zh").get_json()
    assert d["kind"] == "en_zh"
    for q in d["questions"]:
        meanings = [o["meaning"] for o in q["options"]]
        assert len(set(meanings)) == len(meanings)   # 释义互不相同，无双正确项
        assert all(meanings)                          # 选项必须带释义


def test_quiz_kind_zh_en_passthrough_and_default(client):
    d = get(client, "/api/quiz/session?list=test_words&n=1&kind=zh_en").get_json()
    assert d["kind"] == "zh_en"
    assert d["questions"][0]["kind"] == "zh_en"
    assert get(client, "/api/quiz/session?list=test_words&n=1").get_json()["kind"] == "audio_en"
    assert get(client, "/api/quiz/session?list=test_words&n=1&kind=bogus").status_code == 400


def test_quiz_session_unknown_list(client):
    assert get(client, "/api/quiz/session?list=nope").status_code == 404


def test_sprint_session_returns_random_words(client):
    d = get(client, "/api/sprint/session?list=test_words&n=3").get_json()
    assert d["session"]
    assert len(d["items"]) == 3
    for item in d["items"]:
        assert item["text"] and item["audio"]
    assert get(client, "/api/sprint/session?list=test_sents").status_code == 400


def _letters(text):
    return "".join(c for c in text if c.isalpha())


def _play_and_finish(client, user, right_count, n=5, backdate_seconds=60):
    """走一遍完整冲刺流程：会话 → 开局 → 提交答案序列（前 right_count 题答对）。

    用 UPDATE 回拨 started_at 模拟打满 60s，避免测试真等一分钟。
    """
    d = client.get(f"/api/sprint/session?list=test_words&n={n}&u={user}").get_json()
    sid = d["session"]
    assert client.post(f"/api/sprint/session/start?u={user}",
                       json={"session": sid}).status_code == 200
    with db() as conn:
        conn.execute(
            "UPDATE sprint_session SET started_at=? WHERE id=?",
            (datetime.now(timezone.utc) - timedelta(seconds=backdate_seconds), sid))
    answers = [
        {"id": it["id"], "typed": _letters(it["text"]) if i < right_count else "zzz"}
        for i, it in enumerate(d["items"])
    ]
    return client.post(f"/api/sprint/best?u={user}",
                       json={"session": sid, "answers": answers})


def test_sprint_best_keeps_maximum(client):
    assert get(client, "/api/sprint/best").get_json()["best"] is None
    first = _play_and_finish(client, USER, 3).get_json()
    assert first["score"] == 3 and first["best"]["score"] == 3
    lower = _play_and_finish(client, USER, 1).get_json()
    assert lower["best"]["score"] == 3        # 低分不覆盖
    higher = _play_and_finish(client, USER, 5).get_json()
    assert higher["best"]["score"] == 5
    assert higher["record"] is True


def test_sprint_best_rejects_client_asserted_score(client):
    """成绩伪造回归：不带会话直接断言分数一律拒收。"""
    assert client.post(f"/api/sprint/best?u={USER}",
                       json={"score": 999, "combo": 999}).status_code == 404
    assert client.post(f"/api/sprint/best?u={USER}", json={}).status_code == 404
    # 不存在的会话 id
    assert client.post(f"/api/sprint/best?u={USER}",
                       json={"session": "f" * 32, "answers": []}).status_code == 404


def test_sprint_best_rejects_rushed_finish(client):
    """时长闸门：开局后不足 55s 就交卷的成绩无效。"""
    d = get(client, "/api/sprint/session?list=test_words&n=3").get_json()
    sid = d["session"]
    client.post(f"/api/sprint/session/start?u={USER}", json={"session": sid})
    answers = [{"id": it["id"], "typed": _letters(it["text"])} for it in d["items"]]
    r = client.post(f"/api/sprint/best?u={USER}", json={"session": sid, "answers": answers})
    assert r.status_code == 400
    # 未开局就交卷同样拒收
    d2 = get(client, "/api/sprint/session?list=test_words&n=3").get_json()
    r2 = client.post(f"/api/sprint/best?u={USER}",
                     json={"session": d2["session"], "answers": answers})
    assert r2.status_code == 400


def test_sprint_best_rejects_foreign_items_and_replay(client):
    """答案必须对得上会话词流；同一会话不能结算两次。"""
    r = _play_and_finish(client, USER, 2)
    assert r.status_code == 200
    d = get(client, "/api/sprint/session?list=test_words&n=3").get_json()
    sid = d["session"]
    client.post(f"/api/sprint/session/start?u={USER}", json={"session": sid})
    with db() as conn:
        conn.execute("UPDATE sprint_session SET started_at=? WHERE id=?",
                     (datetime.now(timezone.utc) - timedelta(seconds=60), sid))
    bad = client.post(f"/api/sprint/best?u={USER}",
                      json={"session": sid, "answers": [{"id": "zzz-not-in-pool", "typed": "x"}]})
    assert bad.status_code == 400
    # 正常结算后重放同一会话 → 409
    ok = client.post(f"/api/sprint/best?u={USER}", json={
        "session": sid,
        "answers": [{"id": it["id"], "typed": _letters(it["text"])} for it in d["items"]]})
    assert ok.status_code == 200
    replay = client.post(f"/api/sprint/best?u={USER}", json={
        "session": sid,
        "answers": [{"id": it["id"], "typed": _letters(it["text"])} for it in d["items"]]})
    assert replay.status_code == 409


def test_sprint_best_concurrent_writes_keep_high_score(app):
    """并发回归：多线程同一 user 各玩一局同时结算，最终记录应为历史最高。"""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import uuid

    user = uuid.uuid4().hex
    n = 12
    high_n, low_n = 5, 1   # 5 题词流：全对 vs 只对 1 题

    clients = [CsrfClient(app) for _ in range(n)]
    sessions = []
    for cl in clients:
        cl.get("/api/auth/me", headers={"Cookie": f"dict_u={user}"})
        d = cl.get(f"/api/sprint/session?list=test_words&n=5&u={user}").get_json()
        cl.post(f"/api/sprint/session/start?u={user}", json={"session": d["session"]})
        sessions.append(d)
    with db() as conn:
        for d in sessions:
            conn.execute("UPDATE sprint_session SET started_at=? WHERE id=?",
                         (datetime.now(timezone.utc) - timedelta(seconds=60), d["session"]))
    barrier = Barrier(n)

    def hit(cl, d, right_count):
        barrier.wait()
        return cl.post(
            f"/api/sprint/best?u={user}",
            json={"session": d["session"], "answers": [
                {"id": it["id"], "typed": _letters(it["text"]) if i < right_count else "zzz"}
                for i, it in enumerate(d["items"])]},
            headers={"Cookie": f"dict_u={user}"}
        )

    with ThreadPoolExecutor(max_workers=max(32, n + 4)) as pool:
        results = pool.map(lambda args: hit(*args),
                           [(cl, d, high_n if i % 3 == 0 else low_n)
                            for i, (cl, d) in enumerate(zip(clients, sessions))])
        for resp in results:
            assert resp.status_code == 200, resp.json

    with db() as conn:
        row = conn.execute("SELECT score FROM sprint_best WHERE user=?", (user,)).fetchone()
    assert row is not None
    assert row["score"] == high_n
