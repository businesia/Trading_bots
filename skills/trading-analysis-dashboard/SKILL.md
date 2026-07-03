---
name: trading-analysis-dashboard
description: Generate a self-contained HTML trading dashboard in Wall Street terminal style — dark/light theme, market panels, live/demo data mode, and command palette. Use when the user wants a visual trading dashboard, portfolio monitor, or market overview interface to view in a browser.
---

# Trading Analysis Dashboard

Generate a professional, self-contained HTML trading dashboard styled like a Wall Street terminal with dark/light theme toggling, modular market panels, live or demo data modes, and a keyboard-driven command palette.

## When to Use This Skill

- Creating a visual portfolio monitor
- Building a market overview page
- Generating a strategy P&L dashboard
- Producing a risk metrics display
- Setting up a multi-asset watchlist view
- Creating a shareable HTML report of trading analysis

## How to Generate the Dashboard

Ask Claude to create a single-file `dashboard.html` with the following structure and feature set. The file requires no build step and runs entirely in the browser.

## Dashboard Architecture

### Feature Checklist

```
✓ Dark / light theme toggle (persists to localStorage)
✓ Responsive grid layout (1–4 column panels)
✓ Live mode: fetches real data from Alpha Vantage or Yahoo Finance
✓ Demo mode: renders realistic synthetic data (no API key required)
✓ Command palette (Cmd/Ctrl+K): jump to any panel, run commands
✓ Panel types: price chart, P&L curve, risk metrics, watchlist, order book, regime indicator
✓ Keyboard shortcuts: D=demo, L=live, T=theme, R=refresh, K=command palette
✓ Export: screenshot (html2canvas), CSV data download
```

### HTML Skeleton

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Trading Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <style>
    /* CSS variables for theming */
    :root[data-theme="dark"] {
      --bg-primary: #0a0e1a;
      --bg-panel: #111827;
      --bg-panel-header: #1a2234;
      --border: #1e2d4a;
      --text-primary: #e2e8f0;
      --text-secondary: #64748b;
      --text-muted: #334155;
      --accent-green: #00d4aa;
      --accent-red: #ff4757;
      --accent-blue: #3b82f6;
      --accent-yellow: #f59e0b;
      --font-mono: 'Courier New', monospace;
    }
    :root[data-theme="light"] {
      --bg-primary: #f0f4f8;
      --bg-panel: #ffffff;
      --bg-panel-header: #e8edf5;
      --border: #d1dce8;
      --text-primary: #1e293b;
      --text-secondary: #475569;
      --text-muted: #94a3b8;
      --accent-green: #059669;
      --accent-red: #dc2626;
      --accent-blue: #2563eb;
      --accent-yellow: #d97706;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg-primary); color: var(--text-primary);
           font-family: var(--font-mono); font-size: 12px; }

    /* Top bar */
    .topbar { display: flex; align-items: center; padding: 8px 16px;
              background: var(--bg-panel-header); border-bottom: 1px solid var(--border);
              gap: 16px; }
    .topbar-clock { color: var(--accent-green); font-size: 14px; font-weight: bold; }
    .topbar-mode { padding: 2px 8px; border-radius: 3px; font-size: 10px;
                   background: var(--accent-blue); color: #fff; }
    .topbar-mode.demo { background: var(--accent-yellow); color: #000; }

    /* Panel grid */
    .grid { display: grid; gap: 8px; padding: 8px;
            grid-template-columns: repeat(auto-fill, minmax(400px, 1fr)); }
    .panel { background: var(--bg-panel); border: 1px solid var(--border);
             border-radius: 4px; overflow: hidden; }
    .panel-header { background: var(--bg-panel-header); padding: 6px 12px;
                    display: flex; justify-content: space-between; align-items: center;
                    border-bottom: 1px solid var(--border); }
    .panel-title { color: var(--text-secondary); font-size: 10px; text-transform: uppercase;
                   letter-spacing: 1px; }
    .panel-body { padding: 12px; }

    /* Price display */
    .price-main { font-size: 28px; font-weight: bold; color: var(--text-primary); }
    .price-change.up { color: var(--accent-green); }
    .price-change.down { color: var(--accent-red); }

    /* Risk metrics grid */
    .metrics-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .metric-item label { color: var(--text-secondary); font-size: 10px; }
    .metric-item .value { font-size: 18px; font-weight: bold; margin-top: 2px; }

    /* Watchlist table */
    .watchlist { width: 100%; border-collapse: collapse; }
    .watchlist th { color: var(--text-secondary); font-size: 10px; text-align: right;
                    padding: 4px 8px; border-bottom: 1px solid var(--border); }
    .watchlist th:first-child { text-align: left; }
    .watchlist td { padding: 6px 8px; border-bottom: 1px solid var(--text-muted);
                    text-align: right; }
    .watchlist td:first-child { text-align: left; color: var(--accent-blue); }

    /* Command palette */
    .cmd-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7);
                   z-index: 1000; align-items: flex-start; justify-content: center;
                   padding-top: 80px; }
    .cmd-overlay.open { display: flex; }
    .cmd-box { background: var(--bg-panel); border: 1px solid var(--border);
               border-radius: 8px; width: 560px; overflow: hidden; }
    .cmd-input { width: 100%; background: transparent; border: none; outline: none;
                 color: var(--text-primary); font-size: 16px; padding: 16px;
                 font-family: var(--font-mono); border-bottom: 1px solid var(--border); }
    .cmd-item { padding: 10px 16px; cursor: pointer; display: flex;
                justify-content: space-between; }
    .cmd-item:hover { background: var(--bg-panel-header); }
    .cmd-key { color: var(--text-secondary); font-size: 10px; }

    /* Regime badge */
    .regime-badge { display: inline-block; padding: 4px 12px; border-radius: 3px;
                    font-size: 14px; font-weight: bold; }
    .regime-bull { background: rgba(0, 212, 170, 0.15); color: var(--accent-green); }
    .regime-bear { background: rgba(255, 71, 87, 0.15); color: var(--accent-red); }
    .regime-range { background: rgba(245, 158, 11, 0.15); color: var(--accent-yellow); }
    .regime-volatile { background: rgba(59, 130, 246, 0.15); color: var(--accent-blue); }
  </style>
</head>
<body>
  <!-- Top bar with clock, mode indicator, shortcuts -->
  <div class="topbar">
    <span class="topbar-clock" id="clock">--:--:--</span>
    <span class="topbar-mode demo" id="mode-badge">DEMO</span>
    <span style="color:var(--text-secondary); margin-left:auto; font-size:10px;">
      T=Theme &nbsp; D=Demo &nbsp; L=Live &nbsp; R=Refresh &nbsp; ⌘K=Commands
    </span>
    <button onclick="toggleTheme()" style="background:var(--bg-panel-header);
      border:1px solid var(--border); color:var(--text-primary); padding:4px 10px;
      border-radius:3px; cursor:pointer; font-family:inherit;">Theme</button>
  </div>

  <!-- Panel grid (populate dynamically) -->
  <div class="grid" id="grid"></div>

  <!-- Command palette -->
  <div class="cmd-overlay" id="cmd-overlay" onclick="closeCmdPalette(event)">
    <div class="cmd-box">
      <input class="cmd-input" id="cmd-input" placeholder="Type a command..."
             oninput="filterCommands(this.value)" onkeydown="handleCmdKey(event)">
      <div id="cmd-list"></div>
    </div>
  </div>

  <script>
    // ── Theme ──────────────────────────────────────────────────────────────
    let theme = localStorage.getItem('dashTheme') || 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    function toggleTheme() {
      theme = theme === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('dashTheme', theme);
    }

    // ── Clock ──────────────────────────────────────────────────────────────
    setInterval(() => {
      document.getElementById('clock').textContent =
        new Date().toLocaleTimeString('en-US', { hour12: false });
    }, 1000);

    // ── Demo data generators ───────────────────────────────────────────────
    function genPrices(n, start, vol) {
      const prices = [start];
      for (let i = 1; i < n; i++) {
        prices.push(+(prices[i-1] * (1 + (Math.random() - 0.49) * vol)).toFixed(2));
      }
      return prices;
    }

    const DEMO_WATCHLIST = [
      { sym: 'SPY', price: 541.23, chg: 1.23, pct: 0.23 },
      { sym: 'QQQ', price: 467.88, chg: -2.11, pct: -0.45 },
      { sym: 'AAPL', price: 213.45, chg: 3.22, pct: 1.53 },
      { sym: 'TSLA', price: 248.91, chg: -5.67, pct: -2.23 },
      { sym: 'NVDA', price: 131.07, chg: 2.88, pct: 2.25 },
      { sym: 'BTC', price: 67842.00, chg: 1204.00, pct: 1.81 },
      { sym: 'EUR/USD', price: 1.0823, chg: 0.0012, pct: 0.11 },
      { sym: 'GC=F', price: 2389.40, chg: -8.20, pct: -0.34 },
    ];

    const DEMO_RISK = {
      var95: '-1.82%', cvar95: '-2.41%', sharpe: '1.34',
      maxDD: '-8.21%', beta: '0.87', correlation: '0.73',
    };

    // ── Panel builders ─────────────────────────────────────────────────────
    function buildWatchlistPanel() {
      const rows = DEMO_WATCHLIST.map(s => {
        const cls = s.chg >= 0 ? 'up' : 'down';
        const sign = s.chg >= 0 ? '+' : '';
        return `<tr>
          <td>${s.sym}</td>
          <td>${s.price.toLocaleString()}</td>
          <td class="price-change ${cls}">${sign}${s.chg}</td>
          <td class="price-change ${cls}">${sign}${s.pct}%</td>
        </tr>`;
      }).join('');
      return `<div class="panel">
        <div class="panel-header"><span class="panel-title">Watchlist</span></div>
        <div class="panel-body" style="padding:0">
          <table class="watchlist">
            <thead><tr><th>Symbol</th><th>Price</th><th>Chg</th><th>%</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div></div>`;
    }

    function buildChartPanel(sym, prices) {
      const canvasId = 'chart-' + sym.replace(/[^a-z0-9]/gi, '');
      const latest = prices[prices.length - 1];
      const prev = prices[0];
      const chg = latest - prev;
      const pct = ((chg / prev) * 100).toFixed(2);
      const cls = chg >= 0 ? 'up' : 'down';
      setTimeout(() => {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;
        new Chart(ctx, {
          type: 'line',
          data: {
            labels: prices.map((_, i) => i),
            datasets: [{ data: prices, borderColor: chg >= 0 ? '#00d4aa' : '#ff4757',
              borderWidth: 1.5, fill: true, tension: 0.2, pointRadius: 0,
              backgroundColor: chg >= 0 ? 'rgba(0,212,170,0.07)' : 'rgba(255,71,87,0.07)' }]
          },
          options: { responsive: true, plugins: { legend: { display: false } },
            scales: { x: { display: false }, y: { display: false } } }
        });
      }, 50);
      return `<div class="panel">
        <div class="panel-header">
          <span class="panel-title">${sym} Price</span>
          <span class="price-change ${cls}">${chg >= 0 ? '+' : ''}${pct}%</span>
        </div>
        <div class="panel-body">
          <div class="price-main">$${latest.toLocaleString()}</div>
          <canvas id="${canvasId}" height="80"></canvas>
        </div></div>`;
    }

    function buildRiskPanel() {
      const r = DEMO_RISK;
      const items = [
        ['VaR (95%)', r.var95, 'down'], ['CVaR (95%)', r.cvar95, 'down'],
        ['Sharpe Ratio', r.sharpe, 'up'], ['Max Drawdown', r.maxDD, 'down'],
        ['Beta', r.beta, ''], ['Correlation', r.correlation, ''],
      ].map(([label, val, cls]) => `
        <div class="metric-item">
          <label>${label}</label>
          <div class="value price-change ${cls}">${val}</div>
        </div>`).join('');
      return `<div class="panel">
        <div class="panel-header"><span class="panel-title">Risk Metrics</span></div>
        <div class="panel-body"><div class="metrics-grid">${items}</div></div></div>`;
    }

    function buildRegimePanel() {
      const regimes = [
        { label: 'BULL TREND', cls: 'regime-bull', conf: 78 },
        { label: 'RANGING', cls: 'regime-range', conf: 14 },
        { label: 'BEAR TREND', cls: 'regime-bear', conf: 5 },
        { label: 'VOLATILE', cls: 'regime-volatile', conf: 3 },
      ];
      const top = regimes[0];
      const bars = regimes.map(r =>
        `<div style="display:flex;align-items:center;gap:8px;margin:6px 0">
          <span style="width:80px;color:var(--text-secondary);font-size:10px">${r.label}</span>
          <div style="flex:1;background:var(--text-muted);border-radius:2px;height:6px">
            <div style="width:${r.conf}%;background:var(--accent-blue);height:6px;border-radius:2px"></div>
          </div>
          <span style="width:32px;text-align:right;color:var(--text-primary)">${r.conf}%</span>
        </div>`).join('');
      return `<div class="panel">
        <div class="panel-header"><span class="panel-title">Market Regime (HMM)</span></div>
        <div class="panel-body">
          <div style="margin-bottom:12px">
            <span class="regime-badge ${top.cls}">${top.label}</span>
            <span style="margin-left:8px;color:var(--text-secondary);font-size:10px">
              Confidence: ${top.conf}%</span>
          </div>
          ${bars}
        </div></div>`;
    }

    // ── Render grid ────────────────────────────────────────────────────────
    function render() {
      const spyPrices = genPrices(120, 530, 0.005);
      const btcPrices = genPrices(120, 65000, 0.012);
      document.getElementById('grid').innerHTML =
        buildChartPanel('SPY', spyPrices) +
        buildChartPanel('BTC/USD', btcPrices) +
        buildRiskPanel() +
        buildRegimePanel() +
        buildWatchlistPanel();
    }
    render();

    // ── Command palette ────────────────────────────────────────────────────
    const COMMANDS = [
      { label: 'Toggle Theme', key: 'T', action: toggleTheme },
      { label: 'Switch to Demo Mode', key: 'D', action: () => setMode('demo') },
      { label: 'Switch to Live Mode', key: 'L', action: () => setMode('live') },
      { label: 'Refresh Dashboard', key: 'R', action: render },
      { label: 'Export CSV', key: '', action: exportCSV },
    ];

    function openCmdPalette() {
      document.getElementById('cmd-overlay').classList.add('open');
      document.getElementById('cmd-input').value = '';
      filterCommands('');
      setTimeout(() => document.getElementById('cmd-input').focus(), 50);
    }
    function closeCmdPalette(e) {
      if (e.target === document.getElementById('cmd-overlay'))
        document.getElementById('cmd-overlay').classList.remove('open');
    }
    function filterCommands(q) {
      const items = COMMANDS.filter(c => c.label.toLowerCase().includes(q.toLowerCase()))
        .map(c => `<div class="cmd-item" onclick="runCmd(${COMMANDS.indexOf(c)})">
          <span>${c.label}</span><span class="cmd-key">${c.key}</span></div>`).join('');
      document.getElementById('cmd-list').innerHTML = items;
    }
    function handleCmdKey(e) {
      if (e.key === 'Escape') document.getElementById('cmd-overlay').classList.remove('open');
      if (e.key === 'Enter') {
        const first = document.querySelector('.cmd-item');
        if (first) first.click();
      }
    }
    function runCmd(idx) {
      document.getElementById('cmd-overlay').classList.remove('open');
      COMMANDS[idx].action();
    }

    function setMode(mode) {
      const badge = document.getElementById('mode-badge');
      badge.textContent = mode.toUpperCase();
      badge.className = 'topbar-mode ' + (mode === 'demo' ? 'demo' : '');
    }

    function exportCSV() {
      const rows = [['Symbol', 'Price', 'Change', 'Pct']].concat(
        DEMO_WATCHLIST.map(s => [s.sym, s.price, s.chg, s.pct + '%'])
      );
      const csv = rows.map(r => r.join(',')).join('\n');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
      a.download = 'dashboard-export.csv';
      a.click();
    }

    // ── Global keyboard shortcuts ──────────────────────────────────────────
    document.addEventListener('keydown', e => {
      if (e.target.tagName === 'INPUT') return;
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); openCmdPalette(); }
      if (e.key === 't' || e.key === 'T') toggleTheme();
      if (e.key === 'd' || e.key === 'D') setMode('demo');
      if (e.key === 'l' || e.key === 'L') setMode('live');
      if (e.key === 'r' || e.key === 'R') render();
    });
  </script>
</body>
</html>
```

## Customization

To add real live data, replace demo generators with Alpha Vantage or Yahoo Finance fetch calls and call the dashboard's panel builders with live price arrays. Toggle `setMode('live')` via the command palette (⌘K → "Switch to Live Mode").

Add panels by calling any `buildXxxPanel()` function and appending the returned HTML string to `document.getElementById('grid').innerHTML`.
