import pytest

from media import (
    content_type_matches_family,
    is_allowed_media_type,
    normalize_media_content_type,
    sniff_media_family,
    validate_attachment_url,
)
from security import (
    LoginRateLimiter,
    normalize_origin,
    origin_is_allowed,
    parse_iso_datetime,
    resolve_client_ip,
    sanitize_content_type,
    sanitize_filename,
    validate_password_length,
)


@pytest.mark.parametrize(
    "value",
    [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/apng",
        "video/mp4",
        "video/webm",
        "video/ogg",
        "video/quicktime",
    ],
)
def test_allowed_media_types(value):
    assert is_allowed_media_type(value)


@pytest.mark.parametrize(
    "value",
    [
        "image/svg+xml",
        "text/html",
        "application/javascript",
        "application/octet-stream",
        "",
        None,
    ],
)
def test_disallowed_media_types(value):
    assert not is_allowed_media_type(value)


def test_media_type_normalization():
    assert normalize_media_content_type(" Image/PNG ; charset=utf-8") == "image/png"
    assert content_type_matches_family("image/png", "image")
    assert content_type_matches_family("video/mp4", "video")
    assert not content_type_matches_family("image/png", "video")


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"\x89PNG\r\n\x1a\n" + b"rest", "image"),
        (b"\xff\xd8\xff" + b"rest", "image"),
        (b"GIF89a" + b"rest", "image"),
        (b"RIFF\x00\x00\x00\x00WEBP", "image"),
        (b"\x00\x00\x00\x18ftypmp42", "video"),
        (b"\x00\x00\x00\x18ftypavif", "image"),
        (b"\x1aE\xdf\xa3", "video"),
        (b"OggS", "video"),
        (b"<html>", None),
        (b"", None),
    ],
)
def test_sniff_media_family(data, expected):
    assert sniff_media_family(data) == expected


def test_attachment_url_allowlist():
    allowed = ("cdn.discordapp.com", "media.discordapp.net")

    assert validate_attachment_url(
        "https://cdn.discordapp.com/attachments/1/2/image.png?ex=abc", allowed
    )[0]
    assert validate_attachment_url(
        "https://media.discordapp.net/attachments/1/2/image.png", allowed
    )[0]


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.discordapp.com/attachments/1/2/image.png",
        "https://evil.example/attachments/1/2/image.png",
        "https://cdn.discordapp.com.evil.example/attachments/1/2/image.png",
        "https://cdn.discordapp.com:8443/attachments/1/2/image.png",
        "https://user:pass@cdn.discordapp.com/attachments/1/2/image.png",
        "https://127.0.0.1/attachments/image.png",
        "https://cdn.discordapp.com/",
        "https://cdn.discordapp.com/attachments/1/2/image.png#fragment",
        "",
    ],
)
def test_attachment_url_rejections(url):
    assert not validate_attachment_url(url, ("cdn.discordapp.com",))[0]


def test_origin_normalization():
    assert normalize_origin("https://example.com") == "https://example.com"
    assert normalize_origin("https://example.com/") == "https://example.com"
    assert normalize_origin("https://example.com:8443") == "https://example.com:8443"
    assert normalize_origin("https://example.com/path") is None
    assert normalize_origin("https://*.example.com") is None
    assert normalize_origin("javascript:alert(1)") is None


def test_origin_validation_same_origin_and_allowlist():
    assert origin_is_allowed(
        "https://panel.example.com",
        "https",
        "panel.example.com",
    )
    assert origin_is_allowed(
        "https://panel.example.com",
        "https",
        "panel.example.com:443",
    )
    assert not origin_is_allowed(
        "https://evil.example",
        "https",
        "panel.example.com",
    )
    assert origin_is_allowed(
        "https://trusted.example",
        "https",
        "panel.example.com",
        trusted_origins=("https://trusted.example",),
    )
    assert origin_is_allowed(
        "http://localhost:5173",
        "http",
        "localhost:6540",
        allow_loopback_dev=True,
    )
    assert not origin_is_allowed(
        "http://localhost:5173",
        "http",
        "localhost:6540",
        allow_loopback_dev=False,
    )
    assert not origin_is_allowed(None, "https", "panel.example.com")


def test_client_ip_does_not_trust_forwarded_header_by_default():
    assert resolve_client_ip("10.0.0.5", "1.2.3.4", False) == "10.0.0.5"


def test_client_ip_uses_valid_forwarded_value_when_enabled():
    assert resolve_client_ip("10.0.0.5", "1.2.3.4, 10.0.0.5", True) == "10.0.0.5"
    assert resolve_client_ip("10.0.0.5", "not-an-ip", True) == "10.0.0.5"


def test_iso_datetime_normalization():
    assert parse_iso_datetime("2026-01-02") == "2026-01-02T00:00:00"
    assert parse_iso_datetime("2026-01-02T03:04:05Z") == "2026-01-02T03:04:05"
    assert parse_iso_datetime("2026-01-02T03:04:05+02:00") == "2026-01-02T01:04:05"
    assert parse_iso_datetime("invalid") is None
    assert parse_iso_datetime(None) is None


def test_filename_sanitization():
    assert sanitize_filename("image.png") == "image.png"
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\windows\\system32\\cmd.exe") == "cmd.exe"
    assert sanitize_filename("bad\x00name.png") == "badname.png"
    assert sanitize_filename("..") is None
    assert sanitize_filename("x" * 201) is None


def test_content_type_sanitization():
    assert sanitize_content_type("image/png; charset=binary") == "image/png"
    assert sanitize_content_type("text/html") == "text/html"
    assert sanitize_content_type("bad content type") == "application/octet-stream"
    assert sanitize_content_type("") == "application/octet-stream"


def test_password_byte_limit():
    assert validate_password_length("short") is not None
    assert validate_password_length("long-enough") is None
    assert validate_password_length("a" * 72) is None
    assert "72" in validate_password_length("a" * 73)
    assert "72" in validate_password_length("é" * 37)


def test_rate_limiter_is_temporary_and_thread_safe_shape():
    now = [1000.0]
    limiter = LoginRateLimiter(
        max_attempts=3,
        window_seconds=60,
        block_seconds=30,
        clock=lambda: now[0],
    )
    keys = ["user:root", "ip:10.0.0.1"]

    for _ in range(3):
        assert limiter.retry_after(keys) == 0
        limiter.record_failure(keys)

    retry = limiter.retry_after(keys)
    assert retry > 0

    now[0] += 31
    assert limiter.retry_after(keys) == 0

    limiter.record_failure(keys)
    limiter.reset(keys)
    assert limiter.retry_after(keys) == 0
