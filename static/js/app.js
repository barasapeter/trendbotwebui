// ==========================================================================
// DOM references
// ==========================================================================
const feedBody = document.getElementById("feedBody");
const runBtn = document.getElementById("runBtn");
const connDot = document.getElementById("connDot");
const connLabel = document.getElementById("connLabel");
const balanceEl = document.getElementById("balance");
const plEl = document.getElementById("PL");
const modeButtons = document.querySelectorAll(".mode-btn");
const waitingIndicator = document.getElementById("waitingIndicator");
const waitingText = document.getElementById("waitingText");
let streamEnded = false;



// ==========================================================================
// Run Button State Management
// ==========================================================================
const RunButtonState = {
  CONNECTING: 'connecting',
  READY: 'ready',
  INITIALIZING: 'initializing',
  RUNNING: 'running',
  CLOSED: 'closed'
};

let currentRunButtonState = RunButtonState.CONNECTING;
let isBotRunning = false; // Track bot running state independently
let isInitializing = false; // Track initialization state

function updateRunButton(state, customText = null) {
  currentRunButtonState = state;
  
  switch(state) {
    case RunButtonState.CONNECTING:
      runBtn.disabled = true;
      runBtn.textContent = "Connecting...";
      break;
    case RunButtonState.READY:
      // Only enable if bot is NOT running and NOT initializing
      if ((!isBotRunning && !isInitializing) || streamEnded) {
        runBtn.disabled = false;
        runBtn.textContent = customText || "Run Bot";
      } else {
        // If bot is running or initializing, keep it disabled
        runBtn.disabled = true;
        if (isBotRunning) {
          runBtn.textContent = "Bot running...";
        } else if (isInitializing) {
          runBtn.textContent = "Initializing...";
        }
      }
      break;
    case RunButtonState.INITIALIZING:
      isInitializing = true;
      runBtn.disabled = true;
      runBtn.textContent = "Initializing...";
      break;
    case RunButtonState.RUNNING:
      isInitializing = false; // Clear initializing flag when running starts
      isBotRunning = true;
      runBtn.disabled = true;
      runBtn.textContent = "Bot running...";
      break;
    case RunButtonState.CLOSED:
      isInitializing = false;
      isBotRunning = false;
      runBtn.disabled = true;
      runBtn.textContent = "Connection closed";
      break;
    default:
      runBtn.disabled = true;
      runBtn.textContent = "Connecting...";
  }
}

function setWaiting(state) {
  // state: "connecting" | "watching" | "down"
  if (state === "connecting") {
    waitingIndicator.classList.remove("paused");
    waitingText.textContent = "Connecting…";
  } else if (state === "watching") {
    waitingIndicator.classList.remove("paused");
    waitingText.textContent = "Watching for the next update…";
  } else {
    waitingIndicator.classList.add("paused");
    waitingText.textContent = "Connected";
  }
}

let selectedMode = "demo";

modeButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    modeButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    selectedMode = btn.dataset.mode;
  });
});

// ==========================================================================
// Accent system — every status word the server sends maps to one of five
// signal colors. This is the single source of truth for "is this good,
// bad, cautionary, or informational".
// ==========================================================================
const ACCENT = {
  success: "profit",
  profit: "profit",
  win: "profit",
  error: "loss",
  loss: "loss",
  warning: "warn",
  info: "info",
  breakeven: "info",
};

function accentFor(status) {
  return ACCENT[status] || "info";
}

// ==========================================================================
// Feed primitives
// ==========================================================================
function clearEmptyState() {
  const empty = feedBody.querySelector(".feed-empty");
  if (empty) empty.remove();
}

function makeFieldList(fields) {
  const dl = document.createElement("dl");
  dl.className = "field-list";
  fields.forEach(([label, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    dl.appendChild(dt);
    dl.appendChild(dd);
  });
  return dl;
}

function makeBadge(text, accent) {
  const span = document.createElement("span");
  span.className = `badge ${accent}`;
  span.textContent = text;
  return span;
}

/**
 * Prepends a rail item (dot + connecting line + card) to the feed.
 * `accent` drives both the rail dot color and the card theme.
 */
function pushFeedItem(accent, cardEl) {
  clearEmptyState();
  if (ws.readyState === WebSocket.OPEN) setWaiting("watching");

  const item = document.createElement("div");
  item.className = "feed-item";

  const rail = document.createElement("div");
  rail.className = "feed-rail";
  const dot = document.createElement("div");
  dot.className = `feed-dot ${accent}`;
  const line = document.createElement("div");
  line.className = `feed-line ${accent}`;
  rail.appendChild(dot);
  rail.appendChild(line);

  item.appendChild(rail);
  item.appendChild(cardEl);

  feedBody.prepend(item);
}

function makeCard(title, accent, extraClass = "") {
  const card = document.createElement("div");
  card.className = `feed-card ${accent} ${extraClass}`.trim();
  const h = document.createElement("h3");
  h.className = "card-title";
  h.textContent = title;
  card.appendChild(h);
  return card;
}

// ==========================================================================
// Widget renderers — one function per `trade_stream.widget` type, each
// using the element that actually fits its content (definition lists for
// key/value pairs, a badge for outcome words, a metric line for the number
// that matters most).
// ==========================================================================
const RENDERERS = {
  session_initializer(data) {
    const card = makeCard(data.title, "info");
    const m = data.metadata;
    card.appendChild(
      makeFieldList([
        ["Risk Engine", m.risk_engine],
        ["Selection Mode", m.selection_mode],
        ["Starting Balance", m.starting_balance],
        ["Take Profit Goal", m.take_profit_goal],
        ["Max Stop Loss", m.max_stop_loss],
      ])
    );
    pushFeedItem("info", card);
  },

  snackbar(data) {
    const accent = accentFor(data.metadata.status);
    const card = makeCard(data.title, accent);
    const p = document.createElement("p");
    p.className = "card-message";
    p.textContent = data.metadata.message;
    card.appendChild(p);
    pushFeedItem(accent, card);
  },

  detailed_snackbar(data) {
    const accent = accentFor(data.metadata.status);
    const card = makeCard(data.title, accent);
    const m = data.metadata;
    const p = document.createElement("p");
    p.className = "card-message";
    p.textContent = m.message;
    card.appendChild(p);
    card.appendChild(
      makeFieldList([
        ["Stake", m.stake],
        ["Remaining Loss Budget", m.remaining_loss_budget],
      ])
    );
    pushFeedItem(accent, card);
  },

  session_summary(data) {
    const m = data.metadata;
    const isCompletion = m.initial_balance !== undefined;

    if (isCompletion) {
      const accent = accentFor(m.status);
      const card = makeCard(data.title, accent);
      card.appendChild(
        makeFieldList([
          ["Initial Balance", `${m.initial_balance} ${m.currency}`],
          ["Final Balance", `${m.final_balance} ${m.currency}`],
          ["Net Delta", `${m.net_delta} ${m.currency}`],
        ])
      );
      pushFeedItem(accent, card);
      return;
    }

    // Per-trade dashboard header — informational, not a win/loss signal.
    const card = makeCard(data.title, "info", "neutral");
    card.appendChild(
      makeFieldList([
        ["Balance Before", `${m.balance_before} ${m.currency}`],
        ["Market Context", m.market_context],
        ["Direction", m.direction],
        ["Stake", `${m.stake} ${m.currency}`],
      ])
    );
    pushFeedItem("info", card);
  },

  trade_result(data) {
    const m = data.metadata;
    const accent = accentFor(m.status);
    const card = makeCard(data.title, accent);
    card.querySelector(".card-title").appendChild(
      makeBadge(m.outcome, accent)
    );

    const metric = document.createElement("p");
    metric.className = `card-metric ${accent === "loss" ? "loss" : accent === "profit" ? "profit" : "neutral"}`;
    const sign = m.profit > 0 ? "+" : "";
    metric.textContent = `${sign}${m.profit} ${m.currency}`;
    card.appendChild(metric);

    card.appendChild(
      makeFieldList([
        ["Balance After", `${m.balance_after} ${m.currency}`],
        ["Session Net P&L", `${m.session_net_pnl} ${m.currency}`],
      ])
    );
    pushFeedItem(accent, card);
  },

  risk_alert(data) {
    const accent = accentFor(data.metadata.status);
    const card = makeCard(data.title, accent);
    const m = data.metadata;
    const p = document.createElement("p");
    p.className = "card-message";
    p.textContent = m.message;
    card.appendChild(p);
    card.appendChild(
      makeFieldList([
        ["Current Stake", m.stake],
        ["Maximum Allowed Stake", m.max_stake],
      ])
    );
    pushFeedItem(accent, card);
  },

  cumulative_status(data) {
    const m = data.metadata;
    const accent = accentFor(m.status);
    const card = makeCard(data.title, accent);
    card.appendChild(
      makeFieldList([
        ["Starting Balance", `${m.starting_balance} ${m.currency}`],
        ["Current Balance", `${m.current_balance} ${m.currency}`],
        ["Cumulative Net P&L", `${m.cumulative_net_pnl} ${m.currency}`],
      ])
    );
    pushFeedItem(accent, card);
  },

  notification(data) {
    const accent = accentFor(data.metadata.status);
    const card = makeCard(data.title, accent);
    const m = data.metadata;
    const p = document.createElement("p");
    p.className = "card-message";
    p.textContent = m.message;
    card.appendChild(p);

    const extra = [];
    if (m.duration_seconds !== undefined) extra.push(["Duration", `${m.duration_seconds}s`]);
    if (m.signal !== undefined) extra.push(["Signal", m.signal]);
    if (extra.length) card.appendChild(makeFieldList(extra));

    pushFeedItem(accent, card);
  },

  bot_shutdown_summary(data) {
    const m = data.metadata;
    const statusAccent = accentFor(m.status);
    const card = makeCard(data.title, "gold", "shutdown");
    card.querySelector(".card-title").appendChild(makeBadge(m.status, statusAccent));
    card.appendChild(
      makeFieldList([
        ["Sessions Run", m.sessions_run],
        ["Starting Balance", `${m.starting_balance} ${m.currency}`],
        ["Final Balance", `${m.final_balance} ${m.currency}`],
        ["All-Time Net P&L", `${m.all_time_net_pnl} ${m.currency}`],
      ])
    );
    pushFeedItem("gold", card);
  },
};

function renderTradeStream(ts) {
  const renderer = RENDERERS[ts.widget];
  if (renderer) renderer(ts);
}

// ==========================================================================
// Plain system log lines (connection acks, non-widget status strings)
// ==========================================================================
function pushLogLine(text, color) {
  clearEmptyState();
  const line = document.createElement("div");
  line.className = "log-line";
  if (color) line.style.color = color;
  line.textContent = text;
  feedBody.prepend(line);
}

// ==========================================================================
// WebSocket wiring
// ==========================================================================
const ws = new WebSocket(`ws://${window.location.host}/ws`);

// Initialize button in connecting state
updateRunButton(RunButtonState.CONNECTING);

runBtn.onclick = () => {
  if (ws.readyState !== WebSocket.OPEN) {
    // Should not happen as button should be disabled, but guard anyway
    return;
  }
  
  updateRunButton(RunButtonState.INITIALIZING);
  ws.send(
    JSON.stringify({
      action: "run_bot",
      mode: selectedMode,
      stake: 5,
    })
  );
};

ws.onopen = () => {
  connDot.classList.remove("down");
  connDot.classList.add("live");
  connLabel.textContent = "Connected";
  
  // Only set to READY if bot is NOT running and NOT initializing
  if (!isBotRunning && !isInitializing) {
    updateRunButton(RunButtonState.READY);
  } else if (isBotRunning) {
    // Bot is running, keep it in RUNNING state
    updateRunButton(RunButtonState.RUNNING);
  } else if (isInitializing) {
    // Still initializing, keep it in INITIALIZING state
    updateRunButton(RunButtonState.INITIALIZING);
  }
  
  setWaiting("waiting");
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  

  if (data.trade_stream && data.trade_stream.balance) {
    balanceEl.textContent = data.trade_stream.balance;
  }

  // Check if bot is running - this takes priority over all other states
  if (data.bot && data.bot.running || data.trade_stream && data.trade_stream.bot.running) {
    isBotRunning = true;
    isInitializing = false; // Clear initializing flag when bot starts running
    updateRunButton(RunButtonState.RUNNING);
  } else {
    // Bot is not running
    isBotRunning = false;
    // Only reset to READY if we're not in CONNECTING or CLOSED state
    // and we're not currently initializing
    if (currentRunButtonState !== RunButtonState.CONNECTING && 
        currentRunButtonState !== RunButtonState.CLOSED &&
        !isInitializing) {
      updateRunButton(RunButtonState.READY);
    } else if (isInitializing) {
      // Keep it in INITIALIZING state
      updateRunButton(RunButtonState.INITIALIZING);
    }
  }

  



  if (data.balance !== undefined && data.pl !== undefined) {
    balanceEl.textContent = data.balance;
    plEl.textContent = data.pl;
    plEl.classList.remove("pl-positive", "pl-negative");
    const numeric = parseFloat(data.pl);
    if (!Number.isNaN(numeric)) {
      plEl.classList.add(numeric >= 0 ? "pl-positive" : "pl-negative");
    }
  }

  if (data.status) {
    pushLogLine(data.status, data.color);
  }

  if (data.trade_stream) {
    renderTradeStream(data.trade_stream);
  }

  if (data.trade_stream && data.trade_stream.end_of_stream) {
    waitingText.textContent = "Trade Completed";
    waitingIndicator.classList.add("paused");
    streamEnded = true;
    updateRunButton(RunButtonState.READY);

  } else {
    // reset stream ended
    streamEnded = false;
  }
};

ws.onclose = (event) => {
  connDot.classList.remove("live");
  connDot.classList.add("down");
  connLabel.textContent = "Disconnected";
  
  // Reset bot running and initializing flags when connection closes
  isBotRunning = false;
  isInitializing = false;
  
  // When connection closes, button should always be disabled and show "Connection closed"
  updateRunButton(RunButtonState.CLOSED);
  setWaiting("down");
};

ws.onerror = () => {
  connDot.classList.remove("live");
  connDot.classList.add("down");
  connLabel.textContent = "Connection error";
  
  // Reset bot running and initializing flags on error
  isBotRunning = false;
  isInitializing = false;
  
  updateRunButton(RunButtonState.CLOSED);
  setWaiting("down");
};

window.addEventListener("pagehide", () => {
  if (ws.readyState === WebSocket.OPEN) ws.close(1000, "Page unloaded");
});

window.addEventListener("beforeunload", () => {
  if (ws.readyState === WebSocket.OPEN) ws.close(1000, "Page unloading");
});