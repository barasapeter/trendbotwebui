"""experiment.py with Martingale - Optimized for Instant Execution"""

import asyncio
import os
import logging
import sys
import time
import json
from dotenv import load_dotenv
from auth import get_ws_url
from client import DerivClient


# ==================== TERMINAL COLORS ====================
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    GREEN = "\033[38;5;46m"
    RED = "\033[38;5;196m"
    YELLOW = "\033[38;5;220m"
    CYAN = "\033[38;5;51m"
    BLUE = "\033[38;5;33m"
    MAGENTA = "\033[38;5;201m"
    GREY = "\033[38;5;244m"
    WHITE = "\033[38;5;255m"
    ORANGE = "\033[38;5;208m"

    @staticmethod
    def pl(value):
        """Color a P/L value green (profit), red (loss), or grey (flat)."""
        color = C.GREEN if value > 0 else C.RED if value < 0 else C.GREY
        sign = "+" if value > 0 else ""
        return f"{color}{sign}{value:.2f}{C.RESET}"


class ColorFormatter(logging.Formatter):
    """Custom formatter that tints log lines by level."""

    LEVEL_COLORS = {
        logging.DEBUG: C.GREY,
        logging.INFO: C.WHITE,
        logging.WARNING: C.YELLOW,
        logging.ERROR: C.RED,
        logging.CRITICAL: C.RED + C.BOLD,
    }

    def format(self, record):
        base_color = self.LEVEL_COLORS.get(record.levelno, C.WHITE)
        timestamp = f"{C.GREY}{self.formatTime(record, '%H:%M:%S')}{C.RESET}"
        level = f"{base_color}{record.levelname:<8}{C.RESET}"
        message = record.getMessage()
        return f"{timestamp} {level} {message}"


# Setup logging
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ColorFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger("DerivStreakBot")

# Load environment variables
load_dotenv()
API_TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID") or "1089"

# ==================== CONFIGURATION ====================
SYMBOL = "R_100"  # Volatility 100 Index
BASE_STAKE = 0.35  # Starting/reset trade stake amount
CURRENCY = "USD"  # Account currency
TARGET_STREAK = 4  # Enter on N consecutive ticks in one direction
COOLDOWN_SECONDS = 6  # Post-trade cooldown (6 seconds)
MAX_LATENCY_MS = 1000  # Skip execution if market feed lag is too high

# --- Martingale staking ---
MARTINGALE_ENABLED = True
MARTINGALE_MULTIPLIER = 2.0
# =======================================================


# ==================== SESSION P&L TRACKER ====================
class SessionStats:
    """Tracks running net P&L and win/loss counts for the whole session."""

    def __init__(self):
        self.net_pl = 0.0
        self.wins = 0
        self.losses = 0
        self.trades = 0

    def record(self, profit):
        self.net_pl += profit
        self.trades += 1
        if profit > 0:
            self.wins += 1
        elif profit < 0:
            self.losses += 1

    def summary_line(self):
        win_rate = (self.wins / self.trades * 100) if self.trades else 0.0
        pl_color = C.GREEN if self.net_pl >= 0 else C.RED
        return (
            f"{C.BOLD}📊 SESSION{C.RESET} | Trades: {C.CYAN}{self.trades}{C.RESET} "
            f"| Wins: {C.GREEN}{self.wins}{C.RESET} | Losses: {C.RED}{self.losses}{C.RESET} "
            f"| Win Rate: {C.CYAN}{win_rate:.1f}%{C.RESET} "
            f"| Net P/L: {pl_color}{C.BOLD}{self.net_pl:+.2f} {CURRENCY}{C.RESET}"
        )


stats = SessionStats()
# =======================================================


# ==================== MARTINGALE STAKING ====================
class MartingaleManager:
    def __init__(self, base_stake, multiplier=2.0, enabled=True):
        self.base_stake = base_stake
        self.multiplier = multiplier
        self.enabled = enabled
        self.current_stake = base_stake
        self.step = 0

    def next_stake(self):
        return round(self.current_stake, 2) if self.current_stake < 5000 else 5000

    def record_result(self, won):
        if not self.enabled:
            return

        if won:
            if self.step > 0:
                logger.info(
                    f"{C.GREEN}🔁 Martingale reset{C.RESET} — win recovered the drawdown, "
                    f"back to base stake ({C.BOLD}{self.base_stake} {CURRENCY}{C.RESET})."
                )
            self.current_stake = self.base_stake
            self.step = 0
            return

        self.step += 1
        self.current_stake = round(self.current_stake * self.multiplier, 2)
        logger.info(
            f"{C.ORANGE}📈 Martingale step {self.step}{C.RESET} — "
            f"next stake: {C.ORANGE}{C.BOLD}{self.current_stake} {CURRENCY}{C.RESET}"
        )

    def status_tag(self):
        if not self.enabled:
            return f"{C.GREY}[Flat Stake]{C.RESET}"
        if self.step == 0:
            return f"{C.GREEN}[Base]{C.RESET}"
        return f"{C.ORANGE}[Martingale x{self.step}]{C.RESET}"


martingale = MartingaleManager(
    base_stake=BASE_STAKE,
    multiplier=MARTINGALE_MULTIPLIER,
    enabled=MARTINGALE_ENABLED,
)
stake_lock = asyncio.Lock()
# =======================================================


# ==================== PERSISTENT TRADE MANAGER ====================
class PersistentTradeManager:
    """Manages a single persistent trading connection with instant execution."""

    def __init__(self):
        self.client = None
        self.connected = False
        self.lock = asyncio.Lock()
        self.pending_trades = asyncio.Queue()
        self.executing = False
        self.last_trade_time = 0
        self.cooldown_seconds = COOLDOWN_SECONDS

    async def ensure_connected(self):
        """Ensure the persistent trading connection is active."""
        async with self.lock:
            if not self.connected or self.client is None:
                ws_url = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
                self.client = DerivClient(ws_url)
                await self.client.connect()
                self.connected = True
                logger.info(
                    f"{C.GREEN}✅ Persistent trading connection established.{C.RESET}"
                )
            return self.client

    async def execute_trade_instant(self, signal, stake, symbol, currency):
        """
        Execute a trade with MINIMAL delay - assumes connection is already open.
        """
        client = await self.ensure_connected()

        # Build proposal payload
        proposal_payload = {
            "proposal": 1,
            "amount": stake,
            "basis": "stake",
            "contract_type": signal,
            "currency": currency,
            "duration": 5,
            "duration_unit": "t",
            "underlying_symbol": symbol,
        }

        # Send proposal and buy in rapid succession on the SAME connection
        try:
            # Request proposal
            proposal_res = await client.send(proposal_payload)

            if "error" in proposal_res:
                logger.error(
                    f"❌ Proposal failed: {proposal_res['error'].get('message')}"
                )
                return None

            proposal_id = proposal_res.get("proposal", {}).get("id")
            if not proposal_id:
                logger.error("❌ Failed to retrieve Proposal ID.")
                return None

            # Execute purchase immediately
            buy_payload = {"buy": proposal_id, "price": stake}
            buy_res = await client.send(buy_payload)

            if "error" in buy_res:
                logger.error(f"❌ Purchase failed: {buy_res['error'].get('message')}")
                return None

            contract_id = buy_res.get("buy", {}).get("contract_id")
            logger.info(
                f"✅ Trade executed instantly! Contract: {C.CYAN}{contract_id}{C.RESET}"
            )
            return contract_id

        except Exception as e:
            logger.error(f"❌ Trade execution error: {e}")
            return None

    async def poll_contract_status(self, contract_id):
        """
        Poll for contract status using a single request (no subscription overhead).
        """
        client = await self.ensure_connected()
        start_time = time.time()

        while time.time() - start_time < 25:
            try:
                response = await client.send(
                    {"proposal_open_contract": 1, "contract_id": contract_id}
                )

                if "error" in response:
                    logger.warning(
                        f"Status check failed: {response['error'].get('message')}"
                    )
                    await asyncio.sleep(0.5)
                    continue

                poc = response.get("proposal_open_contract", {})
                if poc.get("is_sold"):
                    status = poc.get("status", "unknown").upper()
                    profit = float(poc.get("profit", 0.0))

                    emoji = (
                        "🏆" if status == "WON" else "❌" if status == "LOST" else "⏳"
                    )
                    status_color = (
                        C.GREEN
                        if status == "WON"
                        else C.RED if status == "LOST" else C.YELLOW
                    )

                    logger.info(
                        f"{emoji} {C.BOLD}CONTRACT {contract_id} RESULT: "
                        f"{status_color}{status}{C.RESET} | "
                        f"Profit: {C.pl(profit)} {CURRENCY}"
                    )
                    return profit

            except Exception as e:
                logger.warning(f"Status poll error: {e}")

            await asyncio.sleep(0.3)  # Poll every 300ms

        logger.warning(f"⏱️ Contract {contract_id} timed out after 25 seconds.")
        return None

    async def process_trade(self, signal, symbol, currency):
        """Process a single trade with instant execution."""
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_trade_time < self.cooldown_seconds:
            logger.info(f"⏳ Cooldown active, skipping trade...")
            return

        self.last_trade_time = current_time

        # Get stake
        async with stake_lock:
            stake = martingale.next_stake()
            tag = martingale.status_tag()

        sig_color = C.GREEN if signal == "CALL" else C.RED
        logger.info(
            f"⚡ {C.BOLD}EXECUTING{C.RESET} {sig_color}{signal}{C.RESET} at "
            f"{C.BOLD}{stake} {CURRENCY}{C.RESET} {tag}"
        )

        # Execute instantly
        contract_id = await self.execute_trade_instant(signal, stake, symbol, currency)

        if not contract_id:
            logger.error(f"❌ Failed to execute {signal} trade.")
            return

        # Poll for result
        profit = await self.poll_contract_status(contract_id)

        if profit is not None:
            stats.record(profit)
            logger.info(stats.summary_line())

            # Update Martingale
            async with stake_lock:
                martingale.record_result(won=profit > 0)
        else:
            logger.error(f"❌ Could not determine outcome for contract {contract_id}")

    async def trade_worker(self):
        """Background worker that processes trades from the queue."""
        while True:
            try:
                signal, symbol, currency = await self.pending_trades.get()
                await self.process_trade(signal, symbol, currency)
            except Exception as e:
                logger.error(f"Trade worker error: {e}")
            finally:
                self.pending_trades.task_done()

    def queue_trade(self, signal, symbol, currency):
        """Queue a trade for execution."""
        self.pending_trades.put_nowait((signal, symbol, currency))


# ==================== TICK STREAK TRACKER ====================
class TickStreakTracker:
    def __init__(self, target_streak=4, max_allowed_latency_ms=350):
        self.prices = []
        self.streak = 0
        self.target_streak = target_streak
        self.max_latency = max_allowed_latency_ms
        self.clock_drift_warning_triggered = False

    def process_new_tick(self, price, server_epoch):
        # 1. Network Latency Check
        server_epoch_ms = int(server_epoch * 1000)
        local_time_ms = int(time.time() * 1000)
        latency = local_time_ms - server_epoch_ms

        if abs(latency) > 10000 and not self.clock_drift_warning_triggered:
            logger.warning(
                f"🚨 {C.YELLOW}SYSTEM CLOCK OUT OF SYNC{C.RESET}: Your local time differs from the "
                f"server by {C.BOLD}{latency/1000:.1f}s{C.RESET}. "
                "Synchronize your computer clock via NTP to ensure accurate latency checks!"
            )
            self.clock_drift_warning_triggered = True

        if latency > self.max_latency:
            logger.warning(
                f"⚠️ Skipping tick ({C.ORANGE}High Latency: {latency}ms{C.RESET})"
            )
            return "SKIP_LATENCY"

        # 2. Track Streaks
        if len(self.prices) > 0:
            last_price = self.prices[-1]
            if price > last_price:
                self.streak = self.streak + 1 if self.streak > 0 else 1
            elif price < last_price:
                self.streak = self.streak - 1 if self.streak < 0 else -1
            else:
                self.streak = 0

        self.prices.append(price)
        if len(self.prices) > 20:
            self.prices.pop(0)

        # 3. Output Current Status
        if self.streak > 0:
            direction_emoji, dir_color = "📈", C.GREEN
        elif self.streak < 0:
            direction_emoji, dir_color = "📉", C.RED
        else:
            direction_emoji, dir_color = "➡️", C.GREY

        streak_meter = self._streak_meter(dir_color)
        latency_color = C.GREEN if latency < self.max_latency * 0.5 else C.YELLOW
        next_stake = martingale.next_stake()

        logger.info(
            f"{dir_color}●{C.RESET} Price: {C.WHITE}{C.BOLD}{price:.3f}{C.RESET}  "
            f"Streak: {dir_color}{self.streak:+d}{C.RESET} {direction_emoji} {streak_meter}  "
            f"{C.GREY}│{C.RESET} Latency: {latency_color}{latency}ms{C.RESET}  "
            f"{C.GREY}│{C.RESET} Next Stake: {C.WHITE}{next_stake} {CURRENCY}{C.RESET} {martingale.status_tag()}  "
            f"{C.GREY}│{C.RESET} {stats.summary_line()}"
        )

        # 4. Generate Signal (INSTANT trigger - no delay)
        if self.streak >= self.target_streak:
            return "PUT"
        elif self.streak <= -self.target_streak:
            return "CALL"

        return "HOLD"

    def _streak_meter(self, dir_color):
        filled = min(abs(self.streak), self.target_streak)
        empty = self.target_streak - filled
        return f"[{dir_color}{'█' * filled}{C.RESET}{C.GREY}{'░' * empty}{C.RESET}]"


# ==================== BANNER ====================
def print_banner():
    mg_line = (
        f"{C.GREY}Martingale:{C.RESET} {C.GREEN}ON{C.RESET} (x{MARTINGALE_MULTIPLIER}, uncapped)"
        if MARTINGALE_ENABLED
        else f"{C.GREY}Martingale:{C.RESET} {C.RED}OFF{C.RESET} (flat stake)"
    )
    banner = f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════════╗
║             🤖  DERIV TICK-STREAK BOT  🤖                  ║
╚══════════════════════════════════════════════════════════╝{C.RESET}
{C.GREY}  Symbol:{C.RESET} {C.WHITE}{SYMBOL}{C.RESET}   {C.GREY}Base Stake:{C.RESET} {C.WHITE}{BASE_STAKE} {CURRENCY}{C.RESET}   {C.GREY}Target Streak:{C.RESET} {C.WHITE}{TARGET_STREAK}{C.RESET}   {C.GREY}Cooldown:{C.RESET} {C.WHITE}{COOLDOWN_SECONDS}s{C.RESET}
  {mg_line}
  {C.GREEN}⚡ OPTIMIZED: Persistent Connection | Instant Execution{C.RESET}
"""
    print(banner)


# ==================== MAIN ====================
async def main():
    if not API_TOKEN:
        logger.error("Execution stopped: Missing Token in environment variables.")
        return

    print_banner()

    # Initialize persistent trade manager
    trade_manager = PersistentTradeManager()

    # Start the background trade worker
    worker_task = asyncio.create_task(trade_manager.trade_worker())
    logger.info("🚀 Trade worker started (persistent connection).")

    # Obtain permanent streaming connection URL
    ws_url_ticks = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
    tick_client = DerivClient(ws_url_ticks)

    try:
        await tick_client.connect()
        logger.info(
            f"{C.GREEN}✅ Streaming connection successfully established.{C.RESET}"
        )

        # Subscribe to continuous live ticks
        logger.info(f"Subscribing to tick stream for {C.CYAN}{SYMBOL}{C.RESET}...")
        await tick_client.ws.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))

        tracker = TickStreakTracker(
            target_streak=TARGET_STREAK, max_allowed_latency_ms=MAX_LATENCY_MS
        )

        # Track signals to prevent duplicate triggers
        last_signal_time = 0
        signal_triggered = False

        logger.info(
            f"👁️ Now analyzing market... Awaiting {C.BOLD}{TARGET_STREAK}{C.RESET} tick streak on {C.CYAN}{SYMBOL}{C.RESET}."
        )

        # Core WebSocket streaming loop
        async for message_str in tick_client.ws:
            message = json.loads(message_str)

            if message.get("msg_type") == "tick":
                tick_data = message.get("tick", {})
                price = float(tick_data.get("quote"))
                epoch = float(tick_data.get("epoch"))

                signal = tracker.process_new_tick(price, epoch)

                # Check cooldown at the tick level
                current_time = time.time()
                if current_time - last_signal_time < COOLDOWN_SECONDS:
                    continue

                if signal in ["CALL", "PUT"]:
                    # Reset streak to prevent duplicate triggers on same streak
                    sig_color = C.GREEN if signal == "CALL" else C.RED
                    logger.info(
                        f"🔥 {C.BOLD}Strike Streak Confirmed!{C.RESET} Triggering {sig_color}{C.BOLD}{signal}{C.RESET} order."
                    )

                    # Queue the trade for instant execution
                    trade_manager.queue_trade(signal, SYMBOL, CURRENCY)

                    # Update cooldown
                    last_signal_time = current_time

                    # Reset streak tracking to prevent double-triggering
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
        logger.info(stats.summary_line())

        # Cancel the worker task
        worker_task.cancel()

        # Close connections
        if tick_client and tick_client.ws is not None:
            await tick_client.close()
        if trade_manager.client and trade_manager.client.ws is not None:
            await trade_manager.client.close()
            logger.info("✅ Persistent trading connection closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot manually terminated. Goodbye!")
        logger.info(stats.summary_line())
