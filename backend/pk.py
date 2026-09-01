"""实时 PK 对战：flask-sock WebSocket + SQLite 权威状态。

部署是 gunicorn 多 worker，两条连接可能落在不同进程，进程内注册表广播
不可靠；因此房间与比分以 SQLite 为唯一权威来源，连接线程用
`ws.receive(timeout)` 的空转节拍驱动推送循环：

- 每个节拍点查一次房间与比分（索引查询，毫秒级）；
- room.version 比上次推送新才下发全量快照，对手进度延迟 ≤ 一个节拍（500ms）；
- 每 25s 强制发一帧业务外心跳，防 nginx 的 30s read timeout 断链。

帧协议（JSON）：
  C→S  {"type":"join"} | {"type":"start"} | {"type":"answer",index,text}
       | {"type":"finish"}
  S→C  {"type":"state", ...}（含 phase/winner/role/items/players；
       进行中的 items 不含答案原文）、{"type":"verdict",index,right}（answer 的
       即时判定回执，客户端凭它推进题序）、{"type":"ping"}、{"type":"gone"}

version 单调递增保证多 worker 下不丢事件；游客身份取 Cookie，前端必须先
请求一次 /api/pk/room/<code> 让身份 Cookie 就位再建立 WS 连接。
"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import Blueprint, request
from flask_sock import Sock
from simple_websocket import ConnectionClosed

from .auth import display_name, get_cookie_identity, resp
from .catalog import now
from .challenge import sprint_items
from .config import MATERIALS
from .db import db

bp = Blueprint("pk", __name__)
sock = Sock()

ITEMS_COUNT = 30            # 一局词流长度，与限时冲刺同款词形
GAME_SECONDS = 60           # 作答窗口
GRACE_SECONDS = 15          # 超时判定宽限：弱网下 finish 帧晚到也算完赛
MIN_ANSWER_SECONDS = 1.0    # 单题流速下限：听音+打字有物理下限，比这个快的作答是脚本
POLL_TICK_SECONDS = 0.5     # 推送轮询周期 = 对手进度的最大可见延迟
HEARTBEAT_SECONDS = 25      # nginx proxy_read_timeout(30s) 内必有一帧流量
FINISHED_LINGER_SECONDS = 20   # 关局后再推送这么久，然后释放长连接线程
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # 去 0O1IL 等易混字符
ROOM_CODE_LEN = 6
WAITING_ROOM_TTL_MINUTES = 60   # 无人再开的等待房清理阈值
FINISHED_ROOM_TTL_DAYS = 7      # 战报可回看窗口


@bp.post("/api/pk/room")
def api_create_room():
    """建一个等待房：同一人的陈旧等待房按上限滚动淘汰。

    座位身份只认 Cookie/会话；走 resp() 把游客 Cookie 在建房时就钉住，
    否则深链进来的访客在 WS 阶段会被当成新身份、顶掉自己的对手座。
    """
    user = get_cookie_identity()
    list_key = request.args.get("list", "cet4")
    if list_key not in MATERIALS or MATERIALS[list_key]["type"] != "words":
        return resp({"error": "实时对战仅支持词汇素材"}, 400, identity=user)
    items = sprint_items(list_key, ITEMS_COUNT)

    with db() as conn:
        _sweep_rooms(conn)
        code = _new_code(conn)
        conn.execute(
            """INSERT INTO pk_room(code, creator, list_key, items, created_at)
               VALUES(?,?,?,?,?)""",
            (code, user["user_id"], list_key, json.dumps(items, ensure_ascii=False), now()))
    return resp({"code": code}, identity=user)


@bp.get("/api/pk/room/<code>")
def api_room_snapshot(code):
    """HTTP 快照兜底：不开 WS 也能看房间状态，兼作断线重连前的预热。

    用 resp() 下发：快照里顺带钉住游客 Cookie，保证随后 WS 握手时
    服务端解析出同一个座位身份；顺手结算超时未收官的对局。
    """
    me = get_cookie_identity()
    with db() as conn:
        room = conn.execute(
            "SELECT state, started_at, version FROM pk_room WHERE code=?",
            (code.upper(),)).fetchone()
        if room is None:
            return resp({"error": "对战房间不存在或已过期"}, 404, identity=me)
        _maybe_autofinish(conn, room)
        snap = _snapshot(conn, code.upper(), viewer=me["user_id"])
    if snap is None:
        return resp({"error": "对战房间不存在或已过期"}, 404, identity=me)
    return resp(snap, identity=me)


def _new_code(conn):
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(ROOM_CODE_LEN))
        if not conn.execute("SELECT 1 FROM pk_room WHERE code=?", (code,)).fetchone():
            return code


def _elapsed_seconds(iso_start):
    """计算经过秒数。兼容旧 naive 本地时间数据（假设为本地时区）。"""
    dt = datetime.fromisoformat(iso_start)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return (datetime.now(timezone.utc).astimezone() - dt).total_seconds()


def _deadline_iso(started_at):
    return (datetime.fromisoformat(started_at) + timedelta(seconds=GAME_SECONDS)).isoformat()


def _sweep_rooms(conn):
    """惰性清扫：超时未关局的强制结算；过期等待房/旧战报删除。"""
    for row in conn.execute(
            "SELECT code, started_at FROM pk_room WHERE state='playing'").fetchall():
        if _elapsed_seconds(row["started_at"]) >= GAME_SECONDS + GRACE_SECONDS:
            _finalize_room(conn, row["code"])
    cutoff_wait = (datetime.now(timezone.utc) - timedelta(minutes=WAITING_ROOM_TTL_MINUTES)).isoformat()
    conn.execute("DELETE FROM pk_room WHERE state='waiting' AND created_at < ?", (cutoff_wait,))
    cutoff_done = (datetime.now(timezone.utc) - timedelta(days=FINISHED_ROOM_TTL_DAYS)).isoformat()
    conn.execute("DELETE FROM pk_room WHERE state='finished' AND finished_at < ?", (cutoff_done,))


def _finalize_room(conn, code):
    """关局并推进 version：所有还挂着进行中的比分一并盖上完成章。"""
    stamp = now()
    conn.execute("UPDATE pk_room SET state='finished', finished_at=?, version=version+1 "
                 "WHERE code=? AND state='playing'", (stamp, code))
    conn.execute("UPDATE pk_result SET finished_at=COALESCE(finished_at, ?) "
                 "WHERE room_code=?", (stamp, code))


def _compute_score(correct):
    """从逐词答案推导 score / combo / answered。combo = 末尾连续正确的个数。

    键是 index 的字符串形式，必须按 int 排序：字典序下 "9" > "29"，11 词以上
    的局连击会被错序截断。
    """
    score = sum(1 for v in correct.values() if v)
    combo = 0
    for idx in sorted(correct, key=int, reverse=True):
        if correct[idx]:
            combo += 1
        else:
            break
    return score, combo, len(correct)


def _upsert_result(conn, code, user, name, score, combo, answered, finished):
    """作答进度的单调合并：乱序/重传帧只会抬高各项数值，不会倒退。"""
    conn.execute(
        """INSERT INTO pk_result(room_code, user, name, score, combo, answered, finished_at)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(room_code, user) DO UPDATE SET
             score=MAX(pk_result.score, excluded.score),
             combo=MAX(pk_result.combo, excluded.combo),
             answered=MAX(pk_result.answered, excluded.answered),
             finished_at=COALESCE(excluded.finished_at, pk_result.finished_at)""",
        (code, user, name, score, combo, answered, now() if finished else None))


def _record_answer(conn, code, user, name, items, index, text):
    """服务端校验一次作答：判分、落 answers JSON、重算 score/combo/answered。

    返回 None 表示忽略（index 非法/已交卷），否则返回本次判定 True/False——
    调用方把它作为 verdict 帧下发给作答者。分数完全由服务端推导。
    答错的词允许重试改分——拼错了再改对是听写游戏的主循环；已答对的词
    重复提交不再写库，但仍回报 True（幂等 verdict：断线重放后能拿回判定）。
    调用方须用 db(immediate=True)，读-改-写在多 worker 下才原子。
    """
    if not isinstance(index, int) or isinstance(index, bool) or not (0 <= index < len(items)):
        return None   # index 越界一律拒收，不 clamp：clamp 会把错帧写进槽位 0
    row = conn.execute(
        "SELECT answers, finished_at FROM pk_result WHERE room_code=? AND user=?",
        (code, user)).fetchone()
    if row and row["finished_at"]:
        return None   # 已交卷的座位不再接收新答案
    try:
        answers = json.loads(row["answers"]) if (row and row["answers"]) else {}
    except (ValueError, TypeError):
        answers = {}
    if answers.get(str(index)) is True:
        return True   # 已答对的词不被翻案；幂等回报判定结果即可
    expected = str(items[index].get("text", ""))
    right = text.strip().lower() == expected.strip().lower()
    answers[str(index)] = right
    score, combo, answered = _compute_score(answers)
    conn.execute(
        """INSERT INTO pk_result(room_code, user, name, score, combo, answered, answers)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(room_code, user) DO UPDATE SET
             score=excluded.score, combo=excluded.combo, answered=excluded.answered,
             answers=excluded.answers""",
        (code, user, name, score, combo, answered,
         json.dumps(answers, ensure_ascii=False)))
    conn.execute("UPDATE pk_room SET version=version+1 WHERE code=?", (code,))
    return right


def _roles(row, me):
    if me == row["creator"]:
        return "creator"
    if me == row["opponent"]:
        return "opponent"
    return "spectator"


def _snapshot(conn, code, viewer=None):
    """房间全量快照：WS 推送与 HTTP 兜底共用一份形状。"""
    row = conn.execute("SELECT * FROM pk_room WHERE code=?", (code,)).fetchone()
    if not row:
        return None
    results = {r["user"]: r for r in conn.execute(
        "SELECT * FROM pk_result WHERE room_code=?", (code,)).fetchall()}
    players = []
    for seat in ("creator", "opponent"):
        uid = row[seat]
        if uid is None:
            continue
        res = results.get(uid)
        players.append({
            "user": uid, "seat": seat, "name": display_name(conn, uid),
            "score": res["score"] if res else 0,
            "combo": res["combo"] if res else 0,
            "answered": res["answered"] if res else 0,
            "finished": bool(res and res["finished_at"]),
        })
    winner = None
    if row["state"] == "finished" and players:
        if len(players) == 1:
            winner = players[0]["user"]   # 单人房完赛即胜，终局战报语义完整
        else:
            first, second = players
            winner = ("draw" if first["score"] == second["score"]
                      else (first["user"] if first["score"] > second["score"] else second["user"]))
    items = json.loads(row["items"])
    if row["state"] != "finished":
        # 答案原文不出服务端：进行中只下发发音/题型，判分用 id 反查，
        # 快照泄词时客户端脚本照抄 text 即可满分的路径就此关闭
        items = [{"id": it["id"], "kind": it["kind"], "audio": it["audio"]} for it in items]
    payload = {
        "type": "state",
        "code": row["code"], "list": row["list_key"], "phase": row["state"],
        "items": items,
        "started_at": row["started_at"],
        "deadline_at": _deadline_iso(row["started_at"]) if row["started_at"] else None,
        "server_now": now(),
        "players": players, "winner": winner,
    }
    if viewer is not None:
        payload["me"] = viewer
        payload["role"] = _roles(row, viewer)
    return payload


def _maybe_autofinish(conn, room):
    """到达作答窗口+宽限仍未关局的房间在此收口。"""
    if room["state"] != "playing":
        return
    if _elapsed_seconds(room["started_at"]) < GAME_SECONDS + GRACE_SECONDS:
        return
    _finalize_room(conn, room["code"])


def _handle_message(code, me, raw):
    """处理一帧客户端消息；answer 帧返回 verdict 负载（由连接线程回发），其余返回 None。"""
    try:
        msg = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(msg, dict):
        return None
    kind = msg.get("type")

    with db(immediate=True) as conn:
        row = conn.execute("SELECT * FROM pk_room WHERE code=?", (code,)).fetchone()
        if row is None:
            return None
        role = _roles(row, me)

        if kind == "start":
            # 双方任一人开局即可：等人不再阻塞，先到的先跑也是公平的同词流
            if role in {"creator", "opponent"} and row["state"] == "waiting":
                conn.execute("UPDATE pk_room SET state='playing', started_at=?, "
                             "version=version+1 WHERE code=?", (now(), code))
            return None

        if kind == "answer":
            # 服务端判分：客户端只报 index+文本，不报任何分数
            if role == "spectator" or row["state"] != "playing":
                return None
            index = msg.get("index")
            # 流速闸门：累计作答数不得超过已流逝时间允许的上限。
            # 听音+打字的物理下限约 1s/题，比这快的批量作答是脚本在灌答案
            elapsed = _elapsed_seconds(row["started_at"])
            done_row = conn.execute(
                "SELECT answered FROM pk_result WHERE room_code=? AND user=?",
                (code, me)).fetchone()
            done = done_row["answered"] if done_row else 0
            if done + 1 > int(elapsed / MIN_ANSWER_SECONDS) + 1:
                return None
            right = _record_answer(conn, code, me, display_name(conn, me),
                                   json.loads(row["items"]), index,
                                   str(msg.get("text", "")))
            if right is None:
                return None
            return {"type": "verdict", "index": index, "right": right}

        if kind != "finish" or role == "spectator":
            return None   # 成绩只认服务端判过的 answer 帧；旧 progress 帧已退役
        if row["state"] != "playing":
            return None   # 未开局或已关局的提交一律忽略
        sealed = conn.execute(
            "SELECT finished_at, score, combo, answered FROM pk_result "
            "WHERE room_code=? AND user=?", (code, me)).fetchone()
        if sealed and sealed["finished_at"]:
            return   # 已交卷的座位不得再改写成绩，迟到的重放帧不能抬高战报
        # 交卷只盖章：分数取服务端从 answers 推导出的列，帧内数字一律不信
        _upsert_result(conn, code, me, display_name(conn, me),
                       sealed["score"] if sealed else 0,
                       sealed["combo"] if sealed else 0,
                       sealed["answered"] if sealed else 0, True)
        conn.execute("UPDATE pk_room SET version=version+1 WHERE code=?", (code,))
        done_count = conn.execute(
            "SELECT COUNT(*) c FROM pk_result WHERE room_code=? AND finished_at IS NOT NULL",
            (code,)).fetchone()["c"]
        seats_taken = 2 if row["opponent"] else 1
        if done_count >= seats_taken:
            _finalize_room(conn, code)


@sock.route("/ws/pk/<code>")
def ws_pk(ws, code):
    """每连接一个线程的推送循环；退化为长轮询语义但省掉全部进程间协调。
    座位身份只认会话/Cookie（get_cookie_identity），URL 参数一律不作为归属依据。"""
    me = get_cookie_identity()["user_id"]
    origin = request.headers.get("Origin")
    if not origin or urlparse(origin).hostname != request.host.split(":")[0]:
        ws.close(reason="origin rejected")
        return

    code = code.upper()
    pushed_version = -1     # 未推送过任何快照
    last_outbound = datetime.now(timezone.utc)
    finalized_seen = False

    def send(payload):
        nonlocal last_outbound
        last_outbound = datetime.now(timezone.utc)
        ws.send(json.dumps(payload, ensure_ascii=False))

    try:
        with db() as conn:
            row = conn.execute("SELECT creator, opponent FROM pk_room WHERE code=?",
                               (code,)).fetchone()
            if row is None:
                ws.close(reason="房间不存在或已过期")
                return
            if me != row["creator"] and row["opponent"] is None:
                conn.execute("UPDATE pk_room SET opponent=?, version=version+1 "
                             "WHERE code=? AND opponent IS NULL",
                             (me, code))

        while True:
            raw = ws.receive(timeout=POLL_TICK_SECONDS)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "ignore")
            if raw:
                verdict = _handle_message(code, me, raw)
                if verdict:
                    send(verdict)   # 判定即时回发：作答反馈延迟 ≈ 1 RTT，不等推送节拍

            with db() as conn:
                room = conn.execute(
                    "SELECT state, started_at, version FROM pk_room WHERE code=?",
                    (code,)).fetchone()
                if room is None:
                    send({"type": "gone", "reason": "房间不存在或已过期"})
                    break
                _maybe_autofinish(conn, room)
                fresh = conn.execute(
                    "SELECT * FROM pk_room WHERE code=?", (code,)).fetchone()
                if fresh["version"] > pushed_version:
                    send(_snapshot(conn, code, viewer=me))
                    pushed_version = fresh["version"]
                    if fresh["state"] == "finished":
                        finalized_seen = True
                        final_push_at = datetime.now(timezone.utc)
                elif (datetime.now(timezone.utc) - last_outbound).total_seconds() >= HEARTBEAT_SECONDS:
                    send({"type": "ping"})
            if finalized_seen:
                linger = (datetime.now(timezone.utc) - final_push_at).total_seconds()
                if linger >= FINISHED_LINGER_SECONDS:
                    break   # 终局快照已送达，释放工作线程给下一个对局
    except ConnectionClosed:
        pass   # 客户端离开/刷新是常态退出路径，无需上报


def init_app(app):
    sock.init_app(app)
