import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from accounts import AccountService  # noqa: E402
from audit import AuditService  # noqa: E402
from config import Settings  # noqa: E402
from database import init_db  # noqa: E402
from webback import create_app  # noqa: E402


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        environment="testing",
        production=False,
        session_cookie_secure=False,
        session_cookie_samesite="Lax",
        csrf_secret="test-csrf-secret-that-is-long-enough-1234",
        csrf_secret_ephemeral=False,
        allow_loopback_dev_origins=True,
        login_rate_limit_enabled=True,
        login_rate_limit_attempts=5,
        login_rate_limit_window_seconds=300,
        login_rate_limit_block_seconds=60,
        backup_dir=str(tmp_path / "backups"),
    )


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "manubot-test.db"
    init_db(path)
    return path


@pytest.fixture()
def audit_service(db_path):
    return AuditService(db_path)


@pytest.fixture()
def account_service(db_path, settings, audit_service):
    service = AccountService(
        db_path=db_path,
        superadmin_username="root",
        superadmin_password="root-password",
        settings=settings,
        audit_service=audit_service,
    )
    service.init_db()
    return service


@pytest.fixture()
def app(tmp_path, settings, account_service, audit_service):
    bot_state = {
        "connected": True,
        "last_sequence": 42,
        "guilds": [{"id": "123456789012345678", "name": "Test Guild"}],
        "profile": {"username": "Manubot"},
        "bot_user_id": "999999999999999999",
    }

    def noop(*args, **kwargs):
        return None

    return create_app(
        frontend_dist=tmp_path / "dist",
        app_id="123456789",
        bot_state=bot_state,
        account_service=account_service,
        get_guild_channels=lambda server_id: [
            {"id": "223456789012345678", "name": "general", "type": 0}
        ],
        get_mousetrap_config=lambda server_id: None,
        save_mousetrap_config=lambda server_id, channel_id: {
            "guild_id": server_id,
            "channel_id": channel_id,
            "kick_count": 0,
            "enabled": bool(channel_id),
        },
        get_mousetrap_logs=lambda server_id, channel_id=None, limit=100: {
            "logs": [],
            "config": None,
        },
        get_events=lambda limit=20: [],
        get_dm_users=lambda limit_events=300: [],
        get_dm_history=lambda user_id, limit=120: [],
        get_dm_message=lambda message_id: None,
        save_sent_dm_message=noop,
        mark_dm_message_deleted=noop,
        send_dm=lambda user_id, content, files: {
            "channel_id": "323456789012345678",
            "message_id": "423456789012345678",
            "message": {"id": "423456789012345678"},
        },
        delete_dm=noop,
        regenerate_db=lambda: 3,
        audit_service=audit_service,
        settings=settings,
    )


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def login(client):
    def _login(username="root", password="root-password"):
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        body = response.get_json() or {}
        assert response.status_code == 200, body
        return (body.get("session") or {}).get("csrf_token")

    return _login
