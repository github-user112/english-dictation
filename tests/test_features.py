import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


class FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["ENGLISH_DICTATION_DB"] = str(Path(cls.tmp.name) / "test.db")
        from backend import create_app
        cls.app = create_app()
        cls.app.testing = True

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from backend.config import DB
        from backend.db import init_db
        if DB.exists():
            DB.unlink()
        init_db()
        self.client = self.app.test_client()
        self.user = "a" * 32

    def get(self, path):
        sep = "&" if "?" in path else "?"
        return self.client.get(f"{path}{sep}u={self.user}")

    def post(self, path, data):
        sep = "&" if "?" in path else "?"
        return self.client.post(f"{path}{sep}u={self.user}", json=data)

    def test_user_is_stable_inside_first_request(self):
        r = self.client.get("/api/lists")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json["user"]), 32)
        self.assertIn(r.json["user"], r.headers["Set-Cookie"])

    def test_daily_quota_and_resume(self):
        first = self.get("/api/session?list=cet4&mode=assisted&new=3").json
        second = self.get("/api/session?list=cet4&mode=assisted&new=50").json
        self.assertEqual(first["session"]["id"], second["session"]["id"])
        self.assertEqual([i["id"] for i in first["items"]], [i["id"] for i in second["items"]])
        self.assertEqual(first["quota"]["new_quota"], 3)
        self.assertEqual(first["quota"]["allocated_today"], 3)

    def test_modes_have_independent_sessions(self):
        ids = {mode: self.get(f"/api/session?list=cet4&mode={mode}&new=1").json["session"]["id"]
               for mode in ("pure", "assisted", "follow")}
        self.assertEqual(len(set(ids.values())), 3)

    def test_reviews_do_not_reduce_new_quota(self):
        from backend.db import db
        tomorrow = date.today().isoformat()
        with db() as conn:
            conn.execute("""INSERT INTO word_state(user,list,item_id,kind,status,next_review)
                          VALUES(?,?,?,?,?,?)""",
                         (self.user, "cet4", "abandon", "word", "learning", tomorrow))
        session = self.get("/api/session?list=cet4&mode=pure&new=2").json
        phases = [i["phase"] for i in session["items"]]
        self.assertEqual(phases.count("review"), 1)
        self.assertEqual(phases.count("new"), 2)

    def test_first_answer_and_idempotent_completion(self):
        s = self.get("/api/session?list=cet4&mode=pure&new=1").json
        sid, item = s["session"]["id"], s["items"][0]
        a = self.post("/api/result", {"session_id": sid, "id": item["id"],
            "first_right": False, "final_right": False, "attempt_count": 1,
            "outcome": "attempt"})
        self.assertEqual(a.status_code, 200)
        done = {"session_id": sid, "id": item["id"], "first_right": False,
                "final_right": True, "attempt_count": 2, "outcome": "completed"}
        self.assertFalse(self.post("/api/result", done).json["duplicate"])
        self.assertTrue(self.post("/api/result", done).json["duplicate"])
        stats = self.get("/api/stats").json["practice_modes"]["pure"]
        self.assertEqual((stats["first_right"], stats["first_wrong"], stats["final_right"]), (0, 1, 1))

    def test_follow_does_not_advance_mastery(self):
        s = self.get("/api/session?list=cet4&mode=follow&new=1").json
        item = s["items"][0]
        self.post("/api/result", {"session_id": s["session"]["id"], "id": item["id"],
            "first_right": True, "final_right": True, "attempt_count": 1,
            "outcome": "completed"})
        from backend.db import db
        with db() as conn:
            row = conn.execute("SELECT * FROM word_state WHERE user=? AND item_id=?",
                               (self.user, item["id"])).fetchone()
        self.assertIsNone(row)

    def test_lesson_session_is_ordered_and_filtered(self):
        lessons = self.get("/api/lessons?list=nc1").json["lessons"]
        self.assertEqual(len(lessons), 72)
        session = self.get("/api/session?list=nc1&mode=pure&lesson=2").json
        self.assertTrue(session["items"])
        self.assertTrue(all(i["lesson"] == 2 for i in session["items"]))
        seq = [i["seq"] for i in session["items"]]
        self.assertEqual(seq, sorted(seq))

    def test_duplicate_words_get_unique_ids_and_independent_state(self):
        from backend.catalog import now
        from backend.db import db
        from backend.materials import load_material
        stamp = now()
        quota = len(load_material("cet4"))
        with db() as conn:
            conn.execute("INSERT INTO daily_plan VALUES(?,?,?,?,?,?,?)",
                         (date.today().isoformat(), self.user, "cet4", quota, 0, stamp, stamp))
        s = self.get("/api/session?list=cet4&mode=pure&new=50")
        self.assertEqual(s.status_code, 200)
        ids = [item["id"] for item in s.json["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        by_text = {}
        for item in s.json["items"]:
            by_text.setdefault(item["text"], []).append(item)
        pair = next(items for items in by_text.values() if len(items) > 1)[:2]
        self.assertTrue(any("~2" in item["id"] for item in pair))
        session_id = s.json["session"]["id"]
        for item in pair:
            r = self.post("/api/result", {"session_id": session_id, "id": item["id"],
                "first_right": True, "final_right": True, "attempt_count": 1,
                "outcome": "completed"})
            self.assertEqual(r.status_code, 200)
        with db() as conn:
            rows = conn.execute(
                "SELECT item_id,right_count FROM word_state WHERE user=? AND list=? AND item_id IN (?,?)",
                (self.user, "cet4", pair[0]["id"], pair[1]["id"])).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r["right_count"] == 1 for r in rows))
            conn.execute("UPDATE word_state SET next_review=? WHERE user=? AND list=? AND item_id IN (?,?)",
                         (date.today().isoformat(), self.user, "cet4", pair[0]["id"], pair[1]["id"]))
        review = self.get("/api/session?list=cet4&mode=assisted&new=0").json
        review_ids = {item["id"] for item in review["items"]}
        self.assertIn(pair[0]["id"], review_ids)
        self.assertIn(pair[1]["id"], review_ids)

    def test_review_is_not_returned_before_due_day(self):
        from backend.db import db
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with db() as conn:
            conn.execute("""INSERT INTO word_state(user,list,item_id,kind,status,next_review)
                          VALUES(?,?,?,?,?,?)""",
                         (self.user, "cet4", "abandon", "word", "learning", tomorrow))
        session = self.get("/api/session?list=cet4&mode=pure&new=0").json
        self.assertFalse(any(i["id"] == "abandon" for i in session["items"]))

    def test_skipped_does_not_count_wrong_or_reset_memorized(self):
        from backend.db import db
        item_id = "abandon"
        with db() as conn:
            conn.execute("""INSERT INTO word_state(user,list,item_id,kind,status,wrong_count,
                          right_count,consecutive_right,last_seen,next_review,memorized,
                          memorize_count,last_memorize) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (self.user, "cet4", item_id, "word", "known", 2, 5, 3,
                          date.today().isoformat(), date.today().isoformat(), 1, 2,
                          date.today().isoformat()))
        s = self.get("/api/session?list=cet4&mode=assisted&new=0").json
        item = next(i for i in s["items"] if i["id"] == item_id)
        r = self.post("/api/result", {"session_id": s["session"]["id"], "id": item["id"],
            "first_right": False, "final_right": False, "attempt_count": 1,
            "outcome": "skipped"})
        self.assertEqual(r.status_code, 200)
        with db() as conn:
            state = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                                 (self.user, "cet4", item_id)).fetchone()
            daily = conn.execute("SELECT * FROM daily_log WHERE day=? AND user=?",
                                 (date.today().isoformat(), self.user)).fetchone()
            mode = conn.execute("SELECT * FROM daily_practice_log WHERE day=? AND user=? "
                                "AND practice_mode='assisted'",
                                (date.today().isoformat(), self.user)).fetchone()
        self.assertEqual((state["wrong_count"], state["status"], state["consecutive_right"]),
                         (2, "known", 3))
        self.assertEqual((state["memorized"], state["memorize_count"]), (1, 2))
        self.assertEqual(daily["wrong_count"], 0)
        self.assertEqual((mode["first_wrong_count"], mode["skipped_count"]), (0, 1))

    def test_skipped_new_and_legacy_item_have_no_learning_side_effects(self):
        from backend.db import db
        s = self.get("/api/session?list=cet4&mode=pure&new=1").json
        item = s["items"][0]
        r = self.post("/api/result", {"session_id": s["session"]["id"], "id": item["id"],
            "first_right": False, "final_right": False, "attempt_count": 1,
            "outcome": "skipped"})
        self.assertEqual(r.status_code, 200)
        late_attempt = self.post("/api/result", {"session_id": s["session"]["id"],
            "id": item["id"], "first_right": False, "attempt_count": 1,
            "outcome": "attempt"})
        self.assertTrue(late_attempt.json["duplicate"])
        legacy = self.post("/api/result", {"list": "cet4", "id": "abandon",
            "right": False, "attempt_count": 1, "outcome": "skipped", "mode": "pure"})
        self.assertEqual(legacy.status_code, 200)
        with db() as conn:
            skipped_row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                                       (self.user, "cet4", item["id"])).fetchone()
            legacy_row = conn.execute("SELECT * FROM word_state WHERE user=? AND list=? AND item_id=?",
                                      (self.user, "cet4", "abandon")).fetchone()
            session_item = conn.execute("""SELECT first_right,state FROM study_session_item
                                          WHERE session_id=? AND item_id=?""",
                                        (s["session"]["id"], item["id"])).fetchone()
            mode = conn.execute("SELECT * FROM daily_practice_log WHERE day=? AND user=? "
                                "AND practice_mode='pure'",
                                (date.today().isoformat(), self.user)).fetchone()
        self.assertIsNone(skipped_row)
        self.assertIsNone(legacy_row)
        self.assertEqual((session_item["state"], session_item["first_right"]), ("skipped", None))
        self.assertEqual((mode["first_wrong_count"], mode["skipped_count"]), (0, 2))

    def test_invalid_numeric_inputs_return_400(self):
        for n in ("bad", "0", "101"):
            r = self.get(f"/api/memorize/session?list=cet4&n={n}")
            self.assertEqual(r.status_code, 400)
            self.assertIn("error", r.json)
        for n in ("1", "100"):
            r = self.get(f"/api/memorize/session?list=cet4&n={n}")
            self.assertEqual(r.status_code, 200)
        s = self.get("/api/session?list=cet4&mode=pure&new=1").json
        for attempt_count in ("bad", 0, -1):
            r = self.post("/api/result", {"session_id": s["session"]["id"],
                "id": s["items"][0]["id"], "attempt_count": attempt_count, "outcome": "attempt"})
            self.assertEqual(r.status_code, 400)
            self.assertIn("error", r.json)
        r = self.post("/api/result", {"session_id": s["session"]["id"],
            "id": s["items"][0]["id"], "attempt_count": 1, "outcome": "skip"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.json)

    def test_wrong_page_persists_anonymous_user_cookie(self):
        first = self.client.get("/api/wrong")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.json["user"]), 32)
        self.assertIn(first.json["user"], first.headers["Set-Cookie"])
        second = self.client.get("/api/wrong")
        self.assertEqual(second.json["user"], first.json["user"])

    def test_assets_are_served_from_vite_output(self):
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        html = index.get_data(as_text=True)
        index.close()
        asset = html.split('src="/assets/', 1)[1].split('"', 1)[0]
        response = self.client.get(f"/assets/{asset}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_data())
        response.close()


if __name__ == "__main__":
    unittest.main()
