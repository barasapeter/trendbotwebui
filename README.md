# Deriv Trading Bot — FastAPI / WebSocket version

Refactor of the old terminal script (`rapid_exit_inf.py`) into a service:
one client-server WebSocket connection carries both the trade
configuration and the live trade/market stream, so any front end (web,
desktop, mobile) can render it instead of reading colored terminal text.

## Files

- `main.py` — FastAPI app, single `/ws` endpoint, handles start/stop.
- `bot.py` — the trading engine (session loop, martingale/d'alembert
  staking, trend-follow direction picking, stop-loss guardrails). Same
  logic as the original `rapid_exit_inf.py`, but config-driven and it
  emits JSON events instead of printing.
- `schemas.py` — `TradeConfig` (what a client can configure) and the
  message envelopes.
- `auth.py`, `deriv_client.py` — unchanged in spirit from the original;
  the server still holds the Deriv API token via `.env`. Clients never see
  or send credentials — only trade parameters.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` next to `main.py` (same as before):

```
TOKEN=your_deriv_api_token
APP_ID=your_app_id
```

Run it:

```bash
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** — that serves `static/index.html`, a
vanilla HTML/CSS/JS console: a config sidebar (mirrors every `TradeConfig`
field), Connect/Start/Stop controls, a scrolling "ticker tape" of live
events, session/PnL cards, and a trade log table. No build step, no
frameworks — just open the page. It talks to `/ws` using the exact
protocol described below, so you can also swap in your own frontend later
without touching the backend.

## Protocol

Connect to `ws://localhost:8000/ws`.

**Start a run** — every field is optional; omitted fields fall back to the
same defaults the original script hard-coded:

```json
{
  "type": "start",
  "config": {
    "mode": "demo",
    "strategy_type": "MARTINGALE",
    "direction_mode": "TREND_FOLLOW",
    "symbol": "R_100",
    "duration": 5,
    "duration_unit": "t",
    "currency": "USD",
    "initial_stake": 1.3,
    "max_stake": 5.0,
    "profit_threshold": 1.0,
    "loss_threshold": 6.0,
    "stake_multiplier": 1.1,
    "stake_increment": 1.0,
    "inter_session_pause": 5,
    "max_sessions": 1
  }
}
```

Set `"max_sessions": null` to run indefinitely (until the client sends
`stop` or disconnects) — same as the old `MAX_SESSIONS = math.inf`.

**Stop the run in progress:**

```json
{"type": "stop"}
```

**Server pushes** a stream of `{"type": ..., "data": {...}}` events as the
bot runs: `connected`, `session_start`, `trade_dashboard`, `trade_result`,
`stake_clamped`, `order_rejected`, `max_stake_guardrail`,
`session_target_reached`, `session_stop_loss_breached`,
`session_summary`, `cumulative_status`, `inter_session_pause`,
`stopped_by_client`, `shutdown`, `error`. Map these to whatever UI
components you like (a live dashboard row, a running P/L chart, toasts for
guardrail/error events, etc.).

## Notes / things worth deciding before production use

- Only one bot run per socket connection at a time (matches the original,
  which only ever ran one instance).
- If a real trading account is used, double check `loss_threshold` /
  `max_stake` guardrails against your real risk tolerance before pointing
  `mode` at `"real"`.
- This still has no persistence/auth layer of its own — anyone who can open
  a websocket to this server can start a bot run. Put it behind your own
  auth/session layer before exposing it beyond localhost.
