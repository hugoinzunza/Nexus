/* Co-piloto de Trading — frontend.
 *
 * Se conecta al stream SSE del backend (/m/trading/api/stream), que empuja el
 * estado del mercado en vivo. Por cada instrumento dibuja: precio + variación,
 * estadísticas, gráfico de velas (canvas propio, sin librerías), libro de
 * órdenes y un panel de señales.
 *
 * Si SSE falla, cae a polling de /api/state cada 3s como respaldo.
 */
(function () {
  "use strict";

  const container = document.getElementById("instruments");
  const tpl = document.getElementById("card-tpl");
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  const lastUpdateEl = document.getElementById("last-update");

  // Guardamos el estado de cada tarjeta (nodo DOM + último precio) por símbolo.
  const cards = {};

  // Temporalidades del selector. Se sobreescriben con lo que diga el backend
  // (api/config); estos son el respaldo por si esa llamada falla.
  let TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1D"];
  let DEFAULT_TF = "15m";
  const CANDLE_REFRESH_MS = 6000; // cada cuánto refrescamos las velas del par
  const SMC_REFRESH_MS = 20000;   // cada cuánto recalculamos el análisis SMC

  // --- Primitive custom de Lightweight Charts para las cajas SMC -----
  // Lightweight Charts no trae rectángulos; lo resolvemos con un series
  // primitive que dibuja en el canvas usando priceToCoordinate / timeToCoordinate,
  // así las cajas (premium/discount, FVG, POIs) quedan alineadas al hacer zoom/paneo.
  class SMCRenderer {
    constructor(src) { this._src = src; }
    draw(target) {
      const src = this._src;
      const data = src._data;
      if (!data || !src._series) return;
      const series = src._series;
      const ts = src._chart.timeScale();
      const py = (p) => series.priceToCoordinate(p);
      target.useMediaCoordinateSpace((scope) => {
        const ctx = scope.context;
        const W = scope.mediaSize.width, H = scope.mediaSize.height;
        // Premium (arriba del EQ) y discount (abajo).
        if (data.range && data.range.eq) {
          const yEq = py(data.range.eq);
          if (yEq != null) {
            ctx.fillStyle = "rgba(234,57,67,0.05)"; ctx.fillRect(0, 0, W, yEq);
            ctx.fillStyle = "rgba(22,199,132,0.05)"; ctx.fillRect(0, yEq, W, H - yEq);
          }
        }
        // FVGs sin rellenar: desde su tiempo hacia la derecha.
        (data.fvgs || []).filter((f) => !f.filled).forEach((f) => {
          const y1 = py(f.hi), y2 = py(f.lo); if (y1 == null || y2 == null) return;
          let x = ts.timeToCoordinate(Math.floor(f.t / 1000)); if (x == null) x = 0;
          x = Math.max(0, x);
          ctx.fillStyle = f.bullish ? "rgba(108,92,231,0.13)" : "rgba(245,166,35,0.13)";
          ctx.fillRect(x, Math.min(y1, y2), W - x, Math.abs(y2 - y1));
        });
        // Cajas de POI (ancho completo). Verde = descuento/long, rojo = premium/short.
        ctx.font = "10px -apple-system, sans-serif"; ctx.textBaseline = "top";
        (data.pois || []).forEach((poi) => {
          const y1 = py(poi.hi), y2 = py(poi.lo); if (y1 == null || y2 == null) return;
          const top = Math.min(y1, y2), h = Math.max(1, Math.abs(y2 - y1));
          const long = poi.dir === "long";
          const base = long ? "22,199,132" : "234,57,67";
          ctx.fillStyle = `rgba(${base},${poi.valid ? 0.13 : 0.05})`;
          ctx.fillRect(0, top, W, h);
          ctx.strokeStyle = `rgba(${base},${poi.valid ? 0.7 : 0.3})`;
          ctx.lineWidth = 1;
          ctx.setLineDash(poi.valid ? [] : [3, 3]);
          ctx.strokeRect(0.5, top + 0.5, W - 1, h);
          ctx.setLineDash([]);
          ctx.fillStyle = long ? "#16c784" : "#ea3943";
          ctx.fillText(`POI ${poi.tf} ${poi.valid ? "✓" : "✕"}`, 5, top + 2);
        });
      });
    }
  }
  class SMCPaneView {
    constructor(src) { this._src = src; this._renderer = new SMCRenderer(src); }
    update() {}
    renderer() { return this._renderer; }
    zOrder() { return "bottom"; }   // detrás de las velas
  }
  class SMCPrimitive {
    constructor() { this._data = null; this._views = [new SMCPaneView(this)]; }
    attached(p) { this._series = p.series; this._chart = p.chart; this._requestUpdate = p.requestUpdate; }
    detached() { this._series = null; this._chart = null; }
    setData(d) { this._data = d; if (this._requestUpdate) this._requestUpdate(); }
    updateAllViews() { this._views.forEach((v) => v.update()); }
    paneViews() { return this._views; }
  }

  // --- Formateo ------------------------------------------------------
  function fmtPrice(n) {
    if (n >= 1000) return n.toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (n >= 1) return n.toLocaleString("es", { maximumFractionDigits: 4 });
    return n.toLocaleString("es", { maximumFractionDigits: 6 });
  }
  function fmtQty(n) {
    return n.toLocaleString("es", { maximumFractionDigits: 4 });
  }
  function fmtCompact(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toFixed(2);
  }

  // --- Estado de conexión -------------------------------------------
  function setStatus(state) {
    statusDot.className = "dot";
    if (state === "ok") { statusDot.classList.add("ok"); statusText.textContent = "en vivo"; }
    else if (state === "bad") { statusDot.classList.add("bad"); statusText.textContent = "error de datos"; }
    else { statusText.textContent = "conectando…"; }
  }

  // --- Crear / obtener la tarjeta de un instrumento ------------------
  function getCard(symbol, label) {
    if (cards[symbol]) return cards[symbol];
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.querySelector(".ic-symbol").textContent = label || symbol;
    container.appendChild(node);
    const chartEl = node.querySelector(".chart");
    const card = { node, chartEl, lastPrice: null, timeframe: DEFAULT_TF,
                   candles: [], bars: [], smc: null, priceLines: [], fitted: false };
    cards[symbol] = card;

    createChart(card);
    buildTimeframeSelector(symbol, card);
    setupExpand(card);
    loadCandles(symbol, card); // primera carga
    loadSMC(symbol, card);     // análisis SMC en vivo
    card.refreshTimer = setInterval(() => loadCandles(symbol, card), CANDLE_REFRESH_MS);
    card.smcTimer = setInterval(() => loadSMC(symbol, card), SMC_REFRESH_MS);
    return card;
  }

  // --- Gráfico interactivo (TradingView Lightweight Charts) ----------
  function createChart(card) {
    if (!window.LightweightCharts) return;
    const LC = window.LightweightCharts;
    const chart = LC.createChart(card.chartEl, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: "#8b93a7",
                fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif" },
      grid: { vertLines: { color: "rgba(255,255,255,0.04)" }, horzLines: { color: "rgba(255,255,255,0.04)" } },
      crosshair: { mode: LC.CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#262b38" },
      timeScale: { borderColor: "#262b38", timeVisible: true, secondsVisible: false },
      localization: { locale: "es" },
    });
    const series = chart.addSeries(LC.CandlestickSeries, {
      upColor: "#16c784", downColor: "#ea3943", borderVisible: false,
      wickUpColor: "#16c784", wickDownColor: "#ea3943",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    const prim = new SMCPrimitive();
    series.attachPrimitive(prim);
    card.chart = chart;
    card.series = series;
    card.smcPrim = prim;
  }

  // Actualiza la última vela con el precio en vivo del SSE.
  function liveUpdate(card) {
    if (!card.series || !card.bars.length || card.lastPrice == null) return;
    const last = card.bars[card.bars.length - 1];
    card.series.update({
      time: last.time, open: last.open,
      high: Math.max(last.high, card.lastPrice),
      low: Math.min(last.low, card.lastPrice),
      close: card.lastPrice,
    });
  }

  // Pide el análisis SMC en vivo y lo proyecta como price lines + primitive.
  async function loadSMC(symbol, card) {
    const tf = card.timeframe;
    try {
      const r = await fetch(`api/smc?instrument=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(tf)}`);
      if (!r.ok) return;
      const j = await r.json();
      if (card.timeframe !== tf) return;
      card.smc = j;
      applySMC(card);
      renderSMCPanel(card);
    } catch (err) { /* mantenemos el análisis previo */ }
  }

  function applySMC(card) {
    if (!card.series || !window.LightweightCharts) return;
    const LC = window.LightweightCharts;
    // Niveles de liquidez y equilibrio como price lines (se alinean solas).
    card.priceLines.forEach((pl) => card.series.removePriceLine(pl));
    card.priceLines = [];
    const addLine = (price, color, title) => {
      if (!price) return;
      card.priceLines.push(card.series.createPriceLine({
        price, color, lineWidth: 1, lineStyle: LC.LineStyle.Dashed,
        axisLabelVisible: true, title,
      }));
    };
    const rng = card.smc && card.smc.range;
    if (rng) {
      addLine(rng.strong_high, "#ea3943", "Strong High");
      addLine(rng.weak_low, "#16c784", "Weak Low");
      addLine(rng.eq, "#a29bfe", "EQ 50%");
    }
    // Cajas (premium/discount, FVG, POIs) vía primitive custom.
    card.smcPrim.setData(card.smc);
  }

  // --- Selector de temporalidad --------------------------------------
  function buildTimeframeSelector(symbol, card) {
    const sel = card.node.querySelector(".tf-selector");
    if (!sel) return;
    sel.innerHTML = "";
    TIMEFRAMES.forEach((tf) => {
      const btn = document.createElement("button");
      btn.className = "tf-btn" + (tf === card.timeframe ? " active" : "");
      btn.textContent = tf;
      btn.dataset.tf = tf;
      btn.setAttribute("aria-pressed", tf === card.timeframe ? "true" : "false");
      btn.addEventListener("click", () => {
        if (card.timeframe === tf) return;
        card.timeframe = tf;
        sel.querySelectorAll(".tf-btn").forEach((b) => {
          const on = b.dataset.tf === tf;
          b.classList.toggle("active", on);
          b.setAttribute("aria-pressed", on ? "true" : "false");
        });
        card.smc = null;      // el SMC depende de la TF seleccionada (estructura/FVG)
        card.fitted = false;  // reajustamos la vista a la nueva resolución
        loadCandles(symbol, card);
        loadSMC(symbol, card);
      });
      sel.appendChild(btn);
    });
  }

  // --- Expandir / colapsar el gráfico (pantalla completa) ------------
  function setupExpand(card) {
    const wrap = card.node.querySelector(".chart-wrap");
    const btn = card.node.querySelector(".chart-expand");
    if (!btn || !wrap) return;
    btn.addEventListener("click", () => {
      const open = wrap.classList.toggle("expanded");
      document.body.classList.toggle("chart-open", open);
      btn.textContent = open ? "✕" : "⤢";
      btn.title = open ? "Cerrar" : "Expandir";
      // autoSize redimensiona solo; forzamos un reflow del rango por las dudas.
      setTimeout(() => { if (card.chart) card.chart.timeScale().scrollToRealTime(); }, 60);
    });
  }

  // Pide al backend las velas del par y las carga en el gráfico.
  async function loadCandles(symbol, card) {
    const tf = card.timeframe;
    try {
      const r = await fetch(`api/candles?instrument=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(tf)}`);
      if (!r.ok) return;
      const j = await r.json();
      if (card.timeframe !== tf || !Array.isArray(j.candles) || !card.series) return;
      card.candles = j.candles;
      card.bars = j.candles.map((c) => ({
        time: Math.floor(c.t / 1000), open: c.o, high: c.h, low: c.l, close: c.c,
      }));
      // Preservamos el zoom/paneo del usuario en los refrescos; solo reencuadramos
      // en la primera carga o al cambiar de temporalidad.
      const range = card.chart.timeScale().getVisibleLogicalRange();
      card.series.setData(card.bars);
      if (card.fitted && range) card.chart.timeScale().setVisibleLogicalRange(range);
      else { card.chart.timeScale().fitContent(); card.fitted = true; }
      liveUpdate(card);
    } catch (err) {
      /* dejamos las velas que ya teníamos */
    }
  }

  // --- Render principal ----------------------------------------------
  function render(state) {
    if (state.upstream_ok) setStatus("ok");
    else if (Object.keys(state.instruments || {}).length) setStatus("bad");

    if (state.updated) {
      lastUpdateEl.textContent = new Date(state.updated).toLocaleTimeString("es");
    }

    const insts = state.instruments || {};
    Object.keys(insts).forEach((symbol) => {
      const d = insts[symbol];
      const card = getCard(symbol, d.label);
      renderTicker(card, d.ticker);  // fija card.lastPrice
      renderStats(card, d.ticker);
      renderBook(card, d.book, d.ticker);
      renderSignals(card, d.signals || {});
      liveUpdate(card);              // mueve la última vela con el precio en vivo
    });
  }

  function renderTicker(card, t) {
    if (!t) return;
    const priceEl = card.node.querySelector(".ic-price");
    const newPrice = t.last;
    if (card.lastPrice !== null && newPrice !== card.lastPrice) {
      const dir = newPrice > card.lastPrice ? "flash-up" : "flash-down";
      priceEl.classList.remove("flash-up", "flash-down");
      void priceEl.offsetWidth; // reinicia la animación
      priceEl.classList.add(dir);
      setTimeout(() => priceEl.classList.remove(dir), 350);
    }
    card.lastPrice = newPrice;
    priceEl.textContent = fmtPrice(newPrice);

    const changeEl = card.node.querySelector(".ic-change");
    const pct = (t.change || 0) * 100;
    changeEl.textContent = (pct >= 0 ? "▲ " : "▼ ") + Math.abs(pct).toFixed(2) + "%";
    changeEl.className = "ic-change " + (pct >= 0 ? "up" : "down");
  }

  function renderStats(card, t) {
    if (!t) return;
    card.node.querySelector(".ic-high").textContent = fmtPrice(t.high);
    card.node.querySelector(".ic-low").textContent = fmtPrice(t.low);
    card.node.querySelector(".ic-bid").textContent = fmtPrice(t.bid);
    card.node.querySelector(".ic-ask").textContent = fmtPrice(t.ask);
    card.node.querySelector(".ic-vol").textContent = fmtCompact(t.volume);
  }

  function renderBook(card, book, ticker) {
    if (!book) return;
    const asksEl = card.node.querySelector(".book-side.asks");
    const bidsEl = card.node.querySelector(".book-side.bids");
    const spreadEl = card.node.querySelector(".book-spread");

    const asks = (book.asks || []).slice(0, 8);
    const bids = (book.bids || []).slice(0, 8);
    const maxQty = Math.max(
      1e-9,
      ...asks.map((l) => l.qty),
      ...bids.map((l) => l.qty)
    );

    function rowHTML(level) {
      const w = (level.qty / maxQty) * 100;
      return `<div class="book-row">
        <span class="depth" style="width:${w}%"></span>
        <span class="price">${fmtPrice(level.price)}</span>
        <span class="qty">${fmtQty(level.qty)}</span>
      </div>`;
    }

    // Asks de mayor a menor (el mejor ask queda abajo, pegado al spread).
    asksEl.innerHTML = asks.slice().reverse().map(rowHTML).join("");
    bidsEl.innerHTML = bids.map(rowHTML).join("");

    if (asks.length && bids.length) {
      const spread = asks[0].price - bids[0].price;
      const mid = (asks[0].price + bids[0].price) / 2;
      const bps = mid > 0 ? (spread / mid) * 10000 : 0;
      spreadEl.textContent = `spread ${fmtPrice(spread)} · ${bps.toFixed(1)} bps`;
    }
  }

  function renderSignals(card, s) {
    const n = card.node;
    // Posición en el rango 24h
    const rangeFill = n.querySelector(".bar-fill.range");
    rangeFill.style.width = (s.range_pos || 0) + "%";
    n.querySelector(".sig-range").textContent = (s.range_pos != null ? s.range_pos.toFixed(0) : "—") + "%";

    // Momentum
    const momEl = n.querySelector(".sig-mom");
    const mom = s.momentum_15 || 0;
    momEl.textContent = (mom >= 0 ? "+" : "") + mom.toFixed(2) + "%";
    momEl.className = "v sig-mom " + (mom > 0 ? "up" : mom < 0 ? "down" : "");

    // Spread
    n.querySelector(".sig-spread").textContent = (s.spread_bps != null ? s.spread_bps.toFixed(1) : "—") + " bps";

    // Desequilibrio del libro (-100 vendedor … +100 comprador)
    const imb = s.book_imbalance || 0;
    const imbFill = n.querySelector(".bar-fill.imb");
    const half = Math.min(50, Math.abs(imb) / 2);
    if (imb >= 0) { imbFill.style.left = "50%"; imbFill.style.width = half + "%"; imbFill.style.background = "var(--green)"; }
    else { imbFill.style.left = (50 - half) + "%"; imbFill.style.width = half + "%"; imbFill.style.background = "var(--red)"; }
    const imbEl = n.querySelector(".sig-imb");
    imbEl.textContent = (imb >= 0 ? "+" : "") + imb.toFixed(0);
    imbEl.className = "v sig-imb " + (imb > 0 ? "up" : imb < 0 ? "down" : "");
  }

  // --- Panel "POIs activos" ------------------------------------------
  function renderSMCPanel(card) {
    const el = card.node.querySelector(".smc-list");
    if (!el) return;
    const pois = (card.smc && card.smc.active_pois) || [];
    if (!pois.length) {
      el.innerHTML = '<div class="smc-empty">Sin POIs válidos cerca del precio ahora.</div>';
      return;
    }
    el.innerHTML = pois.map((p) => {
      const zona = p.discount ? "descuento" : "premium";
      const cls = p.discount ? "discount" : "premium";
      const dist = (p.dist_pct > 0 ? "+" : "") + p.dist_pct + "%";
      const here = p.in_zone ? '<span class="smc-here">● en zona</span>' : "";
      return `<div class="smc-poi ${cls}">
        <span class="smc-tf">POI ${p.tf}</span>
        <span class="smc-range">${fmtPrice(p.lo)}–${fmtPrice(p.hi)}</span>
        <span class="smc-zone">${zona}</span>
        <span class="smc-dist">${dist}</span>${here}
      </div>`;
    }).join("");
  }

  // El gráfico (Lightweight Charts) se redimensiona solo con autoSize.
  let lastState = null;

  // --- Conexión: SSE con respaldo a polling --------------------------
  function connectSSE() {
    const es = new EventSource("api/stream");
    es.onmessage = (e) => {
      try {
        lastState = JSON.parse(e.data);
        render(lastState);
      } catch (err) { /* ignoramos frames mal formados */ }
    };
    es.onerror = () => {
      setStatus("");
      // EventSource reintenta solo; si no, el respaldo de polling cubre.
    };
  }

  async function pollOnce() {
    try {
      const r = await fetch("api/state");
      lastState = await r.json();
      render(lastState);
    } catch (err) { setStatus("bad"); }
  }

  // Cargamos la config del módulo (temporalidades + default) y luego arrancamos
  // la conexión en vivo. Si la config falla, usamos los valores por defecto.
  async function init() {
    try {
      const cfg = await fetch("api/config").then((r) => r.json());
      if (Array.isArray(cfg.timeframes) && cfg.timeframes.length) TIMEFRAMES = cfg.timeframes;
      if (cfg.default_timeframe) DEFAULT_TF = cfg.default_timeframe;
    } catch (err) {
      /* nos quedamos con TIMEFRAMES/DEFAULT_TF por defecto */
    }

    // Arrancamos con SSE; además un polling lento de respaldo por si acaso.
    if (window.EventSource) {
      connectSSE();
    } else {
      pollOnce();
      setInterval(pollOnce, 3000);
    }
    setupAlerts();
  }

  // --- Alertas push (reusa el web push ya cableado) ------------------
  function setupAlerts() {
    const btn = document.getElementById("alert-btn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      if (!window.NexusPush) { btn.textContent = "🔕 Push no soportado"; return; }
      btn.disabled = true;
      btn.textContent = "Activando…";
      try {
        await window.NexusPush.activar();
        btn.classList.add("on");
        btn.textContent = "🔔 Alertas activas";
      } catch (err) {
        btn.textContent = "🔕 " + (err && err.message ? err.message : "no se pudo activar");
        setTimeout(() => { btn.textContent = "🔔 Alertas SMC"; btn.disabled = false; }, 4000);
        return;
      }
      btn.disabled = false;
    });
  }

  init();
})();
