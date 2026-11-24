import sqlite3

from audit import ACTION_LOGIN_SUCCESS
from database import get_panel_account_by_username


def test_login_returns_session_and_csrf_token(client, login):
    csrf_token = login()

    response = client.get("/api/auth/session")
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["session"]["role"] == "superadmin"
    assert len(csrf_token) == 64
    assert "token" not in body["session"]


def test_session_token_is_stored_hashed(client, login, db_path):
    csrf_token = login()
    assert csrf_token

    raw_cookie = client.get_cookie("panel_session")
    assert raw_cookie is not None
    raw_token = raw_cookie.value

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT token_hash FROM panel_sessions").fetchall()
    columns = [row[1] for row in conn.execute("PRAGMA table_info(panel_sessions)")]
    conn.close()

    assert "token" not in columns
    assert "token_hash" in columns
    assert len(rows) == 1
    assert rows[0][0] != raw_token
    assert len(rows[0][0]) == 64


def test_invalid_login_is_generic_and_does_not_authenticate(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "root", "password": "wrong"},
    )

    assert response.status_code == 401
    assert response.get_json()["message"] == "Invalid credentials"
    assert client.get_cookie("panel_session") is None


def test_moderator_login_rate_limited_by_username(account_service, settings):
    from security import LoginRateLimiter

    limiter = LoginRateLimiter(
        max_attempts=2,
        window_seconds=300,
        block_seconds=60,
    )
    service = type(account_service)(
        db_path=account_service.db_path,
        superadmin_username="root",
        superadmin_password="root-password",
        settings=settings,
        audit_service=account_service.audit,
        rate_limiter=limiter,
    )
    service.create_account(
        actor_session={"role": "superadmin", "username": "root"},
        username="moderator",
        password="moderator-password",
        role="moderator",
    )

    first = service.login("moderator", "wrong-password", client_ip="10.0.0.1")
    second = service.login("moderator", "wrong-password", client_ip="10.0.0.1")
    blocked = service.login("moderator", "wrong-password", client_ip="10.0.0.1")

    assert first.status_code == 401
    assert second.status_code == 401
    assert blocked.status_code == 429
    assert blocked.retry_after and blocked.retry_after > 0

    # The block is temporary, not a permanent account lock.
    limiter._blocked_until.clear()
    recovered = service.login(
        "moderator", "moderator-password", client_ip="10.0.0.1"
    )
    assert recovered.status_code == 200
    assert recovered.session is not None


def test_password_is_limited_to_72_bytes(account_service):
    created, error = account_service.create_account(
        actor_session={"role": "superadmin", "username": "root"},
        username="longpass",
        password="a" * 73,
        role="moderator",
    )

    assert created is None
    assert "72" in error


def test_password_hash_roundtrip(account_service, db_path):
    account_service.create_account(
        actor_session={"role": "superadmin", "username": "root"},
        username="operator",
        password="operator-password",
        role="moderator",
    )

    row = get_panel_account_by_username(db_path, "operator")
    assert row is not None
    assert row["password_hash"] != "operator-password"
    assert row["password_hash"].startswith("$2")


def test_logout_requires_csrf_and_revokes_session(client, login, db_path):
    csrf_token = login()
    assert csrf_token

    without_csrf = client.post("/api/auth/logout")
    assert without_csrf.status_code == 403

    with_csrf = client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": csrf_token}
    )
    assert with_csrf.status_code == 200

    conn = sqlite3.connect(db_path)
    revoked = conn.execute(
        "SELECT revoked FROM panel_sessions"
    ).fetchall()
    conn.close()
    assert revoked == [(1,)]


def test_login_audit_event_is_recorded(account_service, audit_service):
    account_service.login("root", "root-password", client_ip="127.0.0.1")
    events = audit_service.list_events(page=1, page_size=10)["events"]

    assert any(event["action"] == ACTION_LOGIN_SUCCESS for event in events)
    assert all("password" not in str(event["metadata"]).lower() for event in events)


def test_failed_login_does_not_record_password(account_service, audit_service):
    password = "super-secret-wrong-password"
    account_service.login("root", password, client_ip="127.0.0.1")

    events = audit_service.list_events(page=1, page_size=10)["events"]
    serialized = str([event["metadata"] for event in events])
    assert password not in serialized
    assert "client_ip" in serialized
