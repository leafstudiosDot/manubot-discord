import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from http import cookies

import bcrypt

from audit import (
    ACTION_ACCOUNT_CREATE,
    ACTION_ACCOUNT_PASSWORD_CHANGE,
    ACTION_ACCOUNT_PASSWORD_RESET,
    ACTION_ACCOUNT_PERMISSIONS_UPDATE,
    ACTION_LOGIN_FAILED,
    ACTION_LOGIN_SUCCESS,
    CATEGORY_ACCOUNTS,
    CATEGORY_AUTH,
    AuditService,
)
from config import Settings
from database import (
    get_panel_account_by_id,
    get_panel_account_by_username,
    get_panel_session_by_token,
    init_account_db,
    insert_panel_account,
    insert_panel_session,
    list_panel_accounts,
    revoke_all_panel_sessions_by_roles,
    revoke_panel_session_by_token,
    revoke_panel_sessions_by_identity,
    revoke_panel_sessions_by_username,
    update_panel_account_password,
    update_panel_account_permissions,
)
from security import (
    LoginRateLimiter,
    derive_csrf_token,
    utc_now_iso,
    validate_password_length,
)

ROLE_SUPERADMIN = "superadmin"
ROLE_ADMIN = "admin"
ROLE_MODERATOR = "moderator"

PERMISSION_EVENTS_VIEW = "events_view"
PERMISSION_SERVERS_VIEW = "servers_view"
PERMISSION_DIRECT_MESSAGES_READ = "direct_messages_read"
PERMISSION_DIRECT_MESSAGES_SEND = "direct_messages_send"
PERMISSION_DIRECT_MESSAGES_DELETE = "direct_messages_delete"
PERMISSION_DATABASE_REGENERATE = "database_regenerate"
PERMISSION_ACCOUNTS_VIEW = "accounts_view"
PERMISSION_MODERATOR_MANAGE = "moderator_manage"
PERMISSION_AUDIT_VIEW = "audit_view"

ALL_PERMISSIONS = (
    PERMISSION_EVENTS_VIEW,
    PERMISSION_SERVERS_VIEW,
    PERMISSION_DIRECT_MESSAGES_READ,
    PERMISSION_DIRECT_MESSAGES_SEND,
    PERMISSION_DIRECT_MESSAGES_DELETE,
    PERMISSION_DATABASE_REGENERATE,
    PERMISSION_ACCOUNTS_VIEW,
    PERMISSION_MODERATOR_MANAGE,
    PERMISSION_AUDIT_VIEW,
)

DEFAULT_MODERATOR_PERMISSIONS = {
    PERMISSION_EVENTS_VIEW: False,
    PERMISSION_SERVERS_VIEW: True,
    PERMISSION_DIRECT_MESSAGES_READ: True,
    PERMISSION_DIRECT_MESSAGES_SEND: False,
    PERMISSION_DIRECT_MESSAGES_DELETE: False,
    PERMISSION_DATABASE_REGENERATE: False,
    PERMISSION_ACCOUNTS_VIEW: False,
    PERMISSION_MODERATOR_MANAGE: False,
    PERMISSION_AUDIT_VIEW: False,
}

LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return utc_now_iso()


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return bcrypt.hashpw(b"manubot-dummy-password", bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )


def hash_password(password: str) -> str:
    encoded = (password or "").encode("utf-8")
    if not encoded:
        raise ValueError("Password is required")
    if len(encoded) > 72:
        raise ValueError("Password must be at most 72 bytes (UTF-8)")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False

    try:
        return bool(
            bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        )
    except Exception:
        return False


def _normalize_permissions(raw: dict | None) -> dict[str, bool]:
    base = dict(DEFAULT_MODERATOR_PERMISSIONS)
    if not isinstance(raw, dict):
        return base

    for key in ALL_PERMISSIONS:
        if key in raw:
            base[key] = bool(raw[key])

    # Moderator permissions cannot escalate a moderator into account manager.
    base[PERMISSION_MODERATOR_MANAGE] = False
    base[PERMISSION_ACCOUNTS_VIEW] = False
    base[PERMISSION_DATABASE_REGENERATE] = False
    return base


def _all_permissions_true() -> dict[str, bool]:
    return {key: True for key in ALL_PERMISSIONS}


@dataclass(frozen=True)
class LoginResult:
    session: dict | None = None
    error: str | None = None
    status_code: int = 200
    retry_after: int | None = None


class AccountService:
    def __init__(
        self,
        db_path,
        superadmin_username: str,
        superadmin_password: str,
        superadmin_password_hash: str | None = None,
        cookie_name: str | None = None,
        settings: Settings | None = None,
        audit_service: AuditService | None = None,
        rate_limiter: LoginRateLimiter | None = None,
    ):
        self.db_path = db_path
        self.settings = settings or Settings.from_env()
        self.superadmin_username = (superadmin_username or "").strip()
        self.superadmin_password = superadmin_password or ""
        self.superadmin_password_hash = (superadmin_password_hash or "").strip() or None
        self.cookie_name = cookie_name or self.settings.session_cookie_name
        self.session_ttl = timedelta(hours=self.settings.session_ttl_hours)
        self.csrf_secret = self.settings.csrf_secret
        self.audit = audit_service or AuditService(db_path)
        self.rate_limiter = rate_limiter or LoginRateLimiter(
            enabled=self.settings.login_rate_limit_enabled,
            max_attempts=self.settings.login_rate_limit_attempts,
            window_seconds=self.settings.login_rate_limit_window_seconds,
            block_seconds=self.settings.login_rate_limit_block_seconds,
        )

    def init_db(self) -> None:
        init_account_db(
            self.db_path,
            backup_dir=self.settings.backup_dir,
            backup_retention=self.settings.backup_retention,
        )

    def _audit(self, *, action, category, actor_session=None, **kwargs) -> None:
        try:
            self.audit.record(
                action=action,
                category=category,
                actor_session=actor_session,
                **kwargs,
            )
        except Exception:
            LOGGER.exception("Audit logging failed")

    def _new_session(
        self,
        username: str,
        role: str,
        account_id: int | None,
        permissions: dict[str, bool],
    ) -> dict:
        token = secrets.token_urlsafe(48)
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + self.session_ttl
        session = {
            "token": token,
            "csrf_token": derive_csrf_token(self.csrf_secret, token),
            "username": username,
            "role": role,
            "account_id": account_id,
            "permissions": permissions,
            "issued_at": _utc_now(),
            "expires_at": expires_at.isoformat(),
        }

        insert_panel_session(
            db_path=self.db_path,
            token=token,
            username=username,
            role=role,
            account_id=account_id,
            issued_at=session["issued_at"],
            expires_at=session["expires_at"],
        )
        return session

    def _parse_cookie(self, raw_cookie_header: str) -> str | None:
        if not raw_cookie_header:
            return None

        jar = cookies.SimpleCookie()
        try:
            jar.load(raw_cookie_header)
        except Exception:
            return None

        morsel = jar.get(self.cookie_name)
        if not morsel:
            return None
        return str(morsel.value or "") or None

    def _resolve_session_from_token(self, token: str | None) -> dict | None:
        if not token:
            return None

        row = get_panel_session_by_token(self.db_path, token)
        if not row:
            return None

        if int(row.get("revoked") or 0) == 1:
            return None

        expires_at_text = str(row["expires_at"])
        try:
            expires_at = datetime.fromisoformat(expires_at_text)
        except Exception:
            revoke_panel_session_by_token(self.db_path, token, _utc_now())
            return None

        if datetime.now(timezone.utc).replace(tzinfo=None) >= expires_at:
            revoke_panel_session_by_token(self.db_path, token, _utc_now())
            return None

        role = str(row["role"])
        username = str(row["username"])
        account_id = row.get("account_id")

        if role == ROLE_SUPERADMIN:
            permissions = _all_permissions_true()
        else:
            account_row = get_panel_account_by_username(self.db_path, username)
            if not account_row:
                revoke_panel_session_by_token(self.db_path, token, _utc_now())
                return None

            role = str(account_row["role"])
            account_id = int(account_row["id"])
            raw_permissions = {}
            try:
                raw_permissions = json.loads(account_row.get("permissions_json") or "{}")
            except Exception:
                raw_permissions = {}

            permissions = (
                _all_permissions_true()
                if role == ROLE_ADMIN
                else _normalize_permissions(raw_permissions)
            )

        return {
            "token": token,
            "csrf_token": derive_csrf_token(self.csrf_secret, token),
            "username": username,
            "role": role,
            "account_id": account_id,
            "permissions": permissions,
            "issued_at": str(row["issued_at"]),
            "expires_at": expires_at_text,
        }

    def authenticate_request(self, flask_request):
        token = flask_request.cookies.get(self.cookie_name)
        return self._resolve_session_from_token(token)

    def authenticate_ws_environ(self, environ: dict):
        cookie_header = str(environ.get("HTTP_COOKIE") or "")
        token = self._parse_cookie(cookie_header)
        return self._resolve_session_from_token(token)

    def add_session_cookie(self, flask_response, session: dict):
        max_age = int(self.session_ttl.total_seconds())
        flask_response.set_cookie(
            self.cookie_name,
            session["token"],
            max_age=max_age,
            httponly=True,
            secure=self.settings.session_cookie_secure,
            samesite=self.settings.session_cookie_samesite,
            path="/",
        )

    def clear_session_cookie(self, flask_response):
        flask_response.delete_cookie(
            self.cookie_name,
            path="/",
            secure=self.settings.session_cookie_secure,
            httponly=True,
            samesite=self.settings.session_cookie_samesite,
        )

    def session_public(self, session: dict) -> dict:
        return {
            "username": session["username"],
            "role": session["role"],
            "permissions": dict(session.get("permissions") or {}),
            "expires_at": session.get("expires_at"),
            "csrf_token": session.get("csrf_token"),
        }

    def has_permission(self, session: dict | None, permission: str) -> bool:
        if not session:
            return False
        role = session.get("role")
        if role in (ROLE_SUPERADMIN, ROLE_ADMIN):
            return True
        permissions = session.get("permissions") or {}
        return bool(permissions.get(permission))

    def validate_csrf(self, session: dict | None, provided_token: str | None) -> bool:
        if not session:
            return False
        expected = str(session.get("csrf_token") or "")
        provided = str(provided_token or "").strip()
        if not expected or not provided:
            return False
        return secrets.compare_digest(expected, provided)

    def login(
        self,
        username: str,
        password: str,
        client_ip: str | None = None,
    ) -> LoginResult:
        clean_username = (username or "").strip()
        if not clean_username or not password:
            return LoginResult(
                error="Username and password are required",
                status_code=400,
            )
        if len(clean_username) > 100 or len(password) > 1024:
            return LoginResult(error="Invalid credentials", status_code=401)

        rate_keys = [f"user:{clean_username.lower()}"]
        if client_ip:
            rate_keys.append(f"ip:{client_ip}")

        retry_after = self.rate_limiter.retry_after(rate_keys)
        if retry_after > 0:
            self._audit(
                action=ACTION_LOGIN_FAILED,
                category=CATEGORY_AUTH,
                actor_username=clean_username,
                actor_role="unknown",
                metadata={"reason": "rate_limited", "client_ip": client_ip},
            )
            return LoginResult(
                error="Too many login attempts. Try again later.",
                status_code=429,
                retry_after=retry_after,
            )

        # Superadmin credentials come from the environment. Never fall through
        # to a same-named database account when the superadmin password is wrong.
        if (
            self.superadmin_username
            and clean_username.lower() == self.superadmin_username.lower()
        ):
            valid_superadmin = False
            if self.superadmin_password_hash:
                valid_superadmin = verify_password(
                    password, self.superadmin_password_hash
                )
            elif self.superadmin_password:
                valid_superadmin = secrets.compare_digest(
                    password, self.superadmin_password
                )

            if valid_superadmin:
                session = self._new_session(
                    username=self.superadmin_username,
                    role=ROLE_SUPERADMIN,
                    account_id=None,
                    permissions=_all_permissions_true(),
                )
                self.rate_limiter.reset(rate_keys)
                self._audit(
                    action=ACTION_LOGIN_SUCCESS,
                    category=CATEGORY_AUTH,
                    actor_session=session,
                    metadata={"client_ip": client_ip},
                )
                return LoginResult(session=session)

            self.rate_limiter.record_failure(rate_keys)
            self._audit(
                action=ACTION_LOGIN_FAILED,
                category=CATEGORY_AUTH,
                actor_username=clean_username,
                actor_role="unknown",
                metadata={"reason": "invalid_credentials", "client_ip": client_ip},
            )
            return LoginResult(error="Invalid credentials", status_code=401)

        row = get_panel_account_by_username(self.db_path, clean_username)
        if not row:
            # Keep timing roughly comparable for unknown usernames.
            verify_password(password, _dummy_password_hash())
            self.rate_limiter.record_failure(rate_keys)
            self._audit(
                action=ACTION_LOGIN_FAILED,
                category=CATEGORY_AUTH,
                actor_username=clean_username,
                actor_role="unknown",
                metadata={"reason": "invalid_credentials", "client_ip": client_ip},
            )
            return LoginResult(error="Invalid credentials", status_code=401)

        password_hash = str(row.get("password_hash") or "")
        if not verify_password(password, password_hash):
            self.rate_limiter.record_failure(rate_keys)
            self._audit(
                action=ACTION_LOGIN_FAILED,
                category=CATEGORY_AUTH,
                actor_username=clean_username,
                actor_role=str(row.get("role") or "unknown"),
                metadata={"reason": "invalid_credentials", "client_ip": client_ip},
            )
            return LoginResult(error="Invalid credentials", status_code=401)

        role = str(row["role"])
        raw_permissions = {}
        try:
            raw_permissions = json.loads(row.get("permissions_json") or "{}")
        except Exception:
            raw_permissions = {}

        permissions = (
            _all_permissions_true()
            if role == ROLE_ADMIN
            else _normalize_permissions(raw_permissions)
        )

        session = self._new_session(
            username=str(row["username"]),
            role=role,
            account_id=int(row["id"]),
            permissions=permissions,
        )
        self.rate_limiter.reset(rate_keys)
        self._audit(
            action=ACTION_LOGIN_SUCCESS,
            category=CATEGORY_AUTH,
            actor_session=session,
            metadata={"client_ip": client_ip},
        )
        return LoginResult(session=session)

    def revoke_session_token(self, token: str | None) -> bool:
        clean_token = (token or "").strip()
        if not clean_token:
            return False

        return bool(revoke_panel_session_by_token(self.db_path, clean_token, _utc_now()))

    def logout(self, flask_request) -> None:
        token = flask_request.cookies.get(self.cookie_name)
        self.revoke_session_token(token)

    def revoke_user_sessions(self, username: str, exclude_token: str | None = None) -> int:
        clean_username = (username or "").strip()
        if not clean_username:
            return 0

        return revoke_panel_sessions_by_username(
            db_path=self.db_path,
            username=clean_username,
            revoked_at=_utc_now(),
            exclude_token=exclude_token,
        )

    def revoke_sessions_for_identity(self, username: str, role: str) -> int:
        clean_username = (username or "").strip()
        clean_role = (role or "").strip().lower()
        if not clean_username or clean_role not in (ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_MODERATOR):
            return 0

        return revoke_panel_sessions_by_identity(
            db_path=self.db_path,
            username=clean_username,
            role=clean_role,
            revoked_at=_utc_now(),
        )

    def revoke_all_sessions(self) -> int:
        return revoke_all_panel_sessions_by_roles(
            db_path=self.db_path,
            roles=[ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_MODERATOR],
            revoked_at=_utc_now(),
        )

    def list_accounts(self) -> list[dict]:
        rows = list_panel_accounts(self.db_path)

        result = []
        for row in rows:
            role = str(row["role"])
            raw_permissions = {}
            try:
                raw_permissions = json.loads(row.get("permissions_json") or "{}")
            except Exception:
                raw_permissions = {}

            permissions = (
                _all_permissions_true()
                if role == ROLE_ADMIN
                else _normalize_permissions(raw_permissions)
            )

            result.append(
                {
                    "id": int(row["id"]),
                    "username": str(row["username"]),
                    "role": role,
                    "permissions": permissions,
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                }
            )

        return result

    def create_account(self, actor_session: dict, username: str, password: str, role: str):
        if actor_session.get("role") != ROLE_SUPERADMIN:
            return None, "Only superadmin can create admin or moderator accounts"

        clean_username = (username or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,32}", clean_username):
            return None, "Username must be 3-32 chars and use a-z, A-Z, 0-9, ., _, -"

        if (
            self.superadmin_username
            and clean_username.lower() == self.superadmin_username.lower()
        ):
            return None, "That username is reserved"

        clean_role = (role or "").strip().lower()
        if clean_role not in (ROLE_ADMIN, ROLE_MODERATOR):
            return None, "Role must be either admin or moderator"

        password_error = validate_password_length(password)
        if password_error:
            return None, password_error

        password_hash = hash_password(password)
        permissions = _all_permissions_true() if clean_role == ROLE_ADMIN else _normalize_permissions({})

        inserted_id = insert_panel_account(
            db_path=self.db_path,
            username=clean_username,
            password_hash=password_hash,
            role=clean_role,
            permissions_json=json.dumps(permissions),
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        if inserted_id is None:
            return None, "Username already exists"

        self._audit(
            action=ACTION_ACCOUNT_CREATE,
            category=CATEGORY_ACCOUNTS,
            actor_session=actor_session,
            target_type="account",
            target_id=str(inserted_id),
            metadata={"username": clean_username, "role": clean_role},
        )

        return {"id": inserted_id, "username": clean_username, "role": clean_role}, None

    def update_moderator_permissions(
        self,
        actor_session: dict,
        account_id: int,
        permissions: dict,
    ):
        if actor_session.get("role") not in (ROLE_SUPERADMIN, ROLE_ADMIN):
            return None, "Only superadmin and admin can manage moderator permissions"

        row = get_panel_account_by_id(self.db_path, account_id)
        if not row:
            return None, "Account not found"

        if str(row["role"]) != ROLE_MODERATOR:
            return None, "Only moderator permissions can be updated"

        try:
            previous_raw = json.loads(row.get("permissions_json") or "{}")
        except Exception:
            previous_raw = {}
        previous = _normalize_permissions(previous_raw)
        normalized = _normalize_permissions(permissions)
        update_panel_account_permissions(
            db_path=self.db_path,
            account_id=account_id,
            permissions_json=json.dumps(normalized),
            updated_at=_utc_now(),
        )

        changed = {
            key: normalized[key]
            for key in ALL_PERMISSIONS
            if previous.get(key) != normalized.get(key)
        }
        self._audit(
            action=ACTION_ACCOUNT_PERMISSIONS_UPDATE,
            category=CATEGORY_ACCOUNTS,
            actor_session=actor_session,
            target_type="account",
            target_id=str(account_id),
            metadata={
                "username": str(row["username"]),
                "changed_permissions": changed,
            },
        )

        return {
            "id": int(row["id"]),
            "username": str(row["username"]),
            "role": ROLE_MODERATOR,
            "permissions": normalized,
        }, None

    def change_own_password(
        self,
        actor_session: dict,
        current_password: str,
        new_password: str,
    ):
        role = str(actor_session.get("role") or "")
        if role not in (ROLE_ADMIN, ROLE_MODERATOR):
            return None, "Only admin and moderator can change own password"

        password_error = validate_password_length(new_password)
        if password_error:
            return None, password_error

        username = str(actor_session.get("username") or "").strip()
        if not username:
            return None, "Invalid account"

        row = get_panel_account_by_username(self.db_path, username)
        if not row:
            return None, "Account not found"

        if not verify_password(current_password or "", str(row.get("password_hash") or "")):
            return None, "Current password is incorrect"

        update_panel_account_password(
            db_path=self.db_path,
            account_id=int(row["id"]),
            password_hash=hash_password(new_password),
            updated_at=_utc_now(),
        )

        revoked_count = self.revoke_user_sessions(
            username=username,
            exclude_token=str(actor_session.get("token") or "") or None,
        )
        self._audit(
            action=ACTION_ACCOUNT_PASSWORD_CHANGE,
            category=CATEGORY_ACCOUNTS,
            actor_session=actor_session,
            target_type="account",
            target_id=str(row["id"]),
            metadata={"revoked_sessions": revoked_count},
        )
        return {"username": username, "revoked_sessions": revoked_count}, None

    def superadmin_set_account_password(self, actor_session: dict, account_id: int, new_password: str):
        if actor_session.get("role") != ROLE_SUPERADMIN:
            return None, "Only superadmin can change admin and moderator passwords"

        password_error = validate_password_length(new_password)
        if password_error:
            return None, password_error

        row = get_panel_account_by_id(self.db_path, account_id)
        if not row:
            return None, "Account not found"

        target_role = str(row["role"])
        if target_role not in (ROLE_ADMIN, ROLE_MODERATOR):
            return None, "Only admin and moderator passwords can be changed"

        update_panel_account_password(
            db_path=self.db_path,
            account_id=int(row["id"]),
            password_hash=hash_password(new_password),
            updated_at=_utc_now(),
        )

        revoked_count = self.revoke_user_sessions(username=str(row["username"]))
        self._audit(
            action=ACTION_ACCOUNT_PASSWORD_RESET,
            category=CATEGORY_ACCOUNTS,
            actor_session=actor_session,
            target_type="account",
            target_id=str(row["id"]),
            metadata={
                "username": str(row["username"]),
                "revoked_sessions": revoked_count,
            },
        )
        return {
            "id": int(row["id"]),
            "username": str(row["username"]),
            "role": target_role,
            "revoked_sessions": revoked_count,
        }, None
