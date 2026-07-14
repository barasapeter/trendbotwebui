"""client.py"""

import json
import websockets


class DerivClient:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.req_id = 1

    async def connect(self):
        # 1. Increase the opening handshake timeout (default is 10s)
        # Slower connections or heavy DNS/TLS routing often need more time.
        self.ws = await websockets.connect(self.ws_url, open_timeout=30)
        print("Connected")

    async def subscribe(self, payload):
        payload["req_id"] = self.req_id
        self.req_id += 1

        await self.ws.send(json.dumps(payload))

    async def send(self, payload):
        payload["req_id"] = self.req_id
        self.req_id += 1

        await self.ws.send(json.dumps(payload))

        while True:
            message = json.loads(await self.ws.recv())

            if message.get("req_id") == payload["req_id"]:
                return message

    async def recv(self):
        return json.loads(await self.ws.recv())

    async def close(self):
        # 2. Prevent AttributeError by checking if connection exists
        if self.ws is not None:
            await self.ws.close()
