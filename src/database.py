import base64
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from media import is_allowed_media_type, normalize_media_content_type
from security import sanitize_content_type, sanitize_filename, sha256_hex, utc_now_iso


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mousetrap_configs (
            guild_id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            kick_count INTEGER NOT NULL DEFAULT 0,
            notice_channel_id TEXT,
            notice_message_id TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mousetrap_message_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            content TEXT NOT NULL,
            attachments_json TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mousetrap_message_attachment_blobs (
            log_id INTEGER NOT NULL,
            attachment_index INTEGER NOT NULL,
            filename TEXT,
            content_type TEXT,
            size INTEGER,
            blob BLOB NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (log_id, attachment_index),
            FOREIGN KEY (log_id) REFERENCES mousetrap_message_logs(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_mousetrap_logs_guild_channel_time
        ON mousetrap_message_logs(guild_id, channel_id, occurred_at DESC)
        """
    )
    _ensure_mousetrap_attachment_blob_columns(conn)
    _ensure_mousetrap_config_columns(conn)
    _ensure_audit_table(conn)
    conn.commit()
    conn.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _ensure_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_account_id INTEGER,
            actor_username TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            action TEXT NOT NULL,
            category TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_audit_log_created
        ON admin_audit_log(created_at DESC, id DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_audit_log_actor
        ON admin_audit_log(actor_username, created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_audit_log_action
        ON admin_audit_log(action, created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_admin_audit_log_category
        ON admin_audit_log(category, created_at DESC)
        """
    )


def _ensure_mousetrap_config_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(mousetrap_configs)").fetchall()
    existing_columns = {str(row[1]) for row in rows}

    if "notice_channel_id" not in existing_columns:
        conn.execute("ALTER TABLE mousetrap_configs ADD COLUMN notice_channel_id TEXT")

    if "notice_message_id" not in existing_columns:
        conn.execute("ALTER TABLE mousetrap_configs ADD COLUMN notice_message_id TEXT")


def _ensure_mousetrap_attachment_blob_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(mousetrap_message_attachment_blobs)").fetchall()
    existing_columns = {str(row[1]) for row in rows}

    if "filename" not in existing_columns:
        conn.execute("ALTER TABLE mousetrap_message_attachment_blobs ADD COLUMN filename TEXT")

    if "content_type" not in existing_columns:
        conn.execute("ALTER TABLE mousetrap_message_attachment_blobs ADD COLUMN content_type TEXT")

    if "size" not in existing_columns:
        conn.execute("ALTER TABLE mousetrap_message_attachment_blobs ADD COLUMN size INTEGER")

    if "blob" not in existing_columns:
        conn.execute("ALTER TABLE mousetrap_message_attachment_blobs ADD COLUMN blob BLOB")

    if "created_at" not in existing_columns:
        conn.execute("ALTER TABLE mousetrap_message_attachment_blobs ADD COLUMN created_at TEXT")


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
        (event_type, sequence, json.dumps(payload), datetime.now(timezone.utc).replace(tzinfo=None).isoformat()),
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


def create_database_backup(
    db_path: Path,
    backup_dir: Path | None = None,
    retention: int = 5,
) -> Path | None:
    """Create a consistent snapshot before destructive maintenance.

    Backups contain all application data, including account hashes and DMs, so
    the backup directory must be treated as sensitive and kept off public
    static paths.
    """
    source_path = Path(db_path)
    if not source_path.exists():
        return None

    target_dir = Path(backup_dir) if backup_dir else source_path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y%m%dT%H%M%S%fZ")
    target_path = target_dir / f"{source_path.stem}-{stamp}.db"

    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(target_path)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()

    try:
        os.chmod(target_path, 0o600)
    except OSError:
        pass

    if retention > 0:
        backups = sorted(
            target_dir.glob(f"{source_path.stem}-*.db"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for stale in backups[retention:]:
            try:
                stale.unlink()
            except OSError:
                pass

    return target_path


def regenerate_db(
    db_path: Path,
    backup_dir: Path | None = None,
    backup_retention: int = 5,
) -> int:
    """Delete captured gateway events after taking a verified backup.

    User accounts, sessions, audit records, MouseTrap configuration and logs
    are intentionally preserved.
    """
    init_db(db_path)
    create_database_backup(
        db_path,
        backup_dir=backup_dir,
        retention=backup_retention,
    )

    conn = sqlite3.connect(db_path)
    deleted_count = conn.execute("SELECT COUNT(*) FROM gateway_events").fetchone()[0]
    conn.execute("DELETE FROM gateway_events")
    conn.commit()
    conn.close()

    return int(deleted_count)


def prune_old_records(
    db_path: Path,
    event_retention_days: int = 0,
    mousetrap_log_retention_days: int = 0,
    audit_log_retention_days: int = 0,
) -> dict[str, int]:
    """Optionally prune old rows. A value of 0 disables pruning."""
    removed = {"gateway_events": 0, "mousetrap_message_logs": 0, "admin_audit_log": 0}
    if max(event_retention_days, mousetrap_log_retention_days, audit_log_retention_days) <= 0:
        return removed

    conn = sqlite3.connect(db_path)
    try:
        if event_retention_days > 0:
            cutoff = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=event_retention_days)).isoformat()
            cursor = conn.execute(
                "DELETE FROM gateway_events WHERE created_at < ?",
                (cutoff,),
            )
            removed["gateway_events"] = int(cursor.rowcount or 0)

        if mousetrap_log_retention_days > 0:
            cutoff = (
                datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=mousetrap_log_retention_days)
            ).isoformat()
            old_ids = [
                int(row[0])
                for row in conn.execute(
                    "SELECT id FROM mousetrap_message_logs WHERE occurred_at < ?",
                    (cutoff,),
                ).fetchall()
            ]
            if old_ids:
                placeholders = ",".join("?" for _ in old_ids)
                conn.execute(
                    f"DELETE FROM mousetrap_message_attachment_blobs WHERE log_id IN ({placeholders})",
                    old_ids,
                )
                cursor = conn.execute(
                    f"DELETE FROM mousetrap_message_logs WHERE id IN ({placeholders})",
                    old_ids,
                )
                removed["mousetrap_message_logs"] = int(cursor.rowcount or 0)

        if audit_log_retention_days > 0:
            cutoff = (
                datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=audit_log_retention_days)
            ).isoformat()
            cursor = conn.execute(
                "DELETE FROM admin_audit_log WHERE created_at < ?",
                (cutoff,),
            )
            removed["admin_audit_log"] = int(cursor.rowcount or 0)

        conn.commit()
    finally:
        conn.close()

    return removed


def delete_mousetrap_config(db_path: Path, guild_id: str) -> None:
    if not guild_id:
        return

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        DELETE FROM mousetrap_configs
        WHERE guild_id = ?
        """,
        (guild_id,),
    )
    conn.commit()
    conn.close()


def update_mousetrap_notice_target(
    db_path: Path,
    guild_id: str,
    notice_channel_id: str | None,
    notice_message_id: str | None,
) -> None:
    if not guild_id:
        return

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        UPDATE mousetrap_configs
        SET notice_channel_id = ?,
            notice_message_id = ?,
            updated_at = ?
        WHERE guild_id = ?
        """,
        (notice_channel_id, notice_message_id, _utc_now(), guild_id),
    )
    conn.commit()
    conn.close()


def upsert_mousetrap_config(db_path: Path, guild_id: str, channel_id: str, kick_count: int | None = None) -> None:
    if not guild_id:
        return

    conn = sqlite3.connect(db_path)
    current_kick_count = None
    if kick_count is not None:
        current_kick_count = max(0, int(kick_count or 0))
    else:
        row = conn.execute(
            """
            SELECT kick_count
            FROM mousetrap_configs
            WHERE guild_id = ?
            """,
            (guild_id,),
        ).fetchone()
        if row:
            current_kick_count = int(row[0] or 0)

    if current_kick_count is None:
        current_kick_count = 0

    conn.execute(
        """
        INSERT INTO mousetrap_configs (guild_id, channel_id, kick_count, notice_channel_id, notice_message_id, updated_at)
        VALUES (?, ?, ?, NULL, NULL, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            channel_id = excluded.channel_id,
            kick_count = excluded.kick_count,
            notice_channel_id = NULL,
            notice_message_id = NULL,
            updated_at = excluded.updated_at
        """,
        (guild_id, channel_id, current_kick_count, _utc_now()),
    )
    conn.commit()
    conn.close()


def get_mousetrap_config(db_path: Path, guild_id: str) -> dict | None:
    if not guild_id:
        return None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT guild_id, channel_id, kick_count, notice_channel_id, notice_message_id, updated_at
        FROM mousetrap_configs
        WHERE guild_id = ?
        """,
        (guild_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "guild_id": row["guild_id"],
        "channel_id": row["channel_id"],
        "kick_count": int(row["kick_count"] or 0),
        "notice_channel_id": row["notice_channel_id"] if "notice_channel_id" in row.keys() else None,
        "notice_message_id": row["notice_message_id"] if "notice_message_id" in row.keys() else None,
        "updated_at": row["updated_at"],
    }


def increment_mousetrap_kick_count(db_path: Path, guild_id: str, amount: int = 1) -> int:
    if not guild_id:
        return 0

    increment = max(1, int(amount or 1))
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        """
        SELECT channel_id, kick_count, notice_channel_id, notice_message_id
        FROM mousetrap_configs
        WHERE guild_id = ?
        """,
        (guild_id,),
    ).fetchone()

    if not row:
        conn.close()
        return 0

    channel_id = str(row[0] or "")
    current_kick_count = int(row[1] or 0)
    notice_channel_id = str(row[2] or "") or None
    notice_message_id = str(row[3] or "") or None
    conn.execute(
        """
        UPDATE mousetrap_configs
        SET channel_id = ?,
            kick_count = ?,
            notice_channel_id = ?,
            notice_message_id = ?,
            updated_at = ?
        WHERE guild_id = ?
        """,
        (channel_id, current_kick_count + increment, notice_channel_id, notice_message_id, _utc_now(), guild_id),
    )
    conn.commit()
    conn.close()
    return current_kick_count + increment


def insert_mousetrap_message_log(
    db_path: Path,
    guild_id: str,
    channel_id: str,
    user_id: str,
    content: str,
    attachments: list[dict] | None,
    occurred_at: str,
) -> None:
    if not guild_id or not channel_id or not user_id:
        return

    normalized_attachments = attachments if isinstance(attachments, list) else []
    attachment_rows = []
    for index, attachment in enumerate(normalized_attachments):
        if not isinstance(attachment, dict):
            continue

        blob_value = attachment.get("cached_blob")
        if isinstance(blob_value, memoryview):
            blob_value = blob_value.tobytes()

        if not isinstance(blob_value, (bytes, bytearray)):
            continue

        cached_content_type = normalize_media_content_type(
            attachment.get("cached_content_type") or attachment.get("content_type")
        )
        if not is_allowed_media_type(cached_content_type):
            continue

        attachment_rows.append(
            (
                index,
                sanitize_filename(attachment.get("filename")),
                cached_content_type,
                int(attachment.get("cached_size") or len(blob_value)),
                bytes(blob_value),
                _utc_now(),
            )
        )

    sanitized_attachments = []
    for attachment in normalized_attachments:
        if not isinstance(attachment, dict):
            continue

        sanitized_attachment = dict(attachment)
        sanitized_attachment.pop("cached_blob", None)
        sanitized_attachment.pop("cached_data_url", None)
        sanitized_attachment["filename"] = sanitize_filename(
            attachment.get("filename")
        )
        sanitized_attachment["content_type"] = sanitize_content_type(
            attachment.get("content_type")
        )
        if attachment.get("cached_content_type"):
            sanitized_attachment["cached_content_type"] = sanitize_content_type(
                attachment.get("cached_content_type")
            )
        sanitized_attachments.append(sanitized_attachment)

    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        """
        INSERT INTO mousetrap_message_logs (
            guild_id,
            channel_id,
            user_id,
            content,
            attachments_json,
            occurred_at,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            guild_id,
            channel_id,
            user_id,
            (content or "").strip(),
            json.dumps(sanitized_attachments),
            occurred_at or _utc_now(),
            _utc_now(),
        ),
    )
    log_id = cursor.lastrowid

    if log_id and attachment_rows:
        conn.executemany(
            """
            INSERT INTO mousetrap_message_attachment_blobs (
                log_id,
                attachment_index,
                filename,
                content_type,
                size,
                blob,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [(log_id, *row) for row in attachment_rows],
        )

    conn.commit()
    conn.close()


def list_mousetrap_message_logs(db_path: Path, guild_id: str, channel_id: str | None = None, limit: int = 100) -> list[dict]:
    if not guild_id:
        return []

    safe_limit = max(1, min(limit, 500))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    params: list[object] = [guild_id]
    channel_clause = ""
    if channel_id:
        channel_clause = " AND channel_id = ?"
        params.append(channel_id)

    rows = conn.execute(
        f"""
        SELECT id, guild_id, channel_id, user_id, content, attachments_json, occurred_at, created_at
        FROM mousetrap_message_logs
        WHERE guild_id = ?{channel_clause}
        ORDER BY occurred_at DESC, id DESC
        LIMIT ?
        """,
        (*params, safe_limit),
    ).fetchall()
    conn.close()

    blob_rows = sqlite3.connect(db_path)
    blob_rows.row_factory = sqlite3.Row
    blob_rows_data = blob_rows.execute(
        """
        SELECT log_id, attachment_index, filename, content_type, size, blob
        FROM mousetrap_message_attachment_blobs
        WHERE log_id IN (%s)
        ORDER BY log_id ASC, attachment_index ASC
        """
        % ",".join("?" for _ in rows)
        if rows
        else "SELECT log_id, attachment_index, filename, content_type, size, blob FROM mousetrap_message_attachment_blobs WHERE 0",
        [row["id"] for row in rows] if rows else [],
    ).fetchall()
    blob_rows.close()

    attachment_map: dict[int, dict[int, dict]] = {}
    for blob_row in blob_rows_data:
        log_id = int(blob_row["log_id"])
        attachment_index = int(blob_row["attachment_index"])
        content_type = normalize_media_content_type(blob_row["content_type"])
        blob_value = blob_row["blob"]
        data_url = None
        if (
            blob_value is not None
            and is_allowed_media_type(content_type)
            and isinstance(blob_value, (bytes, bytearray, memoryview))
        ):
            if isinstance(blob_value, memoryview):
                blob_value = blob_value.tobytes()
            data_url = (
                f"data:{content_type};base64,"
                f"{base64.b64encode(bytes(blob_value)).decode('ascii')}"
            )

        attachment_map.setdefault(log_id, {})[attachment_index] = {
            "filename": sanitize_filename(blob_row["filename"]),
            "content_type": content_type or None,
            "cached_content_type": content_type or None,
            "cached_size": blob_row["size"],
            "cached_data_url": data_url,
        }

    logs: list[dict] = []
    for row in rows:
        try:
            attachments = json.loads(row["attachments_json"] or "[]")
            if not isinstance(attachments, list):
                attachments = []
        except json.JSONDecodeError:
            attachments = []

        cached_attachments = attachment_map.get(int(row["id"]), {})
        for index, attachment in enumerate(attachments):
            if not isinstance(attachment, dict):
                continue
            attachment.pop("cached_blob", None)
            attachment.pop("cached_data_url", None)
            attachment["filename"] = sanitize_filename(attachment.get("filename"))
            attachment["content_type"] = sanitize_content_type(
                attachment.get("content_type")
            )
            if attachment.get("cached_content_type"):
                attachment["cached_content_type"] = sanitize_content_type(
                    attachment.get("cached_content_type")
                )
            cached_attachment = cached_attachments.get(index)
            if cached_attachment and cached_attachment.get("cached_data_url"):
                attachment.update(cached_attachment)

        logs.append(
            {
                "id": row["id"],
                "guild_id": row["guild_id"],
                "channel_id": row["channel_id"],
                "user_id": row["user_id"],
                "content": row["content"],
                "attachments": attachments,
                "occurred_at": row["occurred_at"],
                "created_at": row["created_at"],
            }
        )

    return logs


def _panel_sessions_need_migration(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA table_info(panel_sessions)").fetchall()
    if not rows:
        return False
    columns = {str(row[1]) for row in rows}
    return "token" in columns and "token_hash" not in columns


def init_account_db(
    db_path: Path,
    backup_dir: Path | str | None = None,
    backup_retention: int = 5,
) -> None:
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
    if _panel_sessions_need_migration(conn):
        # The token-hash migration rebuilds the session table. Take a
        # consistent snapshot first so a failed or interrupted deployment can
        # be restored without logging every user out.
        conn.commit()
        create_database_backup(
            db_path,
            backup_dir=backup_dir,
            retention=backup_retention,
        )
    _migrate_panel_sessions(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS panel_sessions (
            token_hash TEXT PRIMARY KEY,
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
    _ensure_audit_table(conn)
    conn.commit()
    conn.close()


def _migrate_panel_sessions(conn: sqlite3.Connection) -> None:
    """Hash existing plaintext session tokens without invalidating sessions.

    The legacy ``token`` column is replaced by ``token_hash``. The session
    cookie value itself is unchanged, so a SHA-256 lookup of the presented
    token continues to resolve the same session.
    """
    rows = conn.execute("PRAGMA table_info(panel_sessions)").fetchall()
    if not rows:
        return

    existing_columns = {str(row[1]) for row in rows}
    if "token_hash" in existing_columns:
        return
    if "token" not in existing_columns:
        return

    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        legacy_rows = conn.execute(
            """
            SELECT token, username, role, account_id, issued_at, expires_at, revoked, revoked_at
            FROM panel_sessions
            """
        ).fetchall()
        conn.execute(
            """
            CREATE TABLE panel_sessions_migrated (
                token_hash TEXT PRIMARY KEY,
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
        for row in legacy_rows:
            token = str(row[0] or "")
            if not token:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO panel_sessions_migrated (
                    token_hash, username, role, account_id,
                    issued_at, expires_at, revoked, revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sha256_hex(token),
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                ),
            )
        conn.execute("DROP TABLE panel_sessions")
        conn.execute("ALTER TABLE panel_sessions_migrated RENAME TO panel_sessions")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
        INSERT INTO panel_sessions (token_hash, username, role, account_id, issued_at, expires_at, revoked, revoked_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
        """,
        (sha256_hex(token), username, role, account_id, issued_at, expires_at),
    )
    conn.commit()
    conn.close()


def get_panel_session_by_token(db_path: Path, token: str) -> dict | None:
    token_hash = sha256_hex(token)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT token_hash, username, role, account_id, issued_at, expires_at, revoked
        FROM panel_sessions
        WHERE token_hash = ?
        """,
        (token_hash,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "token_hash": str(row["token_hash"]),
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
        WHERE token_hash = ? AND revoked = 0
        """,
        (revoked_at, sha256_hex(token)),
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
            WHERE lower(username) = lower(?) AND revoked = 0 AND token_hash != ?
            """,
            (revoked_at, username, sha256_hex(exclude_token)),
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
) -> int | None:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO panel_accounts (username, password_hash, role, permissions_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, password_hash, role, permissions_json, created_at, updated_at),
        )
        conn.commit()
        account_id = int(cursor.lastrowid)
        conn.close()
        return account_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


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


def insert_audit_event(
    db_path: Path,
    *,
    actor_account_id: int | None,
    actor_username: str,
    actor_role: str,
    action: str,
    category: str,
    target_type: str | None,
    target_id: str | None,
    metadata_json: str,
    created_at: str,
) -> int:
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        """
        INSERT INTO admin_audit_log (
            actor_account_id,
            actor_username,
            actor_role,
            action,
            category,
            target_type,
            target_id,
            metadata_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            actor_account_id,
            actor_username,
            actor_role,
            action,
            category,
            target_type,
            target_id,
            metadata_json,
            created_at,
        ),
    )
    conn.commit()
    event_id = int(cursor.lastrowid)
    conn.close()
    return event_id


def _audit_where_clause(
    *,
    category: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    query: str | None = None,
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    if category:
        clauses.append("category = ?")
        params.append(category)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if actor:
        clauses.append("lower(actor_username) = lower(?)")
        params.append(actor)
    if target_type:
        clauses.append("target_type = ?")
        params.append(target_type)
    if target_id:
        clauses.append("target_id = ?")
        params.append(target_id)
    if from_ts:
        clauses.append("created_at >= ?")
        params.append(from_ts)
    if to_ts:
        clauses.append("created_at <= ?")
        params.append(to_ts)
    if query:
        escaped = (
            query.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        clauses.append(
            "(actor_username LIKE ? ESCAPE '\\' OR action LIKE ? ESCAPE '\\' "
            "OR target_type LIKE ? ESCAPE '\\' OR target_id LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern, pattern])

    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def list_audit_events(
    db_path: Path,
    *,
    limit: int = 50,
    offset: int = 0,
    category: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    query: str | None = None,
) -> tuple[list[dict], int]:
    safe_limit = max(1, min(int(limit), 100))
    safe_offset = max(0, int(offset))
    where_clause, params = _audit_where_clause(
        category=category,
        action=action,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        from_ts=from_ts,
        to_ts=to_ts,
        query=query,
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    total = int(
        conn.execute(
            f"SELECT COUNT(*) FROM admin_audit_log{where_clause}",
            params,
        ).fetchone()[0]
    )
    rows = conn.execute(
        f"""
        SELECT id, actor_account_id, actor_username, actor_role, action, category,
               target_type, target_id, metadata_json, created_at
        FROM admin_audit_log{where_clause}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, safe_limit, safe_offset),
    ).fetchall()
    conn.close()

    events = [
        {
            "id": int(row["id"]),
            "actor_account_id": row["actor_account_id"],
            "actor_username": str(row["actor_username"]),
            "actor_role": str(row["actor_role"]),
            "action": str(row["action"]),
            "category": str(row["category"]),
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "metadata_json": str(row["metadata_json"] or "{}"),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]
    return events, total


def list_audit_actions(db_path: Path) -> list[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT action FROM admin_audit_log ORDER BY action ASC"
    ).fetchall()
    conn.close()
    return [str(row[0]) for row in rows if row and row[0]]


def get_audit_event(db_path: Path, event_id: int) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT id, actor_account_id, actor_username, actor_role, action, category,
               target_type, target_id, metadata_json, created_at
        FROM admin_audit_log
        WHERE id = ?
        """,
        (event_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": int(row["id"]),
        "actor_account_id": row["actor_account_id"],
        "actor_username": str(row["actor_username"]),
        "actor_role": str(row["actor_role"]),
        "action": str(row["action"]),
        "category": str(row["category"]),
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "metadata_json": str(row["metadata_json"] or "{}"),
        "created_at": str(row["created_at"]),
    }
