"""并发回归测试：小组人数上限、小组活跃挑战数上限的竞态防护。

修复点：groups.py 的 api_join / api_create_challenge 使用 BEGIN IMMEDIATE
串行化 读检查-写入，防止并发请求突破人数/挑战数上限。
"""
import contextlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from flask.testing import FlaskClient

from backend.db import db
from backend.groups import ACTIVE_CHALLENGES_MAX, MEMBERS_DEFAULT_MAX

# 并发测试会批量注册，放宽注册速率限制
_REGISTER_RATE_LIMIT_PATCHES = [
    patch("backend.auth_routes.AUTH_RATE_LIMIT_ATTEMPTS", 10000),
    patch("backend.auth_routes.AUTH_RATE_LIMIT_SECONDS", 3600),
]

PASS = "correct horse battery staple"

CAP = ACTIVE_CHALLENGES_MAX


class CsrfClient(FlaskClient):
    """写请求自动携带 dict_csrf cookie 中的 token（模拟浏览器）。"""
    def open(self, *args, **kwargs):
        method = kwargs.get("method", "GET").upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = self.get_cookie("dict_csrf")
            if token:
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("X-CSRF-Token", token.value)
                kwargs["headers"] = headers
        return super().open(*args, **kwargs)


def _browser(app):
    b = CsrfClient(app)
    b.get("/api/auth/me")
    return b


def _register(app, name):
    b = _browser(app)
    # 并发测试会批量注册，放宽注册速率限制（同 IP 大量注册会触发 429）
    with contextlib.ExitStack() as stack:
        for p in _REGISTER_RATE_LIMIT_PATCHES:
            stack.enter_context(p)
        r = b.post("/api/auth/register", json={"username": name, "password": PASS})
    assert r.status_code == 200, r.json
    return b


def _csrf(b):
    token = b.get_cookie("dict_csrf")
    assert token, "需要 CSRF token"
    return token.value


def _make_group(app, name):
    b = _register(app, f"owner_{uuid4().hex[:8]}")
    r = b.post("/api/groups", json={"name": name})
    assert r.status_code == 200, r.json
    return r.json["id"]


def test_group_join_concurrent_cannot_exceed_cap(app):
    """N 个用户并发加入同一组，最终成员数不得超过 MEMBERS_DEFAULT_MAX。"""
    gid = _make_group(app, "并发上限组")
    n = MEMBERS_DEFAULT_MAX + 5
    users = [_register(app, f"joiner_{uuid4().hex[:8]}") for _ in range(n)]

    # 预先获取 CSRF token（GET /api/auth/me 在 barrier 前完成，避免所有线程阻塞等它）
    csrs = [_csrf(b) for b in users]
    barrier = Barrier(n)

    def hit(i, b, csrf):
        barrier.wait()
        return b.post(f"/api/groups/{gid}/join", headers={"X-CSRF-Token": csrf})

    with ThreadPoolExecutor(max_workers=max(32, n + 4)) as pool:
        results = list(pool.map(hit, range(n), users, csrs))

    success = sum(1 for r in results if r.status_code == 200)
    rejected = sum(1 for r in results if r.status_code == 400)
    assert success + rejected == n
    with db() as conn:
        cnt = conn.execute("SELECT COUNT(*) c FROM group_member WHERE group_id=?", (gid,)).fetchone()["c"]
    assert cnt <= MEMBERS_DEFAULT_MAX


def test_group_challenge_concurrent_cannot_exceed_cap(app):
    """N 个成员并发创建活跃挑战，最终活跃挑战数不得超过 ACTIVE_CHALLENGES_MAX。"""
    gid = _make_group(app, "并发挑战组")
    n = CAP + 3
    joiners = []
    for i in range(n):
        b = _register(app, f"conc_{uuid4().hex[:8]}")
        r = b.post(f"/api/groups/{gid}/join")
        assert r.status_code == 200, r.json
        joiners.append(b)

    csrs = [_csrf(b) for b in joiners]
    barrier = Barrier(n)

    def hit(i, b, csrf):
        barrier.wait()
        return b.post(
            f"/api/groups/{gid}/challenge",
            json={"kind": "words_target", "days": 7, "target_words": 50},
            headers={"X-CSRF-Token": csrf},
        )

    with ThreadPoolExecutor(max_workers=max(32, n + 4)) as pool:
        results = list(pool.map(hit, range(n), joiners, csrs))

    success = sum(1 for r in results if r.status_code == 200)
    rejected = sum(1 for r in results if r.status_code == 400)
    assert success + rejected == n
    with db() as conn:
        cnt = conn.execute(
            # 与 groups.py 的活跃判定一致：expires_at >= 今天
            "SELECT COUNT(*) c FROM group_challenge WHERE group_id=? AND expires_at>=?",
            (gid, date.today().isoformat()),
        ).fetchone()["c"]
    assert cnt <= CAP
