import json
import time
from urllib.parse import parse_qs


def register_ws_routes(
    sock,
    app_id: str | None,
    bot_state: dict,
    get_events,
    get_dm_users,
    get_dm_history,
):
    @sock.route("/ws/health")
    def ws_health(ws):
        while True:
            ws.send(
                json.dumps(
                    {
                        "status": "ok",
                        "bot_connected": bot_state["connected"],
                        "last_sequence": bot_state["last_sequence"],
                        "app_id": app_id,
                        "bot_profile": bot_state.get("profile"),
                    }
                )
            )
            time.sleep(2)

    @sock.route("/ws/events")
    def ws_events(ws):
        query = parse_qs(ws.environ.get("QUERY_STRING", ""))
        try:
            requested_limit = int(query.get("limit", [20])[0])
        except (TypeError, ValueError):
            requested_limit = 20

        limit = max(1, min(requested_limit, 20))

        while True:
            ws.send(json.dumps(get_events(limit=limit)))
            time.sleep(1)

    @sock.route("/ws/direct-messages/users")
    def ws_dm_users(ws):
        query = parse_qs(ws.environ.get("QUERY_STRING", ""))
        try:
            requested_limit = int(query.get("limit", [300])[0])
        except (TypeError, ValueError):
            requested_limit = 300

        limit = max(1, min(requested_limit, 1000))

        while True:
            users = get_dm_users(limit_events=limit)
            ws.send(
                json.dumps(
                    {
                        "count": len(users),
                        "users": users,
                    }
                )
            )
            time.sleep(2)

    @sock.route("/ws/direct-messages/history")
    def ws_dm_history(ws):
        query = parse_qs(ws.environ.get("QUERY_STRING", ""))
        user_id = (query.get("user_id", [""])[0] or "").strip()

        try:
            requested_limit = int(query.get("limit", [150])[0])
        except (TypeError, ValueError):
            requested_limit = 150

        limit = max(1, min(requested_limit, 300))

        if not user_id:
            ws.send(json.dumps({"status": "error", "message": "user_id is required", "messages": []}))
            return

        while True:
            messages = get_dm_history(user_id=user_id, limit=limit)
            ws.send(
                json.dumps(
                    {
                        "status": "ok",
                        "count": len(messages),
                        "messages": messages,
                    }
                )
            )
            time.sleep(2)
