"""波2 功能测试：我的文章（自定义素材）与异步冲刺挑战。"""


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
    cid = client.post("/api/sprint/challenge?list=test_words").get_json()["id"]
    got = client.get(f"/api/sprint/challenge?id={cid}").get_json()
    assert 1 <= len(got["items"]) <= 40          # 测试素材仅 5 词，抽样封顶
    assert got["owner"]
    assert got["scores"] == []

    first = client.post(f"/api/sprint/challenge/{cid}/score",
                        json={"score": 10, "combo": 5, "total": 12}).get_json()
    assert first["record"] is True and first["scores"][0]["score"] == 10
    # 更低分不覆盖，record=False
    second = client.post(f"/api/sprint/challenge/{cid}/score",
                         json={"score": 4, "combo": 9, "total": 6}).get_json()
    assert second["record"] is False and second["scores"][0]["score"] == 10
    # 更高分覆盖
    third = client.post(f"/api/sprint/challenge/{cid}/score",
                        json={"score": 20, "combo": 1, "total": 22}).get_json()
    assert third["record"] is True and third["scores"][0]["score"] == 20

    # 非法分数与不存在的挑战
    assert client.post(f"/api/sprint/challenge/{cid}/score", json={"score": -1}).status_code == 400
    assert client.post("/api/sprint/challenge/nope/score", json={"score": 1}).status_code == 404
    assert client.get("/api/sprint/challenge?id=nope").status_code == 404
