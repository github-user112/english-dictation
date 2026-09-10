"""听读模式接口测试：按课顺序出句、素材与课号校验。"""

USER = "b" * 32


def get(client, path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={USER}")


def test_shadow_lesson_in_order(client):
    r = get(client, "/api/shadow/session?list=test_sents&lesson=1")
    assert r.status_code == 200
    d = r.get_json()
    assert d["total"] == 2
    assert [i["text"] for i in d["items"]] == ["Hello world", "This is a test"]  # 按课原序，不打乱
    assert all(i["audio"] and i["zh"] for i in d["items"])


def test_shadow_without_lesson_returns_all(client):
    d = get(client, "/api/shadow/session?list=test_sents").get_json()
    assert d["total"] == 4


def test_shadow_validation(client):
    assert get(client, "/api/shadow/session?list=test_words").status_code == 400   # 词汇素材不收
    assert get(client, "/api/shadow/session?list=nope").status_code == 404         # 未知素材
    assert get(client, "/api/shadow/session?list=test_sents&lesson=99").status_code == 404
    assert get(client, "/api/shadow/session?list=test_sents&lesson=abc").status_code == 400
