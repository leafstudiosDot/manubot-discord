import os
import asyncio
import json
import websockets
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID")

GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"

async def heartbeat(ws, interval):
    while True:
        await asyncio.sleep(interval / 1000)  # interval is in ms
        await ws.send(json.dumps({"op": 1, "d": None}))

async def main():
    async with websockets.connect(GATEWAY_URL) as ws:
        hello_event = await ws.recv()
        hello_data = json.loads(hello_event)
        interval = hello_data['d']['heartbeat_interval']

        asyncio.create_task(heartbeat(ws, interval))

        identify_payload = {
            "op": 2,
            "d": {
                "token": TOKEN,
                "intents": 0,
                "properties": {
                    "$os": "linux",
                    "$browser": "leafstudiosDot",
                    "$device": "manubot"
                },
                "presence": {
                    "status": "online",
                    "afk": False,
                    "activities": [
                        {
                            "name": "Manubot",
                            "type": 4,
                            "state": "v0.0.1",
                            "flags": 0
                        }
                    ]
                }
            }
        }
        await ws.send(json.dumps(identify_payload))
        print("Manubot for Discord is connected and running as online.")

        while True:
            await ws.recv()

asyncio.run(main())