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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dm_channels (
            channel_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dm_messages (
            message_id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            peer_user_id TEXT,
            author_id TEXT,
            author_username TEXT,
            author_display_name TEXT,
            author_avatar_url TEXT,
            author_is_bot INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL,
            attachments_json TEXT NOT NULL,
            timestamp TEXT,
            edited_timestamp TEXT,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dm_messages_peer_time
        ON dm_messages(peer_user_id, updated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_dm_messages_channel_time
        ON dm_messages(channel_id, updated_at DESC)
        """
    )
    conn.commit()
    conn.close()


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _upsert_dm_channel(conn: sqlite3.Connection, channel_id: str, user_id: str) -> None:
    if not channel_id or not user_id:
        return

    conn.execute(
        """
        INSERT INTO dm_channels (channel_id, user_id, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            user_id = excluded.user_id,
            updated_at = excluded.updated_at
        """,
        (channel_id, user_id, _utc_now()),
    )


def _get_dm_peer_from_channel(conn: sqlite3.Connection, channel_id: str) -> str | None:
    if not channel_id:
        return None

    row = conn.execute(
        """
        SELECT user_id
        FROM dm_channels
        WHERE channel_id = ?
        """,
        (channel_id,),
    ).fetchone()

    if not row:
        return None

    return str(row[0] or "") or None


def _upsert_dm_message_event(conn: sqlite3.Connection, event_type: str, payload: dict) -> None:
    data = payload.get("d") or {}
    if not isinstance(data, dict):
        return

    if data.get("guild_id") is not None:
        return

    channel_id = str(data.get("channel_id") or "")
    message_id = str(data.get("id") or "")
    if not channel_id or not message_id:
        return

    if event_type == "MESSAGE_DELETE":
        conn.execute(
            """
            UPDATE dm_messages
            SET deleted_at = ?, updated_at = ?
            WHERE message_id = ?
            """,
            (_utc_now(), _utc_now(), message_id),
        )
        return

    if event_type not in ("MESSAGE_CREATE", "MESSAGE_UPDATE"):
        return

    author = data.get("author") or {}
    if not isinstance(author, dict):
        author = {}

    author_id = str(author.get("id") or "") or None
    author_is_bot = bool(author.get("bot"))

    # For DMs, non-bot author is the peer user and can map channel->user.
    if author_id and not author_is_bot:
        _upsert_dm_channel(conn, channel_id=channel_id, user_id=author_id)

    peer_user_id = None
    if author_id and not author_is_bot:
        peer_user_id = author_id
    else:
        peer_user_id = _get_dm_peer_from_channel(conn, channel_id)

    username = author.get("username") or None
    display_name = author.get("global_name") or username
    avatar_url = _build_avatar_url(author_id, author.get("avatar")) if author_id else None

    content = (data.get("content") or "").strip()
    attachments = data.get("attachments") or []
    if not isinstance(attachments, list):
        attachments = []

    timestamp = data.get("timestamp")
    edited_timestamp = data.get("edited_timestamp")

    conn.execute(
        """
        INSERT INTO dm_messages (
            message_id,
            channel_id,
            peer_user_id,
            author_id,
            author_username,
            author_display_name,
            author_avatar_url,
            author_is_bot,
            content,
            attachments_json,
            timestamp,
            edited_timestamp,
            deleted_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            channel_id = excluded.channel_id,
            peer_user_id = COALESCE(excluded.peer_user_id, dm_messages.peer_user_id),
            author_id = COALESCE(excluded.author_id, dm_messages.author_id),
            author_username = COALESCE(excluded.author_username, dm_messages.author_username),
            author_display_name = COALESCE(excluded.author_display_name, dm_messages.author_display_name),
            author_avatar_url = COALESCE(excluded.author_avatar_url, dm_messages.author_avatar_url),
            author_is_bot = excluded.author_is_bot,
            content = CASE
                WHEN excluded.content = '' THEN dm_messages.content
                ELSE excluded.content
            END,
            attachments_json = excluded.attachments_json,
            timestamp = COALESCE(excluded.timestamp, dm_messages.timestamp),
            edited_timestamp = COALESCE(excluded.edited_timestamp, dm_messages.edited_timestamp),
            deleted_at = NULL,
            updated_at = excluded.updated_at
        """,
        (
            message_id,
            channel_id,
            peer_user_id,
            author_id,
            username,
            display_name,
            avatar_url,
            1 if author_is_bot else 0,
            content,
            json.dumps(attachments),
            timestamp,
            edited_timestamp,
            None,
            _utc_now(),
            _utc_now(),
        ),
    )


def save_sent_dm_message(db_path: Path, peer_user_id: str, message_payload: dict) -> None:
    if not isinstance(message_payload, dict):
        return

    conn = sqlite3.connect(db_path)

    channel_id = str(message_payload.get("channel_id") or "")
    message_id = str(message_payload.get("id") or "")
    if not channel_id or not message_id:
        conn.close()
        return

    _upsert_dm_channel(conn, channel_id=channel_id, user_id=peer_user_id)

    author = message_payload.get("author") or {}
    if not isinstance(author, dict):
        author = {}

    author_id = str(author.get("id") or "") or None
    username = author.get("username") or None
    display_name = author.get("global_name") or username
    avatar_url = _build_avatar_url(author_id, author.get("avatar")) if author_id else None

    attachments = message_payload.get("attachments") or []
    if not isinstance(attachments, list):
        attachments = []

    conn.execute(
        """
        INSERT INTO dm_messages (
            message_id,
            channel_id,
            peer_user_id,
            author_id,
            author_username,
            author_display_name,
            author_avatar_url,
            author_is_bot,
            content,
            attachments_json,
            timestamp,
            edited_timestamp,
            deleted_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            peer_user_id = excluded.peer_user_id,
            content = excluded.content,
            attachments_json = excluded.attachments_json,
            deleted_at = NULL,
            updated_at = excluded.updated_at
        """,
        (
            message_id,
            channel_id,
            peer_user_id,
            author_id,
            username,
            display_name,
            avatar_url,
            1 if author.get("bot") else 0,
            (message_payload.get("content") or "").strip(),
            json.dumps(attachments),
            message_payload.get("timestamp"),
            message_payload.get("edited_timestamp"),
            None,
            _utc_now(),
            _utc_now(),
        ),
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
    _upsert_dm_message_event(conn, event_type=event_type, payload=payload)
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


def _build_avatar_url(user_id: str | None, avatar_hash: str | None) -> str | None:
    if not user_id or not avatar_hash:
        return None

    ext = "gif" if str(avatar_hash).startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=128"


def get_dm_users(db_path: Path, limit_events: int = 300) -> list[dict]:
    safe_limit = max(1, min(limit_events, 1000))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, event_type, payload, created_at
        FROM gateway_events
        WHERE event_type LIKE 'MESSAGE_%'
        ORDER BY id DESC
        LIMIT ?
        """,
        (safe_limit,),
    ).fetchall()
    conn.close()

    grouped: dict[str, dict] = {}

    for row in rows:
        payload = json.loads(row["payload"])
        data = payload.get("d") or {}
        if not isinstance(data, dict):
            continue

        if data.get("guild_id") is not None:
            continue

        author = data.get("author") or {}
        if not isinstance(author, dict):
            continue

        user_id = str(author.get("id") or "unknown")
        username = author.get("username") or "Unknown"
        global_name = author.get("global_name")
        discriminator = author.get("discriminator")
        is_bot = bool(author.get("bot"))
        display_name = global_name or username
        avatar_url = _build_avatar_url(str(author.get("id") or ""), author.get("avatar"))

        content = (data.get("content") or "").strip()
        attachments = data.get("attachments") or []
        if not content and attachments:
            content = f"[{len(attachments)} attachment(s)]"
        if not content:
            content = "[no text content]"

        channel_id = str(data.get("channel_id") or "")
        existing = grouped.get(user_id)
        if existing is None:
            grouped[user_id] = {
                "user_id": user_id,
                "username": username,
                "global_name": global_name,
                "display_name": display_name,
                "discriminator": discriminator,
                "avatar_url": avatar_url,
                "is_bot": is_bot,
                "message_count": 1,
                "last_message_preview": content[:160],
                "last_event_type": row["event_type"],
                "last_activity": row["created_at"],
                "channels": {channel_id} if channel_id else set(),
            }
            continue

        existing["message_count"] += 1
        if channel_id:
            existing["channels"].add(channel_id)

    users = list(grouped.values())
    for user in users:
        user["channel_count"] = len(user["channels"])
        del user["channels"]

    users.sort(key=lambda item: item.get("last_activity") or "", reverse=True)
    return users


def get_dm_history(db_path: Path, user_id: str, limit: int = 100) -> list[dict]:
    safe_limit = max(1, min(limit, 300))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            message_id,
            channel_id,
            peer_user_id,
            author_id,
            author_username,
            author_display_name,
            author_avatar_url,
            author_is_bot,
            content,
            attachments_json,
            timestamp,
            edited_timestamp,
            deleted_at,
            updated_at
        FROM dm_messages
        WHERE peer_user_id = ?
          AND deleted_at IS NULL
        ORDER BY COALESCE(timestamp, updated_at) DESC
        LIMIT ?
        """,
        (user_id, safe_limit),
    ).fetchall()
    conn.close()

    history: list[dict] = []
    for row in reversed(rows):
        attachments = []
        try:
            attachments = json.loads(row["attachments_json"] or "[]")
            if not isinstance(attachments, list):
                attachments = []
        except json.JSONDecodeError:
            attachments = []

        history.append(
            {
                "message_id": row["message_id"],
                "channel_id": row["channel_id"],
                "peer_user_id": row["peer_user_id"],
                "author": {
                    "id": row["author_id"],
                    "username": row["author_username"],
                    "display_name": row["author_display_name"],
                    "avatar_url": row["author_avatar_url"],
                    "is_bot": bool(row["author_is_bot"]),
                },
                "content": row["content"],
                "attachments": attachments,
                "timestamp": row["timestamp"] or row["updated_at"],
                "edited_timestamp": row["edited_timestamp"],
            }
        )

    return history


def get_dm_message(db_path: Path, message_id: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT message_id, channel_id, peer_user_id, author_id, author_is_bot, deleted_at
        FROM dm_messages
        WHERE message_id = ?
        """,
        (message_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "message_id": row["message_id"],
        "channel_id": row["channel_id"],
        "peer_user_id": row["peer_user_id"],
        "author_id": row["author_id"],
        "author_is_bot": bool(row["author_is_bot"]),
        "deleted_at": row["deleted_at"],
    }


def mark_dm_message_deleted(db_path: Path, message_id: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        UPDATE dm_messages
        SET deleted_at = ?, updated_at = ?
        WHERE message_id = ?
        """,
        (_utc_now(), _utc_now(), message_id),
    )
    conn.commit()
    conn.close()


def regenerate_db(db_path: Path) -> int:
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    deleted_count = conn.execute("SELECT COUNT(*) FROM gateway_events").fetchone()[0]
    conn.execute("DELETE FROM gateway_events")
    conn.commit()
    conn.close()

    return int(deleted_count)


def init_account_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS panel_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'moderator')),
            permissions_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_panel_accounts_role
        ON panel_accounts(role)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS panel_sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            account_id INTEGER,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0,
            revoked_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_panel_sessions_user_role
        ON panel_sessions(username, role)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_panel_sessions_revoked_expiry
        ON panel_sessions(revoked, expires_at)
        """
    )
    conn.commit()
    conn.close()


def insert_panel_session(
    db_path: Path,
    token: str,
    username: str,
    role: str,
    account_id: int | None,
    issued_at: str,
    expires_at: str,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO panel_sessions (token, username, role, account_id, issued_at, expires_at, revoked, revoked_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
        """,
        (token, username, role, account_id, issued_at, expires_at),
    )
    conn.commit()
    conn.close()


def get_panel_session_by_token(db_path: Path, token: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT token, username, role, account_id, issued_at, expires_at, revoked
        FROM panel_sessions
        WHERE token = ?
        """,
        (token,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "token": str(row["token"]),
        "username": str(row["username"]),
        "role": str(row["role"]),
        "account_id": row["account_id"],
        "issued_at": str(row["issued_at"]),
        "expires_at": str(row["expires_at"]),
        "revoked": int(row["revoked"] or 0),
    }


def revoke_panel_session_by_token(db_path: Path, token: str, revoked_at: str) -> int:
    conn = sqlite3.connect(db_path)
    result = conn.execute(
        """
        UPDATE panel_sessions
        SET revoked = 1, revoked_at = ?
        WHERE token = ? AND revoked = 0
        """,
        (revoked_at, token),
    )
    conn.commit()
    conn.close()
    return int(result.rowcount or 0)


def revoke_panel_sessions_by_username(
    db_path: Path,
    username: str,
    revoked_at: str,
    exclude_token: str | None = None,
) -> int:
    conn = sqlite3.connect(db_path)
    if exclude_token:
        result = conn.execute(
            """
            UPDATE panel_sessions
            SET revoked = 1, revoked_at = ?
            WHERE lower(username) = lower(?) AND revoked = 0 AND token != ?
            """,
            (revoked_at, username, exclude_token),
        )
    else:
        result = conn.execute(
            """
            UPDATE panel_sessions
            SET revoked = 1, revoked_at = ?
            WHERE lower(username) = lower(?) AND revoked = 0
            """,
            (revoked_at, username),
        )
    conn.commit()
    conn.close()
    return int(result.rowcount or 0)


def revoke_panel_sessions_by_identity(db_path: Path, username: str, role: str, revoked_at: str) -> int:
    conn = sqlite3.connect(db_path)
    result = conn.execute(
        """
        UPDATE panel_sessions
        SET revoked = 1, revoked_at = ?
        WHERE revoked = 0 AND lower(username) = lower(?) AND role = ?
        """,
        (revoked_at, username, role),
    )
    conn.commit()
    conn.close()
    return int(result.rowcount or 0)


def revoke_all_panel_sessions_by_roles(db_path: Path, roles: list[str], revoked_at: str) -> int:
    if not roles:
        return 0

    placeholders = ",".join("?" for _ in roles)
    conn = sqlite3.connect(db_path)
    result = conn.execute(
        f"""
        UPDATE panel_sessions
        SET revoked = 1, revoked_at = ?
        WHERE revoked = 0 AND role IN ({placeholders})
        """,
        (revoked_at, *roles),
    )
    conn.commit()
    conn.close()
    return int(result.rowcount or 0)


def get_panel_account_by_username(db_path: Path, username: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT id, username, password_hash, role, permissions_json, created_at, updated_at
        FROM panel_accounts
        WHERE lower(username) = lower(?)
        """,
        (username,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "password_hash": str(row["password_hash"]),
        "role": str(row["role"]),
        "permissions_json": str(row["permissions_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_panel_account_by_id(db_path: Path, account_id: int) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT id, username, password_hash, role, permissions_json, created_at, updated_at
        FROM panel_accounts
        WHERE id = ?
        """,
        (account_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "password_hash": str(row["password_hash"]),
        "role": str(row["role"]),
        "permissions_json": str(row["permissions_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_panel_accounts(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, username, role, permissions_json, created_at, updated_at
        FROM panel_accounts
        ORDER BY role ASC, username ASC
        """
    ).fetchall()
    conn.close()

    result: list[dict] = []
    for row in rows:
        result.append(
            {
                "id": int(row["id"]),
                "username": str(row["username"]),
                "role": str(row["role"]),
                "permissions_json": str(row["permissions_json"] or "{}"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return result


def insert_panel_account(
    db_path: Path,
    username: str,
    password_hash: str,
    role: str,
    permissions_json: str,
    created_at: str,
    updated_at: str,
) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO panel_accounts (username, password_hash, role, permissions_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, password_hash, role, permissions_json, created_at, updated_at),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def update_panel_account_permissions(db_path: Path, account_id: int, permissions_json: str, updated_at: str) -> int:
    conn = sqlite3.connect(db_path)
    result = conn.execute(
        """
        UPDATE panel_accounts
        SET permissions_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (permissions_json, updated_at, account_id),
    )
    conn.commit()
    conn.close()
    return int(result.rowcount or 0)


def update_panel_account_password(db_path: Path, account_id: int, password_hash: str, updated_at: str) -> int:
    conn = sqlite3.connect(db_path)
    result = conn.execute(
        """
        UPDATE panel_accounts
        SET password_hash = ?, updated_at = ?
        WHERE id = ?
        """,
        (password_hash, updated_at, account_id),
    )
    conn.commit()
    conn.close()
    return int(result.rowcount or 0)
