"""游客身份、账户会话与响应 Cookie。"""
import hashlib
import re
import secrets
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone

from flask import g, jsonify, make_response, request

from .config import (
    AUTH_COOKIE_SECURE,
    AUTH_SESSION_DAYS,
    COOKIE,
    CSRF_COOKIE,
    SESSION_COOKIE,
)
from .db import db

_USER_ID_RE = re.compile(r"^[0-9a-z]{32}$")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def valid_user_id(value):
    return isinstance(value, str) and bool(_USER_ID_RE.fullmatch(value.lower()))


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _cookie_options(max_age):
    return {"max_age": max_age, "httponly": True, "samesite": "Lax", "secure": AUTH_COOKIE_SECURE}


def _csrf_cookie_options(max_age):
    return {"max_age": max_age, "httponly": False, "samesite": "Lax", "secure": AUTH_COOKIE_SECURE}


def _account_exists(user_id):
    with db() as conn:
        return conn.execute("SELECT 1 FROM account WHERE user_id=?", (user_id,)).fetchone() is not None


# last_seen_at 写入节流：同一会话至多每 90 秒落盘一次，避免每个请求一次写放大
_LAST_SEEN_INTERVAL = 90


def _session_identity():
    """请求内缓存 + 节流落盘。before_request 与路由各查一次的历史已消除。"""
    if hasattr(g, "dict_session_identity"):
        return g.dict_session_identity
    g.dict_session_identity = _load_session_identity()
    return g.dict_session_identity


def _load_session_identity():
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        return None
    token = token_hash(raw_token)
    with db() as conn:
        row = conn.execute("""
            SELECT s.user_id, s.csrf_token, s.expires_at, s.last_seen_at, a.username
            FROM auth_session s JOIN account a ON a.user_id=s.user_id
            WHERE s.token_hash=? AND a.disabled_at IS NULL
        """, (token,)).fetchone()
        if not row:
            return None
        now = now_iso()
        if row["expires_at"] <= now:
            conn.execute("DELETE FROM auth_session WHERE token_hash=?", (token,))
            return None
        if (row["last_seen_at"] or "") <= _past_iso(_LAST_SEEN_INTERVAL):
            conn.execute("UPDATE auth_session SET last_seen_at=? WHERE token_hash=?", (now, token))
    return {
        "user_id": row["user_id"], "username": row["username"],
        "csrf_token": row["csrf_token"], "authenticated": True,
    }


def _past_iso(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def legacy_account_protected():
    """旧 URL 不能绕过已认领账户；有效会话仍优先。"""
    if _session_identity() is not None:
        return False
    user_id = request.args.get("u", "").lower()
    return valid_user_id(user_id) and _account_exists(user_id)


def get_identity():
    if hasattr(g, "dict_identity"):
        return g.dict_identity

    identity = _session_identity()
    if identity is not None:
        g.dict_identity = identity
        return identity

    legacy_id = request.args.get("u", "").lower()
    cookie_id = request.cookies.get(COOKIE, "").lower()
    for user_id in (legacy_id, cookie_id):
        if valid_user_id(user_id) and not _account_exists(user_id):
            g.dict_identity = {"user_id": user_id, "username": None, "csrf_token": None, "authenticated": False}
            return g.dict_identity

    g.dict_identity = {
        "user_id": uuid_mod.uuid4().hex, "username": None,
        "csrf_token": None, "authenticated": False,
    }
    return g.dict_identity


def get_user():
    return get_identity()["user_id"]


def get_cookie_identity():
    """只认会话或 dict_u Cookie 的身份解析；PK 座位专用。

    ?u= 是旧进度页的兼容通道，值来自 URL：座位归属若接受它，
    知道别人 uuid 的人就能顶替其对局身份。这里刻意不读该参数。
    """
    identity = _session_identity()
    if identity is not None:
        return identity
    cached = getattr(g, "dict_cookie_identity", None)
    if cached is not None:
        return cached
    cookie_id = request.cookies.get(COOKIE, "").lower()
    if valid_user_id(cookie_id) and not _account_exists(cookie_id):
        resolved = {"user_id": cookie_id, "username": None, "csrf_token": None,
                    "authenticated": False}
    else:
        resolved = {"user_id": uuid_mod.uuid4().hex, "username": None,
                    "csrf_token": None, "authenticated": False}
    g.dict_cookie_identity = resolved
    return resolved


def authenticated():
    return get_identity()["authenticated"]


def identity_payload():
    identity = get_identity()
    return {
        "authenticated": identity["authenticated"],
        "guest": not identity["authenticated"],
        "username": identity["username"],
        "account_protected": legacy_account_protected(),
    }


def issue_session(conn, user_id):
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=AUTH_SESSION_DAYS)
    conn.execute("""
        INSERT INTO auth_session(token_hash, user_id, csrf_token, created_at, expires_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (token_hash(raw_token), user_id, csrf_token, issued_at.isoformat(), expires_at.isoformat(), issued_at.isoformat()))
    return raw_token, csrf_token


def set_session(response, raw_token, csrf_token):
    response.set_cookie(SESSION_COOKIE, raw_token, **_cookie_options(AUTH_SESSION_DAYS * 86400))
    response.set_cookie(CSRF_COOKIE, csrf_token, **_csrf_cookie_options(AUTH_SESSION_DAYS * 86400))
    return response


def clear_session(response):
    response.delete_cookie(SESSION_COOKIE, samesite="Lax", secure=AUTH_COOKIE_SECURE)
    return response


def csrf_valid():
    token = request.headers.get("X-CSRF-Token", "")
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    if not token or not secrets.compare_digest(token, cookie_token):
        return False
    identity = get_identity()
    return not identity["authenticated"] or secrets.compare_digest(token, identity["csrf_token"])


def display_name(conn, user):
    """公开场合（排行榜/对战/挑战）的展示名：登录用户用用户名，游客用 游客xxxx。"""
    row = conn.execute("SELECT username FROM account WHERE user_id=?", (user,)).fetchone()
    if row:
        return row["username"]
    tail = "".join(ch for ch in user if ch.isalnum())[:4] or "0000"
    return f"游客{tail}"


def display_names(conn, users):
    """批量展示名。游客名取 id 尾 4 位——与 challenge 冲刺比分榜的历史口径一致，
    游客 ID 恒为 32 位 hex，该约定不随时间变化。"""
    ids = list(dict.fromkeys(users))   # 去重保序
    named = {}
    if ids:
        named = {r["user_id"]: r["username"] for r in conn.execute(
            f"SELECT user_id, username FROM account WHERE user_id IN ({','.join('?' * len(ids))})",
            ids)}
    out = {}
    for uid in ids:
        if uid in named:
            out[uid] = named[uid]
            continue
        tail = "".join(ch for ch in uid if ch.isalnum())[:4] or "0000"
        out[uid] = f"游客{tail}"
    return out


def resp(obj, status=200, identity=None):
    """JSON 响应：游客身份和 CSRF token 保存在 Cookie，不再写入 URL。

    identity 供座位类端点显式传入（如 PK 只认 Cookie 的 get_cookie_identity），
    保证"业务视角的身份"与"Cookie 下发的身份"是同一个；缺省走完整解析。
    """
    ident = identity or get_identity()
    payload = {**obj, "user": ident["user_id"]}
    response = make_response(jsonify(payload), status)
    if not ident["authenticated"]:
        response.set_cookie(COOKIE, ident["user_id"], **_cookie_options(31536000))
    csrf_token = ident["csrf_token"] or request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(24)
    response.set_cookie(CSRF_COOKIE, csrf_token, **_csrf_cookie_options(AUTH_SESSION_DAYS * 86400))
    return response
