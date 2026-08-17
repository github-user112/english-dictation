"""账户注册、登录与会话管理接口。"""
import re
import time

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from .auth import (
    authenticated,
    clear_session,
    get_identity,
    identity_payload,
    issue_session,
    legacy_account_protected,
    resp,
    set_session,
    token_hash,
)
from .config import AUTH_RATE_LIMIT_ATTEMPTS, AUTH_RATE_LIMIT_SECONDS, COOKIE
from .db import db

bp = Blueprint("auth_routes", __name__, url_prefix="/api/auth")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
_PASSWORD_MIN_LENGTH = 12
_PASSWORD_MAX_LENGTH = 128


def _body():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _username(value):
    if not isinstance(value, str) or not _USERNAME_RE.fullmatch(value):
        return None
    return value.lower()


def _password(value):
    if not isinstance(value, str) or not _PASSWORD_MIN_LENGTH <= len(value) <= _PASSWORD_MAX_LENGTH:
        return None
    return value


def _client_ip():
    return request.remote_addr or "unknown"


def _rate_limited(conn, scope, key):
    now = int(time.time())
    row = conn.execute(
        "SELECT window_started_at, attempts FROM auth_rate_limit WHERE scope=? AND key=?",
        (scope, key),
    ).fetchone()
    if not row:
        return False
    if now - row["window_started_at"] >= AUTH_RATE_LIMIT_SECONDS:
        conn.execute("DELETE FROM auth_rate_limit WHERE scope=? AND key=?", (scope, key))
        return False
    return row["attempts"] >= AUTH_RATE_LIMIT_ATTEMPTS


def _record_failure(conn, scope, key):
    now = int(time.time())
    row = conn.execute(
        "SELECT window_started_at, attempts FROM auth_rate_limit WHERE scope=? AND key=?",
        (scope, key),
    ).fetchone()
    if not row or now - row["window_started_at"] >= AUTH_RATE_LIMIT_SECONDS:
        conn.execute("""
            INSERT INTO auth_rate_limit(scope, key, window_started_at, attempts)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(scope, key) DO UPDATE SET window_started_at=excluded.window_started_at, attempts=1
        """, (scope, key, now))
    else:
        conn.execute(
            "UPDATE auth_rate_limit SET attempts=attempts+1 WHERE scope=? AND key=?",
            (scope, key),
        )


def _clear_failures(conn, scope, key):
    conn.execute("DELETE FROM auth_rate_limit WHERE scope=? AND key=?", (scope, key))


def _too_many_attempts():
    return jsonify({"error": "尝试次数过多，请稍后再试"}), 429


def _invalid_credentials():
    return jsonify({"error": "用户名或密码错误"}), 401


@bp.get("/me")
def me():
    return resp(identity_payload())


@bp.post("/register")
def register():
    if authenticated():
        return jsonify({"error": "当前已登录账户"}), 409
    if legacy_account_protected():
        return jsonify({"error": "该学习档案已受账户保护，请登录", "account_protected": True}), 401
    data = _body()
    username = _username(data.get("username"))
    password = _password(data.get("password"))
    if not username:
        return jsonify({"error": "用户名应为 3–32 位字母、数字或下划线"}), 400
    if not password:
        return jsonify({"error": "密码长度应为 12–128 位"}), 400

    user_id = get_identity()["user_id"]
    ip_key = _client_ip()
    with db() as conn:
        if _rate_limited(conn, "register-ip", ip_key):
            return _too_many_attempts()
        existing = conn.execute("SELECT 1 FROM account WHERE username=?", (username,)).fetchone()
        if existing:
            _record_failure(conn, "register-ip", ip_key)
            return jsonify({"error": "用户名已被使用"}), 409
        conn.execute("""
            INSERT INTO account(user_id, username, password_hash, created_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (user_id, username, generate_password_hash(password, method="scrypt")))
        raw_token, csrf_token = issue_session(conn, user_id)
        _record_failure(conn, "register-ip", ip_key)

    response = jsonify({"authenticated": True, "guest": False, "username": username})
    response.delete_cookie(COOKIE, samesite="Lax")
    return set_session(response, raw_token, csrf_token)


@bp.post("/login")
def login():
    data = _body()
    username = _username(data.get("username"))
    password = data.get("password")
    username_key = username or "invalid"
    ip_key = _client_ip()
    with db() as conn:
        if _rate_limited(conn, "login-ip", ip_key) or _rate_limited(conn, "login-user", username_key):
            return _too_many_attempts()
        row = conn.execute(
            "SELECT user_id, password_hash FROM account WHERE username=? AND disabled_at IS NULL",
            (username_key,),
        ).fetchone()
        if not row or not isinstance(password, str) or not check_password_hash(row["password_hash"], password):
            _record_failure(conn, "login-ip", ip_key)
            _record_failure(conn, "login-user", username_key)
            return _invalid_credentials()
        raw_token, csrf_token = issue_session(conn, row["user_id"])
        conn.execute("UPDATE account SET last_login_at=datetime('now') WHERE user_id=?", (row["user_id"],))
        _clear_failures(conn, "login-ip", ip_key)
        _clear_failures(conn, "login-user", username_key)

    return set_session(jsonify({"authenticated": True, "guest": False, "username": username_key}), raw_token, csrf_token)


@bp.post("/logout")
def logout():
    raw_token = request.cookies.get("dict_session")
    if raw_token:
        with db() as conn:
            conn.execute("DELETE FROM auth_session WHERE token_hash=?", (token_hash(raw_token),))
    response = jsonify({"authenticated": False, "guest": True, "username": None})
    response.delete_cookie("dict_session", samesite="Lax")
    return response


@bp.post("/change-password")
def change_password():
    if not authenticated():
        return jsonify({"error": "请先登录"}), 401
    data = _body()
    current_password = data.get("current_password")
    new_password = _password(data.get("new_password"))
    if not new_password:
        return jsonify({"error": "新密码长度应为 12–128 位"}), 400

    identity = get_identity()
    with db() as conn:
        row = conn.execute("SELECT password_hash FROM account WHERE user_id=?", (identity["user_id"],)).fetchone()
        if not row or not isinstance(current_password, str) or not check_password_hash(row["password_hash"], current_password):
            return jsonify({"error": "当前密码错误"}), 400
        conn.execute("UPDATE account SET password_hash=? WHERE user_id=?", (
            generate_password_hash(new_password, method="scrypt"), identity["user_id"],
        ))
        conn.execute("DELETE FROM auth_session WHERE user_id=?", (identity["user_id"],))
        raw_token, csrf_token = issue_session(conn, identity["user_id"])

    return set_session(jsonify({"authenticated": True, "guest": False, "username": identity["username"]}), raw_token, csrf_token)
