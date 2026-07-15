"""experiment2.py - Tiered Risk Management with Fixed Numeric TP/SL Hedging - FULLY FIXED"""

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
logger = logging.getLogger("DerivTieredBot")

# Load environment variables
load_dotenv()
API_TOKEN = os.getenv("TOKEN")
APP_ID = os.getenv("APP_ID") or "1089"

# ==================== CONFIGURATION ====================
SYMBOL = "R_100"
CURRENCY = "USD"
TARGET_STREAK = 4
CONTRACT_DURATION = 5
COOLDOWN_SECONDS = 6
MAX_LATENCY_MS = 1000

HEARTBEAT_INTERVAL = 5
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY = 2

# ==================== TP/SL CONFIGURATION - FIXED ====================
TP_SL_MONITOR_INTERVAL = 0.1  # FIXED: 100ms for faster detection
TP_SL_SLIPPAGE_TOLERANCE = 0.02  # FIXED: 0.02 price points tolerance
HEDGE_STAKE_MULTIPLIER = 1.0

# ==================== TIERED RISK CONFIGURATION ====================
ABSOLUTE_MIN_BALANCE = 5.00
ABSOLUTE_MIN_STAKE = 0.10

TIER_1_MIN = 17.50
TIER_1_MAX = 49.99
TIER_1_STAKE = 0.35
TIER_1_TP = 0.30
TIER_1_SL = 0.20

TIER_2_MIN = 50.00
TIER_2_MAX = 99.99
TIER_2_STAKE = 1.00
TIER_2_TP = 0.80
TIER_2_SL = 0.50

TIER_3_MIN = 100.00
TIER_3_MAX = 499.99
TIER_3_STAKE = 2.00
TIER_3_TP = 1.50
TIER_3_SL = 1.00

TIER_4_MIN = 500.00
TIER_4_MAX = 999.99
TIER_4_STAKE = 10.00
TIER_4_TP = 5.00
TIER_4_SL = 3.00

TIER_5_MIN = 1000.00
TIER_5_RISK_PERCENT = 1.5
TIER_5_TP_PERCENT = 1.5
TIER_5_SL_PERCENT = 0.8

DAILY_LOSS_LIMIT_PERCENT = 10.0
DAILY_PROFIT_TARGET_PERCENT = 10.0
MAX_CONSECUTIVE_LOSSES = 3
# ===============================================================


# ==================== SESSION P&L TRACKER ====================
class SessionStats:
    def __init__(self, initial_balance=20.0):
        self.initial_balance = initial_balance
        self.net_pl = 0.0
        self.wins = 0
        self.losses = 0
        self.trades = 0
        self.start_time = datetime.now()
        self.trade_history = []
        self.pending_trades = {}
        self.active_trades = {}
        self.consecutive_losses = 0
        self.max_consecutive_losses = 0
        self.max_drawdown = 0.0
        self.peak_balance = initial_balance
        self.daily_start_balance = initial_balance
        self.daily_net_pl = 0.0
        self.daily_trades = 0
        self.daily_wins = 0
        self.daily_losses = 0
        self.daily_max_drawdown = 0.0
        self.daily_peak_balance = initial_balance
        self.is_daily_stopped = False
        self.daily_stop_reason = None

    def get_current_balance(self):
        return self.initial_balance + self.net_pl

    def get_daily_balance(self):
        return self.daily_start_balance + self.daily_net_pl

    def get_drawdown_percent(self):
        current = self.get_current_balance()
        if self.peak_balance > 0:
            return ((self.peak_balance - current) / self.peak_balance) * 100
        return 0.0

    def get_daily_drawdown_percent(self):
        current = self.get_daily_balance()
        if self.daily_peak_balance > 0:
            return ((self.daily_peak_balance - current) / self.daily_peak_balance) * 100
        return 0.0

    def get_daily_profit_percent(self):
        if self.daily_start_balance > 0:
            return (self.daily_net_pl / self.daily_start_balance) * 100
        return 0.0

    def record(
        self,
        profit,
        contract_id,
        signal,
        stake,
        entry_price,
        exit_price,
        is_hedge=False,
    ):
        self.net_pl += profit
        self.trades += 1
        self.daily_net_pl += profit
        self.daily_trades += 1

        if profit > 0:
            self.wins += 1
            self.daily_wins += 1
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.daily_losses += 1
            self.consecutive_losses += 1
            if self.consecutive_losses > self.max_consecutive_losses:
                self.max_consecutive_losses = self.consecutive_losses

        current_balance = self.get_current_balance()
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance

        daily_current = self.get_daily_balance()
        if daily_current > self.daily_peak_balance:
            self.daily_peak_balance = daily_current

        drawdown = self.get_drawdown_percent()
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        daily_dd = self.get_daily_drawdown_percent()
        if daily_dd > self.daily_max_drawdown:
            self.daily_max_drawdown = daily_dd

        daily_profit_pct = self.get_daily_profit_percent()
        if daily_profit_pct >= DAILY_PROFIT_TARGET_PERCENT:
            self.is_daily_stopped = True
            self.daily_stop_reason = f"Daily Profit Target Hit: {daily_profit_pct:.1f}%"
        elif daily_dd >= DAILY_LOSS_LIMIT_PERCENT:
            self.is_daily_stopped = True
            self.daily_stop_reason = f"Daily Loss Limit Hit: {daily_dd:.1f}%"

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
                "balance": current_balance,
                "is_hedge": is_hedge,
            }
        )

    def reset_daily(self):
        self.daily_start_balance = self.get_current_balance()
        self.daily_net_pl = 0.0
        self.daily_trades = 0
        self.daily_wins = 0
        self.daily_losses = 0
        self.daily_max_drawdown = 0.0
        self.daily_peak_balance = self.daily_start_balance
        self.is_daily_stopped = False
        self.daily_stop_reason = None
        self.consecutive_losses = 0

    def summary_line(self):
        win_rate = (self.wins / self.trades * 100) if self.trades else 0.0
        pl_color = C.GREEN if self.net_pl >= 0 else C.RED
        active = (
            f" | {C.YELLOW}Active: {len(self.pending_trades)}{C.RESET}"
            if self.pending_trades
            else ""
        )
        dd = (
            f" | {C.RED}DD: {self.max_drawdown:.1f}%{C.RESET}"
            if self.max_drawdown > 0
            else ""
        )
        daily_status = ""
        if self.is_daily_stopped:
            daily_status = f" | {C.RED}🛑 DAILY STOP: {self.daily_stop_reason}{C.RESET}"
        elif self.daily_trades > 0:
            daily_profit = self.get_daily_profit_percent()
            daily_color = C.GREEN if daily_profit >= 0 else C.RED
            daily_status = f" | Daily: {daily_color}{daily_profit:+.1f}%{C.RESET}"

        return (
            f"{C.BOLD}📊 SESSION{C.RESET} | Trades: {C.CYAN}{self.trades}{C.RESET} "
            f"| Wins: {C.GREEN}{self.wins}{C.RESET} | Losses: {C.RED}{self.losses}{C.RESET} "
            f"| Win Rate: {C.CYAN}{win_rate:.1f}%{C.RESET} "
            f"| Net P/L: {pl_color}{C.BOLD}{self.net_pl:+.2f} {CURRENCY}{C.RESET}"
            f"{active}{dd}{daily_status}"
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
            f"{C.BOLD}Performance:{C.RESET}",
            f"  Trades: {self.trades}  Wins: {C.GREEN}{self.wins}{C.RESET}  Losses: {C.RED}{self.losses}{C.RESET}  Win Rate: {C.CYAN}{(self.wins/self.trades*100):.1f}%{C.RESET}",
            f"  Net P/L: {C.pl(self.net_pl)} {CURRENCY}",
            f"  Current Balance: {C.WHITE}{self.get_current_balance():.2f} {CURRENCY}{C.RESET}",
            f"  Max Drawdown: {C.RED}{self.max_drawdown:.1f}%{C.RESET}",
            f"  Max Consecutive Losses: {C.RED}{self.max_consecutive_losses}{C.RESET}",
            "",
            f"{C.BOLD}Daily Stats:{C.RESET}",
            f"  Daily Trades: {self.daily_trades}  Wins: {C.GREEN}{self.daily_wins}{C.RESET}  Losses: {C.RED}{self.daily_losses}{C.RESET}",
            f"  Daily P/L: {C.pl(self.daily_net_pl)} {CURRENCY} ({C.pl(self.get_daily_profit_percent())}%)",
            f"  Daily Max Drawdown: {C.RED}{self.daily_max_drawdown:.1f}%{C.RESET}",
            (
                f"  Daily Status: {C.RED}{self.daily_stop_reason}{C.RESET}"
                if self.is_daily_stopped
                else "  Daily Status: {C.GREEN}ACTIVE{C.RESET}"
            ),
            "",
            f"{C.BOLD}{C.UNDERLINE}Trade History:{C.RESET}",
        ]

        for i, trade in enumerate(self.trade_history, 1):
            result_color = C.GREEN if trade["result"] == "WON" else C.RED
            hedge_tag = " [HEDGE]" if trade.get("is_hedge", False) else ""
            lines.append(
                f"  #{i:2d} {trade['time'][11:19]} {trade['signal']:4s} "
                f"Stake: {trade['stake']:5.2f}  Entry: {trade['entry_price']:.3f}  "
                f"Exit: {trade['exit_price']:.3f}  {result_color}{trade['result']:4s}{C.RESET}{hedge_tag}  "
                f"P/L: {C.pl(trade['profit'])}  Bal: {trade['balance']:.2f}"
            )

        lines.append(
            f"{C.CYAN}═══════════════════════════════════════════════════════════{C.RESET}"
        )
        return "\n".join(lines)


stats = SessionStats(initial_balance=1000.0)
# =======================================================


# ==================== TIERED STAKE MANAGER ====================
class TieredStakeManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self.current_stake = TIER_1_STAKE
        self.current_tier = 1
        self.current_tp = TIER_1_TP
        self.current_sl = TIER_1_SL
        self._trading_blocked = False
        self._block_reason = None

    def _get_tier_config(self, balance):
        if balance < ABSOLUTE_MIN_BALANCE:
            return (
                None,
                -1,
                None,
                None,
                f"Balance ${balance:.2f} below absolute minimum ${ABSOLUTE_MIN_BALANCE:.2f}",
            )

        if balance < TIER_1_MIN:
            ratio = (balance - ABSOLUTE_MIN_BALANCE) / (
                TIER_1_MIN - ABSOLUTE_MIN_BALANCE
            )
            scaled_stake = round(
                ABSOLUTE_MIN_STAKE + (TIER_1_STAKE - ABSOLUTE_MIN_STAKE) * ratio, 2
            )
            if scaled_stake < ABSOLUTE_MIN_STAKE:
                scaled_stake = ABSOLUTE_MIN_STAKE
            scaled_tp = round(TIER_1_TP * ratio, 2)
            scaled_sl = round(TIER_1_SL * ratio, 2)
            if scaled_tp < 0.05:
                scaled_tp = 0.05
            if scaled_sl < 0.05:
                scaled_sl = 0.05
            return scaled_stake, 0, scaled_tp, scaled_sl, None

        if TIER_1_MIN <= balance <= TIER_1_MAX:
            return TIER_1_STAKE, 1, TIER_1_TP, TIER_1_SL, None
        if TIER_2_MIN <= balance <= TIER_2_MAX:
            return TIER_2_STAKE, 2, TIER_2_TP, TIER_2_SL, None
        if TIER_3_MIN <= balance <= TIER_3_MAX:
            return TIER_3_STAKE, 3, TIER_3_TP, TIER_3_SL, None
        if TIER_4_MIN <= balance <= TIER_4_MAX:
            return TIER_4_STAKE, 4, TIER_4_TP, TIER_4_SL, None
        if balance >= TIER_5_MIN:
            stake = round(balance * (TIER_5_RISK_PERCENT / 100), 2)
            if stake < TIER_4_STAKE:
                stake = TIER_4_STAKE
            tp = round(stake * (TIER_5_TP_PERCENT / 100), 2)
            sl = round(stake * (TIER_5_SL_PERCENT / 100), 2)
            if tp < 0.10:
                tp = 0.10
            if sl < 0.05:
                sl = 0.05
            return stake, 5, tp, sl, None
        return TIER_1_STAKE, 1, TIER_1_TP, TIER_1_SL, None

    async def get_current_stake(self):
        async with self._lock:
            return self.current_stake

    async def get_current_tp_sl(self):
        async with self._lock:
            return self.current_tp, self.current_sl

    async def update_stake(self, balance):
        async with self._lock:
            new_stake, tier, tp, sl, block_reason = self._get_tier_config(balance)

            if tier == -1:
                self.current_stake = 0.0
                self.current_tier = -1
                self.current_tp = 0.0
                self.current_sl = 0.0
                self._trading_blocked = True
                self._block_reason = block_reason
                return 0.0, 0.0, 0.0, block_reason

            tier_changed = tier != self.current_tier
            self.current_stake = new_stake
            self.current_tier = tier
            self.current_tp = tp
            self.current_sl = sl
            self._trading_blocked = False
            self._block_reason = None

            if tier_changed:
                tier_names = {
                    -1: "CRITICAL - STOPPED",
                    0: "Below Minimum (Scaled)",
                    1: "Survival",
                    2: "Growth",
                    3: "Professional",
                    4: "Compounding",
                    5: "Fortress",
                }
                logger.info(
                    f"{C.CYAN}🔁 TIER CHANGE{C.RESET}: {tier_names.get(self.current_tier, 'Unknown')} → "
                    f"{C.BOLD}{tier_names.get(tier, 'Unknown')}{C.RESET} "
                    f"(Stake: {C.WHITE}{self.current_stake:.2f}{C.RESET} | "
                    f"TP: {C.GREEN}{self.current_tp:.2f}{C.RESET} | "
                    f"SL: {C.RED}{self.current_sl:.2f}{C.RESET})"
                )
            return self.current_stake, self.current_tp, self.current_sl, None

    async def reset_to_base(self):
        async with self._lock:
            self.current_stake = TIER_1_STAKE
            self.current_tier = 1
            self.current_tp = TIER_1_TP
            self.current_sl = TIER_1_SL
            self._trading_blocked = False
            self._block_reason = None
            logger.info(
                f"{C.YELLOW}🔄 Stake reset to base: {TIER_1_STAKE} {CURRENCY}{C.RESET}"
            )
            return self.current_stake

    def is_trading_allowed(self):
        return (
            self.current_stake > 0.0
            and self.current_tier != -1
            and not self._trading_blocked
        )

    def get_block_reason(self):
        return self._block_reason

    def status_tag(self):
        if self._trading_blocked:
            return f"{C.RED}[🔴 TRADING STOPPED]{C.RESET}"

        tier_names = {
            -1: "🔴 STOPPED",
            0: "⚠️ Scaled",
            1: "Survival",
            2: "Growth",
            3: "Professional",
            4: "Compounding",
            5: "Fortress",
        }
        tier_name = tier_names.get(self.current_tier, "Unknown")
        if self.current_stake == 0.0:
            return f"{C.RED}[🔴 TRADING STOPPED]{C.RESET}"
        risk_emoji = "🟢" if self.current_tier >= 1 else "🟡"
        return f"{risk_emoji}[{tier_name}: {self.current_stake:.2f} | TP: {self.current_tp:.2f} | SL: {self.current_sl:.2f}]{C.RESET}"


tiered_stake = TieredStakeManager()
# =======================================================


# ==================== PERSISTENT TRADE MANAGER - FIXED ====================
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
        self._heartbeat_failures = 0
        self.daily_reset_time = datetime.now()
        self.active_contracts = {}
        self._bot_running = True
        self._price_history = {}  # Store recent prices for each contract
        self._tp_sl_triggered = set()  # Track triggered contracts

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
                    self.reconnect_attempts = 0
            except Exception as e:
                logger.error(f"{C.RED}❌ Execution client failed: {e}{C.RESET}")
                self.reconnect_attempts += 1
                if self.reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                    logger.error(f"{C.RED}❌ Max reconnect attempts reached.{C.RESET}")
                    return None
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
                    self.reconnect_attempts = 0
            except Exception as e:
                logger.error(f"{C.RED}❌ Polling client failed: {e}{C.RESET}")
                self.reconnect_attempts += 1
                if self.reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                    logger.error(f"{C.RED}❌ Max reconnect attempts reached.{C.RESET}")
                    return None
                return None
        return self.polling_client

    async def heartbeat(self):
        consecutive_failures = 0
        max_consecutive_failures = 3
        while not self._is_closing:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if self._is_closing:
                break
            try:
                exec_ok = True
                if self.execution_client and self.execution_client.ws:
                    exec_ok = await self.execution_client.ping()
                    if not exec_ok:
                        logger.warning(
                            f"{C.YELLOW}⚠️ Execution client ping failed, reconnecting...{C.RESET}"
                        )
                        self.execution_client = None
                        await self.ensure_execution_client()
                poll_ok = True
                if self.polling_client and self.polling_client.ws:
                    poll_ok = await self.polling_client.ping()
                    if not poll_ok:
                        logger.warning(
                            f"{C.YELLOW}⚠️ Polling client ping failed, reconnecting...{C.RESET}"
                        )
                        self.polling_client = None
                        await self.ensure_polling_client()
                if exec_ok and poll_ok:
                    consecutive_failures = 0
                    self._heartbeat_failures = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                self._heartbeat_failures += 1
                logger.warning(
                    f"{C.YELLOW}⚠️ Heartbeat warning ({consecutive_failures}): {str(e)[:50]}{C.RESET}"
                )
                if consecutive_failures >= max_consecutive_failures:
                    logger.warning(
                        f"{C.YELLOW}🔄 Multiple heartbeat failures, forcing reconnect...{C.RESET}"
                    )
                    self.execution_client = None
                    self.polling_client = None
                    await self.ensure_execution_client()
                    await self.ensure_polling_client()
                    consecutive_failures = 0

    async def get_current_price(self):
        try:
            client = await self.ensure_polling_client()
            if not client:
                return None
            response = await client.send({"ticks": SYMBOL, "subscribe": 0})
            if "error" in response:
                return None
            tick = response.get("tick", {})
            return float(tick.get("quote", 0))
        except Exception as e:
            return None

    async def execute_hedge_trade(self, signal, stake, symbol, currency):
        client = await self.ensure_execution_client()
        if client is None:
            return None, None

        proposal_payload = {
            "proposal": 1,
            "amount": stake,
            "basis": "stake",
            "contract_type": signal,
            "currency": currency,
            "duration": CONTRACT_DURATION,
            "duration_unit": "t",
            "underlying_symbol": symbol,
        }

        try:
            proposal_res = await client.send(proposal_payload)
            if "error" in proposal_res:
                logger.error(
                    f"{C.RED}❌ Hedge proposal failed: {proposal_res['error'].get('message')}{C.RESET}"
                )
                return None, None

            proposal_data = proposal_res.get("proposal", {})
            proposal_id = proposal_data.get("id")
            entry_price = (
                proposal_data.get("entry_spot") or proposal_data.get("spot") or 0.0
            )

            if not proposal_id:
                return None, None

            buy_payload = {"buy": proposal_id, "price": stake}
            buy_res = await client.send(buy_payload)
            if "error" in buy_res:
                logger.error(
                    f"{C.RED}❌ Hedge purchase failed: {buy_res['error'].get('message')}{C.RESET}"
                )
                return None, None

            contract_id = buy_res.get("buy", {}).get("contract_id")
            logger.info(
                f"{C.PURPLE}🛡️ HEDGE EXECUTED{C.RESET} {signal} Contract: {C.CYAN}{contract_id}{C.RESET} "
                f"{C.GREY}| Stake: {C.WHITE}{stake:.2f}{C.RESET}"
            )
            return contract_id, entry_price

        except Exception as e:
            logger.error(f"{C.RED}❌ Hedge execution error: {e}{C.RESET}")
            return None, None

    async def monitor_tp_sl(
        self, contract_id, signal, entry_price, stake, tp_amount, sl_amount
    ):
        """FIXED: Monitor price for TP/SL triggers with slippage tolerance and immediate execution."""

        # Convert fixed dollar amounts to price levels
        if signal == "CALL":
            take_profit_price = entry_price + tp_amount
            stop_loss_price = entry_price - sl_amount
        else:
            take_profit_price = entry_price - tp_amount
            stop_loss_price = entry_price + sl_amount

        # Add tolerance
        tp_hit_price = take_profit_price - TP_SL_SLIPPAGE_TOLERANCE
        sl_hit_price = stop_loss_price + TP_SL_SLIPPAGE_TOLERANCE

        logger.info(
            f"{C.CYAN}🎯 TP/SL MONITORING{C.RESET} | Contract: {contract_id} "
            f"| TP: {C.GREEN}{take_profit_price:.3f}{C.RESET} (${tp_amount:.2f}) "
            f"| SL: {C.RED}{stop_loss_price:.3f}{C.RESET} (${sl_amount:.2f}) "
            f"| Signal: {signal} | Stake: {stake:.2f}"
            f"| Tolerance: ±{TP_SL_SLIPPAGE_TOLERANCE:.2f}"
        )

        start_time = time.time()
        max_monitor_time = CONTRACT_DURATION * 2
        hedge_executed = False
        self._price_history[contract_id] = []
        self._tp_sl_triggered.discard(contract_id)

        # Pre-calculate hedge details
        hedge_signal = "PUT" if signal == "CALL" else "CALL"
        current_balance = stats.get_current_balance()
        _, _, _, _ = await tiered_stake.update_stake(current_balance)
        hedge_stake = tiered_stake.current_stake * HEDGE_STAKE_MULTIPLIER
        if hedge_stake < 0.10:
            hedge_stake = 0.10

        while time.time() - start_time < max_monitor_time:
            if self._is_closing or contract_id not in stats.pending_trades:
                break

            if contract_id in self._tp_sl_triggered:
                break

            current_price = await self.get_current_price()
            if current_price is None:
                await asyncio.sleep(TP_SL_MONITOR_INTERVAL)
                continue

            # Store price history for debugging
            self._price_history[contract_id].append(current_price)
            if len(self._price_history[contract_id]) > 10:
                self._price_history[contract_id].pop(0)

            tp_hit = False
            sl_hit = False

            # Check with tolerance
            if signal == "CALL":
                if current_price >= tp_hit_price:
                    tp_hit = True
                    logger.info(
                        f"{C.GREEN}🎯 TAKE PROFIT HIT!{C.RESET} Price: {current_price:.3f} >= {tp_hit_price:.3f} (Target: {take_profit_price:.3f})"
                    )
                elif current_price <= sl_hit_price:
                    sl_hit = True
                    logger.info(
                        f"{C.RED}🛑 STOP LOSS HIT!{C.RESET} Price: {current_price:.3f} <= {sl_hit_price:.3f} (Target: {stop_loss_price:.3f})"
                    )
            else:
                if current_price <= tp_hit_price:
                    tp_hit = True
                    logger.info(
                        f"{C.GREEN}🎯 TAKE PROFIT HIT!{C.RESET} Price: {current_price:.3f} <= {tp_hit_price:.3f} (Target: {take_profit_price:.3f})"
                    )
                elif current_price >= sl_hit_price:
                    sl_hit = True
                    logger.info(
                        f"{C.RED}🛑 STOP LOSS HIT!{C.RESET} Price: {current_price:.3f} >= {sl_hit_price:.3f} (Target: {stop_loss_price:.3f})"
                    )

            # ===== FIX: Execute hedge IMMEDIATELY when TP/SL is hit =====
            if tp_hit or sl_hit:
                self._tp_sl_triggered.add(contract_id)
                logger.info(
                    f"{C.PURPLE}🛡️ EXECUTING HEDGE{C.RESET} | Original: {contract_id} "
                    f"| Hedge: {hedge_signal} | Stake: {hedge_stake:.2f} | Reason: {'TP' if tp_hit else 'SL'}"
                )

                hedge_contract_id, hedge_entry = await self.execute_hedge_trade(
                    hedge_signal, hedge_stake, SYMBOL, CURRENCY
                )

                if hedge_contract_id:
                    hedge_executed = True
                    self.active_contracts[hedge_contract_id] = {
                        "is_hedge": True,
                        "original_contract": contract_id,
                        "signal": hedge_signal,
                        "stake": hedge_stake,
                        "entry": hedge_entry,
                        "tp_hit": tp_hit,
                        "sl_hit": sl_hit,
                    }

                    if contract_id in self.active_contracts:
                        self.active_contracts[contract_id]["hedge_placed"] = True
                        self.active_contracts[contract_id][
                            "hedge_contract"
                        ] = hedge_contract_id

                    logger.info(
                        f"{C.PURPLE}🛡️ HEDGE CONTRACT PLACED{C.RESET} | ID: {hedge_contract_id} "
                        f"| Signal: {hedge_signal} | Stake: {hedge_stake:.2f}"
                    )
                    break

            await asyncio.sleep(TP_SL_MONITOR_INTERVAL)

        # Clean up
        if contract_id in self._price_history:
            del self._price_history[contract_id]

        if not hedge_executed and contract_id in stats.pending_trades:
            logger.debug(f"Contract {contract_id} monitoring ended naturally.")

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
            "duration": CONTRACT_DURATION,
            "duration_unit": "t",
            "underlying_symbol": symbol,
        }

        try:
            proposal_res = await client.send(proposal_payload)
            if "error" in proposal_res:
                logger.error(
                    f"{C.RED}❌ Proposal failed: {proposal_res['error'].get('message')}{C.RESET}"
                )
                return None, None

            proposal_data = proposal_res.get("proposal", {})
            proposal_id = proposal_data.get("id")
            entry_price = (
                proposal_data.get("entry_spot") or proposal_data.get("spot") or 0.0
            )

            if not proposal_id:
                return None, None

            buy_payload = {"buy": proposal_id, "price": stake}
            buy_res = await client.send(buy_payload)
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
                f"{C.GREY}| Latency: {total_time:.0f}ms{C.RESET}"
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
        consecutive_errors = 0

        while time.time() - start_time < 25:
            if self._is_closing:
                return None, None

            try:
                response = await client.send(
                    {"proposal_open_contract": 1, "contract_id": contract_id}
                )
                poll_count += 1
                consecutive_errors = 0

                if "error" in response:
                    error_msg = response["error"].get("message", "unknown")
                    await asyncio.sleep(0.5)
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
                        f"{status_color}{status}{C.RESET} | Exit: {C.WHITE}{exit_price:.3f}{C.RESET} "
                        f"| Profit: {C.pl(profit)} {CURRENCY}"
                    )
                    return profit, exit_price

            except asyncio.TimeoutError:
                consecutive_errors += 1
                if consecutive_errors >= 2:
                    self.polling_client = None
                    client = await self.ensure_polling_client()
                    if client is None:
                        return None, None
                    consecutive_errors = 0
                await asyncio.sleep(0.5)
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 2:
                    self.polling_client = None
                    client = await self.ensure_polling_client()
                    if client is None:
                        return None, None
                    consecutive_errors = 0
                await asyncio.sleep(1.0)
            await asyncio.sleep(0.3)

        return None, None

    async def check_daily_reset(self):
        now = datetime.now()
        if now.day != self.daily_reset_time.day:
            logger.info(
                f"{C.CYAN}📅 New day detected. Resetting daily stats...{C.RESET}"
            )
            stats.reset_daily()
            self.daily_reset_time = now
            await tiered_stake.reset_to_base()
            return True
        return False

    def print_trade_preview(self, signal, stake, entry_price, tp_amount, sl_amount):
        """Print TP/SL targets before executing trade."""
        if signal == "CALL":
            tp = entry_price + tp_amount
            sl = entry_price - sl_amount
        else:
            tp = entry_price - tp_amount
            sl = entry_price + sl_amount

        logger.info("")
        logger.info(
            f"{C.CYAN}{C.BOLD}═══════════════════════════════════════════════════════════{C.RESET}"
        )
        logger.info(f"{C.BOLD}🎯 TRADE PREVIEW{C.RESET}")
        logger.info(
            f"{C.CYAN}───────────────────────────────────────────────────────────────────{C.RESET}"
        )
        logger.info(f"  {C.GREY}Signal:{C.RESET}      {C.BOLD}{signal}{C.RESET}")
        logger.info(
            f"  {C.GREY}Stake:{C.RESET}       {C.BOLD}{stake:.2f} {CURRENCY}{C.RESET}"
        )
        logger.info(
            f"  {C.GREY}Entry Price:{C.RESET} {C.BOLD}{entry_price:.3f}{C.RESET}"
        )
        logger.info(
            f"  {C.GREY}Take Profit:{C.RESET} {C.GREEN}{C.BOLD}{tp:.3f}{C.RESET} (${C.GREEN}{tp_amount:.2f}{C.RESET})"
        )
        logger.info(
            f"  {C.GREY}Stop Loss:{C.RESET}   {C.RED}{C.BOLD}{sl:.3f}{C.RESET} (${C.RED}{sl_amount:.2f}{C.RESET})"
        )
        logger.info(
            f"  {C.GREY}Current Bal:{C.RESET} {C.WHITE}{stats.get_current_balance():.2f} {CURRENCY}{C.RESET}"
        )
        logger.info(f"  {C.GREY}Tier:{C.RESET}        {tiered_stake.status_tag()}")
        logger.info(
            f"{C.CYAN}═══════════════════════════════════════════════════════════{C.RESET}"
        )
        logger.info("")

        return tp, sl

    async def process_trade(self, signal, symbol, currency):
        if self._is_closing:
            return

        await self.check_daily_reset()

        if stats.is_daily_stopped:
            logger.warning(
                f"{C.RED}🛑 DAILY STOP ACTIVE: {stats.daily_stop_reason}{C.RESET}"
            )
            return

        if stats.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            logger.warning(
                f"{C.RED}🛑 EMERGENCY STOP: {stats.consecutive_losses} consecutive losses!{C.RESET}"
            )
            return

        current_balance = stats.get_current_balance()
        stake, tp_amount, sl_amount, block_reason = await tiered_stake.update_stake(
            current_balance
        )

        if not tiered_stake.is_trading_allowed():
            logger.critical("")
            logger.critical(
                f"{C.RED}{C.BOLD}═══════════════════════════════════════════════════════════{C.RESET}"
            )
            logger.critical(
                f"{C.RED}{C.BOLD}🚨 TRADING STOPPED - INSUFFICIENT BALANCE{C.RESET}"
            )
            logger.critical(
                f"{C.RED}{C.BOLD}═══════════════════════════════════════════════════════════{C.RESET}"
            )
            logger.critical(
                f"{C.RED}  Reason: {block_reason or tiered_stake.get_block_reason()}{C.RESET}"
            )
            logger.critical(
                f"{C.RED}  Current Balance: ${current_balance:.2f}{C.RESET}"
            )
            logger.critical(
                f"{C.RED}  Minimum Required: ${ABSOLUTE_MIN_BALANCE:.2f}{C.RESET}"
            )
            logger.critical(
                f"{C.RED}{C.BOLD}═══════════════════════════════════════════════════════════{C.RESET}"
            )
            logger.critical(
                f"{C.RED}  🛑 BOT WILL NOW EXIT. Please deposit funds and restart.{C.RESET}"
            )
            logger.critical(
                f"{C.RED}{C.BOLD}═══════════════════════════════════════════════════════════{C.RESET}"
            )
            logger.critical("")
            self._bot_running = False
            asyncio.get_event_loop().stop()
            return

        if stake <= 0.0:
            logger.critical(
                f"{C.RED}🚨 Invalid stake: {stake:.2f}. Trading blocked.{C.RESET}"
            )
            self._bot_running = False
            asyncio.get_event_loop().stop()
            return

        current_time = time.time()
        if current_time - self.last_trade_time < self.cooldown_seconds:
            remaining = self.cooldown_seconds - (current_time - self.last_trade_time)
            logger.info(
                f"{C.GREY}⏳ Cooldown active ({remaining:.1f}s remaining){C.RESET}"
            )
            return

        async with self._trade_lock:
            self.last_trade_time = time.time()
            sig_color = C.GREEN if signal == "CALL" else C.RED

            logger.info(
                f"{C.PURPLE}⚡ EXECUTING{C.RESET} {sig_color}{signal}{C.RESET} "
                f"{C.GREY}| Stake: {C.BOLD}{stake:.2f}{C.RESET} {tiered_stake.status_tag()}"
            )

            contract_id, entry_price = await self.execute_trade_instant(
                signal, stake, symbol, currency
            )

            if not contract_id:
                logger.error(f"{C.RED}❌ Failed to execute {signal} trade.{C.RESET}")
                return

            tp, sl = self.print_trade_preview(
                signal, stake, entry_price, tp_amount, sl_amount
            )

            stats.pending_trades[contract_id] = {
                "signal": signal,
                "stake": stake,
                "entry": entry_price,
            }

            self.active_contracts[contract_id] = {
                "signal": signal,
                "stake": stake,
                "entry": entry_price,
                "is_hedge": False,
                "hedge_placed": False,
                "hedge_contract": None,
                "start_time": time.time(),
            }

            # Start TP/SL monitoring
            asyncio.create_task(
                self.monitor_tp_sl(
                    contract_id, signal, entry_price, stake, tp_amount, sl_amount
                )
            )

            # Resolve in background
            asyncio.create_task(
                self._resolve_trade(contract_id, signal, stake, entry_price)
            )

    async def _resolve_trade(self, contract_id, signal, stake, entry_price):
        profit, exit_price = await self.poll_contract_status(contract_id)

        stats.pending_trades.pop(contract_id, None)

        is_hedge = False
        hedge_info = self.active_contracts.get(contract_id, {})
        if hedge_info.get("is_hedge", False):
            is_hedge = True

        if profit is not None:
            stats.record(
                profit, contract_id, signal, stake, entry_price, exit_price, is_hedge
            )
            logger.info(stats.summary_line())
            await tiered_stake.update_stake(stats.get_current_balance())

            if stats.is_daily_stopped:
                logger.warning(f"{C.RED}🛑 {stats.daily_stop_reason}{C.RESET}")
        else:
            logger.error(
                f"{C.RED}❌ Could not determine outcome for contract {contract_id}{C.RESET}"
            )
            stats.record(0.0, contract_id, signal, stake, entry_price, 0.0, is_hedge)
            logger.info(stats.summary_line())

        self.active_contracts.pop(contract_id, None)
        self._tp_sl_triggered.discard(contract_id)

    async def trade_worker(self):
        self.heartbeat_task = asyncio.create_task(self.heartbeat())
        logger.info(
            f"{C.GREEN}💓 Heartbeat started (interval: {HEARTBEAT_INTERVAL}s){C.RESET}"
        )

        while not self._is_closing and self._bot_running:
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
        if self._is_closing or not self._bot_running:
            return
        if not tiered_stake.is_trading_allowed():
            return
        if stats.is_daily_stopped:
            return
        if stats.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
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
            except Exception:
                pass
        if self.polling_client:
            try:
                await self.polling_client.close()
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

        stake = tiered_stake.current_stake
        status = tiered_stake.status_tag()

        if tiered_stake._trading_blocked:
            logger.info(
                f"{dir_color}●{C.RESET} Price: {C.WHITE}{C.BOLD}{price:.3f}{C.RESET}  "
                f"Streak: {dir_color}{self.streak:+d}{C.RESET} {direction_emoji} {streak_meter}  "
                f"{C.GREY}│{C.RESET} {C.RED}🔴 TRADING STOPPED - INSUFFICIENT BALANCE{C.RESET}"
            )
            return "HOLD"

        logger.info(
            f"{dir_color}●{C.RESET} Price: {C.WHITE}{C.BOLD}{price:.3f}{C.RESET}  "
            f"Streak: {dir_color}{self.streak:+d}{C.RESET} {direction_emoji} {streak_meter}  "
            f"{C.GREY}│{C.RESET} Latency: {latency_color}{latency}ms{C.RESET} "
            f"{C.GREY}({tick_freq}){C.RESET}  "
            f"{C.GREY}│{C.RESET} Next Stake: {C.WHITE}{stake:.2f} {CURRENCY}{C.RESET} {status}  "
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
    banner = f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════════╗
║             🤖  DERIV TIERED-RISK BOT  🤖                  ║
║        FIXED NUMERIC TP/SL HEDGING STRATEGY               ║
║              ★ FULLY FIXED VERSION ★                      ║
╚══════════════════════════════════════════════════════════╝{C.RESET}
{C.GREY}  Symbol:{C.RESET} {C.WHITE}{SYMBOL}{C.RESET}   {C.GREY}Target Streak:{C.RESET} {C.WHITE}{TARGET_STREAK}{C.RESET}   {C.GREY}Duration:{C.RESET} {C.WHITE}{CONTRACT_DURATION} ticks{C.RESET}
  
  {C.BOLD}{C.GREEN}📊 TIERED RISK MANAGEMENT (NO MARTINGALE){C.RESET}
  {C.GREY}  Minimum Balance:{C.RESET} ${ABSOLUTE_MIN_BALANCE:.2f}  {C.GREY}|{C.RESET} Minimum Stake: ${ABSOLUTE_MIN_STAKE:.2f}
  
  {C.GREY}  Tier 1 (${TIER_1_MIN:.0f}-${TIER_1_MAX:.0f}):{C.RESET} Stake ${TIER_1_STAKE:.2f} | TP ${TIER_1_TP:.2f} | SL ${TIER_1_SL:.2f}
  {C.GREY}  Tier 2 (${TIER_2_MIN:.0f}-${TIER_2_MAX:.0f}):{C.RESET} Stake ${TIER_2_STAKE:.2f} | TP ${TIER_2_TP:.2f} | SL ${TIER_2_SL:.2f}
  {C.GREY}  Tier 3 (${TIER_3_MIN:.0f}-${TIER_3_MAX:.0f}):{C.RESET} Stake ${TIER_3_STAKE:.2f} | TP ${TIER_3_TP:.2f} | SL ${TIER_3_SL:.2f}
  {C.GREY}  Tier 4 (${TIER_4_MIN:.0f}-${TIER_4_MAX:.0f}):{C.RESET} Stake ${TIER_4_STAKE:.2f} | TP ${TIER_4_TP:.2f} | SL ${TIER_4_SL:.2f}
  {C.GREY}  Tier 5 (${TIER_5_MIN:.0f}+):{C.RESET} {TIER_5_RISK_PERCENT}% stake | {TIER_5_TP_PERCENT}% TP | {TIER_5_SL_PERCENT}% SL

  {C.BOLD}{C.YELLOW}🎯 TP/SL CONFIGURATION - FIXED:{C.RESET}
  {C.GREY}  Take Profit:{C.RESET} Fixed numeric values per tier  {C.GREY}|{C.RESET} Stop Loss: Fixed numeric values per tier
  {C.GREY}  Monitor Interval:{C.RESET} {TP_SL_MONITOR_INTERVAL}s  {C.GREY}|{C.RESET} Slippage Tolerance: ±{TP_SL_SLIPPAGE_TOLERANCE}
  {C.GREY}  Hedge Stake:{C.RESET} {HEDGE_STAKE_MULTIPLIER}x original  {C.GREY}|{C.RESET} Immediate Hedge Execution

  {C.BOLD}{C.YELLOW}🛑 RISK LIMITS:{C.RESET}
  {C.GREY}  Daily Loss Limit:{C.RESET} {DAILY_LOSS_LIMIT_PERCENT}%  {C.GREY}|{C.RESET} Daily Profit Target: {DAILY_PROFIT_TARGET_PERCENT}%
  {C.GREY}  Max Consecutive Losses:{C.RESET} {MAX_CONSECUTIVE_LOSSES}

  {C.GREEN}⚡ FEATURES: Fixed Numeric TP/SL | Hedging | Flat Staking | Slippage Tolerance{C.RESET}
  {C.GREY}💓 Heartbeat: {HEARTBEAT_INTERVAL}s | Max Reconnect: {MAX_RECONNECT_ATTEMPTS}{C.RESET}
"""
    print(banner)


# ==================== MAIN ====================
async def main():
    if not API_TOKEN:
        logger.error("Execution stopped: Missing Token in environment variables.")
        return

    print_banner()

    initial_balance = stats.initial_balance
    if initial_balance < ABSOLUTE_MIN_BALANCE:
        logger.critical("")
        logger.critical(
            f"{C.RED}{C.BOLD}═══════════════════════════════════════════════════════════{C.RESET}"
        )
        logger.critical(f"{C.RED}{C.BOLD}🚨 INITIAL BALANCE CHECK FAILED{C.RESET}")
        logger.critical(
            f"{C.RED}{C.BOLD}═══════════════════════════════════════════════════════════{C.RESET}"
        )
        logger.critical(f"{C.RED}  Current Balance: ${initial_balance:.2f}{C.RESET}")
        logger.critical(
            f"{C.RED}  Minimum Required: ${ABSOLUTE_MIN_BALANCE:.2f}{C.RESET}"
        )
        logger.critical(
            f"{C.RED}  Shortfall: ${ABSOLUTE_MIN_BALANCE - initial_balance:.2f}{C.RESET}"
        )
        logger.critical(
            f"{C.RED}{C.BOLD}═══════════════════════════════════════════════════════════{C.RESET}"
        )
        logger.critical(
            f"{C.RED}  🛑 BOT CANNOT START. Please deposit funds and restart.{C.RESET}"
        )
        logger.critical(
            f"{C.RED}{C.BOLD}═══════════════════════════════════════════════════════════{C.RESET}"
        )
        logger.critical("")
        return

    logger.info(
        f"{C.GREY}🚀 Starting bot at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}"
    )
    logger.info(
        f"{C.GREY}💰 Starting Balance: {stats.initial_balance} {CURRENCY}{C.RESET}"
    )
    logger.info(
        f"{C.GREEN}📊 Initial Stake: {tiered_stake.current_stake} {CURRENCY}{C.RESET}"
    )
    logger.info(
        f"{C.GREEN}📊 TP: ${tiered_stake.current_tp:.2f} | SL: ${tiered_stake.current_sl:.2f}{C.RESET}"
    )
    logger.info(f"{C.GREEN}📊 Minimum Balance: ${ABSOLUTE_MIN_BALANCE:.2f}{C.RESET}")
    logger.info(f"{C.CYAN}📊 Slippage Tolerance: ±{TP_SL_SLIPPAGE_TOLERANCE}{C.RESET}")

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
            if not trade_manager._bot_running:
                logger.warning(
                    f"{C.YELLOW}🛑 Bot stopping due to trading block...{C.RESET}"
                )
                break

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
