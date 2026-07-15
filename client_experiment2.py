"""client.py - Fixed with recv lock and proper connection management"""

import json
import asyncio
import websockets


class DerivClient:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.req_id = 1
        self._recv_lock = asyncio.Lock()  # CRITICAL: Prevents concurrent recv calls
        self._is_closing = False
        self._connected = False

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, open_timeout=30)
        self._connected = True
        self._is_closing = False
        print("Connected")

    async def subscribe(self, payload):
        if self._is_closing or self.ws is None:
            raise Exception("Connection is closed")
        
        payload["req_id"] = self.req_id
        self.req_id += 1
        await self.ws.send(json.dumps(payload))

    async def send(self, payload):
        """Send a request and wait for the matching response."""
        if self._is_closing or self.ws is None:
            raise Exception("Connection is closed")
        
        payload["req_id"] = self.req_id
        req_id = self.req_id
        self.req_id += 1

        await self.ws.send(json.dumps(payload))

        while True:
            message = await self.recv()
            if message.get("req_id") == req_id:
                return message

    async def recv(self):
        """Receive a message with lock to prevent concurrent recv calls."""
        if self._is_closing or self.ws is None:
            raise Exception("Connection is closed")
        
        # CRITICAL FIX: Only one coroutine can call recv at a time
        async with self._recv_lock:
            try:
                return json.loads(await self.ws.recv())
            except websockets.exceptions.ConnectionClosed:
                self._connected = False
                raise

    async def recv_streaming(self):
        """For streaming responses where req_id matching is not needed."""
        if self._is_closing or self.ws is None:
            raise Exception("Connection is closed")
        
        async with self._recv_lock:
            try:
                return json.loads(await self.ws.recv())
            except websockets.exceptions.ConnectionClosed:
                self._connected = False
                raise

    async def ping(self):
        """Send a ping to check connection health."""
        if self._is_closing or self.ws is None:
            raise Exception("Connection is closed")
        try:
            await self.ws.ping()
            return True
        except:
            self._connected = False
            raise

    async def close(self):
        self._is_closing = True
        if self.ws is not None:
            try:
                await self.ws.close()
            except:
                pass
            self.ws = None
            self._connected = False

    @property
    def is_connected(self):
        return self._connected and self.ws is not None and not self._is_closing