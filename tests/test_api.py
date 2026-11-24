import io
import json

from database import get_panel_account_by_username


def create_moderator(account_service, username="moderator", password="moderator-password"):
    created, error = account_service.create_account(
        actor_session={"role": "superadmin", "username": "root"},
        username=username,
        password=password,
        role="moderator",
    )
    assert error is None
    return created


def set_permissions(account_service, account_id, permissions):
    updated, error = account_service.update_moderator_permissions(
        actor_session={"role": "superadmin", "username": "root"},
        account_id=account_id,
        permissions=permissions,
    )
    assert error is None
    return updated


def login_as(client, username, password):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    body = response.get_json() or {}
    assert response.status_code == 200, body
    return body["session"]["csrf_token"]


def test_endpoints_require_authentication(client):
    for path in ("/api/auth/session", "/api/events", "/api/accounts", "/api/audit-logs"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.get_json()["message"] == "Authentication required"


def test_login_rejects_cross_origin_request(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "root", "password": "root-password"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert "origin" in response.get_json()["message"].lower()


def test_same_origin_login_is_allowed(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "root", "password": "root-password"},
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 200


def test_json_content_type_is_required(client, login):
    login()
    csrf_token = client.get("/api/auth/session").get_json()["session"]["csrf_token"]

    response = client.post(
        "/api/accounts",
        data="not-json",
        content_type="text/plain",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 415


def test_unsafe_request_requires_csrf_header(client, login):
    login()

    response = client.post(
        "/api/sessions/revoke-all",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 403
    assert response.get_json()["message"] == "CSRF validation failed"


def test_moderator_cannot_escalate_permissions(client, account_service):
    moderator = create_moderator(account_service)
    login_as(client, "moderator", "moderator-password")

    for permission in (
        "accounts_view",
        "moderator_manage",
        "database_regenerate",
    ):
        updated = set_permissions(
            account_service, moderator["id"], {permission: True}
        )
        assert updated["permissions"][permission] is False


def test_moderator_cannot_create_accounts(client, account_service):
    create_moderator(account_service)
    csrf_token = login_as(client, "moderator", "moderator-password")

    response = client.post(
        "/api/accounts",
        json={
            "username": "another",
            "password": "another-password",
            "role": "admin",
        },
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 403


def test_moderator_with_audit_permission_can_read_audit_log(client, account_service):
    moderator = create_moderator(account_service)
    set_permissions(account_service, moderator["id"], {"audit_view": True})
    login_as(client, "moderator", "moderator-password")

    response = client.get("/api/audit-logs")

    assert response.status_code == 200
    assert "events" in response.get_json()


def test_moderator_without_audit_permission_is_forbidden(client, account_service):
    create_moderator(account_service)
    login_as(client, "moderator", "moderator-password")

    response = client.get("/api/audit-logs")

    assert response.status_code == 403


def test_mousetrap_logs_validate_server_id(client, login):
    csrf_token = login()

    response = client.get("/api/servers/not-a-snowflake/mousetrap/logs")

    assert response.status_code == 400
    assert "Server id" in response.get_json()["message"]


def test_unknown_server_returns_not_found(client, login):
    login()

    response = client.get("/api/servers/123456789012345670/channels")

    assert response.status_code == 404


def test_dm_send_requires_valid_user_id(client, login):
    csrf_token = login()

    response = client.post(
        "/api/direct-messages/send",
        data={"user_id": "bad", "content": "hello"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 400
    assert "user_id" in response.get_json()["message"]


def test_dm_send_rejects_too_many_attachments(client, login, settings):
    csrf_token = login()
    files = [
        (io.BytesIO(b"x"), f"file-{index}.txt") for index in range(settings.max_dm_attachments + 1)
    ]

    try:
        response = client.post(
            "/api/direct-messages/send",
            data={"user_id": "223456789012345678", "content": "hello", "files": files},
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": csrf_token},
        )
    finally:
        for handle, _ in files:
            handle.close()

    assert response.status_code == 400


def test_dm_send_rejects_oversized_file(client, login, settings):
    csrf_token = login()

    with io.BytesIO(b"a" * (settings.max_dm_file_bytes + 1)) as oversized:
        response = client.post(
            "/api/direct-messages/send",
            data={
                "user_id": "223456789012345678",
                "content": "",
                "files": (oversized, "large.bin"),
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": csrf_token},
        )

    assert response.status_code == 413


def test_dm_send_accepts_valid_payload(client, login, account_service):
    csrf_token = login()

    with io.BytesIO(b"hello") as upload:
        response = client.post(
            "/api/direct-messages/send",
            data={
                "user_id": "223456789012345678",
                "content": "hello there",
                "files": (upload, "hello.txt"),
            },
            content_type="multipart/form-data",
            headers={"X-CSRF-Token": csrf_token},
        )

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_unknown_route_returns_generic_json_error(client):
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    body = response.get_json()
    assert body["message"] == "Not found"
    assert "traceback" not in json.dumps(body).lower()


def test_security_headers_are_present(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_account_password_change_revokes_other_sessions(client, account_service, db_path):
    create_moderator(account_service)
    db_cookie = login_as(client, "moderator", "moderator-password")

    # A second independent session for the same account.
    other_client = client.application.test_client()
    login_as(other_client, "moderator", "moderator-password")

    response = client.post(
        "/api/accounts/change-own-password",
        json={
            "current_password": "moderator-password",
            "new_password": "new-moderator-password",
        },
        headers={"X-CSRF-Token": db_cookie},
    )

    assert response.status_code == 200
    assert response.get_json()["account"]["revoked_sessions"] >= 1

    # The current session remains valid, others are revoked.
    assert client.get("/api/auth/session").status_code == 200
    assert other_client.get("/api/auth/session").status_code == 401

    row = get_panel_account_by_username(db_path, "moderator")
    assert row is not None
