import json
import threading

import pytest
from werkzeug.serving import make_server
from websockets.sync.client import connect

from accounts import AccountService
from security import LoginRateLimiter
from wsback import _query_limit, _run_send_loop, _send_json


@pytest.fixture()
def live_server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _login_cookie(client, username="root", password="root-password"):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return client.get_cookie("panel_session").value


def _connect(live_server, cookie, path="/ws/health", origin=None):
    port = live_server.server_port
    return connect(
        f"ws://127.0.0.1:{port}{path}",
        origin=origin or f"http://127.0.0.1:{port}",
        additional_headers={"Cookie": f"panel_session={cookie}"} if cookie else None,
        open_timeout=5,
        close_timeout=5,
        max_size=1024 * 1024,
    )


def test_websocket_rejects_untrusted_origin(live_server, client):
    cookie = _login_cookie(client)

    with _connect(live_server, cookie, origin="https://evil.example") as ws:
        message = json.loads(ws.recv(timeout=5))

    assert message["status"] == "error"
    assert "origin" in message["message"].lower()


def test_websocket_requires_authentication(live_server):
    with _connect(live_server, None) as ws:
        message = json.loads(ws.recv(timeout=5))

    assert message["status"] == "error"
    assert "authentication" in message["message"].lower()


def test_websocket_health_streams_for_authenticated_session(live_server, client):
    cookie = _login_cookie(client)

    with _connect(live_server, cookie) as ws:
        message = json.loads(ws.recv(timeout=5))

    assert message["status"] == "ok"
    assert message["bot_connected"] is True
    assert message["last_sequence"] == 42


def test_websocket_events_requires_permission(live_server, client, account_service):
    created, error = account_service.create_account(
        actor_session={"role": "superadmin", "username": "root"},
        username="moderator",
        password="moderator-password",
        role="moderator",
    )
    assert error is None
    cookie = _login_cookie(client, "moderator", "moderator-password")

    with _connect(live_server, cookie, path="/ws/events") as ws:
        message = json.loads(ws.recv(timeout=5))

    assert message["status"] == "error"
    assert message["message"] == "Forbidden"


def test_websocket_refresh_revokes_session(account_service):
    service = AccountService(
        db_path=account_service.db_path,
        superadmin_username="root",
        superadmin_password="root-password",
        settings=account_service.settings,
        audit_service=account_service.audit,
        rate_limiter=LoginRateLimiter(),
    )
    session = service.login("root", "root-password").session
    environ = {
        "HTTP_COOKIE": f"panel_session={session['token']}",
    }
    assert service.authenticate_ws_environ(environ) is not None

    service.revoke_session_token(session["token"])
    assert service.authenticate_ws_environ(environ) is None


class _FakeSocket:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, payload):
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(payload)


def test_ws_send_json_never_raises_on_disconnect():
    assert _send_json(_FakeSocket(fail=True), {"status": "ok"}) is False
    assert _send_json(_FakeSocket(), {"status": "ok"}) is True


def test_ws_loop_stops_when_session_is_invalid():
    ws = _FakeSocket()
    calls = {"count": 0}

    def refresh():
        calls["count"] += 1
        return False

    _run_send_loop(ws, refresh, lambda: {"status": "ok"}, 0.01)

    assert calls["count"] == 1
    assert len(ws.sent) == 1
    assert "no longer valid" in ws.sent[0]


def test_ws_loop_stops_safely_when_socket_closes():
    ws = _FakeSocket(fail=True)

    _run_send_loop(ws, lambda: True, lambda: {"status": "ok"}, 0.01)

    assert ws.sent == []


def test_ws_query_limit_is_bounded():
    environ = {"QUERY_STRING": "limit=100000"}
    assert _query_limit(environ, default=20, maximum=50) == 50
    assert _query_limit({"QUERY_STRING": "limit=nope"}, 20, 50) == 20
    assert _query_limit({"QUERY_STRING": "limit=0"}, 20, 50) == 1
