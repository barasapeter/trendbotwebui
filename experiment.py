"""experiment.py"""

import asyncio
import os
import logging
import sys
import time
import json
from dotenv import load_dotenv
from auth import get_ws_url
from client import DerivClient

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("DerivStreakBot")

# Load environment variables
load_dotenv()
API_TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID") or "1089"

# ==================== CONFIGURATION ====================
SYMBOL = "R_100"  # Volatility 100 Index
STAKE = 1.0  # Trade stake amount
CURRENCY = "USD"  # Account currency
TARGET_STREAK = 4  # Enter on N consecutive ticks in one direction
COOLDOWN_TICKS = 6  # Post-trade cooldown (approx 6 seconds)
MAX_LATENCY_MS = 900  # Skip execution if market feed lag is too high
# =======================================================


class TickStreakTracker:
    def __init__(self, target_streak=4, max_allowed_latency_ms=350):
        self.prices = []
        self.streak = 0  # Positive for UP streak, negative for DOWN streak
        self.target_streak = target_streak
        self.max_latency = max_allowed_latency_ms
        self.clock_drift_warning_triggered = False

    def process_new_tick(self, price, server_epoch):
        # 1. Network Latency Check
        server_epoch_ms = int(server_epoch * 1000)
        local_time_ms = int(time.time() * 1000)
        latency = local_time_ms - server_epoch_ms

        # Trigger warning if PC system time differs significantly from Deriv server
        if abs(latency) > 10000 and not self.clock_drift_warning_triggered:
            logger.warning(
                f"🚨 SYSTEM CLOCK OUT OF SYNC: Your local time differs from the server by {latency/1000:.1f}s. "
                "Synchronize your computer clock via NTP to ensure accurate latency checks!"
            )
            self.clock_drift_warning_triggered = True

        # Skip execution if network is struggling
        if latency > self.max_latency:
            logger.warning(f"⚠️ Skipping tick (High Latency: {latency}ms)")
            return "SKIP_LATENCY"

        # 2. Track Streaks
        if len(self.prices) > 0:
            last_price = self.prices[-1]
            if price > last_price:
                self.streak = self.streak + 1 if self.streak > 0 else 1
            elif price < last_price:
                self.streak = self.streak - 1 if self.streak < 0 else -1
            else:
                self.streak = 0  # Flat tick breaks momentum streak

        self.prices.append(price)
        if len(self.prices) > 20:
            self.prices.pop(0)

        # 3. Output Current Status
        direction_emoji = "📈" if self.streak > 0 else "📉" if self.streak < 0 else "➡️"
        logger.info(
            f"🟢 Price: {price:.3f} | Streak: {self.streak:+d} {direction_emoji} (Latency: {latency}ms)"
        )

        # 4. Generate Signal
        if self.streak >= self.target_streak:
            return "PUT"  # Mean reversion strategy: Overextended Up -> expect Down
        elif self.streak <= -self.target_streak:
            return "CALL"  # Mean reversion strategy: Overextended Down -> expect Up

        return "HOLD"


async def execute_trade_via_proposal(client, contract_type, symbol, stake, currency):
    """
    Executes a trade by requesting a contract proposal first,
    then executing the purchase using the derived proposal ID.
    """
    # Step 1: Request Proposal
    proposal_payload = {
        "proposal": 1,
        "amount": stake,
        "basis": "stake",
        "contract_type": contract_type,
        "currency": currency,
        "duration": 5,
        "duration_unit": "t",
        "underlying_symbol": symbol,  # Corrected key parameter
    }

    logger.info(f"📋 Requesting {contract_type} contract proposal for {symbol}...")
    proposal_res = await client.send(proposal_payload)

    if "error" in proposal_res:
        logger.error(f"❌ Proposal failed: {proposal_res['error'].get('message')}")
        return None

    proposal_data = proposal_res.get("proposal", {})
    proposal_id = proposal_data.get("id")
    payout = proposal_data.get("payout")

    if not proposal_id:
        logger.error("❌ Failed to retrieve Proposal ID.")
        return None

    logger.info(
        f"✨ Proposal received! ID: {proposal_id} | Potential Payout: {payout} {currency}"
    )

    # Step 2: Execute Purchase
    buy_payload = {"buy": proposal_id, "price": stake}

    logger.info(f"🚀 Purchasing contract via proposal {proposal_id}...")
    buy_res = await client.send(buy_payload)

    if "error" in buy_res:
        logger.error(f"❌ Purchase failed: {buy_res['error'].get('message')}")
        return None

    buy_info = buy_res.get("buy", {})
    return buy_info.get("contract_id")


async def check_contract_status(client, contract_id):
    """Monitors trade outcomes on the active on-demand connection by subscribing to it."""
    payload = {
        "proposal_open_contract": 1,
        "contract_id": contract_id,
        "subscribe": 1,
    }
    try:
        logger.info(f"📡 Subscribing to contract status for {contract_id}...")
        await client.subscribe(payload)

        # Read the real-time stream of status updates
        # Includes a safety timeout check to avoid locking up if the connection breaks
        start_time = time.time()
        while time.time() - start_time < 20:
            response = await client.recv()
            if "error" in response:
                logger.warning(
                    f"Could not check status: {response['error'].get('message')}"
                )
                return

            poc = response.get("proposal_open_contract", {})
            if poc:
                status = poc.get("status", "unknown").upper()
                is_sold = poc.get("is_sold")

                # Check if the contract has completed settlement (is_sold is True)
                if is_sold:
                    profit = float(poc.get("profit", 0.0))
                    emoji = (
                        "🏆" if status == "WON" else "❌" if status == "LOST" else "⏳"
                    )
                    logger.info(
                        f"{emoji} CONTRACT {contract_id} RESULT: {status} | Profit: {profit:+.2f} {CURRENCY}"
                    )
                    return  # Settlement parsed, break out of loop

    except Exception as e:
        logger.error(f"Failed tracking status for contract {contract_id}: {e}")


async def handle_trade_execution(signal, symbol, stake, currency):
    """
    Connects to the API on-demand, executes the contract,
    monitors the outcome, and gracefully terminates the session.
    """
    # 1. Fetch a fresh authorized trading URL
    ws_url_trades = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
    trade_client = DerivClient(ws_url_trades)

    try:
        logger.info("🔌 Opening dedicated trading connection...")
        await trade_client.connect()

        # 2. Place trade
        contract_id = await execute_trade_via_proposal(
            trade_client, signal, symbol, stake, currency
        )

        # 3. Track resolution using active subscription channel
        if contract_id:
            await check_contract_status(trade_client, contract_id)

    except Exception as e:
        logger.error(f"❌ Execution failed: {e}", exc_info=True)
    finally:
        logger.info("🔌 Closing dedicated trading connection.")
        # Check if trade_client and trade_client.ws are initialized before closing to prevent AttributeError
        if trade_client and trade_client.ws is not None:
            await trade_client.close()


async def main():
    if not API_TOKEN:
        logger.error("Execution stopped: Missing Token in environment variables.")
        return

    # Obtain permanent streaming connection URL
    ws_url_ticks = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)

    logger.info("Initializing streaming client...")
    tick_client = DerivClient(ws_url_ticks)

    try:
        await tick_client.connect()
        logger.info("Streaming connection successfully established.")

        # Subscribe to continuous live ticks
        logger.info(f"Subscribing to tick stream for {SYMBOL}...")
        await tick_client.ws.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))

        tracker = TickStreakTracker(
            target_streak=TARGET_STREAK, max_allowed_latency_ms=MAX_LATENCY_MS
        )
        cooldown_counter = 0

        logger.info(
            f"Now analyzing market... Awaiting {TARGET_STREAK} tick streak on {SYMBOL}."
        )

        # Core WebSocket streaming loop
        async for message_str in tick_client.ws:
            message = json.loads(message_str)

            if message.get("msg_type") == "tick":
                tick_data = message.get("tick", {})
                price = float(tick_data.get("quote"))
                epoch = float(tick_data.get("epoch"))

                signal = tracker.process_new_tick(price, epoch)

                # Cooldown tracking logic
                if cooldown_counter > 0:
                    cooldown_counter -= 1
                    continue

                if signal in ["CALL", "PUT"]:
                    logger.info(
                        f"🔥 Strike Streak Confirmed! Triggering {signal} order."
                    )

                    # Fire-and-forget: Spins up the execution engine on a separate task thread
                    asyncio.create_task(
                        handle_trade_execution(signal, SYMBOL, STAKE, CURRENCY)
                    )

                    # Reset tracking to prevent double triggers
                    cooldown_counter = COOLDOWN_TICKS
                    tracker.streak = 0

            elif "error" in message:
                logger.error(
                    f"WebSocket incoming error: {message['error'].get('message')}"
                )

    except asyncio.CancelledError:
        logger.info("Bot execution cancelled. Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Critical failure in streaming thread: {e}", exc_info=True)
    finally:
        logger.info("Tearing down active connections...")
        # Check if tick_client and tick_client.ws are initialized before closing to prevent AttributeError
        if tick_client and tick_client.ws is not None:
            await tick_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot manually terminated. Goodbye!")
