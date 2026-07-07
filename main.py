"""main.py

FastAPI + websocket front door for the bot.

Protocol (all messages are JSON):

  Client -> Server
    {"type": "start", "config": { ...TradeConfig fields, all optional... }}
    {"type": "stop"}
    {"type": "ping"}

  Server -> Client (streamed as the bot runs)
    {"type": "connected", "data": {...}}
    {"type": "session_start", "data": {...}}
    {"type": "trade_dashboard", "data": {...}}
    {"type": "trade_result", "data": {...}}
    {"type": "session_summary", "data": {...}}
    {"type": "cumulative_status", "data": {...}}
    {"type": "shutdown", "data": {...}}
    {"type": "error", "data": {"message": "..."}}
    ...plus a few narrower event types (stake_clamped, order_rejected,
    max_stake_guardrail, session_stop_loss_breached, etc.) - see bot.py.

Only one bot run is allowed per connection at a time; send "stop" (or just
close the socket) to end it. A fresh "start" after a stop begins a new run.
"""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import ValidationError

from bot import run_bot
from schemas import TradeConfig

app = FastAPI(title="Deriv Trading Bot WS")

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index():
    """Serves the vanilla HTML/CSS/JS console at static/index.html."""
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws")
async def trade_ws(websocket: WebSocket):
    await websocket.accept()

    bot_task: asyncio.Task | None = None

    async def emit(event_type: str, data: dict) -> None:
        await websocket.send_json({"type": event_type, "data": data})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await emit("error", {"message": "Message must be valid JSON."})
                continue

            msg_type = message.get("type")

            if msg_type == "ping":
                await emit("pong", {})
                continue

            if msg_type == "stop":
                if bot_task and not bot_task.done():
                    bot_task.cancel()
                else:
                    await emit("error", {"message": "No bot is currently running."})
                continue

            if msg_type == "start":
                if bot_task and not bot_task.done():
                    await emit(
                        "error",
                        {"message": "A bot is already running. Send 'stop' first."},
                    )
                    continue

                try:
                    cfg = TradeConfig(**(message.get("config") or {}))
                except ValidationError as exc:
                    await emit("error", {"message": exc.errors()})
                    continue

                async def _run(cfg=cfg):
                    try:
                        await run_bot(cfg, emit)
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:  # noqa: BLE001 - surface to client
                        await emit("error", {"message": str(exc)})

                bot_task = asyncio.create_task(_run())
                continue

            await emit("error", {"message": f"Unknown message type: {msg_type!r}"})

    except WebSocketDisconnect:
        if bot_task and not bot_task.done():
            bot_task.cancel()
