from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory


def create_app(frontend_dist: Path, app_id: str | None, bot_state: dict, get_events):
    app = Flask(__name__, static_folder=str(frontend_dist), static_url_path="")

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
