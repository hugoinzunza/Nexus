const $ = (id) => document.getElementById(id);
const fmt = (value, digits = 2) => value == null ? "—" : Number(value).toLocaleString("es-CL", { maximumFractionDigits: digits });
const usd = (value) => value == null ? "—" : `US$${Number(value).toLocaleString("es-CL", { maximumFractionDigits: 0 })}`;
const compactUsd = (value) => {
  if (value == null) return "—";
  const number = Number(value);
  if (Math.abs(number) >= 1e9) return `US$${fmt(number / 1e9, 2)}B`;
  if (Math.abs(number) >= 1e6) return `US$${fmt(number / 1e6, 2)}M`;
  return usd(number);
};
const signed = (value, suffix = "", digits = 2) => value == null ? "—" : `${value >= 0 ? "+" : ""}${fmt(value, digits)}${suffix}`;
const escapeHtml = (value) => String(value ?? "—").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
let state = null;
let liquidationMode = "levels";

function latest(values) {
  return Array.isArray(values) && values.length ? values[values.length - 1] : null;
}

function metric(label, value, cls = "") {
  return `<div class="metric"><span>${label}</span><b class="${cls}">${value}</b></div>`;
}

function setupCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width: rect.width, height: rect.height };
}

function grid(ctx, width, height, left = 62, bottom = 30) {
  ctx.strokeStyle = "#222936";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = 18 + i * (height - bottom - 18) / 4;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - 12, y);
    ctx.stroke();
  }
}

function line(ctx, values, x, y, color) {
  const valid = values.map((value, index) => [index, Number(value)]).filter((row) => Number.isFinite(row[1]));
  if (valid.length < 2) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  valid.forEach(([index, value], point) => {
    const px = x(index, values.length);
    const py = y(value);
    if (point === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
  });
  ctx.stroke();
}

function renderHistory() {
  const canvas = $("history-chart");
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  grid(ctx, width, height);
  const rows = state.history || [];
  const oi = rows.map((row) => row.oi_usd ?? row.oi_btc);
  const funding = rows.map((row) => row.funding_pct);
  const allOi = oi.filter(Number.isFinite), allFunding = funding.filter(Number.isFinite);
  if (allOi.length < 2) {
    ctx.fillStyle = "#919baa";
    ctx.font = "12px sans-serif";
    ctx.fillText("Recolectando historia causal", 24, 38);
    return;
  }
  const scale = (values) => {
    const min = Math.min(...values), max = Math.max(...values);
    const span = max - min || 1;
    return (value) => 18 + (max - value) / span * (height - 48);
  };
  const x = (index, count) => 62 + index / Math.max(1, count - 1) * (width - 78);
  line(ctx, oi, x, scale(allOi), "#43bdd7");
  if (allFunding.length > 1) line(ctx, funding, x, scale(allFunding), "#e8b653");
  ctx.fillStyle = "#919baa";
  ctx.font = "10px ui-monospace, monospace";
  ctx.fillText(fmt(Math.max(...allOi), 0), 10, 25);
  ctx.fillText(fmt(Math.min(...allOi), 0), 10, height - 31);
}

function reason(capability) {
  if (capability?.available) return "Disponible";
  const text = String(capability?.reason || "No disponible");
  if (/plan|upgrade|permission|professional|403/i.test(text)) return "No incluido en el plan API";
  // Se escapa acá: el texto viene del payload de ingesta (token compartido) y se
  // interpola en innerHTML. Sin esto, quien tenga el token planta HTML en el
  // panel de un usuario logueado que sí puede llamar /m/bot/api/command.
  return escapeHtml(text.length > 90 ? `${text.slice(0, 87)}...` : text);
}

function renderCapabilities() {
  const labels = {
    liquidation_map: "Mapa de liquidaciones",
    liquidation_heatmap: "Heatmap agregado",
    orderbook_heatmap: "Heatmap order book",
    large_orders: "Órdenes grandes",
  };
  const capabilities = state.advanced?.capabilities || {};
  $("capabilities").innerHTML = Object.entries(labels).map(([key, label]) => {
    const capability = capabilities[key];
    return `<div class="capability ${capability?.available ? "ok" : "no"}"><b>${label}</b><span>${reason(capability)}</span></div>`;
  }).join("");
}

function renderOverview() {
  const basic = state.basic?.indicators || {};
  const intervals = state.basic?.intervals || {};
  const oi = basic.open_interest?.close_usd || basic.open_interest?.close_btc || [];
  const oiNow = latest(oi), oiPrev = oi.length > 1 ? oi[oi.length - 2] : null;
  const oiChange = oiNow != null && oiPrev ? (oiNow / oiPrev - 1) * 100 : null;
  const funding = latest(basic.funding?.close_pct);
  const liq = latest(basic.liquidations?.bars);
  const top = latest(basic.top_traders?.long_pct);
  const book = latest(basic.orderbook?.bid_ask_ratio);
  $("market-metrics").innerHTML =
    metric("Funding OI", signed(funding, "%", 4)) +
    metric("OI agregado", compactUsd(oiNow)) +
    metric(`Cambio OI ${intervals.open_interest || "1h"}`, signed(oiChange, "%"), (oiChange || 0) >= 0 ? "up" : "down") +
    metric("Liquidaciones L/S", liq ? `${fmt(liq.long_musd)}M / ${fmt(liq.short_musd)}M` : "—") +
    metric("Top traders long", top == null ? "—" : `${fmt(top)}%`) +
    metric("Book bid/ask ±1%", fmt(book, 2));
  renderHistory();
  renderCapabilities();
  const analysis = state.basic_analysis || {};
  const readings = [
    ["Apalancamiento", analysis.leverage],
    ["Funding", analysis.funding],
    ["Liquidaciones", analysis.liquidations],
    ["Top traders", analysis.positioning],
    ["Profundidad", analysis.orderbook],
  ];
  $("basic-analysis").innerHTML = readings.map(([label, value]) =>
    `<div class="regime"><span>${label}</span><b>${value || "sin datos"}</b></div>`
  ).join("");
}

function pctClass(value, neutral = 0) {
  if (value == null) return "";
  return Number(value) >= neutral ? "up" : "down";
}

function renderFlow() {
  const basic = state.basic?.indicators || {};
  const candles = basic.price?.candles || [];
  const priceNow = latest(candles)?.close;
  const pricePrev = candles.length > 1 ? candles[candles.length - 2]?.close : null;
  const priceChange = priceNow != null && pricePrev ? (priceNow / pricePrev - 1) * 100 : null;
  const oi = basic.open_interest?.close_usd || [];
  const oiNow = latest(oi), oiPrev = oi.length > 1 ? oi[oi.length - 2] : null;
  const oiChange = oiNow != null && oiPrev ? (oiNow / oiPrev - 1) * 100 : null;
  const taker = latest(basic.taker?.bars);
  const globalLong = latest(basic.global_accounts?.long_pct);
  const topAccounts = latest(basic.top_accounts?.long_pct);
  const topPositions = latest(basic.top_traders?.long_pct);
  const fundingOi = latest(basic.funding?.close_pct);
  const fundingVolume = latest(basic.funding_volume?.close_pct);
  const bookBinance = latest(basic.orderbook?.bid_ask_ratio);
  const bookAll = latest(basic.orderbook_aggregated?.bid_ask_ratio);
  $("flow-metrics").innerHTML =
    metric("Precio 4h", signed(priceChange, "%"), pctClass(priceChange)) +
    metric("OI 4h", signed(oiChange, "%"), pctClass(oiChange)) +
    metric("Taker compra", taker?.buy_ratio == null ? "—" : `${fmt(taker.buy_ratio)}%`, pctClass((taker?.buy_ratio || 50) - 50)) +
    metric("Global long", globalLong == null ? "—" : `${fmt(globalLong)}%`) +
    metric("Top cuentas long", topAccounts == null ? "—" : `${fmt(topAccounts)}%`) +
    metric("Top posiciones long", topPositions == null ? "—" : `${fmt(topPositions)}%`) +
    metric("Funding OI / Vol", fundingOi == null && fundingVolume == null ? "—" : `${signed(fundingOi, "%", 4)} / ${signed(fundingVolume, "%", 4)}`) +
    metric("Book B/A · Bin/agg", `${fmt(bookBinance)} / ${fmt(bookAll)}`);

  const oiData = basic.open_interest_exchanges || {};
  const oiRows = oiData.exchanges || [];
  const totalOi = Number(oiData.total?.oi_usd || oiRows.reduce((sum, row) => sum + Number(row.oi_usd || 0), 0));
  $("oi-exchanges").innerHTML = oiRows.length ? oiRows.map((row) => {
    const share = totalOi ? Number(row.oi_usd || 0) / totalOi * 100 : null;
    return `<tr><td>${escapeHtml(row.exchange)}</td><td>${compactUsd(row.oi_usd)}</td><td>${share == null ? "—" : `${fmt(share)}%`}</td><td class="${pctClass(row.change_4h_pct)}">${signed(row.change_4h_pct, "%")}</td><td class="${pctClass(row.change_24h_pct)}">${signed(row.change_24h_pct, "%")}</td><td>${compactUsd(row.stable_margin_usd)}</td></tr>`;
  }).join("") : `<tr><td colspan="6" class="empty">Sin desglose de OI disponible</td></tr>`;

  const takerRows = basic.taker_exchanges?.exchanges || [];
  $("taker-exchanges").innerHTML = takerRows.length ? takerRows.map((row) => {
    const volume = (Number(row.buy_musd) + Number(row.sell_musd)) * 1e6;
    return `<tr><td>${escapeHtml(row.exchange)}</td><td class="buy">${fmt(row.buy_ratio)}%</td><td class="sell">${fmt(row.sell_ratio)}%</td><td>${compactUsd(volume)}</td></tr>`;
  }).join("") : `<tr><td colspan="4" class="empty">Sin flujo taker por exchange</td></tr>`;

  const liqRows = basic.liquidation_exchanges?.exchanges || [];
  $("liquidation-exchanges").innerHTML = liqRows.length ? liqRows.map((row) => {
    const long = Number(row.long_musd || 0), short = Number(row.short_musd || 0);
    const dominance = long > short * 1.5 ? "longs" : short > long * 1.5 ? "shorts" : "mixto";
    return `<tr><td>${escapeHtml(row.exchange)}</td><td class="down">${fmt(long)}M</td><td class="up">${fmt(short)}M</td><td>${dominance}</td></tr>`;
  }).join("") : `<tr><td colspan="4" class="empty">Sin liquidaciones por exchange</td></tr>`;
}

function message(id, text) {
  const element = $(id);
  element.textContent = text || "";
  element.classList.toggle("visible", Boolean(text));
}

function drawLevelMap() {
  const canvas = $("liquidation-chart");
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const levels = state.advanced?.liquidation_map || [];
  const price = Number(state.advanced?.price);
  if (!levels.length || !Number.isFinite(price)) {
    message("liquidation-message", reason(state.advanced?.capabilities?.liquidation_map));
    return;
  }
  message("liquidation-message", "");
  const visible = levels.filter((row) => Math.abs(row.price / price - 1) <= 0.18);
  const prices = visible.map((row) => row.price).concat(price);
  const min = Math.min(...prices), max = Math.max(...prices);
  const amountMax = Math.max(...visible.map((row) => row.amount_usd), 1);
  const y = (value) => 22 + (max - value) / (max - min || 1) * (height - 48);
  grid(ctx, width, height, 92, 26);
  visible.slice().sort((a, b) => a.price - b.price).forEach((row) => {
    const py = y(row.price);
    const length = Math.max(3, (row.amount_usd / amountMax) * (width - 160));
    ctx.fillStyle = row.price > price ? "rgba(239,99,112,.68)" : "rgba(36,200,138,.68)";
    ctx.fillRect(94, py - 2, length, 4);
  });
  const currentY = y(price);
  ctx.strokeStyle = "#edf1f7";
  ctx.setLineDash([5, 5]);
  ctx.beginPath();
  ctx.moveTo(82, currentY);
  ctx.lineTo(width - 12, currentY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#edf1f7";
  ctx.font = "11px ui-monospace, monospace";
  ctx.fillText(`BTC ${fmt(price, 0)}`, 10, currentY + 4);
  const top = visible.slice().sort((a, b) => b.amount_usd - a.amount_usd).slice(0, 20);
  const labelRows = [];
  for (const row of top) {
    const py = y(row.price);
    if (Math.abs(py - currentY) < 18) continue;
    if (labelRows.every((other) => Math.abs(other - py) >= 15)) labelRows.push(py);
    if (labelRows.length === 6) break;
  }
  top.filter((row) => labelRows.includes(y(row.price))).forEach((row) => {
    ctx.fillStyle = "#b9c1ce";
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillText(`${fmt(row.price, 0)} · ${usd(row.amount_usd)}`, Math.min(width - 175, 102 + (row.amount_usd / amountMax) * (width - 160)), y(row.price) + 4);
  });
}

function drawLiquidationHeatmap() {
  const canvas = $("liquidation-chart");
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const data = state.advanced?.liquidation_heatmap;
  if (!data?.points?.length || !data?.prices?.length) {
    message("liquidation-message", reason(state.advanced?.capabilities?.liquidation_heatmap));
    return;
  }
  message("liquidation-message", "");
  const points = data.points;
  const maxX = Math.max(...points.map((row) => row[0]), 1);
  const maxValue = Math.max(...points.map((row) => row[2]), 1);
  const cellW = Math.max(2, (width - 74) / (maxX + 1));
  const cellH = Math.max(2, (height - 44) / data.prices.length);
  points.forEach(([xIndex, yIndex, value]) => {
    const intensity = Math.min(1, Math.sqrt(value / maxValue));
    ctx.fillStyle = `rgba(232,182,83,${0.12 + intensity * 0.78})`;
    ctx.fillRect(60 + xIndex * cellW, 16 + (data.prices.length - yIndex - 1) * cellH, cellW + 1, cellH + 1);
  });
  const candles = data.candles || [];
  if (candles.length > 1) {
    const prices = data.prices;
    const min = Math.min(...prices), max = Math.max(...prices);
    ctx.strokeStyle = "#edf1f7";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    candles.forEach((row, index) => {
      const x = 60 + index / (candles.length - 1) * (width - 74);
      const y = 16 + (max - row[4]) / (max - min || 1) * (height - 44);
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }
}

function renderLiquidationSummary() {
  const pressure = state.experimental_pressure;
  const price = Number(state.advanced?.price);
  const levels = state.advanced?.liquidation_map || [];
  const above = levels.filter((row) => row.price > price).sort((a, b) => b.amount_usd - a.amount_usd)[0];
  const below = levels.filter((row) => row.price < price).sort((a, b) => b.amount_usd - a.amount_usd)[0];
  $("liq-above").textContent = usd(pressure?.liquidation_usd?.above);
  $("liq-below").textContent = usd(pressure?.liquidation_usd?.below);
  $("level-above").textContent = above ? `${fmt(above.price, 0)} · ${usd(above.amount_usd)}` : "—";
  $("level-below").textContent = below ? `${fmt(below.price, 0)} · ${usd(below.amount_usd)}` : "—";
}

function renderLiquidations() {
  if (liquidationMode === "levels") drawLevelMap(); else drawLiquidationHeatmap();
  renderLiquidationSummary();
}

function drawOrderbook() {
  const canvas = $("orderbook-chart");
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const apiSnapshots = state.advanced?.orderbook_heatmap || [];
  const visualSnapshots = state.visual_orderbook_history || [];
  const snapshots = apiSnapshots.length ? apiSnapshots : visualSnapshots;
  if (!snapshots.length) {
    message("orderbook-message", state.visual_snapshot?.whale_orders?.rows?.length
      ? "La historia visual comienza con la próxima captura automática"
      : reason(state.advanced?.capabilities?.orderbook_heatmap));
    return;
  }
  message("orderbook-message", "");
  const price = Number(state.visual_indicator?.price || state.advanced?.price);
  const all = snapshots.flatMap((row) => row.bids.concat(row.asks))
    .filter((row) => !price || Math.abs(row[0] / price - 1) <= 0.12);
  const prices = all.map((row) => row[0]);
  const quantities = all.map((row) => row[1]);
  const min = Math.min(...prices), max = Math.max(...prices), qMax = Math.max(...quantities, 1);
  const xStep = (width - 74) / Math.max(1, snapshots.length);
  snapshots.forEach((snapshot, index) => {
    for (const [side, color] of [["bids", "36,200,138"], ["asks", "239,99,112"]]) {
      snapshot[side].forEach(([levelPrice, quantity]) => {
        if (levelPrice < min || levelPrice > max) return;
        const y = 16 + (max - levelPrice) / (max - min || 1) * (height - 44);
        const alpha = Math.min(.9, .08 + Math.sqrt(quantity / qMax) * .82);
        ctx.fillStyle = `rgba(${color},${alpha})`;
        ctx.fillRect(60 + index * xStep, y - 2, Math.max(2, xStep + 1), 4);
      });
    }
  });
  if (Number.isFinite(price)) {
    const y = 16 + (max - price) / (max - min || 1) * (height - 44);
    ctx.strokeStyle = "#edf1f7";
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(56, y);
    ctx.lineTo(width - 12, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#edf1f7";
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillText(fmt(price, 0), 9, y + 3);
  }
}

function renderLargeOrders() {
  const apiRows = state.advanced?.large_orders || [];
  const visualRows = state.visual_snapshot?.whale_orders?.rows || [];
  const rows = apiRows.length ? apiRows : visualRows.map((row) => ({
    ...row,
    side: row.side === "bid" ? "buy" : "sell",
    usd: row.amount_usd,
  }));
  const price = Number(state.visual_indicator?.price || state.advanced?.price);
  $("large-orders").innerHTML = rows.length ? rows.slice(0, 30).map((row) => {
    const distance = Number.isFinite(price) ? (row.price / price - 1) * 100 : null;
    const age = row.duration || (row.started_at ? new Date(row.started_at).toLocaleString("es-CL") : "—");
    const exchange = row.exchange && row.exchange !== "unknown" ? ` · ${escapeHtml(row.exchange)}` : "";
    return `<tr><td class="${row.side}">${row.side === "buy" ? "COMPRA" : "VENTA"}${exchange}</td><td>${fmt(row.price, 1)}</td><td>${signed(distance, "%")}</td><td>${usd(row.usd)}</td><td>${escapeHtml(age)}</td></tr>`;
  }).join("") : `<tr><td colspan="5" class="empty">${reason(state.advanced?.capabilities?.large_orders)}</td></tr>`;
}

function renderOrderbook() {
  const interval = state.advanced?.capabilities?.orderbook_heatmap?.interval;
  const visualHistory = state.visual_orderbook_history || [];
  $("book-interval").textContent = interval
    ? `48 snapshots · intervalos de ${interval}`
    : visualHistory.length
      ? `${visualHistory.length} capturas visuales · cada 5 min · historial forward`
      : "Recolectando historial visual cada 5 min";
  drawOrderbook();
  renderLargeOrders();
}

function visualLevelRows() {
  return state.visual_snapshot?.liquidation_heatmap?.levels || [];
}

function drawVisualLevels() {
  const canvas = $("visual-level-chart");
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const visual = state.visual_indicator;
  const price = Number(visual?.price);
  const rows = visualLevelRows().filter((row) =>
    Number(row.intensity_usd) >= 5e6 && Math.abs(Number(row.price) / price - 1) <= 0.06
  );
  if (!Number.isFinite(price) || !rows.length) {
    message("visual-level-message", state.visual_error || "Esperando mapa visual autorizado");
    return;
  }
  message("visual-level-message", "");
  const prices = rows.map((row) => Number(row.price)).concat(price);
  const min = Math.min(...prices), max = Math.max(...prices);
  const strongest = Math.max(...rows.map((row) => Number(row.intensity_usd)), 1);
  const y = (value) => 24 + (max - value) / (max - min || 1) * (height - 48);
  grid(ctx, width, height, 102, 24);
  rows.slice().sort((a, b) => Number(a.price) - Number(b.price)).forEach((row) => {
    const rowPrice = Number(row.price);
    const amount = Number(row.intensity_usd);
    const py = y(rowPrice);
    const barWidth = Math.max(5, amount / strongest * (width - 240));
    ctx.fillStyle = rowPrice > price ? "rgba(239,99,112,.74)" : "rgba(36,200,138,.74)";
    ctx.fillRect(104, py - 4, barWidth, 8);
    if (amount / strongest >= 0.55) {
      ctx.fillStyle = "#b9c1ce";
      ctx.font = "10px ui-monospace, monospace";
      ctx.fillText(
        `${fmt(rowPrice, 0)} · ${compactUsd(amount)}`,
        Math.min(width - 170, 112 + barWidth),
        py + 4,
      );
    }
  });
  const currentY = y(price);
  ctx.strokeStyle = "#edf1f7";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([5, 4]);
  ctx.beginPath();
  ctx.moveTo(92, currentY);
  ctx.lineTo(width - 12, currentY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#edf1f7";
  ctx.font = "11px ui-monospace, monospace";
  ctx.fillText(`BTC ${fmt(price, 0)}`, 10, currentY + 4);
}

function levelText(level) {
  return level ? `${fmt(level.price, 0)} USDT` : "—";
}

function levelMeta(level) {
  return level ? `${signed(level.distance_pct, "%", 2)} · ${compactUsd(level.intensity_usd)}` : "—";
}

function renderVisual() {
  const visual = state.visual_indicator;
  const snapshot = state.visual_snapshot;
  const fresh = $("visual-freshness");
  if (!visual || !snapshot) {
    fresh.querySelector("b").textContent = "—";
    fresh.querySelector("span").textContent = "sin captura";
    $("visual-warning").textContent = state.visual_error || "Esperando la primera captura del colector dedicado.";
    drawVisualLevels();
    return;
  }
  const score = Number(visual.score);
  $("visual-score").textContent = Number.isFinite(score) ? signed(score, "", 1) : "—";
  $("visual-score").className = Number.isFinite(score) ? score >= 18 ? "up" : score <= -18 ? "down" : "" : "";
  $("visual-label").textContent = visual.label || "No validado";
  const levels = visual.levels || {};
  $("visual-nearest-up").textContent = levelText(levels.nearest_above);
  $("visual-nearest-up-meta").textContent = levelMeta(levels.nearest_above);
  $("visual-nearest-down").textContent = levelText(levels.nearest_below);
  $("visual-nearest-down-meta").textContent = levelMeta(levels.nearest_below);
  $("visual-depth").textContent = compactUsd(visual.depth?.latest_delta_usd);
  $("visual-depth").className = pctClass(visual.depth?.latest_delta_usd);
  $("visual-depth-meta").textContent = visual.depth?.decelerating ? "positivo, desacelerando" :
    visual.depth?.slope_usd == null ? "sin pendiente" :
    `pendiente ${signed(visual.depth.slope_usd / 1e6, "M", 2)}`;
  fresh.querySelector("b").textContent = `${fmt(visual.age_seconds, 0)} s`;
  fresh.querySelector("span").textContent = visual.age_seconds <= 600 ? "captura vigente" : "captura antigua";
  $("visual-warning").textContent = visual.warning;
  const c = visual.components || {};
  $("visual-components").innerHTML =
    component("Heatmap: atracción", c.heatmap_attraction) +
    component("Mapa: atracción", c.map_attraction) +
    component("Delta del libro", c.depth_delta) +
    component("Muros ballena", c.whale_bid_pressure) +
    // El consenso conserva el signo: dos componentes de acuerdo bajista deben
    // leerse negativos (antes Math.abs los pintaba en verde con +).
    component("Consenso", (c.heatmap_attraction != null && c.map_attraction != null)
      ? (Math.sign(c.heatmap_attraction) === Math.sign(c.map_attraction) ? (c.heatmap_attraction + c.map_attraction) / 2 : 0)
      : null);
  const coverage = visual.coverage || {};
  $("visual-source").textContent = `Captura ${new Date(snapshot.captured_at).toLocaleString("es-CL")} · tooltip scan`;
  $("visual-coverage").innerHTML = [
    ["Mapa acumulado", coverage.map_levels, snapshot.liquidation_map?.range],
    ["Heatmap Model 2", coverage.heatmap_levels, snapshot.liquidation_heatmap?.range],
    ["Delta order book", coverage.depth_points, `${snapshot.depth_delta?.interval} · ±${snapshot.depth_delta?.range_pct}%`],
    ["Órdenes ballena activas", coverage.whale_orders, snapshot.whale_orders?.range],
  ].map(([layer, count, range]) =>
    `<tr><td>${escapeHtml(layer)}</td><td>${fmt(count, 0)}</td><td>${escapeHtml(range)}</td><td>Tooltips ECharts</td><td>Research · sin órdenes</td></tr>`
  ).join("");
  const shadow = state.visual_shadow || {};
  const metrics = shadow.metrics || {};
  $("shadow-decisions").textContent = fmt(shadow.decisions, 0);
  $("shadow-trades").textContent = fmt(shadow.closed_trades, 0);
  $("shadow-open").textContent = shadow.open_trade
    ? `${shadow.open_trade.direction} virtual desde ${fmt(shadow.open_trade.entry, 0)}`
    : "sin posición virtual";
  $("shadow-wr").textContent = metrics.win_rate_pct == null ? "—" : `${fmt(metrics.win_rate_pct, 1)}%`;
  $("shadow-result").textContent = metrics.total_net_pct == null ? "—" : signed(metrics.total_net_pct, "%", 2);
  $("shadow-result").className = pctClass(metrics.total_net_pct);
  $("shadow-dd").textContent = metrics.max_drawdown_pct == null ? "—" : `DD ${fmt(metrics.max_drawdown_pct, 2)}%`;
  $("shadow-warning").textContent = shadow.warning || "Esperando datos forward";
  drawVisualLevels();
}

function component(label, value) {
  if (value == null) return `<article><span>${label}</span><b>—</b></article>`;
  const number = Number(value) * 100;
  return `<article><span>${label}</span><b class="${number >= 0 ? "up" : "down"}">${signed(number, "", 1)}</b></article>`;
}

function renderModel() {
  const apiModel = state.experimental_pressure || {};
  const visual = state.visual_indicator || {};
  const hasVisual = visual.score != null;
  const model = hasVisual ? visual : apiModel;
  const score = model.score == null ? null : Number(model.score);
  const scoreBox = $("pressure-score");
  scoreBox.querySelector("b").textContent = Number.isFinite(score) ? signed(score, "", 1) : "—";
  scoreBox.querySelector("b").className = Number.isFinite(score) ? score >= 18 ? "up" : score <= -18 ? "down" : "" : "";
  scoreBox.querySelector("span").textContent = model.label || "sin datos";
  const visualForward = Number(state.visual_shadow?.decisions || 0);
  const apiForward = Number(apiModel.forward_observations || 0);
  const observations = hasVisual ? visualForward : Number(apiModel.observations || 0);
  const minimum = hasVisual ? 2016 : Number(apiModel.minimum_for_calibration || 100);
  $("calibration-label").textContent = hasVisual
    ? `${visualForward} capturas visuales forward · ${apiForward} API forward`
    : `${Number(apiModel.historical_observations || 0)} históricas · ${apiForward} forward`;
  $("calibration-progress").max = minimum;
  $("calibration-progress").value = Math.min(observations, minimum);
  const visualComponents = visual.components || {};
  const apiComponents = apiModel.components || {};
  $("model-components").innerHTML = hasVisual
    ? component("Heatmap: atracción", visualComponents.heatmap_attraction) +
      component("Mapa: atracción", visualComponents.map_attraction) +
      component("Delta del libro", visualComponents.depth_delta) +
      component("Muros ballena · observación", visualComponents.whale_bid_pressure) +
      component("Posicionamiento contrarian", apiComponents.positioning_contrarian) +
      component("Funding contrarian", apiComponents.funding_contrarian)
    : component("Atracción liquidaciones", apiComponents.liquidation_attraction) +
      component("Imbalance order book", apiComponents.orderbook_imbalance) +
      component("Posicionamiento contrarian", apiComponents.positioning_contrarian) +
      component("Funding contrarian", apiComponents.funding_contrarian);
  $("radar-method").textContent = hasVisual
    ? "50% heatmap · 30% mapa · 20% delta del libro (renormalizado por componente disponible). Muros ballena, posicionamiento y funding se muestran en paralelo y NO entran al puntaje."
    : "45% atracción de liquidaciones · 35% imbalance bid/ask · 10% posicionamiento contrarian · 10% funding contrarian.";
  // Frescura: el Radar aceptaba capturas de hasta 30 min como vigentes y, al
  // vencerlas, cambiaba al modelo API sin avisar. Ahora ambos casos se dicen.
  const edad = Number(visual.age_seconds);
  const lag = Number(visual.coverage?.heatmap_lag_seconds);
  const avisos = [];
  if (hasVisual) {
    if (Number.isFinite(edad)) avisos.push(`captura de hace ${Math.round(edad / 60)} min`);
    if (Number.isFinite(lag) && lag > 900) avisos.push(`heatmap atrasado ${Math.round(lag / 60)} min respecto de la captura`);
  } else {
    avisos.push("sin captura visual vigente: se muestra el modelo API, que es OTRA fórmula");
  }
  const muestra = hasVisual
    ? "Las capturas van cada 5 min y están autocorrelacionadas: a 4h y 12h las ventanas no solapadas son ~42 y ~14 por semana, no 2.016."
    : "La fórmula queda fija mientras recolectamos.";
  $("radar-validation").textContent =
    `${avisos.length ? avisos.join(" · ") + ". " : ""}${muestra} Research only: no habilita órdenes.`;
}

function render(data) {
  state = data;
  if (data.waiting) {
    $("updated").textContent = "Esperando primera captura del VPS";
    return;
  }
  $("price").textContent = data.advanced?.price ? `${fmt(data.advanced.price, 1)} USDT` : "BTCUSDT";
  $("updated").textContent = `Actualizado hace ${fmt(data.age_seconds, 0)} s`;
  const capabilities = data.advanced?.capabilities || {};
  const hasLiquidations = capabilities.liquidation_map?.available || capabilities.liquidation_heatmap?.available;
  const hasOrderbook = capabilities.orderbook_heatmap?.available ||
    capabilities.large_orders?.available ||
    Boolean(data.visual_snapshot?.whale_orders?.rows?.length);
  document.querySelector('[data-tab="liquidations"]').classList.toggle("hidden", !hasLiquidations);
  document.querySelector('[data-tab="orderbook"]').classList.toggle("hidden", !hasOrderbook);
  renderOverview();
  renderFlow();
  renderLiquidations();
  renderOrderbook();
  renderVisual();
  renderModel();
}

function activateTab(button) {
  if (!button) return;
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${button.dataset.tab}`));
    requestAnimationFrame(() => {
      if (!state) return;
      if (button.dataset.tab === "overview") renderOverview();
      if (button.dataset.tab === "flow") renderFlow();
      if (button.dataset.tab === "liquidations") renderLiquidations();
      if (button.dataset.tab === "orderbook") renderOrderbook();
      if (button.dataset.tab === "visual") renderVisual();
    });
}

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    activateTab(button);
    history.replaceState(null, "", `#${button.dataset.tab}`);
  });
});

document.querySelectorAll("[data-liq-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    liquidationMode = button.dataset.liqMode;
    document.querySelectorAll("[data-liq-mode]").forEach((item) => item.classList.toggle("active", item === button));
    renderLiquidations();
  });
});

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => state && render(state), 120);
});

fetch("api/state").then((response) => response.json()).then(render).catch(() => {
  $("updated").textContent = "No se pudo cargar el snapshot";
});

const initialTab = document.querySelector(`[data-tab="${location.hash.slice(1)}"]`);
if (initialTab) activateTab(initialTab);
