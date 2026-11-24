"""Runtime configuration loaded from environment variables.

The defaults are intentionally conservative for production. Local development
can opt out of Secure cookies and add explicit development origins without
weakening production defaults.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

from security import normalize_origin


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be a boolean value")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name) or ""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _parse_origins(name: str) -> tuple[str, ...]:
    origins: list[str] = []
    for value in _env_list(name):
        if "*" in value:
            raise ValueError(f"{name} must not contain wildcard origins")
        normalized = normalize_origin(value)
        if not normalized:
            raise ValueError(f"{name} contains an invalid origin: {value!r}")
        if normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


def _parse_host_allowlist(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    values = _env_list(name)
    if not values:
        return default
    hosts: list[str] = []
    for value in values:
        host = value.strip().lower().rstrip(".")
        if (
            not host
            or "*" in host
            or "/" in host
            or ":" in host
            or not all(char.isalnum() or char in ".-" for char in host)
        ):
            raise ValueError(f"{name} contains an invalid hostname: {value!r}")
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    production: bool = False

    api_host: str = "0.0.0.0"
    api_port: int = 6540
    web_threads: int = 16
    log_level: str = "info"
    gateway_enabled: bool = True

    session_cookie_name: str = "panel_session"
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "Lax"
    session_ttl_hours: int = 12
    csrf_secret: str = field(default_factory=lambda: secrets.token_urlsafe(48))
    csrf_secret_ephemeral: bool = True

    trusted_origins: tuple[str, ...] = ()
    ws_trusted_origins: tuple[str, ...] = ()
    allow_loopback_dev_origins: bool = True
    trust_proxy_headers: bool = False

    login_rate_limit_enabled: bool = True
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300
    login_rate_limit_block_seconds: int = 900

    max_request_bytes: int = 32 * 1024 * 1024
    max_json_bytes: int = 64 * 1024
    max_dm_file_bytes: int = 8 * 1024 * 1024
    max_dm_attachments: int = 10

    mousetrap_cdn_allowlist: tuple[str, ...] = (
        "cdn.discordapp.com",
        "media.discordapp.net",
    )
    mousetrap_max_attachment_bytes: int = 8 * 1024 * 1024
    mousetrap_max_message_bytes: int = 24 * 1024 * 1024
    mousetrap_max_attachments: int = 10
    mousetrap_max_concurrent_downloads: int = 4
    mousetrap_download_timeout_seconds: int = 20
    mousetrap_connect_timeout_seconds: int = 5

    backup_dir: str | None = None
    backup_retention: int = 5
    event_retention_days: int = 0
    mousetrap_log_retention_days: int = 0
    audit_log_retention_days: int = 0

    enable_hsts: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        environment = (
            os.getenv("MANUBOT_ENV")
            or os.getenv("FLASK_ENV")
            or "development"
        ).strip().lower()
        production = environment in ("production", "prod")

        session_cookie_secure = _env_bool("SESSION_COOKIE_SECURE", production)
        samesite = (os.getenv("SESSION_COOKIE_SAMESITE") or "Lax").strip()
        if samesite.lower() not in ("lax", "strict", "none"):
            raise ValueError("SESSION_COOKIE_SAMESITE must be Lax, Strict, or None")
        if samesite.lower() == "none" and not session_cookie_secure:
            raise ValueError("SameSite=None cookies must also use Secure cookies")

        csrf_secret = (os.getenv("CSRF_SECRET") or "").strip()
        csrf_secret_ephemeral = not bool(csrf_secret)
        if not csrf_secret:
            csrf_secret = secrets.token_urlsafe(48)
        elif len(csrf_secret) < 32:
            raise ValueError("CSRF_SECRET must be at least 32 characters")

        trusted_origins = _parse_origins("TRUSTED_ORIGINS")
        ws_trusted_origins = _parse_origins("WS_TRUSTED_ORIGINS")

        return cls(
            environment=environment,
            production=production,
            api_host=(os.getenv("API_HOST") or "0.0.0.0").strip(),
            api_port=_env_int("API_PORT", 6540, 1, 65535),
            web_threads=_env_int("WEB_THREADS", 16, 1, 256),
            log_level=(os.getenv("LOG_LEVEL") or "info").strip().lower(),
            gateway_enabled=_env_bool("MANUBOT_GATEWAY_ENABLED", True),
            session_cookie_name=(os.getenv("SESSION_COOKIE_NAME") or "panel_session").strip(),
            session_cookie_secure=session_cookie_secure,
            session_cookie_samesite=samesite,
            session_ttl_hours=_env_int("SESSION_TTL_HOURS", 12, 1, 24 * 30),
            csrf_secret=csrf_secret,
            csrf_secret_ephemeral=csrf_secret_ephemeral,
            trusted_origins=trusted_origins,
            ws_trusted_origins=ws_trusted_origins,
            allow_loopback_dev_origins=_env_bool(
                "ALLOW_LOOPBACK_DEV_ORIGINS", not production
            ),
            trust_proxy_headers=_env_bool("TRUST_PROXY_HEADERS", False),
            login_rate_limit_enabled=_env_bool("LOGIN_RATE_LIMIT_ENABLED", True),
            login_rate_limit_attempts=_env_int(
                "LOGIN_RATE_LIMIT_ATTEMPTS", 5, 1, 100
            ),
            login_rate_limit_window_seconds=_env_int(
                "LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300, 10, 86400
            ),
            login_rate_limit_block_seconds=_env_int(
                "LOGIN_RATE_LIMIT_BLOCK_SECONDS", 900, 10, 86400
            ),
            max_request_bytes=_env_int(
                "MAX_REQUEST_BYTES", 32 * 1024 * 1024, 1024, 512 * 1024 * 1024
            ),
            max_json_bytes=_env_int("MAX_JSON_BYTES", 64 * 1024, 1024, 4 * 1024 * 1024),
            max_dm_file_bytes=_env_int(
                "MAX_DM_FILE_BYTES", 8 * 1024 * 1024, 1, 512 * 1024 * 1024
            ),
            max_dm_attachments=_env_int("MAX_DM_ATTACHMENTS", 10, 1, 50),
            mousetrap_cdn_allowlist=_parse_host_allowlist(
                "MOUSETRAP_CDN_ALLOWLIST",
                ("cdn.discordapp.com", "media.discordapp.net"),
            ),
            mousetrap_max_attachment_bytes=_env_int(
                "MOUSETRAP_MAX_ATTACHMENT_BYTES",
                8 * 1024 * 1024,
                1024,
                64 * 1024 * 1024,
            ),
            mousetrap_max_message_bytes=_env_int(
                "MOUSETRAP_MAX_MESSAGE_BYTES",
                24 * 1024 * 1024,
                1024,
                256 * 1024 * 1024,
            ),
            mousetrap_max_attachments=_env_int(
                "MOUSETRAP_MAX_ATTACHMENTS", 10, 1, 50
            ),
            mousetrap_max_concurrent_downloads=_env_int(
                "MOUSETRAP_MAX_CONCURRENT_DOWNLOADS", 4, 1, 16
            ),
            mousetrap_download_timeout_seconds=_env_int(
                "MOUSETRAP_DOWNLOAD_TIMEOUT_SECONDS", 20, 1, 300
            ),
            mousetrap_connect_timeout_seconds=_env_int(
                "MOUSETRAP_CONNECT_TIMEOUT_SECONDS", 5, 1, 60
            ),
            backup_dir=(os.getenv("BACKUP_DIR") or "").strip() or None,
            backup_retention=_env_int("BACKUP_RETENTION", 5, 0, 100),
            event_retention_days=_env_int("EVENT_RETENTION_DAYS", 0, 0, 36500),
            mousetrap_log_retention_days=_env_int(
                "MOUSETRAP_LOG_RETENTION_DAYS", 0, 0, 36500
            ),
            audit_log_retention_days=_env_int(
                "AUDIT_LOG_RETENTION_DAYS", 0, 0, 36500
            ),
            enable_hsts=_env_bool("ENABLE_HSTS", False),
        )
