import os
import sys
import threading
import time
import json
from pathlib import Path
from urllib.parse import parse_qs

from flask import Flask, jsonify, request, send_from_directory
from flask_sock import Sock


def _restart_current_process() -> None:
    # Small delay gives Flask enough time to flush the JSON response.
    time.sleep(0.6)
    os.execv(sys.executable, [sys.executable, *sys.argv])


def create_app(
    frontend_dist: Path,
    app_id: str | None,
    bot_state: dict,
    get_events,
    get_dm_users,
    get_dm_history,
    get_dm_message,
    save_sent_dm_message,
    mark_dm_message_deleted,
    send_dm,
    delete_dm,
    regenerate_db,
):
    app = Flask(__name__, static_folder=str(frontend_dist), static_url_path="")
    sock = Sock(app)

    @app.get("/api/health")
    def api_health():
        return jsonify(
            {
                "status": "ok",
                "bot_connected": bot_state["connected"],
                "last_sequence": bot_state["last_sequence"],
                "app_id": app_id,
                "bot_profile": bot_state.get("profile"),
            }
        )

    @app.get("/api/events")
    def api_events():
        limit = request.args.get("limit", default=20, type=int)
        return jsonify(get_events(limit=limit))

    @app.get("/api/direct-messages/users")
    def api_direct_message_users():
        limit = request.args.get("limit", default=300, type=int)
        users = get_dm_users(limit_events=limit)
        return jsonify(
            {
                "count": len(users),
                "users": users,
            }
        )

    @app.post("/api/direct-messages/send")
    def api_dm_send():
        user_id = (request.form.get("user_id") or "").strip()
        content = request.form.get("content") or ""
        uploaded_files = request.files.getlist("files")

        if not user_id:
            return jsonify({"status": "error", "message": "user_id is required"}), 400

        files_payload = []
        for uploaded in uploaded_files:
            data = uploaded.read()
            files_payload.append(
                {
                    "filename": uploaded.filename or "upload.bin",
                    "content_type": uploaded.mimetype or "application/octet-stream",
                    "data": data,
                }
            )

        if not content.strip() and not files_payload:
            return jsonify({"status": "error", "message": "content or files are required"}), 400

        try:
            result = send_dm(user_id=user_id, content=content, files=files_payload)
            save_sent_dm_message(user_id=user_id, message_payload=result.get("message") or {})
        except Exception as err:
            return jsonify({"status": "error", "message": str(err)}), 500

        return jsonify({"status": "ok", "result": result})

    @app.get("/api/direct-messages/history")
    def api_dm_history():
        user_id = (request.args.get("user_id") or "").strip()
        limit = request.args.get("limit", default=120, type=int)

        if not user_id:
            return jsonify({"status": "error", "message": "user_id is required"}), 400

        messages = get_dm_history(user_id=user_id, limit=limit)
        return jsonify({"status": "ok", "count": len(messages), "messages": messages})

    @app.delete("/api/direct-messages/messages/<message_id>")
    def api_delete_dm(message_id):
        message = get_dm_message(message_id=message_id)
        if not message:
            return jsonify({"status": "error", "message": "Message not found"}), 404

        bot_user_id = str(bot_state.get("bot_user_id") or "")
        author_id = str(message.get("author_id") or "")
        if not bot_user_id or author_id != bot_user_id:
            return jsonify({"status": "error", "message": "Only bot-authored DM messages can be deleted"}), 403

        channel_id = str(message.get("channel_id") or "")
        if not channel_id:
            return jsonify({"status": "error", "message": "Message channel is unavailable"}), 400

        try:
            delete_dm(channel_id=channel_id, message_id=message_id)
            mark_dm_message_deleted(message_id=message_id)
        except Exception as err:
            return jsonify({"status": "error", "message": str(err)}), 500

        return jsonify({"status": "ok", "message_id": message_id, "deleted": True})

    @app.get("/api/servers")
    def api_servers():
        guilds = bot_state.get("guilds") or []
        return jsonify(
            {
                "count": len(guilds),
                "servers": guilds,
            }
        )

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

    @app.delete("/api/database/regenerate")
    def api_regenerate_db():
        deleted_count = regenerate_db()

        restart_thread = threading.Thread(target=_restart_current_process, daemon=True)
        restart_thread.start()

        return jsonify(
            {
                "status": "ok",
                "message": "Database regenerated. All event rows were deleted.",
                "deleted_count": deleted_count,
                "restarting": True,
            }
        )

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        if frontend_dist.exists():
            asset_path = frontend_dist / path
            if path and asset_path.exists() and asset_path.is_file():
                return send_from_directory(str(frontend_dist), path)
            return send_from_directory(str(frontend_dist), "index.html")

        return jsonify(
            {
                "message": "Frontend build not found.",
                "next_steps": [
                    "Run: cd frontend && npm install",
                    "Run: npm run build",
                    "Restart this Python service",
                ],
            }
        )

    return app
