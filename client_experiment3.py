"""client.py - Fixed with recv lock and timeout"""

import json
import asyncio
import websockets
import time


class DerivClient:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.req_id = 1
        self._recv_lock = asyncio.Lock()
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

    async def send(self, payload, timeout=10):
        """Send a request and wait for the matching response with timeout."""
        if self._is_closing or self.ws is None:
            raise Exception("Connection is closed")

        payload["req_id"] = self.req_id
        req_id = self.req_id
        self.req_id += 1

        await self.ws.send(json.dumps(payload))

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Use asyncio.wait_for with timeout
                message = await asyncio.wait_for(self.recv(), timeout=1.0)
                if message.get("req_id") == req_id:
                    return message
            except asyncio.TimeoutError:
                # Check if connection is still alive
                if self.ws is None or self._is_closing:
                    raise Exception("Connection closed during receive")
                # Continue waiting if within timeout
                continue
            except websockets.exceptions.ConnectionClosed:
                self._connected = False
                raise Exception("Connection closed during receive")

        raise Exception(f"Timeout waiting for response to request {req_id}")

    async def recv(self):
        """Receive a message with lock to prevent concurrent recv calls."""
        if self._is_closing or self.ws is None:
            raise Exception("Connection is closed")

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
            await asyncio.wait_for(self.ws.ping(), timeout=2.0)
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
