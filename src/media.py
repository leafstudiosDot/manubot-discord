"""Allowlisted attachment media types and lightweight content sniffing."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from security import sanitize_content_type

ALLOWED_IMAGE_CONTENT_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/apng",
    }
)

ALLOWED_VIDEO_CONTENT_TYPES = frozenset(
    {
        "video/mp4",
        "video/webm",
        "video/ogg",
        "video/quicktime",
    }
)

ALLOWED_MEDIA_CONTENT_TYPES = ALLOWED_IMAGE_CONTENT_TYPES | ALLOWED_VIDEO_CONTENT_TYPES


def normalize_media_content_type(value: object) -> str:
    return sanitize_content_type(value)


def is_allowed_media_type(content_type: object) -> bool:
    return normalize_media_content_type(content_type) in ALLOWED_MEDIA_CONTENT_TYPES


def is_image_content_type(content_type: object) -> bool:
    return normalize_media_content_type(content_type) in ALLOWED_IMAGE_CONTENT_TYPES


def is_video_content_type(content_type: object) -> bool:
    return normalize_media_content_type(content_type) in ALLOWED_VIDEO_CONTENT_TYPES


def sniff_media_family(data: bytes) -> str | None:
    """Return ``image`` or ``video`` for a small set of recognized signatures.

    This is deliberately conservative. It prevents HTML/SVG/script bytes from
    being cached as an image even when an upstream Content-Type header lies.
    """
    if not data:
        return None

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if data.startswith(b"\xff\xd8\xff"):
        return "image"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis"):
            return "image"
        return "video"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "video"
    if data.startswith(b"OggS"):
        return "video"
    return None


def content_type_matches_family(content_type: str, family: str | None) -> bool:
    if is_image_content_type(content_type):
        return family == "image"
    if is_video_content_type(content_type):
        return family == "video"
    return False


def validate_attachment_url(
    value: object,
    allowed_hosts: tuple[str, ...] | list[str] | set[str],
) -> tuple[bool, str]:
    """Validate an HTTPS Discord CDN URL without following redirects.

    Returns ``(ok, reason)``. Reasons are for server logs only and never
    include the full URL because Discord CDN URLs contain signed parameters.
    """
    raw = str(value or "").strip()
    if not raw or len(raw) > 2048:
        return False, "missing_or_oversized_url"

    try:
        parsed = urlsplit(raw)
    except ValueError:
        return False, "invalid_url"

    if (parsed.scheme or "").lower() != "https":
        return False, "non_https_url"
    if parsed.username or parsed.password:
        return False, "url_credentials"
    if parsed.fragment:
        return False, "url_fragment"

    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return False, "missing_hostname"

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        # CDN hostnames are explicit allowlist entries, never raw IPs.
        return False, "ip_literal_host"

    allowed = {str(host).strip().lower().rstrip(".") for host in allowed_hosts}
    if hostname not in allowed:
        return False, "host_not_allowlisted"

    try:
        port = parsed.port
    except ValueError:
        return False, "invalid_port"
    if port not in (None, 443):
        return False, "non_standard_port"

    if not parsed.path or parsed.path == "/":
        return False, "missing_path"

    return True, "ok"
