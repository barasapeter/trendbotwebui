"""experiment.py with Martingale - Optimized with Connection Health & Enhanced Logging"""

import asyncio
import os
import logging
import sys
import time
import json
from datetime import datetime
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
    PINK = "\033[38;5;205m"
    PURPLE = "\033[38;5;129m"

    @staticmethod
    def pl(value):
        """Color a P/L value green (profit), red (loss), or grey (flat)."""
        color = C.GREEN if value > 0 else C.RED if value < 0 else C.GREY
        sign = "+" if value > 0 else ""
        return f"{color}{sign}{value:.2f}{C.RESET}"


class ColorFormatter(logging.Formatter):
    """Custom formatter that tints log lines by level with microsecond precision."""
    
    def formatTime(self, record, datefmt=None):
        """Override to support microseconds using datetime."""
        ct = datetime.fromtimestamp(record.created)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.strftime("%H:%M:%S.%f")[:-3]  # Show milliseconds

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
SYMBOL = "R_100"  # Volatility 100 Index
BASE_STAKE = 0.35  # Starting/reset trade stake amount
CURRENCY = "USD"  # Account currency
TARGET_STREAK = 4  # Enter on N consecutive ticks in one direction
COOLDOWN_SECONDS = 6  # Post-trade cooldown (6 seconds)
MAX_LATENCY_MS = 1000  # Skip execution if market feed lag is too high

# --- Martingale staking ---
MARTINGALE_ENABLED = True
MARTINGALE_MULTIPLIER = 2.0

# --- Connection Health ---
HEARTBEAT_INTERVAL = 15  # Check connection every 15 seconds
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY = 2  # Seconds between reconnect attempts
# =======================================================


# ==================== SESSION P&L TRACKER ====================
class SessionStats:
    """Tracks running net P&L and win/loss counts for the whole session."""

    def __init__(self):
        self.net_pl = 0.0
        self.wins = 0
        self.losses = 0
        self.trades = 0
        self.start_time = datetime.now()
        self.trade_history = []

    def record(self, profit, contract_id, signal, stake, entry_price, exit_price):
        self.net_pl += profit
        self.trades += 1
        if profit > 0:
            self.wins += 1
        else:
            self.losses += 1
        
        # Store trade for analysis
        self.trade_history.append({
            "time": datetime.now().isoformat(),
            "contract_id": contract_id,
            "signal": signal,
            "stake": stake,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "profit": profit,
            "result": "WON" if profit > 0 else "LOST"
        })

    def summary_line(self):
        win_rate = (self.wins / self.trades * 100) if self.trades else 0.0
        pl_color = C.GREEN if self.net_pl >= 0 else C.RED
        return (
            f"{C.BOLD}📊 SESSION{C.RESET} | Trades: {C.CYAN}{self.trades}{C.RESET} "
            f"| Wins: {C.GREEN}{self.wins}{C.RESET} | Losses: {C.RED}{self.losses}{C.RESET} "
            f"| Win Rate: {C.CYAN}{win_rate:.1f}%{C.RESET} "
            f"| Net P/L: {pl_color}{C.BOLD}{self.net_pl:+.2f} {CURRENCY}{C.RESET}"
        )

    def detailed_summary(self):
        """Generate a detailed summary with all trades."""
        if not self.trade_history:
            return "No trades executed."
        
        lines = [
            f"\n{C.BOLD}{C.CYAN}═══════════════════════════════════════════════════════════{C.RESET}",
            f"{C.BOLD}📊 SESSION DETAILED SUMMARY{C.RESET}",
            f"{C.GREY}Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}",
            f"{C.GREY}Duration: {datetime.now() - self.start_time}{C.RESET}",
            f"",
            f"{C.BOLD}Trades:{C.RESET} {self.trades}  {C.GREEN}Wins:{C.RESET} {self.wins}  {C.RED}Losses:{C.RESET} {self.losses}  {C.CYAN}Win Rate:{C.RESET} {(self.wins/self.trades*100):.1f}%",
            f"{C.BOLD}Net P/L:{C.RESET} {C.pl(self.net_pl)} {CURRENCY}",
            f"",
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
        
        lines.append(f"{C.CYAN}═══════════════════════════════════════════════════════════{C.RESET}")
        return "\n".join(lines)


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
        self.loss_streak = 0

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
            self.loss_streak = 0
            return

        self.step += 1
        self.loss_streak += 1
        self.current_stake = round(self.current_stake * self.multiplier, 2)
        logger.info(
            f"{C.ORANGE}📈 Martingale step {self.step}{C.RESET} — "
            f"next stake: {C.ORANGE}{C.BOLD}{self.current_stake} {CURRENCY}{C.RESET} "
            f"{C.GREY}(loss streak: {self.loss_streak}){C.RESET}"
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
    """Manages a single persistent trading connection with health monitoring."""
    
    def __init__(self):
        self.client = None
        self.connected = False
        self.lock = asyncio.Lock()
        self.pending_trades = asyncio.Queue()
        self.executing = False
        self.last_trade_time = 0
        self.cooldown_seconds = COOLDOWN_SECONDS
        self.heartbeat_task = None
        self.reconnect_attempts = 0
        self.last_heartbeat = 0
        self.connection_id = id(self)  # Unique ID for this connection
        self._is_closing = False
        
    async def ensure_connected(self):
        """Ensure the persistent trading connection is active with health check."""
        if self._is_closing:
            return None
            
        async with self.lock:
            # Check if connection is actually alive
            is_alive = False
            
            if self.client and self.client.ws is not None:
                try:
                    # Send a ping to test connection
                    await self.client.ws.ping()
                    is_alive = True
                    self.reconnect_attempts = 0  # Reset attempts on successful ping
                except Exception as e:
                    logger.warning(
                        f"{C.YELLOW}⚠️ Connection health check failed: {str(e)[:50]}{C.RESET}"
                    )
                    is_alive = False
            
            # If connection is dead, reconnect
            if not is_alive or self.client is None:
                if self.reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                    logger.error(
                        f"{C.RED}❌ Max reconnect attempts ({MAX_RECONNECT_ATTEMPTS}) reached. Giving up.{C.RESET}"
                    )
                    return None
                
                self.reconnect_attempts += 1
                logger.warning(
                    f"{C.YELLOW}🔄 Reconnecting... Attempt {self.reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS}{C.RESET}"
                )
                
                # Close old connection if it exists
                if self.client and self.client.ws is not None:
                    try:
                        await self.client.close()
                    except:
                        pass
                
                # Wait before reconnecting
                await asyncio.sleep(RECONNECT_DELAY)
                
                # Create new connection
                try:
                    ws_url = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
                    self.client = DerivClient(ws_url)
                    await self.client.connect()
                    self.connected = True
                    self.reconnect_attempts = 0
                    logger.info(f"{C.GREEN}✅ Persistent trading connection re-established.{C.RESET}")
                except Exception as e:
                    logger.error(f"{C.RED}❌ Reconnect failed: {e}{C.RESET}")
                    return None
            
            return self.client
    
    async def heartbeat(self):
        """Periodically check if the connection is alive."""
        while not self._is_closing:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if self._is_closing:
                break
            try:
                if self.client and self.client.ws is not None:
                    # Send a ping to check connection
                    await self.client.ws.ping()
                    self.last_heartbeat = time.time()
                    logger.debug(f"{C.GREY}💓 Heartbeat OK (conn {self.connection_id}){C.RESET}")
                else:
                    logger.warning(f"{C.YELLOW}⚠️ No client connection for heartbeat{C.RESET}")
                    # Trigger reconnect
                    self.connected = False
                    await self.ensure_connected()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    f"{C.YELLOW}⚠️ Heartbeat failed: {str(e)[:50]}{C.RESET}"
                )
                self.connected = False
                await self.ensure_connected()
    
    async def execute_trade_instant(self, signal, stake, symbol, currency):
        """
        Execute a trade with MINIMAL delay - assumes connection is already open.
        Returns: (contract_id, entry_price)
        """
        start_time = time.time()
        
        client = await self.ensure_connected()
        if client is None:
            logger.error(f"{C.RED}❌ No connection available for trade.{C.RESET}")
            return None, None
        
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
            proposal_start = time.time()
            proposal_res = await client.send(proposal_payload)
            proposal_time = (time.time() - proposal_start) * 1000
            
            if "error" in proposal_res:
                logger.error(
                    f"{C.RED}❌ Proposal failed: {proposal_res['error'].get('message')}{C.RESET}"
                )
                return None, None
            
            # Extract proposal data with fallback paths
            proposal_data = proposal_res.get("proposal", {})
            proposal_id = proposal_data.get("id")
            
            # Try multiple paths for entry price
            entry_price = proposal_data.get("entry_spot")
            if entry_price is None:
                entry_price = proposal_data.get("spot")
            if entry_price is None:
                entry_price = proposal_data.get("quote")
            if entry_price is None:
                entry_price = 0.0
            
            if not proposal_id:
                logger.error(f"{C.RED}❌ Failed to retrieve Proposal ID.{C.RESET}")
                return None, None
            
            # Execute purchase immediately
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
            
            # Enhanced logging with timing metrics
            logger.info(
                f"{C.GREEN}✅ Trade executed!{C.RESET} Contract: {C.CYAN}{contract_id}{C.RESET} "
                f"{C.GREY}| Entry: {C.WHITE}{entry_price:.3f}{C.RESET} "
                f"{C.GREY}| Latency: Proposal {proposal_time:.0f}ms + Buy {buy_time:.0f}ms = {total_time:.0f}ms{C.RESET}"
            )
            
            return contract_id, entry_price
            
        except Exception as e:
            logger.error(f"{C.RED}❌ Trade execution error: {e}{C.RESET}")
            import traceback
            traceback.print_exc()
            return None, None
    
    async def poll_contract_status(self, contract_id):
        """
        Poll for contract status using a single request (no subscription overhead).
        Returns: (profit, exit_price)
        """
        client = await self.ensure_connected()
        if client is None:
            return None, None
        
        start_time = time.time()
        poll_count = 0
        
        while time.time() - start_time < 25:
            if self._is_closing:
                return None, None
            try:
                poll_start = time.time()
                response = await client.send({
                    "proposal_open_contract": 1,
                    "contract_id": contract_id
                })
                poll_time = (time.time() - poll_start) * 1000
                poll_count += 1
                
                if "error" in response:
                    logger.warning(
                        f"{C.YELLOW}⚠️ Status poll {poll_count} failed: {response['error'].get('message')}{C.RESET}"
                    )
                    await asyncio.sleep(0.3)
                    continue
                
                poc = response.get("proposal_open_contract", {})
                if poc.get("is_sold"):
                    status = poc.get("status", "unknown").upper()
                    profit = float(poc.get("profit", 0.0))
                    exit_price = float(poc.get("exit_spot", 0.0))
                    
                    emoji = "🏆" if status == "WON" else "❌" if status == "LOST" else "⏳"
                    status_color = C.GREEN if status == "WON" else C.RED if status == "LOST" else C.YELLOW
                    
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
            f"{C.YELLOW}⏱️ Contract {contract_id} timed out after 25 seconds ({poll_count} polls).{C.RESET}"
        )
        return None, None
    
    async def process_trade(self, signal, symbol, currency):
        """Process a single trade with instant execution."""
        if self._is_closing:
            return
            
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_trade_time < self.cooldown_seconds:
            remaining = self.cooldown_seconds - (current_time - self.last_trade_time)
            logger.info(
                f"{C.GREY}⏳ Cooldown active ({remaining:.1f}s remaining){C.RESET}"
            )
            return
        
        self.last_trade_time = current_time
        
        # Get stake
        async with stake_lock:
            stake = martingale.next_stake()
            tag = martingale.status_tag()
        
        sig_color = C.GREEN if signal == "CALL" else C.RED
        logger.info(
            f"{C.PURPLE}⚡ EXECUTING{C.RESET} {sig_color}{signal}{C.RESET} at "
            f"{C.BOLD}{stake} {CURRENCY}{C.RESET} {tag} "
            f"{C.GREY}(queue size: {self.pending_trades.qsize()}){C.RESET}"
        )
        
        # Execute instantly
        contract_id, entry_price = await self.execute_trade_instant(signal, stake, symbol, currency)
        
        if not contract_id:
            logger.error(f"{C.RED}❌ Failed to execute {signal} trade.{C.RESET}")
            return
        
        # Poll for result
        profit, exit_price = await self.poll_contract_status(contract_id)
        
        if profit is not None:
            stats.record(profit, contract_id, signal, stake, entry_price, exit_price)
            logger.info(stats.summary_line())
            
            # Update Martingale
            async with stake_lock:
                martingale.record_result(won=profit > 0)
        else:
            logger.error(f"{C.RED}❌ Could not determine outcome for contract {contract_id}{C.RESET}")
    
    async def trade_worker(self):
        """Background worker that processes trades from the queue."""
        # Start heartbeat
        self.heartbeat_task = asyncio.create_task(self.heartbeat())
        logger.info(f"{C.GREEN}💓 Heartbeat started (interval: {HEARTBEAT_INTERVAL}s){C.RESET}")
        
        while not self._is_closing:
            try:
                signal, symbol, currency = await self.pending_trades.get()
                await self.process_trade(signal, symbol, currency)
            except asyncio.CancelledError:
                logger.info(f"{C.GREY}Trade worker cancelled.{C.RESET}")
                break
            except Exception as e:
                logger.error(f"{C.RED}❌ Trade worker error: {e}{C.RESET}")
                import traceback
                traceback.print_exc()
            finally:
                self.pending_trades.task_done()
    
    def queue_trade(self, signal, symbol, currency):
        """Queue a trade for execution."""
        if self._is_closing:
            return
        self.pending_trades.put_nowait((signal, symbol, currency))
        logger.debug(f"{C.GREY}📥 Trade queued ({self.pending_trades.qsize()} pending){C.RESET}")
    
    async def close(self):
        """Gracefully close the connection."""
        self._is_closing = True
        
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except:
                pass
        
        if self.client and self.client.ws is not None:
            try:
                await self.client.close()
                logger.info(f"{C.GREY}🔌 Persistent trading connection closed.{C.RESET}")
            except:
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
        self.signal_cooldown = 1.0  # 1 second between signals

    def process_new_tick(self, price, server_epoch):
        # 1. Network Latency Check
        server_epoch_ms = int(server_epoch * 1000)
        local_time_ms = int(time.time() * 1000)
        latency = local_time_ms - server_epoch_ms

        if abs(latency) > 10000 and not self.clock_drift_warning_triggered:
            logger.warning(
                f"🚨 {C.YELLOW}SYSTEM CLOCK OUT OF SYNC{C.RESET}: Your local time differs from the "
                f"server by {C.BOLD}{latency/1000:.1f}s{C.RESET}. "
                "Synchronize your computer clock via NTP!"
            )
            self.clock_drift_warning_triggered = True

        if latency > self.max_latency:
            logger.warning(
                f"{C.YELLOW}⚠️ Skipping tick{C.RESET} ({C.ORANGE}High Latency: {latency}ms{C.RESET})"
            )
            return "SKIP_LATENCY"

        # 2. Track Streaks with timestamps
        if len(self.prices) > 0:
            last_price = self.prices[-1]
            if price > last_price:
                self.streak = self.streak + 1 if self.streak > 0 else 1
            elif price < last_price:
                self.streak = self.streak - 1 if self.streak < 0 else -1
            else:
                self.streak = 0  # Flat tick breaks momentum streak

        self.prices.append(price)
        self.timestamps.append(time.time())
        if len(self.prices) > 20:
            self.prices.pop(0)
            self.timestamps.pop(0)

        # 3. Output Current Status (enhanced with tick frequency)
        if self.streak > 0:
            direction_emoji, dir_color = "📈", C.GREEN
        elif self.streak < 0:
            direction_emoji, dir_color = "📉", C.RED
        else:
            direction_emoji, dir_color = "➡️", C.GREY

        streak_meter = self._streak_meter(dir_color)
        latency_color = C.GREEN if latency < self.max_latency * 0.5 else C.YELLOW
        
        # Calculate tick frequency
        tick_freq = "N/A"
        if len(self.timestamps) > 1:
            avg_interval = (self.timestamps[-1] - self.timestamps[0]) / (len(self.timestamps) - 1)
            tick_freq = f"{avg_interval*1000:.0f}ms"

        next_stake = martingale.next_stake()

        logger.info(
            f"{dir_color}●{C.RESET} Price: {C.WHITE}{C.BOLD}{price:.3f}{C.RESET}  "
            f"Streak: {dir_color}{self.streak:+d}{C.RESET} {direction_emoji} {streak_meter}  "
            f"{C.GREY}│{C.RESET} Latency: {latency_color}{latency}ms{C.RESET} "
            f"{C.GREY}({tick_freq}){C.RESET}  "
            f"{C.GREY}│{C.RESET} Next Stake: {C.WHITE}{next_stake} {CURRENCY}{C.RESET} {martingale.status_tag()}  "
            f"{C.GREY}│{C.RESET} {stats.summary_line()}"
        )

        # 4. Generate Signal with cooldown
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
  {C.GREEN}⚡ OPTIMIZED: Persistent Connection | Health Monitoring | Instant Execution{C.RESET}
  {C.GREY}💓 Heartbeat: {HEARTBEAT_INTERVAL}s | Max Reconnect: {MAX_RECONNECT_ATTEMPTS}{C.RESET}
"""
    print(banner)


# ==================== MAIN ====================
async def main():
    if not API_TOKEN:
        logger.error("Execution stopped: Missing Token in environment variables.")
        return

    print_banner()
    logger.info(f"{C.GREY}🚀 Starting bot at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}")

    # Initialize persistent trade manager
    trade_manager = PersistentTradeManager()
    
    # PRE-CONNECT the trading connection to avoid delay on first trade
    logger.info("🔌 Pre-connecting trading connection...")
    await trade_manager.ensure_connected()
    logger.info(f"{C.GREEN}✅ Trading connection ready.{C.RESET}")
    
    # Start the background trade worker
    worker_task = asyncio.create_task(trade_manager.trade_worker())
    logger.info("🚀 Trade worker started (persistent connection).")

    # Obtain permanent streaming connection URL
    ws_url_ticks = get_ws_url(account_type="demo", token=API_TOKEN, app_id=APP_ID)
    tick_client = DerivClient(ws_url_ticks)

    try:
        await tick_client.connect()
        logger.info(f"{C.GREEN}✅ Streaming connection successfully established.{C.RESET}")

        # Subscribe to continuous live ticks
        logger.info(f"Subscribing to tick stream for {C.CYAN}{SYMBOL}{C.RESET}...")
        await tick_client.ws.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))

        tracker = TickStreakTracker(
            target_streak=TARGET_STREAK, max_allowed_latency_ms=MAX_LATENCY_MS
        )
        
        # Track signals to prevent duplicate triggers
        last_signal_time = 0

        logger.info(
            f"{C.CYAN}👁️ Now analyzing market... Awaiting {C.BOLD}{TARGET_STREAK}{C.RESET} tick streak on {C.CYAN}{SYMBOL}{C.RESET}."
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
                    sig_color = C.GREEN if signal == "CALL" else C.RED
                    logger.info(
                        f"{C.YELLOW}🔥 Strike Streak Confirmed!{C.RESET} Triggering {sig_color}{C.BOLD}{signal}{C.RESET} order at price {C.WHITE}{price:.3f}{C.RESET}"
                    )
                    
                    # Queue the trade for instant execution
                    trade_manager.queue_trade(signal, SYMBOL, CURRENCY)
                    
                    # Update cooldown
                    last_signal_time = current_time
                    
                    # Reset streak tracking to prevent double-triggering
                    tracker.streak = 0

            elif "error" in message:
                logger.error(
                    f"{C.RED}❌ WebSocket incoming error: {message['error'].get('message')}{C.RESET}"
                )

    except asyncio.CancelledError:
        logger.info("Bot execution cancelled. Shutting down gracefully...")
    except Exception as e:
        logger.error(f"{C.RED}❌ Critical failure in streaming thread: {e}{C.RESET}", exc_info=True)
    finally:
        logger.info("Tearing down active connections...")
        
        # Print detailed summary
        logger.info(stats.detailed_summary())
        
        # Cancel the worker task
        worker_task.cancel()
        try:
            await worker_task
        except:
            pass
        
        # Close connections
        if tick_client and tick_client.ws is not None:
            await tick_client.close()
        
        await trade_manager.close()
        
        logger.info(f"{C.GREY}🛑 Bot stopped at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot manually terminated. Goodbye!")
        logger.info(stats.detailed_summary())