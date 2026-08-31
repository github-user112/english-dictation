from datetime import date, timedelta


def get(client, path, user="a" * 32):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={user}")


def post(client, path, data, user="a" * 32):
    sep = "&" if "?" in path else "?"
    return client.post(f"{path}{sep}u={user}", json=data)


def test_user_is_stable_inside_first_request(client):
    response = client.get("/api/lists")
    assert response.status_code == 200
    assert len(response.json["user"]) == 32
    assert response.json["user"] in response.headers["Set-Cookie"]


def test_daily_quota_and_resume(client):
    first = get(client, "/api/session?list=test_words&mode=assisted&new=3").json
    second = get(client, "/api/session?list=test_words&mode=assisted&new=50").json
    assert first["session"]["id"] == second["session"]["id"]
    assert [item["id"] for item in first["items"]] == [item["id"] for item in second["items"]]
    assert first["quota"]["new_quota"] == 3
    assert first["quota"]["allocated_today"] == 3


def test_modes_have_independent_sessions(client):
    ids = {
        mode: get(client, f"/api/session?list=test_words&mode={mode}&new=1").json["session"]["id"]
        for mode in ("pure", "assisted", "follow")
    }
    assert len(set(ids.values())) == 3


def test_reviews_do_not_reduce_new_quota(client):
    from backend.db import db

    with db() as conn:
        conn.execute("""INSERT INTO word_state(user,list,item_id,kind,status,next_review)
                      VALUES(?,?,?,?,?,?)""",
                     ("a" * 32, "test_words", "abandon", "word", "learning", date.today().isoformat()))
    session = get(client, "/api/session?list=test_words&mode=pure&new=2").json
    phases = [item["phase"] for item in session["items"]]
    assert phases.count("review") == 1
    assert phases.count("new") == 2


def test_first_answer_and_idempotent_completion(client):
    session = get(client, "/api/session?list=test_words&mode=pure&new=1").json
    session_id, item = session["session"]["id"], session["items"][0]
    attempt = post(client, "/api/result", {
        "session_id": session_id, "id": item["id"], "first_right": False,
        "final_right": False, "attempt_count": 1, "outcome": "attempt",
    })
    assert attempt.status_code == 200
    done = {"session_id": session_id, "id": item["id"], "first_right": False,
            "final_right": True, "attempt_count": 2, "outcome": "completed"}
    assert post(client, "/api/result", done).json["duplicate"] is False
    assert post(client, "/api/result", done).json["duplicate"] is True
    stats = get(client, "/api/stats").json["practice_modes"]["pure"]
    assert (stats["first_right"], stats["first_wrong"], stats["final_right"]) == (0, 1, 1)


def test_follow_does_not_advance_mastery(client):
    session = get(client, "/api/session?list=test_words&mode=follow&new=1").json
    item = session["items"][0]
    post(client, "/api/result", {
        "session_id": session["session"]["id"], "id": item["id"],
        "first_right": True, "final_right": True, "attempt_count": 1, "outcome": "completed",
    })
    from backend.db import db
    with db() as conn:
        row = conn.execute("SELECT * FROM word_state WHERE user=? AND item_id=?",
                           ("a" * 32, item["id"])).fetchone()
    assert row is None


def test_completed_results_schedule_reviews_with_fsrs(client):
    """FSRS 调度：首答对 → 约 4 天；连对增长；答错收缩到 1 天；状态机不变。"""
    from backend.catalog import now
    from backend.db import db
    # FSRS-4.5 黄金值：同日连续首答对时 r=1，官方增长式末项 (e^{w9(1-r)}-1)=0，
    # 稳定性必须停在初始值 W[2]=3.7145、间隔恒 4 天。
    # 若回归成漏 "-" 的旧式，同日重复会把稳定性按 ~1.69 倍连乘（间隔漂到 6/8/240+ 天）。
    expected_intervals = {1: 4, 2: 4, 3: 4}
    init_good_stability = 3.7145
    cases = ((1, "learning", True), (2, "learning", True), (3, "known", True))
    for consecutive, (expected_consecutive, status, first_right) in enumerate(cases, 1):
        session_id = f"schedule-{consecutive}"
        stamp = now()
        with db() as conn:
            conn.execute("INSERT INTO study_session VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (session_id, "a" * 32, "test_words", "pure", "all", "daily", None,
                          date.today().isoformat(), 0, "active", stamp, stamp, None))
            conn.execute("""INSERT INTO study_session_item(session_id,seq,item_id,kind,phase)
                          VALUES(?,?,?,?,?)""",
                         (session_id, 0, "abandon", "word", "review" if consecutive > 1 else "new"))
        response = post(client, "/api/result", {
            "session_id": session_id, "id": "abandon", "first_right": first_right,
            "final_right": True, "attempt_count": 1, "outcome": "completed",
        })
        assert response.status_code == 200
        with db() as conn:
            row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                               ("a" * 32, "test_words", "abandon")).fetchone()
        assert (row["consecutive_right"], row["status"]) == (expected_consecutive, status)
        assert abs(row["stability"] - init_good_stability) < 1e-3   # 同日复习零增长
        assert row["next_review"] == (
            date.today() + timedelta(days=expected_intervals[consecutive])).isoformat()


def test_fsrs_wrong_answer_shortens_interval(client):
    from backend.catalog import now
    from backend.db import db

    session_id = "schedule-wrong"
    stamp = now()
    with db() as conn:
        conn.execute("INSERT INTO study_session VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (session_id, "a" * 32, "test_words", "pure", "all", "daily", None,
                      date.today().isoformat(), 0, "active", stamp, stamp, None))
        conn.execute("INSERT INTO study_session_item(session_id,seq,item_id,kind,phase) VALUES(?,?,?,?,?)",
                     (session_id, 0, "apple", "word", "new"))
    resp = post(client, "/api/result", {
        "session_id": session_id, "id": "apple", "first_right": False,
        "final_right": False, "attempt_count": 2, "outcome": "completed",
        "typed": "aple",
    })
    assert resp.status_code == 200
    with db() as conn:
        row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                           ("a" * 32, "test_words", "apple")).fetchone()
    assert row["next_review"] == (date.today() + timedelta(days=1)).isoformat()
    # 错拼已随结果入库，供易混词挖掘
    with db() as conn:
        typed = conn.execute("SELECT last_typed FROM study_session_item WHERE session_id=?",
                             (session_id,)).fetchone()["last_typed"]
    assert typed == "aple"


def test_lesson_session_is_ordered_and_filtered(client):
    lessons = get(client, "/api/lessons?list=test_sents").json["lessons"]
    assert len(lessons) == 2
    session = get(client, "/api/session?list=test_sents&mode=pure&lesson=2").json
    assert session["items"]
    assert all(item["lesson"] == 2 for item in session["items"])
    seq = [item["seq"] for item in session["items"]]
    assert seq == sorted(seq)


def test_lesson_sessions_resume_only_in_the_same_mode(client):
    first = get(client, "/api/session?list=test_sents&mode=pure&lesson=2").json
    same_mode = get(client, "/api/session?list=test_sents&mode=pure&lesson=2").json
    assert first["session"]["id"] == same_mode["session"]["id"]
    assert [item["id"] for item in first["items"]] == [item["id"] for item in same_mode["items"]]

    assisted = get(client, "/api/session?list=test_sents&mode=assisted&lesson=2").json
    follow = get(client, "/api/session?list=test_sents&mode=follow&lesson=2").json
    assert len({first["session"]["id"], assisted["session"]["id"], follow["session"]["id"]}) == 3
    assert assisted["session"]["practice_mode"] == "assisted"
    assert follow["session"]["practice_mode"] == "follow"

    session_id, item = first["session"]["id"], first["items"][0]
    assert post(client, "/api/result", {
        "session_id": session_id, "id": item["id"], "first_right": True,
        "final_right": True, "attempt_count": 1, "outcome": "completed",
    }).status_code == 200
    resumed = get(client, "/api/session?list=test_sents&mode=pure&lesson=2").json
    assert resumed["session"]["id"] == session_id
    assert all(candidate["id"] != item["id"] for candidate in resumed["items"])

    for candidate in list(resumed["items"]):
        post(client, "/api/result", {
            "session_id": session_id, "id": candidate["id"], "first_right": True,
            "final_right": True, "attempt_count": 1, "outcome": "completed",
        })
    restarted = get(client, "/api/session?list=test_sents&mode=pure&lesson=2").json
    assert restarted["session"]["id"] != session_id
    assert restarted["items"][0]["id"] == first["items"][0]["id"]


def test_duplicate_words_get_unique_ids_and_independent_state(client):
    session = get(client, "/api/session?list=test_words&mode=pure&new=50").json
    ids = [item["id"] for item in session["items"]]
    assert len(ids) == len(set(ids))
    by_text = {}
    for item in session["items"]:
        by_text.setdefault(item["text"], []).append(item)
    pair = next(items for items in by_text.values() if len(items) > 1)[:2]
    assert any("~2" in item["id"] for item in pair)

    session_id = session["session"]["id"]
    for item in pair:
        assert post(client, "/api/result", {
            "session_id": session_id, "id": item["id"], "first_right": True,
            "final_right": True, "attempt_count": 1, "outcome": "completed",
        }).status_code == 200

    from backend.db import db
    with db() as conn:
        rows = conn.execute(
            "SELECT item_id,right_count FROM word_state WHERE user=? AND list=? AND item_id IN (?,?)",
            ("a" * 32, "test_words", pair[0]["id"], pair[1]["id"]),
        ).fetchall()
        assert len(rows) == 2
        assert all(row["right_count"] == 1 for row in rows)
        conn.execute("UPDATE word_state SET next_review=? WHERE user=? AND list=? AND item_id IN (?,?)",
                     (date.today().isoformat(), "a" * 32, "test_words", pair[0]["id"], pair[1]["id"]))
    review = get(client, "/api/session?list=test_words&mode=assisted&new=0").json
    review_ids = {item["id"] for item in review["items"]}
    assert pair[0]["id"] in review_ids
    assert pair[1]["id"] in review_ids


def test_review_is_not_returned_before_due_day(client):
    from backend.db import db

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    with db() as conn:
        conn.execute("""INSERT INTO word_state(user,list,item_id,kind,status,next_review)
                      VALUES(?,?,?,?,?,?)""",
                     ("a" * 32, "test_words", "abandon", "word", "learning", tomorrow))
    session = get(client, "/api/session?list=test_words&mode=pure&new=0").json
    assert not any(item["id"] == "abandon" for item in session["items"])


def test_skipped_does_not_count_wrong_or_reset_memorized(client):
    from backend.db import db

    with db() as conn:
        conn.execute("""INSERT INTO word_state(user,list,item_id,kind,status,wrong_count,
                      right_count,consecutive_right,last_seen,next_review,memorized,
                      memorize_count,last_memorize) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     ("a" * 32, "test_words", "abandon", "word", "known", 2, 5, 3,
                      date.today().isoformat(), date.today().isoformat(), 1, 2, date.today().isoformat()))
    session = get(client, "/api/session?list=test_words&mode=assisted&new=0").json
    item = next(item for item in session["items"] if item["id"] == "abandon")
    response = post(client, "/api/result", {
        "session_id": session["session"]["id"], "id": item["id"], "first_right": False,
        "final_right": False, "attempt_count": 1, "outcome": "skipped",
    })
    assert response.status_code == 200
    with db() as conn:
        state = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                             ("a" * 32, "test_words", "abandon")).fetchone()
        daily = conn.execute("SELECT * FROM daily_log WHERE day=? AND user=?",
                             (date.today().isoformat(), "a" * 32)).fetchone()
        mode = conn.execute("SELECT * FROM daily_practice_log WHERE day=? AND user=? AND practice_mode='assisted'",
                            (date.today().isoformat(), "a" * 32)).fetchone()
    assert (state["wrong_count"], state["status"], state["consecutive_right"]) == (2, "known", 3)
    assert (state["memorized"], state["memorize_count"]) == (1, 2)
    assert (daily["review_count"], daily["wrong_count"]) == (1, 0)
    assert (mode["review_count"], mode["first_wrong_count"], mode["skipped_count"]) == (1, 0, 1)


def test_skipped_new_and_legacy_item_have_no_learning_side_effects(client):
    from backend.db import db

    session = get(client, "/api/session?list=test_words&mode=pure&new=1").json
    item = session["items"][0]
    assert post(client, "/api/result", {
        "session_id": session["session"]["id"], "id": item["id"], "first_right": False,
        "final_right": False, "attempt_count": 1, "outcome": "skipped",
    }).status_code == 200
    late_attempt = post(client, "/api/result", {
        "session_id": session["session"]["id"], "id": item["id"], "first_right": False,
        "attempt_count": 1, "outcome": "attempt",
    })
    assert late_attempt.json["duplicate"] is True
    legacy = post(client, "/api/result", {
        "list": "test_words", "id": "abandon", "right": False, "attempt_count": 1,
        "outcome": "skipped", "mode": "pure",
    })
    assert legacy.status_code == 200
    with db() as conn:
        skipped_row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                                   ("a" * 32, "test_words", item["id"])).fetchone()
        legacy_row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                                  ("a" * 32, "test_words", "abandon")).fetchone()
        session_item = conn.execute("""SELECT first_right,state FROM study_session_item
                                      WHERE session_id=? AND item_id=?""",
                                    (session["session"]["id"], item["id"])).fetchone()
        daily = conn.execute("SELECT * FROM daily_log WHERE day=? AND user=?",
                             (date.today().isoformat(), "a" * 32)).fetchone()
        mode = conn.execute("SELECT * FROM daily_practice_log WHERE day=? AND user=? AND practice_mode='pure'",
                            (date.today().isoformat(), "a" * 32)).fetchone()
    assert skipped_row is None
    assert legacy_row is None
    assert (session_item["state"], session_item["first_right"]) == ("skipped", None)
    assert (daily["new_count"], daily["wrong_count"]) == (1, 0)
    assert (mode["new_count"], mode["review_count"], mode["first_wrong_count"], mode["skipped_count"]) == (1, 1, 0, 2)


def test_invalid_numeric_inputs_return_400(client):
    for number in ("bad", "0", "101"):
        response = get(client, f"/api/memorize/session?list=test_words&n={number}")
        assert response.status_code == 400
        assert "error" in response.json
    for number in ("1", "100"):
        assert get(client, f"/api/memorize/session?list=test_words&n={number}").status_code == 200
    session = get(client, "/api/session?list=test_words&mode=pure&new=1").json
    for attempt_count in ("bad", 0, -1):
        response = post(client, "/api/result", {
            "session_id": session["session"]["id"], "id": session["items"][0]["id"],
            "attempt_count": attempt_count, "outcome": "attempt",
        })
        assert response.status_code == 400
        assert "error" in response.json
    response = post(client, "/api/result", {
        "session_id": session["session"]["id"], "id": session["items"][0]["id"],
        "attempt_count": 1, "outcome": "skip",
    })
    assert response.status_code == 400


def test_wrong_page_persists_anonymous_user_cookie(client):
    first = client.get("/api/wrong")
    assert first.status_code == 200
    assert len(first.json["user"]) == 32
    assert first.json["user"] in first.headers["Set-Cookie"]
    second = client.get("/api/wrong")
    assert second.json["user"] == first.json["user"]


def test_assets_are_served_from_test_static_output(client):
    index = client.get("/")
    assert index.status_code == 200
    asset = index.get_data(as_text=True).split('src="/assets/', 1)[1].split('"', 1)[0]
    response = client.get(f"/assets/{asset}")
    assert response.status_code == 200
    assert response.get_data()


def test_completed_requires_both_results(client):
    """completed 缺作答结果会落成 0：ghost 错答进 daily_log.wrong_count，
    但 update_word_state 被 None 挡下——四处口径对不上，须直接拒掉。"""
    from backend.db import db

    session = get(client, "/api/session?list=test_words&mode=pure&new=1").json
    session_id, item = session["session"]["id"], session["items"][0]["id"]
    for payload in ({"outcome": "completed"}, {"outcome": "completed", "final_right": True}):
        response = post(client, "/api/result", {"session_id": session_id, "id": item, **payload})
        assert response.status_code == 400, response.json
    with db() as conn:
        row = conn.execute("SELECT state FROM study_session_item WHERE session_id=? AND item_id=?",
                           (session_id, item)).fetchone()
    assert row["state"] == "pending"
    done = {"session_id": session_id, "id": item, "first_right": False,
            "final_right": True, "attempt_count": 2, "outcome": "completed"}
    assert post(client, "/api/result", done).json["duplicate"] is False


def test_result_bool_fields_must_be_real_booleans(client):
    session = get(client, "/api/session?list=test_words&mode=pure&new=1").json
    session_id, item = session["session"]["id"], session["items"][0]["id"]
    for field in ("right", "first_right", "final_right"):
        for bad in (1, 0, "yes", "", 2.5):
            response = post(client, "/api/result", {
                "session_id": session_id, "id": item, field: bad, "outcome": "attempt",
            })
            assert response.status_code == 400, (field, bad, response.json)
            assert field in response.json["error"]
