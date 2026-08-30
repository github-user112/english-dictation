"""实时 PK 对战：HTTP 房间接口 + 消息状态机 + ws_pk 入口。

flask 测试客户端建不了真实 WebSocket，但 ws_pk 只需要一个会抛
ConnectionClosed 的 stub：它足以穿过 Origin 门禁与座位认领，
推送循环第一次 receive 就退出。真实双端长连接由 gunicorn 冒烟验证。
"""
import json
import uuid
from datetime import datetime, timedelta

from simple_websocket import ConnectionClosed

from backend.config import COOKIE
from backend.db import db
from backend.pk import (FINISHED_ROOM_TTL_DAYS, GAME_SECONDS, GRACE_SECONDS,
                        ROOM_CODE_LEN, WAITING_ROOM_TTL_MINUTES,
                        _compute_score, _finalize_room, _handle_message,
                        _maybe_autofinish, _new_code, _record_answer,
                        _snapshot, _sweep_rooms, _upsert_result)


def snapshot(code, viewer=None):
    """快照便捷封装：开一条临时连接再查，测试体里少一层 with。"""
    with db() as conn:
        return _snapshot(conn, code, viewer=viewer)

A = uuid.uuid4().hex       # 32 位小写十六进制，与游客/账户 id 同形状
B = uuid.uuid4().hex


def now_iso(offset_seconds=0):
    return (datetime.now() + timedelta(seconds=offset_seconds)).isoformat(timespec="seconds")


def new_code():
    with db() as conn:
        return _new_code(conn)


def create_room(client, list_key="test_words", who=A):
    """座位身份只走 Cookie（?u= 已封禁），测试客户端同样带 Cookie 进门。"""
    client.set_cookie(COOKIE, who)
    r = client.post(f"/api/pk/room?list={list_key}")
    assert r.status_code == 200, r.json
    return r.json["code"]


def guest(app, user_id):
    """带指定游客 Cookie 的独立浏览器。"""
    c = app.test_client()
    c.set_cookie(COOKIE, user_id)
    return c


class FakeWs:
    """最小 WS 替身：receive 立即抛 ConnectionClosed 使推送循环退出。"""
    def __init__(self):
        self.sent = []
        self.reason = None

    def send(self, payload):
        self.sent.append(payload)

    def close(self, reason=""):
        self.reason = reason

    def receive(self, timeout=None):
        raise ConnectionClosed()


def open_ws(app, code, origin, user):
    """从 ws_pk 真实入口进门：测的是 Origin 门禁与座位认领，不是断言逻辑本身。

    本仓库的 flask_sock fork 里 @sock.route 返回装饰器而非被装饰的函数，
    模块级 ws_pk 名是 None；从路由表取注册项再走 __wrapped__ 拿回原函数。
    """
    handler = app.view_functions["__flask_sock.ws_pk"].__wrapped__
    headers = [("Cookie", f"{COOKIE}={user}")]
    if origin is not None:
        headers.append(("Origin", origin))
    fake = FakeWs()
    with app.test_request_context(f"/ws/pk/{code}", method="GET", headers=headers):
        handler(fake, code)
    return fake


STREAM = [{"id": str(n), "text": f"w{n}", "kind": "word", "audio": ""} for n in range(5)]


def make_room_direct(state="waiting", opponent=None):
    """绕过 HTTP 造房间：返回 code。"""
    code = new_code()
    with db() as conn:
        conn.execute(
            "INSERT INTO pk_room(code,creator,opponent,list_key,items,state,version,"
            "created_at,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (code, A, opponent, "test_words", json.dumps(STREAM), state, 0, now_iso(),
             now_iso() if state != "waiting" else None,
             now_iso() if state == "finished" else None))
    return code


def seat(code, name="creator"):
    return next(p for p in snapshot(code)["players"] if p["seat"] == name)


def answer(code, user, index, text):
    _handle_message(code, user, json.dumps({"type": "answer", "index": index, "text": text}))


def finish(code, user, **extra):
    _handle_message(code, user, json.dumps({"type": "finish", **extra}))


# ---------------- HTTP 接口 ----------------

def test_create_room_rejects_non_word_and_unknown_material(client):
    client.set_cookie(COOKIE, A)
    assert client.post("/api/pk/room?list=test_sents").status_code == 400
    assert client.post("/api/pk/room?list=nope").status_code == 400
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM pk_room").fetchone()["c"]
    assert n == 0                     # 两笔失败请求都不能留下房间


def test_create_room_returns_shareable_unique_codes(client):
    one, two = create_room(client), create_room(client)
    alphabet = set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
    for code in (one, two):
        assert len(code) == ROOM_CODE_LEN and set(code) <= alphabet   # 口令无易混字符
    assert one != two


def test_snapshot_reports_role_for_viewer_and_guest_names(app, client):
    code = create_room(client)
    snap = guest(app, A).get(f"/api/pk/room/{code.lower()}").json   # 小写口令也认
    assert snap["phase"] == "waiting"
    assert snap["role"] == "creator" and len(snap["items"]) == 5
    assert snap["players"][0]["name"].startswith("游客")
    stranger_view = guest(app, B).get(f"/api/pk/room/{code}").json
    assert stranger_view["role"] == "spectator"
    assert app.test_client().get("/api/pk/room/ZZZZZZ").status_code == 404


def test_identity_comes_from_cookie_never_from_url_param(app):
    """座位归属评审修复：?u= 不再是身份通道，Cookie 缺失即造新身份。"""
    code = make_room_direct()
    # 攻击者拿着房主 A 的 uuid 当 u= 参数来访：既不顶座也不钉成 A
    r = app.test_client().get(f"/api/pk/room/{code}?u={A}")
    assert r.json["user"] != A and r.json["role"] == "spectator"


def test_cold_deeplink_pins_guest_cookie_across_requests(app):
    """无 Cookie 深链：首次快照下发 Cookie，同一浏览器后续请求身份一致。"""
    code = make_room_direct()
    c = app.test_client()
    first = c.get(f"/api/pk/room/{code}")
    set_cookie_header = first.headers.get("Set-Cookie") or ""
    assert COOKIE in set_cookie_header
    pinned_id = first.json["user"]
    second = c.get(f"/api/pk/room/{code}")
    assert second.json["user"] == pinned_id          # 快照预热把身份稳住


# ---------------- ws_pk 入口 ----------------

def test_ws_origin_gate_rejects_mismatched_origin(app):
    code = make_room_direct()
    fake = open_ws(app, code, "https://evil.example", B)
    assert fake.reason == "origin rejected"
    with db() as conn:
        row = conn.execute("SELECT opponent FROM pk_room WHERE code=?", (code,)).fetchone()
    assert row["opponent"] is None          # 被拒的访客没占到对手位


def test_ws_origin_gate_rejects_missing_origin(app):
    code = make_room_direct()
    assert open_ws(app, code, None, B).reason == "origin rejected"


def test_ws_seat_claim_first_comer_wins(app):
    """先到的访客占对手位，后到的同席访客沦为旁观者。"""
    code = make_room_direct()
    open_ws(app, code, "http://localhost", B)
    open_ws(app, code, "http://localhost", "c" * 32)
    with db() as conn:
        row = conn.execute("SELECT opponent FROM pk_room WHERE code=?", (code,)).fetchone()
    assert row["opponent"] == B


# ---------------- 消息驱动的状态机 ----------------

def test_start_only_from_waiting_and_either_seat_may_start(client):
    code = make_room_direct()
    _handle_message(code, A, json.dumps({"type": "start"}))
    snap = snapshot(code)
    assert snap["phase"] == "playing" and snap["deadline_at"]
    started = snap["started_at"]
    _handle_message(code, B, json.dumps({"type": "start"}))     # 二次开局是重放帧，忽略
    assert snapshot(code)["started_at"] == started

    fresh = make_room_direct()
    _handle_message(fresh, B, '{"not-json"}')                   # 干扰帧不炸不越权
    # 没人坐对手位时 B 只是旁观者，无权开局；WS 路径里进房即占位，故先由 A 开
    _handle_message(fresh, B, json.dumps({"type": "start"}))
    assert snapshot(fresh)["phase"] == "waiting"
    _handle_message(fresh, A, json.dumps({"type": "start"}))
    assert snapshot(fresh)["phase"] == "playing"


def test_progress_frame_retired(client):
    """progress 帧已退役：客户端自报进度在任何阶段都不再落库。"""
    code = make_room_direct(opponent=B)
    _handle_message(code, A, json.dumps({"type": "progress", "score": 9, "answered": 9}))
    assert seat(code)["score"] == 0                        # waiting 中提交无效
    _handle_message(code, A, json.dumps({"type": "start"}))
    _handle_message(code, A, json.dumps({"type": "progress", "score": 9, "combo": 9, "answered": 9}))
    s = seat(code)
    assert (s["score"], s["combo"], s["answered"]) == (0, 0, 0)   # playing 中也不再信任


def test_single_player_room_finishes_on_own_finish(client):
    code = new_code()
    with db() as conn:
        conn.execute(
            "INSERT INTO pk_room(code,creator,list_key,items,state,created_at) VALUES(?,?,?,?,?,?)",
            (code, A, "test_words", json.dumps(STREAM[:1]), "waiting", now_iso()))
    _handle_message(code, A, json.dumps({"type": "start"}))
    answer(code, A, 0, STREAM[0]["text"])
    finish(code, A)
    snap = snapshot(code)
    assert snap["phase"] == "finished"
    assert snap["winner"] is None            # 单人自练无胜负，只有成绩
    assert snap["players"][0]["score"] == 1
    assert snap["players"][0]["finished"] is True


def test_answers_alone_do_not_finalize_room(client):
    """答完所有题不再自动关局：收口由前端显式 finish 帧驱动。"""
    code = make_room_direct(state="playing", opponent=None)
    for i in range(len(STREAM)):
        answer(code, A, i, STREAM[i]["text"])
    snap = snapshot(code)
    assert snap["phase"] == "playing"                # 答案不驱动关局
    assert snap["players"][0]["score"] == len(STREAM)
    assert snap["players"][0]["finished"] is False
    finish(code, A)
    assert snapshot(code)["phase"] == "finished"     # 显式交卷才收口


def test_draw_and_winner_determination(client):
    code = make_room_direct(opponent=B)
    _handle_message(code, A, json.dumps({"type": "start"}))
    for user in (A, B):
        answer(code, user, 0, STREAM[0]["text"])
        finish(code, user)
    draw = snapshot(code)
    assert draw["phase"] == "finished" and draw["winner"] == "draw"

    other = make_room_direct(opponent=B)
    _handle_message(other, A, json.dumps({"type": "start"}))
    answer(other, A, 0, STREAM[0]["text"])
    for i in range(len(STREAM)):
        answer(other, B, i, STREAM[i]["text"])
    finish(other, A)
    finish(other, B)
    won = snapshot(other)
    assert won["winner"] == B
    assert [p["seat"] for p in won["players"]] == ["creator", "opponent"]


def test_spectator_frames_never_write_results(client):
    code = make_room_direct(opponent=B)
    _handle_message(code, A, json.dumps({"type": "start"}))
    spectator = uuid.uuid4().hex
    answer(code, spectator, 0, STREAM[0]["text"])
    finish(code, spectator, score=9, answered=9)
    with db() as conn:
        rows = conn.execute("SELECT user FROM pk_result WHERE room_code=?", (code,)).fetchall()
    assert {r["user"] for r in rows} <= {A, B}


def test_upsert_merge_keeps_best_values_and_first_finished_at(client):
    code = make_room_direct()
    with db() as conn:
        _upsert_result(conn, code, A, "游客xx", 10, 5, 12, True)
        _upsert_result(conn, code, A, "游客xx", 4, 2, 8, False)
        row = conn.execute("SELECT * FROM pk_result WHERE room_code=? AND user=?",
                           (code, A)).fetchone()
    assert row["score"] == 10 and row["combo"] == 5 and row["answered"] == 12
    assert row["finished_at"] is not None           # 重传未完赛帧不清掉已盖的完成章


def test_timeout_autofinish_stamps_every_open_seat(client):
    code = make_room_direct(opponent=B, state="playing")
    past = now_iso(-(GAME_SECONDS + GRACE_SECONDS + 30))
    with db() as conn:
        conn.execute("UPDATE pk_room SET started_at=? WHERE code=?", (past, code))
        _upsert_result(conn, code, A, "游客aa", 7, 3, 9, False)   # 只有 A 有进度
        row = conn.execute("SELECT * FROM pk_room WHERE code=?", (code,)).fetchone()
        _maybe_autofinish(conn, row)
        room = conn.execute("SELECT state FROM pk_room WHERE code=?", (code,)).fetchone()
        open_seats = conn.execute(
            "SELECT user FROM pk_result WHERE room_code=? AND finished_at IS NULL",
            (code,)).fetchall()
    assert room["state"] == "finished"
    assert open_seats == []                            # 未主动交卷的一方也被盖完成章
    assert snapshot(code)["phase"] == "finished"


def test_autofinish_ignores_fresh_games(client):
    code = make_room_direct(state="playing")
    with db() as conn:
        row = conn.execute("SELECT * FROM pk_room WHERE code=?", (code,)).fetchone()
        before = row["version"]
        _maybe_autofinish(conn, row)
        after = conn.execute("SELECT version, state FROM pk_room WHERE code=?",
                             (code,)).fetchone()
    assert after["state"] == "playing" and after["version"] == before


def test_finalize_is_idempotent_after_state_advance(client):
    code = make_room_direct(opponent=B, state="playing")
    with db() as conn:
        _finalize_room(conn, code)
        first = conn.execute("SELECT version FROM pk_room WHERE code=?", (code,)).fetchone()
        _finalize_room(conn, code)
        second = conn.execute("SELECT version FROM pk_room WHERE code=?", (code,)).fetchone()
    assert second["version"] == first["version"]       # WHERE state='playing' 使重放成为空操作


def test_sweep_removes_stale_waiting_and_aged_battle_reports(client):
    keep_wait = make_room_direct()
    old_wait = make_room_direct()
    stale_play = make_room_direct(opponent=B, state="playing")
    keep_done = make_room_direct(state="finished")
    aged_done = make_room_direct(state="finished")

    now = datetime.now()
    with db() as conn:
        conn.execute("UPDATE pk_room SET created_at=? WHERE code=?",
                     ((now - timedelta(minutes=WAITING_ROOM_TTL_MINUTES + 5)).isoformat(), old_wait))
        conn.execute("UPDATE pk_room SET started_at=? WHERE code=?",
                     ((now - timedelta(seconds=GAME_SECONDS + GRACE_SECONDS + 90)).isoformat(),
                      stale_play))
        conn.execute("UPDATE pk_room SET finished_at=? WHERE code=?",
                     ((now - timedelta(days=FINISHED_ROOM_TTL_DAYS + 1)).isoformat(), aged_done))
        _sweep_rooms(conn)

    with db() as conn:
        rows = {r["code"]: r["state"] for r in
                conn.execute("SELECT code, state FROM pk_room").fetchall()}
    assert old_wait not in rows                        # 过期等待房被删
    assert aged_done not in rows                       # 过期战报被删
    assert rows[keep_wait] == "waiting"
    assert rows[keep_done] == "finished"
    assert rows[stale_play] == "finished"              # 超时对局先补结算再保留战报


# ---------------- 服务端判分 ----------------

def test_record_answer_correct_increases_score(app):
    """正确作答 → score+1, answered+1"""
    code = make_room_direct(state="playing", opponent=B)
    with db() as conn:
        ok = _record_answer(conn, code, A, "tester", STREAM, 0, STREAM[0]["text"])
    assert ok is True
    with db() as conn:
        row = conn.execute("SELECT score, answered, answers FROM pk_result WHERE room_code=? AND user=?",
                           (code, A)).fetchone()
    assert row["score"] == 1
    assert row["answered"] == 1
    assert json.loads(row["answers"])["0"] is True


def test_record_answer_wrong_no_score_increase(app):
    """错误作答 → score 不变, answered+1"""
    code = make_room_direct(state="playing", opponent=B)
    with db() as conn:
        ok = _record_answer(conn, code, A, "tester", STREAM, 0, "WRONG_ANSWER")
    assert ok is True
    with db() as conn:
        row = conn.execute("SELECT score, answered, answers FROM pk_result WHERE room_code=? AND user=?",
                           (code, A)).fetchone()
    assert row["score"] == 0
    assert row["answered"] == 1
    assert json.loads(row["answers"])["0"] is False


def test_record_answer_wrong_then_retry_scores_correct(app):
    """答错的词可重试改分——拼错了再改对是听写的主循环。"""
    code = make_room_direct(state="playing", opponent=B)
    with db() as conn:
        assert _record_answer(conn, code, A, "t", STREAM, 0, "WRONG") is True
        assert _record_answer(conn, code, A, "t", STREAM, 0, STREAM[0]["text"]) is True
        row = conn.execute("SELECT score, answers FROM pk_result WHERE room_code=? AND user=?",
                           (code, A)).fetchone()
    assert row["score"] == 1
    assert json.loads(row["answers"])["0"] is True


def test_record_answer_duplicate_ignored(app):
    """已答对的词不被后续提交翻案"""
    code = make_room_direct(state="playing", opponent=B)
    with db() as conn:
        ok1 = _record_answer(conn, code, A, "t", STREAM, 0, STREAM[0]["text"])
        ok2 = _record_answer(conn, code, A, "t", STREAM, 0, "DIFFERENT")
    assert ok1 is True
    assert ok2 is False


def test_record_answer_out_of_range_rejected(app):
    """越界 index → 返回 False，不建记录"""
    code = make_room_direct(state="playing", opponent=B)
    with db() as conn:
        ok = _record_answer(conn, code, A, "t", STREAM, 99, "anything")
    assert ok is False
    with db() as conn:
        row = conn.execute("SELECT * FROM pk_result WHERE room_code=? AND user=?",
                           (code, A)).fetchone()
    assert row is None


def test_record_answer_bad_index_never_corrupts_slot_zero(app):
    """index 非真整数时拒收而非 clamp：clamp 会把错帧写进槽位 0。"""
    code = make_room_direct(state="playing", opponent=B)
    for bad in ("0", 1.5, True, -1, len(STREAM), None, [0]):
        with db() as conn:
            assert _record_answer(conn, code, A, "t", STREAM, bad, STREAM[0]["text"]) is False
    with db() as conn:
        row = conn.execute("SELECT * FROM pk_result WHERE room_code=? AND user=?",
                           (code, A)).fetchone()
    assert row is None                    # 全程未污染任何槽位


def test_record_answer_case_insensitive(app):
    """答案大小写不敏感"""
    code = make_room_direct(state="playing", opponent=B)
    with db() as conn:
        ok = _record_answer(conn, code, A, "t", STREAM, 0, STREAM[0]["text"].upper())
    assert ok is True
    with db() as conn:
        row = conn.execute("SELECT score FROM pk_result WHERE room_code=? AND user=?",
                           (code, A)).fetchone()
    assert row["score"] == 1


def test_compute_score_from_answers():
    """从 answers 字典推导 score/combo/answered"""
    answers = {"0": True, "1": False, "2": True, "3": True}
    score, combo, answered = _compute_score(answers)
    assert score == 3      # 3 个正确
    assert combo == 2      # 末尾连续正确 2 个 (index 2,3)
    assert answered == 4   # 共 4 个答案


def test_compute_score_all_wrong():
    """全错时 combo=0"""
    answers = {"0": False, "1": False, "2": False}
    score, combo, answered = _compute_score(answers)
    assert score == 0
    assert combo == 0
    assert answered == 3


def test_compute_score_combo_is_numeric_order():
    """键是字符串 index：字典序下 "9" > "11"，11 词以上的局连击会被错序截断。"""
    answers = {str(i): True for i in range(12)}
    answers["11"] = False
    assert _compute_score(answers) == (11, 0, 12)     # 末词错 → 连击清零
    answers["11"] = True
    assert _compute_score(answers) == (12, 12, 12)    # 全对 → 全程连击


def test_answer_message_updates_score(app):
    """answer 帧 → 服务端校验并更新分数，不驱动关局"""
    code = make_room_direct(state="playing", opponent=B)
    answer(code, A, 0, STREAM[0]["text"])
    seat_a = seat(code)
    assert (seat_a["score"], seat_a["answered"]) == (1, 1)
    assert snapshot(code)["phase"] == "playing"


def test_answer_message_wrong_answer_no_score(app):
    """answer 帧答错 → score 不增加但 answered 增加"""
    code = make_room_direct(state="playing", opponent=B)
    answer(code, A, 0, "WRONG")
    seat_a = seat(code)
    assert (seat_a["score"], seat_a["answered"]) == (0, 1)


def test_spectator_answer_ignored(app):
    """旁观者不能上报答案"""
    code = make_room_direct(state="playing", opponent=B)
    spectator_id = "d" * 32
    answer(code, spectator_id, 0, STREAM[0]["text"])
    with db() as conn:
        row = conn.execute("SELECT * FROM pk_result WHERE room_code=? AND user=?",
                           (code, spectator_id)).fetchone()
    assert row is None


def test_finish_seals_server_computed_score(app):
    """finish 只盖章：分数取服务端判过的 answers，帧内自报数字一律不信。"""
    code = make_room_direct(state="playing", opponent=B)
    answer(code, A, 0, STREAM[0]["text"])
    finish(code, A, score=99999, combo=99999, answered=99999)
    s = seat(code)
    assert (s["score"], s["combo"], s["answered"]) == (1, 1, 1)
    assert s["finished"] is True


def test_finish_without_answers_scores_zero(app):
    """没答过就交卷：成绩归零，不因 finish 帧里的数字而虚高。"""
    code = make_room_direct(state="playing", opponent=B)
    finish(code, A, score=7, answered=7)
    s = seat(code)
    assert (s["score"], s["combo"], s["answered"]) == (0, 0, 0)
    assert s["finished"] is True


def test_sealed_seat_ignores_late_frames(app):
    """交卷后迟到的 answer / finish 重放：不改写成绩，不再抬 version。"""
    code = make_room_direct(state="playing", opponent=B)
    answer(code, A, 0, STREAM[0]["text"])
    finish(code, A)
    with db() as conn:
        before = conn.execute("SELECT version FROM pk_room WHERE code=?", (code,)).fetchone()["version"]
    answer(code, A, 1, STREAM[1]["text"])
    finish(code, A, score=99)
    with db() as conn:
        after = conn.execute("SELECT version FROM pk_room WHERE code=?", (code,)).fetchone()["version"]
    assert after == before
    assert (seat(code)["score"], seat(code)["answered"]) == (1, 1)
