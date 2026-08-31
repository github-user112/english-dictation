"""好友系统：申请/通过/删除、按用户名搜索、共同动态流。

仅登录账户可参与：游客身份是无凭据的 Cookie UUID，随时会换新，
挂不上稳定的社交关系；动态与关系的写入统一在此模块做游客短路。

关系存储规范化为 (user_a < user_b) 单行，杜绝 A→B 与 B→A 并存；
pending 方向由 requested_by 记忆，对方主动申请时自动转为已通过。
"""
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from .auth import (authenticated, display_names, get_user, now_iso, resp,
                   valid_user_id)
from .db import db
from .profile import LEVELS, derive_profile, level_of, xp_of

bp = Blueprint("friends", __name__)


# 动态流保留窗口：过期行在每次写入时顺带清理，_feed 查询量因此有上界
ACTIVITY_TTL_DAYS = 14
FRIENDS_MAX = 100          # 好友数量上限：防关系表被单账号无界膨胀
SEARCH_LIMIT = 20


def escape_like(q):
    """把用户输入转成字面 LIKE 模式：%/_ 无通配语义，避免借搜索枚举用户名。

    好友与小组搜索共用；SQL 侧需配套 ESCAPE '\\'。
    """
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _pair(me, other):
    """规范化成 (小, 大)；同串即自加，返回 None 让调用方拒绝。"""
    if me == other:
        return None
    return (me, other) if me < other else (other, me)


def at_friends_cap(conn, user_id):
    """已接受的好友数是否已达上限。申请/通过/邀请共用这一份口径，避免各写一份漂移。"""
    return conn.execute(
        "SELECT COUNT(*) c FROM friend_relation "
        "WHERE (user_a=? OR user_b=?) AND status='accepted'", (user_id, user_id)).fetchone()["c"] >= FRIENDS_MAX


def _relation_state(row, me):
    """把规范化行翻译成以我为视角的状态。"""
    if row is None:
        return "none"
    if row["status"] == "accepted":
        return "friends"
    return "incoming" if row["requested_by"] != me else "outgoing"


def _require_auth():
    """社交端点的统一门卫：游客明确得到 401，而不是写入幽灵数据。"""
    if authenticated():
        return None
    return jsonify({"error": "请先登录后再使用好友功能", "login_required": True}), 401


@bp.get("/api/friends/invite-info")
def api_invite_info():
    """邀请横幅的公开查询：注册页要向访客展示是谁发出的邀请。

    只回用户名、只认完整合法的 user_id，不暴露其余档案信息。
    """
    raw = request.args.get("user", "")
    if not valid_user_id(raw):
        return jsonify({"error": "无效的邀请链接"}), 400
    with db() as conn:
        row = conn.execute(
            "SELECT username FROM account WHERE user_id=? AND disabled_at IS NULL",
            (raw,)).fetchone()
    if not row:
        return jsonify({"error": "没有这个用户"}), 404
    return resp({"username": row["username"]})


@bp.get("/api/friends/search")
def api_search():
    guard = _require_auth()
    if guard:
        return guard
    me = get_user()
    q = (request.args.get("q") or "").strip()
    if len(q) < 1 or len(q) > 32:
        return jsonify({"error": "请输入要搜索的用户名"}), 400
    with db() as conn:
        rows = conn.execute(
            "SELECT user_id, username FROM account "
            "WHERE username LIKE ? ESCAPE '\\' COLLATE NOCASE AND disabled_at IS NULL AND user_id<>? "
            "ORDER BY username LIMIT ?", (escape_like(q), me, SEARCH_LIMIT)).fetchall()
        states = {}
        ids = [r["user_id"] for r in rows]
        if ids:
            marks = ",".join("?" * len(ids))
            others = (*ids, *ids)
            for r in conn.execute(
                    f"""SELECT * FROM friend_relation
                        WHERE (user_a=? AND user_b IN ({marks}))
                           OR (user_b=? AND user_a IN ({marks}))""", (me, *ids, me, *ids)):
                other = r["user_b"] if r["user_a"] == me else r["user_a"]
                states[other] = _relation_state(r, me)
    users = [{"user_id": r["user_id"], "username": r["username"],
              "relation": states.get(r["user_id"], "none")} for r in rows]
    return resp({"users": users})


@bp.get("/api/friends")
def api_friends():
    guard = _require_auth()
    if guard:
        return guard
    me = get_user()
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM friend_relation WHERE user_a=? OR user_b=?", (me, me)).fetchall()
        friends, incoming, outgoing = [], [], []
        for r in rows:
            other = r["user_b"] if r["user_a"] == me else r["user_a"]
            entry = {"user_id": other}
            state = _relation_state(r, me)
            if state == "friends":
                friends.append(entry)
            elif state == "incoming":
                requester = conn.execute(
                    "SELECT username FROM account WHERE user_id=?", (other,)).fetchone()
                entry["username"] = requester["username"] if requester else "已注销账户"
                incoming.append(entry)
            else:
                outgoing.append(entry)

        def enrich(entries):
            """补全展示信息：等级/连续天数/今天是否已练/最后活跃。"""
            if not entries:
                return entries
            ids = [e["user_id"] for e in entries]
            marks = ",".join("?" * len(ids))
            accts = {r["user_id"]: r["username"] for r in conn.execute(
                f"SELECT user_id, username FROM account WHERE user_id IN ({marks})", ids)}
            seen = {r["user_id"]: r["last_seen_at"] for r in conn.execute(
                f"""SELECT user_id, MAX(last_seen_at) last_seen_at FROM auth_session
                    WHERE user_id IN ({marks}) GROUP BY user_id""", ids)}
            for e in entries:
                uid = e["user_id"]
                prof = derive_profile(conn, uid)
                e.update({
                    "username": accts.get(uid, "已注销账户"),
                    "level": prof["level"], "level_title": prof["title"],
                    "streak": prof["streak"], "today_done": prof["today_done"],
                    "xp": prof["xp"], "last_active_at": seen.get(uid),
                })
            return entries

        friends = enrich(friends)
        incoming = enrich(incoming)
        outgoing = enrich(outgoing)
    friends.sort(key=lambda e: (-e["streak"], -e["xp"]))
    return resp({"friends": friends,
                 "requests": {"incoming": incoming, "outgoing": outgoing},
                 "max": FRIENDS_MAX})


@bp.post("/api/friends/add")
def api_add():
    guard = _require_auth()
    if guard:
        return guard
    me = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    target_id = data.get("user_id")
    username = data.get("username")

    with db() as conn:
        if target_id:
            acct = conn.execute(
                "SELECT user_id, username FROM account WHERE user_id=? AND disabled_at IS NULL",
                (target_id,)).fetchone()
        else:
            if not isinstance(username, str) or not username.strip():
                return jsonify({"error": "缺少好友用户名"}), 400
            acct = conn.execute(
                "SELECT user_id, username FROM account WHERE username=? COLLATE NOCASE "
                "AND disabled_at IS NULL", (username.strip(),)).fetchone()
        if not acct:
            return jsonify({"error": "没有这个用户"}), 404
        other = acct["user_id"]
        pair = _pair(me, other)
        if pair is None:
            return jsonify({"error": "不能添加自己为好友"}), 400
        # 添加或自动通过都会新建关系，双方都要有空位
        if any(at_friends_cap(conn, uid) for uid in pair):
            return jsonify({"error": f"好友数已达上限（{FRIENDS_MAX}）"}), 400

        stamp = now_iso()
        row = conn.execute("SELECT * FROM friend_relation WHERE user_a=? AND user_b=?",
                           pair).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO friend_relation(user_a, user_b, status, requested_by,
                                              created_at, updated_at)
                   VALUES(?,?, 'pending', ?, ?, ?)""", (*pair, me, stamp, stamp))
            return resp({"relation": "outgoing"})
        state = _relation_state(row, me)
        if state == "friends":
            return resp({"relation": "friends"})
        if state == "outgoing":
            return resp({"relation": "outgoing"})
        # 对方先发起过申请：这次添加即双向确认
        cur = conn.execute(
            "UPDATE friend_relation SET status='accepted', updated_at=? "
            "WHERE user_a=? AND user_b=? AND status='pending'", (stamp, *pair))
        if cur.rowcount:   # 并发下第二个 UPDATE 命中 0 行，不重复发动态
            record_activity(conn, me, "friend_join", {"with": other})
            record_activity(conn, other, "friend_join", {"with": me})
        return resp({"relation": "friends"})


@bp.post("/api/friends/accept")
def api_accept():
    guard = _require_auth()
    if guard:
        return guard
    me = get_user()
    data = request.get_json(silent=True)
    other = data.get("user_id") if isinstance(data, dict) else None
    if not other:
        return jsonify({"error": "缺少 user_id"}), 400
    pair = _pair(me, other)
    if pair is None:
        return jsonify({"error": "参数无效"}), 400
    with db() as conn:
        row = conn.execute("SELECT * FROM friend_relation WHERE user_a=? AND user_b=?",
                           pair).fetchone()
        if row is None or row["status"] != "pending" or row["requested_by"] == me:
            return jsonify({"error": "没有待通过的好友申请"}), 404
        # 通过前校验双方好友数是否已达上限（与 api_add 同口径）
        if any(at_friends_cap(conn, uid) for uid in pair):
            return jsonify({"error": f"好友数已达上限（{FRIENDS_MAX}）"}), 400
        cur = conn.execute("UPDATE friend_relation SET status='accepted', updated_at=? "
                     "WHERE user_a=? AND user_b=? AND status='pending'", (now_iso(), *pair))
        if cur.rowcount:   # 并发下第二个 UPDATE 命中 0 行，不重复发动态
            record_activity(conn, me, "friend_join", {"with": other})
            record_activity(conn, other, "friend_join", {"with": me})
    return resp({"relation": "friends"})


@bp.post("/api/friends/reject")
def api_reject():
    """拒绝待确认申请或删除已有好友：统一为解除关系。"""
    guard = _require_auth()
    if guard:
        return guard
    me = get_user()
    data = request.get_json(silent=True)
    other = data.get("user_id") if isinstance(data, dict) else None
    if not other:
        return jsonify({"error": "缺少 user_id"}), 400
    pair = _pair(me, other)
    if pair is None:
        return jsonify({"error": "参数无效"}), 400
    with db() as conn:
        deleted = conn.execute("DELETE FROM friend_relation WHERE user_a=? AND user_b=?",
                               pair).rowcount
    return resp({"removed": bool(deleted)})


@bp.get("/api/friends/activity")
def api_activity():
    guard = _require_auth()
    if guard:
        return guard
    me = get_user()
    with db() as conn:
        friend_ids = [
            r["user_b"] if r["user_a"] == me else r["user_a"]
            for r in conn.execute(
                "SELECT user_a, user_b FROM friend_relation "
                "WHERE status='accepted' AND (user_a=? OR user_b=?)", (me, me))]
        who = [me, *friend_ids]
        marks = ",".join("?" * len(who))
        rows = conn.execute(
            f"""SELECT user, kind, detail, created_at FROM friend_activity
                WHERE user IN ({marks}) ORDER BY id DESC LIMIT 50""", who).fetchall()
        names = display_names(conn, who)
    events = []
    for r in rows:
        try:
            detail = json.loads(r["detail"])
        except ValueError:
            detail = {}
        events.append({"user": r["user"], "name": names.get(r["user"], "？"),
                       "kind": r["kind"], **detail, "created_at": r["created_at"]})
    return resp({"events": events})


# ---------------- 动态写入：由各玩法结束点调用，失败不影响主流程 ----------------

def record_activity(conn, user, kind, detail):
    """写一条动态并清理过期行。只记录登录账户；游客 UUID 会无限新增，写了也没人看。

    必须在调用方的事务连接上执行：随业务写入一起提交/回滚，动态与事实保持一致。
    """
    if not authenticated():
        return
    stamp = now_iso()
    conn.execute("INSERT INTO friend_activity(user, kind, detail, created_at) VALUES(?,?,?,?)",
                 (user, kind, json.dumps(detail, ensure_ascii=False), stamp))
    conn.execute("DELETE FROM friend_activity WHERE created_at < ?",
                 ((datetime.now(timezone.utc).date()
                   - timedelta(days=ACTIVITY_TTL_DAYS)).isoformat(),))


def notify_level(conn, user):
    """练习统计变更后探测升级，发 level_up 动态。

    探测基线存 friend_level_seen：首次观察到该用户时静默建档（避免老号一上来
    就连发一堆"升到历史等级"）；此后每当实时等级超过基线即推送并推进基线。
    未登录用户查 friend_level_seen 必落空——插入一行等于开始记账，因此必须
    先挡掉：否则游客每次答题都白建基线行。
    """
    if not authenticated():
        return
    row = conn.execute("SELECT level FROM friend_level_seen WHERE user=?", (user,)).fetchone()
    if row is None:
        record_silent_baseline(conn, user)
        return
    level_now = level_of(xp_of(conn, user))
    if level_now <= row["level"]:
        return
    # 条件推进基线：只有 level 确实推进时才命中 1 行；并发下第二个 UPDATE 命中 0 行
    cur = conn.execute("""INSERT INTO friend_level_seen(user, level, updated_at) VALUES(?,?,?)
                    ON CONFLICT(user) DO UPDATE SET level=excluded.level,
                        updated_at=excluded.updated_at
                    WHERE friend_level_seen.level < excluded.level""",
                 (user, level_now, now_iso()))
    if cur.rowcount:
        record_activity(conn, user, "level_up",
                        {"level": level_now, "title": LEVELS[level_now - 1][1]})


def record_silent_baseline(conn, user):
    conn.execute("""INSERT INTO friend_level_seen(user, level, updated_at) VALUES(?,?,?)
                    ON CONFLICT(user) DO UPDATE SET level=excluded.level,
                        updated_at=excluded.updated_at""",
                 (user, level_of(xp_of(conn, user)), now_iso()))
