import sqlite3
from datetime import datetime, timedelta, timezone

from database import (
    create_database_backup,
    get_audit_event,
    get_panel_account_by_username,
    get_panel_session_by_token,
    init_account_db,
    init_db,
    insert_audit_event,
    insert_event,
    insert_mousetrap_message_log,
    insert_panel_account,
    list_mousetrap_message_logs,
    prune_old_records,
    regenerate_db,
)
from security import sha256_hex, utc_now_iso


def test_legacy_session_tokens_are_hashed_without_logouts(tmp_path):
    legacy_db = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy_db)
    conn.executescript(
        """
        CREATE TABLE panel_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            permissions_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE panel_sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            account_id INTEGER,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0,
            revoked_at TEXT
        );
        """
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    conn.execute(
        "INSERT INTO panel_accounts (username, password_hash, role, permissions_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("legacy", "hash", "moderator", "{}", now.isoformat(), now.isoformat()),
    )
    conn.execute(
        "INSERT INTO panel_sessions (token, username, role, account_id, issued_at, expires_at, revoked, revoked_at) VALUES (?, ?, ?, ?, ?, ?, 0, NULL)",
        ("raw-legacy-token", "legacy", "moderator", 1, now.isoformat(), (now + timedelta(hours=1)).isoformat()),
    )
    conn.commit()
    conn.close()

    init_account_db(legacy_db)

    backups = list((tmp_path / "backups").glob("*.db"))
    assert len(backups) == 1

    raw = "raw-legacy-token"
    row = get_panel_session_by_token(legacy_db, raw)
    assert row is not None
    assert row["token_hash"] == sha256_hex(raw)
    assert row["username"] == "legacy"

    conn = sqlite3.connect(legacy_db)
    columns = [item[1] for item in conn.execute("PRAGMA table_info(panel_sessions)")]
    stored = conn.execute("SELECT token_hash FROM panel_sessions").fetchall()
    conn.close()
    assert "token" not in columns
    assert stored == [(sha256_hex(raw),)]


def test_regenerate_creates_backup_and_preserves_accounts_and_audit(tmp_path):
    db_path = tmp_path / "manubot.db"
    backup_dir = tmp_path / "backups"
    init_db(db_path)
    init_account_db(db_path)
    insert_event(db_path, "MESSAGE_CREATE", 1, {"d": {"content": "hello"}})
    insert_panel_account(
        db_path=db_path,
        username="moderator",
        password_hash="hash",
        role="moderator",
        permissions_json="{}",
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )
    insert_audit_event(
        db_path,
        actor_account_id=None,
        actor_username="root",
        actor_role="superadmin",
        action="test.action",
        category="auth",
        target_type=None,
        target_id=None,
        metadata_json="{}",
        created_at=utc_now_iso(),
    )

    deleted = regenerate_db(db_path, backup_dir=backup_dir, backup_retention=2)

    assert deleted == 1
    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    assert get_panel_account_by_username(db_path, "moderator") is not None
    assert get_audit_event(db_path, 1) is not None

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM gateway_events").fetchone()[0] == 0
    conn.close()

    backup_conn = sqlite3.connect(backups[0])
    assert backup_conn.execute("SELECT COUNT(*) FROM gateway_events").fetchone()[0] == 1
    backup_conn.close()


def test_backup_retention_and_permissions(tmp_path):
    db_path = tmp_path / "manubot.db"
    backup_dir = tmp_path / "backups"
    init_db(db_path)

    for _ in range(4):
        create_database_backup(db_path, backup_dir=backup_dir, retention=2)

    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 2


def test_mousetrap_blobs_only_store_allowed_media(tmp_path):
    db_path = tmp_path / "manubot.db"
    init_db(db_path)
    insert_mousetrap_message_log(
        db_path=db_path,
        guild_id="123456789012345678",
        channel_id="223456789012345678",
        user_id="323456789012345678",
        content="hello",
        attachments=[
            {
                "filename": "../../evil.svg",
                "content_type": "image/svg+xml",
                "cached_content_type": "image/svg+xml",
                "cached_blob": b"<svg onload=alert(1)></svg>",
            },
            {
                "filename": "photo.png",
                "content_type": "image/png",
                "cached_content_type": "image/png",
                "cached_blob": b"\x89PNG\r\n\x1a\nfake",
                "cached_size": 12,
            },
        ],
        occurred_at=utc_now_iso(),
    )

    logs = list_mousetrap_message_logs(
        db_path, guild_id="123456789012345678", limit=10
    )
    assert len(logs) == 1
    attachments = logs[0]["attachments"]

    assert attachments[0]["filename"] == "evil.svg"
    assert attachments[0].get("cached_data_url") is None
    assert attachments[1]["filename"] == "photo.png"
    assert attachments[1]["cached_data_url"].startswith("data:image/png;base64,")

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT content_type FROM mousetrap_message_attachment_blobs"
    ).fetchall()
    conn.close()
    assert rows == [("image/png",)]


def test_prune_old_records(tmp_path):
    db_path = tmp_path / "manubot.db"
    init_db(db_path)
    old = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=40)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO gateway_events (event_type, sequence, payload, created_at) VALUES (?, ?, ?, ?)",
        ("OLD_EVENT", 1, "{}", old),
    )
    conn.commit()
    conn.close()

    removed = prune_old_records(db_path, event_retention_days=30)

    assert removed["gateway_events"] == 1
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM gateway_events").fetchone()[0] == 0
    conn.close()


def test_prune_disabled_by_default(tmp_path):
    db_path = tmp_path / "manubot.db"
    init_db(db_path)
    insert_event(db_path, "EVENT", 1, {"d": {}})

    removed = prune_old_records(db_path)

    assert removed == {
        "gateway_events": 0,
        "mousetrap_message_logs": 0,
        "admin_audit_log": 0,
    }
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM gateway_events").fetchone()[0] == 1
    conn.close()
