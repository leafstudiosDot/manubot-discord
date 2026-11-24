import asyncio
import json
import logging
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

from accounts import AccountService
from audit import AuditService
from config import Settings
from database import (
    get_dm_history,
    get_dm_message,
    get_dm_users,
    get_events,
    get_mousetrap_config,
    init_db,
    insert_event,
    mark_dm_message_deleted,
    prune_old_records,
    regenerate_db,
    save_sent_dm_message,
)
from discord import delete_dm, get_guild_channels, runbot, send_dm
from gateway_lock import GatewayLock
from mousetrap import (
    build_mousetrap_logs,
    handle_guild_message,
    set_mousetrap_channel,
)
from webback import create_app

load_dotenv()

SETTINGS = Settings.from_env()
LOGGER = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID")
SUPERADMIN_USERNAME = os.getenv("SUPERADMIN_USERNAME")
SUPERADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD")
SUPERADMIN_PASSWORD_HASH = os.getenv("SUPERADMIN_PASSWORD_HASH")

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT_DIR / "manubot.db"
DB_PATH = Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH)))
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
BACKUP_DIR = Path(SETTINGS.backup_dir) if SETTINGS.backup_dir else DB_PATH.parent / "backups"
GATEWAY_LOCK_PATH = DB_PATH.parent / "manubot-gateway.lock"

_gateway_lock = GatewayLock(GATEWAY_LOCK_PATH)
_gateway_thread: threading.Thread | None = None
_database_initialized = False


def resolve_app_version() -> str:
    env_version = (os.getenv("APP_VERSION") or "").strip()
    if env_version:
        return env_version if env_version.startswith("v") else f"v{env_version}"

    package_json_path = ROOT_DIR / "frontend" / "package.json"
    try:
        package_data = json.loads(package_json_path.read_text(encoding="utf-8"))
        package_version = str(package_data.get("version") or "").strip()
        if package_version:
            return package_version if package_version.startswith("v") else f"v{package_version}"
    except Exception:
        pass

    return "v0.0.0"


BOT_STATE = {
    "connected": False,
    "last_sequence": None,
    "version": resolve_app_version(),
    "app_id": APP_ID,
    "bot_user_id": None,
    "profile": None,
    "guilds": [],
}

audit_service = AuditService(DB_PATH)
account_service = AccountService(
    db_path=DB_PATH,
    superadmin_username=SUPERADMIN_USERNAME or "",
    superadmin_password=SUPERADMIN_PASSWORD or "",
    superadmin_password_hash=SUPERADMIN_PASSWORD_HASH,
    settings=SETTINGS,
    audit_service=audit_service,
)


def _save_mousetrap_config(server_id: str, channel_id: str | None):
    try:
        return asyncio.run(
            set_mousetrap_channel(
                TOKEN, DB_PATH, guild_id=server_id, channel_id=channel_id
            )
        )
    except Exception:
        LOGGER.exception("Failed to update MouseTrap channel for %s", server_id)
        existing = get_mousetrap_config(DB_PATH, guild_id=server_id)
        return {
            "guild_id": server_id,
            "channel_id": channel_id,
            "kick_count": int(existing.get("kick_count") or 0) if existing else 0,
            "enabled": bool(channel_id),
            "warning": "The Discord channel could not be updated.",
        }


app = create_app(
    frontend_dist=FRONTEND_DIST,
    app_id=APP_ID,
    bot_state=BOT_STATE,
    account_service=account_service,
    get_guild_channels=lambda server_id: asyncio.run(
        get_guild_channels(TOKEN, guild_id=server_id)
    ),
    get_mousetrap_config=lambda server_id: get_mousetrap_config(
        DB_PATH, guild_id=server_id
    ),
    save_mousetrap_config=lambda server_id, channel_id: _save_mousetrap_config(
        server_id, channel_id
    ),
    get_mousetrap_logs=lambda server_id, channel_id=None, limit=100: asyncio.run(
        build_mousetrap_logs(
            TOKEN,
            DB_PATH,
            guild_id=server_id,
            channel_id=channel_id,
            limit=limit,
        )
    ),
    get_events=lambda limit=25: get_events(DB_PATH, limit=limit),
    get_dm_users=lambda limit_events=300: get_dm_users(
        DB_PATH, limit_events=limit_events
    ),
    get_dm_history=lambda user_id, limit=120: get_dm_history(
        DB_PATH, user_id=user_id, limit=limit
    ),
    get_dm_message=lambda message_id: get_dm_message(
        DB_PATH, message_id=message_id
    ),
    save_sent_dm_message=lambda user_id, message_payload: save_sent_dm_message(
        DB_PATH, peer_user_id=user_id, message_payload=message_payload
    ),
    mark_dm_message_deleted=lambda message_id: mark_dm_message_deleted(
        DB_PATH, message_id=message_id
    ),
    send_dm=lambda user_id, content, files: asyncio.run(
        send_dm(TOKEN, user_id=user_id, content=content, files=files)
    ),
    delete_dm=lambda channel_id, message_id: asyncio.run(
        delete_dm(TOKEN, channel_id=channel_id, message_id=message_id)
    ),
    regenerate_db=lambda: regenerate_db(
        DB_PATH,
        backup_dir=BACKUP_DIR,
        backup_retention=SETTINGS.backup_retention,
    ),
    audit_service=audit_service,
    settings=SETTINGS,
)


def initialize_database() -> None:
    global _database_initialized
    if _database_initialized:
        return

    init_db(DB_PATH)
    account_service.init_db()
    prune_old_records(
        DB_PATH,
        event_retention_days=SETTINGS.event_retention_days,
        mousetrap_log_retention_days=SETTINGS.mousetrap_log_retention_days,
        audit_log_retention_days=SETTINGS.audit_log_retention_days,
    )
    _database_initialized = True


def _run_gateway() -> None:
    try:
        asyncio.run(
            runbot(
                token=TOKEN,
                bot_state=BOT_STATE,
                save_event=lambda event_type, sequence, payload: insert_event(
                    DB_PATH, event_type, sequence, payload
                ),
                handle_guild_message=lambda payload: handle_guild_message(
                    TOKEN, DB_PATH, payload, settings=SETTINGS
                ),
            )
        )
    except Exception:
        LOGGER.exception("Discord gateway stopped unexpectedly")
        BOT_STATE["connected"] = False


def start_gateway_thread() -> bool:
    """Start exactly one Discord Gateway connection per host.

    The OS-level lock prevents a second process (for example an accidental
    multi-worker Gunicorn deployment) from opening a duplicate gateway session.
    """
    global _gateway_thread

    if not SETTINGS.gateway_enabled:
        LOGGER.info("Discord gateway is disabled by configuration")
        return False
    if not TOKEN:
        raise RuntimeError("TOKEN is required to start the Discord gateway")
    if _gateway_thread and _gateway_thread.is_alive():
        return True
    if not _gateway_lock.acquire():
        LOGGER.error(
            "Another Manubot process already holds the Discord gateway lock"
        )
        return False

    _gateway_thread = threading.Thread(
        target=_run_gateway,
        name="discord-gateway",
        daemon=True,
    )
    _gateway_thread.start()
    return True


def validate_startup_configuration() -> None:
    if not SUPERADMIN_USERNAME:
        raise RuntimeError(
            "SUPERADMIN_USERNAME is required to run the panel."
        )
    if not SUPERADMIN_PASSWORD and not SUPERADMIN_PASSWORD_HASH:
        raise RuntimeError(
            "Set SUPERADMIN_PASSWORD_HASH (recommended) or SUPERADMIN_PASSWORD."
        )
    if SETTINGS.production and SETTINGS.csrf_secret_ephemeral:
        LOGGER.warning(
            "CSRF_SECRET is not set. Sessions will be invalidated across restarts; "
            "set a persistent value in production."
        )
    if SETTINGS.production and SETTINGS.trust_proxy_headers:
        LOGGER.warning(
            "TRUST_PROXY_HEADERS is enabled. Only use it behind a reverse proxy "
            "that overwrites X-Forwarded-* headers."
        )
    if not APP_ID:
        LOGGER.warning("APP_ID is missing; health responses will show it as null.")


def run_development_server() -> None:
    LOGGER.info(
        "Development server listening on http://%s:%s",
        SETTINGS.api_host,
        SETTINGS.api_port,
    )
    app.run(
        host=SETTINGS.api_host,
        port=SETTINGS.api_port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, SETTINGS.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    validate_startup_configuration()
    initialize_database()
    start_gateway_thread()

    if SETTINGS.production:
        raise RuntimeError(
            "The Flask development server is disabled in production. "
            "Run: gunicorn --config gunicorn.conf.py wsgi:app"
        )

    run_development_server()


if __name__ == "__main__":
    main()
