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
      const D = src._data;
      if (!D || !src._series) return;
      const smc = D.smc;
      const show = D.show || {};
      const series = src._series;
      const ts = src._chart.timeScale();
      const py = (p) => series.priceToCoordinate(p);
      const tx = (tms) => ts.timeToCoordinate(Math.floor(tms / 1000));
      target.useMediaCoordinateSpace((scope) => {
        const ctx = scope.context;
        const W = scope.mediaSize.width, H = scope.mediaSize.height;

        // --- Capa LuxAlgo: cinta de tendencia (EMA 21/55), detrás de todo ---
        if (show.ribbon && D.ribbon && D.ribbon.length) {
          const pts = D.ribbon;
          for (let i = 1; i < pts.length; i++) {
            const a = pts[i - 1], b = pts[i];
            if (a.f == null || a.s == null || b.f == null || b.s == null) continue;
            const xa = ts.timeToCoordinate(a.t), xb = ts.timeToCoordinate(b.t);
            if (xa == null || xb == null) continue;
            const yaf = py(a.f), yas = py(a.s), ybf = py(b.f), ybs = py(b.s);
            if (yaf == null || yas == null || ybf == null || ybs == null) continue;
            const bull = (a.f + b.f) >= (a.s + b.s);
            ctx.fillStyle = bull ? "rgba(22,199,132,0.10)" : "rgba(234,57,67,0.10)";
            ctx.beginPath(); ctx.moveTo(xa, yaf); ctx.lineTo(xb, ybf);
            ctx.lineTo(xb, ybs); ctx.lineTo(xa, yas); ctx.closePath(); ctx.fill();
          }
          const drawEma = (key, color) => {
            ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.beginPath(); let on = false;
            for (const p of pts) {
              const x = ts.timeToCoordinate(p.t), y = py(p[key]);
              if (x == null || y == null) { on = false; continue; }
              if (!on) { ctx.moveTo(x, y); on = true; } else ctx.lineTo(x, y);
            }
            ctx.stroke();
          };
          drawEma("f", "rgba(162,155,254,0.55)");
          drawEma("s", "rgba(139,147,167,0.5)");
        }

        if (!smc) return;
        // --- Overlay SMC (siempre): premium/discount, FVG, POIs ---
        if (smc.range && smc.range.eq) {
          const yEq = py(smc.range.eq);
          if (yEq != null) {
            ctx.fillStyle = "rgba(234,57,67,0.05)"; ctx.fillRect(0, 0, W, yEq);
            ctx.fillStyle = "rgba(22,199,132,0.05)"; ctx.fillRect(0, yEq, W, H - yEq);
          }
        }
        ctx.font = "9px -apple-system, sans-serif"; ctx.textBaseline = "top";
        (smc.fvgs || []).filter((f) => !f.filled).forEach((f) => {
          const y1 = py(f.hi), y2 = py(f.lo); if (y1 == null || y2 == null) return;
          let x = tx(f.t); if (x == null) x = 0; x = Math.max(0, x);
          const top = Math.min(y1, y2);
          ctx.fillStyle = f.bullish ? "rgba(108,92,231,0.13)" : "rgba(245,166,35,0.13)";
          ctx.fillRect(x, top, W - x, Math.abs(y2 - y1));
          ctx.fillStyle = f.bullish ? "#a29bfe" : "#f5a623";
          ctx.fillText(f.bullish ? "FVG↑" : "FVG↓", x + 3, top + 1);
        });
        ctx.font = "10px -apple-system, sans-serif"; ctx.textBaseline = "top";
        (smc.pois || []).forEach((poi) => {
          const y1 = py(poi.hi), y2 = py(poi.lo); if (y1 == null || y2 == null) return;
          const top = Math.min(y1, y2), h = Math.max(1, Math.abs(y2 - y1));
          const long = poi.dir === "long";
          const base = long ? "22,199,132" : "234,57,67";
          ctx.fillStyle = `rgba(${base},${poi.valid ? 0.13 : 0.05})`;
          ctx.fillRect(0, top, W, h);
          ctx.strokeStyle = `rgba(${base},${poi.valid ? 0.7 : 0.3})`;
          ctx.lineWidth = 1; ctx.setLineDash(poi.valid ? [] : [3, 3]);
          ctx.strokeRect(0.5, top + 0.5, W - 1, h); ctx.setLineDash([]);
          ctx.fillStyle = long ? "#16c784" : "#ea3943";
          ctx.fillText(`POI ${poi.tf} ${poi.valid ? "✓" : "✕"}`, 5, top + 2);
        });

        // --- Capa LuxAlgo: niveles Weak/Strong con % ---
        if (show.levels && smc.levels) {
          ctx.font = "9px -apple-system, sans-serif"; ctx.textBaseline = "middle";
          smc.levels.forEach((lv) => {
            const y = py(lv.price); if (y == null) return;
            const high = lv.type === "high";
            const col = high ? "#ea3943" : "#16c784";
            ctx.strokeStyle = col; ctx.globalAlpha = lv.kind === "weak" ? 0.55 : 0.3;
            ctx.setLineDash([1, 4]); ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
            ctx.setLineDash([]); ctx.globalAlpha = 1;
            ctx.fillStyle = col;
            const txt = `${lv.label}${lv.pct != null ? " " + lv.pct + "%" : ""}`;
            ctx.fillText(txt, 4, y + (high ? -6 : 6));
          });
        }

        // --- Capa LuxAlgo: proyección TP/SL (escenario, NO señal) ---
        if (show.tpsl && smc.tpsl) {
          const t = smc.tpsl;
          ctx.font = "9px -apple-system, sans-serif"; ctx.textBaseline = "middle";
          const line = (price, color, label) => {
            if (price == null) return;
            const y = py(price); if (y == null) return;
            ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); ctx.setLineDash([]);
            ctx.fillStyle = color;
            const tw = ctx.measureText(label).width;
            ctx.fillText(label, W - tw - 6, y - 5);
          };
          line(t.sl, "#ea3943", "SL");
          line(t.tp1, "rgba(22,199,132,0.8)", "TP1 (1R)");
          line(t.tp2, "rgba(22,199,132,0.9)", "TP2 (2R)");
          line(t.tp3, "#16c784", "TP3 (3R)");
          line(t.liq, "#a29bfe", "Liquidez");
        }
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

  // --- Indicadores (Vol / RSI / ADX) ---------------------------------
  // Estado global (mismo para todos los pares), recordado en localStorage.
  const IND_KEY = "nexus_trading_ind";
  const IND_DEFAULTS = { vol: true, rsi: false, adx: false, ribbon: false, levels: false, tpsl: false };
  let indState = (() => {
    try { return Object.assign({}, IND_DEFAULTS, JSON.parse(localStorage.getItem(IND_KEY) || "{}")); }
    catch (e) { return Object.assign({}, IND_DEFAULTS); }
  })();
  function emaArr(values, period) {
    const k = 2 / (period + 1), out = [];
    for (let i = 0; i < values.length; i++) out.push(i === 0 ? values[0] : values[i] * k + out[i - 1] * (1 - k));
    return out;
  }
  function luxShow() { return { ribbon: indState.ribbon, levels: indState.levels, tpsl: indState.tpsl }; }
  function saveIndState() { try { localStorage.setItem(IND_KEY, JSON.stringify(indState)); } catch (e) {} }

  function rsiCalc(closes, p) {
    const n = closes.length, out = new Array(n).fill(null);
    if (n <= p) return out;
    let g = 0, l = 0;
    for (let i = 1; i <= p; i++) { const d = closes[i] - closes[i - 1]; if (d >= 0) g += d; else l -= d; }
    let ag = g / p, al = l / p;
    out[p] = 100 - 100 / (1 + (al === 0 ? 1e9 : ag / al));
    for (let i = p + 1; i < n; i++) {
      const d = closes[i] - closes[i - 1];
      ag = (ag * (p - 1) + (d > 0 ? d : 0)) / p;
      al = (al * (p - 1) + (d < 0 ? -d : 0)) / p;
      out[i] = 100 - 100 / (1 + (al === 0 ? 1e9 : ag / al));
    }
    return out;
  }

  function adxCalc(h, l, c, p) {
    const n = h.length, out = new Array(n).fill(null);
    if (n < 2 * p + 1) return out;
    const tr = [0], pdm = [0], ndm = [0];
    for (let i = 1; i < n; i++) {
      const up = h[i] - h[i - 1], dn = l[i - 1] - l[i];
      pdm.push(up > dn && up > 0 ? up : 0);
      ndm.push(dn > up && dn > 0 ? dn : 0);
      tr.push(Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1])));
    }
    let atr = 0, sp = 0, sn = 0;
    for (let i = 1; i <= p; i++) { atr += tr[i]; sp += pdm[i]; sn += ndm[i]; }
    const dx = new Array(n).fill(null);
    for (let i = p + 1; i < n; i++) {
      atr = atr - atr / p + tr[i]; sp = sp - sp / p + pdm[i]; sn = sn - sn / p + ndm[i];
      const pdi = atr ? 100 * sp / atr : 0, ndi = atr ? 100 * sn / atr : 0, sum = pdi + ndi;
      dx[i] = sum ? 100 * Math.abs(pdi - ndi) / sum : 0;
    }
    let adxv = null, cnt = 0, acc = 0;
    for (let i = p + 1; i < n; i++) {
      if (dx[i] == null) continue;
      if (adxv == null) { acc += dx[i]; cnt++; if (cnt === p) { adxv = acc / p; out[i] = adxv; } }
      else { adxv = (adxv * (p - 1) + dx[i]) / p; out[i] = adxv; }
    }
    return out;
  }

  // (Re)crea las series de indicadores de una tarjeta según indState.
  function buildIndicators(card) {
    if (!card.chart || !window.LightweightCharts) return;
    const LC = window.LightweightCharts;
    card.ind = card.ind || {};
    ["vol", "rsi", "adx"].forEach((k) => {
      if (card.ind[k]) { try { card.chart.removeSeries(card.ind[k]); } catch (e) {} card.ind[k] = null; }
    });
    if (indState.vol) {
      const v = card.chart.addSeries(LC.HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" }, 0);
      v.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
      card.ind.vol = v;
    }
    let pane = 1;
    if (indState.rsi) {
      const r = card.chart.addSeries(LC.LineSeries, { color: "#a29bfe", lineWidth: 1, priceLineVisible: false,
        priceFormat: { type: "price", precision: 1, minMove: 0.1 } }, pane);
      [[70, "rgba(234,57,67,0.45)"], [30, "rgba(22,199,132,0.45)"], [50, "rgba(139,147,167,0.3)"]].forEach(
        ([pr, co]) => r.createPriceLine({ price: pr, color: co, lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true }));
      card.ind.rsi = r; pane++;
    }
    if (indState.adx) {
      const a = card.chart.addSeries(LC.LineSeries, { color: "#f5a623", lineWidth: 1, priceLineVisible: false,
        priceFormat: { type: "price", precision: 1, minMove: 0.1 } }, pane);
      a.createPriceLine({ price: 25, color: "rgba(139,147,167,0.4)", lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true });
      card.ind.adx = a; pane++;
    }
    const panes = card.chart.panes();
    for (let i = 1; i < panes.length; i++) { try { panes[i].setHeight(card.expanded ? 130 : 84); } catch (e) {} }
    setIndicatorData(card);
  }

  function _ohlc(card) {
    const cs = card.candles || [];
    const closes = cs.map((c) => c.c), highs = cs.map((c) => c.h), lows = cs.map((c) => c.l);
    if (card.lastPrice != null && cs.length) {
      const i = cs.length - 1;
      closes[i] = card.lastPrice;
      highs[i] = Math.max(highs[i], card.lastPrice);
      lows[i] = Math.min(lows[i], card.lastPrice);
    }
    return { cs, closes, highs, lows };
  }

  function setIndicatorData(card) {
    if (!card.ind) return;
    const { cs, closes, highs, lows } = _ohlc(card);
    if (!cs.length) return;
    const ts = (c) => Math.floor(c.t / 1000);
    if (card.ind.vol) {
      card.ind.vol.setData(cs.map((c, i) => ({ time: ts(c), value: c.v,
        color: (i === cs.length - 1 ? card.lastPrice ?? c.c : c.c) >= c.o ? "rgba(22,199,132,0.5)" : "rgba(234,57,67,0.5)" })));
    }
    if (card.ind.rsi) {
      const r = rsiCalc(closes, 14);
      card.ind.rsi.setData(cs.map((c, i) => (r[i] == null ? null : { time: ts(c), value: r[i] })).filter(Boolean));
    }
    if (card.ind.adx) {
      const a = adxCalc(highs, lows, closes, 14);
      card.ind.adx.setData(cs.map((c, i) => (a[i] == null ? null : { time: ts(c), value: a[i] })).filter(Boolean));
    }
  }

  function updateIndicatorsLast(card) {
    if (!card.ind || card.lastPrice == null) return;
    const { cs, closes, highs, lows } = _ohlc(card);
    if (!cs.length) return;
    const t = Math.floor(cs[cs.length - 1].t / 1000);
    if (card.ind.vol) {
      const c = cs[cs.length - 1];
      card.ind.vol.update({ time: t, value: c.v, color: card.lastPrice >= c.o ? "rgba(22,199,132,0.5)" : "rgba(234,57,67,0.5)" });
    }
    if (card.ind.rsi) { const r = rsiCalc(closes, 14); const v = r[r.length - 1]; if (v != null) card.ind.rsi.update({ time: t, value: v }); }
    if (card.ind.adx) { const a = adxCalc(highs, lows, closes, 14); const v = a[a.length - 1]; if (v != null) card.ind.adx.update({ time: t, value: v }); }
  }

  // Botones de toggle por tarjeta; el estado es global y se aplica a todos.
  // Indicadores en panes (recrean series) y capas Lux (solo redibujan el primitive).
  const TOGGLE_GROUPS = {
    ".ind-toggles": [["vol", "Vol"], ["rsi", "RSI"], ["adx", "ADX"]],
    ".lux-toggles": [["ribbon", "Cinta"], ["levels", "Niveles"], ["tpsl", "TP/SL"]],
  };
  const PANE_INDICATORS = new Set(["vol", "rsi", "adx"]);

  function buildToggles(card) {
    Object.entries(TOGGLE_GROUPS).forEach(([sel, items]) => {
      const box = card.node.querySelector(sel);
      if (!box) return;
      box.innerHTML = "";
      items.forEach(([k, label]) => {
        const b = document.createElement("button");
        b.className = "tf-btn ind-btn" + (indState[k] ? " active" : "");
        b.textContent = label;
        b.dataset.ind = k;
        b.addEventListener("click", () => {
          indState[k] = !indState[k];
          saveIndState();
          if (PANE_INDICATORS.has(k)) Object.values(cards).forEach((c) => buildIndicators(c));
          else Object.values(cards).forEach((c) => { computeRibbon(c); pushPrim(c); });
          refreshToggleUI();
        });
        box.appendChild(b);
      });
    });
  }
  function refreshToggleUI() {
    Object.values(cards).forEach((c) => {
      c.node.querySelectorAll(".ind-btn").forEach((b) => {
        b.classList.toggle("active", !!indState[b.dataset.ind]);
      });
    });
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
    card.ind = {};
    buildToggles(card);
    buildIndicators(card);     // indicadores según el estado guardado
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
    updateIndicatorsLast(card);
    if (indState.ribbon) { computeRibbon(card); pushPrim(card); }
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
    pushPrim(card);
  }

  // Recalcula la cinta de tendencia (EMA 21/55) desde las velas, con el precio en vivo.
  function computeRibbon(card) {
    const cs = card.candles || [];
    if (!cs.length) { card.ribbon = []; return; }
    const closes = cs.map((c) => c.c);
    if (card.lastPrice != null) closes[closes.length - 1] = card.lastPrice;
    const f = emaArr(closes, 21), s = emaArr(closes, 55);
    card.ribbon = cs.map((c, i) => ({ t: Math.floor(c.t / 1000), f: f[i], s: s[i] }));
  }

  // Empuja al primitive todo lo que dibuja: overlay SMC + cinta + niveles + TP/SL.
  function pushPrim(card) {
    if (card.smcPrim) card.smcPrim.setData({ smc: card.smc, ribbon: card.ribbon || [], show: luxShow() });
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
      card.expanded = open;
      document.body.classList.toggle("chart-open", open);
      btn.textContent = open ? "✕" : "⤢";
      btn.title = open ? "Cerrar" : "Expandir";
      // autoSize redimensiona solo; ajustamos el alto de los subpanes y reencuadramos.
      setTimeout(() => {
        if (!card.chart) return;
        const panes = card.chart.panes();
        for (let i = 1; i < panes.length; i++) { try { panes[i].setHeight(open ? 130 : 84); } catch (e) {} }
        card.chart.timeScale().scrollToRealTime();
      }, 60);
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
      setIndicatorData(card);
      computeRibbon(card);
      pushPrim(card);
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
