// ==========================================================================
// DOM references
// ==========================================================================
const feedBody = document.getElementById("feedBody");
const runBtn = document.getElementById("runBtn");
const stopBtn = document.getElementById("stopBtn");
const connDot = document.getElementById("connDot");
const connLabel = document.getElementById("connLabel");
const balanceEl = document.getElementById("balance");
const plEl = document.getElementById("PL");
const modeButtons = document.querySelectorAll(".mode-btn");
const waitingIndicator = document.getElementById("waitingIndicator");
const waitingText = document.getElementById("waitingText");
let streamEnded = false;

const input = document.getElementById("lossTolerance");

input.addEventListener("input", () => {
    if (input.value === "") return;
    input.value = Math.min(85, Math.max(0.001, Number(input.value)));
});

// ==========================================================================
// Mode state management with persistence
// ==========================================================================
// Try to load saved mode from localStorage, fallback to "demo"
let selectedMode = localStorage.getItem("selectedMode") || "demo";

// Update UI to reflect saved mode
modeButtons.forEach((btn) => {
  if (btn.dataset.mode === selectedMode) {
    btn.classList.add("active");
  } else {
    btn.classList.remove("active");
  }
});

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
let isBotRunning = false;
let isInitializing = false;

function updateRunButton(state, customText = null) {
  currentRunButtonState = state;
  
  switch(state) {
    case RunButtonState.CONNECTING:
      runBtn.disabled = true;
      runBtn.textContent = "Connecting...";
      break;
    case RunButtonState.READY:
      if ((!isBotRunning && !isInitializing) || streamEnded) {
        runBtn.disabled = false;
        runBtn.textContent = customText || "Run Bot";
      } else {
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
      isInitializing = false;
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
  if (state === "connecting") {
    waitingIndicator.classList.remove("paused");
    waitingText.textContent = "Connecting…";
  } else if (state === "watching") {
    waitingIndicator.classList.remove("paused");
    waitingText.textContent = "";
  } else {
    waitingIndicator.classList.add("paused");
    waitingText.textContent = "Connected";
  }
}

// ==========================================================================
// Mode selection with persistence and balance refresh
// ==========================================================================
modeButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    // Check if this is actually a change
    if (btn.dataset.mode === selectedMode) {
      // If clicking the same mode, still refresh balance
      refreshBalanceForCurrentMode();
      return;
    }
    
    // Update UI
    modeButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    
    // Save selected mode
    selectedMode = btn.dataset.mode;
    localStorage.setItem("selectedMode", selectedMode);
    
    // Reset initial balance when switching modes
    initialBal = 0;
    
    // Show skeleton while loading new balance
    showSkeleton(balanceEl, 'number');
    showSkeleton(plEl, 'number');
    
    // Refresh balance for the new mode
    refreshBalanceForCurrentMode();
  });
});

// ==========================================================================
// Refresh balance for current mode
// ==========================================================================
function refreshBalanceForCurrentMode() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    console.log(`Requesting balance for mode: ${selectedMode}`);
    ws.send(JSON.stringify({
      action: "get_balance",
      mode: selectedMode
    }));
  } else {
    console.warn("WebSocket not open, cannot refresh balance");
    // Try again when connection opens
    pendingBalanceRequest = true;
  }
}

let pendingBalanceRequest = false;

// ==========================================================================
// Accent system
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
// Widget renderers
// ==========================================================================
const RENDERERS = {
  session_initializer(data) {
    const card = makeCard(data.title, "info");
    const m = data.metadata;
    card.appendChild(
      makeFieldList([
        ["Risk Engine", m.risk_engine],
        ["Selection Mode", m.selection_mode],
        ["Starting Balance", formatNumberWithCommas(m.starting_balance)],
        ["Take Profit Goal", formatNumberWithCommas(m.take_profit_goal)],
        ["Max Stop Loss", formatNumberWithCommas(m.max_stop_loss)],
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
        ["Stake", formatNumberWithCommas(m.stake)],
        ["Remaining Loss Budget", formatNumberWithCommas(m.remaining_loss_budget)],
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
          ["Initial Balance", `${formatNumberWithCommas(m.initial_balance)} ${m.currency}`],
          ["Final Balance", `${formatNumberWithCommas(m.final_balance)} ${m.currency}`],
          ["Net Delta", `${formatNumberWithCommas(m.net_delta)} ${m.currency}`],
        ])
      );
      pushFeedItem(accent, card);
      return;
    }

    const card = makeCard(data.title, "info", "neutral");
    card.appendChild(
      makeFieldList([
        ["Balance Before", `${formatNumberWithCommas(m.balance_before)} ${m.currency}`],
        ["Market Context", m.market_context],
        ["Direction", m.direction],
        ["Stake", `${formatNumberWithCommas(m.stake)} ${m.currency}`],
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
    metric.textContent = `${sign}${formatNumberWithCommas(m.profit)} ${m.currency}`;
    card.appendChild(metric);

    card.appendChild(
      makeFieldList([
        ["Balance After", `${formatNumberWithCommas(m.balance_after)} ${m.currency}`],
        ["Session Net P&L", `${formatNumberWithCommas(m.session_net_pnl)} ${m.currency}`],
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
        ["Current Stake", formatNumberWithCommas(m.stake)],
        ["Maximum Allowed Stake", formatNumberWithCommas(m.max_stake)],
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
        ["Starting Balance", `${formatNumberWithCommas(m.starting_balance)} ${m.currency}`],
        ["Current Balance", `${formatNumberWithCommas(m.current_balance)} ${m.currency}`],
        ["Cumulative Net P&L", `${formatNumberWithCommas(m.cumulative_net_pnl)} ${m.currency}`],
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
    const card = makeCard(data.title, "profit-dim", "shutdown");
    card.querySelector(".card-title").appendChild(makeBadge(m.status, statusAccent));
    card.appendChild(
      makeFieldList([
        ["Sessions Run", m.sessions_run],
        ["Starting Balance", `${formatNumberWithCommas(m.starting_balance)} ${m.currency}`],
        ["Final Balance", `${formatNumberWithCommas(m.final_balance)} ${m.currency}`],
        ["All-Time Net P&L", `${formatNumberWithCommas(m.all_time_net_pnl)} ${m.currency}`],
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
// Plain system log lines
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
// Format numbers to 2 decimal places with commas
// ==========================================================================
function formatNumberWithCommas(value) {
  if (value === undefined || value === null) return "0.00";
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return "0.00";
  
  // Format with commas and 2 decimal places
  const parts = num.toFixed(2).split('.');
  const integerPart = parts[0];
  const decimalPart = parts[1];
  
  // Add commas to integer part
  const withCommas = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  
  return `${withCommas}.${decimalPart}`;
}

function formatNumber(value) {
  if (value === undefined || value === null) return "0.00";
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return "0.00";
  return num.toFixed(2);
}

function formatPL(value) {
  if (value === undefined || value === null) return "+0.00";
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return "+0.00";
  const formatted = Math.abs(num).toFixed(2);
  return num >= 0 ? `+${formatted}` : `-${formatted}`;
}

// ==========================================================================
// Skeleton loader helpers
// ==========================================================================
function showSkeleton(element, type = 'number') {
  if (!element) return;
  element.classList.add('skeleton');
  if (type === 'number') {
    element.classList.add('skeleton-number');
  } else {
    element.classList.add('skeleton-text');
  }
  element.textContent = 'Loading...';
}

function hideSkeleton(element) {
  if (!element) return;
  element.classList.remove('skeleton', 'skeleton-number', 'skeleton-text');
}

// ==========================================================================
// Update balance and PL display
// ==========================================================================
function updateBalanceAndPL(balance, pl) {
  if (balance !== undefined && balance !== null) {
    const balanceNum = typeof balance === 'string' ? parseFloat(balance) : balance;
    if (!isNaN(balanceNum)) {
      hideSkeleton(balanceEl);
      balanceEl.textContent = formatNumberWithCommas(balanceNum);
      
      // Update balance color based on change from initial
      if (initialBal !== 0 && balanceNum < initialBal) {
        balanceEl.style.color = "red";
      } else {
        balanceEl.style.color = "#1fa971";
      }
    }
  }
  
  if (pl !== undefined && pl !== null) {
    const plNum = typeof pl === 'string' ? parseFloat(pl) : pl;
    if (!isNaN(plNum)) {
      hideSkeleton(plEl);
      plEl.textContent = formatPL(plNum);
      
      // Update PL color
      if (plNum < 0) {
        plEl.style.color = "red";
        plEl.classList.remove("pl-positive");
        plEl.classList.add("pl-negative");
      } else {
        plEl.style.color = "#1fa971";
        plEl.classList.remove("pl-negative");
        plEl.classList.add("pl-positive");
      }
    }
  }
}

// ==========================================================================
// Update connection indicators
// ==========================================================================
function updateConnectionIndicators(connected) {
  if (connected) {
    connDot.classList.remove("down");
    connDot.classList.add("live");
    connLabel.textContent = "Connected";
    setWaiting("watching");
  } else {
    connDot.classList.remove("live");
    connDot.classList.add("down");
    connLabel.textContent = "Disconnected";
    setWaiting("down");
  }
}

// ==========================================================================
// WebSocket wiring
// ==========================================================================
const ws = new WebSocket(`ws://${window.location.host}/ws`);

// Initialize UI
updateRunButton(RunButtonState.CONNECTING);
setWaiting("connecting");
let initialBal = 0;

// Force initial connection dot state to show "connecting"
connDot.classList.remove("live");
connDot.classList.add("down");
connLabel.textContent = "Connecting...";

// Set initial balance and PL to show skeleton loaders
showSkeleton(balanceEl, 'number');
showSkeleton(plEl, 'number');

// Handle WebSocket open event
ws.onopen = () => {
  // Update connection indicators
  updateConnectionIndicators(true);
  
  // Request initial balance with current mode
  refreshBalanceForCurrentMode();
  
  // Handle any pending balance requests
  if (pendingBalanceRequest) {
    pendingBalanceRequest = false;
    refreshBalanceForCurrentMode();
  }
  
  // Update button state
  if (!isBotRunning && !isInitializing) {
    updateRunButton(RunButtonState.READY);
  } else if (isBotRunning) {
    updateRunButton(RunButtonState.RUNNING);
  } else if (isInitializing) {
    updateRunButton(RunButtonState.INITIALIZING);
  }
};

// Handle WebSocket messages
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  // Handle balance and PL updates from trade_stream
  if (data.trade_stream) {
    stopBtn.style.display = "block";
    if (data.trade_stream.widget == "bot_shutdown_summary") {
      stopBtn.style.display = "none";
      updateRunButton(RunButtonState.READY);
    }
    if (data.trade_stream.title == "STOP COMMAND RECEIVED") {
      stopBtn.textContent = "Bot Stopped";
      setTimeout(() => {
          // stopBtn.style.display = "none";
          stopBtn.disabled=true;
      }, 1000);
    } else {
      

    }
    // Update balance if present
    if (data.trade_stream.balance !== undefined) {
      const balance = data.trade_stream.balance;
      const pl = data.trade_stream.pl !== undefined ? data.trade_stream.pl : 0;
      
      // Store initial balance if not set
      if (initialBal === 0 && balance !== undefined) {
        initialBal = typeof balance === 'string' ? parseFloat(balance) : balance;
      }
      
      updateBalanceAndPL(balance, pl);
    }
    
    // Render the trade stream
    renderTradeStream(data.trade_stream);
    
    // Check for end of stream
    if (data.trade_stream.end_of_stream) {
      waitingText.textContent = "";
      waitingIndicator.classList.add("paused");
      streamEnded = true;
      updateRunButton(RunButtonState.READY);
      stopBtn.style.display = "none";
      stopBtn.disabled = true;
    } else {
      streamEnded = false;
    }
  }
  
  // Handle separate balance update response (from get_balance action)
  if (data.balance !== undefined || data.pl !== undefined) {
    const balance = data.balance;
    const pl = data.pl !== undefined ? data.pl : 0;
    
    if (balance !== undefined && initialBal === 0) {
      initialBal = typeof balance === 'string' ? parseFloat(balance) : balance;
    }
    
    updateBalanceAndPL(balance, pl);
  }

  // Check if bot is running
  if (data.bot && data.bot.running) {
    stopBtn.textContent = "Stop";
    stopBtn.disabled = false;
    isBotRunning = true;
    isInitializing = false;
    updateRunButton(RunButtonState.RUNNING);
  } else if (data.trade_stream && data.trade_stream.bot && data.trade_stream.bot.running) {
    isBotRunning = true;
    isInitializing = false;
    updateRunButton(RunButtonState.RUNNING);
  } else {
    // Only update if bot state changes
    const wasRunning = isBotRunning;
    isBotRunning = false;

    waitingIndicator.classList.add("paused");
    updateRunButton(RunButtonState.READY);
    
    // Reset button state if it was running and we got a non-running response
    if (wasRunning && !data.bot?.running && !data.trade_stream?.bot?.running) {
      if (currentRunButtonState !== RunButtonState.CONNECTING && 
          currentRunButtonState !== RunButtonState.CLOSED &&
          !isInitializing) {
        updateRunButton(RunButtonState.READY);
      }
    }
  }

  // Handle status messages
  if (data.status) {
    pushLogLine(data.status, data.color);
  }
};

// Handle WebSocket close
ws.onclose = (event) => {
  updateConnectionIndicators(false);
  
  isBotRunning = false;
  isInitializing = false;
  
  updateRunButton(RunButtonState.CLOSED);
  
  // Show skeleton loaders when disconnected
  showSkeleton(balanceEl, 'number');
  showSkeleton(plEl, 'number');
};

// Handle WebSocket error
ws.onerror = () => {
  updateConnectionIndicators(false);
  
  isBotRunning = false;
  isInitializing = false;
  
  updateRunButton(RunButtonState.CLOSED);
  
  // Show skeleton loaders when disconnected
  showSkeleton(balanceEl, 'number');
  showSkeleton(plEl, 'number');
};

// Run button click handler
runBtn.onclick = () => {
  if (input.value == "") {
    alert("Tisk tolerance % required");
    input.focus();
    return;
  }
  if (ws.readyState !== WebSocket.OPEN) {
    return;
  }
  
  updateRunButton(RunButtonState.INITIALIZING);
  ws.send(
    JSON.stringify({
      action: "run_bot",
      mode: selectedMode,
      stake: 5,
      risk_tolerance: input.value,
    })
  );
};



stopBtn.addEventListener("click", () => {
    stopBtn.textContent = "Stopping...";
    stopBtn.disabled = true;
    if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            action: "stop_bot"
        }));
    } else {
      stopBtn.textContent = "No Connection";
    }
});

// Handle page unload
window.addEventListener("pagehide", () => {
  if (ws.readyState === WebSocket.OPEN) ws.close(1000, "Page unloaded");
});

window.addEventListener("beforeunload", () => {
  if (ws.readyState === WebSocket.OPEN) ws.close(1000, "Page unloading");
});

// If WebSocket is already open when this script loads, request balance immediately
if (ws.readyState === WebSocket.OPEN) {
  updateConnectionIndicators(true);
  refreshBalanceForCurrentMode();
  if (!isBotRunning && !isInitializing) {
    updateRunButton(RunButtonState.READY);
  }
}