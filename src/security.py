"""Small, dependency-free security helpers shared by the backend."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlsplit

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_SNOWFLAKE_RE = re.compile(r"^\d{5,25}$")
_CONTENT_TYPE_RE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")

DEV_LOOPBACK_ORIGINS = frozenset(
    {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://[::1]:5173",
    }
)


def utc_now_iso() -> str:
    """Return a timezone-aware UTC timestamp suitable for SQLite text columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def derive_csrf_token(secret: str, session_token: str) -> str:
    """Derive a session-bound CSRF token.

    The value is deterministic for a session so it can be returned by the
    session endpoint after a reload, while remaining unguessable to a
    cross-site attacker that cannot read the HttpOnly session cookie.
    """
    return hmac.new(
        (secret or "").encode("utf-8"),
        f"csrf:{session_token}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def csrf_matches(secret: str, session_token: str | None, provided: str | None) -> bool:
    if not session_token or not provided:
        return False
    expected = derive_csrf_token(secret, session_token)
    return hmac.compare_digest(expected, provided.strip())


def normalize_origin(value: str | None) -> str | None:
    """Normalize an HTTP(S) origin, rejecting paths, credentials and wildcards."""
    raw = (value or "").strip()
    if not raw or "*" in raw:
        return None

    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.path not in ("", "/"):
        return None
    if parsed.query or parsed.fragment:
        return None

    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return None

    try:
        port = parsed.port
    except ValueError:
        return None

    if ":" in hostname:
        host_display = f"[{hostname}]"
    else:
        host_display = hostname

    default_port = 443 if scheme == "https" else 80
    if port is not None and port != default_port:
        return f"{scheme}://{host_display}:{port}"
    return f"{scheme}://{host_display}"


def origin_is_allowed(
    origin: str | None,
    request_scheme: str,
    request_host: str,
    trusted_origins: Iterable[str] = (),
    *,
    allow_loopback_dev: bool = False,
) -> bool:
    """Validate an Origin header against same-origin and an explicit allowlist."""
    if not origin:
        return False

    normalized = normalize_origin(origin)
    if not normalized:
        return False

    host = (request_host or "").strip().lower().rstrip(".")
    scheme = (request_scheme or "http").strip().lower()
    if scheme not in ("http", "https"):
        scheme = "http"

    same_origin = normalize_origin(f"{scheme}://{host}")
    if same_origin and hmac.compare_digest(normalized, same_origin):
        return True

    for trusted in trusted_origins:
        trusted_normalized = normalize_origin(trusted)
        if trusted_normalized and hmac.compare_digest(normalized, trusted_normalized):
            return True

    if allow_loopback_dev and normalized in DEV_LOOPBACK_ORIGINS:
        return True

    return False


def is_snowflake(value: object) -> bool:
    return bool(_SNOWFLAKE_RE.fullmatch(str(value or "").strip()))


def resolve_client_ip(
    remote_addr: str | None,
    forwarded_for: str | None,
    trust_proxy_headers: bool = False,
) -> str:
    """Return a rate-limiting key without trusting spoofable headers by default.

    ``X-Forwarded-For`` is only considered when explicitly enabled for a
    deployment whose reverse proxy overwrites the header. The rightmost valid
    address is used because it is the value appended by the nearest trusted
    proxy; earlier entries may be client-supplied.
    """
    remote = (remote_addr or "").strip()
    if not trust_proxy_headers:
        return remote

    candidates = str(forwarded_for or "").split(",")
    for candidate in reversed(candidates):
        value = candidate.strip()
        if not value:
            continue
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            continue

    return remote


def parse_iso_datetime(value: str | None) -> str | None:
    """Normalize a user-supplied ISO date/time for SQLite text comparisons."""
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.isoformat(timespec="seconds")


def sanitize_filename(value: object) -> str | None:
    """Return a safe basename for an uploaded file, or None if invalid."""
    name = str(value or "").strip().replace("\\", "/")
    name = name.rsplit("/", 1)[-1]
    name = _CONTROL_CHARS_RE.sub("", name).strip()
    if not name or name in (".", ".."):
        return None
    if len(name) > 200 or len(name.encode("utf-8")) > 255:
        return None
    return name


def sanitize_content_type(value: object) -> str:
    raw = str(value or "").split(";", 1)[0].strip().lower()
    if not raw or len(raw) > 100 or not _CONTENT_TYPE_RE.fullmatch(raw):
        return "application/octet-stream"
    return raw


def password_byte_length(password: str) -> int:
    return len((password or "").encode("utf-8"))


def validate_password_length(
    password: str, *, minimum_chars: int = 8, maximum_bytes: int = 72
) -> str | None:
    """Validate password length without ever logging or echoing the password."""
    if not password:
        return "Password is required"
    if len(password) < minimum_chars:
        return f"Password must be at least {minimum_chars} characters"
    if password_byte_length(password) > maximum_bytes:
        return f"Password must be at most {maximum_bytes} bytes (UTF-8)"
    return None


class LoginRateLimiter:
    """Thread-safe, time-boxed brute-force protection.

    Keys are normally a username and a client address. A block is temporary and
    never disables an account, so an attacker cannot permanently lock out an
    administrator.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_attempts: int = 5,
        window_seconds: int = 300,
        block_seconds: int = 900,
        clock=time.monotonic,
    ) -> None:
        self.enabled = enabled
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(1, int(window_seconds))
        self.block_seconds = max(1, int(block_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}
        self._blocked_until: dict[str, float] = {}

    def _now(self) -> float:
        return float(self._clock())

    def _trim(self, key: str, now: float) -> deque[float]:
        failures = self._failures.get(key)
        if failures is None:
            failures = deque()
            self._failures[key] = failures
        cutoff = now - self.window_seconds
        while failures and failures[0] < cutoff:
            failures.popleft()
        return failures

    def retry_after(self, keys: Iterable[str]) -> int:
        if not self.enabled:
            return 0

        now = self._now()
        retry = 0
        with self._lock:
            for key in keys:
                blocked_until = self._blocked_until.get(key)
                if blocked_until is None:
                    continue
                if blocked_until <= now:
                    self._blocked_until.pop(key, None)
                    self._failures.pop(key, None)
                    continue
                retry = max(retry, int(blocked_until - now) + 1)
        return retry

    def record_failure(self, keys: Iterable[str]) -> None:
        if not self.enabled:
            return

        now = self._now()
        with self._lock:
            for key in keys:
                blocked_until = self._blocked_until.get(key)
                if blocked_until is not None and blocked_until <= now:
                    self._blocked_until.pop(key, None)
                    self._failures.pop(key, None)
                if blocked_until is not None and blocked_until > now:
                    continue

                failures = self._trim(key, now)
                failures.append(now)
                if len(failures) >= self.max_attempts:
                    self._blocked_until[key] = now + self.block_seconds
                    failures.clear()

    def reset(self, keys: Iterable[str]) -> None:
        with self._lock:
            for key in keys:
                self._blocked_until.pop(key, None)
                self._failures.pop(key, None)
