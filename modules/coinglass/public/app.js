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
  const text = capability?.reason || "No disponible";
  if (/plan|upgrade|permission|professional|403/i.test(text)) return "No incluido en el plan API";
  return text.length > 90 ? `${text.slice(0, 87)}...` : text;
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
  const snapshots = state.advanced?.orderbook_heatmap || [];
  if (!snapshots.length) {
    message("orderbook-message", reason(state.advanced?.capabilities?.orderbook_heatmap));
    return;
  }
  message("orderbook-message", "");
  const price = Number(state.advanced?.price);
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
  const rows = state.advanced?.large_orders || [];
  const price = Number(state.advanced?.price);
  $("large-orders").innerHTML = rows.length ? rows.slice(0, 30).map((row) => {
    const distance = Number.isFinite(price) ? (row.price / price - 1) * 100 : null;
    return `<tr><td class="${row.side}">${row.side === "buy" ? "COMPRA" : "VENTA"}</td><td>${fmt(row.price, 1)}</td><td>${signed(distance, "%")}</td><td>${usd(row.usd)}</td><td>${row.started_at ? new Date(row.started_at).toLocaleString("es-CL") : "—"}</td></tr>`;
  }).join("") : `<tr><td colspan="5" class="empty">${reason(state.advanced?.capabilities?.large_orders)}</td></tr>`;
}

function renderOrderbook() {
  const interval = state.advanced?.capabilities?.orderbook_heatmap?.interval;
  $("book-interval").textContent = interval
    ? `48 snapshots · intervalos de ${interval}`
    : "Intervalo no disponible en el plan";
  drawOrderbook();
  renderLargeOrders();
}

function component(label, value) {
  if (value == null) return `<article><span>${label}</span><b>—</b></article>`;
  const number = Number(value) * 100;
  return `<article><span>${label}</span><b class="${number >= 0 ? "up" : "down"}">${signed(number, "", 1)}</b></article>`;
}

function renderModel() {
  const model = state.experimental_pressure || {};
  const score = model.score == null ? null : Number(model.score);
  const scoreBox = $("pressure-score");
  scoreBox.querySelector("b").textContent = Number.isFinite(score) ? signed(score, "", 1) : "—";
  scoreBox.querySelector("b").className = Number.isFinite(score) ? score >= 15 ? "up" : score <= -15 ? "down" : "" : "";
  scoreBox.querySelector("span").textContent = model.label || "sin datos";
  const observations = Number(model.observations || 0);
  const minimum = Number(model.minimum_for_calibration || 100);
  $("calibration-label").textContent = `${observations} / ${minimum} observaciones`;
  $("calibration-progress").max = minimum;
  $("calibration-progress").value = Math.min(observations, minimum);
  const c = model.components || {};
  $("model-components").innerHTML =
    component("Atracción liquidaciones", c.liquidation_attraction) +
    component("Imbalance order book", c.orderbook_imbalance) +
    component("Posicionamiento contrarian", c.positioning_contrarian) +
    component("Funding contrarian", c.funding_contrarian);
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
  const hasOrderbook = capabilities.orderbook_heatmap?.available || capabilities.large_orders?.available;
  document.querySelector('[data-tab="liquidations"]').classList.toggle("hidden", !hasLiquidations);
  document.querySelector('[data-tab="orderbook"]').classList.toggle("hidden", !hasOrderbook);
  renderOverview();
  renderLiquidations();
  renderOrderbook();
  renderModel();
}

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((item) => item.classList.toggle("active", item === button));
    document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${button.dataset.tab}`));
    requestAnimationFrame(() => {
      if (button.dataset.tab === "overview") renderOverview();
      if (button.dataset.tab === "liquidations") renderLiquidations();
      if (button.dataset.tab === "orderbook") renderOrderbook();
    });
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
