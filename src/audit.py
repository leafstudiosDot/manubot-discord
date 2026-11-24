"""Administrator activity audit log service.

Records are append-only through the application API. Callers must pass only
non-sensitive structured metadata; the sanitizer below is a second line of
defence, not a substitute for careful call sites.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from database import (
    get_audit_event,
    insert_audit_event,
    list_audit_actions,
    list_audit_events,
)
from security import utc_now_iso

LOGGER = logging.getLogger(__name__)

CATEGORY_AUTH = "auth"
CATEGORY_ACCOUNTS = "accounts"
CATEGORY_SESSIONS = "sessions"
CATEGORY_DIRECT_MESSAGES = "direct_messages"
CATEGORY_MOUSETRAP = "mousetrap"
CATEGORY_DATABASE = "database"

CATEGORIES = (
    CATEGORY_AUTH,
    CATEGORY_ACCOUNTS,
    CATEGORY_SESSIONS,
    CATEGORY_DIRECT_MESSAGES,
    CATEGORY_MOUSETRAP,
    CATEGORY_DATABASE,
)

ACTION_LOGIN_SUCCESS = "auth.login.success"
ACTION_LOGIN_FAILED = "auth.login.failed"
ACTION_LOGOUT = "auth.logout"
ACTION_ACCOUNT_CREATE = "account.create"
ACTION_ACCOUNT_PERMISSIONS_UPDATE = "account.permissions.update"
ACTION_ACCOUNT_PASSWORD_CHANGE = "account.password.change"
ACTION_ACCOUNT_PASSWORD_RESET = "account.password.reset"
ACTION_SESSIONS_REVOKE = "sessions.revoke"
ACTION_SESSIONS_REVOKE_GLOBAL = "sessions.revoke_global"
ACTION_DM_SEND = "direct_message.send"
ACTION_DM_DELETE = "direct_message.delete"
ACTION_MOUSETRAP_CONFIG_UPDATE = "mousetrap.config.update"
ACTION_DATABASE_REGENERATE = "database.regenerate"

ACTION_LABELS = {
    ACTION_LOGIN_SUCCESS: "Signed in",
    ACTION_LOGIN_FAILED: "Failed sign-in",
    ACTION_LOGOUT: "Signed out",
    ACTION_ACCOUNT_CREATE: "Created account",
    ACTION_ACCOUNT_PERMISSIONS_UPDATE: "Updated moderator permissions",
    ACTION_ACCOUNT_PASSWORD_CHANGE: "Changed own password",
    ACTION_ACCOUNT_PASSWORD_RESET: "Reset account password",
    ACTION_SESSIONS_REVOKE: "Revoked own sessions",
    ACTION_SESSIONS_REVOKE_GLOBAL: "Revoked all sessions",
    ACTION_DM_SEND: "Sent direct message",
    ACTION_DM_DELETE: "Deleted direct message",
    ACTION_MOUSETRAP_CONFIG_UPDATE: "Updated MouseTrap configuration",
    ACTION_DATABASE_REGENERATE: "Regenerated database",
}

CATEGORY_LABELS = {
    CATEGORY_AUTH: "Authentication",
    CATEGORY_ACCOUNTS: "Accounts",
    CATEGORY_SESSIONS: "Sessions",
    CATEGORY_DIRECT_MESSAGES: "Direct messages",
    CATEGORY_MOUSETRAP: "MouseTrap",
    CATEGORY_DATABASE: "Database",
}

_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "blob",
    "file_bytes",
    "raw_content",
    "message_content",
    "content_body",
    "upload_data",
)

_DROP = object()


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _sanitize_value(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return str(value)[:256]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        cleaned = "".join(char for char in value if ord(char) >= 32 and ord(char) != 127)
        return cleaned[:256]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 30:
                break
            clean_key = str(key)[:64]
            if not clean_key or _is_sensitive_key(clean_key):
                continue
            cleaned = _sanitize_value(item, depth + 1)
            if cleaned is not _DROP:
                result[clean_key] = cleaned
        return result
    if isinstance(value, (list, tuple)):
        cleaned_items = []
        for item in value[:20]:
            cleaned = _sanitize_value(item, depth + 1)
            if cleaned is not _DROP:
                cleaned_items.append(cleaned)
        return cleaned_items
    return str(value)[:256]


def sanitize_metadata(metadata: Any) -> dict:
    if not isinstance(metadata, dict):
        return {}
    cleaned = _sanitize_value(metadata)
    return cleaned if isinstance(cleaned, dict) else {}


def _parse_metadata(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return sanitize_metadata(parsed)


class AuditService:
    def __init__(self, db_path):
        self.db_path = db_path

    def record(
        self,
        *,
        action: str,
        category: str,
        actor_session: dict | None = None,
        actor_account_id: int | None = None,
        actor_username: str | None = None,
        actor_role: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata: dict | None = None,
    ) -> int | None:
        session = actor_session or {}
        resolved_account_id = actor_account_id
        if resolved_account_id is None and session.get("account_id") is not None:
            try:
                resolved_account_id = int(session["account_id"])
            except (TypeError, ValueError):
                resolved_account_id = None

        username = str(actor_username or session.get("username") or "unknown")[:100]
        role = str(actor_role or session.get("role") or "unknown")[:32]
        clean_action = str(action or "unknown")[:100]
        clean_category = str(category or "unknown")[:32]

        try:
            return insert_audit_event(
                self.db_path,
                actor_account_id=resolved_account_id,
                actor_username=username,
                actor_role=role,
                action=clean_action,
                category=clean_category,
                target_type=str(target_type)[:64] if target_type else None,
                target_id=str(target_id)[:128] if target_id else None,
                metadata_json=json.dumps(sanitize_metadata(metadata or {})),
                created_at=utc_now_iso(),
            )
        except Exception:
            # Auditing must never take down an administrative operation, but a
            # failure is still reported server-side without sensitive data.
            LOGGER.exception("Failed to write audit event %s", clean_action)
            return None

    def list_events(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        category: str | None = None,
        action: str | None = None,
        actor: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        query: str | None = None,
    ) -> dict:
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        events, total = list_audit_events(
            self.db_path,
            limit=safe_page_size,
            offset=(safe_page - 1) * safe_page_size,
            category=category,
            action=action,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            from_ts=from_ts,
            to_ts=to_ts,
            query=query,
        )
        for event in events:
            event["metadata"] = _parse_metadata(event.pop("metadata_json", "{}"))
        pages = max(1, (total + safe_page_size - 1) // safe_page_size)
        return {
            "events": events,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "pages": pages,
        }

    def get_event(self, event_id: int) -> dict | None:
        event = get_audit_event(self.db_path, event_id)
        if not event:
            return None
        event["metadata"] = _parse_metadata(event.pop("metadata_json", "{}"))
        return event

    def meta(self) -> dict:
        actions = set(ACTION_LABELS)
        actions.update(list_audit_actions(self.db_path))
        return {
            "categories": [
                {"value": category, "label": CATEGORY_LABELS.get(category, category)}
                for category in CATEGORIES
            ],
            "actions": [
                {"value": action, "label": ACTION_LABELS.get(action, action)}
                for action in sorted(actions)
            ],
        }
