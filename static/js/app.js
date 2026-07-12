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
const riskInput = document.getElementById("lossTolerance");
let streamEnded = false;

// ==========================================================================
// Log Storage - Persistence
// ==========================================================================
const STORAGE_KEY = 'trade_stream_logs';
const RT_STORAGE_KEY = 'risk_tolerance_value';
const MAX_STORED_LOGS = 1000;

function saveLogsToStorage(logs) {
    try {
        if (logs.length > MAX_STORED_LOGS) {
            logs = logs.slice(-MAX_STORED_LOGS);
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(logs));
    } catch (e) {
        console.warn('Failed to save logs to localStorage:', e);
        try {
            localStorage.removeItem(STORAGE_KEY);
            localStorage.setItem(STORAGE_KEY, JSON.stringify(logs));
        } catch (e2) {
            console.warn('Failed to save logs even after clearing:', e2);
        }
    }
}

function loadLogsFromStorage() {
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) {
            return JSON.parse(stored);
        }
    } catch (e) {
        console.warn('Failed to load logs from localStorage:', e);
    }
    return [];
}

function clearStoredLogs() {
    localStorage.removeItem(STORAGE_KEY);
}

// ==========================================================================
// Risk Tolerance Storage
// ==========================================================================
function saveRiskTolerance(value) {
    try {
        if (value !== undefined && value !== null && value !== '') {
            localStorage.setItem(RT_STORAGE_KEY, String(value));
        } else {
            localStorage.removeItem(RT_STORAGE_KEY);
        }
    } catch (e) {
        console.warn('Failed to save risk tolerance:', e);
    }
}

function loadRiskTolerance() {
    try {
        const stored = localStorage.getItem(RT_STORAGE_KEY);
        if (stored !== null) {
            return stored;
        }
    } catch (e) {
        console.warn('Failed to load risk tolerance:', e);
    }
    return '';
}

function clearRiskTolerance() {
    localStorage.removeItem(RT_STORAGE_KEY);
}

// ==========================================================================
// Skeleton loader helpers - FIXED
// ==========================================================================
function showSkeleton(element, type = 'number') {
  if (!element) return;
  
  // Set minimum dimensions to match content
  if (type === 'number') {
    element.style.minWidth = '120px';
    element.style.minHeight = '38px';
    element.style.display = 'inline-block';
    element.style.fontSize = '32px';
    element.style.lineHeight = '1.1';
  } else {
    element.style.minWidth = '60px';
    element.style.minHeight = '1.2em';
  }
  
  // Apply skeleton classes
  element.classList.add('skeleton');
  if (type === 'number') {
    element.classList.add('skeleton-number');
  } else {
    element.classList.add('skeleton-text');
  }
  
  // Preserve content space
  element.textContent = '\u00A0';
}

function hideSkeleton(element) {
  if (!element) return;
  element.classList.remove('skeleton', 'skeleton-number', 'skeleton-text');
  
  // Reset styles
  element.style.minWidth = '';
  element.style.minHeight = '';
  element.style.display = '';
  element.style.fontSize = '';
  element.style.lineHeight = '';
  element.textContent = '';
}

function showFeedSkeleton(count = 3) {
  if (!feedBody) return;
  
  // Remove existing skeletons
  const existing = feedBody.querySelectorAll('.feed-skeleton');
  existing.forEach(el => el.remove());
  
  // Create new skeletons
  for (let i = 0; i < count; i++) {
    const skeleton = document.createElement('div');
    skeleton.className = 'feed-skeleton';
    skeleton.style.animationDelay = `${i * 0.1}s`;
    
    const rail = document.createElement('div');
    rail.className = 'feed-rail';
    const dot = document.createElement('div');
    dot.className = 'feed-dot neutral';
    const line = document.createElement('div');
    line.className = 'feed-line neutral';
    rail.appendChild(dot);
    rail.appendChild(line);
    skeleton.appendChild(rail);
    
    const card = document.createElement('div');
    card.className = 'skeleton-card';
    for (let j = 0; j < 4; j++) {
      const lineEl = document.createElement('div');
      lineEl.className = 'skeleton-line';
      card.appendChild(lineEl);
    }
    skeleton.appendChild(card);
    
    feedBody.prepend(skeleton);
  }
}

function hideFeedSkeleton() {
  if (!feedBody) return;
  const skeletons = feedBody.querySelectorAll('.feed-skeleton');
  skeletons.forEach(el => el.remove());
}

// ==========================================================================
// Feed primitives
// ==========================================================================
let logEntries = [];

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

function storeLogEntry(accent, cardEl, logData) {
    const entry = {
        timestamp: new Date().toISOString(),
        accent: accent,
        title: logData?.title || 'Unknown',
        widget: logData?.widget || 'unknown',
        metadata: logData?.metadata || {},
        html: cardEl.outerHTML
    };
    
    logEntries.push(entry);
    
    if (logEntries.length > MAX_STORED_LOGS) {
        logEntries = logEntries.slice(-MAX_STORED_LOGS);
    }
    
    saveLogsToStorage(logEntries);
}

function pushFeedItem(accent, cardEl, logData = null) {
    clearEmptyState();
    hideFeedSkeleton();
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
    
    if (logData) {
        storeLogEntry(accent, cardEl, logData);
    }
}

function pushLogLine(text, color) {
    clearEmptyState();
    hideFeedSkeleton();
    const line = document.createElement("div");
    line.className = "log-line";
    if (color) line.style.color = color;
    line.textContent = text;
    feedBody.prepend(line);
    
    const entry = {
        timestamp: new Date().toISOString(),
        type: 'log_line',
        text: text,
        color: color || null
    };
    
    logEntries.push(entry);
    if (logEntries.length > MAX_STORED_LOGS) {
        logEntries = logEntries.slice(-MAX_STORED_LOGS);
    }
    saveLogsToStorage(logEntries);
}

// ==========================================================================
// Restore logs from storage on page load
// ==========================================================================
function restoreLogsFromStorage() {
    const storedLogs = loadLogsFromStorage();
    if (storedLogs && storedLogs.length > 0) {
        logEntries = storedLogs;
        
        feedBody.innerHTML = '';
        clearEmptyState();
        
        storedLogs.forEach(entry => {
            if (entry.type === 'log_line') {
                const line = document.createElement("div");
                line.className = "log-line";
                if (entry.color) line.style.color = entry.color;
                line.textContent = entry.text;
                feedBody.prepend(line);
            } else if (entry.html) {
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = entry.html;
                const cardEl = tempDiv.firstElementChild;
                if (cardEl) {
                    const item = document.createElement("div");
                    item.className = "feed-item";

                    const rail = document.createElement("div");
                    rail.className = "feed-rail";
                    const dot = document.createElement("div");
                    dot.className = `feed-dot ${entry.accent}`;
                    const line = document.createElement("div");
                    line.className = `feed-line ${entry.accent}`;
                    rail.appendChild(dot);
                    rail.appendChild(line);

                    item.appendChild(rail);
                    item.appendChild(cardEl);

                    feedBody.prepend(item);
                }
            }
        });
        
        console.log(`Restored ${storedLogs.length} log entries from storage`);
        return true;
    }
    return false;
}

// ==========================================================================
// Mode state management with persistence
// ==========================================================================
let selectedMode = localStorage.getItem("selectedMode") || "demo";

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
        runBtn.textContent = customText || "Execute";
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
    if (btn.dataset.mode === selectedMode) {
      refreshBalanceForCurrentMode();
      return;
    }
    
    modeButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    
    selectedMode = btn.dataset.mode;
    localStorage.setItem("selectedMode", selectedMode);
    
    initialBal = 0;
    
    showSkeleton(balanceEl, 'number');
    showSkeleton(plEl, 'number');
    
    refreshBalanceForCurrentMode();
  });
});

// ==========================================================================
// Refresh balance for current mode - with smooth transition
// ==========================================================================
let pendingBalanceRequest = false;

function refreshBalanceForCurrentMode() {
  showSkeleton(balanceEl, 'number');
  showSkeleton(plEl, 'number');
  
  if (feedBody && feedBody.children.length === 0) {
    showFeedSkeleton(3);
  }
  
  if (ws && ws.readyState === WebSocket.OPEN) {
    console.log(`Requesting balance for mode: ${selectedMode}`);
    ws.send(JSON.stringify({
      action: "get_balance",
      mode: selectedMode
    }));
  } else {
    console.warn("WebSocket not open, cannot refresh balance");
    pendingBalanceRequest = true;
    setTimeout(() => {
      hideSkeleton(balanceEl);
      hideSkeleton(plEl);
      hideFeedSkeleton();
    }, 5000);
  }
}

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
    pushFeedItem("info", card, data);
  },

  snackbar(data) {
    const accent = accentFor(data.metadata.status);
    const card = makeCard(data.title, accent);
    const p = document.createElement("p");
    p.className = "card-message";
    p.textContent = data.metadata.message;
    card.appendChild(p);
    pushFeedItem(accent, card, data);
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
    pushFeedItem(accent, card, data);
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
      pushFeedItem(accent, card, data);
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
    pushFeedItem("info", card, data);
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
    pushFeedItem(accent, card, data);
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
    pushFeedItem(accent, card, data);
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
    pushFeedItem(accent, card, data);
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

    pushFeedItem(accent, card, data);
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
    pushFeedItem("gold", card, data);
  },
};

function renderTradeStream(ts) {
  const renderer = RENDERERS[ts.widget];
  if (renderer) renderer(ts);
}

// ==========================================================================
// Format numbers to 2 decimal places with commas
// ==========================================================================
function formatNumberWithCommas(value) {
  if (value === undefined || value === null) return "0.00";
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return "0.00";
  
  const parts = num.toFixed(2).split('.');
  const integerPart = parts[0];
  const decimalPart = parts[1];
  
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
  const parts = formatted.split('.');
  const integerPart = parts[0];
  const decimalPart = parts[1];
  
  const withCommas = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const formattedWithCommas = `${withCommas}.${decimalPart}`;
  
  return num >= 0 ? `+${formattedWithCommas}` : `-${formattedWithCommas}`;
}

// ==========================================================================
// Update balance and PL display - with smooth transition
// ==========================================================================
let initialBal = 0;

function updateBalanceAndPL(balance, pl) {
  if (balance !== undefined && balance !== null) {
    const balanceNum = typeof balance === 'string' ? parseFloat(balance) : balance;
    if (!isNaN(balanceNum)) {
      setTimeout(() => {
        hideSkeleton(balanceEl);
        balanceEl.textContent = formatNumberWithCommas(balanceNum);
        
        if (initialBal !== 0 && balanceNum < initialBal) {
          balanceEl.style.color = "var(--loss)";
        } else {
          balanceEl.style.color = "var(--profit)";
        }
        
        balanceEl.style.transition = 'opacity 0.3s ease';
        balanceEl.style.opacity = '0';
        requestAnimationFrame(() => {
          balanceEl.style.opacity = '1';
        });
      }, 100);
    }
  }
  
  if (pl !== undefined && pl !== null) {
    const plNum = typeof pl === 'string' ? parseFloat(pl) : pl;
    if (!isNaN(plNum)) {
      setTimeout(() => {
        hideSkeleton(plEl);
        plEl.textContent = formatPL(plNum);
        
        if (plNum < 0) {
          plEl.style.color = "var(--loss)";
          plEl.classList.remove("pl-positive");
          plEl.classList.add("pl-negative");
        } else {
          plEl.style.color = "var(--profit)";
          plEl.classList.remove("pl-negative");
          plEl.classList.add("pl-positive");
        }
        
        plEl.style.transition = 'opacity 0.3s ease';
        plEl.style.opacity = '0';
        requestAnimationFrame(() => {
          plEl.style.opacity = '1';
        });
      }, 150);
    }
  }
  
  setTimeout(() => {
    hideFeedSkeleton();
  }, 300);
  
  updateRiskIndicatorFromInput();
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
const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

updateRunButton(RunButtonState.CONNECTING);
setWaiting("connecting");

connDot.classList.remove("live");
connDot.classList.add("down");
connLabel.textContent = "Connecting...";

showSkeleton(balanceEl, 'number');
showSkeleton(plEl, 'number');

// ==========================================================================
// Restore risk tolerance from storage
// ==========================================================================
function restoreRiskTolerance() {
    const storedValue = loadRiskTolerance();
    if (storedValue !== '') {
        riskInput.value = storedValue;
        setTimeout(() => {
            updateRiskIndicatorFromInput();
        }, 100);
        console.log(`Restored risk tolerance: ${storedValue}%`);
    }
}

// ==========================================================================
// WebSocket event handlers
// ==========================================================================
ws.onopen = () => {
  updateConnectionIndicators(true);
  refreshBalanceForCurrentMode();
  
  if (pendingBalanceRequest) {
    pendingBalanceRequest = false;
    refreshBalanceForCurrentMode();
  }
  
  if (!isBotRunning && !isInitializing) {
    updateRunButton(RunButtonState.READY);
  } else if (isBotRunning) {
    updateRunButton(RunButtonState.RUNNING);
  } else if (isInitializing) {
    updateRunButton(RunButtonState.INITIALIZING);
  }
  
  setTimeout(() => {
    updateRiskIndicatorFromInput();
  }, 400);
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.trade_stream) {
    stopBtn.style.display = "block";
    if (data.trade_stream.widget == "bot_shutdown_summary") {
      stopBtn.style.display = "none";
      updateRunButton(RunButtonState.READY);
    }
    if (data.trade_stream.title == "STOP COMMAND RECEIVED") {
      stopBtn.textContent = "Bot Stopped";
      setTimeout(() => {
          stopBtn.disabled=true;
      }, 1000);
    }
    if (data.trade_stream.balance !== undefined) {
      const balance = data.trade_stream.balance;
      const pl = data.trade_stream.pl !== undefined ? data.trade_stream.pl : 0;
      
      if (initialBal === 0 && balance !== undefined) {
        initialBal = typeof balance === 'string' ? parseFloat(balance) : balance;
      }
      
      updateBalanceAndPL(balance, pl);
    }
    
    renderTradeStream(data.trade_stream);
    
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
  
  if (data.balance !== undefined || data.pl !== undefined) {
    const balance = data.balance;
    const pl = data.pl !== undefined ? data.pl : 0;
    
    if (balance !== undefined && initialBal === 0) {
      initialBal = typeof balance === 'string' ? parseFloat(balance) : balance;
    }
    
    updateBalanceAndPL(balance, pl);
  }

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
    const wasRunning = isBotRunning;
    isBotRunning = false;

    waitingIndicator.classList.add("paused");
    updateRunButton(RunButtonState.READY);
    
    if (wasRunning && !data.bot?.running && !data.trade_stream?.bot?.running) {
      if (currentRunButtonState !== RunButtonState.CONNECTING && 
          currentRunButtonState !== RunButtonState.CLOSED &&
          !isInitializing) {
        updateRunButton(RunButtonState.READY);
      }
    }
  }

  if (data.status) {
    pushLogLine(data.status, data.color);
  }
};

ws.onclose = (event) => {
  updateConnectionIndicators(false);
  isBotRunning = false;
  isInitializing = false;
  updateRunButton(RunButtonState.CLOSED);
  showSkeleton(balanceEl, 'number');
  showSkeleton(plEl, 'number');
};

ws.onerror = () => {
  updateConnectionIndicators(false);
  isBotRunning = false;
  isInitializing = false;
  updateRunButton(RunButtonState.CLOSED);
  showSkeleton(balanceEl, 'number');
  showSkeleton(plEl, 'number');
};

// ==========================================================================
// Run button click handler
// ==========================================================================
runBtn.onclick = () => {
  const riskValue = parseFloat(riskInput.value);
  
  if (riskInput.value === "" || isNaN(riskValue)) {
    alert("Risk tolerance % required");
    riskInput.focus();
    return;
  } else if (riskValue > 85 || riskValue < 0.001) {
    alert("Risk tolerance % must be between 0.001 and 85");
    riskInput.focus();
    return;
  }
  
  if (ws.readyState !== WebSocket.OPEN) {
    alert("Not connected to server");
    return;
  }
  
  logEntries = [];
  clearStoredLogs();
  feedBody.innerHTML = '';
  clearEmptyState();
  showFeedSkeleton(3);
  
  updateRunButton(RunButtonState.INITIALIZING);
  ws.send(
    JSON.stringify({
      action: "run_bot",
      mode: selectedMode,
      stake: 5,
      risk_tolerance: riskValue,
    })
  );
};

// ==========================================================================
// Stop button handler
// ==========================================================================
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

// ==========================================================================
// Risk Indicator - SL Value Display
// ==========================================================================
function createRiskIndicator() {
    let indicator = document.querySelector('.risk-indicator');
    if (indicator) return indicator;
    
    indicator = document.createElement('div');
    indicator.className = 'risk-indicator';
    
    Object.assign(indicator.style, {
        display: 'flex',
        alignItems: 'center',
        gap: '2px',
        padding: '2px 10px 2px 4px',
        borderRadius: '999px',
        fontFamily: 'var(--font-body, "Nunito", sans-serif)',
        fontSize: '12px',
        fontWeight: '600',
        color: 'var(--text-dim, #726f7d)',
        minHeight: '30px',
        transition: 'all 0.3s ease',
        opacity: '0',
        marginLeft: 'auto',
        flexShrink: '0'
    });
    
    const label = document.createElement('span');
    label.className = 'risk-label';
    label.textContent = 'SL';
    Object.assign(label.style, {
        color: 'var(--loss, #e0435f)',
        fontWeight: '700',
        fontSize: '10px',
        letterSpacing: '0.3px',
        textTransform: 'uppercase',
        opacity: '0.7'
    });
    indicator.appendChild(label);
    
    const valueDisplay = document.createElement('span');
    valueDisplay.className = 'risk-value';
    valueDisplay.style.backgroundColor = "transparent";
    Object.assign(valueDisplay.style, {
        color: 'var(--text, #2c2b35)',
        fontWeight: '700',
        fontSize: '13px',
        transition: 'color 0.3s ease'
    });
    
    valueDisplay.textContent = '';
    Object.assign(valueDisplay.style, {
        color: 'var(--text-faint, #a29fae)',
        background: 'var(--surface, #ffffff)',
        padding: '1px 8px',
        borderRadius: '4px',
        minWidth: '40px',
        textAlign: 'center'
    });
    indicator.appendChild(valueDisplay);
    
    const inputContainer = document.querySelector('.controls > div:has(.RT)');
    if (inputContainer) {
        inputContainer.style.display = 'flex';
        inputContainer.style.alignItems = 'center';
        inputContainer.style.gap = '6px';
        inputContainer.style.padding = '4px 6px 4px 12px';
        inputContainer.appendChild(indicator);
    }
    
    setTimeout(() => {
        indicator.style.opacity = '1';
        indicator.style.transform = 'scale(1)';
    }, 50);
    
    return indicator;
}

// ==========================================================================
// Update Risk Indicator
// ==========================================================================
function updateRiskIndicator(percentage, balance) {
    const indicator = document.querySelector('.risk-indicator');
    if (!indicator) {
        createRiskIndicator();
        const newIndicator = document.querySelector('.risk-indicator');
        if (!newIndicator) return;
    }
    
    const valueDisplay = indicator.querySelector('.risk-value');
    if (!valueDisplay) return;
    
    if (percentage !== null && percentage !== undefined && 
        !isNaN(percentage) && balance > 0 && percentage > 0) {
        
        const value = (percentage / 100) * balance;
        const formattedValue = formatNumberWithCommas(value);
        
        Object.assign(valueDisplay.style, {
            background: 'transparent',
            padding: '1px 4px',
            minWidth: 'auto',
            textAlign: 'left'
        });
        
        valueDisplay.textContent = `${formattedValue}`;
        
        if (percentage <= 2) {
            valueDisplay.style.color = 'var(--profit, #1fa971)';
        } else if (percentage <= 5) {
            valueDisplay.style.color = 'var(--warn, #dd9328)';
        } else {
            valueDisplay.style.color = 'var(--loss, #e0435f)';
        }
        
        indicator.style.opacity = '1';
        indicator.style.transform = 'scale(1)';
        
    } else {
        valueDisplay.textContent = '';
        Object.assign(valueDisplay.style, {
            color: 'var(--text-faint, #a29fae)',
            background: 'var(--surface, #ffffff)',
            padding: '1px 8px',
            borderRadius: '4px',
            minWidth: '40px',
            textAlign: 'center'
        });
        indicator.style.opacity = '0.6';
    }
}

// ==========================================================================
// Update risk indicator from input value
// ==========================================================================
function updateRiskIndicatorFromInput() {
    if (riskInput.value === '') {
        const indicator = document.querySelector('.risk-indicator');
        if (indicator) {
            const valueDisplay = indicator.querySelector('.risk-value');
            if (valueDisplay) {
                valueDisplay.textContent = '';
                Object.assign(valueDisplay.style, {
                    color: 'var(--text-faint, #a29fae)',
                    background: 'var(--surface, #ffffff)',
                    padding: '1px 8px',
                    borderRadius: '4px',
                    minWidth: '40px',
                    textAlign: 'center'
                });
                indicator.style.opacity = '0.6';
            }
        }
        return;
    }
    
    const val = parseFloat(riskInput.value);
    if (!isNaN(val) && val > 0) {
        saveRiskTolerance(riskInput.value);
        const balanceText = balanceEl.textContent;
        const balance = parseFloat(balanceText.replace(/,/g, ''));
        if (!isNaN(balance) && balance > 0) {
            updateRiskIndicator(val, balance);
        }
    } else {
        const indicator = document.querySelector('.risk-indicator');
        if (indicator) {
            const valueDisplay = indicator.querySelector('.risk-value');
            if (valueDisplay) {
                valueDisplay.textContent = '';
                Object.assign(valueDisplay.style, {
                    color: 'var(--text-faint, #a29fae)',
                    background: 'var(--surface, #ffffff)',
                    padding: '1px 8px',
                    borderRadius: '4px',
                    minWidth: '40px',
                    textAlign: 'center'
                });
                indicator.style.opacity = '0.6';
            }
        }
    }
}

// ==========================================================================
// Initialize risk indicator on page load
// ==========================================================================
function initializeRiskIndicator() {
    createRiskIndicator();
    setTimeout(() => {
        updateRiskIndicatorFromInput();
    }, 400);
}

// ==========================================================================
// Setup input with styling and event listeners
// ==========================================================================
Object.assign(riskInput.style, {
    border: 'none',
    outline: 'none',
    background: 'transparent',
    fontSize: '14px',
    fontWeight: '600',
    color: 'var(--text, #2c2b35)',
    width: '60px',
    padding: '4px 0',
    fontFamily: 'var(--font-body, "Nunito", sans-serif)'
});

const percentSign = document.createElement('span');
percentSign.textContent = '%';
Object.assign(percentSign.style, {
    color: 'var(--text-dim, #726f7d)',
    fontWeight: '600',
    fontSize: '13px',
    marginRight: '2px'
});

riskInput.parentNode.insertBefore(percentSign, riskInput.nextSibling);

riskInput.addEventListener('input', function() {
    if (this.value !== '') {
        saveRiskTolerance(this.value);
    } else {
        clearRiskTolerance();
    }
    updateRiskIndicatorFromInput();
});

riskInput.addEventListener('blur', function() {
    if (this.value === '') {
        const indicator = document.querySelector('.risk-indicator');
        if (indicator) {
            const valueDisplay = indicator.querySelector('.risk-value');
            if (valueDisplay) {
                valueDisplay.textContent = '';
                Object.assign(valueDisplay.style, {
                    color: 'var(--text-faint, #a29fae)',
                    background: 'var(--surface, #ffffff)',
                    padding: '1px 8px',
                    borderRadius: '4px',
                    minWidth: '40px',
                    textAlign: 'center'
                });
                indicator.style.opacity = '0.6';
            }
        }
        clearRiskTolerance();
    }
});

// ==========================================================================
// Page load handlers
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
  showSkeleton(balanceEl, 'number');
  showSkeleton(plEl, 'number');
  
  if (feedBody && feedBody.children.length === 0) {
    showFeedSkeleton(3);
  }
  
  initializeRiskIndicator();
  
  setTimeout(() => {
    const hasRestoredLogs = restoreLogsFromStorage();
    if (hasRestoredLogs) {
      hideFeedSkeleton();
    }
  }, 100);
});

// Handle page unload
window.addEventListener("pagehide", () => {
  if (ws.readyState === WebSocket.OPEN) ws.close(1000, "Page unloaded");
});

window.addEventListener("beforeunload", () => {
  if (ws.readyState === WebSocket.OPEN) ws.close(1000, "Page unloading");
});

// If WebSocket is already open when this script loads
if (ws.readyState === WebSocket.OPEN) {
  updateConnectionIndicators(true);
  refreshBalanceForCurrentMode();
  if (!isBotRunning && !isInitializing) {
    updateRunButton(RunButtonState.READY);
  }
}