import asyncio
import json
import logging

import aiohttp
import websockets

GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
DISCORD_API_BASE = "https://discord.com/api"
LOGGER = logging.getLogger(__name__)

REST_TIMEOUT = aiohttp.ClientTimeout(total=20, connect=5, sock_read=20)
GATEWAY_MAX_MESSAGE_BYTES = 4 * 1024 * 1024


def _cdn_asset_url(path: str, asset_hash: str | None) -> str | None:
    if not asset_hash:
        return None

    ext = "gif" if asset_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/{path}/{asset_hash}.{ext}?size=1024"


async def refresh_bot_profile(token: str, bot_state: dict) -> None:
    headers = {"Authorization": f"Bot {token}"}
    app_id = bot_state.get("app_id")

    async with aiohttp.ClientSession(headers=headers, timeout=REST_TIMEOUT) as session:
        user_data = None
        application_data = None
        guild_data = None

        async with session.get("https://discord.com/api/users/@me") as response:
            if response.status == 200:
                user_data = await response.json()

        async with session.get("https://discord.com/api/oauth2/applications/@me") as response:
            if response.status == 200:
                application_data = await response.json()

        async with session.get("https://discord.com/api/users/@me/guilds") as response:
            if response.status == 200:
                guild_data = await response.json()

    if not user_data:
        return

    user_id = user_data.get("id")
    username = user_data.get("username") or "Unknown"
    discriminator = str(user_data.get("discriminator") or "0000").zfill(4)
    avatar_url = _cdn_asset_url(f"avatars/{user_id}", user_data.get("avatar"))
    banner_url = _cdn_asset_url(f"banners/{user_id}", user_data.get("banner"))

    app_icon_url = None
    app_cover_url = None
    if application_data and app_id:
        app_icon_url = _cdn_asset_url(f"app-icons/{app_id}", application_data.get("icon"))
        app_cover_url = _cdn_asset_url(f"app-icons/{app_id}", application_data.get("cover_image"))

    bot_state["profile"] = {
        "id": user_id,
        "username": username,
        "discriminator": discriminator,
        "avatar_url": avatar_url or app_icon_url,
        "banner_url": banner_url or app_cover_url,
    }
    bot_state["bot_user_id"] = user_id

    guilds = []
    for guild in guild_data or []:
        if not isinstance(guild, dict):
            continue

        guild_id = str(guild.get("id") or "")
        icon_hash = guild.get("icon")
        icon_url = None
        if guild_id and icon_hash:
            ext = "gif" if str(icon_hash).startswith("a_") else "png"
            icon_url = f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.{ext}?size=128"

        guilds.append(
            {
                "id": guild_id,
                "name": guild.get("name") or "Unknown Server",
                "icon_url": icon_url,
                "owner": bool(guild.get("owner")),
                "permissions": guild.get("permissions"),
                "features": guild.get("features") or [],
            }
        )

    guilds.sort(key=lambda item: item["name"].lower())

    async with aiohttp.ClientSession(headers=headers, timeout=REST_TIMEOUT) as session:
        for guild in guilds:
            guild_id = guild.get("id")
            if not guild_id:
                guild["channels"] = []
                continue

            try:
                async with session.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/channels") as response:
                    if response.status != 200:
                        guild["channels"] = []
                        continue

                    channel_data = await response.json()
            except Exception:
                guild["channels"] = []
                continue

            if not isinstance(channel_data, list):
                guild["channels"] = []
                continue

            guild["channels"] = [
                {
                    "id": str(channel.get("id") or ""),
                    "name": str(channel.get("name") or "unknown-channel"),
                    "type": channel.get("type"),
                    "parent_id": channel.get("parent_id"),
                }
                for channel in channel_data
                if isinstance(channel, dict) and channel.get("type") in (0, 5, 10, 11, 12)
            ]

            guild["channels"].sort(key=lambda item: item["name"].lower())

    bot_state["guilds"] = guilds


def dm_event(event_type: str, payload: dict) -> bool:
    data = payload.get("d") or {}
    if not isinstance(data, dict):
        return False

    if not event_type.startswith("MESSAGE_"):
        return False

    return data.get("guild_id") is None


async def heartbeat(ws, interval):
    try:
        while True:
            await asyncio.sleep(interval / 1000)  # interval is in ms
            await ws.send(json.dumps({"op": 1, "d": None}))
    except asyncio.CancelledError:
        raise
    except Exception:
        # Let the receive loop observe the closed socket and reconnect.
        LOGGER.debug("Gateway heartbeat stopped", exc_info=True)


async def run(token: str, bot_state: dict, save_event, handle_guild_message=None):
    activity_state = str(bot_state.get("version") or "v0.0.0")

    async with websockets.connect(
        GATEWAY_URL,
        open_timeout=10,
        close_timeout=5,
        ping_interval=30,
        ping_timeout=10,
        max_size=GATEWAY_MAX_MESSAGE_BYTES,
    ) as ws:
        hello_event = await ws.recv()
        hello_data = json.loads(hello_event)
        interval = hello_data["d"]["heartbeat_interval"]

        heartbeat_task = asyncio.create_task(heartbeat(ws, interval))

        identify_payload = {
            "op": 2,
            "d": {
                "token": token,
                "intents": (
                    (1 << 9) |   # GUILD_MESSAGES
                    (1 << 12) |  # DIRECT_MESSAGES
                    (1 << 15)    # MESSAGE_CONTENT
                ),
                "properties": {
                    "$os": "linux",
                    "$browser": "leafstudiosDot",
                    "$device": "manubot",
                },
                "presence": {
                    "status": "online",
                    "afk": False,
                    "activities": [
                        {
                            "name": "Manubot",
                            "type": 4,
                            "state": activity_state,
                            "flags": 0,
                        }
                    ],
                },
            },
        }
        await ws.send(json.dumps(identify_payload))
        bot_state["connected"] = True

        try:
            await refresh_bot_profile(token, bot_state)
        except Exception:
            LOGGER.exception("Failed to refresh bot profile")

        LOGGER.info("Manubot for Discord is connected and running as online.")

        try:
            while True:
                raw_message = await ws.recv()
                try:
                    payload = json.loads(raw_message)
                except (TypeError, ValueError):
                    LOGGER.warning("Ignoring malformed Discord gateway payload")
                    continue
                if not isinstance(payload, dict):
                    continue

                op = payload.get("op")
                event_type = payload.get("t") or f"OP_{op}"
                sequence = payload.get("s")
                bot_state["last_sequence"] = sequence

                if event_type != "OP_11":
                    LOGGER.debug("Gateway event %s seq=%s", event_type, sequence)

                if event_type == "MESSAGE_CREATE" and handle_guild_message:
                    data = payload.get("d") or {}
                    if isinstance(data, dict) and data.get("guild_id") is not None:
                        try:
                            await handle_guild_message(payload)
                        except Exception:
                            LOGGER.exception("MouseTrap handling failed")

                if dm_event(event_type, payload):
                    save_event(event_type, sequence, payload)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
            bot_state["connected"] = False


async def runbot(token: str, bot_state: dict, save_event, handle_guild_message=None):
    while True:
        try:
            await run(token=token, bot_state=bot_state, save_event=save_event, handle_guild_message=handle_guild_message)
        except Exception as err:
            bot_state["connected"] = False
            LOGGER.warning("Discord connection dropped (%s)", type(err).__name__)
            await asyncio.sleep(5)


async def _discord_request_json(session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> dict:
    async with session.request(method, url, **kwargs) as response:
        raw = await response.text()
        payload = {}
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}

        if response.status >= 400:
            error_message = payload.get("message") if isinstance(payload, dict) else None
            raise RuntimeError(error_message or f"Discord API request failed with status {response.status}")

        return payload if isinstance(payload, dict) else {}


async def send_dm(token: str, user_id: str, content: str | None = None, files: list[dict] | None = None) -> dict:
    text_content = (content or "").strip()
    attachments = files or []

    if not user_id:
        raise RuntimeError("user_id is required")

    if not text_content and not attachments:
        raise RuntimeError("message content or at least one file is required")

    headers = {"Authorization": f"Bot {token}"}

    async with aiohttp.ClientSession(headers=headers, timeout=REST_TIMEOUT) as session:
        channel_data = await _discord_request_json(
            session,
            "POST",
            f"{DISCORD_API_BASE}/users/@me/channels",
            json={"recipient_id": user_id},
        )

        channel_id = str(channel_data.get("id") or "")
        if not channel_id:
            raise RuntimeError("failed to resolve a DM channel for this user")

        if attachments:
            attachment_specs = []
            for index, item in enumerate(attachments):
                attachment_specs.append(
                    {
                        "id": index,
                        "filename": item.get("filename") or f"file-{index}",
                    }
                )

            message_payload = {
                "content": text_content,
                "attachments": attachment_specs,
            }

            form = aiohttp.FormData()
            form.add_field("payload_json", json.dumps(message_payload), content_type="application/json")

            for index, item in enumerate(attachments):
                form.add_field(
                    f"files[{index}]",
                    item.get("data") or b"",
                    filename=item.get("filename") or f"file-{index}",
                    content_type=item.get("content_type") or "application/octet-stream",
                )

            message_data = await _discord_request_json(
                session,
                "POST",
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                data=form,
            )
        else:
            message_data = await _discord_request_json(
                session,
                "POST",
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
                json={"content": text_content},
            )

    return {
        "channel_id": channel_id,
        "message_id": message_data.get("id"),
        "timestamp": message_data.get("timestamp"),
        "message": message_data,
    }


async def delete_dm(token: str, channel_id: str, message_id: str) -> None:
    if not channel_id or not message_id:
        raise RuntimeError("channel_id and message_id are required")

    headers = {"Authorization": f"Bot {token}"}
    async with aiohttp.ClientSession(headers=headers, timeout=REST_TIMEOUT) as session:
        async with session.delete(f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}") as response:
            if response.status >= 400:
                raw = await response.text()
                try:
                    payload = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    payload = {}

                error_message = payload.get("message") if isinstance(payload, dict) else None
                raise RuntimeError(error_message or f"Failed to delete message (status {response.status})")


async def edit_discord_message(token: str, channel_id: str, message_id: str, payload: dict) -> dict:
    if not token:
        raise RuntimeError("token is required")
    if not channel_id or not message_id:
        raise RuntimeError("channel_id and message_id are required")

    headers = {"Authorization": f"Bot {token}"}
    async with aiohttp.ClientSession(headers=headers, timeout=REST_TIMEOUT) as session:
        async with session.patch(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}",
            json=payload,
        ) as response:
            raw = await response.text()
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"raw": raw}

            if response.status >= 400:
                error_message = data.get("message") if isinstance(data, dict) else None
                raise RuntimeError(error_message or f"Failed to edit message (status {response.status})")

            return data if isinstance(data, dict) else {}


async def get_guild_channels(token: str, guild_id: str) -> list[dict]:
    if not guild_id:
        raise RuntimeError("guild_id is required")

    headers = {"Authorization": f"Bot {token}"}
    async with aiohttp.ClientSession(headers=headers, timeout=REST_TIMEOUT) as session:
        async with session.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/channels") as response:
            raw = await response.text()
            if response.status >= 400:
                try:
                    payload = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    payload = {}

                error_message = payload.get("message") if isinstance(payload, dict) else None
                raise RuntimeError(error_message or f"Discord API request failed with status {response.status}")

            try:
                channels = json.loads(raw) if raw else []
            except json.JSONDecodeError:
                return []

    if not isinstance(channels, list):
        return []

    return [channel for channel in channels if isinstance(channel, dict)]
