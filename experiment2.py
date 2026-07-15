"""experiment2.py - Fixed Martingale Pre-Fetch with Dual Connections"""

import asyncio
import os
import logging
import sys
import time
import json
from datetime import datetime
from dotenv import load_dotenv
from auth import get_ws_url
from client_experiment2 import DerivClient


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
    PINK = "\033[38;5;205m"
    PURPLE = "\033[38;5;129m"

    @staticmethod
    def pl(value):
        color = C.GREEN if value > 0 else C.RED if value < 0 else C.GREY
        sign = "+" if value > 0 else ""
        return f"{color}{sign}{value:.2f}{C.RESET}"


class ColorFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ct = datetime.fromtimestamp(record.created)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.strftime("%H:%M:%S.%f")[:-3]

    def format(self, record):
        base_color = self.LEVEL_COLORS.get(record.levelno, C.WHITE)
        timestamp = f"{C.GREY}{self.formatTime(record, '%H:%M:%S.%f')[:-3]}{C.RESET}"
        level = f"{base_color}{record.levelname:<8}{C.RESET}"
        message = record.getMessage()
        return f"{timestamp} {level} {message}"


ColorFormatter.LEVEL_COLORS = {
    logging.DEBUG: C.GREY,
    logging.INFO: C.WHITE,
    logging.WARNING: C.YELLOW,
    logging.ERROR: C.RED,
    logging.CRITICAL: C.RED + C.BOLD,
}


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
SYMBOL = "R_100"
BASE_STAKE = 1
CURRENCY = "USD"
TARGET_STREAK = 4
COOLDOWN_SECONDS = 6
MAX_LATENCY_MS = 1000

MARTINGALE_ENABLED = True
MARTINGALE_MULTIPLIER = 2.0

HEARTBEAT_INTERVAL = 15
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY = 2
# =======================================================


# ==================== SESSION P&L TRACKER ====================
class SessionStats:
    def __init__(self):
        self.net_pl = 0.0
        self.wins = 0
        self.losses = 0
        self.trades = 0
        self.start_time = datetime.now()
        self.trade_history = []
        self.pending_trades = {}

    def record(self, profit, contract_id, signal, stake, entry_price, exit_price):
        self.net_pl += profit
        self.trades += 1
        if profit > 0:
            self.wins += 1
        else:
            self.losses += 1

        self.trade_history.append(
            {
                "time": datetime.now().isoformat(),
                "contract_id": contract_id,
                "signal": signal,
                "stake": stake,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "profit": profit,
                "result": "WON" if profit > 0 else "LOST",
            }
        )

    def summary_line(self):
        win_rate = (self.wins / self.trades * 100) if self.trades else 0.0
        pl_color = C.GREEN if self.net_pl >= 0 else C.RED
        active = (
            f" | {C.YELLOW}Active: {len(self.pending_trades)}{C.RESET}"
            if self.pending_trades
            else ""
        )
        return (
            f"{C.BOLD}📊 SESSION{C.RESET} | Trades: {C.CYAN}{self.trades}{C.RESET} "
            f"| Wins: {C.GREEN}{self.wins}{C.RESET} | Losses: {C.RED}{self.losses}{C.RESET} "
            f"| Win Rate: {C.CYAN}{win_rate:.1f}%{C.RESET} "
            f"| Net P/L: {pl_color}{C.BOLD}{self.net_pl:+.2f} {CURRENCY}{C.RESET}{active}"
        )

    def detailed_summary(self):
        if not self.trade_history:
            return "No trades executed."

        lines = [
            f"\n{C.BOLD}{C.CYAN}═══════════════════════════════════════════════════════════{C.RESET}",
            f"{C.BOLD}📊 SESSION DETAILED SUMMARY{C.RESET}",
            f"{C.GREY}Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}",
            f"{C.GREY}Duration: {datetime.now() - self.start_time}{C.RESET}",
            "",
            f"{C.BOLD}Trades:{C.RESET} {self.trades}  {C.GREEN}Wins:{C.RESET} {self.wins}  {C.RED}Losses:{C.RESET} {self.losses}  {C.CYAN}Win Rate:{C.RESET} {(self.wins/self.trades*100):.1f}%",
            f"{C.BOLD}Net P/L:{C.RESET} {C.pl(self.net_pl)} {CURRENCY}",
            "",
            f"{C.BOLD}{C.UNDERLINE}Trade History:{C.RESET}",
        ]

        for i, trade in enumerate(self.trade_history, 1):
            result_color = C.GREEN if trade["result"] == "WON" else C.RED
            lines.append(
                f"  #{i:2d} {trade['time'][11:19]} {trade['signal']:4s} "
                f"Stake: {trade['stake']:5.2f}  Entry: {trade['entry_price']:.3f}  "
                f"Exit: {trade['exit_price']:.3f}  {result_color}{trade['result']:4s}{C.RESET}  "
                f"P/L: {C.pl(trade['profit'])}"
            )

        lines.append(
            f"{C.CYAN}═══════════════════════════════════════════════════════════{C.RESET}"
        )
        return "\n".join(lines)


stats = SessionStats()
# =======================================================


# ==================== MARTINGALE MANAGER ====================
class MartingaleManager:
    def __init__(self, base_stake, multiplier=2.0, enabled=True):
        self.base_stake = base_stake
        self.multiplier = multiplier
        self.enabled = enabled
        self.current_stake = base_stake
        self.step = 0
        self.loss_streak = 0
        self._lock = asyncio.Lock()
        self._pending_stake = None
        self._is_prefetched = False  # Track if we've pre-fetched

    async def get_current_stake(self):
        """Get the current stake without consuming pending."""
        async with self._lock:
            return self.current_stake

    async def next_stake_async(self):
        """Get the next stake - use pending if available, otherwise current."""
        async with self._lock:
            if self._pending_stake is not None:
                stake = self._pending_stake
                self._pending_stake = None
                self._is_prefetched = False
                return round(stake, 2)
            return round(self.current_stake, 2)

    async def pre_fetch_next_stake(self):
        """
        CRITICAL FIX: Pre-fetch the next stake by ACTUALLY updating current_stake.
        This simulates the loss happening NOW so future pre-fetches use the right value.
        """
        async with self._lock:
            if not self.enabled:
                return

            # Calculate next stake (multiply current by multiplier)
            next_stake = round(self.current_stake * self.multiplier, 2)

            # CRITICAL: Update current_stake immediately so future pre-fetches multiply correctly
            self.current_stake = next_stake
            self._pending_stake = next_stake
            self._is_prefetched = True
            self.step += 1
            self.loss_streak += 1

            logger.info(
                f"{C.ORANGE}📈 Martingale pre-fetched step {self.step}{C.RESET} — "
                f"next stake ready: {C.ORANGE}{C.BOLD}{next_stake} {CURRENCY}{C.RESET} "
                f"{C.GREY}(loss streak: {self.loss_streak}){C.RESET}"
            )

    async def record_result_async(self, won):
        """Record result and finalize the martingale state."""
        if not self.enabled:
            return

        async with self._lock:
            if won:
                if self.step > 0 or self._is_prefetched:
                    logger.info(
                        f"{C.GREEN}🔁 Martingale reset{C.RESET} — win recovered the drawdown, "
                        f"back to base stake ({C.BOLD}{self.base_stake} {CURRENCY}{C.RESET})."
                    )
                self.current_stake = self.base_stake
                self.step = 0
                self.loss_streak = 0
                self._pending_stake = None
                self._is_prefetched = False
                return

            # Loss: current_stake was already updated during pre_fetch
            # Just clear pending and log
            self._pending_stake = None
            self._is_prefetched = False
            # current_stake stays as-is (already multiplied)

    def status_tag(self):
        if not self.enabled:
            return f"{C.GREY}[Flat Stake]{C.RESET}"
        if self._is_prefetched or self._pending_stake is not None:
            return f"{C.ORANGE}[Pre-fetched x{self.step}]{C.RESET}"
        if self.step == 0:
            return f"{C.GREEN}[Base]{C.RESET}"
        return f"{C.ORANGE}[Martingale x{self.step}]{C.RESET}"


martingale = MartingaleManager(
    base_stake=BASE_STAKE,
    multiplier=MARTINGALE_MULTIPLIER,
    enabled=MARTINGALE_ENABLED,
)
# =======================================================


# ==================== PERSISTENT TRADE MANAGER ====================
class PersistentTradeManager:
    def __init__(self):
        self.execution_client = None
        self.polling_client = None
        self.lock = asyncio.Lock()
        self.pending_trades = asyncio.Queue()
        self.last_trade_time = 0
        self.cooldown_seconds = COOLDOWN_SECONDS
        self.heartbeat_task = None
        self.reconnect_attempts = 0
        self._is_closing = False
        self._trade_lock = asyncio.Lock()
        self._pending_contracts = {}

    async def _create_client(self, label="client"):
        try:
            ws_url = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
            client = DerivClient(ws_url)
            await client.connect()
            return client
        except Exception as e:
            logger.error(f"{C.RED}❌ Failed to create {label}: {e}{C.RESET}")
            return None

    async def ensure_execution_client(self):
        if self._is_closing:
            return None

        if self.execution_client is None or not self.execution_client.is_connected:
            try:
                if self.execution_client:
                    await self.execution_client.close()
                self.execution_client = await self._create_client("execution")
                if self.execution_client:
                    logger.info(f"{C.GREEN}✅ Execution client ready.{C.RESET}")
            except Exception as e:
                logger.error(f"{C.RED}❌ Execution client failed: {e}{C.RESET}")
                return None

        return self.execution_client

    async def ensure_polling_client(self):
        if self._is_closing:
            return None

        if self.polling_client is None or not self.polling_client.is_connected:
            try:
                if self.polling_client:
                    await self.polling_client.close()
                self.polling_client = await self._create_client("polling")
                if self.polling_client:
                    logger.info(f"{C.GREEN}✅ Polling client ready.{C.RESET}")
            except Exception as e:
                logger.error(f"{C.RED}❌ Polling client failed: {e}{C.RESET}")
                return None

        return self.polling_client

    async def heartbeat(self):
        while not self._is_closing:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if self._is_closing:
                break
            try:
                if self.execution_client and self.execution_client.ws:
                    await self.execution_client.ping()
                if self.polling_client and self.polling_client.ws:
                    await self.polling_client.ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    f"{C.YELLOW}⚠️ Heartbeat warning: {str(e)[:50]}{C.RESET}"
                )

    async def execute_trade_instant(self, signal, stake, symbol, currency):
        start_time = time.time()

        client = await self.ensure_execution_client()
        if client is None:
            return None, None

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

        try:
            proposal_start = time.time()
            proposal_res = await client.send(proposal_payload)
            proposal_time = (time.time() - proposal_start) * 1000

            if "error" in proposal_res:
                logger.error(
                    f"{C.RED}❌ Proposal failed: {proposal_res['error'].get('message')}{C.RESET}"
                )
                return None, None

            proposal_data = proposal_res.get("proposal", {})
            proposal_id = proposal_data.get("id")

            entry_price = proposal_data.get("entry_spot")
            if entry_price is None:
                entry_price = proposal_data.get("spot")
            if entry_price is None:
                entry_price = proposal_data.get("quote")
            if entry_price is None:
                entry_price = 0.0

            if not proposal_id:
                return None, None

            buy_start = time.time()
            buy_payload = {"buy": proposal_id, "price": stake}
            buy_res = await client.send(buy_payload)
            buy_time = (time.time() - buy_start) * 1000

            if "error" in buy_res:
                logger.error(
                    f"{C.RED}❌ Purchase failed: {buy_res['error'].get('message')}{C.RESET}"
                )
                return None, None

            contract_id = buy_res.get("buy", {}).get("contract_id")
            total_time = (time.time() - start_time) * 1000

            logger.info(
                f"{C.GREEN}✅ Trade executed!{C.RESET} Contract: {C.CYAN}{contract_id}{C.RESET} "
                f"{C.GREY}| Entry: {C.WHITE}{entry_price:.3f}{C.RESET} "
                f"{C.GREY}| Latency: Proposal {proposal_time:.0f}ms + Buy {buy_time:.0f}ms = {total_time:.0f}ms{C.RESET}"
            )

            return contract_id, entry_price

        except Exception as e:
            logger.error(f"{C.RED}❌ Trade execution error: {e}{C.RESET}")
            return None, None

    async def poll_contract_status(self, contract_id):
        client = await self.ensure_polling_client()
        if client is None:
            return None, None

        start_time = time.time()
        poll_count = 0

        while time.time() - start_time < 25:
            if self._is_closing:
                return None, None
            try:
                response = await client.send(
                    {"proposal_open_contract": 1, "contract_id": contract_id}
                )
                poll_count += 1

                if "error" in response:
                    await asyncio.sleep(0.3)
                    continue

                poc = response.get("proposal_open_contract", {})
                if poc.get("is_sold"):
                    status = poc.get("status", "unknown").upper()
                    profit = float(poc.get("profit", 0.0))
                    exit_price = float(poc.get("exit_spot", 0.0))

                    emoji = (
                        "🏆" if status == "WON" else "❌" if status == "LOST" else "⏳"
                    )
                    status_color = (
                        C.GREEN
                        if status == "WON"
                        else C.RED if status == "LOST" else C.YELLOW
                    )

                    logger.info(
                        f"{emoji} {C.BOLD}CONTRACT {contract_id} RESULT:{C.RESET} "
                        f"{status_color}{status}{C.RESET} {C.GREY}|{C.RESET} "
                        f"Exit: {C.WHITE}{exit_price:.3f}{C.RESET} {C.GREY}|{C.RESET} "
                        f"Profit: {C.pl(profit)} {CURRENCY} {C.GREY}(polls: {poll_count}){C.RESET}"
                    )
                    return profit, exit_price

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"{C.YELLOW}⚠️ Status poll error: {e}{C.RESET}")

            await asyncio.sleep(0.3)

        logger.warning(
            f"{C.YELLOW}⏱️ Contract {contract_id} timed out after 25 seconds.{C.RESET}"
        )
        return None, None

    async def process_trade(self, signal, symbol, currency):
        if self._is_closing:
            return

        current_time = time.time()
        if current_time - self.last_trade_time < self.cooldown_seconds:
            remaining = self.cooldown_seconds - (current_time - self.last_trade_time)
            logger.info(
                f"{C.GREY}⏳ Cooldown active ({remaining:.1f}s remaining){C.RESET}"
            )
            return

        # Get stake - this will use pending if available, otherwise current
        stake = await martingale.next_stake_async()

        async with self._trade_lock:
            self.last_trade_time = time.time()

            sig_color = C.GREEN if signal == "CALL" else C.RED
            logger.info(
                f"{C.PURPLE}⚡ EXECUTING{C.RESET} {sig_color}{signal}{C.RESET} at "
                f"{C.BOLD}{stake} {CURRENCY}{C.RESET} {martingale.status_tag()}"
            )

            contract_id, entry_price = await self.execute_trade_instant(
                signal, stake, symbol, currency
            )

            if not contract_id:
                logger.error(f"{C.RED}❌ Failed to execute {signal} trade.{C.RESET}")
                return

            stats.pending_trades[contract_id] = {
                "signal": signal,
                "stake": stake,
                "entry": entry_price,
            }

            # CRITICAL FIX: Pre-fetch the NEXT stake immediately
            # This updates current_stake so future pre-fetches multiply correctly
            await martingale.pre_fetch_next_stake()

            # Resolve in background
            asyncio.create_task(
                self._resolve_trade(contract_id, signal, stake, entry_price)
            )

    async def _resolve_trade(self, contract_id, signal, stake, entry_price):
        profit, exit_price = await self.poll_contract_status(contract_id)

        stats.pending_trades.pop(contract_id, None)

        if profit is not None:
            stats.record(profit, contract_id, signal, stake, entry_price, exit_price)
            logger.info(stats.summary_line())

            # Record result - this will reset or confirm the martingale state
            await martingale.record_result_async(won=profit > 0)
        else:
            logger.error(
                f"{C.RED}❌ Could not determine outcome for contract {contract_id}{C.RESET}"
            )

    async def trade_worker(self):
        self.heartbeat_task = asyncio.create_task(self.heartbeat())
        logger.info(
            f"{C.GREEN}💓 Heartbeat started (interval: {HEARTBEAT_INTERVAL}s){C.RESET}"
        )

        while not self._is_closing:
            try:
                signal, symbol, currency = await self.pending_trades.get()
                await self.process_trade(signal, symbol, currency)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"{C.RED}❌ Trade worker error: {e}{C.RESET}")
                import traceback

                traceback.print_exc()
            finally:
                self.pending_trades.task_done()

    def queue_trade(self, signal, symbol, currency):
        if self._is_closing:
            return
        self.pending_trades.put_nowait((signal, symbol, currency))

    async def close(self):
        self._is_closing = True

        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except Exception:
                pass

        if self.execution_client:
            try:
                await self.execution_client.close()
                logger.info(f"{C.GREY}🔌 Execution connection closed.{C.RESET}")
            except Exception:
                pass

        if self.polling_client:
            try:
                await self.polling_client.close()
                logger.info(f"{C.GREY}🔌 Polling connection closed.{C.RESET}")
            except Exception:
                pass


# ==================== TICK STREAK TRACKER ====================
class TickStreakTracker:
    def __init__(self, target_streak=4, max_allowed_latency_ms=350):
        self.prices = []
        self.timestamps = []
        self.streak = 0
        self.target_streak = target_streak
        self.max_latency = max_allowed_latency_ms
        self.clock_drift_warning_triggered = False
        self.last_signal_time = 0
        self.signal_cooldown = 1.0

    def process_new_tick(self, price, server_epoch):
        server_epoch_ms = int(server_epoch * 1000)
        local_time_ms = int(time.time() * 1000)
        latency = local_time_ms - server_epoch_ms

        if abs(latency) > 10000 and not self.clock_drift_warning_triggered:
            logger.warning(
                f"🚨 {C.YELLOW}SYSTEM CLOCK OUT OF SYNC{C.RESET}: Your local time differs from the "
                f"server by {C.BOLD}{latency/1000:.1f}s{C.RESET}."
            )
            self.clock_drift_warning_triggered = True

        if latency > self.max_latency:
            logger.warning(
                f"{C.YELLOW}⚠️ Skipping tick ({C.ORANGE}High Latency: {latency}ms{C.RESET})"
            )
            return "SKIP_LATENCY"

        if len(self.prices) > 0:
            last_price = self.prices[-1]
            if price > last_price:
                self.streak = self.streak + 1 if self.streak > 0 else 1
            elif price < last_price:
                self.streak = self.streak - 1 if self.streak < 0 else -1
            else:
                self.streak = 0

        self.prices.append(price)
        self.timestamps.append(time.time())
        if len(self.prices) > 20:
            self.prices.pop(0)
            self.timestamps.pop(0)

        if self.streak > 0:
            direction_emoji, dir_color = "📈", C.GREEN
        elif self.streak < 0:
            direction_emoji, dir_color = "📉", C.RED
        else:
            direction_emoji, dir_color = "➡️", C.GREY

        streak_meter = self._streak_meter(dir_color)
        latency_color = C.GREEN if latency < self.max_latency * 0.5 else C.YELLOW

        tick_freq = "N/A"
        if len(self.timestamps) > 1:
            avg_interval = (self.timestamps[-1] - self.timestamps[0]) / (
                len(self.timestamps) - 1
            )
            tick_freq = f"{avg_interval*1000:.0f}ms"

        # Get current stake for display
        stake = martingale.current_stake
        if martingale._pending_stake is not None:
            stake = martingale._pending_stake

        logger.info(
            f"{dir_color}●{C.RESET} Price: {C.WHITE}{C.BOLD}{price:.3f}{C.RESET}  "
            f"Streak: {dir_color}{self.streak:+d}{C.RESET} {direction_emoji} {streak_meter}  "
            f"{C.GREY}│{C.RESET} Latency: {latency_color}{latency}ms{C.RESET} "
            f"{C.GREY}({tick_freq}){C.RESET}  "
            f"{C.GREY}│{C.RESET} Next Stake: {C.WHITE}{stake:.2f} {CURRENCY}{C.RESET} {martingale.status_tag()}  "
            f"{C.GREY}│{C.RESET} {stats.summary_line()}"
        )

        current_time = time.time()
        if current_time - self.last_signal_time < self.signal_cooldown:
            return "HOLD"

        if self.streak >= self.target_streak:
            self.last_signal_time = current_time
            return "PUT"
        elif self.streak <= -self.target_streak:
            self.last_signal_time = current_time
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
  {C.GREEN}⚡ FIXED: Martingale Pre-Fetch | Dual Connections | Instant Execution{C.RESET}
  {C.GREY}💓 Heartbeat: {HEARTBEAT_INTERVAL}s | Max Reconnect: {MAX_RECONNECT_ATTEMPTS}{C.RESET}
"""
    print(banner)


# ==================== MAIN ====================
async def main():
    if not API_TOKEN:
        logger.error("Execution stopped: Missing Token in environment variables.")
        return

    print_banner()
    logger.info(
        f"{C.GREY}🚀 Starting bot at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}"
    )

    trade_manager = PersistentTradeManager()

    logger.info("🔌 Pre-connecting trading connections...")
    await trade_manager.ensure_execution_client()
    await trade_manager.ensure_polling_client()
    logger.info(f"{C.GREEN}✅ Trading connections ready.{C.RESET}")

    worker_task = asyncio.create_task(trade_manager.trade_worker())
    logger.info("🚀 Trade worker started.")

    ws_url_ticks = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
    tick_client = DerivClient(ws_url_ticks)

    try:
        await tick_client.connect()
        logger.info(
            f"{C.GREEN}✅ Streaming connection successfully established.{C.RESET}"
        )

        logger.info(f"Subscribing to tick stream for {C.CYAN}{SYMBOL}{C.RESET}...")
        await tick_client.ws.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))

        tracker = TickStreakTracker(
            target_streak=TARGET_STREAK, max_allowed_latency_ms=MAX_LATENCY_MS
        )

        last_signal_time = 0

        logger.info(
            f"{C.CYAN}👁️ Now analyzing market... Awaiting {C.BOLD}{TARGET_STREAK}{C.RESET} tick streak on {C.CYAN}{SYMBOL}{C.RESET}."
        )

        async for message_str in tick_client.ws:
            message = json.loads(message_str)

            if message.get("msg_type") == "tick":
                tick_data = message.get("tick", {})
                price = float(tick_data.get("quote"))
                epoch = float(tick_data.get("epoch"))

                signal = tracker.process_new_tick(price, epoch)

                current_time = time.time()
                if current_time - last_signal_time < COOLDOWN_SECONDS:
                    continue

                if signal in ["CALL", "PUT"]:
                    sig_color = C.GREEN if signal == "CALL" else C.RED
                    logger.info(
                        f"{C.YELLOW}🔥 Strike Streak Confirmed!{C.RESET} Triggering {sig_color}{C.BOLD}{signal}{C.RESET} order at price {C.WHITE}{price:.3f}{C.RESET}"
                    )

                    trade_manager.queue_trade(signal, SYMBOL, CURRENCY)
                    last_signal_time = current_time
                    tracker.streak = 0

            elif "error" in message:
                logger.error(
                    f"{C.RED}❌ WebSocket incoming error: {message['error'].get('message')}{C.RESET}"
                )

    except asyncio.CancelledError:
        logger.info("Bot execution cancelled. Shutting down gracefully...")
    except Exception as e:
        logger.error(f"{C.RED}❌ Critical failure: {e}{C.RESET}", exc_info=True)
    finally:
        logger.info("Tearing down active connections...")
        logger.info(stats.detailed_summary())

        worker_task.cancel()
        try:
            await worker_task
        except Exception:
            pass

        if tick_client and tick_client.ws is not None:
            await tick_client.close()

        await trade_manager.close()
        logger.info(
            f"{C.GREY}🛑 Bot stopped at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}"
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot manually terminated. Goodbye!")
        logger.info(stats.detailed_summary())
