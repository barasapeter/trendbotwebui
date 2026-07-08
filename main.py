from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
from datetime import datetime


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


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    try:
        while True:
            await asyncio.sleep(0.5)

            await ws.send_json(
                {
                    "balance": 10234.56,
                    "pl": 18.75,
                    "status": "running",
                    "trade": {"stake": 5, "profit": 1.2, "symbol": "R_100"},
                    "timestamp": datetime.now().isoformat(),
                }
            )
    except Exception:
        print("Client disconnected")
