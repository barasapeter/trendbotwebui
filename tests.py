from auth import get_ws_url
from datetime import datetime
from zoneinfo import ZoneInfo

import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID")


print(get_ws_url("demo", token=TOKEN, app_id=APP_ID))

print(datetime.now(ZoneInfo("Africa/Nairobi")))
