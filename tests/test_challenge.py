"""听音选词 / 限时冲刺接口测试。"""
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
    assert len(d["items"]) == 3
    for item in d["items"]:
        assert item["text"] and item["audio"]
    assert get(client, "/api/sprint/session?list=test_sents").status_code == 400


def test_sprint_best_keeps_maximum(client):
    assert get(client, "/api/sprint/best").get_json()["best"] is None
    first = client.post(f"/api/sprint/best?u={USER}",
                        json={"score": 12, "combo": 5, "total": 15}).get_json()
    assert first["best"]["score"] == 12
    lower = client.post(f"/api/sprint/best?u={USER}",
                        json={"score": 3, "combo": 9, "total": 20}).get_json()
    assert lower["best"]["score"] == 12       # 低分不覆盖，即使连击更高
    higher = client.post(f"/api/sprint/best?u={USER}",
                         json={"score": 20, "combo": 2, "total": 25}).get_json()
    assert higher["best"]["score"] == 20
    assert higher["record"] is True


def test_sprint_best_validates_score(client):
    assert client.post(f"/api/sprint/best?u={USER}", json={"score": -5}).status_code == 400
    assert client.post(f"/api/sprint/best?u={USER}", json={}).status_code == 400
    assert client.post(f"/api/sprint/best?u={USER}", json={"score": "abc"}).status_code == 400
    # bool/float 不是合法成绩（int(True)==1、int(3.9)==3 的隐式转换必须拒绝）
    assert client.post(f"/api/sprint/best?u={USER}", json={"score": True}).status_code == 400
    assert client.post(f"/api/sprint/best?u={USER}", json={"score": 3.9}).status_code == 400


def test_sprint_best_concurrent_writes_keep_high_score(app):
    """并发回归：多线程同一 user 上报高低分混写，最终记录应为历史最高（非最后写入）。

    修复点：challenge.py api_sprint_best_post 使用 BEGIN IMMEDIATE 串行化
    读检查-比较-写入，防止低分最后到达覆盖已存在的高分。
    """
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import uuid

    user = uuid.uuid4().hex
    n = 20
    high, low = 90, 5
    scores = [high if i % 3 == 0 else low for i in range(n)]

    # Flask test client 非线程安全，每个线程独立 client；预先获取 CSRF token 后再在 barrier 后并发
    clients = [CsrfClient(app) for _ in range(n)]
    for cl in clients:
        cl.get("/api/auth/me", headers={"Cookie": f"dict_u={user}"})
    barrier = Barrier(n)

    def hit(cl, s):
        barrier.wait()
        return cl.post(
            f"/api/sprint/best?u={user}",
            json={"score": s, "combo": s, "total": s + 10},
            headers={"Cookie": f"dict_u={user}"}
        )

    with ThreadPoolExecutor(max_workers=max(32, n + 4)) as pool:
        for resp in pool.map(hit, clients, scores):
            assert resp.status_code == 200, resp.json

    with db() as conn:
        row = conn.execute("SELECT score FROM sprint_best WHERE user=?", (user,)).fetchone()
    assert row is not None
    assert row["score"] == high
