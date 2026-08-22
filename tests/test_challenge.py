"""听音选词 / 限时冲刺接口测试。"""
from backend.db import db

USER = "b" * 32


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
        target = next(o for o in q["options"] if o["id"] == q["id"])
        assert target["text"]


def test_quiz_session_caps_at_material_size(client):
    d = get(client, "/api/quiz/session?list=test_words&n=30").get_json()
    assert d["total"] == 5  # 测试素材共 5 个词条（含重名去重后的 hello~2）


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
