from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
from datetime import datetime
import random

app = FastAPI()

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configure templates
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "FastAPI", "message": "Hello, FastAPI!"},
    )


async def sender(ws: WebSocket):
    count = 0

    try:
        while True:
            await asyncio.sleep(4)
            count += 1

            await ws.send_json(
                {
                    "balance": 10234.56,
                    "pl": 18.75,
                    "status": f"OK, websocket running [{count}]",
                    "color": random.choice(
                        ["red", "blue", "green", "brown", "#20bebe", "orange"]
                    ),
                    "timestamp": datetime.now().isoformat(),
                }
            )

    except (WebSocketDisconnect, RuntimeError):
        print("Sender stopped.")
    except asyncio.CancelledError:
        print("Sender cancelled.")
        raise


async def receiver(ws: WebSocket):
    try:
        while True:
            data = await ws.receive_json()

            action = data.get("action")

            if action == "run_bot":
                await ws.send_json(
                    {
                        "balance": 10234.56,
                        "pl": 18.75,
                        "status": "COMMAND: Run Bot!",
                        "color": random.choice(
                            ["red", "blue", "green", "brown", "#20bebe", "orange"]
                        ),
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            elif action == "stop_bot":
                print("Stopping bot...")

            elif action == "change_stake":
                print("New stake:", data["stake"])

            elif action == "switch_account":
                print("Account:", data["account"])
    except WebSocketDisconnect:
        print("Client disconnected.")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    sender_task = asyncio.create_task(sender(ws))
    receiver_task = asyncio.create_task(receiver(ws))

    done, pending = await asyncio.wait(
        [sender_task, receiver_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)
