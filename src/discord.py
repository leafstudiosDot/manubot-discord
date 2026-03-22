import asyncio
import json

import websockets


GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"


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
