"""好友 / 小组 / 全局排行榜接口测试。

排行榜取值一律从学习表实时推导，这里直接插源表数据断言排名与窗口过滤；
好友与小组走登录账户多浏览器流程，游客只应得到 401。
"""
from datetime import date, datetime, timedelta

from flask.testing import FlaskClient

from backend.db import db
from backend.friends import ACTIVITY_TTL_DAYS, FRIENDS_MAX
from backend.groups import (ACTIVE_CHALLENGES_MAX, CHALLENGE_DAYS_DEFAULT,
                            MEMBERS_DEFAULT_MAX, MY_GROUPS_MAX)
from backend.leaderboard import ACCURACY_MIN_ATTEMPTS

PASS = "correct horse battery staple"


class SocialBrowser(FlaskClient):
    """独立于 conftest.client 夹具的多账号浏览器：写请求自动带 CSRF token。"""

    def open(self, *args, **kwargs):
        method = kwargs.get("method", "GET").upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = self.get_cookie("dict_csrf")
            if token:
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("X-CSRF-Token", token.value)
                kwargs["headers"] = headers
        return super().open(*args, **kwargs)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def day_iso(offset=0):
    return (date.today() + timedelta(days=offset)).isoformat()


def browser(app, username=None):
    """新浏览器会话；给了用户名就注册成登录账户。"""
    b = SocialBrowser(app)
    b.get("/api/auth/me")
    if username:
        r = b.post("/api/auth/register", json={"username": username, "password": PASS})
        assert r.status_code == 200, r.json
    return b


def uid_of(b):
    return b.get("/api/auth/me").json["user"]


# ---------------- 排行榜 ----------------

def test_leaderboard_rejects_unknown_scope_and_period(client):
    assert client.get("/api/leaderboard?scope=nope").status_code == 400
    assert client.get("/api/leaderboard?scope=daily&period=nope").status_code == 400


def test_leaderboard_sprint_best_orders_and_exposes_details(client):
    a, b = uid_of(client), "e" * 32
    with db() as conn:
        conn.executemany("INSERT INTO sprint_best(user,score,combo,total,updated_at) VALUES(?,?,?,?,?)",
                         [(a, 30, 12, 40, now_iso()), (b, 45, 30, 45, now_iso())])
    d = client.get(f"/api/leaderboard?scope=sprint&u={a}").json
    assert [r["rank"] for r in d["rows"]] == [1, 2]
    assert d["rows"][0]["value"] == 45 and d["rows"][0]["combo"] == 30 and d["rows"][0]["total"] == 45
    assert d["me_rank"] == 2 and d["total_players"] == 2
    # sprint 无逐局历史，任何周期参数都等价于 all
    assert client.get("/api/leaderboard?scope=sprint&period=weekly").json["period"] == "all"
    assert client.get("/api/leaderboard?scope=streak&period=monthly").json["period"] == "all"


def test_leaderboard_masks_strangers_but_not_self(app):
    """打码在后端完成：陌生人只留首尾轮廓，本人行保留全名，邮箱域名仍可读。"""
    viewer, rival, mailer = (browser(app, name) for name in
                             ("viewer_me", "alice_soc", "bob_smith@qq.com"))
    with db() as conn:
        conn.executemany(
            "INSERT INTO sprint_best(user,score,combo,total,updated_at) VALUES(?,?,?,?,?)",
            [(uid_of(mailer), 30, 3, 40, now_iso()),
             (uid_of(rival), 20, 2, 40, now_iso()),
             (uid_of(viewer), 10, 1, 40, now_iso())])
    names = {r["rank"]: r["name"]
             for r in viewer.get("/api/leaderboard?scope=sprint").json["rows"]}
    assert names[1] == "bo***h@qq.com"      # 邮箱：本地段打码，域名保留便于辨识
    assert names[2] == "al***c"             # 陌生人：中段固定三星，不暴露长度
    assert names[3] == "viewer_me"          # 自己那一行无需对自己隐藏


def test_leaderboard_daily_respects_period_windows(client):
    with db() as conn:
        conn.executemany(
            "INSERT INTO daily_challenge(day,user,list_key,score,total,detail,completed_at) "
            "VALUES(?,?,?,?,?,?,?)",
            [(day_iso(0), "f" * 32, "test_words", 90, 100, "[]", now_iso()),
             (day_iso(-20), "f" * 32, "test_words", 99, 100, "[]", now_iso()),
             (day_iso(0), "a" * 32, "test_words", 70, 100, "[]", now_iso())])
    weekly = client.get("/api/leaderboard?scope=daily&period=weekly").json
    assert weekly["total_players"] == 2 and weekly["rows"][0]["value"] == 90   # -20 天的 99 分不进本周窗
    monthly = client.get("/api/leaderboard?scope=daily&period=monthly").json
    assert monthly["rows"][0]["value"] == 99     # -20 天在月度 30 天窗口内，月度榜看得到
    alltime = client.get("/api/leaderboard?scope=daily").json
    assert alltime["rows"][0]["value"] == 99


def test_leaderboard_xp_weights_match_profile_formula(client):
    u = "b" * 32
    with db() as conn:
        conn.execute(
            "INSERT INTO daily_practice_log(day,user,practice_mode,new_count,review_count,"
            "first_right_count,first_wrong_count,final_right_count,skipped_count) VALUES(?,?,?,?,?,?,?,?,?)",
            (day_iso(0), u, "assisted", 4, 5, 7, 2, 7, 1))
        conn.execute("INSERT INTO daily_log(day,user,memorize_right,memorize_wrong) VALUES(?,?,?,?)",
                     (day_iso(0), u, 6, 0))
        conn.execute("INSERT INTO daily_challenge(day,user,list_key,score,total,detail,completed_at) "
                     "VALUES(?,?,?,?,?,?,?)", (day_iso(0), u, "test_words", 8, 10, "[]", now_iso()))
    d = client.get(f"/api/leaderboard?scope=xp&period=all&u={u}").json
    row = d["rows"][0]
    # 7*10 + 4*3 + (2+1)*2 + 6*5 + 8*10 + 2*2 = 70+12+6+30+80+4 = 202
    assert row["value"] == 202
    assert row["level"] == 2 and row["level_title"]
    assert d["me_rank"] == 1


def test_leaderboard_streak_counts_union_of_practice_days(client):
    u = "c" * 32
    with db() as conn:
        for offset in (-1, -3):    # 今天没练从昨天回数：昨天算 1，前天断档停止 → 1 天
            conn.execute("INSERT INTO daily_log(day,user,new_count) VALUES(?,?,1)",
                         (day_iso(offset), u))
        conn.execute("INSERT INTO daily_challenge(day,user,list_key,score,total,detail,completed_at) "
                     "VALUES(?,?,?,?,?,?,?)",
                     (day_iso(-2), u, "test_words", 5, 10, "[]", now_iso()))   # 补上前天：并集成链
    d = client.get(f"/api/leaderboard?scope=streak&u={u}").json
    assert d["rows"][0]["value"] == 3


def test_leaderboard_accuracy_requires_minimum_attempts(client):
    strong, thin = "d" * 32, "9" * 32
    n = ACCURACY_MIN_ATTEMPTS
    with db() as conn:
        conn.execute(
            "INSERT INTO daily_practice_log(day,user,practice_mode,first_right_count,"
            "first_wrong_count,final_right_count) VALUES(?,?,?,?,?,?)",
            (day_iso(0), strong, "assisted", 19, 1, 20))
        conn.execute(
            "INSERT INTO daily_practice_log(day,user,practice_mode,first_right_count,"
            "first_wrong_count,final_right_count) VALUES(?,?,?,?,?,?)",
            (day_iso(0), thin, "assisted", 15, 4, 15))   # 19 次首答 < 阈值，不上榜
    d = client.get("/api/leaderboard?scope=accuracy").json
    assert d["total_players"] == 1
    assert d["rows"][0]["user"] == strong and d["rows"][0]["value"] == round(19 / 20 * 100, 1)


def test_leaderboard_ranks_guests_with_fallback_names(app):
    guest = "1234" + "7" * 28
    with db() as conn:
        conn.execute("INSERT INTO sprint_best(user,score,combo,total,updated_at) VALUES(?,?,?,?,?)",
                     (guest, 22, 9, 40, now_iso()))
    d = app.test_client().get(f"/api/leaderboard?scope=sprint&u={guest}").json
    assert d["rows"][0]["name"].startswith("游客") and d["me_rank"] == 1


# ---------------- 好友 ----------------

def test_friends_require_login(app):
    b = browser(app)
    assert b.get("/api/friends").status_code == 401
    r = b.post("/api/friends/add", json={"username": "anyone"})
    assert r.status_code == 401 and r.json["login_required"] is True


def test_friend_request_then_accept_full_lifecycle(app):
    alice, bob = browser(app, "alice_soc"), browser(app, "bob_soc")
    bob_id = uid_of(bob)

    r = alice.post("/api/friends/add", json={"username": "BOB_SOC"})   # 大小写不敏感命中
    assert r.status_code == 200 and r.json["relation"] == "outgoing"

    incoming = bob.get("/api/friends").json
    assert len(incoming["requests"]["incoming"]) == 1
    assert incoming["requests"]["incoming"][0]["username"] == "alice_soc"
    assert incoming["requests"]["incoming"][0]["level_title"]

    # 同向重复通过没有待确认的申请；请求方自己也不能"接受"自己的出站申请
    assert alice.post("/api/friends/accept", json={"user_id": bob_id}).status_code == 404

    ok = bob.post("/api/friends/accept", json={"user_id": uid_of(alice)})
    assert ok.status_code == 200 and ok.json["relation"] == "friends"

    friends_a = alice.get("/api/friends").json["friends"]
    assert [e["user_id"] for e in friends_a] == [bob_id]
    entry = friends_a[0]
    for field in ("username", "level", "streak", "today_done", "xp"):
        assert field in entry

    events = alice.get("/api/friends/activity").json["events"]
    joins = [e for e in events if e["kind"] == "friend_join"]
    assert {e["name"] for e in joins} >= {"alice_soc"}   # 双方各有一条结为好友的动态


def test_mutual_add_auto_accepts(app):
    alice, bob = browser(app, "carol_soc"), browser(app, "dave_soc")
    first = alice.post("/api/friends/add", json={"user_id": uid_of(bob)})
    second = bob.post("/api/friends/add", json={"user_id": uid_of(alice)})
    assert first.json["relation"] == "outgoing"
    assert second.status_code == 200 and second.json["relation"] == "friends"
    assert alice.get("/api/friends").json["friends"][0]["user_id"] == uid_of(bob)


def test_add_self_unknown_user_and_remove(app):
    alice, bob = browser(app, "erin_soc"), browser(app, "frank_soc")
    me = uid_of(alice)
    assert alice.post("/api/friends/add", json={"user_id": me}).status_code == 400
    assert alice.post("/api/friends/add", json={"username": "ghost_nobody"}).status_code == 404

    other = uid_of(bob)
    alice.post("/api/friends/add", json={"user_id": other})
    assert alice.post("/api/friends/reject", json={"user_id": other}).json["removed"] is True
    assert alice.post("/api/friends/reject", json={"user_id": other}).json["removed"] is False
    listing = alice.get("/api/friends").json
    assert not any(e["user_id"] == other for e in listing["friends"])
    assert listing["max"] == FRIENDS_MAX


def test_search_reports_relation_state_per_user(app):
    alice, bob, carol = browser(app, "grace_soc"), browser(app, "heidi_soc"), browser(app, "ivan_soc")
    alice.post("/api/friends/add", json={"user_id": uid_of(bob)})          # outgoing
    carol.post("/api/friends/add", json={"user_id": uid_of(alice)})        # alice 视角 incoming
    users = alice.get("/api/friends/search?q=_soc").json["users"]
    rows = {u["username"]: u["relation"] for u in users}
    assert rows["heidi_soc"] == "outgoing"
    assert rows["ivan_soc"] == "incoming"
    alice.post("/api/friends/add", json={"user_id": uid_of(carol)})   # 反向申请自动成友
    users = alice.get("/api/friends/search?q=_soc").json["users"]
    assert {u["username"]: u["relation"] for u in users}["ivan_soc"] == "friends"
    assert all(u["user_id"] != uid_of(alice) for u in users)          # 永远搜不到自己


def test_activity_feed_merges_friends_and_ttoldd_rows_are_pruned(app):
    alice, bob = browser(app, "judy_soc"), browser(app, "mallory_soc")
    with db() as conn:
        ancient = (date.today() - timedelta(days=ACTIVITY_TTL_DAYS + 3)).isoformat()
        conn.executemany(
            "INSERT INTO friend_activity(user,kind,detail,created_at) VALUES(?,?,?,?)",
            [(uid_of(alice), "sprint_record", '{"score":99}', f"{ancient}T10:00:00")])
    bob.post("/api/friends/add", json={"user_id": uid_of(alice)})
    alice.post("/api/friends/add", json={"user_id": uid_of(bob)})   # 自动互认并写动态

    events = alice.get("/api/friends/activity").json["events"]
    kinds = {(e["name"], e["kind"]) for e in events}
    assert ("judy_soc", "friend_join") in kinds or ("mallory_soc", "friend_join") in kinds
    assert all(e["kind"] != "sprint_record" for e in events)   # 过期动态已被写路径清理


def test_level_up_event_emitted_once_when_crossing_threshold(app):
    loner, pal = browser(app, "nick_soc"), browser(app, "oscar_soc")
    nick = uid_of(loner)
    pal.post("/api/friends/add", json={"user_id": nick})
    loner.post("/api/friends/add", json={"user_id": uid_of(pal)})

    def answer(count):
        for _ in range(count):
            r = loner.post("/api/result",
                           json={"list": "test_words", "id": "hello", "right": True,
                                 "mode": "assisted"})
            assert r.status_code == 200

    answer(1)    # 首次入账建立基线（当前等级），不应立即产生升级动态
    answer(11)   # 11 题再入账 110 XP ≥ 100 的二级阈值 → 恰好一条 level_up
    events = pal.get("/api/friends/activity").json["events"]
    ups = [e for e in events if e["kind"] == "level_up"]
    assert len(ups) == 1 and ups[0]["level"] == 2 and ups[0]["title"]
    assert ups[0]["name"] == "nick_soc"


def test_friend_cap_blocks_new_relations(app):
    alice = browser(app, "peggy_soc")
    me = uid_of(alice)
    with db() as conn:
        for i in range(FRIENDS_MAX):
            other = ("ff%02d" % i).ljust(32, "0")
            pair = sorted((me, other))
            conn.execute("INSERT INTO friend_relation(user_a,user_b,status,requested_by,created_at) "
                         "VALUES(?,?,?,?,?)", (*pair, "accepted", me, now_iso()))
    trent = browser(app, "trent_soc")
    r = alice.post("/api/friends/add", json={"user_id": uid_of(trent)})
    assert r.status_code == 400 and str(FRIENDS_MAX) in r.json["error"]


def test_friend_cap_blocks_auto_accept_and_invite(app):
    """自动通过分支与注册邀请也受好友上限约束——只查申请人自己会让对方超限。"""
    trent = browser(app, "trent_full")
    trent_id = uid_of(trent)
    alice = browser(app, "peggy_full")
    alice_id = uid_of(alice)
    with db() as conn:
        for i in range(FRIENDS_MAX):
            other = ("ff%02d" % i).ljust(32, "0")
            conn.execute("INSERT INTO friend_relation(user_a,user_b,status,requested_by,created_at) "
                         "VALUES(?,?,?,?,?)", (*sorted((trent_id, other)), "accepted",
                                               trent_id, now_iso()))
        # trent 先向 alice 申请过：alice 这次添加走双向确认（自动通过）分支
        conn.execute("INSERT INTO friend_relation(user_a,user_b,status,requested_by,created_at,updated_at) "
                     "VALUES(?,?,?,?,?,?)", (*sorted((trent_id, alice_id)), "pending",
                                             trent_id, now_iso(), now_iso()))
    r = alice.post("/api/friends/add", json={"user_id": trent_id})
    assert r.status_code == 400 and "上限" in r.json["error"]

    # 邀请人满员：被邀请人注册照常成功，但不建关系
    r = SocialBrowser(app).post("/api/auth/register",
                               json={"username": "invitee_full", "password": PASS,
                                     "inviter": trent_id})
    assert r.status_code == 200, r.json
    with db() as conn:
        accepted = conn.execute(
            "SELECT COUNT(*) c FROM friend_relation "
            "WHERE (user_a=? OR user_b=?) AND status='accepted'",
            (trent_id, trent_id)).fetchone()["c"]
    assert accepted == FRIENDS_MAX


# ---------------- 小组 ----------------

def test_groups_require_login(app):
    b = browser(app)
    assert b.get("/api/groups").status_code == 401
    r = b.post("/api/groups", json={"name": "黎明背词团"})
    assert r.status_code == 401 and r.json["login_required"] is True


def _make_group(browser, name):
    r = browser.post("/api/groups", json={"name": name})
    assert r.status_code == 200, r.json
    return r.json["id"]


def test_group_create_validates_name_and_lists_membership(app):
    owner = browser(app, "owner_grp")
    assert owner.post("/api/groups", json={"name": ""}).status_code == 400
    assert owner.post("/api/groups", json={"name": "x" * 25}).status_code == 400

    gid = _make_group(owner, "黎明背词团")
    mine = owner.get("/api/groups").json["groups"]
    assert [g["id"] for g in mine] == [gid]
    assert mine[0]["role"] == "owner" and mine[0]["member_count"] == 1

    # 详情对已登录的非成员开放公开预览（邀请链接先看组再决定加入），
    # 但成员名单与挑战成绩属组内信息，与 /challenges 的 403 口径一致不随详情泄露；游客仍被挡
    outsider = browser(app, "walker_grp")
    member_view = outsider.get(f"/api/groups/{gid}")
    assert member_view.status_code == 200
    detail = member_view.json
    assert detail["is_member"] is False and detail["role"] is None
    assert detail["member_count"] == 1
    assert detail["members"] == [] and detail["challenges"] == []
    assert "creator" not in detail   # 预览不暴露创建者 user_id
    assert browser(app).get(f"/api/groups/{gid}").status_code == 401
    assert outsider.get("/api/groups/nope404").status_code == 404


def test_group_join_leave_and_duplicate_join(app):
    owner, joiner = browser(app, "kate_grp"), browser(app, "lion_grp")
    gid = _make_group(owner, "晨读小组")

    first = joiner.post(f"/api/groups/{gid}/join")
    again = joiner.post(f"/api/groups/{gid}/join")
    assert first.status_code == 200 and again.json["joined"] is True

    members = {m["name"]: m for m in owner.get(f"/api/groups/{gid}").json["members"]}
    assert set(members) == {"kate_grp", "lion_grp"}
    assert members["lion_grp"]["me"] is False              # me 标记跟请求者走
    assert joiner.get(f"/api/groups/{gid}").json["members"][1]["me"] is True

    assert joiner.post(f"/api/groups/{gid}/leave").json["left"] is True
    assert joiner.post(f"/api/groups/{gid}/leave").status_code == 404
    detail = owner.get(f"/api/groups/{gid}").json
    assert detail["member_count"] == 1

    # 组长不能退出，只能解散
    r = owner.post(f"/api/groups/{gid}/leave")
    assert r.status_code == 400 and "解散" in r.json["error"]


def test_group_member_cap_blocks_join(app):
    owner, outsider = browser(app, "mary_grp"), browser(app, "nancy_grp")
    gid = _make_group(owner, "满员小组")
    with db() as conn:
        for i in range(MEMBERS_DEFAULT_MAX - 1):
            conn.execute("INSERT INTO group_member(group_id,user,role,joined_at) VALUES(?,?,?,?)",
                         (gid, ("u%02d" % i).ljust(32, "0"), "member", now_iso()))
    r = outsider.post(f"/api/groups/{gid}/join")
    assert r.status_code == 400 and str(MEMBERS_DEFAULT_MAX) in r.json["error"]


def test_my_groups_cap_blocks_create(app):
    owner = browser(app, "olive_grp")
    for i in range(MY_GROUPS_MAX):
        assert owner.post("/api/groups", json={"name": f"组{i:02d}"}).status_code == 200
    r = owner.post("/api/groups", json={"name": "超出上限"})
    assert r.status_code == 400 and str(MY_GROUPS_MAX) in r.json["error"]


def test_group_search_hides_joined_flag_and_full(app):
    owner, seeker = browser(app, "pat_grp"), browser(app, "quinn_grp")
    gid = _make_group(owner, "词汇突击队")
    found = seeker.get("/api/groups/search?q=词汇突击").json["groups"]
    assert [g["id"] for g in found] == [gid]
    assert found[0]["joined"] is False and found[0]["full"] is False
    seeker.post(f"/api/groups/{gid}/join")
    found = seeker.get("/api/groups/search?q=词汇突击队").json["groups"]
    assert found[0]["joined"] is True
    assert seeker.get("/api/groups/search?q=").status_code == 400
    assert seeker.get("/api/groups/search?q=" + "x" * 33).status_code == 400


def test_group_dissolve_owner_only_cascades(app):
    owner, member = browser(app, "rob_grp"), browser(app, "sam_grp")
    gid = _make_group(owner, "临别试验组")
    member.post(f"/api/groups/{gid}/join")

    assert member.post(f"/api/groups/{gid}/dissolve").status_code == 403
    assert owner.post(f"/api/groups/{gid}/dissolve").json["dissolved"] is True
    assert owner.get(f"/api/groups/{gid}").status_code == 404
    with db() as conn:
        left = conn.execute("SELECT COUNT(*) c FROM group_member WHERE group_id=?", (gid,)).fetchone()["c"]
    assert left == 0


def _active_challenges(browser, gid):
    return browser.get(f"/api/groups/{gid}").json["challenges"]


def test_group_challenge_validation_and_active_cap(app):
    owner = browser(app, "tina_grp")
    gid = _make_group(owner, "挑战验证组")
    body = {"kind": "words_target", "days": 7, "target_words": 500}

    bad_kind = dict(body, kind="sprint")
    assert owner.post(f"/api/groups/{gid}/challenge", json=bad_kind).status_code == 400
    outsider = browser(app, "uma_grp")
    assert outsider.post(f"/api/groups/{gid}/challenge", json=body).status_code == 403

    for _ in range(ACTIVE_CHALLENGES_MAX):
        r = owner.post(f"/api/groups/{gid}/challenge", json=dict(body, days=30))
        assert r.status_code == 200
    r = owner.post(f"/api/groups/{gid}/challenge", json=body)
    assert r.status_code == 400 and "上限" in r.json["error"]


def test_daily_challenge_scores_derive_from_source_table(app):
    owner, mate, outsider = browser(app, "victor_grp"), browser(app, "wally_grp"), browser(app, "xena_grp")
    gid = _make_group(owner, "每日挑战组")
    mate.post(f"/api/groups/{gid}/join")
    owner.post(f"/api/groups/{gid}/challenge", json={"kind": "daily", "days": 3})

    challenge = _active_challenges(owner, gid)[0]
    end_day = date.fromisoformat(challenge["expires_at"])
    assert (end_day - date.today()).days == 3                # 到期日 = 创建日 + days
    assert challenge["created_by"] == "victor_grp" and challenge["active"] is True

    inside_end = challenge["expires_at"]                      # 到期当天仍计入
    beyond_end = (end_day + timedelta(days=1)).isoformat()
    start_day = challenge["created_at"][:10]                  # 服务端按日切窗
    yesterday_out = (date.fromisoformat(start_day) - timedelta(days=1)).isoformat()
    with db() as conn:
        rows = [
            # owner：窗口内两日累计 60+50
            (day_iso(0), uid_of(owner), "test_words", 60, 100),
            (inside_end, uid_of(owner), "test_words", 50, 100),
            # mate：仅到期次日的一份，应被排除
            (beyond_end, uid_of(mate), "test_words", 95, 100),
            # 窗口开启之前的历史成绩不计
            (yesterday_out, uid_of(mate), "test_words", 88, 100),
            # 非成员的成绩永远不进组内榜单
            (day_iso(0), uid_of(outsider), "test_words", 99, 100),
        ]
        for day, user, lk, score, total in rows:
            conn.execute(
                "INSERT OR REPLACE INTO daily_challenge(day,user,list_key,score,total,detail,completed_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (day, user, lk, score, total, "[]", now_iso()))

    challenge = _active_challenges(mate, gid)[0]
    scores = {s["name"]: s["value"] for s in challenge["scores"]}
    counts = challenge["played_counts"]
    assert scores == {"victor_grp": 110}
    assert counts[uid_of(owner)] == 2
    assert all(s["name"] != "wally_grp" and s["name"] != "xena_grp" for s in challenge["scores"])


def test_words_target_challenge_merges_two_sources_and_ranks(app):
    owner, mate = browser(app, "yuri_grp"), browser(app, "zara_grp")
    gid = _make_group(owner, "词量目标组")
    mate.post(f"/api/groups/{gid}/join")
    created = owner.post(f"/api/groups/{gid}/challenge",
                         json={"kind": "words_target", "days": 5, "target_words": 50})
    assert created.status_code == 200

    with db() as conn:
        # mate：听打末答对 20 + 背诵答对 15 = 35 > owner 的 30
        conn.execute(
            "INSERT INTO daily_practice_log(day,user,practice_mode,new_count,review_count,"
            "first_right_count,first_wrong_count,final_right_count,skipped_count) VALUES(?,?,?,?,?,?,?,?,?)",
            (day_iso(0), uid_of(mate), "assisted", 0, 25, 22, 3, 20, 0))
        conn.execute("INSERT INTO daily_log(day,user,memorize_right,memorize_wrong) VALUES(?,?,?,?)",
                     (day_iso(0), uid_of(mate), 15, 1))
        conn.execute(
            "INSERT INTO daily_practice_log(day,user,practice_mode,new_count,review_count,"
            "first_right_count,first_wrong_count,final_right_count,skipped_count) VALUES(?,?,?,?,?,?,?,?,?)",
            (day_iso(0), uid_of(owner), "transcribe", 5, 0, 30, 0, 30, 0))

    challenge = _active_challenges(mate, gid)[0]
    assert challenge["target_words"] == 50 and challenge["played_counts"] is None
    assert [(s["name"], s["value"]) for s in challenge["scores"]] == [
        ("zara_grp", 35), ("yuri_grp", 30)]


def test_expired_challenge_flags_inactive_but_still_scores(app):
    owner = browser(app, "abel_grp")
    gid = _make_group(owner, "过期挑战组")
    owner.post(f"/api/groups/{gid}/challenge", json={"kind": "daily", "days": 2})
    created_past = (date.today() - timedelta(days=3)).isoformat()
    ended_past = (date.today() - timedelta(days=1)).isoformat()
    with db() as conn:
        # 把整条挑战挪回"三天前发起、昨天到期"的真实时序：过期不等于删除，
        # 窗口内的历史战果必须还能查到
        conn.execute("UPDATE group_challenge SET created_at=?, expires_at=? "
                     "WHERE created_at LIKE ? AND group_id=?",
                     (f"{created_past}T10:00:00", ended_past, f"{date.today().isoformat()}%", gid))
        conn.execute("INSERT OR REPLACE INTO daily_challenge(day,user,list_key,score,total,detail,"
                     "completed_at) VALUES(?,?,?,?,?,?,?)",
                     (ended_past, uid_of(owner), "test_words", 77, 100, "[]", now_iso()))
        conn.execute("INSERT OR REPLACE INTO daily_challenge(day,user,list_key,score,total,detail,"
                     "completed_at) VALUES(?,?,?,?,?,?,?)",
                     (date.today().isoformat(), uid_of(owner), "test_words", 55, 100, "[]", now_iso()))
    challenge = _active_challenges(owner, gid)[0]
    assert challenge["active"] is False
    assert challenge["scores"][0]["value"] == 77             # 只统计窗口内的那天，今天的不算
