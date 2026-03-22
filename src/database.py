import json
import sqlite3
from datetime import datetime
from pathlib import Path


def init_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gateway_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            sequence INTEGER,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def insert_event(db_path: Path, event_type: str, sequence, payload: dict) -> None:
    if event_type == "OP_11":
        return

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO gateway_events (event_type, sequence, payload, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (event_type, sequence, json.dumps(payload), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_events(db_path: Path, limit: int = 20) -> list[dict]:
    safe_limit = max(1, min(limit, 20))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, event_type, sequence, payload, created_at
        FROM gateway_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (safe_limit,),
    ).fetchall()
    conn.close()

    events = []
    for row in rows:
        events.append(
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "sequence": row["sequence"],
                "created_at": row["created_at"],
                "payload": json.loads(row["payload"]),
            }
        )

    return events


def regenerate_db(db_path: Path) -> int:
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    deleted_count = conn.execute("SELECT COUNT(*) FROM gateway_events").fetchone()[0]
    conn.execute("DELETE FROM gateway_events")
    conn.commit()
    conn.close()

    return int(deleted_count)
