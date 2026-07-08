import asyncio
import json
import mimetypes

import aiohttp

from database import (
    delete_mousetrap_config,
    get_mousetrap_config,
    increment_mousetrap_kick_count,
    insert_mousetrap_message_log,
    list_mousetrap_message_logs,
    update_mousetrap_notice_target,
)
from discord import delete_dm as delete_discord_message, edit_discord_message

DISCORD_API_BASE = "https://discord.com/api"
MAX_MOUSETTRAP_ATTACHMENT_CACHE_BYTES = 8 * 1024 * 1024


def _resolve_attachment_content_type(attachment: dict) -> str:
    content_type = str(attachment.get("content_type") or "").strip()
    if content_type:
        return content_type

    filename = str(attachment.get("filename") or "").strip()
    guessed_type, _ = mimetypes.guess_type(filename)
    return guessed_type or ""


def _is_cacheable_mousetrap_attachment(attachment: dict) -> bool:
    content_type = _resolve_attachment_content_type(attachment)
    if not content_type.startswith(("image/", "video/")):
        return False

    try:
        size = int(attachment.get("size") or 0)
    except (TypeError, ValueError):
        size = 0

    return size <= MAX_MOUSETTRAP_ATTACHMENT_CACHE_BYTES


async def _cache_mousetrap_attachment(session: aiohttp.ClientSession, attachment: dict) -> dict:
    cached_attachment = dict(attachment)
    if not _is_cacheable_mousetrap_attachment(cached_attachment):
        return cached_attachment

    source_url = str(cached_attachment.get("proxy_url") or cached_attachment.get("url") or "").strip()
    if not source_url:
        return cached_attachment

    try:
        async with session.get(source_url) as response:
            if response.status >= 400:
                return cached_attachment

            content_type = str(response.headers.get("Content-Type") or _resolve_attachment_content_type(cached_attachment) or "").strip()
            if not content_type.startswith(("image/", "video/")):
                return cached_attachment

            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_MOUSETTRAP_ATTACHMENT_CACHE_BYTES:
                        return cached_attachment
                except (TypeError, ValueError):
                    pass

            raw_bytes = await response.read()
            if len(raw_bytes) > MAX_MOUSETTRAP_ATTACHMENT_CACHE_BYTES:
                return cached_attachment

            cached_attachment["cached_blob"] = raw_bytes
            cached_attachment["cached_content_type"] = content_type
            cached_attachment["cached_size"] = len(raw_bytes)
    except Exception:
        return cached_attachment

    return cached_attachment


async def cache_mousetrap_attachments(attachments: list[dict]) -> list[dict]:
    if not attachments:
        return []

    async with aiohttp.ClientSession() as session:
        return await asyncio.gather(*(_cache_mousetrap_attachment(session, attachment) for attachment in attachments))


def build_mousetrap_notice_payload(kick_count: int) -> dict:
    return {
        "embeds": [
            {
                "title": "MouseTrap enabled",
                "description": "This channel will be used to catch spam bots or non-bot hacked/compromised Discord accounts. Any user that sends a message in this channel will be automatically kicked from the server.",
                "color": 15105570,
                "fields": [
                    {
                        "name": "Kick Count",
                        "value": str(max(0, int(kick_count or 0))),
                        "inline": True,
                    }
                ],
            }
        ],
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 4,
                        "label": f"Kick Count: {max(0, int(kick_count or 0))}",
                        "custom_id": "mousetrap:armed",
                        "disabled": True,
                    }
                ],
            }
        ],
    }


def build_mousetrap_disabled_payload(kick_count: int) -> dict:
    payload = build_mousetrap_notice_payload(kick_count=kick_count)
    payload["embeds"][0]["description"] = "MouseTrap is currently disabled."
    return payload


async def send_mousetrap_notice(token: str, channel_id: str, kick_count: int) -> dict:
    if not token:
        raise RuntimeError("token is required")
    if not channel_id:
        raise RuntimeError("channel_id is required")

    headers = {"Authorization": f"Bot {token}"}
    payload = build_mousetrap_notice_payload(kick_count=kick_count)

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            json=payload,
        ) as response:
            raw = await response.text()
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"raw": raw}

            if response.status >= 400:
                error_message = data.get("message") if isinstance(data, dict) else None
                raise RuntimeError(error_message or f"Failed to send MouseTrap notice (status {response.status})")

            return data if isinstance(data, dict) else {}


async def edit_mousetrap_notice(token: str, channel_id: str, message_id: str, kick_count: int, enabled: bool = True) -> dict:
    payload = build_mousetrap_notice_payload(kick_count=kick_count) if enabled else build_mousetrap_disabled_payload(kick_count=kick_count)
    return await edit_discord_message(token=token, channel_id=channel_id, message_id=message_id, payload=payload)


async def kick_guild_member(token: str, guild_id: str, user_id: str, reason: str | None = None) -> None:
    if not token:
        raise RuntimeError("token is required")
    if not guild_id or not user_id:
        raise RuntimeError("guild_id and user_id are required")

    headers = {"Authorization": f"Bot {token}"}
    params = {}
    if reason:
        params["reason"] = reason

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.delete(
            f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}",
            params=params or None,
        ) as response:
            if response.status >= 400:
                raw = await response.text()
                try:
                    data = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    data = {}

                error_message = data.get("message") if isinstance(data, dict) else None
                raise RuntimeError(error_message or f"Failed to kick member (status {response.status})")


async def delete_discord_message(token: str, channel_id: str, message_id: str) -> None:
    if not token:
        raise RuntimeError("token is required")
    if not channel_id or not message_id:
        raise RuntimeError("channel_id and message_id are required")

    headers = {"Authorization": f"Bot {token}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.delete(f"https://discord.com/api/channels/{channel_id}/messages/{message_id}") as response:
            if response.status >= 400:
                raw = await response.text()
                try:
                    payload = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    payload = {}

                error_message = payload.get("message") if isinstance(payload, dict) else None
                raise RuntimeError(error_message or f"Failed to delete message (status {response.status})")


async def fetch_discord_user_profile(token: str, user_id: str) -> dict | None:
    if not token or not user_id:
        return None

    headers = {"Authorization": f"Bot {token}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(f"{DISCORD_API_BASE}/users/{user_id}") as response:
            if response.status >= 400:
                return None

            try:
                payload = await response.json()
            except Exception:
                return None

    if not isinstance(payload, dict):
        return None

    avatar_hash = payload.get("avatar")
    avatar_url = None
    if user_id and avatar_hash:
        ext = "gif" if str(avatar_hash).startswith("a_") else "png"
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.{ext}?size=128"

    return {
        "id": str(payload.get("id") or user_id),
        "username": payload.get("username") or "Unknown",
        "global_name": payload.get("global_name"),
        "display_name": payload.get("global_name") or payload.get("username") or "Unknown",
        "discriminator": payload.get("discriminator"),
        "avatar_url": avatar_url,
        "bot": bool(payload.get("bot")),
    }


def record_mousetrap_trigger(
    db_path,
    guild_id: str,
    channel_id: str,
    user_id: str,
    content: str,
    attachments: list[dict] | None,
    occurred_at: str,
) -> int:
    insert_mousetrap_message_log(
        db_path=db_path,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        content=content,
        attachments=attachments,
        occurred_at=occurred_at,
    )
    return increment_mousetrap_kick_count(db_path=db_path, guild_id=guild_id, amount=1)


def resolve_active_mousetrap_channel(db_path, guild_id: str) -> dict | None:
    return get_mousetrap_config(db_path=db_path, guild_id=guild_id)


async def build_mousetrap_logs(token: str, db_path, guild_id: str, channel_id: str | None = None, limit: int = 100) -> dict:
    config = get_mousetrap_config(db_path=db_path, guild_id=guild_id)
    resolved_channel_id = channel_id or (str(config.get("channel_id") or "") if config else None)
    logs = list_mousetrap_message_logs(
        db_path=db_path,
        guild_id=guild_id,
        channel_id=resolved_channel_id,
        limit=limit,
    )

    profiles: dict[str, dict | None] = {}
    for log in logs:
        user_id = str(log.get("user_id") or "")
        if user_id and user_id not in profiles:
            profiles[user_id] = await fetch_discord_user_profile(token=token, user_id=user_id)

    enriched_logs = []
    for log in logs:
        user_id = str(log.get("user_id") or "")
        enriched_logs.append(
            {
                **log,
                "author": profiles.get(user_id) or {
                    "id": user_id,
                    "username": user_id,
                    "global_name": None,
                    "display_name": user_id,
                    "discriminator": None,
                    "avatar_url": None,
                    "bot": False,
                },
            }
        )

    return {
        "status": "ok",
        "config": config,
        "logs": enriched_logs,
    }


async def set_mousetrap_channel(token: str, db_path, guild_id: str, channel_id: str | None) -> dict:
    current = get_mousetrap_config(db_path=db_path, guild_id=guild_id)
    current_kick_count = int(current.get("kick_count") or 0) if current else 0
    previous_notice_channel_id = str(current.get("notice_channel_id") or "") if current else ""
    previous_notice_message_id = str(current.get("notice_message_id") or "") if current else ""
    next_channel_id = str(channel_id or "")

    if previous_notice_channel_id and previous_notice_message_id:
        try:
            await delete_discord_message(token=token, channel_id=previous_notice_channel_id, message_id=previous_notice_message_id)
        except Exception:
            pass

    if not next_channel_id:
        from database import upsert_mousetrap_config

        upsert_mousetrap_config(db_path=db_path, guild_id=guild_id, channel_id="", kick_count=current_kick_count)
        update_mousetrap_notice_target(db_path=db_path, guild_id=guild_id, notice_channel_id=None, notice_message_id=None)
        return {
            "guild_id": guild_id,
            "channel_id": None,
            "kick_count": current_kick_count,
            "enabled": False,
        }

    from database import upsert_mousetrap_config

    upsert_mousetrap_config(db_path=db_path, guild_id=guild_id, channel_id=next_channel_id, kick_count=current_kick_count)
    notice = await send_mousetrap_notice(token=token, channel_id=next_channel_id, kick_count=current_kick_count)
    notice_channel_id = str(notice.get("channel_id") or next_channel_id)
    notice_message_id = str(notice.get("id") or "") or None
    if notice_message_id:
        update_mousetrap_notice_target(
            db_path=db_path,
            guild_id=guild_id,
            notice_channel_id=notice_channel_id,
            notice_message_id=notice_message_id,
        )

    return {
        "guild_id": guild_id,
        "channel_id": next_channel_id,
        "kick_count": current_kick_count,
        "enabled": True,
    }


async def handle_guild_message(token: str, db_path, payload: dict) -> None:
    data = payload.get("d") or {}
    if not isinstance(data, dict):
        return

    guild_id = str(data.get("guild_id") or "")
    channel_id = str(data.get("channel_id") or "")
    if not guild_id or not channel_id:
        return

    author = data.get("author") or {}
    if not isinstance(author, dict):
        return

    if author.get("bot"):
        return

    config = get_mousetrap_config(db_path=db_path, guild_id=guild_id)
    if not config or str(config.get("channel_id") or "") != channel_id:
        return

    user_id = str(author.get("id") or "")
    if not user_id:
        return

    occurred_at = str(data.get("timestamp") or "")
    content = str(data.get("content") or "")
    attachments = data.get("attachments") or []
    if not isinstance(attachments, list):
        attachments = []

    cached_attachments = []
    try:
        cached_attachments = await cache_mousetrap_attachments(attachments)
    except Exception:
        cached_attachments = attachments

    message_id = str(data.get("id") or "")
    if message_id:
        try:
            await delete_discord_message(token=token, channel_id=channel_id, message_id=message_id)
        except Exception:
            pass

    try:
        reason = f"MouseTrap triggered in channel {channel_id}"
        await kick_guild_member(token=token, guild_id=guild_id, user_id=user_id, reason=reason)
    except Exception:
        return

    record_mousetrap_trigger(
        db_path=db_path,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        content=content,
        attachments=cached_attachments,
        occurred_at=occurred_at,
    )

    updated_config = get_mousetrap_config(db_path=db_path, guild_id=guild_id)
    if not updated_config:
        return

    notice_channel_id = str(updated_config.get("notice_channel_id") or "")
    notice_message_id = str(updated_config.get("notice_message_id") or "")
    if notice_channel_id and notice_message_id:
        try:
            await edit_mousetrap_notice(
                token=token,
                channel_id=notice_channel_id,
                message_id=notice_message_id,
                kick_count=int(updated_config.get("kick_count") or 0),
                enabled=bool(str(updated_config.get("channel_id") or "")),
            )
        except Exception:
            pass