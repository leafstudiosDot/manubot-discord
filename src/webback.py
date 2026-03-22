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


def create_app(frontend_dist: Path, app_id: str | None, bot_state: dict, get_events, regenerate_db):
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
            }
        )

    @app.get("/api/events")
    def api_events():
        limit = request.args.get("limit", default=20, type=int)
        return jsonify(get_events(limit=limit))

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
