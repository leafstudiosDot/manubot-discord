import json
import logging
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory
from flask_sock import Sock
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from accounts import (
    PERMISSION_ACCOUNTS_VIEW,
    PERMISSION_AUDIT_VIEW,
    PERMISSION_DIRECT_MESSAGES_DELETE,
    PERMISSION_DIRECT_MESSAGES_READ,
    PERMISSION_DIRECT_MESSAGES_SEND,
    PERMISSION_EVENTS_VIEW,
    PERMISSION_SERVERS_VIEW,
    ROLE_ADMIN,
    ROLE_MODERATOR,
    ROLE_SUPERADMIN,
)
from audit import (
    ACTION_DATABASE_REGENERATE,
    ACTION_DM_DELETE,
    ACTION_DM_SEND,
    ACTION_LOGOUT,
    ACTION_MOUSETRAP_CONFIG_UPDATE,
    ACTION_SESSIONS_REVOKE,
    ACTION_SESSIONS_REVOKE_GLOBAL,
    CATEGORIES,
    CATEGORY_AUTH,
    CATEGORY_DATABASE,
    CATEGORY_DIRECT_MESSAGES,
    CATEGORY_MOUSETRAP,
    CATEGORY_SESSIONS,
)
from config import Settings
from security import (
    UNSAFE_METHODS,
    is_snowflake,
    normalize_origin,
    origin_is_allowed,
    parse_iso_datetime,
    resolve_client_ip,
    sanitize_content_type,
    sanitize_filename,
)
from wsback import register_ws_routes

LOGGER = logging.getLogger(__name__)
SAFE_ERROR_MESSAGES = {
    400: "Invalid request",
    401: "Authentication required",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    413: "Request payload too large",
    415: "Unsupported media type",
    429: "Too many requests",
    500: "Internal server error",
    502: "The upstream service failed to process the request",
}


class ApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _json_error(message: str, status_code: int):
    return jsonify({"status": "error", "message": message}), status_code


def _read_upload_limited(upload, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.stream.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ApiError(413, "Uploaded file is too large")
        chunks.append(bytes(chunk))
    return b"".join(chunks)


def create_app(
    frontend_dist: Path,
    app_id: str | None,
    bot_state: dict,
    account_service,
    get_guild_channels,
    get_mousetrap_config,
    save_mousetrap_config,
    get_mousetrap_logs,
    get_events,
    get_dm_users,
    get_dm_history,
    get_dm_message,
    save_sent_dm_message,
    mark_dm_message_deleted,
    send_dm,
    delete_dm,
    regenerate_db,
    audit_service=None,
    settings: Settings | None = None,
):
    resolved_settings = settings or Settings.from_env()
    audit_service = audit_service or getattr(account_service, "audit", None)

    # Avoid mounting Flask's static route at "/" because it can intercept
    # client-side routes (e.g. /servers) and return 404 before SPA fallback.
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = resolved_settings.max_request_bytes
    app.config["JSON_SORT_KEYS"] = False

    if resolved_settings.trust_proxy_headers:
        # Only enabled when a reverse proxy overwrites these headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    sock = Sock(app)

    def _request_scheme() -> str:
        return "https" if request.is_secure else request.scheme

    def _origin_allowed(origin: str | None, *, websocket: bool = False) -> bool:
        trusted = (
            resolved_settings.ws_trusted_origins or resolved_settings.trusted_origins
            if websocket
            else resolved_settings.trusted_origins
        )
        return origin_is_allowed(
            origin,
            _request_scheme(),
            request.host,
            trusted,
            allow_loopback_dev=resolved_settings.allow_loopback_dev_origins,
        )

    def _require_auth(permission: str | None = None, roles: tuple[str, ...] | None = None):
        session = getattr(g, "panel_session", None)
        if not session:
            session = account_service.authenticate_request(request)
        if not session:
            return None, _json_error("Authentication required", 401)[0], 401

        if roles and session.get("role") not in roles:
            return None, _json_error("Forbidden", 403)[0], 403

        if permission and not account_service.has_permission(session, permission):
            return None, _json_error("Forbidden", 403)[0], 403

        g.panel_session = session
        return session, None, None

    def _json_body() -> dict:
        if not request.is_json:
            raise ApiError(415, "Content-Type must be application/json")
        if (
            request.content_length is not None
            and request.content_length > resolved_settings.max_json_bytes
        ):
            raise ApiError(413, "JSON request body is too large")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ApiError(400, "Invalid JSON body")
        return payload

    def _int_query(name: str, default: int, minimum: int, maximum: int) -> int:
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ApiError(400, f"{name} must be an integer") from exc
        if value < minimum or value > maximum:
            raise ApiError(400, f"{name} must be between {minimum} and {maximum}")
        return value

    def _audit(action: str, category: str, session, **kwargs) -> None:
        if not audit_service:
            return
        try:
            audit_service.record(
                action=action,
                category=category,
                actor_session=session,
                **kwargs,
            )
        except Exception:
            LOGGER.exception("Failed to record audit event %s", action)

    def _guild_exists(server_id: str) -> bool:
        guilds = bot_state.get("guilds") or []
        return any(
            str(guild.get("id") or "") == server_id
            for guild in guilds
            if isinstance(guild, dict)
        )

    def _client_ip() -> str:
        return resolve_client_ip(
            request.remote_addr,
            request.headers.get("X-Forwarded-For"),
            resolved_settings.trust_proxy_headers,
        )

    def _ws_scheme(ws) -> str:
        environ = ws.environ
        scheme = str(environ.get("wsgi.url_scheme") or "http").lower()
        if resolved_settings.trust_proxy_headers:
            forwarded = str(
                environ.get("HTTP_X_FORWARDED_PROTO") or ""
            ).split(",")[0].strip().lower()
            if forwarded in ("http", "https"):
                scheme = forwarded
        return scheme

    def _ws_origin_allowed(ws) -> bool:
        environ = ws.environ
        origin = str(environ.get("HTTP_ORIGIN") or "").strip()
        host = str(environ.get("HTTP_HOST") or "").strip()
        trusted = (
            resolved_settings.ws_trusted_origins
            or resolved_settings.trusted_origins
        )
        return origin_is_allowed(
            origin,
            _ws_scheme(ws),
            host,
            trusted,
            allow_loopback_dev=resolved_settings.allow_loopback_dev_origins,
        )

    def _require_ws_auth(ws, permission: str | None = None):
        if not _ws_origin_allowed(ws):
            try:
                ws.send(
                    json.dumps(
                        {
                            "status": "error",
                            "message": "WebSocket origin is not allowed",
                        }
                    )
                )
            except Exception:
                pass
            return None

        session = account_service.authenticate_ws_environ(ws.environ)
        if not session:
            try:
                ws.send(
                    json.dumps(
                        {"status": "error", "message": "Authentication required"}
                    )
                )
            except Exception:
                pass
            return None

        if permission and not account_service.has_permission(session, permission):
            try:
                ws.send(json.dumps({"status": "error", "message": "Forbidden"}))
            except Exception:
                pass
            return None

        return session

    def _refresh_ws_session(ws, permission: str | None = None) -> bool:
        if not _ws_origin_allowed(ws):
            return False
        session = account_service.authenticate_ws_environ(ws.environ)
        if not session:
            return False
        if permission and not account_service.has_permission(session, permission):
            return False
        return True

    register_ws_routes(
        sock=sock,
        app_id=app_id,
        bot_state=bot_state,
        get_events=get_events,
        get_dm_users=get_dm_users,
        get_dm_history=get_dm_history,
        require_ws_auth=_require_ws_auth,
        refresh_ws_session=_refresh_ws_session,
        permission_events_view=PERMISSION_EVENTS_VIEW,
        permission_direct_messages_read=PERMISSION_DIRECT_MESSAGES_READ,
    )

    @app.before_request
    def security_guard():
        if not request.path.startswith("/api/"):
            return None

        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("Origin")
            if origin and not _origin_allowed(origin):
                return _json_error("Request origin is not allowed", 403)

            if request.path != "/api/auth/login":
                session = account_service.authenticate_request(request)
                g.panel_session = session

                if request.path == "/api/auth/logout" and not session:
                    return None

                if not session:
                    return _json_error("Authentication required", 401)

                if not account_service.validate_csrf(
                    session, request.headers.get("X-CSRF-Token")
                ):
                    return _json_error("CSRF validation failed", 403)

            if request.is_json:
                content_length = request.content_length
                if (
                    content_length is not None
                    and content_length > resolved_settings.max_json_bytes
                ):
                    return _json_error("JSON request body is too large", 413)

        if request.method in ("GET", "HEAD"):
            session = account_service.authenticate_request(request)
            g.panel_session = session

        return None

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Content-Security-Policy",
            "frame-ancestors 'none'; base-uri 'self'; object-src 'none'",
        )
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "X-Permitted-Cross-Domain-Policies", "none"
        )
        if resolved_settings.enable_hsts and resolved_settings.production:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return _json_error(err.message, err.status_code)

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException):
        status_code = int(err.code or 500)
        if request.path.startswith("/api/") or request.path == "/healthz":
            message = SAFE_ERROR_MESSAGES.get(status_code, "Request failed")
            return _json_error(message, status_code)
        return err

    @app.errorhandler(Exception)
    def handle_unexpected_error(err: Exception):
        LOGGER.exception(
            "Unhandled request error on %s %s", request.method, request.path
        )
        if request.path.startswith("/api/"):
            return _json_error("Internal server error", 500)
        return "Internal server error", 500

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.post("/api/auth/login")
    def api_auth_login():
        payload = _json_body()
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")

        result = account_service.login(
            username=username,
            password=password,
            client_ip=_client_ip(),
        )
        if result.error or not result.session:
            response, status_code = _json_error(
                result.error or "Invalid credentials",
                result.status_code,
            )
            if result.retry_after:
                response.headers["Retry-After"] = str(result.retry_after)
            return response, status_code

        response = jsonify(
            {
                "status": "ok",
                "session": account_service.session_public(result.session),
            }
        )
        account_service.add_session_cookie(response, result.session)
        return response

    @app.post("/api/auth/logout")
    def api_auth_logout():
        session = getattr(g, "panel_session", None)
        if session:
            _audit(
                ACTION_LOGOUT,
                CATEGORY_AUTH,
                session,
                target_type="session",
            )
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
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_ACCOUNTS_VIEW
        )
        if not session:
            return err_response, err_code

        accounts = account_service.list_accounts()
        return jsonify({"status": "ok", "accounts": accounts})

    @app.post("/api/accounts")
    def api_accounts_create():
        session, err_response, err_code = _require_auth(
            roles=(ROLE_SUPERADMIN,)
        )
        if not session:
            return err_response, err_code

        payload = _json_body()
        created, err = account_service.create_account(
            actor_session=session,
            username=str(payload.get("username") or ""),
            password=str(payload.get("password") or ""),
            role=str(payload.get("role") or ""),
        )
        if err:
            status_code = 409 if "already exists" in err else 400
            return _json_error(err, status_code)

        return jsonify({"status": "ok", "account": created}), 201

    @app.patch("/api/accounts/<int:account_id>/permissions")
    def api_accounts_update_permissions(account_id: int):
        session, err_response, err_code = _require_auth(
            roles=(ROLE_SUPERADMIN, ROLE_ADMIN)
        )
        if not session:
            return err_response, err_code

        payload = _json_body()
        permissions = payload.get("permissions")
        if not isinstance(permissions, dict):
            return _json_error("permissions must be an object", 400)

        updated, err = account_service.update_moderator_permissions(
            actor_session=session,
            account_id=account_id,
            permissions=permissions,
        )
        if err:
            status_code = 404 if "not found" in err.lower() else 400
            return _json_error(err, status_code)

        return jsonify({"status": "ok", "account": updated})

    @app.post("/api/accounts/change-own-password")
    def api_accounts_change_own_password():
        session, err_response, err_code = _require_auth()
        if not session:
            return err_response, err_code

        payload = _json_body()
        updated, err = account_service.change_own_password(
            actor_session=session,
            current_password=str(payload.get("current_password") or ""),
            new_password=str(payload.get("new_password") or ""),
        )
        if err:
            status_code = 403 if "Only admin and moderator" in err else 400
            return _json_error(err, status_code)

        return jsonify({"status": "ok", "account": updated})

    @app.post("/api/accounts/<int:account_id>/password")
    def api_accounts_set_password(account_id: int):
        session, err_response, err_code = _require_auth(
            roles=(ROLE_SUPERADMIN,)
        )
        if not session:
            return err_response, err_code

        payload = _json_body()
        updated, err = account_service.superadmin_set_account_password(
            actor_session=session,
            account_id=account_id,
            new_password=str(payload.get("new_password") or ""),
        )
        if err:
            status_code = 404 if "not found" in err.lower() else 400
            return _json_error(err, status_code)

        return jsonify({"status": "ok", "account": updated})

    @app.post("/api/sessions/revoke-all")
    def api_revoke_all_sessions():
        session, err_response, err_code = _require_auth()
        if not session:
            return err_response, err_code

        _audit(ACTION_SESSIONS_REVOKE, CATEGORY_SESSIONS, session)
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
        session, err_response, err_code = _require_auth(
            roles=(ROLE_SUPERADMIN,)
        )
        if not session:
            return err_response, err_code

        _audit(ACTION_SESSIONS_REVOKE_GLOBAL, CATEGORY_SESSIONS, session)
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
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_EVENTS_VIEW
        )
        if not session:
            return err_response, err_code

        limit = _int_query("limit", 20, 1, 100)
        return jsonify(get_events(limit=limit))

    @app.get("/api/direct-messages/users")
    def api_direct_message_users():
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_DIRECT_MESSAGES_READ
        )
        if not session:
            return err_response, err_code

        limit = _int_query("limit", 300, 1, 1000)
        users = get_dm_users(limit_events=limit)
        return jsonify({"count": len(users), "users": users})

    @app.post("/api/direct-messages/send")
    def api_dm_send():
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_DIRECT_MESSAGES_SEND
        )
        if not session:
            return err_response, err_code

        user_id = str(request.form.get("user_id") or "").strip()
        content = str(request.form.get("content") or "")
        uploaded_files = request.files.getlist("files")

        if not is_snowflake(user_id):
            return _json_error("user_id is invalid", 400)
        if len(content) > 2000:
            return _json_error("Message content must be at most 2000 characters", 400)
        if len(uploaded_files) > resolved_settings.max_dm_attachments:
            return _json_error(
                f"At most {resolved_settings.max_dm_attachments} files are allowed",
                400,
            )

        files_payload = []
        total_bytes = 0
        for index, upload in enumerate(uploaded_files):
            raw_filename = upload.filename or ""
            filename = sanitize_filename(raw_filename) or f"upload-{index + 1}.bin"
            if raw_filename and not sanitize_filename(raw_filename):
                return _json_error("A filename is invalid", 400)

            data = _read_upload_limited(
                upload, resolved_settings.max_dm_file_bytes
            )
            total_bytes += len(data)
            if total_bytes > resolved_settings.max_request_bytes:
                return _json_error("Uploaded files are too large", 413)

            files_payload.append(
                {
                    "filename": filename,
                    "content_type": sanitize_content_type(upload.mimetype),
                    "data": data,
                }
            )

        if not content.strip() and not files_payload:
            return _json_error("content or files are required", 400)

        try:
            result = send_dm(
                user_id=user_id, content=content, files=files_payload
            )
            save_sent_dm_message(
                user_id=user_id, message_payload=result.get("message") or {}
            )
        except Exception:
            LOGGER.exception(
                "Failed to send a direct message to user %s", user_id
            )
            return _json_error("Failed to send direct message", 502)

        _audit(
            ACTION_DM_SEND,
            CATEGORY_DIRECT_MESSAGES,
            session,
            target_type="dm_user",
            target_id=user_id,
            metadata={
                "attachment_count": len(files_payload),
                "has_text": bool(content.strip()),
            },
        )
        return jsonify({"status": "ok", "result": result})

    @app.get("/api/direct-messages/history")
    def api_dm_history():
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_DIRECT_MESSAGES_READ
        )
        if not session:
            return err_response, err_code

        user_id = str(request.args.get("user_id") or "").strip()
        limit = _int_query("limit", 120, 1, 500)
        if not is_snowflake(user_id):
            return _json_error("user_id is invalid", 400)

        messages = get_dm_history(user_id=user_id, limit=limit)
        return jsonify(
            {"status": "ok", "count": len(messages), "messages": messages}
        )

    @app.delete("/api/direct-messages/messages/<message_id>")
    def api_delete_dm(message_id):
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_DIRECT_MESSAGES_DELETE
        )
        if not session:
            return err_response, err_code

        if not is_snowflake(message_id):
            return _json_error("message_id is invalid", 400)

        message = get_dm_message(message_id=message_id)
        if not message:
            return _json_error("Message not found", 404)

        bot_user_id = str(bot_state.get("bot_user_id") or "")
        author_id = str(message.get("author_id") or "")
        if not bot_user_id or author_id != bot_user_id:
            return _json_error(
                "Only bot-authored DM messages can be deleted", 403
            )

        channel_id = str(message.get("channel_id") or "")
        if not channel_id:
            return _json_error("Message channel is unavailable", 400)

        try:
            delete_dm(channel_id=channel_id, message_id=message_id)
            mark_dm_message_deleted(message_id=message_id)
        except Exception:
            LOGGER.exception(
                "Failed to delete direct message %s in channel %s",
                message_id,
                channel_id,
            )
            return _json_error("Failed to delete direct message", 502)

        _audit(
            ACTION_DM_DELETE,
            CATEGORY_DIRECT_MESSAGES,
            session,
            target_type="dm_message",
            target_id=message_id,
            metadata={"channel_id": channel_id},
        )
        return jsonify(
            {"status": "ok", "message_id": message_id, "deleted": True}
        )

    @app.get("/api/servers")
    def api_servers():
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_SERVERS_VIEW
        )
        if not session:
            return err_response, err_code

        guilds = bot_state.get("guilds") or []
        return jsonify({"count": len(guilds), "servers": guilds})

    @app.get("/api/servers/<server_id>/channels")
    def api_server_channels(server_id: str):
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_SERVERS_VIEW
        )
        if not session:
            return err_response, err_code

        if not is_snowflake(server_id):
            return _json_error("Server id is invalid", 400)
        if not _guild_exists(server_id):
            return _json_error("Server not found", 404)

        try:
            channels = get_guild_channels(server_id=server_id)
        except Exception:
            LOGGER.exception("Failed to fetch channels for server %s", server_id)
            return _json_error("Failed to load server channels", 502)

        text_channels = []
        for channel in channels:
            if not isinstance(channel, dict):
                continue
            channel_type = channel.get("type")
            if channel_type not in (0, 5, 10, 11, 12):
                continue

            text_channels.append(
                {
                    "id": str(channel.get("id") or ""),
                    "name": str(channel.get("name") or "unknown-channel"),
                    "type": channel_type,
                    "parent_id": channel.get("parent_id"),
                }
            )

        text_channels.sort(key=lambda item: item["name"].lower())
        return jsonify({"status": "ok", "channels": text_channels})

    @app.get("/api/servers/<server_id>/mousetrap")
    def api_server_mousetrap(server_id: str):
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_SERVERS_VIEW
        )
        if not session:
            return err_response, err_code

        if not is_snowflake(server_id):
            return _json_error("Server id is invalid", 400)

        config = get_mousetrap_config(server_id)
        return jsonify({"status": "ok", "config": config})

    @app.post("/api/servers/<server_id>/mousetrap")
    def api_server_mousetrap_save(server_id: str):
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_SERVERS_VIEW
        )
        if not session:
            return err_response, err_code

        if not is_snowflake(server_id):
            return _json_error("Server id is invalid", 400)
        if not _guild_exists(server_id):
            return _json_error("Server not found", 404)

        payload = _json_body()
        channel_id = str(payload.get("channel_id") or "").strip()
        if channel_id and channel_id != "none" and not is_snowflake(channel_id):
            return _json_error("channel_id is invalid", 400)

        try:
            config = save_mousetrap_config(
                server_id,
                channel_id if channel_id and channel_id != "none" else None,
            )
        except Exception:
            LOGGER.exception("Failed to save MouseTrap config for %s", server_id)
            return _json_error("Failed to save MouseTrap configuration", 502)

        _audit(
            ACTION_MOUSETRAP_CONFIG_UPDATE,
            CATEGORY_MOUSETRAP,
            session,
            target_type="discord_server",
            target_id=server_id,
            metadata={"channel_id": channel_id or "none"},
        )
        return jsonify({"status": "ok", "config": config})

    @app.get("/api/servers/<server_id>/mousetrap/logs")
    def api_server_mousetrap_logs(server_id: str):
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_SERVERS_VIEW
        )
        if not session:
            return err_response, err_code

        if not is_snowflake(server_id):
            return _json_error("Server id is invalid", 400)

        limit = _int_query("limit", 100, 1, 500)
        channel_id = (request.args.get("channel_id") or "").strip() or None
        if channel_id and not is_snowflake(channel_id):
            return _json_error("channel_id is invalid", 400)

        try:
            data = get_mousetrap_logs(
                server_id, channel_id=channel_id, limit=limit
            )
        except Exception:
            LOGGER.exception("Failed to load MouseTrap logs for %s", server_id)
            return _json_error("Failed to load MouseTrap logs", 502)

        return jsonify(data)

    @app.get("/api/audit-logs")
    def api_audit_logs():
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_AUDIT_VIEW
        )
        if not session:
            return err_response, err_code

        if not audit_service:
            return _json_error("Audit log is unavailable", 503)

        page = _int_query("page", 1, 1, 1_000_000)
        page_size = _int_query("page_size", 25, 1, 100)
        category = (request.args.get("category") or "").strip() or None
        action = (request.args.get("action") or "").strip() or None
        actor = (request.args.get("actor") or "").strip() or None
        target_type = (request.args.get("target_type") or "").strip() or None
        target_id = (request.args.get("target_id") or "").strip() or None
        query = (request.args.get("query") or "").strip() or None
        from_raw = (request.args.get("from") or "").strip() or None
        to_raw = (request.args.get("to") or "").strip() or None

        if category and category not in CATEGORIES:
            return _json_error("category filter is invalid", 400)
        for label, value in (
            ("action", action),
            ("actor", actor),
            ("target_type", target_type),
            ("target_id", target_id),
            ("query", query),
        ):
            if value and len(value) > 200:
                return _json_error(f"{label} filter is too long", 400)

        from_ts = parse_iso_datetime(from_raw)
        to_ts = parse_iso_datetime(to_raw)
        if from_raw and not from_ts:
            return _json_error("from must be an ISO date or timestamp", 400)
        if to_raw and not to_ts:
            return _json_error("to must be an ISO date or timestamp", 400)

        data = audit_service.list_events(
            page=page,
            page_size=page_size,
            category=category,
            action=action,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            from_ts=from_ts,
            to_ts=to_ts,
            query=query,
        )
        return jsonify({"status": "ok", **data})

    @app.get("/api/audit-logs/meta")
    def api_audit_logs_meta():
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_AUDIT_VIEW
        )
        if not session:
            return err_response, err_code

        if not audit_service:
            return _json_error("Audit log is unavailable", 503)
        return jsonify({"status": "ok", **audit_service.meta()})

    @app.get("/api/audit-logs/<int:event_id>")
    def api_audit_log_detail(event_id: int):
        session, err_response, err_code = _require_auth(
            permission=PERMISSION_AUDIT_VIEW
        )
        if not session:
            return err_response, err_code

        if not audit_service:
            return _json_error("Audit log is unavailable", 503)
        event = audit_service.get_event(event_id)
        if not event:
            return _json_error("Audit event not found", 404)
        return jsonify({"status": "ok", "event": event})

    @app.delete("/api/database/regenerate")
    def api_regenerate_db():
        session, err_response, err_code = _require_auth(
            roles=(ROLE_SUPERADMIN,)
        )
        if not session:
            return err_response, err_code

        _audit(ACTION_DATABASE_REGENERATE, CATEGORY_DATABASE, session)
        try:
            deleted_count = regenerate_db()
        except Exception:
            LOGGER.exception("Database regeneration failed")
            return _json_error("Database regeneration failed", 500)

        return jsonify(
            {
                "status": "ok",
                "message": (
                    "Gateway events were deleted after creating a database "
                    "backup. A restart is not required."
                ),
                "deleted_count": deleted_count,
                "restarting": False,
            }
        )

    def _safe_static_file(path: str) -> Path | None:
        if not path:
            return None
        try:
            candidate = (frontend_dist / path).resolve()
            dist_root = frontend_dist.resolve()
        except (OSError, ValueError):
            return None
        if dist_root not in candidate.parents:
            return None
        if candidate.exists() and candidate.is_file():
            return candidate
        return None

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        if path.startswith("api/") or path.startswith("ws/"):
            return _json_error("Not found", 404)

        if frontend_dist.exists():
            asset_path = _safe_static_file(path)
            if asset_path is not None:
                return send_from_directory(
                    str(frontend_dist), str(asset_path.relative_to(frontend_dist))
                )
            return send_from_directory(str(frontend_dist), "index.html")

        return jsonify(
            {
                "message": "Frontend build not found.",
                "next_steps": [
                    "Run: cd frontend && npm ci",
                    "Run: npm run build",
                    "Restart this Python service",
                ],
            }
        )

    return app
