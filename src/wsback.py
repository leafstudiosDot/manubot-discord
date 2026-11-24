import json
import logging
import time
from urllib.parse import parse_qs

LOGGER = logging.getLogger(__name__)

SESSION_RECHECK_SECONDS = 5.0


def _query_limit(environ: dict, default: int, maximum: int) -> int:
    query = parse_qs(environ.get("QUERY_STRING", ""))
    try:
        requested = int(query.get("limit", [str(default)])[0])
    except (TypeError, ValueError):
        requested = default
    return max(1, min(requested, maximum))


def _send_json(ws, payload: dict | list) -> bool:
    try:
        ws.send(json.dumps(payload))
        return True
    except Exception:
        # A closed or half-closed socket must never crash the worker.
        return False


def _run_send_loop(ws, refresh_session, produce_payload, interval_seconds):
    """Send periodic snapshots with revalidation and disconnect-safe writes.

    Incoming frames are intentionally never parsed by these read-only sockets,
    so malformed client messages cannot influence server state.
    """
    last_check = 0.0
    while True:
        now = time.monotonic()
        if now - last_check >= SESSION_RECHECK_SECONDS:
            if not refresh_session():
                _send_json(
                    ws,
                    {"status": "error", "message": "Session is no longer valid"},
                )
                return
            last_check = now

        try:
            payload = produce_payload()
        except Exception:
            LOGGER.exception("WebSocket data producer failed")
            _send_json(ws, {"status": "error", "message": "Temporary server error"})
            return

        if not _send_json(ws, payload):
            return
        time.sleep(interval_seconds)


def register_ws_routes(
    sock,
    app_id: str | None,
    bot_state: dict,
    get_events,
    get_dm_users,
    get_dm_history,
    require_ws_auth,
    refresh_ws_session,
    permission_events_view: str,
    permission_direct_messages_read: str,
):
    @sock.route("/ws/health")
    def ws_health(ws):
        session = require_ws_auth(ws)
        if not session:
            return

        def produce():
            return {
                "status": "ok",
                "bot_connected": bot_state["connected"],
                "last_sequence": bot_state["last_sequence"],
                "app_id": app_id,
                "bot_profile": bot_state.get("profile"),
            }

        _run_send_loop(
            ws,
            lambda: refresh_ws_session(ws),
            produce,
            2,
        )

    @sock.route("/ws/events")
    def ws_events(ws):
        session = require_ws_auth(ws, permission=permission_events_view)
        if not session:
            return

        limit = _query_limit(ws.environ, default=20, maximum=20)

        _run_send_loop(
            ws,
            lambda: refresh_ws_session(ws, permission=permission_events_view),
            lambda: get_events(limit=limit),
            1,
        )

    @sock.route("/ws/direct-messages/users")
    def ws_dm_users(ws):
        session = require_ws_auth(
            ws, permission=permission_direct_messages_read
        )
        if not session:
            return

        limit = _query_limit(ws.environ, default=300, maximum=1000)

        def produce():
            users = get_dm_users(limit_events=limit)
            return {"count": len(users), "users": users}

        _run_send_loop(
            ws,
            lambda: refresh_ws_session(
                ws, permission=permission_direct_messages_read
            ),
            produce,
            2,
        )

    @sock.route("/ws/direct-messages/history")
    def ws_dm_history(ws):
        session = require_ws_auth(
            ws, permission=permission_direct_messages_read
        )
        if not session:
            return

        query = parse_qs(ws.environ.get("QUERY_STRING", ""))
        user_id = (query.get("user_id", [""])[0] or "").strip()
        limit = _query_limit(ws.environ, default=150, maximum=300)

        if not user_id:
            _send_json(
                ws,
                {
                    "status": "error",
                    "message": "user_id is required",
                    "messages": [],
                },
            )
            return

        def produce():
            messages = get_dm_history(user_id=user_id, limit=limit)
            return {
                "status": "ok",
                "count": len(messages),
                "messages": messages,
            }

        _run_send_loop(
            ws,
            lambda: refresh_ws_session(
                ws, permission=permission_direct_messages_read
            ),
            produce,
            2,
        )
