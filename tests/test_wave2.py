"""波2 功能测试：我的文章（自定义素材）与异步冲刺挑战。"""
from backend.db import db


def test_custom_material_lifecycle(client):
    text = "Hello world. This is a test! Is it working? Yes it is."
    r = client.post("/api/materials/custom", json={"title": "Demo", "text": text})
    assert r.status_code == 200
    d = r.get_json()
    mid = d["id"]
    assert d["count"] >= 3 and d["title"] == "Demo"

    lst = client.get("/api/materials/custom").get_json()["items"]
    assert any(x["id"] == mid for x in lst)

    det = client.get(f"/api/materials/custom/{mid}").get_json()
    assert det["title"] == "Demo"
    assert all(s["kind"] == "sentence" and s["text"] for s in det["sentences"])

    assert client.delete(f"/api/materials/custom/{mid}").status_code == 200
    assert client.get(f"/api/materials/custom/{mid}").status_code == 404


def test_custom_material_validation(client):
    # 太短
    assert client.post("/api/materials/custom", json={"text": "hi"}).status_code == 400
    # 切不出 3 句（无句末标点）
    r = client.post("/api/materials/custom", json={"text": "one two three four five"})
    assert r.status_code == 400
    # 非法 body
    assert client.post("/api/materials/custom", data="notjson", content_type="text/plain").status_code in (400, 500)


def test_sprint_challenge_flow(client):
    from datetime import datetime, timedelta, timezone

    def play(cid, right_count):
        """开局 → 回拨时间戳 → 提交答案序列（前 right_count 题答对）。"""
        sid = client.post(f"/api/sprint/challenge/{cid}/start").get_json()["session"]
        with db() as conn:
            conn.execute("UPDATE sprint_session SET started_at=? WHERE id=?",
                         (datetime.now(timezone.utc) - timedelta(seconds=60), sid))
        items = client.get(f"/api/sprint/challenge?id={cid}").get_json()["items"]
        answers = [{"id": it["id"],
                    "typed": "".join(c for c in it["text"] if c.isalpha())
                    if i < right_count else "zzz"}
                   for i, it in enumerate(items)]
        return client.post(f"/api/sprint/challenge/{cid}/score",
                           json={"session": sid, "answers": answers})

    cid = client.post("/api/sprint/challenge?list=test_words").get_json()["id"]
    got = client.get(f"/api/sprint/challenge?id={cid}").get_json()
    assert 1 <= len(got["items"]) <= 40          # 测试素材仅 5 词，抽样封顶
    assert got["owner"]
    assert got["scores"] == []

    first = play(cid, 3).get_json()
    assert first["record"] is True and first["scores"][0]["score"] == 3
    # 更低分不覆盖，record=False
    second = play(cid, 1).get_json()
    assert second["record"] is False and second["scores"][0]["score"] == 3
    # 更高分覆盖
    third = play(cid, 5).get_json()
    assert third["record"] is True and third["scores"][0]["score"] == 5

    # 无会话/错误会话一律拒收；不存在的挑战 404
    assert client.post(f"/api/sprint/challenge/{cid}/score",
                       json={"score": 99}).status_code == 400
    assert client.post("/api/sprint/challenge/nope/score", json={"score": 1}).status_code == 404
    assert client.post("/api/sprint/challenge/nope/start").status_code == 404
    assert client.get("/api/sprint/challenge?id=nope").status_code == 404
