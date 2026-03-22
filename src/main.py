import os
import asyncio
import threading
from pathlib import Path
from dotenv import load_dotenv

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

ROOT_DIR = Path(__file__).resolve().parent
DB_PATH = ROOT_DIR / "manubot.db"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
API_PORT = int(os.getenv("API_PORT", "6540"))
BOT_STATE = {
    "connected": False,
    "last_sequence": None,
    "app_id": APP_ID,
    "bot_user_id": None,
    "profile": None,
    "guilds": [],
}

app = create_app(
    frontend_dist=FRONTEND_DIST,
    app_id=APP_ID,
    bot_state=BOT_STATE,
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
        raise RuntimeError("TOKEN is missing from .env")

    if not APP_ID:
        print("Warning: APP_ID is missing from .env. Health endpoint will show app_id as null.")

    init_db(DB_PATH)
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