import json
import re
import secrets
from datetime import datetime, timedelta
from http import cookies

import bcrypt

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

ALL_PERMISSIONS = (
    PERMISSION_EVENTS_VIEW,
    PERMISSION_SERVERS_VIEW,
    PERMISSION_DIRECT_MESSAGES_READ,
    PERMISSION_DIRECT_MESSAGES_SEND,
    PERMISSION_DIRECT_MESSAGES_DELETE,
    PERMISSION_DATABASE_REGENERATE,
    PERMISSION_ACCOUNTS_VIEW,
    PERMISSION_MODERATOR_MANAGE,
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
}


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def hash_password(password: str) -> str:
    encoded = (password or "").encode("utf-8")
    if not encoded:
        raise ValueError("Password is required")
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

    # Moderator permissions cannot escalate moderator into account manager.
    base[PERMISSION_MODERATOR_MANAGE] = False
    base[PERMISSION_ACCOUNTS_VIEW] = False
    base[PERMISSION_DATABASE_REGENERATE] = False
    return base


def _all_permissions_true() -> dict[str, bool]:
    return {key: True for key in ALL_PERMISSIONS}


class AccountService:
    def __init__(
        self,
        db_path,
        superadmin_username: str,
        superadmin_password: str,
        superadmin_password_hash: str | None = None,
        cookie_name: str = "panel_session",
    ):
        self.db_path = db_path
        self.superadmin_username = (superadmin_username or "").strip()
        self.superadmin_password = superadmin_password or ""
        self.superadmin_password_hash = (superadmin_password_hash or "").strip() or None
        self.cookie_name = cookie_name
        self.session_ttl = timedelta(hours=12)

    def init_db(self) -> None:
        init_account_db(self.db_path)

    def _new_session(
        self,
        username: str,
        role: str,
        account_id: int | None,
        permissions: dict[str, bool],
    ) -> dict:
        token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + self.session_ttl
        session = {
            "token": token,
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

        if datetime.utcnow() >= expires_at:
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
            "token": str(row["token"]),
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
            secure=False,
            samesite="Lax",
            path="/",
        )

    def clear_session_cookie(self, flask_response):
        flask_response.delete_cookie(self.cookie_name, path="/")

    def session_public(self, session: dict) -> dict:
        return {
            "username": session["username"],
            "role": session["role"],
            "permissions": dict(session.get("permissions") or {}),
            "expires_at": session.get("expires_at"),
        }

    def has_permission(self, session: dict | None, permission: str) -> bool:
        if not session:
            return False
        role = session.get("role")
        if role in (ROLE_SUPERADMIN, ROLE_ADMIN):
            return True
        permissions = session.get("permissions") or {}
        return bool(permissions.get(permission))

    def login(self, username: str, password: str) -> tuple[dict | None, str | None]:
        clean_username = (username or "").strip()
        if not clean_username or not password:
            return None, "Username and password are required"

        # Superadmin credentials are sourced from .env.
        if self.superadmin_username and clean_username.lower() == self.superadmin_username.lower():
            valid_superadmin = False
            if self.superadmin_password_hash:
                valid_superadmin = verify_password(password, self.superadmin_password_hash)
            elif self.superadmin_password:
                valid_superadmin = secrets.compare_digest(password, self.superadmin_password)

            if valid_superadmin:
                session = self._new_session(
                    username=self.superadmin_username,
                    role=ROLE_SUPERADMIN,
                    account_id=None,
                    permissions=_all_permissions_true(),
                )
                return session, None

        row = get_panel_account_by_username(self.db_path, clean_username)
        if not row:
            return None, "Invalid credentials"

        password_hash = str(row.get("password_hash") or "")
        if not verify_password(password, password_hash):
            return None, "Invalid credentials"

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
        return session, None

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

        clean_role = (role or "").strip().lower()
        if clean_role not in (ROLE_ADMIN, ROLE_MODERATOR):
            return None, "Role must be either admin or moderator"

        if len(password or "") < 8:
            return None, "Password must be at least 8 characters"

        password_hash = hash_password(password)
        permissions = _all_permissions_true() if clean_role == ROLE_ADMIN else _normalize_permissions({})

        inserted = insert_panel_account(
            db_path=self.db_path,
            username=clean_username,
            password_hash=password_hash,
            role=clean_role,
            permissions_json=json.dumps(permissions),
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        if not inserted:
            return None, "Username already exists"

        return {"username": clean_username, "role": clean_role}, None

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

        normalized = _normalize_permissions(permissions)
        update_panel_account_permissions(
            db_path=self.db_path,
            account_id=account_id,
            permissions_json=json.dumps(normalized),
            updated_at=_utc_now(),
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

        if len(new_password or "") < 8:
            return None, "New password must be at least 8 characters"

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
        return {"username": username}, None

    def superadmin_set_account_password(self, actor_session: dict, account_id: int, new_password: str):
        if actor_session.get("role") != ROLE_SUPERADMIN:
            return None, "Only superadmin can change admin and moderator passwords"

        if len(new_password or "") < 8:
            return None, "New password must be at least 8 characters"

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
        return {
            "id": int(row["id"]),
            "username": str(row["username"]),
            "role": target_role,
            "revoked_sessions": revoked_count,
        }, None
