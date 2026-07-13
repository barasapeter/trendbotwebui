"""
Main Workflow (bot.py)
Fully integrated automated Martingale/D'Alembert options execution engine for Gold (XAUUSD).
Equipped with a Split-Window Trend Analyzer and an automated Finnhub Economic Calendar Guard.
"""

import asyncio
import math
import argparse
import os
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv

# Load local client components
from client import DerivClient
from auth import get_ws_url

load_dotenv()

TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

# ==========================================
# ANSI COLOR CODES (for terminal dashboards)
# ==========================================
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"

# ==========================================
# 1. BOT CONFIGURATION & PARAMETERS
# ==========================================
STRATEGY_TYPE = "MARTINGALE"  # "MARTINGALE" or "D_ALEMBERT"

# Core Gold Settings
SYMBOL = "frxXAUUSD"  # Gold vs US Dollar Spot
DURATION = 5  # 5-minute option duration
DURATION_UNIT = "m"  # "m" for Minutes (Minimum server requirement for Gold)
CURRENCY = "USD"

# Selection Strategy: "TREND_FOLLOW", "CALL", "PUT", "ALTERNATE"
DIRECTION_MODE = "TREND_FOLLOW"

# Risk Architecture
INITIAL_STAKE = 10.0
MAX_STAKE = 100.0
PROFIT_THRESHOLD = 20.0
LOSS_THRESHOLD = 100.0

STAKE_MULTIPLIER = 2.0  # [Martingale] Scale multiplier
STAKE_INCREMENT = 1.0  # [D'Alembert] Scale increment steps

# Timing Configurations
INTER_SESSION_PAUSE = 5  # Seconds between clearing one session and booting next
MAX_SESSIONS = 20 or math.inf

# News Restriction Windows
PAUSE_MINUTES_BEFORE = 15
PAUSE_MINUTES_AFTER = 15


# ==========================================
# 2. FINNHUB ECONOMIC CALENDAR GUARD ENGINE
# ==========================================
class EconomicNewsGuard:
    def __init__(self, api_key, pause_before=15, pause_after=15):
        self.api_key = api_key
        self.pause_before = timedelta(minutes=pause_before)
        self.pause_after = timedelta(minutes=pause_after)
        self.cached_events = []
        self.last_fetched_date = None

    def fetch_and_log_schedule(self):
        """Fetches the week's high-impact events and prints a clean layout on startup."""
        if not self.api_key:
            print(
                f"{YELLOW}[NEWS GUARD WARNING] No FINNHUB_API_KEY found in .env. Running without News Guard Protection!{RESET}"
            )
            return

        now = datetime.now(timezone.utc)
        self.last_fetched_date = now
        start_date = now.strftime("%Y-%m-%d")
        end_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")

        url = f"https://finnhub.io/api/v1/calendar/economic?from={start_date}&to={end_date}&token={self.api_key}"

        print(f"{CYAN}⏳ Syncing Global Economic Data Feed...{RESET}")
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                raw_data = response.json().get("economicCalendar", [])

                # Filter solely down to high-impact US data points affecting Gold pricing
                self.cached_events = [
                    {
                        "time": datetime.fromisoformat(
                            event["time"].replace("Z", "+00:00")
                        ),
                        "event": event.get("event", "Unknown Data Release"),
                        "impact": event.get("impact", "high"),
                    }
                    for event in raw_data
                    if event.get("impact") == "high" and event.get("country") == "US"
                ]

                # Output a clear formatted visual layout directly to the console
                print(f"\n{MAGENTA}==================================================")
                print("    UPCOMING HIGH-IMPACT ECONOMIC NEWS EVENTS      ")
                print(f"=================================================={RESET}")
                if not self.cached_events:
                    print(" No high-impact USD events scheduled for this week.")
                else:
                    for item in self.cached_events:
                        local_time_str = (
                            item["time"].astimezone().strftime("%Y-%m-%d %H:%M Local")
                        )
                        print(f" • [{local_time_str}] {item['event']}")
                print(
                    f"{MAGENTA}==================================================\n{RESET}"
                )
            else:
                print(
                    f"{RED}[NEWS GUARD ERROR] Failed to fetch calendar (Status: {response.status_code}){RESET}, Text: {response.text}"
                )
        except Exception as e:
            print(
                f"{RED}[NEWS GUARD ERROR] Error interacting with news data stream: {e}{RESET}"
            )

    def is_market_dangerous(self):
        """Evaluates whether current execution timestamp resides inside a restriction window."""
        if not self.cached_events:
            return False

        now = datetime.now(timezone.utc)
        for item in self.cached_events:
            window_start = item["time"] - self.pause_before
            window_end = item["time"] + self.pause_after

            if window_start <= now <= window_end:
                minutes_remaining = (item["time"] - now).total_seconds() / 60
                print(
                    f"\n{YELLOW}⚠️ [NEWS INTERCEPT] Proximity Alert! High-Impact Event: '{item['event']}'"
                )
                print(
                    f"   Delta Window: {minutes_remaining:+.1f} minutes from event baseline. Halting trades.{RESET}"
                )
                return True
        return False


# Initialize Guard Environment Globally
news_guard = EconomicNewsGuard(
    FINNHUB_API_KEY, PAUSE_MINUTES_BEFORE, PAUSE_MINUTES_AFTER
)


# ==========================================
# 3. CORE UTILITY API METHODS
# ==========================================
async def get_account_balance(client):
    """Queries and returns the exact live wallet balance from Deriv API."""
    res = await client.send({"balance": 1})
    if "error" in res:
        print(f"Balance Fetch Error: {res['error']['message']}")
        return 0.0
    return float(res.get("balance", {}).get("balance", 0.0))


async def get_market_trend(client, symbol):
    """
    UPGRADED GOLD VECTOR FILTER: Pulls a 20-tick historical window.
    Splits data into structural halves to parse momentum directions,
    effectively isolating real price shifts from short-term micro-tick noise.
    """
    payload = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": 20,
        "end": "latest",
        "style": "ticks",
    }
    res = await client.send(payload)
    if "error" in res or "history" not in res:
        return "CALL", "SIDEWAYS NOISE (Fallback to Rise)"

    prices = res["history"].get("prices", [])
    if len(prices) >= 20:
        # Split history into baseline segment vs newest segment
        baseline_segment = prices[0:10]
        current_segment = prices[10:20]

        avg_baseline = sum(baseline_segment) / len(baseline_segment)
        avg_current = sum(current_segment) / len(current_segment)

        displacement = avg_current - avg_baseline
        threshold = 0.02  # Filter out tight, flat consolidation structures

        if displacement > threshold:
            return "CALL", f"GOLD STRUCTURAL BULLISH VEC (Delta: +{displacement:.3f})"
        elif displacement < -threshold:
            return "PUT", f"GOLD STRUCTURAL BEARISH VEC (Delta: {displacement:.3f})"
        else:
            return (
                "CALL",
                f"CONSOLIDATION FLATS (Range Bound Delta: {displacement:+.3f})",
            )

    return "CALL", "INITIALIZING FEED (Insufficient tick depth)"


# ==========================================
# 4. SINGLE SESSION EXECUTION ENGINE
# ==========================================
async def run_session(client, session_num):
    """Runs one full options session utilizing targeted risk profiles."""
    current_stake = INITIAL_STAKE
    total_profit_loss = 0.0
    current_direction = "CALL"
    trade_count = 0

    initial_session_balance = await get_account_balance(client)

    print("==================================================")
    print(f"SESSION #{session_num} — INITIALIZING SYSTEM ENGINE")
    print("==================================================")
    print(f"Risk Engine     : {STRATEGY_TYPE}")
    print(f"Selection Mode  : {DIRECTION_MODE}")
    print("Asset Target    : Gold Spot (XAU/USD)")
    print(f"Execution Target: {DURATION} {DURATION_UNIT.upper()}")
    print(f"Starting balance: {initial_session_balance:.2f} {CURRENCY}")
    print(f"Take Profit Goal: +{PROFIT_THRESHOLD} {CURRENCY}")
    print(f"Max Stop Loss   : -{LOSS_THRESHOLD} {CURRENCY}")
    print("==================================================\n")

    while True:
        if total_profit_loss >= PROFIT_THRESHOLD:
            print(
                f"{GREEN}TARGET PROFIT REACHED! Session #{session_num} exiting cleanly.{RESET}"
            )
            break
        if total_profit_loss <= -LOSS_THRESHOLD:
            print(
                f"{RED}STOP LOSS BOUNDARY HIT! Terminating Session #{session_num}.{RESET}"
            )
            break

        # --- LIVE ECONOMIC CALENDAR GUARD INTERCEPT ---
        while news_guard.is_market_dangerous():
            print(
                f"{YELLOW}[PAUSE CYCLE] Standing by on sidelines for 60 seconds...{RESET}"
            )
            await asyncio.sleep(60)

        trade_count += 1
        balance_before_trade = await get_account_balance(client)

        if DIRECTION_MODE == "TREND_FOLLOW":
            current_direction, trend_label = await get_market_trend(client, SYMBOL)
        elif DIRECTION_MODE == "ALTERNATE":
            current_direction = "PUT" if current_direction == "CALL" else "CALL"
            trend_label = "Alternating Cycle"
        else:
            current_direction = DIRECTION_MODE
            trend_label = f"Forced {DIRECTION_MODE}"

        # Risk Threshold Adjustments
        remaining_budget = LOSS_THRESHOLD + total_profit_loss
        if current_stake > remaining_budget:
            print(
                f"{YELLOW}Guardrail Trigger: stake {current_stake:.2f} exceeds remaining allowance of {remaining_budget:.2f}!{RESET}"
            )
            if remaining_budget <= 0:
                print("Zero remaining operational capacity — closing session loop.")
                break
            current_stake = round(remaining_budget, 2)
            print(f"Clamped running stake allocation to: {current_stake:.2f}")

        print("--------------------------------------------------")
        print(f"SESSION #{session_num} | TRADE #{trade_count} RUNTIME METRICS")
        print("--------------------------------------------------")
        print(f"Balance Before : {balance_before_trade:.2f} {CURRENCY}")
        print(f"Market Context : {trend_label}")
        print(
            f"Execution Type : Buying {current_direction} | Size: {current_stake:.2f} {CURRENCY}"
        )

        buy_payload = {
            "buy": "1",
            "price": current_stake,
            "parameters": {
                "contract_type": current_direction,
                "currency": CURRENCY,
                "underlying_symbol": SYMBOL,
                "amount": current_stake,
                "basis": "stake",
                "duration": DURATION,
                "duration_unit": DURATION_UNIT,
            },
        }

        buy_response = await client.send(buy_payload)

        if "error" in buy_response:
            print(
                f"{RED}Order Rejected by Server: {buy_response['error']['message']}{RESET}"
            )
            print("Retrying loop execution sequence in 5 seconds...")
            await asyncio.sleep(5)
            continue

        contract_id = buy_response["buy"]["contract_id"]

        # Subscribe directly to contract data stream state mutations
        await client.subscribe(
            {
                "proposal_open_contract": 1,
                "contract_id": contract_id,
                "subscribe": 1,
            }
        )

        contract_profit = 0.0
        is_win = False

        while True:
            msg = await client.recv()
            if msg.get("msg_type") == "proposal_open_contract":
                poc = msg.get("proposal_open_contract", {})
                if poc.get("is_sold"):
                    contract_profit = float(poc.get("profit", 0.0))
                    is_win = contract_profit > 0
                    break

        total_profit_loss += contract_profit
        balance_after_trade = await get_account_balance(client)

        outcome_color = GREEN if is_win else RED
        result_str = "WIN" if is_win else "LOSS"
        print(
            f"{outcome_color}Match Outcome   : {result_str} ({contract_profit:+.2f} {CURRENCY}){RESET}"
        )
        print(f"Balance After   : {balance_after_trade:.2f} {CURRENCY}")
        pnl_color = GREEN if total_profit_loss >= 0 else RED
        print(
            f"{pnl_color}Session Net PnL : {total_profit_loss:+.2f} {CURRENCY}{RESET}"
        )
        print("--------------------------------------------------\n")

        # Re-evaluate Risk Layer Math Scaling
        if is_win:
            if STRATEGY_TYPE == "MARTINGALE":
                current_stake = INITIAL_STAKE
            elif STRATEGY_TYPE == "D_ALEMBERT":
                current_stake = max(INITIAL_STAKE, current_stake - STAKE_INCREMENT)
        else:
            if STRATEGY_TYPE == "MARTINGALE":
                current_stake = round((current_stake * STAKE_MULTIPLIER), 2)
            elif STRATEGY_TYPE == "D_ALEMBERT":
                current_stake = current_stake + STAKE_INCREMENT

            if current_stake > MAX_STAKE:
                print(
                    f"{YELLOW}Max Stake Guardrail Reset Enforced ({current_stake:.2f} > {MAX_STAKE:.2f}){RESET}"
                )
                current_stake = INITIAL_STAKE

        await asyncio.sleep(1.5)

    final_session_balance = await get_account_balance(client)
    summary_color = GREEN if total_profit_loss >= 0 else RED
    print("\n==================================================")
    print(f"SESSION #{session_num} ARCHIVE CLOSURE REPORT")
    print("==================================================")
    print(f"Initial Session Balance : {initial_session_balance:.2f} {CURRENCY}")
    print(f"Final Session Balance   : {final_session_balance:.2f} {CURRENCY}")
    print(
        f"{summary_color}Session Net Delta Result: {total_profit_loss:+.2f} {CURRENCY}{RESET}"
    )
    print("==================================================\n")

    return total_profit_loss


# ==========================================
# 5. MAIN ARCHITECTURE RUNTIME
# ==========================================
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", type=str, default="demo")
    args = parser.parse_args()
    mode = args.mode

    # Fetch economic calendar structure once immediately on startup execution
    news_guard.fetch_and_log_schedule()

    print(f'Runtime Network Channel: "{mode.upper()}"')

    client = DerivClient(
        ws_url=get_ws_url(account_type=mode, token=TOKEN, app_id=APP_ID)
    )
    await client.connect()

    grand_total_pnl = 0.0
    session_num = 0
    starting_balance = await get_account_balance(client)

    try:
        while MAX_SESSIONS is None or session_num < MAX_SESSIONS:
            session_num += 1
            session_pnl = await run_session(client, session_num)
            grand_total_pnl += session_pnl

            running_balance = await get_account_balance(client)
            cumulative_color = GREEN if grand_total_pnl >= 0 else RED

            print(f"{CYAN}==================================================")
            print(f"SESSIONS CUMULATIVE STATUS (after session #{session_num})")
            print(f"=================================================={RESET}")
            print(f"Starting Balance (all time) : {starting_balance:.2f} {CURRENCY}")
            print(f"Current Balance             : {running_balance:.2f} {CURRENCY}")
            print(
                f"{cumulative_color}Cumulative Net PnL           : {grand_total_pnl:+.2f} {CURRENCY}{RESET}"
            )
            print(f"{CYAN}=================================================={RESET}\n")

            if session_num < MAX_SESSIONS:
                print(
                    f"Pausing {INTER_SESSION_PAUSE}s before starting next session...\n"
                )
                await asyncio.sleep(INTER_SESSION_PAUSE)

    except KeyboardInterrupt:
        print(
            f"\n{YELLOW}Manual processing interrupt received. Exiting systems cleanly...{RESET}"
        )

    finally:
        final_balance = await get_account_balance(client)
        summary_color = GREEN if grand_total_pnl >= 0 else RED
        header_color = GREEN if grand_total_pnl >= 0 else YELLOW

        print(f"\n{header_color}==================================================")
        print("BOT GLOBAL SHUTDOWN — TOTAL HISTORICAL PERFORMANCE")
        print(f"=================================================={RESET}")
        print(f"Total Sessions Run      : {session_num}")
        print(f"Starting Global Balance : {starting_balance:.2f} {CURRENCY}")
        print(f"Final Account Balance   : {final_balance:.2f} {CURRENCY}")
        print(
            f"{summary_color}All-Time Combined PnL   : {grand_total_pnl:+.2f} {CURRENCY}{RESET}"
        )
        print(
            f"{header_color}=================================================={RESET}"
        )

        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
