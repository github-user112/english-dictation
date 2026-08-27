"""学习小组：建组 / 加入 / 退出与解散、组内挑战。

小组挑战的分数一律从学习表实时推导（daily_challenge 的比分、
daily_practice_log 的末答对数、daily_log 的背诵对数），不另设提分端点——
与服务端判分哲学一致：客户端提交不了的分数才可信。

小组详情登录后即可查看（搜索/邀请链接先看组再决定加入）；只有成员变更与
发起挑战要求已在组内。
"""
import json
import uuid
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from .auth import authenticated, display_name, get_user, resp
from .catalog import clamp_int, now
from .friends import escape_like
from .db import db
from .profile import derive_profile

bp = Blueprint("groups", __name__)

NAME_MAX = 24
MEMBERS_DEFAULT_MAX = 20      # 组人数上限固定为默认值；要调大改这里并同步文案
CHALLENGE_KINDS = {"daily", "words_target"}
ACTIVE_CHALLENGES_MAX = 3     # 同组同时进行的挑战数上限
MY_GROUPS_MAX = 20            # 单账号加入的小组数上限
CHALLENGE_DAYS_DEFAULT, CHALLENGE_DAYS_MIN, CHALLENGE_DAYS_MAX = 7, 1, 30


def _require_auth():
    if authenticated():
        return None
    return jsonify({"error": "请先登录后再使用小组功能", "login_required": True}), 401


def _membership(conn, group_id, user):
    return conn.execute(
        "SELECT * FROM group_member WHERE group_id=? AND user=?", (group_id, user)).fetchone()


def _today_iso():
    return date.today().isoformat()


@bp.post("/api/groups")
def api_create():
    guard = _require_auth()
    if guard:
        return guard
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    name = (data.get("name") or "").strip()
    if not 1 <= len(name) <= NAME_MAX:
        return jsonify({"error": f"小组名需 1–{NAME_MAX} 个字符"}), 400

    with db() as conn:
        mine = conn.execute(
            "SELECT COUNT(*) c FROM group_member WHERE user=?", (user,)).fetchone()["c"]
        if mine >= MY_GROUPS_MAX:
            return jsonify({"error": f"最多加入 {MY_GROUPS_MAX} 个小组"}), 400
        gid = uuid.uuid4().hex[:10]
        conn.execute("INSERT INTO study_group(id, name, creator, created_at) VALUES(?,?,?,?)",
                     (gid, name, user, now()))
        conn.execute("INSERT INTO group_member(group_id, user, role, joined_at) "
                     "VALUES(?,?,'owner',?)", (gid, user, now()))
    return resp({"id": gid, "name": name})


@bp.get("/api/groups")
def api_my_groups():
    guard = _require_auth()
    if guard:
        return guard
    user = get_user()
    with db() as conn:
        rows = conn.execute(
            """SELECT g.id, g.name, g.creator, g.created_at AS group_created_at,
                      m.role, m.joined_at,
                      (SELECT COUNT(*) FROM group_member gm WHERE gm.group_id=g.id) member_count
               FROM study_group g JOIN group_member m ON m.group_id=g.id AND m.user=?
               ORDER BY g.created_at""", (user,)).fetchall()
        creators = {r["creator"] for r in rows}
        creator_names = {uid: display_name(conn, uid) for uid in creators}
    groups = [{"id": r["id"], "name": r["name"], "role": r["role"],
               "creator_name": creator_names.get(r["creator"], "？"),
               "created_at": r["group_created_at"], "joined_at": r["joined_at"],
               "member_count": r["member_count"],
               "max_members": MEMBERS_DEFAULT_MAX} for r in rows]
    return resp({"groups": groups})


@bp.get("/api/groups/search")
def api_search():
    guard = _require_auth()
    if guard:
        return guard
    me = get_user()
    q = (request.args.get("q") or "").strip()
    if not 1 <= len(q) <= 32:
        return jsonify({"error": "请输入要搜索的小组名"}), 400
    with db() as conn:
        rows = conn.execute(
            """SELECT g.id, g.name, g.created_at,
                      (SELECT COUNT(*) FROM group_member gm WHERE gm.group_id=g.id) members,
                      EXISTS(SELECT 1 FROM group_member gm2
                             WHERE gm2.group_id=g.id AND gm2.user=?) joined
               FROM study_group g
               WHERE g.name LIKE ? ESCAPE '\\' COLLATE NOCASE
               ORDER BY members DESC, g.created_at LIMIT 20""",
            (me, escape_like(q))).fetchall()
    return resp({"groups": [
        {"id": r["id"], "name": r["name"], "members": r["members"],
         "max_members": MEMBERS_DEFAULT_MAX,
         "full": r["members"] >= MEMBERS_DEFAULT_MAX,
         "joined": bool(r["joined"])}
        for r in rows]})


def _member_cards(conn, group_id, viewer=None):
    """成员卡片：等级/连续/今日已练按 profile 口径推导，自己一行带 me 标记。"""
    rows = conn.execute(
        "SELECT user, role, joined_at FROM group_member WHERE group_id=? ORDER BY joined_at",
        (group_id,)).fetchall()
    cards = []
    for r in rows:
        uid = r["user"]
        prof = derive_profile(conn, uid)
        cards.append({"user_id": uid, "name": display_name(conn, uid),
                      "role": r["role"], "joined_at": r["joined_at"],
                      "level": prof["level"], "level_title": prof["title"],
                      "streak": prof["streak"], "xp": prof["xp"],
                      "today_done": prof["today_done"], "me": uid == viewer})
    return cards


def _challenge_payload(conn, row, member_ids, names):
    """把一条挑战行翻译成带全员实时进度的响应体。窗口按日粒度：
    含创建日、含到期日的自然日区间。"""
    cfg = json.loads(row["config"] or "{}")
    start_day = str(row["created_at"])[:10]
    end_day = str(row["expires_at"])[:10]

    values, played = {}, {}
    if row["kind"] == "daily":
        marks = ",".join("?" * len(member_ids))
        for r in conn.execute(
                f"""SELECT user, SUM(score) s, COUNT(*) n FROM daily_challenge
                    WHERE day>=? AND day<=? AND user IN ({marks}) GROUP BY user""",
                (start_day, end_day, *member_ids)):
            values[r["user"]], played[r["user"]] = r["s"] or 0, r["n"]
    elif row["kind"] == "words_target":
        marks = ",".join("?" * len(member_ids))
        for r in conn.execute(
                f"""SELECT user, SUM(final_right_count) s FROM daily_practice_log
                    WHERE day>=? AND day<=? AND user IN ({marks}) GROUP BY user""",
                (start_day, end_day, *member_ids)):
            values[r["user"]] = r["s"] or 0
        # 背诵对只落在 daily_log.memorize_right，与听打口径不同源不重叠
        for r in conn.execute(
                f"""SELECT user, SUM(memorize_right) s FROM daily_log
                    WHERE day>=? AND day<=? AND user IN ({marks}) GROUP BY user""",
                (start_day, end_day, *member_ids)):
            values[r["user"]] = values.get(r["user"], 0) + (r["s"] or 0)
    else:
        return None   # 未知类型不入库（写入端校验过），防御性跳过渲染

    scores = sorted(({"user_id": uid, "name": names.get(uid, "？"), "value": int(v)}
                     for uid, v in values.items()),
                    key=lambda s: (-s["value"], s["user_id"]))
    kind = row["kind"]
    target = cfg.get("target_words") if kind == "words_target" else None
    return {
        "id": row["id"], "kind": kind, "config": cfg,
        "created_by": names.get(row["creator"], "？"), "created_at": row["created_at"],
        "expires_at": row["expires_at"], "active": end_day >= _today_iso(),
        "target_words": target,
        "played_counts": played if kind == "daily" else None,
        "scores": scores,
    }


@bp.get("/api/groups/<gid>")
def api_detail(gid):
    guard = _require_auth()
    if guard:
        return guard
    me = get_user()
    with db() as conn:
        grp = conn.execute("SELECT * FROM study_group WHERE id=?", (gid,)).fetchone()
        if not grp:
            return jsonify({"error": "小组不存在"}), 404
        mine = _membership(conn, gid, me)
        member_ids = [r["user"] for r in conn.execute(
            "SELECT user FROM group_member WHERE group_id=? ORDER BY joined_at", (gid,))]
        names = {uid: display_name(conn, uid) for uid in member_ids}
        challenges = conn.execute(
            "SELECT * FROM group_challenge WHERE group_id=? ORDER BY created_at DESC LIMIT 20",
            (gid,)).fetchall()
        payloads = [p for p in (
            _challenge_payload(conn, ch, member_ids, names) for ch in challenges) if p]
        cards = _member_cards(conn, gid, viewer=me)
    cards.sort(key=lambda c: (c["role"] != "owner", -c["streak"]))
    return resp({
        "id": grp["id"], "name": grp["name"], "creator": grp["creator"],
        "creator_name": names.get(grp["creator"], "？"),
        "created_at": grp["created_at"], "max_members": MEMBERS_DEFAULT_MAX,
        "members": cards, "member_count": len(cards),
        "role": mine["role"] if mine else None, "is_member": mine is not None,
        "challenges": payloads,
    })


@bp.get("/api/groups/<gid>/challenges")
def api_challenges(gid):
    guard = _require_auth()
    if guard:
        return guard
    me = get_user()
    with db() as conn:
        if not conn.execute("SELECT 1 FROM study_group WHERE id=?", (gid,)).fetchone():
            return jsonify({"error": "小组不存在"}), 404
        if not _membership(conn, gid, me):
            return jsonify({"error": "加入小组后才能查看挑战"}), 403
        member_ids = [r["user"] for r in conn.execute(
            "SELECT user FROM group_member WHERE group_id=?", (gid,))]
        names = {uid: display_name(conn, uid) for uid in member_ids}
        rows = conn.execute(
            "SELECT * FROM group_challenge WHERE group_id=? ORDER BY created_at DESC LIMIT 20",
            (gid,)).fetchall()
        payloads = [p for p in (
            _challenge_payload(conn, ch, member_ids, names) for ch in rows) if p]
    return resp({"challenges": payloads})


@bp.post("/api/groups/<gid>/join")
def api_join(gid):
    guard = _require_auth()
    if guard:
        return guard
    user = get_user()
    with db() as conn:
        if not conn.execute("SELECT 1 FROM study_group WHERE id=?", (gid,)).fetchone():
            return jsonify({"error": "小组不存在"}), 404
        if _membership(conn, gid, user):
            return resp({"joined": True})
        mine = conn.execute("SELECT COUNT(*) c FROM group_member WHERE user=?",
                            (user,)).fetchone()["c"]
        if mine >= MY_GROUPS_MAX:
            return jsonify({"error": f"最多加入 {MY_GROUPS_MAX} 个小组"}), 400
        members = conn.execute("SELECT COUNT(*) c FROM group_member WHERE group_id=?",
                               (gid,)).fetchone()["c"]
        if members >= MEMBERS_DEFAULT_MAX:
            return jsonify({"error": f"小组人数已满（{MEMBERS_DEFAULT_MAX}）"}), 400
        conn.execute("INSERT INTO group_member(group_id, user, role, joined_at) "
                     "VALUES(?,?,'member',?)", (gid, user, now()))
    return resp({"joined": True})


@bp.post("/api/groups/<gid>/leave")
def api_leave(gid):
    guard = _require_auth()
    if guard:
        return guard
    user = get_user()
    with db() as conn:
        mine = _membership(conn, gid, user)
        if not mine:
            return jsonify({"error": "你不在这个小组里"}), 404
        grp = conn.execute("SELECT creator FROM study_group WHERE id=?", (gid,)).fetchone()
        if grp and grp["creator"] == user:
            return jsonify({"error": "组长不能退出；请解散小组"}), 400
        conn.execute("DELETE FROM group_member WHERE group_id=? AND user=?", (gid, user))
    return resp({"left": True})


@bp.post("/api/groups/<gid>/dissolve")
def api_dissolve(gid):
    """解散小组：仅组长。成员与挑战随外键级联删除。"""
    guard = _require_auth()
    if guard:
        return guard
    user = get_user()
    with db() as conn:
        grp = conn.execute("SELECT creator FROM study_group WHERE id=?", (gid,)).fetchone()
        if not grp:
            return jsonify({"error": "小组不存在"}), 404
        if grp["creator"] != user:
            return jsonify({"error": "只有组长可以解散小组"}), 403
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM study_group WHERE id=?", (gid,))
    return resp({"dissolved": True})


@bp.post("/api/groups/<gid>/challenge")
def api_create_challenge(gid):
    guard = _require_auth()
    if guard:
        return guard
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    kind = data.get("kind")
    if kind not in CHALLENGE_KINDS:
        return jsonify({"error": "未知挑战类型"}), 400
    days = clamp_int(data.get("days"), CHALLENGE_DAYS_DEFAULT,
                     CHALLENGE_DAYS_MIN, CHALLENGE_DAYS_MAX)
    cfg = {}
    if kind == "words_target":
        cfg["target_words"] = clamp_int(data.get("target_words"), 50, 1, 100000)

    expires = (date.today() + timedelta(days=days)).isoformat()
    with db() as conn:
        if not conn.execute("SELECT 1 FROM study_group WHERE id=?", (gid,)).fetchone():
            return jsonify({"error": "小组不存在"}), 404
        if not _membership(conn, gid, user):
            return jsonify({"error": "加入小组后才能发起挑战"}), 403
        active = conn.execute(
            "SELECT COUNT(*) c FROM group_challenge WHERE group_id=? AND expires_at>=?",
            (gid, _today_iso())).fetchone()["c"]
        if active >= ACTIVE_CHALLENGES_MAX:
            return jsonify({"error": "同时进行的挑战已达上限"}), 400
        cid = uuid.uuid4().hex[:10]
        conn.execute(
            """INSERT INTO group_challenge(id, group_id, creator, kind, config,
                                          created_at, expires_at)
               VALUES(?,?,?,?,?,?,?)""",
            (cid, gid, user, kind, json.dumps(cfg, ensure_ascii=False), now(), expires))
    return resp({"id": cid, "expires_at": expires})
