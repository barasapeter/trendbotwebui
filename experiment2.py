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
    """Custom formatter that tints log lines by level, keeping message content
    (which may already carry its own ANSI colors) untouched."""

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
BASE_STAKE = 1.0  # Starting/reset trade stake amount
CURRENCY = "USD"  # Account currency
TARGET_STREAK = 4  # Enter on N consecutive ticks in one direction
COOLDOWN_TICKS = 6  # Post-trade cooldown (approx 6 seconds)
MAX_LATENCY_MS = 900  # Skip execution if market feed lag is too high

# --- Martingale staking ---
MARTINGALE_ENABLED = True  # Set False to trade flat BASE_STAKE every time
MARTINGALE_MULTIPLIER = 2.0  # Stake multiplier applied after each loss
MAX_MARTINGALE_STEPS = (
    5  # Safety cap: resets to BASE_STAKE after this many consecutive losses
)
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
    """
    Tracks the current stake based on a Martingale progression:
    on a loss, the next stake is multiplied up; on a win (or after
    hitting the step cap), it resets back to the base stake.
    """

    def __init__(self, base_stake, multiplier=2.0, max_steps=5, enabled=True):
        self.base_stake = base_stake
        self.multiplier = multiplier
        self.max_steps = max_steps
        self.enabled = enabled
        self.current_stake = base_stake
        self.step = 0

    def next_stake(self):
        """Stake to use for the upcoming trade."""
        return round(self.current_stake, 2)

    def record_result(self, won):
        """Update the progression after a contract settles."""
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

        # Loss: escalate the stake
        self.step += 1
        if self.step >= self.max_steps:
            logger.warning(
                f"{C.YELLOW}⚠️ Max Martingale steps reached ({self.max_steps}).{C.RESET} "
                f"Resetting to base stake to cap risk."
            )
            self.current_stake = self.base_stake
            self.step = 0
        else:
            self.current_stake = round(self.current_stake * self.multiplier, 2)
            logger.info(
                f"{C.ORANGE}📈 Martingale step {self.step}/{self.max_steps}{C.RESET} — "
                f"next stake: {C.ORANGE}{C.BOLD}{self.current_stake} {CURRENCY}{C.RESET}"
            )

    def status_tag(self):
        """Short colored tag showing where we are in the progression."""
        if not self.enabled:
            return f"{C.GREY}[Flat Stake]{C.RESET}"
        if self.step == 0:
            return f"{C.GREEN}[Base]{C.RESET}"
        return f"{C.ORANGE}[Martingale x{self.step}]{C.RESET}"


martingale = MartingaleManager(
    base_stake=BASE_STAKE,
    multiplier=MARTINGALE_MULTIPLIER,
    max_steps=MAX_MARTINGALE_STEPS,
    enabled=MARTINGALE_ENABLED,
)
# Guards stake reads/updates since trades can fire as overlapping async tasks
stake_lock = asyncio.Lock()
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
                f"🚨 {C.YELLOW}SYSTEM CLOCK OUT OF SYNC{C.RESET}: Your local time differs from the "
                f"server by {C.BOLD}{latency/1000:.1f}s{C.RESET}. "
                "Synchronize your computer clock via NTP to ensure accurate latency checks!"
            )
            self.clock_drift_warning_triggered = True

        # Skip execution if network is struggling
        if latency > self.max_latency:
            logger.warning(
                f"⚠️  Skipping tick ({C.ORANGE}High Latency: {latency}ms{C.RESET})"
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
                self.streak = 0  # Flat tick breaks momentum streak

        self.prices.append(price)
        if len(self.prices) > 20:
            self.prices.pop(0)

        # 3. Output Current Status (dope streak meter + colored direction)
        if self.streak > 0:
            direction_emoji, dir_color = "📈", C.GREEN
        elif self.streak < 0:
            direction_emoji, dir_color = "📉", C.RED
        else:
            direction_emoji, dir_color = "➡️", C.GREY

        streak_meter = self._streak_meter(dir_color)
        latency_color = C.GREEN if latency < self.max_latency * 0.5 else C.YELLOW

        logger.info(
            f"{dir_color}●{C.RESET} Price: {C.WHITE}{C.BOLD}{price:.3f}{C.RESET}  "
            f"Streak: {dir_color}{self.streak:+d}{C.RESET} {direction_emoji} {streak_meter}  "
            f"{C.GREY}│{C.RESET} Latency: {latency_color}{latency}ms{C.RESET}  "
            f"{C.GREY}│{C.RESET} Next Stake: {C.WHITE}{martingale.next_stake()} {CURRENCY}{C.RESET} {martingale.status_tag()}  "
            f"{C.GREY}│{C.RESET} {stats.summary_line()}"
        )

        # 4. Generate Signal
        if self.streak >= self.target_streak:
            return "PUT"  # Mean reversion strategy: Overextended Up -> expect Down
        elif self.streak <= -self.target_streak:
            return "CALL"  # Mean reversion strategy: Overextended Down -> expect Up

        return "HOLD"

    def _streak_meter(self, dir_color):
        """Renders a small block meter showing streak progress toward target."""
        filled = min(abs(self.streak), self.target_streak)
        empty = self.target_streak - filled
        return f"[{dir_color}{'█' * filled}{C.RESET}{C.GREY}{'░' * empty}{C.RESET}]"


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

    type_color = C.RED if contract_type == "PUT" else C.GREEN
    logger.info(
        f"📋 Requesting {type_color}{C.BOLD}{contract_type}{C.RESET} contract proposal for {C.CYAN}{symbol}{C.RESET}..."
    )
    proposal_res = await client.send(proposal_payload)

    if "error" in proposal_res:
        logger.error(
            f"❌ Proposal failed: {C.RED}{proposal_res['error'].get('message')}{C.RESET}"
        )
        return None

    proposal_data = proposal_res.get("proposal", {})
    proposal_id = proposal_data.get("id")
    payout = proposal_data.get("payout")

    if not proposal_id:
        logger.error("❌ Failed to retrieve Proposal ID.")
        return None

    logger.info(
        f"✨ Proposal received! ID: {C.CYAN}{proposal_id}{C.RESET} | Potential Payout: {C.GREEN}{payout} {currency}{C.RESET}"
    )

    # Step 2: Execute Purchase
    buy_payload = {"buy": proposal_id, "price": stake}

    logger.info(
        f"🚀 Purchasing contract via proposal {C.CYAN}{proposal_id}{C.RESET}..."
    )
    buy_res = await client.send(buy_payload)

    if "error" in buy_res:
        logger.error(
            f"❌ Purchase failed: {C.RED}{buy_res['error'].get('message')}{C.RESET}"
        )
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
        logger.info(
            f"📡 Subscribing to contract status for {C.CYAN}{contract_id}{C.RESET}..."
        )
        await client.subscribe(payload)

        # Read the real-time stream of status updates
        # Includes a safety timeout check to avoid locking up if the connection breaks
        start_time = time.time()
        while time.time() - start_time < 20:
            response = await client.recv()
            if "error" in response:
                logger.warning(
                    f"Could not check status: {C.YELLOW}{response['error'].get('message')}{C.RESET}"
                )
                return None

            poc = response.get("proposal_open_contract", {})
            if poc:
                status = poc.get("status", "unknown").upper()
                is_sold = poc.get("is_sold")

                # Check if the contract has completed settlement (is_sold is True)
                if is_sold:
                    profit = float(poc.get("profit", 0.0))

                    # Update running net P&L for the session
                    stats.record(profit)

                    if status == "WON":
                        emoji, status_color = "🏆", C.GREEN
                    elif status == "LOST":
                        emoji, status_color = "❌", C.RED
                    else:
                        emoji, status_color = "⏳", C.YELLOW

                    logger.info(
                        f"{emoji} {C.BOLD}CONTRACT {contract_id} RESULT: "
                        f"{status_color}{status}{C.RESET}{C.BOLD}{C.RESET} | "
                        f"Profit: {C.pl(profit)} {CURRENCY}"
                    )
                    logger.info(stats.summary_line())
                    return profit  # Settlement parsed, hand profit back to caller

    except Exception as e:
        logger.error(f"Failed tracking status for contract {contract_id}: {e}")

    return None


async def handle_trade_execution(signal, symbol, currency):
    """
    Connects to the API on-demand, executes the contract at the current
    Martingale-adjusted stake, monitors the outcome, updates the Martingale
    progression, and gracefully terminates the session.
    """
    # 1. Fetch a fresh authorized trading URL
    ws_url_trades = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
    trade_client = DerivClient(ws_url_trades)

    try:
        # Lock stake selection so overlapping trades can't race on the same step
        async with stake_lock:
            stake = martingale.next_stake()
            tag = martingale.status_tag()

        logger.info(
            f"🔌 {C.BLUE}Opening dedicated trading connection...{C.RESET} "
            f"{C.GREY}|{C.RESET} Stake: {C.BOLD}{stake} {currency}{C.RESET} {tag}"
        )
        await trade_client.connect()

        # 2. Place trade at the Martingale-adjusted stake
        contract_id = await execute_trade_via_proposal(
            trade_client, signal, symbol, stake, currency
        )

        # 3. Track resolution using active subscription channel
        if contract_id:
            profit = await check_contract_status(trade_client, contract_id)

            # 4. Feed the outcome back into the Martingale progression
            if profit is not None:
                async with stake_lock:
                    martingale.record_result(won=profit > 0)

    except Exception as e:
        logger.error(f"❌ Execution failed: {e}", exc_info=True)
    finally:
        logger.info(f"🔌 {C.GREY}Closing dedicated trading connection.{C.RESET}")
        # Check if trade_client and trade_client.ws are initialized before closing to prevent AttributeError
        if trade_client and trade_client.ws is not None:
            await trade_client.close()


def print_banner():
    mg_line = (
        f"{C.GREY}Martingale:{C.RESET} {C.GREEN}ON{C.RESET} (x{MARTINGALE_MULTIPLIER}, max {MAX_MARTINGALE_STEPS} steps)"
        if MARTINGALE_ENABLED
        else f"{C.GREY}Martingale:{C.RESET} {C.RED}OFF{C.RESET} (flat stake)"
    )
    banner = f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════════╗
║             🤖  DERIV TICK-STREAK BOT  🤖                  ║
╚══════════════════════════════════════════════════════════╝{C.RESET}
{C.GREY}  Symbol:{C.RESET} {C.WHITE}{SYMBOL}{C.RESET}   {C.GREY}Base Stake:{C.RESET} {C.WHITE}{BASE_STAKE} {CURRENCY}{C.RESET}   {C.GREY}Target Streak:{C.RESET} {C.WHITE}{TARGET_STREAK}{C.RESET}   {C.GREY}Cooldown:{C.RESET} {C.WHITE}{COOLDOWN_TICKS} ticks{C.RESET}
  {mg_line}
"""
    print(banner)


async def main():
    if not API_TOKEN:
        logger.error("Execution stopped: Missing Token in environment variables.")
        return

    print_banner()

    # Obtain permanent streaming connection URL
    ws_url_ticks = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)

    logger.info("Initializing streaming client...")
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
        cooldown_counter = 0

        logger.info(
            f"👁️  Now analyzing market... Awaiting {C.BOLD}{TARGET_STREAK}{C.RESET} tick streak on {C.CYAN}{SYMBOL}{C.RESET}."
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
                    sig_color = C.GREEN if signal == "CALL" else C.RED
                    logger.info(
                        f"🔥 {C.BOLD}Strike Streak Confirmed!{C.RESET} Triggering {sig_color}{C.BOLD}{signal}{C.RESET} order."
                    )

                    # Fire-and-forget: Spins up the execution engine on a separate task thread
                    asyncio.create_task(
                        handle_trade_execution(signal, SYMBOL, CURRENCY)
                    )

                    # Reset tracking to prevent double triggers
                    cooldown_counter = COOLDOWN_TICKS
                    tracker.streak = 0

            elif "error" in message:
                logger.error(
                    f"WebSocket incoming error: {C.RED}{message['error'].get('message')}{C.RESET}"
                )

    except asyncio.CancelledError:
        logger.info("Bot execution cancelled. Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Critical failure in streaming thread: {e}", exc_info=True)
    finally:
        logger.info("Tearing down active connections...")
        logger.info(stats.summary_line())
        # Check if tick_client and tick_client.ws are initialized before closing to prevent AttributeError
        if tick_client and tick_client.ws is not None:
            await tick_client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot manually terminated. Goodbye!")
        logger.info(stats.summary_line())
