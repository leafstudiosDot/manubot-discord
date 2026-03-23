import os
import sys
import threading
import time
import json
from pathlib import Path
from urllib.parse import parse_qs

from flask import Flask, g, jsonify, request, send_from_directory
from flask_sock import Sock

from accounts import (
    PERMISSION_ACCOUNTS_VIEW,
    PERMISSION_DATABASE_REGENERATE,
    PERMISSION_DIRECT_MESSAGES_DELETE,
    PERMISSION_DIRECT_MESSAGES_READ,
    PERMISSION_DIRECT_MESSAGES_SEND,
    PERMISSION_EVENTS_VIEW,
    PERMISSION_SERVERS_VIEW,
    ROLE_ADMIN,
    ROLE_MODERATOR,
    ROLE_SUPERADMIN,
)


def _restart_current_process() -> None:
    # Small delay gives Flask enough time to flush the JSON response.
    time.sleep(0.6)
    os.execv(sys.executable, [sys.executable, *sys.argv])


def create_app(
    frontend_dist: Path,
    app_id: str | None,
    bot_state: dict,
    account_service,
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
    # Avoid mounting Flask's static route at "/" because it can intercept
    # client-side routes (e.g. /servers) and return 404 before SPA fallback.
    app = Flask(__name__)
    sock = Sock(app)

    def _require_auth(permission: str | None = None, roles: tuple[str, ...] | None = None):
        session = account_service.authenticate_request(request)
        if not session:
            return None, jsonify({"status": "error", "message": "Authentication required"}), 401

        if roles and session.get("role") not in roles:
            return None, jsonify({"status": "error", "message": "Forbidden"}), 403

        if permission and not account_service.has_permission(session, permission):
            return None, jsonify({"status": "error", "message": "Forbidden"}), 403

        g.panel_session = session
        return session, None, None

    def _require_ws_auth(ws, permission: str | None = None):
        session = account_service.authenticate_ws_environ(ws.environ)
        if not session:
            ws.send(json.dumps({"status": "error", "message": "Authentication required"}))
            return None

        if permission and not account_service.has_permission(session, permission):
            ws.send(json.dumps({"status": "error", "message": "Forbidden"}))
            return None

        return session

    @app.post("/api/auth/login")
    def api_auth_login():
        payload = request.get_json(silent=True) or {}
        username = (payload.get("username") or "").strip()
        password = payload.get("password") or ""

        session, err = account_service.login(username=username, password=password)
        if err or not session:
            return jsonify({"status": "error", "message": err or "Invalid credentials"}), 401

        response = jsonify(
            {
                "status": "ok",
                "session": account_service.session_public(session),
            }
        )
        account_service.add_session_cookie(response, session)
        return response

    @app.post("/api/auth/logout")
    def api_auth_logout():
        account_service.logout(request)
        response = jsonify({"status": "ok"})
        account_service.clear_session_cookie(response)
        return response

    @app.get("/api/auth/session")
    def api_auth_session():
        session, err_response, err_code = _require_auth()
        if not session:
            return err_response, err_code

        return jsonify(
            {
                "status": "ok",
                "session": account_service.session_public(session),
            }
        )

    @app.get("/api/accounts")
    def api_accounts_list():
        session, err_response, err_code = _require_auth(permission=PERMISSION_ACCOUNTS_VIEW)
        if not session:
            return err_response, err_code

        accounts = account_service.list_accounts()
        return jsonify({"status": "ok", "accounts": accounts})

    @app.post("/api/accounts")
    def api_accounts_create():
        session, err_response, err_code = _require_auth(roles=(ROLE_SUPERADMIN,))
        if not session:
            return err_response, err_code

        payload = request.get_json(silent=True) or {}
        created, err = account_service.create_account(
            actor_session=session,
            username=payload.get("username") or "",
            password=payload.get("password") or "",
            role=payload.get("role") or "",
        )
        if err:
            return jsonify({"status": "error", "message": err}), 400

        return jsonify({"status": "ok", "account": created}), 201

    @app.patch("/api/accounts/<int:account_id>/permissions")
    def api_accounts_update_permissions(account_id: int):
        session, err_response, err_code = _require_auth(roles=(ROLE_SUPERADMIN, ROLE_ADMIN))
        if not session:
            return err_response, err_code

        payload = request.get_json(silent=True) or {}
        updated, err = account_service.update_moderator_permissions(
            actor_session=session,
            account_id=account_id,
            permissions=payload.get("permissions") or {},
        )
        if err:
            return jsonify({"status": "error", "message": err}), 400

        return jsonify({"status": "ok", "account": updated})

    @app.post("/api/accounts/change-own-password")
    def api_accounts_change_own_password():
        session, err_response, err_code = _require_auth()
        if not session:
            return err_response, err_code

        payload = request.get_json(silent=True) or {}
        updated, err = account_service.change_own_password(
            actor_session=session,
            current_password=payload.get("current_password") or "",
            new_password=payload.get("new_password") or "",
        )
        if err:
            status_code = 403 if "Only admin and moderator" in err else 400
            return jsonify({"status": "error", "message": err}), status_code

        return jsonify({"status": "ok", "account": updated})

    @app.post("/api/accounts/<int:account_id>/password")
    def api_accounts_set_password(account_id: int):
        session, err_response, err_code = _require_auth(roles=(ROLE_SUPERADMIN,))
        if not session:
            return err_response, err_code

        payload = request.get_json(silent=True) or {}
        updated, err = account_service.superadmin_set_account_password(
            actor_session=session,
            account_id=account_id,
            new_password=payload.get("new_password") or "",
        )
        if err:
            return jsonify({"status": "error", "message": err}), 400

        return jsonify({"status": "ok", "account": updated})

    @app.post("/api/sessions/revoke-all")
    def api_revoke_all_sessions():
        session, err_response, err_code = _require_auth()
        if not session:
            return err_response, err_code

        revoked_count = account_service.revoke_sessions_for_identity(
            username=str(session.get("username") or ""),
            role=str(session.get("role") or ""),
        )
        response = jsonify(
            {
                "status": "ok",
                "revoked_count": revoked_count,
                "logged_out": True,
            }
        )
        account_service.clear_session_cookie(response)
        return response

    @app.post("/api/sessions/revoke-all-global")
    def api_revoke_all_sessions_global():
        session, err_response, err_code = _require_auth(roles=(ROLE_SUPERADMIN,))
        if not session:
            return err_response, err_code

        revoked_count = account_service.revoke_all_sessions()
        response = jsonify(
            {
                "status": "ok",
                "revoked_count": revoked_count,
                "logged_out": True,
            }
        )
        account_service.clear_session_cookie(response)
        return response

    @app.get("/api/health")
    def api_health():
        session, err_response, err_code = _require_auth()
        if not session:
            return err_response, err_code

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
        session, err_response, err_code = _require_auth(permission=PERMISSION_EVENTS_VIEW)
        if not session:
            return err_response, err_code

        limit = request.args.get("limit", default=20, type=int)
        return jsonify(get_events(limit=limit))

    @app.get("/api/direct-messages/users")
    def api_direct_message_users():
        session, err_response, err_code = _require_auth(permission=PERMISSION_DIRECT_MESSAGES_READ)
        if not session:
            return err_response, err_code

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
        session, err_response, err_code = _require_auth(permission=PERMISSION_DIRECT_MESSAGES_SEND)
        if not session:
            return err_response, err_code

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
        session, err_response, err_code = _require_auth(permission=PERMISSION_DIRECT_MESSAGES_READ)
        if not session:
            return err_response, err_code

        user_id = (request.args.get("user_id") or "").strip()
        limit = request.args.get("limit", default=120, type=int)

        if not user_id:
            return jsonify({"status": "error", "message": "user_id is required"}), 400

        messages = get_dm_history(user_id=user_id, limit=limit)
        return jsonify({"status": "ok", "count": len(messages), "messages": messages})

    @app.delete("/api/direct-messages/messages/<message_id>")
    def api_delete_dm(message_id):
        session, err_response, err_code = _require_auth(permission=PERMISSION_DIRECT_MESSAGES_DELETE)
        if not session:
            return err_response, err_code

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
        session, err_response, err_code = _require_auth(permission=PERMISSION_SERVERS_VIEW)
        if not session:
            return err_response, err_code

        guilds = bot_state.get("guilds") or []
        return jsonify(
            {
                "count": len(guilds),
                "servers": guilds,
            }
        )

    @sock.route("/ws/health")
    def ws_health(ws):
        session = _require_ws_auth(ws)
        if not session:
            return

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
        session = _require_ws_auth(ws, permission=PERMISSION_EVENTS_VIEW)
        if not session:
            return

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
        session = _require_ws_auth(ws, permission=PERMISSION_DIRECT_MESSAGES_READ)
        if not session:
            return

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
        session = _require_ws_auth(ws, permission=PERMISSION_DIRECT_MESSAGES_READ)
        if not session:
            return

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
        session, err_response, err_code = _require_auth(roles=(ROLE_SUPERADMIN,))
        if not session:
            return err_response, err_code

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
        if path.startswith("api/") or path.startswith("ws/"):
            return jsonify({"status": "error", "message": "Not found"}), 404

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
