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
    const canvas = node.querySelector(".chart");
    // Cada par recuerda su propia temporalidad y sus velas (estado en el front).
    const card = { node, canvas, lastPrice: null, timeframe: DEFAULT_TF, candles: [], smc: null };
    cards[symbol] = card;

    buildTimeframeSelector(symbol, card);
    loadCandles(symbol, card); // primera carga
    loadSMC(symbol, card);     // análisis SMC en vivo
    // Refrescos periódicos.
    card.refreshTimer = setInterval(() => loadCandles(symbol, card), CANDLE_REFRESH_MS);
    card.smcTimer = setInterval(() => loadSMC(symbol, card), SMC_REFRESH_MS);

    return card;
  }

  function redraw(card) { drawChart(card.canvas, chartData(card), card.smc); }

  // Pide el análisis SMC en vivo (estructura, premium/discount, FVG y POIs de
  // 1D/4h/1h) y actualiza el gráfico y el panel "POIs activos".
  async function loadSMC(symbol, card) {
    const tf = card.timeframe;
    try {
      const r = await fetch(`api/smc?instrument=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(tf)}`);
      if (!r.ok) return;
      const j = await r.json();
      if (card.timeframe !== tf) return;
      card.smc = j;
      redraw(card);
      renderSMCPanel(card);
    } catch (err) { /* mantenemos el análisis previo */ }
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
        card.smc = null; // el SMC depende de la TF seleccionada (estructura/FVG)
        loadCandles(symbol, card); // recarga con la nueva resolución
        loadSMC(symbol, card);
      });
      sel.appendChild(btn);
    });
  }

  // Pide al backend las velas del par en la temporalidad activa y redibuja.
  async function loadCandles(symbol, card) {
    const tf = card.timeframe;
    try {
      const r = await fetch(`api/candles?instrument=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(tf)}`);
      if (!r.ok) return;
      const j = await r.json();
      if (card.timeframe !== tf) return; // el usuario cambió mientras tanto
      if (Array.isArray(j.candles)) {
        card.candles = j.candles;
        redraw(card);
      }
    } catch (err) {
      /* dejamos las velas que ya teníamos */
    }
  }

  // Combina las velas cargadas con el precio en vivo: la última vela y la línea
  // de precio se mueven con cada tick del SSE, sin esperar el próximo refresco.
  function chartData(card) {
    const cs = card.candles;
    if (!cs || !cs.length) return [];
    if (card.lastPrice == null) return cs;
    const out = cs.slice();
    const last = Object.assign({}, out[out.length - 1]);
    last.c = card.lastPrice;
    last.h = Math.max(last.h, card.lastPrice);
    last.l = Math.min(last.l, card.lastPrice);
    out[out.length - 1] = last;
    return out;
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
      renderTicker(card, d.ticker);
      renderStats(card, d.ticker);
      renderBook(card, d.book, d.ticker);
      renderSignals(card, d.signals || {});
      // El gráfico usa las velas de la temporalidad elegida (api/candles), con
      // el precio en vivo del SSE sobre la última vela, más el overlay SMC.
      redraw(card);
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

  // --- Gráfico de velas (canvas, sin librerías) ----------------------
  function drawChart(canvas, candles, smc) {
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 600;
    const cssH = canvas.clientHeight || 240;
    if (canvas.width !== cssW * dpr || canvas.height !== cssH * dpr) {
      canvas.width = cssW * dpr;
      canvas.height = cssH * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    if (!candles.length) return;

    // Mostramos las últimas N velas que entren cómodas.
    const padR = 58, padL = 8, padT = 10, padB = 18;
    const plotW = cssW - padR - padL;
    const plotH = cssH - padT - padB;

    const maxBars = Math.min(candles.length, Math.floor(plotW / 6));
    const data = candles.slice(-maxBars);

    let hi = -Infinity, lo = Infinity;
    data.forEach((c) => { hi = Math.max(hi, c.h); lo = Math.min(lo, c.l); });
    if (hi === lo) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.08;
    hi += pad; lo -= pad;

    const x = (i) => padL + (i + 0.5) * (plotW / data.length);
    const y = (p) => padT + (1 - (p - lo) / (hi - lo)) * plotH;

    // Rejilla + etiquetas de precio
    ctx.font = "10px -apple-system, sans-serif";
    ctx.textBaseline = "middle";
    ctx.strokeStyle = "rgba(255,255,255,0.05)";
    ctx.fillStyle = "#8b93a7";
    const gridN = 4;
    for (let g = 0; g <= gridN; g++) {
      const p = lo + (hi - lo) * (g / gridN);
      const yy = y(p);
      ctx.beginPath();
      ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
      ctx.fillText(fmtPrice(p), padL + plotW + 6, yy);
    }

    // --- Overlay SMC (contexto, detrás de las velas) ------------------
    if (smc) drawSMC(ctx, smc, { padL, padT, plotW, plotH, y, hi, lo });

    // Velas
    const cw = Math.max(1.5, (plotW / data.length) * 0.62);
    data.forEach((c, i) => {
      const up = c.c >= c.o;
      const col = up ? "#16c784" : "#ea3943";
      const cx = x(i);
      ctx.strokeStyle = col;
      ctx.fillStyle = col;
      // mecha
      ctx.beginPath();
      ctx.moveTo(cx, y(c.h)); ctx.lineTo(cx, y(c.l)); ctx.stroke();
      // cuerpo
      const yo = y(c.o), yc = y(c.c);
      const top = Math.min(yo, yc);
      const h = Math.max(1, Math.abs(yc - yo));
      ctx.fillRect(cx - cw / 2, top, cw, h);
    });

    // Línea del precio actual
    const lastC = data[data.length - 1].c;
    const yL = y(lastC);
    ctx.strokeStyle = "rgba(162,155,254,0.7)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(padL, yL); ctx.lineTo(padL + plotW, yL); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#a29bfe";
    ctx.fillRect(padL + plotW, yL - 8, padR - 6, 16);
    ctx.fillStyle = "#0f1117";
    ctx.fillText(fmtPrice(lastC), padL + plotW + 4, yL);
  }

  // --- Overlay SMC sobre el gráfico ----------------------------------
  function drawSMC(ctx, smc, d) {
    const { padL, padT, plotW, plotH, y } = d;
    const top = padT, bot = padT + plotH, right = padL + plotW;
    const clamp = (v) => Math.max(top, Math.min(bot, v));
    ctx.font = "9px -apple-system, sans-serif";
    ctx.textBaseline = "alphabetic";

    // Premium / discount + equilibrio 50%.
    const rng = smc.range;
    if (rng && rng.eq) {
      const yEq = y(rng.eq);
      if (yEq > top && yEq < bot) {
        ctx.fillStyle = "rgba(234,57,67,0.05)"; ctx.fillRect(padL, top, plotW, yEq - top);     // premium
        ctx.fillStyle = "rgba(22,199,132,0.05)"; ctx.fillRect(padL, yEq, plotW, bot - yEq);     // discount
        ctx.strokeStyle = "rgba(162,155,254,0.55)"; ctx.setLineDash([2, 3]);
        ctx.beginPath(); ctx.moveTo(padL, yEq); ctx.lineTo(right, yEq); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = "#a29bfe"; ctx.fillText("EQ 50%", padL + 3, yEq - 3);
      }
      // Liquidez: Strong High / Weak Low.
      [["strong_high", "Strong High · Liquidez", "#ea3943"],
       ["weak_low", "Weak Low · Liquidez", "#16c784"]].forEach(([k, lbl, col]) => {
        const p = rng[k]; if (!p) return;
        const yy = y(p); if (yy <= top || yy >= bot) return;
        ctx.strokeStyle = col; ctx.globalAlpha = 0.5; ctx.setLineDash([5, 4]);
        ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(right, yy); ctx.stroke();
        ctx.setLineDash([]); ctx.globalAlpha = 1;
        ctx.fillStyle = col; ctx.fillText(lbl, padL + 3, yy - 3);
      });
    }

    // FVGs sin rellenar (imbalances) — bandas tenues.
    (smc.fvgs || []).filter((f) => !f.filled).forEach((f) => {
      const a = clamp(y(f.hi)), b = clamp(y(f.lo));
      if (Math.abs(b - a) < 0.5) return;
      ctx.fillStyle = f.bullish ? "rgba(108,92,231,0.12)" : "rgba(245,166,35,0.12)";
      ctx.fillRect(right - plotW * 0.35, Math.min(a, b), plotW * 0.35, Math.abs(b - a));
    });

    // Cajas de POI (order blocks). Verde = descuento/long, rojo = premium/short.
    (smc.pois || []).forEach((poi) => {
      const a = y(poi.hi), b = y(poi.lo);
      const t = Math.min(a, b), bt = Math.max(a, b);
      if (bt < top || t > bot) return; // fuera de vista
      const ct = clamp(t), cb = clamp(bt);
      const long = poi.dir === "long";
      const base = long ? "22,199,132" : "234,57,67";
      ctx.fillStyle = `rgba(${base},${poi.valid ? 0.14 : 0.05})`;
      ctx.fillRect(padL, ct, plotW, cb - ct);
      ctx.strokeStyle = `rgba(${base},${poi.valid ? 0.7 : 0.3})`;
      ctx.setLineDash(poi.valid ? [] : [3, 3]);
      ctx.strokeRect(padL, ct, plotW, cb - ct);
      ctx.setLineDash([]);
      ctx.fillStyle = long ? "#16c784" : "#ea3943";
      ctx.fillText(`POI ${poi.tf} ${poi.valid ? "✓" : "✕"}`, padL + 4, ct + 9);
    });
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

  // Redibuja los gráficos al cambiar el tamaño de la ventana.
  let lastState = null;
  window.addEventListener("resize", () => { if (lastState) render(lastState); });

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
