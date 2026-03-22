import os
import asyncio
import threading
from pathlib import Path
from dotenv import load_dotenv

from database import get_events, init_db, insert_event, regenerate_db
from discord import runbot
from webback import create_app

load_dotenv()
TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID")

ROOT_DIR = Path(__file__).resolve().parent
DB_PATH = ROOT_DIR / "manubot.db"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
API_PORT = int(os.getenv("API_PORT", "6540"))
BOT_STATE = {"connected": False, "last_sequence": None}

app = create_app(
    frontend_dist=FRONTEND_DIST,
    app_id=APP_ID,
    bot_state=BOT_STATE,
    get_events=lambda limit=25: get_events(DB_PATH, limit=limit),
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