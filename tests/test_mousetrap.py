import asyncio

import pytest

from config import Settings
from mousetrap import (
    _MessageAttachmentBudget,
    _download_attachment,
    _sanitized_attachment,
    cache_mousetrap_attachments,
)


def settings(**overrides):
    values = {
        "environment": "testing",
        "csrf_secret": "x" * 40,
        "mousetrap_cdn_allowlist": ("cdn.discordapp.com",),
        "mousetrap_max_attachment_bytes": 1024,
        "mousetrap_max_message_bytes": 2048,
        "mousetrap_max_attachments": 4,
        "mousetrap_max_concurrent_downloads": 2,
        "mousetrap_download_timeout_seconds": 5,
        "mousetrap_connect_timeout_seconds": 1,
    }
    values.update(overrides)
    return Settings(**values)


class _FakeContent:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class _FakeResponse:
    def __init__(self, status=200, headers=None, chunks=()):
        self.status = status
        self.headers = headers or {}
        self.content = _FakeContent(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"payload"


def test_download_accepts_allowlisted_media():
    session = _FakeSession(
        _FakeResponse(
            headers={"Content-Type": "image/png", "Content-Length": str(len(PNG_BYTES))},
            chunks=[PNG_BYTES],
        )
    )
    budget = _MessageAttachmentBudget(2048)
    attachment = {"filename": "photo.png", "size": len(PNG_BYTES)}
    url = "https://cdn.discordapp.com/attachments/1/2/photo.png?ex=signed"

    result = asyncio.run(
        _download_attachment(session, url, attachment, settings(), budget)
    )

    assert result["cached_blob"] == PNG_BYTES
    assert result["cached_content_type"] == "image/png"
    assert result["cached_size"] == len(PNG_BYTES)
    assert session.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(status=302, headers={"Location": "https://evil.example/file"}),
        _FakeResponse(
            headers={"Content-Type": "image/svg+xml"}, chunks=[b"<svg></svg>"]
        ),
        _FakeResponse(
            headers={"Content-Type": "text/html"}, chunks=[b"<html></html>"]
        ),
        _FakeResponse(
            headers={"Content-Type": "image/png"}, chunks=[b"<html>not a png</html>"]
        ),
        _FakeResponse(
            headers={"Content-Type": "image/png", "Content-Length": "999999"},
            chunks=[PNG_BYTES],
        ),
        _FakeResponse(
            headers={"Content-Type": "image/png"}, chunks=[PNG_BYTES, b"x" * 2048]
        ),
    ],
)
def test_download_rejects_unsafe_responses(response):
    session = _FakeSession(response)
    budget = _MessageAttachmentBudget(4096)
    attachment = {"filename": "photo.png", "size": len(PNG_BYTES)}
    url = "https://cdn.discordapp.com/attachments/1/2/photo.png"

    result = asyncio.run(
        _download_attachment(session, url, attachment, settings(), budget)
    )

    assert "cached_blob" not in result
    assert budget.used == 0


def test_download_rejects_non_allowlisted_host_without_request():
    session = _FakeSession(_FakeResponse(chunks=[PNG_BYTES]))
    budget = _MessageAttachmentBudget(4096)

    result = asyncio.run(
        _download_attachment(
            session,
            "https://evil.example/file.png",
            {"filename": "file.png", "size": 10},
            settings(),
            budget,
        )
    )

    assert "cached_blob" not in result
    assert session.calls == []


def test_download_respects_aggregate_message_budget():
    budget = _MessageAttachmentBudget(20)
    session = _FakeSession(
        _FakeResponse(
            headers={"Content-Type": "image/png"}, chunks=[PNG_BYTES]
        )
    )
    attachment = {"filename": "photo.png", "size": len(PNG_BYTES)}
    url = "https://cdn.discordapp.com/attachments/1/2/photo.png"

    first = asyncio.run(
        _download_attachment(session, url, attachment, settings(), budget)
    )
    second = asyncio.run(
        _download_attachment(session, url, attachment, settings(), budget)
    )

    assert first["cached_blob"] == PNG_BYTES
    assert "cached_blob" not in second
    assert budget.used == len(PNG_BYTES)


def test_sanitized_attachment_drops_bytes_and_limits_fields():
    attachment = {
        "filename": "../../evil.png",
        "content_type": "image/png; charset=x",
        "url": "https://cdn.discordapp.com/a.png",
        "proxy_url": "https://media.discordapp.net/a.png",
        "cached_blob": b"secret",
        "cached_data_url": "data:text/html;base64,abc",
    }

    result = _sanitized_attachment(attachment)

    assert result["filename"] == "evil.png"
    assert result["content_type"] == "image/png"
    assert "cached_blob" not in result
    assert "cached_data_url" not in result


def test_cache_never_exceeds_attachment_count():
    attachments = [
        {
            "filename": f"file-{index}.png",
            "content_type": "image/png",
            "proxy_url": "https://evil.example/file.png",
        }
        for index in range(10)
    ]

    result = asyncio.run(
        cache_mousetrap_attachments(attachments, settings=settings())
    )

    assert len(result) == 4
    assert all("cached_blob" not in item for item in result)
