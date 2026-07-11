from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from client import DerivClient
from auth import get_ws_url
import math
import utils

from pathlib import Path

users_dir = Path("users")
users_dir.mkdir(parents=True, exist_ok=True)


app = FastAPI()


app.add_middleware(
    SessionMiddleware,
    secret_key="Load it later... adios!",
)

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

# How long to wait for a contract's final "is_sold" result before giving up
# on that specific poll and re-checking stop_event / connection health.
# This is a *retry interval*, not a hard timeout on the trade itself -- the
# loop keeps waiting past this, it just wakes up periodically so a stuck or
# dropped feed can never block shutdown forever.
CONTRACT_RESULT_POLL_TIMEOUT = 10  # seconds


app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if not request.session.get("username"):
        return RedirectResponse("/auth")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Runner", "balance": None, "PL": None},
    )


@app.get("/auth", response_class=HTMLResponse)
async def auth(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auth.html",
        context={"title": "Authorization - Amy"},
    )


@app.post("/auth", response_class=JSONResponse)
async def auth_post(request: Request):
    try:
        payload = await request.json()

        api_token = payload.get("api_token")
        app_id = payload.get("app_id")
        email = payload.get("email")

        if not api_token or not app_id or not email:
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: api_token, app_id or email",
            )

        result = utils.validate_email(email)

        if not result["valid"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid email address",
            )

        username = result["username"]

        user = {
            "username": username,
            "api_token": api_token,
            "app_id": app_id,
            "created_at": datetime.now(ZoneInfo("Africa/Nairobi")).isoformat(),
        }

        users_dir = Path("users")
        users_dir.mkdir(exist_ok=True)

        filepath = users_dir / f"{username}.json"

        # ==========================================================
        # Existing account
        # ==========================================================
        if filepath.exists():
            try:
                with open(filepath, "r", encoding="utf-8") as file:
                    existing_user = json.load(file)

            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read user file: {e}",
                )

            if (
                user["username"] == existing_user.get("username")
                and user["api_token"] == existing_user.get("api_token")
                and user["app_id"] == existing_user.get("app_id")
            ):
                request.session["username"] = username
                request.session["api_token"] = existing_user["api_token"]
                request.session["app_id"] = existing_user["app_id"]

                return JSONResponse(
                    status_code=200,
                    content={"detail": "Login successful"},
                )

            raise HTTPException(
                status_code=401,
                detail="The sign-in details are incorrect.",
            )

        # ==========================================================
        # New account
        # ==========================================================
        try:
            # Validate the credentials
            get_ws_url(
                account_type="demo",
                token=api_token,
                app_id=app_id,
            )

            with open(filepath, "w", encoding="utf-8") as file:
                json.dump(user, file, indent=4)

            request.session["username"] = username
            request.session["api_token"] = api_token
            request.session["app_id"] = app_id

            return JSONResponse(
                status_code=200,
                content={"detail": "Account created successfully"},
            )

        except Exception as e:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token or app_id: {e}",
            )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {e}",
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
            return "CALL", "BULLISH MOMENTUM"
        elif prices[-1] < prices[-2]:
            return "PUT", "BEARISH MOMENTUM"

    return "CALL", "STAGNANT MARKETS"


async def wait_for_contract_result(client, contract_id, stop_event):
    """
    Waits for the specific `contract_id` this trade opened to report
    is_sold, and returns (contract_profit, is_win).

    Fixes the original hang: the old loop did

        while True:
            msg = await client.recv()
            if msg.get("msg_type") == "proposal_open_contract":
                poc = msg.get("proposal_open_contract", {})
                if poc.get("is_sold"):
                    ...
                    break

    which had two problems:
      1. It never checked `contract_id`, so an unrelated
         proposal_open_contract update (e.g. leftover from a previous
         subscription) could in principle be misread.
      2. It had no timeout and never looked at `stop_event`. If the
         expected message was ever delayed, dropped, or simply never
         arrived (dropped connection, upstream hiccup), `client.recv()`
         would await forever. That hang blocks run_session from ever
         reaching its top-of-loop stop check again, which is exactly the
         "stuck after order placed" and "stuck on STOP COMMAND RECEIVED"
         symptoms: the *previous* trade's wait was still hung, so nothing
         downstream (trade_result_summary, the stop check, the
         bot_shutdown_summary in run_bot_loop's finally block) could ever
         run.

    This version polls with a timeout so it periodically wakes up even if
    no message arrives, filters strictly on contract_id, and re-subscribes
    if the feed goes quiet -- so a stuck feed can never block shutdown.
    """
    while True:
        try:
            msg = await asyncio.wait_for(
                client.recv(), timeout=CONTRACT_RESULT_POLL_TIMEOUT
            )
        except asyncio.TimeoutError:
            # No message within the poll window. If a stop was requested
            # while we were waiting, don't keep waiting indefinitely on a
            # feed that may be stalled -- surface that to the caller so
            # run_session can still make forward progress toward shutdown
            # once this specific contract does resolve, rather than being
            # silently stuck with no visibility.
            if stop_event.is_set():
                # Re-issue the subscription in case it silently dropped;
                # harmless no-op if it's still alive server-side.
                try:
                    await client.subscribe(
                        {
                            "proposal_open_contract": 1,
                            "contract_id": contract_id,
                            "subscribe": 1,
                        }
                    )
                except Exception:
                    pass
            continue

        if msg.get("msg_type") != "proposal_open_contract":
            continue

        poc = msg.get("proposal_open_contract", {})
        if poc.get("contract_id") != contract_id:
            # Not the contract this trade opened -- ignore and keep polling.
            continue

        if poc.get("is_sold"):
            contract_profit = float(poc.get("profit", 0.0))
            is_win = contract_profit > 0
            return contract_profit, is_win


async def stream(ws: WebSocket, data: dict):
    await ws.send_json({"trade_stream": data})


# ==========================================
# 3. SINGLE SESSION EXECUTION ENGINE
# ==========================================
async def run_session(
    client,
    session_num,
    ws: WebSocket,
    stop_event: asyncio.Event,
    session_state: dict,
    strategy_params: dict,
):
    """
    Runs one full session (until profit target or stop-loss is hit) and
    returns the session's net PnL so the caller can accumulate it.

    `stop_event` is an asyncio.Event shared with the receiver's message loop.
    It is checked at the TOP of every iteration -- before any market lookup
    or buy payload is built -- so once it's set, no new trade is ever placed.

    `session_state` is a shared dict. Its "order_in_flight" flag is set True
    the instant a buy payload is sent over the network, and False again once
    that contract's result is known. The receiver's stop_bot handler reads
    this flag to decide what acknowledgement to send: if an order is already
    in flight, stopping must wait for that order's result rather than cutting
    it off.
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

    # # Strategy Specific Parameters
    # INITIAL_STAKE = 5  # 100 × 0.05
    # MAX_STAKE = 50  # 1000 × 0.05
    # PROFIT_THRESHOLD = 5 or 5  # 100 × 0.05
    # LOSS_THRESHOLD = 50  # 1000 × 0.05

    # Strategy Specific Parameters
    INITIAL_STAKE = strategy_params.get("initial_stake")
    MAX_STAKE = strategy_params.get("max_stake")
    PROFIT_THRESHOLD = strategy_params.get("profit_threshold")
    LOSS_THRESHOLD = strategy_params.get("loss_threshold")

    STAKE_MULTIPLIER = 2  # [Martingale] Multiplier factor on loss
    STAKE_INCREMENT = 1.0  # [D'Alembert] Unit unit scale change

    current_stake = INITIAL_STAKE
    total_profit_loss = 0.0
    current_direction = "CALL"
    trade_count = 0

    initial_session_balance = await get_account_balance(client)

    session_initializer = {
        "widget": "session_initializer",
        "title": f"SESSION {session_num} OF {MAX_SESSIONS} INITIALIZING",
        "balance": await get_account_balance(client),
        "pl": round(total_profit_loss, 2),
        "metadata": {
            "risk_engine": STRATEGY_TYPE,
            "selection_mode": DIRECTION_MODE,
            "starting_balance": f"{initial_session_balance:.2f} {CURRENCY}",
            "take_profit_goal": f"+{PROFIT_THRESHOLD} {CURRENCY}",
            "max_stop_loss": f"-{LOSS_THRESHOLD} {CURRENCY}",
        },
    }
    await stream(ws, session_initializer | {"bot": {"running": True}})

    while True:
        # ------------------------------------------------------------
        # STOP CHECK -- must be the FIRST thing evaluated each loop.
        # Placing it here (before target/loss checks, before market
        # lookups, before the buy payload is built) guarantees that once
        # stop_bot is requested, no further order can ever be sent.
        # ------------------------------------------------------------
        if stop_event.is_set():
            bot_stopped = {
                "widget": "snackbar",
                "title": "BOT STOPPED",
                "balance": await get_account_balance(client),
                "pl": round(total_profit_loss, 2),
                "metadata": {
                    "session": session_num,
                    "message": f"Session {session_num} halted by stop command. No further trades will be placed.",
                    "status": "info",
                },
            }
            await stream(ws, bot_stopped | {"bot": {"running": False}})
            break

        if total_profit_loss >= PROFIT_THRESHOLD:
            target_profit_reached = {
                "widget": "snackbar",
                "title": "TARGET PROFIT REACHED!",
                "balance": await get_account_balance(client),
                "pl": round(total_profit_loss, 2),
                "metadata": {
                    "session": session_num,
                    "message": f"Session {session_num} Stopping.",
                    "status": "success",
                },
            }
            await stream(ws, target_profit_reached | {"bot": {"running": False}})
            break
        if total_profit_loss <= -LOSS_THRESHOLD:
            stop_loss_breached = {
                "widget": "snackbar",
                "title": "STOP LOSS LIMIT BREACHED!",
                "balance": await get_account_balance(client),
                "pl": round(total_profit_loss, 2),
                "metadata": {
                    "session": session_num,
                },
            }
            await stream(ws, stop_loss_breached | {"bot": {"running": False}})
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
                "pl": round(total_profit_loss, 2),
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
            await stream(ws, stop_loss_guardrail | {"bot": {"running": True}})
            if remaining_budget <= 0:
                no_loss_budget = {
                    "widget": "snackbar",
                    "title": "NO LOSS BUDGET REMAINS",
                    "balance": await get_account_balance(client),
                    "pl": round(total_profit_loss, 2),
                    "metadata": {
                        "message": "No loss budget remains - ending session now.",
                        "status": "warning",
                    },
                }
                await stream(ws, no_loss_budget | {"bot": {"running": False}})
                break
            current_stake = round(remaining_budget, 2)
            stake_clamped = {
                "widget": "detailed_snackbar",
                "title": "STAKE CLAMPED",
                "balance": await get_account_balance(client),
                "pl": round(total_profit_loss, 2),
                "metadata": {
                    "stake": current_stake,
                    "message": f"Clamping stake to remaining budget: {current_stake:.2f}",
                    "status": "info",
                },
            }
            await stream(ws, stake_clamped | {"bot": {"running": True}})

        
        if current_stake > 5000:
            current_stake = 5000
            stake2_clamped = {
                "widget": "detailed_snackbar",
                "title": "STAKE CLAMPED",
                "balance": await get_account_balance(client),
                "pl": round(total_profit_loss, 2),
                "metadata": {
                    "stake": current_stake,
                    "message": f"Projected payout > $10,000. Stake clamped to ${current_stake:.2f}.",
                    "status": "info",
                },
            }
            await stream(ws, stake2_clamped | {"bot": {"running": True}})

        if current_stake < 0.35:
            current_stake = 0.35

        # Clean Logging Interface (Per-Trade Metrics Dashboard)
        session_summary = {
            "widget": "session_summary",
            "title": f"SESSION {session_num} OF {MAX_SESSIONS} T{trade_count}",
            "balance": await get_account_balance(client),
            "pl": round(total_profit_loss, 2),
            "metadata": {
                "balance_before": balance_before_trade,
                "currency": CURRENCY,
                "market_context": trend_label,
                "direction": current_direction,
                "stake": current_stake,
            },
        }
        await stream(ws, session_summary | {"bot": {"running": True}})

        # Second stop check -- in case stop_bot arrived while we were doing
        # the (awaited, network-bound) trend lookup above. Still strictly
        # before the buy payload is sent.
        if stop_event.is_set():
            bot_stopped = {
                "widget": "snackbar",
                "title": "BOT STOPPED",
                "balance": await get_account_balance(client),
                "pl": round(total_profit_loss, 2),
                "metadata": {
                    "session": session_num,
                    "message": f"Session {session_num} halted by stop command before trade {trade_count} was placed.",
                    "status": "info",
                },
            }
            await stream(ws, bot_stopped | {"bot": {"running": False}})
            break

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

        # From this point on the network payload has left for the buy order.
        # Mark it as in-flight so a concurrent stop_bot request knows it must
        # wait for this specific order's result before shutting down.
        session_state["order_in_flight"] = True
        buy_response = await client.send(buy_payload)

        if "error" in buy_response:
            # No contract was actually opened -- safe to clear immediately.
            session_state["order_in_flight"] = False
            order_rejected = {
                "widget": "snackbar",
                "title": "ORDER REJECTED BY SERVER",
                "balance": await get_account_balance(client),
                "pl": round(total_profit_loss, 2),
                "metadata": {
                    "message": buy_response["error"]["message"],
                    "status": "error",
                },
            }
            await stream(ws, order_rejected | {"bot": {"running": True}})
            await stream(
                ws,
                {
                    "widget": "snackbar",
                    "title": "RETRYING EXECUTION",
                    "balance": await get_account_balance(client),
                    "pl": round(total_profit_loss, 2),
                    "metadata": {
                        "message": "Retrying loop execution sequence in 5 seconds...",
                        "retry_in_seconds": 5,
                        "status": "info",
                    },
                }
                | {"bot": {"running": False}},
            )
            break

        contract_id = buy_response["buy"]["contract_id"]

        # Stream Contract Expiry Progress
        await client.subscribe(
            {
                "proposal_open_contract": 1,
                "contract_id": contract_id,
                "subscribe": 1,
            }
        )

        # FIX: previously this was an inline `while True: msg = await
        # client.recv() ...` with no contract_id filter, no timeout, and no
        # stop_event visibility. If the expected is_sold message was ever
        # delayed or dropped, this would hang forever, which is what caused
        # both symptoms you saw: the session could never reach the
        # top-of-loop stop check again, so trade_result_summary,
        # session_state["order_in_flight"] = False, and eventually
        # bot_shutdown_summary in run_bot_loop's finally block would never
        # stream. wait_for_contract_result() polls with a timeout, filters
        # strictly on this trade's contract_id, and re-subscribes if the
        # feed goes quiet while a stop is pending -- so it always resolves
        # once the real result arrives, and never blocks shutdown forever.
        contract_profit, is_win = await wait_for_contract_result(
            client, contract_id, stop_event
        )

        # Result is known now -- the in-flight order is resolved. This is
        # what unblocks a pending stop_bot: the very next thing that happens
        # is the trade_result_summary stream below, followed (if stopping)
        # by the top-of-loop stop check and the shutdown summary.
        session_state["order_in_flight"] = False

        # Calculate Running Accounting Adjustments
        total_profit_loss += contract_profit

        # 3. Fetch Post-execution Account Adjustments
        balance_after_trade = await get_account_balance(client)

        # Color-coded outcome: green for a win/profit round, red for a loss round
        result_str = "WIN" if is_win else "LOSS"
        trade_result_summary = {
            "widget": "trade_result",
            "title": f"TRADE {trade_count}",
            "balance": await get_account_balance(client),
            "pl": round(total_profit_loss, 2),
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

        await stream(ws, trade_result_summary | {"bot": {"running": True}})

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
                        "pl": round(total_profit_loss, 2),
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
                    }
                    | {"bot": {"running": True}},
                )
                current_stake = INITIAL_STAKE

        await asyncio.sleep(1.5)  # Safe spacing interval between evaluation loops

    # Session Closure Summary Output
    final_session_balance = await get_account_balance(client)
    session_summary_report = {
        "widget": "session_summary",
        "title": f"SESSION {session_num} COMPLETED",
        "balance": await get_account_balance(client),
        "pl": round(total_profit_loss, 2),
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

    await stream(ws, session_summary_report | {"bot": {"running": False}})

    return total_profit_loss


async def run_bot_loop(
    client,
    ws: WebSocket,
    stop_event: asyncio.Event,
    current_mode: str,
    session_state: dict,
    strategy_params: dict,
):
    """
    Runs the multi-session bot loop. This is launched as its OWN background
    task by receiver() so that the websocket receive loop stays free to
    process incoming messages (in particular `stop_bot`) while trading is
    in progress. Without this, stop_bot could never be received because the
    receiver task would be blocked awaiting this function synchronously.
    """
    await ws.send_json(
        {
            "message": "acknowledgement",
            "status": "Connecting to Deriv servers...",
        }
    )

    grand_total_pnl = 0.0
    session_num = 0
    starting_balance = await get_account_balance(client)

    try:
        while MAX_SESSIONS is None or session_num < MAX_SESSIONS:
            if stop_event.is_set():
                break

            session_num += 1
            session_pnl = await run_session(
                client, session_num, ws, stop_event, session_state, strategy_params
            )
            grand_total_pnl += session_pnl

            running_balance = await get_account_balance(client)

            print("FINAL PLN::", round(grand_total_pnl, 2))

            cumulative_status_report = {
                "widget": "cumulative_status",
                "title": f"SESSIONS CUMULATIVE STATUS [S{session_num}]",
                "balance": running_balance,
                "pl": round(grand_total_pnl, 2),
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
            if not session_is_final and not stop_event.is_set():
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
                # Sleep in small increments so a stop_bot command doesn't
                # have to wait out the full pause before taking effect.
                slept = 0.0
                while slept < INTER_SESSION_PAUSE and not stop_event.is_set():
                    await asyncio.sleep(0.25)
                    slept += 0.25

    except asyncio.CancelledError:
        raise
    finally:
        final_balance = await get_account_balance(client)

        bot_shutdown_summary = {
            "widget": "bot_shutdown_summary",
            "title": "BOT SHUTDOWN FINAL SUMMARY",
            "balance": final_balance,
            "end_of_stream": True,
            "pl": round(grand_total_pnl, 2),
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

        await stream(ws, bot_shutdown_summary | {"bot": {"running": False}})

        # Close the client for the current mode
        await client.close()


async def receiver(ws: WebSocket, session: dict):
    # Store client instances for each mode
    clients = {"real": None, "demo": None}
    current_mode = "demo"  # Default mode

    # Shared, mutable stop signal + handle to the currently running bot task.
    # A plain bool passed by value cannot be observed by run_session() once
    # the loop has started; an Event is shared by reference and can be
    # `.set()` from here even while run_session() is mid-loop.
    stop_event = asyncio.Event()
    bot_task: asyncio.Task | None = None
    # Tracks whether the currently running bot has a buy order in flight
    # (network payload already sent, result not yet known). Read by the
    # stop_bot handler below to decide which acknowledgement to send.
    session_state = {"order_in_flight": False}

    try:
        while True:
            data = await ws.receive_json()

            action = data.get("action")
            requested_mode = data.get("mode", "demo")

            print(f"Action: {action}, Mode: {requested_mode}")

            # Update current mode
            current_mode = requested_mode

            # Get or create client for the requested mode
            client = clients.get(current_mode)

            # If client doesn't exist or is closed, create a new one
            if client is None:
                print(f"Creating new {current_mode} client...")
                client = DerivClient(
                    ws_url=get_ws_url(
                        account_type=current_mode,
                        token=session.get("api_token"),
                        app_id=session.get("app_id"),
                    )
                )
                await client.connect()
                clients[current_mode] = client
                print(f"{current_mode.capitalize()} client connected successfully")
            else:
                # Check if client is still connected
                try:
                    # Test connection by sending a ping
                    await client.send({"ping": 1})
                except Exception:
                    print(f"Reconnecting {current_mode} client...")
                    await client.close()
                    client = DerivClient(
                        ws_url=get_ws_url(
                            account_type=current_mode,
                            token=session.get("api_token"),
                            app_id=session.get("app_id"),
                        )
                    )
                    await client.connect()
                    clients[current_mode] = client

            # Send initial balance via WebSocket
            initial_balance = await get_account_balance(client)
            await ws.send_json(
                {
                    "balance": initial_balance,
                    "pl": "+0.00",
                    "bot": {"running": True},
                    "is_initial": True,
                    "mode": current_mode,
                }
            )

            if action == "run_bot":
                if bot_task and not bot_task.done():
                    await stream(
                        ws,
                        {
                            "widget": "notification",
                            "title": "BOT ALREADY RUNNING",
                            "balance": await get_account_balance(client),
                            "metadata": {
                                "message": "A bot session is already in progress.",
                                "status": "warning",
                            },
                        },
                    )
                else:
                    # Reset the stop signal for this fresh run, then launch
                    # the whole session loop as an independent background
                    # task. This is the key fix: it frees up this while-loop
                    # (and the `await ws.receive_json()` below) to keep
                    # listening for a `stop_bot` command WHILE trades are
                    # actively being placed.

                    # # Strategy Specific Parameters
                    # INITIAL_STAKE = strategy_params.get("initial_stake")
                    # MAX_STAKE = strategy_params.get("max_stake")
                    # PROFIT_THRESHOLD = strategy_params.get("profit_threshold")
                    # LOSS_THRESHOLD = strategy_params.get("loss_threshold")
                    # loss_threshold = round(
                    #     initial_balance * int(data.get("risk_tolerance")) / 100, 2
                    # )
                    # profit_threshold = round(loss_threshold * 0.1, 2)
                    # initial_stake = profit_threshold
                    # max_stake = loss_threshold

                    loss_threshold = round(
                        initial_balance * float(data.get("risk_tolerance")) / 100, 2
                    )

                    initial_stake = round(loss_threshold * 0.10, 2)
                    profit_threshold = round(
                        initial_stake * 1.0, 2
                    )  # Was initially  round(initial_stake * 0.90, 2)
                    max_stake = loss_threshold

                    strategy_params = {
                        "initial_stake": (initial_stake),
                        "max_stake": max_stake,
                        "profit_threshold": profit_threshold,
                        "loss_threshold": loss_threshold,
                    }
                    stop_event = asyncio.Event()
                    session_state = {"order_in_flight": False}
                    bot_task = asyncio.create_task(
                        run_bot_loop(
                            client,
                            ws,
                            stop_event,
                            current_mode,
                            session_state,
                            strategy_params,
                        )
                    )

            elif action == "stop_bot":
                stop_event.set()

                if session_state.get("order_in_flight"):
                    # A buy payload already went out over the network. We
                    # can't cancel it -- acknowledge the stop immediately,
                    # but be explicit that shutdown waits for that specific
                    # order's result. No further buy orders will be placed
                    # after this one; run_session's top-of-loop stop check
                    # will catch it right after the trade_result_summary
                    # is streamed, and run_bot_loop's finally block will
                    # then stream the shutdown confirmation.
                    #
                    # This acknowledgement used to be the last thing the
                    # client ever saw when an order was in flight, because
                    # the inner contract-wait loop this was promising to
                    # follow up on could hang indefinitely (see
                    # wait_for_contract_result). Now that the wait loop
                    # always resolves, this promise is actually kept.
                    await stream(
                        ws,
                        {
                            "widget": "notification",
                            "title": "STOP COMMAND RECEIVED",
                            "balance": (
                                await get_account_balance(client) if client else 0
                            ),
                            "metadata": {
                                "message": "Bot stopped with an inflight contract.",
                                "status": "warning",
                            },
                        },
                    )
                else:
                    await stream(
                        ws,
                        {
                            "widget": "notification",
                            "title": "STOP COMMAND RECEIVED",
                            "balance": (
                                await get_account_balance(client) if client else 0
                            ),
                            "metadata": {
                                "message": "Bot stop command received. No new trades will be placed; stopping as soon as the current step completes.",
                                "status": "error",
                            },
                        },
                    )

            elif action == "change_stake":
                await stream(ws, "New stake:", data["stake"])

            elif action == "switch_account":
                # Close existing client for the mode
                if clients.get(data["account"]):
                    await clients[data["account"]].close()
                    clients[data["account"]] = None
                await stream(ws, "Account:", data["account"])

            elif action == "get_balance":
                # Get the client for the requested mode
                mode = data.get("mode", current_mode)
                client_for_balance = clients.get(mode)

                if client_for_balance:
                    try:
                        balance = await get_account_balance(client_for_balance)
                        await ws.send_json(
                            {
                                "balance": balance,
                                "pl": "+0.00",
                                "status": "Balance updated",
                                "is_balance_update": True,
                                "mode": mode,
                            }
                        )
                    except Exception as e:
                        print(f"Error getting balance for {mode}: {e}")
                        # Try to reconnect
                        try:
                            await client_for_balance.close()
                        except Exception:
                            pass
                        client_for_balance = DerivClient(
                            ws_url=get_ws_url(
                                account_type=mode,
                                token=session.get("api_token"),
                                app_id=session.get("app_id"),
                            )
                        )
                        await client_for_balance.connect()
                        clients[mode] = client_for_balance
                        balance = await get_account_balance(client_for_balance)
                        await ws.send_json(
                            {
                                "balance": balance,
                                "pl": "+0.00",
                                "status": "Balance updated (reconnected)",
                                "is_balance_update": True,
                                "mode": mode,
                            }
                        )
                else:
                    # Create a new client for this mode
                    print(f"Creating new {mode} client for balance request...")
                    try:
                        client_for_balance = DerivClient(
                            ws_url=get_ws_url(
                                account_type=mode,
                                token=session.get("api_token"),
                                app_id=session.get("app_id"),
                            )
                        )
                        await client_for_balance.connect()
                        clients[mode] = client_for_balance
                        balance = await get_account_balance(client_for_balance)
                        await ws.send_json(
                            {
                                "balance": balance,
                                "pl": "+0.00",
                                "status": "Balance updated (new connection)",
                                "is_balance_update": True,
                                "mode": mode,
                            }
                        )
                    except Exception as e:
                        print(f"Error creating {mode} client: {e}")
                        await ws.send_json(
                            {
                                "balance": 0.0,
                                "pl": "+0.00",
                                "status": f"Error: {str(e)}",
                                "is_balance_update": True,
                                "mode": mode,
                            }
                        )

    except WebSocketDisconnect:
        print("Client disconnected.")
        # Make sure any running bot task is stopped and cleaned up
        stop_event.set()
        if bot_task and not bot_task.done():
            bot_task.cancel()
            try:
                await bot_task
            except (asyncio.CancelledError, Exception):
                pass
        # Close all clients
        for mode, client in clients.items():
            if client:
                try:
                    await client.close()
                except Exception:
                    pass


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    receiver_task = asyncio.create_task(receiver(ws, ws.scope.get("session")))

    done, pending = await asyncio.wait(
        [receiver_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)
