"""Main workflow (main.py)
Optimized for Gold (XAUUSD) Options Trading with a clean, client-renderable stream.
"""

import asyncio
import math
from client import DerivClient
from auth import get_ws_url
import argparse

import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID")

# ==========================================
# ANSI COLOR CODES (for terminal output)
# ==========================================
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
YELLOW = "\033[93m"

# ==========================================
# 1. BOT CONFIGURATION & PARAMETERS
# ==========================================
STRATEGY_TYPE = "MARTINGALE"  # "MARTINGALE" or "D_ALEMBERT"

# Core Trade Parameters (Updated for Gold with Minimum Timeframe)
SYMBOL = "frxXAUUSD"  # Gold vs US Dollar Asset Symbol
DURATION = 5  # Smallest supported duration interval
DURATION_UNIT = "m"  # "m" for Minutes (Minimum requirement for Gold)
CURRENCY = "USD"

# WIN RATE CONFIGURATION
DIRECTION_MODE = "TREND_FOLLOW"

# Strategy Specific Parameters
INITIAL_STAKE = 50
MAX_STAKE = 100
PROFIT_THRESHOLD = 20
LOSS_THRESHOLD = 100

STAKE_MULTIPLIER = 2  # [Martingale] Multiplier factor on loss
STAKE_INCREMENT = 1.0  # [D'Alembert] Unit scale change

# LOOPING BEHAVIOUR
INTER_SESSION_PAUSE = 5  # seconds
MAX_SESSIONS = 20 or math.inf


# ==========================================
# 2. CORE UTILITY API METHODS
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
    Reads immediate micro-ticks on Gold to judge short-term momentum shifts.
    """
    payload = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": 3,
        "end": "latest",
        "style": "ticks",
    }
    res = await client.send(payload)
    if "error" in res or "history" not in res:
        return "CALL", "SIDEWAYS (Fallback to Rise)"

    prices = res["history"].get("prices", [])
    if len(prices) >= 2:
        if prices[-1] > prices[-2]:
            return "CALL", "GOLD BULLISH MOMENTUM (Price Rising)"
        elif prices[-1] < prices[-2]:
            return "PUT", "GOLD BEARISH MOMENTUM (Price Dropping)"

    return "CALL", "STAGNANT MARKETS (No Edge Detected)"


# ==========================================
# 3. SINGLE SESSION EXECUTION ENGINE
# ==========================================
async def run_session(client, session_num):
    """Runs one full session until bounds are triggered."""
    current_stake = INITIAL_STAKE
    total_profit_loss = 0.0
    current_direction = "CALL"
    trade_count = 0

    initial_session_balance = await get_account_balance(client)

    print("==================================================")
    print(f"SESSION #{session_num} — INITIALIZING (GOLD SPOT)")
    print("==================================================")
    print(f"Risk Engine     : {STRATEGY_TYPE}")
    print(f"Selection Mode  : {DIRECTION_MODE}")
    print(f"Asset Class     : Gold (XAU/USD)")
    print(f"Timeframe       : {DURATION} {DURATION_UNIT.upper()}")
    print(f"Starting Balance: {initial_session_balance:.2f} {CURRENCY}")
    print(f"Take Profit Goal: +{PROFIT_THRESHOLD} {CURRENCY}")
    print(f"Max Stop Loss   : -{LOSS_THRESHOLD} {CURRENCY}")
    print("==================================================\n")

    while True:
        if total_profit_loss >= PROFIT_THRESHOLD:
            print(f"TARGET PROFIT REACHED! Session #{session_num} Stopping Safely.")
            break
        if total_profit_loss <= -LOSS_THRESHOLD:
            print(f"{RED}STOP LOSS LIMIT BREACHED! Session #{session_num}.")
            break

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

        remaining_budget = LOSS_THRESHOLD + total_profit_loss
        if current_stake > remaining_budget:
            print(
                f"Stop-Loss Guardrail Triggered: stake {current_stake:.2f} exceeds "
                f"remaining loss budget of {remaining_budget:.2f}!"
            )
            if remaining_budget <= 0:
                print("No loss budget remains — ending session now.")
                break
            current_stake = round(remaining_budget, 2)
            print(f"Clamping stake to remaining budget: {current_stake:.2f}")

        print("--------------------------------------------------")
        print(f"SESSION #{session_num} | TRADE #{trade_count} DASHBOARD")
        print("--------------------------------------------------")
        print(f"Balance Before : {balance_before_trade:.2f} {CURRENCY}")
        print(f"Market Context : {trend_label}")
        print(
            f"Execution      : Buying {current_direction} | Stake: {current_stake:.2f} {CURRENCY}"
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
            print(f"Order Rejected by Server: {buy_response['error']['message']}")
            print("Retrying loop execution sequence in 5 seconds...")
            await asyncio.sleep(5)
            continue

        contract_id = buy_response["buy"]["contract_id"]

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
                    f"Max Stake Guardrail Breached ({current_stake:.2f} > {MAX_STAKE:.2f})!"
                )
                print(f"Dropping stake to initial configuration: {INITIAL_STAKE}")
                current_stake = INITIAL_STAKE

        await asyncio.sleep(1.5)

    final_session_balance = await get_account_balance(client)
    summary_color = GREEN if total_profit_loss >= 0 else RED
    print("\n==================================================")
    print(f"SESSION #{session_num} COMPLETED SUMMARY REPORT")
    print("==================================================")
    print(f"Initial Session Balance : {initial_session_balance:.2f} {CURRENCY}")
    print(f"Final Session Balance   : {final_session_balance:.2f} {CURRENCY}")
    print(
        f"{summary_color}Session Net Delta Result: {total_profit_loss:+.2f} {CURRENCY}{RESET}"
    )
    print("==================================================\n")

    return total_profit_loss


# ==========================================
# 4. MAIN RUNTIME — LOOPS SESSIONS FOREVER
# ==========================================
async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", type=str, default="demo")
    args = parser.parse_args()
    mode = args.mode

    print(f'Mode: "{mode.upper()}"')

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

            session_is_final = session_num == MAX_SESSIONS
            if not session_is_final:
                print(
                    f"Pausing {INTER_SESSION_PAUSE}s before starting next session...\n"
                )
                await asyncio.sleep(INTER_SESSION_PAUSE)

    except KeyboardInterrupt:
        print("\nManual interrupt received (Ctrl+C). Shutting down gracefully...")

    finally:
        final_balance = await get_account_balance(client)
        summary_color = GREEN if grand_total_pnl >= 0 else RED
        header_color = GREEN if grand_total_pnl >= 0 else YELLOW

        print(f"\n{header_color}==================================================")
        print("BOT SHUTDOWN — FINAL ALL-TIME SUMMARY")
        print(f"=================================================={RESET}")
        print(f"Sessions Run            : {session_num}")
        print(f"Starting Balance        : {starting_balance:.2f} {CURRENCY}")
        print(f"Final Balance           : {final_balance:.2f} {CURRENCY}")
        print(
            f"{summary_color}All-Time Net PnL        : {grand_total_pnl:+.2f} {CURRENCY}{RESET}"
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
