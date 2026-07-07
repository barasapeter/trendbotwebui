"""schemas.py

Pydantic models describing:
  - the trade configuration a client sends to start a bot run (this replaces
    the module-level constants that used to live at the top of
    rapid_exit_inf.py)
  - the envelope used for every message sent client <-> server over the
    websocket
"""

from typing import Optional, Literal, Any
from pydantic import BaseModel, Field


class TradeConfig(BaseModel):
    # Account / connection
    mode: Literal["demo", "real"] = "demo"

    # Strategy selection
    strategy_type: Literal["MARTINGALE", "D_ALEMBERT"] = "MARTINGALE"
    direction_mode: Literal["TREND_FOLLOW", "CALL", "PUT", "ALTERNATE"] = "TREND_FOLLOW"

    # Core trade parameters
    symbol: str = "R_100"
    duration: int = 5
    duration_unit: str = "t"
    currency: str = "USD"

    # Stake / risk parameters
    initial_stake: float = 1.3
    max_stake: float = 5.0
    profit_threshold: float = 1.0
    loss_threshold: float = 6.0
    stake_multiplier: float = 1.1
    stake_increment: float = 1.0

    # Looping behaviour
    inter_session_pause: float = 5.0
    # null / omitted -> run forever until stopped or Ctrl+C-equivalent (client "stop")
    max_sessions: Optional[int] = 1


class ClientMessage(BaseModel):
    """Messages the client sends to the server over the websocket."""

    type: Literal["start", "stop", "ping"]
    config: Optional[TradeConfig] = None


class ServerMessage(BaseModel):
    """Every message the server pushes to the client is one of these."""

    type: str
    data: Any = Field(default_factory=dict)
