import os
import json
import asyncio
import threading
from pathlib import Path
from dotenv import load_dotenv
from accounts import AccountService

from database import (
    get_dm_history,
    get_dm_message,
    get_dm_users,
    get_events,
    init_db,
    insert_event,
    mark_dm_message_deleted,
    regenerate_db,
    save_sent_dm_message,
)
from discord import runbot, send_dm, delete_dm
from webback import create_app

load_dotenv()
TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID")
SUPERADMIN_USERNAME = os.getenv("SUPERADMIN_USERNAME")
SUPERADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD")
SUPERADMIN_PASSWORD_HASH = os.getenv("SUPERADMIN_PASSWORD_HASH")

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT_DIR / "manubot.db"
DB_PATH = Path(os.getenv("DB_PATH", str(DEFAULT_DB_PATH)))
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
API_PORT = int(os.getenv("API_PORT", "6540"))


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

account_service = AccountService(
    db_path=DB_PATH,
    superadmin_username=SUPERADMIN_USERNAME or "",
    superadmin_password=SUPERADMIN_PASSWORD or "",
    superadmin_password_hash=SUPERADMIN_PASSWORD_HASH,
)

app = create_app(
    frontend_dist=FRONTEND_DIST,
    app_id=APP_ID,
    bot_state=BOT_STATE,
    account_service=account_service,
    get_events=lambda limit=25: get_events(DB_PATH, limit=limit),
    get_dm_users=lambda limit_events=300: get_dm_users(DB_PATH, limit_events=limit_events),
    get_dm_history=lambda user_id, limit=120: get_dm_history(DB_PATH, user_id=user_id, limit=limit),
    get_dm_message=lambda message_id: get_dm_message(DB_PATH, message_id=message_id),
    save_sent_dm_message=lambda user_id, message_payload: save_sent_dm_message(
        DB_PATH, peer_user_id=user_id, message_payload=message_payload
    ),
    mark_dm_message_deleted=lambda message_id: mark_dm_message_deleted(DB_PATH, message_id=message_id),
    send_dm=lambda user_id, content, files: asyncio.run(
        send_dm(TOKEN, user_id=user_id, content=content, files=files)
    ),
    delete_dm=lambda channel_id, message_id: asyncio.run(
        delete_dm(TOKEN, channel_id=channel_id, message_id=message_id)
    ),
    regenerate_db=lambda: regenerate_db(DB_PATH),
)


def run_flask_server():
    app.run(host="0.0.0.0", port=API_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "TOKEN is missing from .env. TOKEN and SUPERADMIN_USERNAME are required to run the server."
        )

    if not SUPERADMIN_USERNAME:
        raise RuntimeError(
            "SUPERADMIN_USERNAME is missing from .env. TOKEN and SUPERADMIN_USERNAME are required to run the server."
        )

    if not APP_ID:
        print("Warning: APP_ID is missing from .env. Health endpoint will show app_id as null.")

    init_db(DB_PATH)
    account_service.init_db()

    print(f"Flask API listening on http://localhost:{API_PORT}")

    flask_thread = threading.Thread(target=run_flask_server, daemon=True)
    flask_thread.start()

    asyncio.run(
        runbot(
            token=TOKEN,
            bot_state=BOT_STATE,
            save_event=lambda event_type, sequence, payload: insert_event(
                DB_PATH, event_type, sequence, payload
            ),
        )
    )