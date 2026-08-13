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

    def test_review_is_not_returned_before_due_day(self):
        s = self.get("/api/session?list=cet4&mode=assisted&new=1").json
        item = s["items"][0]
        self.post("/api/result", {"session_id": s["session"]["id"], "id": item["id"],
            "first_right": False, "final_right": False, "attempt_count": 1,
            "outcome": "skipped"})
        from backend.db import db
        with db() as conn:
            row = conn.execute("SELECT next_review FROM word_state WHERE user=? AND item_id=?",
                               (self.user, item["id"])).fetchone()
        self.assertEqual(row["next_review"], (date.today() + timedelta(days=1)).isoformat())
        another = self.get("/api/session?list=cet4&mode=pure&new=0").json
        self.assertFalse(any(i["id"] == item["id"] for i in another["items"]))


if __name__ == "__main__":
    unittest.main()
