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
    now_iso,
    resp,
    set_session,
    token_hash,
    valid_user_id,
)
from .config import AUTH_RATE_LIMIT_ATTEMPTS, AUTH_RATE_LIMIT_SECONDS, COOKIE
from .db import db
from .friends import at_friends_cap, record_activity

bp = Blueprint("auth_routes", __name__, url_prefix="/api/auth")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
_NEW_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{6,32}$")
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_PASSWORD_MIN_LENGTH = 6
_PASSWORD_MAX_LENGTH = 128


def _body():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _username(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if not (_USERNAME_RE.fullmatch(value) or (len(value) <= 254 and _EMAIL_RE.fullmatch(value))):
        return None
    return value


def _new_username(value):
    """新账户可用 6 位用户名或邮箱；登录兼容原有 3–5 位用户名。"""
    value = _username(value)
    if not value:
        return None
    return value if _EMAIL_RE.fullmatch(value) or _NEW_USERNAME_RE.fullmatch(value) else None


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
    username = _new_username(data.get("username"))
    password = _password(data.get("password"))
    if not username:
        return jsonify({"error": "请输入 6–32 位用户名（字母、数字或下划线），或有效邮箱"}), 400
    if not password:
        return jsonify({"error": "密码至少需要 6 位，最多 128 位"}), 400

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
            VALUES (?, ?, ?, ?)
        """, (user_id, username, generate_password_hash(password, method="scrypt"), now_iso()))
        raw_token, csrf_token = issue_session(conn, user_id)
        _record_failure(conn, "register-ip", ip_key)
        # 邀请链接：注册即与邀请人结为好友（含把对方此前的单向申请一并确认）
        inviter = data.get("inviter")
        if isinstance(inviter, str) and valid_user_id(inviter):
            inviter_row = conn.execute(
                "SELECT 1 FROM account WHERE user_id=? AND disabled_at IS NULL",
                (inviter,)).fetchone()
            if inviter_row:
                pair = (user_id, inviter) if user_id < inviter else (inviter, user_id)
                # 邀请人好友已满则不建关系，注册本身照常成功
                if pair[0] != pair[1] and not at_friends_cap(conn, inviter):
                    conn.execute(
                        """INSERT INTO friend_relation(user_a,user_b,status,requested_by,
                                                      created_at,updated_at)
                           VALUES(?,?, 'accepted', ?, ?, ?)
                           ON CONFLICT(user_a,user_b) DO UPDATE SET
                               status='accepted', updated_at=excluded.updated_at""",
                        (*pair, inviter, now_iso(), now_iso()))
                    for who in (user_id, inviter):
                        record_activity(conn, who, "friend_join",
                                        {"with": inviter if who == user_id else user_id})

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
        conn.execute("UPDATE account SET last_login_at=? WHERE user_id=?", (now_iso(), row["user_id"]))
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
        return jsonify({"error": "新密码至少需要 6 位，最多 128 位"}), 400

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
