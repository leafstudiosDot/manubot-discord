import asyncio
import json

import aiohttp
import websockets


GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"


def _cdn_asset_url(path: str, asset_hash: str | None) -> str | None:
    if not asset_hash:
        return None

    ext = "gif" if asset_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/{path}/{asset_hash}.{ext}?size=1024"


async def refresh_bot_profile(token: str, bot_state: dict) -> None:
    headers = {"Authorization": f"Bot {token}"}
    app_id = bot_state.get("app_id")

    async with aiohttp.ClientSession(headers=headers) as session:
        user_data = None
        application_data = None

        async with session.get("https://discord.com/api/users/@me") as response:
            if response.status == 200:
                user_data = await response.json()

        async with session.get("https://discord.com/api/oauth2/applications/@me") as response:
            if response.status == 200:
                application_data = await response.json()

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
        "username": username,
        "discriminator": discriminator,
        "avatar_url": avatar_url or app_icon_url,
        "banner_url": banner_url or app_cover_url,
    }


def dm_event(event_type: str, payload: dict) -> bool:
    data = payload.get("d") or {}
    if not isinstance(data, dict):
        return False

    if not event_type.startswith("MESSAGE_"):
        return False

    return data.get("guild_id") is None


async def heartbeat(ws, interval):
    while True:
        await asyncio.sleep(interval / 1000)  # interval is in ms
        await ws.send(json.dumps({"op": 1, "d": None}))


async def run(token: str, bot_state: dict, save_event):
    async with websockets.connect(GATEWAY_URL) as ws:
        hello_event = await ws.recv()
        hello_data = json.loads(hello_event)
        interval = hello_data["d"]["heartbeat_interval"]

        asyncio.create_task(heartbeat(ws, interval))

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
                            "state": "v0.0.1",
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
        except Exception as err:
            print(f"Failed to refresh bot profile: {err}")

        print("Manubot for Discord is connected and running as online.")

        while True:
            raw_message = await ws.recv()
            payload = json.loads(raw_message)

            op = payload.get("op")
            event_type = payload.get("t") or f"OP_{op}"
            sequence = payload.get("s")
            bot_state["last_sequence"] = sequence

            if event_type != "OP_11":
                print(f"[Gateway] {event_type} seq={sequence}")

            if dm_event(event_type, payload):
                save_event(event_type, sequence, payload)


async def runbot(token: str, bot_state: dict, save_event):
    while True:
        try:
            await run(token=token, bot_state=bot_state, save_event=save_event)
        except Exception as err:
            bot_state["connected"] = False
            print(f"Discord connection dropped: {err}")
            await asyncio.sleep(5)
