"""每日挑战「今日词力」接口测试：确定性出题与服务端判分。"""
from datetime import date

from backend.db import db

USER = "b" * 32
USER2 = "c" * 32


def get(client, path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={USER}")


def _all_right(client, list_key="test_words"):
    """拉当日题组并构造全对提交。"""
    d = get(client, f"/api/daily?list={list_key}").get_json()
    return d, [{"id": q["id"], "picked": q["id"]} for q in d["questions"]]


def test_daily_same_day_same_list_identical_for_everyone(client):
    a = client.get(f"/api/daily?list=test_words&u={USER}").get_json()
    b = client.get(f"/api/daily?list=test_words&u={USER2}").get_json()
    assert a["questions"] == b["questions"]
    again = get(client, "/api/daily?list=test_words").get_json()
    assert again["questions"] == a["questions"]


def test_daily_shape_and_options(client):
    d = get(client, "/api/daily?list=test_words").get_json()
    assert d["day"] == date.today().isoformat()
    assert 2 <= d["total"] <= 10
    assert len(d["questions"]) == d["total"]
    assert d["completed"] is False and d["my_result"] is None
    for q in d["questions"]:
        assert q["kind"] in {"audio_en", "en_zh", "zh_en"}
        assert q["audio"] and q["text"]     # playWord 靠 text 拼真人发音 URL
        assert q["id"] in {o["id"] for o in q["options"]}
        texts = [o["text"] for o in q["options"]]
        assert len(set(texts)) == len(texts)   # 同文异 id 的选项不能同时出现


def test_daily_targets_are_deduped_by_text(client):
    # 素材 5 词条去重后只有 4 个唯一文本；hello 与 hello~2 不能各出一题
    d = get(client, "/api/daily?list=test_words").get_json()
    assert d["total"] == 4
    assert len({q["text"] for q in d["questions"]}) == 4


def test_daily_rejects_sentence_and_unknown_list(client):
    assert get(client, "/api/daily?list=test_sents").status_code == 400
    assert get(client, "/api/daily?list=nope").status_code == 404


def test_daily_result_scores_perfect_run_once(client):
    d, answers = _all_right(client)
    r = client.post(f"/api/daily/result?u={USER}",
                    json={"list": d["list"], "answers": answers})
    assert r.status_code == 200
    body = r.get_json()
    assert body["duplicate"] is False
    assert body["score"] == body["total"] == d["total"]
    assert [x["id"] for x in body["detail"]] == [q["id"] for q in d["questions"]]
    assert all(x["right"] for x in body["detail"])
    # 全对 4 题：10×4 经验，且完成情况已回填到个人档案
    assert body["profile"]["xp"] == 10 * d["total"]
    assert body["profile"]["daily_done_today"] is True

    # 听打统计口径不受污染：每日挑战不写 daily_log / word_state（与 quiz/sprint 一致）
    with db() as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM daily_log WHERE user=?", (USER,)).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM word_state WHERE user=?", (USER,)).fetchone()["c"] == 0

    # 当天再战不再计分：POST 幂等返回首成绩，GET 标记已完成
    again = client.post(f"/api/daily/result?u={USER}",
                        json={"list": d["list"], "answers": answers}).get_json()
    assert again["duplicate"] is True
    assert again["score"] == body["score"]
    d2 = get(client, "/api/daily?list=test_words").get_json()
    assert d2["completed"] is True and d2["my_result"]["score"] == body["score"]


def test_daily_result_grading_is_server_side(client):
    d = get(client, "/api/daily?list=test_words").get_json()
    answers = []
    for q in d["questions"]:
        wrong = next(o for o in q["options"] if o["id"] != q["id"])
        answers.append({"id": q["id"], "picked": wrong["id"]})
    r = client.post(f"/api/daily/result?u={USER}",
                    json={"list": d["list"], "answers": answers}).get_json()
    assert r["score"] == 0
    assert all(x["right"] is False for x in r["detail"])
    # 全错也拿"努力分"：每题 2 点经验
    assert r["profile"]["xp"] == 2 * d["total"]


def test_daily_result_validates_answers(client):
    d, answers = _all_right(client)
    url = f"/api/daily/result?u={USER}"
    assert client.post(url, json={"list": "nope", "answers": answers}).status_code == 400
    assert client.post(url, json={"list": d["list"], "answers": "x"}).status_code == 400
    assert client.post(url, json={"list": d["list"], "answers": []}).status_code == 400
    # 缺题、未知题目、重复作答同一题都要拒
    assert client.post(url, json={"list": d["list"], "answers": answers[:-1]}).status_code == 400
    assert client.post(url, json={"list": d["list"], "answers": answers + [answers[0]]}).status_code == 400
    ghost = [{"id": "ghost-word", "picked": answers[0]["picked"]}] * d["total"]
    assert client.post(url, json={"list": d["list"], "answers": ghost}).status_code == 400
    # picked 必须是真实选项的字符串 id（数字/布尔一律拒）
    bad_type = [{"id": q["id"], "picked": 1} for q in d["questions"]]
    assert client.post(url, json={"list": d["list"], "answers": bad_type}).status_code == 400
    foreign = [{"id": q["id"], "picked": q["id"]} for q in d["questions"]]
    foreign[0] = {"id": foreign[0]["id"], "picked": "not-an-option"}
    assert client.post(url, json={"list": d["list"], "answers": foreign}).status_code == 400


def test_daily_result_stores_canonical_order(client):
    d, answers = _all_right(client)
    r = client.post(f"/api/daily/result?u={USER}", json={
        "list": d["list"], "answers": list(reversed(answers))}).get_json()
    # 乱序提交不影响存储次序：分享网格对所有用户呈现一致的题目顺序
    assert [x["id"] for x in r["detail"]] == [q["id"] for q in d["questions"]]
    assert r["score"] == d["total"]


def test_daily_result_mints_identity_without_cookies(client):
    _, answers = _all_right(client)
    r = client.post("/api/daily/result",
                    json={"list": "test_words", "answers": answers})
    assert r.status_code == 200
    assert r.get_json()["duplicate"] is False


def test_daily_practice_rounds_deal_fresh_questions(client):
    off = get(client, "/api/daily?list=test_words").get_json()
    p1 = get(client, "/api/daily?list=test_words&r=1").get_json()
    # 练习局：另一批题（小词库表现为换序/换题型/换干扰项）、不计成绩
    assert p1["practice"] is True and p1["completed"] is False and p1["my_result"] is None
    assert [q["id"] for q in p1["questions"]] != [q["id"] for q in off["questions"]]
    # 同一轮次确定性重放，不同轮次不同题
    again = get(client, "/api/daily?list=test_words&r=1").get_json()
    assert again["questions"] == p1["questions"]
    p2 = get(client, "/api/daily?list=test_words&r=2").get_json()
    assert [q["id"] for q in p2["questions"]] != [q["id"] for q in p1["questions"]]
    # 非法轮次回退正式局
    assert get(client, "/api/daily?list=test_words&r=abc").get_json()["practice"] is False


def test_daily_practice_never_touches_official_score(client):
    d, answers = _all_right(client)
    client.post(f"/api/daily/result?u={USER}", json={"list": d["list"], "answers": answers})
    # 正式局已完成；练习局照常出题且不携带正式成绩
    pr = get(client, "/api/daily?list=test_words&r=5").get_json()
    assert pr["practice"] is True and pr["my_result"] is None
    off = get(client, "/api/daily?list=test_words").get_json()
    assert off["completed"] is True and off["practice"] is False
    # 正式成绩不被练习局覆盖：仍是最初那次
    assert off["my_result"]["score"] == off["total"]
