"""bot.py

This is rapid_exit_inf.py's engine, restructured to run inside a FastAPI
websocket handler instead of a terminal:

  - All the module-level constants (SYMBOL, STRATEGY_TYPE, INITIAL_STAKE...)
    are now fields on a `TradeConfig` passed in per-run.
  - Every `print(...)` becomes an `await emit("event_name", {...})` call, so
    the client gets structured JSON it can render however it likes instead
    of ANSI-colored terminal text.
  - The whole thing is cancellable: main.py cancels the asyncio task running
    `run_bot` when the client sends {"type": "stop"}, and we catch
    asyncio.CancelledError to shut down cleanly (closing the Deriv
    connection, emitting a final summary) exactly like the old
    KeyboardInterrupt handler did.

The trading logic itself (martingale / d'alembert staking, trend-follow
direction picking, stop-loss guardrails) is unchanged from the original.
"""

import asyncio
from typing import Awaitable, Callable

from deriv_client import DerivClient
from auth import get_ws_url
from schemas import TradeConfig

Emit = Callable[[str, dict], Awaitable[None]]


async def get_account_balance(client: DerivClient) -> float:
    res = await client.send({"balance": 1})
    if "error" in res:
        return 0.0
    return float(res.get("balance", {}).get("balance", 0.0))


async def get_market_trend(client: DerivClient, symbol: str):
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
            return "CALL", "BULLISH MOMENTUM (Price Rising)"
        elif prices[-1] < prices[-2]:
            return "PUT", "BEARISH MOMENTUM (Price Dropping)"

    return "CALL", "STAGNANT MARKETS (No Edge Detected)"


async def run_session(client: DerivClient, cfg: TradeConfig, session_num: int, emit: Emit) -> float:
    current_stake = cfg.initial_stake
    total_profit_loss = 0.0
    current_direction = "CALL"
    trade_count = 0

    initial_session_balance = await get_account_balance(client)

    await emit(
        "session_start",
        {
            "session_num": session_num,
            "strategy_type": cfg.strategy_type,
            "direction_mode": cfg.direction_mode,
            "starting_balance": initial_session_balance,
            "profit_threshold": cfg.profit_threshold,
            "loss_threshold": cfg.loss_threshold,
            "currency": cfg.currency,
        },
    )

    while True:
        if total_profit_loss >= cfg.profit_threshold:
            await emit(
                "session_target_reached",
                {"session_num": session_num, "net_pnl": total_profit_loss},
            )
            break
        if total_profit_loss <= -cfg.loss_threshold:
            await emit(
                "session_stop_loss_breached",
                {"session_num": session_num, "net_pnl": total_profit_loss},
            )
            break

        trade_count += 1
        balance_before_trade = await get_account_balance(client)

        trend_label = "Fixed"
        if cfg.direction_mode == "TREND_FOLLOW":
            current_direction, trend_label = await get_market_trend(client, cfg.symbol)
        elif cfg.direction_mode == "ALTERNATE":
            current_direction = "PUT" if current_direction == "CALL" else "CALL"
            trend_label = "Alternating Cycle"
        else:
            current_direction = cfg.direction_mode
            trend_label = f"Forced {cfg.direction_mode}"

        # Pre-trade stop-loss guardrail: clamp stake to remaining loss budget
        remaining_budget = cfg.loss_threshold + total_profit_loss
        if current_stake > remaining_budget:
            if remaining_budget <= 0:
                await emit(
                    "session_no_budget_remaining",
                    {"session_num": session_num, "net_pnl": total_profit_loss},
                )
                break
            clamped_stake = round(remaining_budget, 2)
            await emit(
                "stake_clamped",
                {
                    "session_num": session_num,
                    "requested_stake": current_stake,
                    "clamped_stake": clamped_stake,
                    "remaining_budget": remaining_budget,
                },
            )
            current_stake = clamped_stake

        await emit(
            "trade_dashboard",
            {
                "session_num": session_num,
                "trade_num": trade_count,
                "balance_before": balance_before_trade,
                "market_context": trend_label,
                "direction": current_direction,
                "stake": current_stake,
                "currency": cfg.currency,
            },
        )

        buy_payload = {
            "buy": "1",
            "price": current_stake,
            "parameters": {
                "contract_type": current_direction,
                "currency": cfg.currency,
                "underlying_symbol": cfg.symbol,
                "amount": current_stake,
                "basis": "stake",
                "duration": cfg.duration,
                "duration_unit": cfg.duration_unit,
            },
        }

        buy_response = await client.send(buy_payload)

        if "error" in buy_response:
            await emit(
                "order_rejected",
                {
                    "session_num": session_num,
                    "trade_num": trade_count,
                    "message": buy_response["error"]["message"],
                },
            )
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

        await emit(
            "trade_result",
            {
                "session_num": session_num,
                "trade_num": trade_count,
                "direction": current_direction,
                "stake": current_stake,
                "outcome": "WIN" if is_win else "LOSS",
                "contract_profit": contract_profit,
                "balance_after": balance_after_trade,
                "session_net_pnl": total_profit_loss,
                "currency": cfg.currency,
            },
        )

        # Risk management: adjust next stake per strategy
        if is_win:
            if cfg.strategy_type == "MARTINGALE":
                current_stake = cfg.initial_stake
            elif cfg.strategy_type == "D_ALEMBERT":
                current_stake = max(cfg.initial_stake, current_stake - cfg.stake_increment)
        else:
            if cfg.strategy_type == "MARTINGALE":
                current_stake = round(current_stake * cfg.stake_multiplier, 2)
            elif cfg.strategy_type == "D_ALEMBERT":
                current_stake = current_stake + cfg.stake_increment

            if current_stake > cfg.max_stake:
                await emit(
                    "max_stake_guardrail",
                    {
                        "session_num": session_num,
                        "attempted_stake": current_stake,
                        "max_stake": cfg.max_stake,
                        "reset_to": cfg.initial_stake,
                    },
                )
                current_stake = cfg.initial_stake

        await asyncio.sleep(1.5)

    final_session_balance = await get_account_balance(client)
    await emit(
        "session_summary",
        {
            "session_num": session_num,
            "initial_balance": initial_session_balance,
            "final_balance": final_session_balance,
            "net_pnl": total_profit_loss,
        },
    )

    return total_profit_loss


async def run_bot(cfg: TradeConfig, emit: Emit) -> None:
    """Entry point used by main.py. Runs sessions per `cfg` until
    cfg.max_sessions is hit, or until this coroutine's task is cancelled
    (client sent {"type": "stop"}), mirroring the old KeyboardInterrupt path.
    """
    client = DerivClient(ws_url=get_ws_url(account_type=cfg.mode))
    await client.connect()
    await emit("connected", {"mode": cfg.mode})

    grand_total_pnl = 0.0
    session_num = 0
    starting_balance = await get_account_balance(client)

    try:
        while cfg.max_sessions is None or session_num < cfg.max_sessions:
            session_num += 1
            session_pnl = await run_session(client, cfg, session_num, emit)
            grand_total_pnl += session_pnl

            running_balance = await get_account_balance(client)
            await emit(
                "cumulative_status",
                {
                    "session_num": session_num,
                    "starting_balance": starting_balance,
                    "current_balance": running_balance,
                    "cumulative_net_pnl": grand_total_pnl,
                },
            )

            session_is_final = session_num == cfg.max_sessions
            if not session_is_final:
                await emit(
                    "inter_session_pause",
                    {"seconds": cfg.inter_session_pause},
                )
                await asyncio.sleep(cfg.inter_session_pause)

    except asyncio.CancelledError:
        await emit("stopped_by_client", {"session_num": session_num})
        raise

    finally:
        final_balance = await get_account_balance(client)
        await emit(
            "shutdown",
            {
                "sessions_run": session_num,
                "starting_balance": starting_balance,
                "final_balance": final_balance,
                "all_time_net_pnl": grand_total_pnl,
            },
        )
        await client.close()
