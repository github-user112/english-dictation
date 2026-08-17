from datetime import datetime, timedelta, timezone

from flask.testing import FlaskClient

from backend.db import db


def register(client, username="alice", password="correct horse battery staple"):
    return client.post("/api/auth/register", json={"username": username, "password": password})


def login(client, username="alice", password="correct horse battery staple"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_registration_claims_guest_progress_without_migration(client):
    guest = client.get("/api/auth/me").json["user"]
    with db() as conn:
        conn.execute("INSERT INTO word_state(user,list,item_id,status) VALUES(?,?,?,?)", (guest, "test_words", "hello", "learning"))

    response = register(client)

    assert response.status_code == 200
    assert response.json == {"authenticated": True, "guest": False, "username": "alice"}
    assert any("dict_session=" in value for value in response.headers.getlist("Set-Cookie"))
    with db() as conn:
        account = conn.execute("SELECT user_id, password_hash FROM account WHERE username='alice'").fetchone()
        progress = conn.execute("SELECT status FROM word_state WHERE user=? AND item_id='hello'", (guest,)).fetchone()
    assert account["user_id"] == guest
    assert account["password_hash"] != "correct horse battery staple"
    assert progress["status"] == "learning"


def test_registered_legacy_link_requires_login(app, client):
    guest = client.get("/api/auth/me").json["user"]
    assert register(client).status_code == 200

    visitor = app.test_client()
    response = visitor.get(f"/api/lists?u={guest}")

    assert response.status_code == 401
    assert response.json["account_protected"] is True


def test_login_uses_generic_failure_and_session(client):
    assert register(client, "alice_1").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200

    wrong_user = login(client, "missing", "wrong password that is long enough")
    wrong_password = login(client, "alice_1", "wrong password that is long enough")
    success = login(client, "alice_1")

    assert wrong_user.status_code == wrong_password.status_code == 401
    assert wrong_user.json == wrong_password.json == {"error": "用户名或密码错误"}
    assert success.status_code == 200
    assert client.get("/api/auth/me").json["username"] == "alice_1"


def test_account_validation_and_duplicate_username(client):
    assert register(client, "bad name").status_code == 400
    assert register(client, "short", "too short").status_code == 400
    assert register(client, "alice_2").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert register(client, "alice_2").status_code == 409


def test_password_change_revokes_other_sessions(app, client):
    old_password = "correct horse battery staple"
    new_password = "new correct horse battery staple"
    assert register(client, "alice_3", old_password).status_code == 200

    other = app.test_client()
    assert login(other, "alice_3", old_password).status_code == 200
    changed = client.post("/api/auth/change-password", json={
        "current_password": old_password, "new_password": new_password,
    })

    assert changed.status_code == 200
    assert other.get("/api/auth/me").json["authenticated"] is False
    assert client.post("/api/auth/logout").status_code == 200
    assert login(client, "alice_3", old_password).status_code == 401
    assert login(client, "alice_3", new_password).status_code == 200


def test_expired_session_becomes_guest(client):
    assert register(client, "alice_4").status_code == 200
    with db() as conn:
        conn.execute("UPDATE auth_session SET expires_at=?", ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json["authenticated"] is False
    assert response.json["guest"] is True


def test_state_changes_require_csrf_and_reject_bad_origin(app):
    browser = FlaskClient(app)
    browser.get("/api/auth/me")

    missing_csrf = browser.post("/api/memorize", json={"list": "test_words", "id": "hello", "right": True})
    bad_origin = browser.post("/api/auth/register", json={"username": "alice_5", "password": "correct horse battery staple"}, headers={"Origin": "https://attacker.example"})

    assert missing_csrf.status_code == 403
    assert bad_origin.status_code == 403


def test_failed_logins_are_rate_limited(client):
    for _ in range(5):
        assert login(client, "missing", "wrong password that is long enough").status_code == 401

    assert login(client, "missing", "wrong password that is long enough").status_code == 429
