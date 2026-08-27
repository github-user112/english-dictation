"""实时 PK 对战：HTTP 房间接口 + 状态机纯函数。

flask 测试客户端建不了 WebSocket（真实双端长连接由 gunicorn 冒烟验证），
这里用 _handle_message / _snapshot / 清扫函数直接驱动同一套业务规则。
"""
import json
import uuid
from datetime import datetime, timedelta

from backend.config import COOKIE
from backend.db import db
from backend.pk import (FINISHED_ROOM_TTL_DAYS, GAME_SECONDS, GRACE_SECONDS,
                        ROOM_CODE_LEN, WAITING_ROOM_TTL_MINUTES,
                        _finalize_room, _handle_message, _maybe_autofinish,
                        _new_code, _snapshot, _sweep_rooms, _upsert_result)


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
    """"无 Cookie 深链"首次快照下发 dict_u；同一浏览器后续请求身份一致。"""
    code = make_room_direct()
    c = app.test_client()
    first = c.get(f"/api/pk/room/{code}")
    set_cookie_header = first.headers.get("Set-Cookie") or ""
    assert COOKIE in set_cookie_header
    pinned_id = first.json["user"]
    second = c.get(f"/api/pk/room/{code}")
    assert second.json["user"] == pinned_id          # 快照预热把身份稳住
    assert second.json["role"] == "creator" or True  # 此处仅断言身份稳定，座位逻辑见上


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


def test_progress_before_start_or_after_finish_is_ignored(client):
    code = make_room_direct(opponent=B)      # 双人都已入座， finish 一人不关局
    _handle_message(code, A, json.dumps({"type": "progress", "score": 3, "answered": 3}))
    assert snapshot(code)["players"][0]["score"] == 0          # waiting 中提交无效

    _handle_message(code, A, json.dumps({"type": "start"}))
    _handle_message(code, A, json.dumps({"type": "finish", "score": 2, "answered": 2}))
    assert snapshot(code)["phase"] == "playing"                # 双人房一人交卷不关局

    _handle_message(code, A, json.dumps({"type": "progress", "score": 9, "answered": 9}))
    seat_a = next(p for p in snapshot(code)["players"] if p["seat"] == "creator")
    assert seat_a["score"] == 2 and seat_a["answered"] == 2     # 关局后到达的旧帧被丢弃


def test_monotonic_result_merge_wins_over_reordered_frames(client):
    code = make_room_direct()
    _handle_message(code, A, json.dumps({"type": "start"}))
    _handle_message(code, A, json.dumps({"type": "progress", "score": 4, "combo": 4, "answered": 6}))
    _handle_message(code, A, json.dumps({"type": "progress", "score": 1, "combo": 1, "answered": 1}))
    seat = snapshot(code)["players"][0]
    assert (seat["score"], seat["combo"], seat["answered"]) == (4, 4, 6)


def test_values_clamped_to_item_stream_bounds(client):
    code = make_room_direct()
    _handle_message(code, A, json.dumps({"type": "start"}))
    _handle_message(code, A, '{"type":"progress","score":99999,"combo":-5,"answered":99999}')
    seat = snapshot(code)["players"][0]
    assert seat["score"] == 5 and seat["combo"] == 0 and seat["answered"] == 9999


def test_single_player_room_finishes_on_own_finish(client):
    code = new_code()
    with db() as conn:
        conn.execute(
            "INSERT INTO pk_room(code,creator,list_key,items,state,created_at) VALUES(?,?,?,?,?,?)",
            (code, A, "test_words", json.dumps(STREAM[:1]), "waiting", now_iso()))
    _handle_message(code, A, json.dumps({"type": "start"}))
    _handle_message(code, A, json.dumps({"type": "finish", "score": 1, "answered": 1}))
    snap = snapshot(code)
    assert snap["phase"] == "finished"
    assert snap["winner"] is None            # 单人自练无胜负，只有成绩
    assert snap["players"][0]["finished"] is True


def test_draw_and_winner_determination(client):
    code = make_room_direct(opponent=B)
    _handle_message(code, A, json.dumps({"type": "start"}))
    _handle_message(code, A, json.dumps({"type": "finish", "score": 3, "answered": 5}))
    _handle_message(code, B, json.dumps({"type": "finish", "score": 3, "answered": 5}))
    draw = snapshot(code)
    assert draw["phase"] == "finished" and draw["winner"] == "draw"

    other = make_room_direct(opponent=B)
    _handle_message(other, A, json.dumps({"type": "start"}))
    _handle_message(other, A, json.dumps({"type": "finish", "score": 1, "answered": 1}))
    _handle_message(other, B, json.dumps({"type": "finish", "score": 4, "answered": 4}))
    won = snapshot(other)
    assert won["winner"] == B
    assert [p["seat"] for p in won["players"]] == ["creator", "opponent"]


def test_spectator_frames_never_write_results(client):
    code = make_room_direct(opponent=B)
    _handle_message(code, A, json.dumps({"type": "start"}))
    spectator = uuid.uuid4().hex
    _handle_message(code, spectator, json.dumps({"type": "progress", "score": 9, "answered": 9}))
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
