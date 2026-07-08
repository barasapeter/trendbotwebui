from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
from datetime import datetime
import random
from client import DerivClient
from auth import get_ws_url
import math

app = FastAPI()

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
YELLOW = "\033[93m"

CURRENCY = "USD"

# LOOPING BEHAVIOUR
# How long to pause between the end of one session and the start of the next.
INTER_SESSION_PAUSE = 5  # seconds

# Number of sessions to run. Choose ONE of the following styles:
#   MAX_SESSIONS = 3            -> runs exactly 3 sessions, then stops
#   MAX_SESSIONS = math.inf     -> runs forever until Ctrl+C ("infinite")
#   MAX_SESSIONS = None         -> also runs forever until Ctrl+C (same as above)
MAX_SESSIONS = 1 or math.inf


app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Remove DerivClient usage here - balance will be streamed via WebSocket
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "FastAPI", "balance": "-", "PL": "null"},
    )


async def get_account_balance(client):
    """Queries and returns the exact live wallet balance from Deriv API."""
    res = await client.send({"balance": 1})
    if "error" in res:
        print(f"Balance Fetch Error: {res['error']['message']}")
        return 0.0
    return float(res.get("balance", {}).get("balance", 0.0))


async def get_market_trend(client, symbol):
    """
    WIN-RATE ENHANCER: Reads immediate tick momentum.
    Returns ('CALL', label) for an uptrend, or ('PUT', label) for a downtrend.
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
        # Compare current tick to previous tick to detect immediate micro-direction
        if prices[-1] > prices[-2]:
            return "CALL", "BULLISH MOMENTUM (Price Rising)"
        elif prices[-1] < prices[-2]:
            return "PUT", "BEARISH MOMENTUM (Price Dropping)"

    return "CALL", "STAGNANT MARKETS (No Edge Detected)"


async def stream(ws: WebSocket, data: dict):
    await ws.send_json({"trade_stream": data} | {"bot": {"running": True}})


# ==========================================
# 3. SINGLE SESSION EXECUTION ENGINE
# ==========================================
async def run_session(client, session_num, ws: WebSocket):
    """
    Runs one full session (until profit target or stop-loss is hit) and
    returns the session's net PnL so the caller can accumulate it.
    """

    # ==========================================
    # 1. BOT CONFIGURATION & PARAMETERS
    # ==========================================
    STRATEGY_TYPE = "MARTINGALE"  # "MARTINGALE" or "D_ALEMBERT"

    # Core Trade Parameters
    SYMBOL = "R_100"  # Volatility 100 Index (High tick frequency)
    DURATION = 5  # Number of ticks/seconds
    DURATION_UNIT = "t"  # "t" for ticks

    # WIN RATE CONFIGURATION
    # "TREND_FOLLOW" analyses live tick momentum before placing an order.
    # Options: "TREND_FOLLOW", "CALL" (Always Rise), "PUT" (Always Fall), "ALTERNATE"
    DIRECTION_MODE = "TREND_FOLLOW"

    # Strategy Specific Parameters
    INITIAL_STAKE = 10
    MAX_STAKE = 100
    PROFIT_THRESHOLD = 1
    LOSS_THRESHOLD = 100

    STAKE_MULTIPLIER = 2  # [Martingale] Multiplier factor on loss
    STAKE_INCREMENT = 1.0  # [D'Alembert] Unit unit scale change

    current_stake = INITIAL_STAKE
    total_profit_loss = 0.0
    current_direction = "CALL"
    trade_count = 0

    initial_session_balance = await get_account_balance(client)

    session_initializer = {
        "widget": "session_initializer",
        "title": f"SESSION {session_num} out of {MAX_SESSIONS} INITIALIZING",
        "balance": await get_account_balance(client),
        "metadata": {
            "risk_engine": STRATEGY_TYPE,
            "selection_mode": DIRECTION_MODE,
            "starting_balance": f"{initial_session_balance:.2f} {CURRENCY}",
            "take_profit_goal": f"+{PROFIT_THRESHOLD} {CURRENCY}",
            "max_stop_loss": f"-{LOSS_THRESHOLD} {CURRENCY}",
        },
    }
    await stream(ws, session_initializer)

    while True:
        if total_profit_loss >= PROFIT_THRESHOLD:
            target_profit_reached = {
                "widget": "snackbar",
                "title": "TARGET PROFIT REACHED!",
                "balance": await get_account_balance(client),
                "metadata": {
                    "session": session_num,
                    "message": f"Session {session_num} Stopping.",
                    "status": "success",
                },
            }
            await stream(ws, target_profit_reached)
            break
        if total_profit_loss <= -LOSS_THRESHOLD:
            stop_loss_breached = {
                "widget": "snackbar",
                "title": "STOP LOSS LIMIT BREACHED!",
                "balance": await get_account_balance(client),
                "metadata": {
                    "session": session_num,
                    "message": f"Session {session_num}.",
                    "status": "error",
                },
            }
            await stream(ws, stop_loss_breached)
            break

        trade_count += 1

        # 1. Fetch pre-execution state parameters
        balance_before_trade = await get_account_balance(client)

        # Determine Execution Direction Strategy
        trend_label = "Fixed"
        if DIRECTION_MODE == "TREND_FOLLOW":
            current_direction, trend_label = await get_market_trend(client, SYMBOL)
        elif DIRECTION_MODE == "ALTERNATE":
            current_direction = "PUT" if current_direction == "CALL" else "CALL"
            trend_label = "Alternating Cycle"
        else:
            current_direction = DIRECTION_MODE
            trend_label = f"Forced {DIRECTION_MODE}"

        # PRE-TRADE STOP-LOSS GUARDRAIL
        # Clamp the stake to whatever loss budget actually remains, so a
        # single trade can never blow past LOSS_THRESHOLD outright.
        remaining_budget = LOSS_THRESHOLD + total_profit_loss  # e.g. 25 + (-20) = 5
        if current_stake > remaining_budget:
            stop_loss_guardrail = {
                "widget": "detailed_snackbar",
                "title": "STOP-LOSS GUARDRAIL TRIGGERED",
                "balance": await get_account_balance(client),
                "metadata": {
                    "stake": f"{current_stake:.2f}",
                    "remaining_loss_budget": f"{remaining_budget:.2f}",
                    "message": (
                        f"Stake {current_stake:.2f} exceeds remaining "
                        f"loss budget of {remaining_budget:.2f}."
                    ),
                    "status": "warning",
                },
            }
            await stream(ws, stop_loss_guardrail)
            if remaining_budget <= 0:
                no_loss_budget = {
                    "widget": "snackbar",
                    "title": "NO LOSS BUDGET REMAINS",
                    "balance": await get_account_balance(client),
                    "metadata": {
                        "message": "No loss budget remains — ending session now.",
                        "status": "warning",
                    },
                }
                await stream(ws, no_loss_budget)
                break
            current_stake = round(remaining_budget, 2)
            stake_clamped = {
                "widget": "detailed_snackbar",
                "title": "STAKE CLAMPED",
                "balance": await get_account_balance(client),
                "metadata": {
                    "stake": current_stake,
                    "message": f"Clamping stake to remaining budget: {current_stake:.2f}",
                    "status": "info",
                },
            }
            await stream(ws, stake_clamped)

        # Clean Logging Interface (Per-Trade Metrics Dashboard)
        session_summary = {
            "widget": "session_summary",
            "title": f"SESSION {session_num} out of {MAX_SESSIONS} | TRADE {trade_count} DASHBOARD",
            "balance": await get_account_balance(client),
            "metadata": {
                "balance_before": balance_before_trade,
                "currency": CURRENCY,
                "market_context": trend_label,
                "direction": current_direction,
                "stake": current_stake,
            },
        }
        await stream(ws, session_summary)

        # Send Execution Payload
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
            order_rejected = {
                "widget": "snackbar",
                "title": "ORDER REJECTED BY SERVER",
                "balance": await get_account_balance(client),
                "metadata": {
                    "message": buy_response["error"]["message"],
                    "status": "error",
                },
            }
            await stream(ws, order_rejected)
            await stream(
                ws,
                {
                    "widget": "snackbar",
                    "title": "RETRYING EXECUTION",
                    "balance": await get_account_balance(client),
                    "metadata": {
                        "message": "Retrying loop execution sequence in 5 seconds...",
                        "retry_in_seconds": 5,
                        "status": "info",
                    },
                },
            )
            await asyncio.sleep(5)
            continue

        contract_id = buy_response["buy"]["contract_id"]

        # await stream Contract Expiry Progress
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

        # Calculate Running Accounting Adjustments
        total_profit_loss += contract_profit

        # 3. Fetch Post-execution Account Adjustments
        balance_after_trade = await get_account_balance(client)

        # Color-coded outcome: green for a win/profit round, red for a loss round
        result_str = "WIN" if is_win else "LOSS"
        trade_result_summary = {
            "widget": "trade_result",
            "title": f"TRADE #{trade_count} RESULT",
            "balance": await get_account_balance(client),
            "metadata": {
                "outcome": result_str,
                "profit": contract_profit,
                "balance_after": balance_after_trade,
                "session_net_pnl": total_profit_loss,
                "currency": CURRENCY,
                "status": (
                    "win"
                    if contract_profit > 0
                    else "loss" if contract_profit < 0 else "breakeven"
                ),
            },
        }

        await stream(ws, trade_result_summary)

        # Apply Risk Management Calculations (Martingale vs D'Alembert)
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
                await stream(
                    ws,
                    {
                        "widget": "risk_alert",
                        "title": "MAX STAKE GUARDRAIL BREACHED",
                        "balance": await get_account_balance(client),
                        "metadata": {
                            "stake": current_stake,
                            "max_stake": MAX_STAKE,
                            "message": (
                                f"Stake {current_stake:.2f} exceeds the maximum "
                                f"allowed stake of {MAX_STAKE:.2f}."
                                f"Dropping stake to initial configuration: {INITIAL_STAKE}"
                            ),
                            "status": "error",
                        },
                    },
                )
                current_stake = INITIAL_STAKE

        await asyncio.sleep(1.5)  # Safe spacing interval between evaluation loops

    # Session Closure Summary Output
    final_session_balance = await get_account_balance(client)
    session_summary_report = {
        "widget": "session_summary",
        "title": f"SESSION #{session_num} COMPLETED SUMMARY REPORT",
        "balance": await get_account_balance(client),
        "metadata": {
            "initial_balance": initial_session_balance,
            "final_balance": final_session_balance,
            "net_delta": total_profit_loss,
            "currency": CURRENCY,
            "status": (
                "profit"
                if total_profit_loss > 0
                else "loss" if total_profit_loss < 0 else "breakeven"
            ),
        },
    }

    await stream(ws, session_summary_report)

    return total_profit_loss


async def receiver(ws: WebSocket):
    # Create a single client instance that will be reused
    client = None

    try:
        while True:
            data = await ws.receive_json()

            action = data.get("action")

            if action == "run_bot":
                await ws.send_json(
                    {
                        "message": "acknowledgement",
                        "status": "Connecting to Deriv servers...",
                    }
                )

                # Only create client if it doesn't exist or was closed
                if client is None:
                    client = DerivClient(ws_url=get_ws_url(account_type="demo"))
                    await client.connect()

                # Send initial balance via WebSocket
                initial_balance = await get_account_balance(client)
                await ws.send_json(
                    {
                        "balance": initial_balance,
                        "pl": 0.00,
                        "bot": {"running": True},
                        "is_initial": True,
                    }
                )

                grand_total_pnl = 0.0
                session_num = 0
                starting_balance = initial_balance

                try:
                    while MAX_SESSIONS is None or session_num < MAX_SESSIONS:
                        session_num += 1
                        session_pnl = await run_session(client, session_num, ws)
                        grand_total_pnl += session_pnl

                        running_balance = await get_account_balance(client)

                        cumulative_status_report = {
                            "widget": "cumulative_status",
                            "title": f"SESSIONS CUMULATIVE STATUS (::S{session_num})",
                            "balance": running_balance,
                            "metadata": {
                                "starting_balance": starting_balance,
                                "current_balance": running_balance,
                                "cumulative_net_pnl": grand_total_pnl,
                                "currency": CURRENCY,
                                "status": (
                                    "profit"
                                    if grand_total_pnl > 0
                                    else "loss" if grand_total_pnl < 0 else "breakeven"
                                ),
                            },
                        }

                        await stream(ws, cumulative_status_report)

                        session_is_final = session_num == MAX_SESSIONS
                        if not session_is_final:
                            await stream(
                                ws,
                                {
                                    "widget": "notification",
                                    "title": "INTER-SESSION PAUSE",
                                    "balance": await get_account_balance(client),
                                    "metadata": {
                                        "duration_seconds": INTER_SESSION_PAUSE,
                                        "message": f"Pausing {INTER_SESSION_PAUSE}s before starting next session...",
                                        "status": "info",
                                    },
                                },
                            )
                            await asyncio.sleep(INTER_SESSION_PAUSE)

                except KeyboardInterrupt:
                    await stream(
                        ws,
                        {
                            "widget": "notification",
                            "title": "MANUAL INTERRUPT RECEIVED",
                            "balance": (
                                await get_account_balance(client) if client else 0
                            ),
                            "metadata": {
                                "message": "Shutting down gracefully...",
                                "signal": "SIGINT",
                                "status": "info",
                            },
                        },
                    )

                finally:
                    if client:
                        final_balance = await get_account_balance(client)

                        bot_shutdown_summary = {
                            "widget": "bot_shutdown_summary",
                            "title": "BOT SHUTDOWN FINAL ALL-TIME SUMMARY",
                            "balance": final_balance,
                            "end_of_stream": True,
                            "metadata": {
                                "sessions_run": session_num,
                                "starting_balance": starting_balance,
                                "final_balance": final_balance,
                                "all_time_net_pnl": grand_total_pnl,
                                "currency": CURRENCY,
                                "status": (
                                    "profit"
                                    if grand_total_pnl > 0
                                    else "loss" if grand_total_pnl < 0 else "breakeven"
                                ),
                            },
                        }

                        await stream(ws, bot_shutdown_summary)

                        await client.close()
                        client = None

            elif action == "stop_bot":
                if client:
                    # Close the client connection
                    await client.close()
                    client = None
                await stream(
                    ws,
                    {
                        "title": "Bot Stopped",
                        "balance": "Disconnected",
                        "metadata": {
                            "message": "Bot stopped by user request",
                            "status": "info",
                        },
                    },
                )

            elif action == "change_stake":
                await stream(ws, "New stake:", data["stake"])

            elif action == "switch_account":
                if client:
                    await client.close()
                    client = None
                await stream(ws, "Account:", data["account"])

            elif action == "get_balance":
                if client:
                    balance = await get_account_balance(client)
                    await ws.send_json(
                        {
                            "balance": balance,
                            "pl": 0.00,
                            "status": "Balance updated",
                            "is_balance_update": True,
                        }
                    )
                else:
                    await ws.send_json(
                        {"balance": "Not connected", "status": "No active connection"}
                    )

    except WebSocketDisconnect:
        print("Client disconnected.")
        if client:
            await client.close()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    receiver_task = asyncio.create_task(receiver(ws))

    done, pending = await asyncio.wait(
        [receiver_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)
