"""auth.py

Unchanged in spirit from the original CLI version: credentials still come
from the server's environment (.env). The FastAPI server is the one process
holding the Deriv API token — clients only ever send trade *configuration*
over the websocket, never credentials.
"""

import os
from dotenv import load_dotenv
import requests

load_dotenv()

TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Deriv-App-ID": APP_ID,
}


def get_ws_url(account_type: str) -> str:
    get_app_id_response = requests.get(
        "https://api.derivws.com/trading/v1/options/accounts", headers=HEADERS
    )
    get_app_id_response.raise_for_status()

    apps = get_app_id_response.json()
    app_id = None
    for app in apps.get("data", []):
        if app.get("account_type") == account_type.lower():
            app_id = app.get("account_id")

    if app_id is None:
        raise ValueError('Invalid account type. Only "real" and "demo" are allowed')

    get_ws_url_response = requests.post(
        f"https://api.derivws.com/trading/v1/options/accounts/{app_id}/otp",
        headers=HEADERS,
    )
    get_ws_url_response.raise_for_status()

    data = get_ws_url_response.json()
    return data["data"]["url"]
