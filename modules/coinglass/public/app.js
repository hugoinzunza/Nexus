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
  renderLecturas(liq);
}

// Dos lecturas, en formato grafico. Se dejaron solo estas porque son las unicas
// que dicen algo que el grafico de precio no muestra; las otras tres eran
// redundantes o no accionables.
const CUADRANTES = [
  ["Precio sube · OI sube", "nuevos longs", "up"],
  ["Precio sube · OI baja", "cierre de shorts", "up"],
  ["Precio baja · OI sube", "nuevos shorts", "down"],
  ["Precio baja · OI baja", "salida de longs", "down"],
];

function renderLecturas(liq) {
  const analysis = state.basic_analysis || {};

  // --- Mecanismo: cuadrante 2x2 con la celda vigente encendida ---
  const lectura = String(analysis.leverage || "");
  const activo = CUADRANTES.findIndex(([, etiqueta]) => lectura.includes(etiqueta));
  $("lev-titulo").textContent = lectura || "sin datos";
  $("lev-titulo").className = activo < 0 ? "" : CUADRANTES[activo][2];
  $("lev-cuadrantes").innerHTML = CUADRANTES.map(([eje, etiqueta, clase], i) =>
    `<div class="cuadrante${i === activo ? " on " + clase : ""}">` +
    `<span>${escapeHtml(eje)}</span><b>${escapeHtml(etiqueta)}</b></div>`
  ).join("");

  // --- Liquidaciones: barra proporcional long vs short ---
  const largos = Number(liq?.long_musd) || 0;
  const cortos = Number(liq?.short_musd) || 0;
  const total = largos + cortos;
  $("liq-titulo").textContent = analysis.liquidations || "sin datos";
  $("liq-titulo").className = total === 0 ? ""
    : largos > cortos * 2 ? "down" : cortos > largos * 2 ? "up" : "";
  if (!total) {
    $("liq-barra").innerHTML = `<p class="empty">Sin liquidaciones en la última barra.</p>`;
    return;
  }
  const pctL = Math.round(100 * largos / total);
  $("liq-barra").innerHTML =
    `<div class="liq-track">` +
    `<div class="liq-long" style="width:${pctL}%"></div>` +
    `<div class="liq-short" style="width:${100 - pctL}%"></div></div>` +
    `<div class="liq-pies">` +
    `<span class="down"><b>${fmt(largos)}M</b> longs barridos · ${pctL}%</span>` +
    `<span class="up">${100 - pctL}% · <b>${fmt(cortos)}M</b> shorts barridos</span>` +
    `</div>`;
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

// Ventana vertical del grafico del libro, en % alrededor del precio de AHORA.
// 0 = todo el rango. La captura de Hugo mostro el problema: sin acotar, dos muros
// lejanos aplastan la accion del precio y el "ahora" queda ilegible.
let bookZoom = 1.5;

// Flujo de muros: compara cada captura con la anterior. Un muro que desaparece
// PUEDE haber sido consumido (el precio paso por ahi) o retirado (no llego nunca),
// y esa segunda es la firma del spoofing. Es una inferencia: entre capturas hay
// 5 min y solo se conoce el precio de cada punta.
function flujoDeMuros(snapshots, referencia) {
  // Tolerancia de 0,05% del precio: un muro que se corre unos dolares es EL MISMO
  // muro. Dos errores ya cometidos aca:
  //  1) clave al dolar exacto -> todo salia nuevo + retirado (377 y 377);
  //  2) dividir por (precio * TOL) -> eso es 1/TOL, constante, asi que TODOS los
  //     muros caian en el mismo bucket y nunca habia eventos (0, 0, 0).
  // El paso tiene que venir de una referencia fija, no del precio de cada muro.
  const paso = Math.max(1, (referencia || 1) * 0.0005);
  const clave = (lado, precio) => `${lado}:${Math.round(precio / paso)}`;
  // Dos muros distintos pueden caer en el mismo bucket. Con `Map.set` el segundo
  // pisaba al primero: su monto desaparecia del diff y, si uno de los dos se
  // retiraba, el bucket seguia ocupado y no se generaba evento. Se ACUMULA.
  const indexar = (snap) => {
    const mapa = new Map();
    for (const [lado, campo] of [["bid", "bids"], ["ask", "asks"]]) {
      for (const [p, usd] of snap[campo] || []) {
        const k = clave(lado, p);
        const previo = mapa.get(k);
        if (previo) { previo.usd += usd; } else { mapa.set(k, { p, usd, lado }); }
      }
    }
    return mapa;
  };
  const eventos = [];
  let nuevos = 0, consumidos = 0, retirados = 0;
  for (let i = 1; i < snapshots.length; i++) {
    const antes = indexar(snapshots[i - 1]), ahora = indexar(snapshots[i]);
    const pa = Number(snapshots[i - 1].price), pb = Number(snapshots[i].price);
    const lo = Math.min(pa, pb), hi = Math.max(pa, pb);
    for (const [k, m] of ahora) {
      if (!antes.has(k)) { eventos.push({ i, ...m, tipo: "nuevo" }); nuevos++; }
    }
    for (const [k, m] of antes) {
      if (ahora.has(k)) continue;
      // el precio recorrio ese nivel entre las dos capturas -> se lo comieron
      const tocado = m.p >= lo && m.p <= hi;
      eventos.push({ i, ...m, tipo: tocado ? "consumido" : "retirado" });
      tocado ? consumidos++ : retirados++;
    }
  }
  return { eventos, nuevos, consumidos, retirados };
}

// El pie decia "cada 5 min" cableado. Es el mismo defecto que ya corregimos en la
// pestana Flujo (el "4h" fijo que resultaba ser 1h): si el timer cambia o hay
// huecos, miente. Se mide con la MEDIANA de los saltos, que ignora los huecos.
function intervaloMedido(snapshots) {
  const ts = snapshots.map((s) => Date.parse(s.captured_at)).filter(Number.isFinite);
  const saltos = [];
  for (let i = 1; i < ts.length; i++) if (ts[i] > ts[i - 1]) saltos.push(ts[i] - ts[i - 1]);
  if (!saltos.length) return "intervalo desconocido";
  saltos.sort((a, b) => a - b);
  const minutos = Math.round(saltos[Math.floor(saltos.length / 2)] / 60000);
  const huecos = saltos.filter((s) => s > saltos[Math.floor(saltos.length / 2)] * 2.5).length;
  return `cada ~${minutos} min` + (huecos ? ` · ${huecos} hueco${huecos > 1 ? "s" : ""}` : "");
}

function drawOrderbook() {
  const canvas = $("orderbook-chart");
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  // Solo el historial VISUAL: el heatmap de profundidad de la API quedo muerto
  // (401 "Upgrade plan"). Antes se mezclaban los dos datasets bajo el mismo
  // titulo —profundidad completa vs muros discretos— sin decir cual se veia.
  const snapshots = state.visual_orderbook_history || [];
  if (snapshots.length < 2) {
    message("orderbook-message", snapshots.length
      ? "Con una sola captura no hay historia: la serie parte con la proxima"
      : "Recolectando historial visual cada 5 min");
    return;
  }
  message("orderbook-message", "");

  const L = 68, R = 128, T = 20, B = 30;
  const muros = snapshots.flatMap((snap, i) => [
    ...(snap.bids || []).map(([p, usd]) => ({ i, p, usd, lado: "bid" })),
    ...(snap.asks || []).map(([p, usd]) => ({ i, p, usd, lado: "ask" })),
  ]).filter((m) => Number.isFinite(m.p) && Number.isFinite(m.usd));
  const precios = snapshots.map((s) => Number(s.price)).filter(Number.isFinite);
  if (!muros.length || !precios.length) {
    message("orderbook-message", "Las capturas no traen muros legibles");
    return;
  }

  // --- ventana vertical: centrada en el precio de AHORA cuando hay zoom ---
  const ahora = precios[precios.length - 1];
  let min, max;
  if (bookZoom > 0) {
    min = ahora * (1 - bookZoom / 100);
    max = ahora * (1 + bookZoom / 100);
    // el recorrido del precio nunca queda fuera del marco
    min = Math.min(min, Math.min(...precios));
    max = Math.max(max, Math.max(...precios));
  } else {
    const pmin = Math.min(...precios), pmax = Math.max(...precios);
    const centro = (pmin + pmax) / 2;
    const radio = Math.max((pmax - pmin) / 2 * 1.6, centro * 0.02);
    min = centro - radio; max = centro + radio;
    const cerca = muros.filter((m) => m.p >= min && m.p <= max);
    if (cerca.length) {
      min = Math.min(min, Math.min(...cerca.map((m) => m.p)));
      max = Math.max(max, Math.max(...cerca.map((m) => m.p)));
    }
  }
  const pad = (max - min) * 0.04 || 1;
  min -= pad; max += pad;
  const maxUsd = Math.max(...muros.map((m) => m.usd), 1);
  const X = (i) => L + i * (width - L - R) / Math.max(1, snapshots.length - 1);
  const Y = (p) => T + (max - p) / (max - min || 1) * (height - T - B);

  // --- eje Y: precios reales, no solo la linea del precio actual ---
  ctx.font = "10px ui-monospace, monospace";
  ctx.textBaseline = "middle";
  for (let k = 0; k <= 5; k++) {
    const p = min + (max - min) * k / 5;
    const y = Y(p);
    ctx.strokeStyle = "#1e2532";
    ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(width - R, y); ctx.stroke();
    ctx.fillStyle = "#7d879a";
    ctx.textAlign = "right";
    ctx.fillText(fmt(p, 0), L - 8, y);
  }

  // --- muros: cada captura una columna; area proporcional al monto ---
  const ancho = Math.max(2, (width - L - R) / snapshots.length * 0.9);
  for (const m of muros) {
    if (m.p < min || m.p > max) continue;      // fuera del encuadre
    const rel = Math.sqrt(m.usd / maxUsd);
    ctx.fillStyle = m.lado === "bid"
      ? `rgba(36,200,138,${(0.12 + rel * 0.5).toFixed(3)})`
      : `rgba(239,99,112,${(0.12 + rel * 0.5).toFixed(3)})`;
    const alto = Math.max(3, rel * 11);
    ctx.fillRect(X(m.i) - ancho / 2, Y(m.p) - alto / 2, ancho, alto);
  }

  // --- FLUJO: que muros nacen, se comen o se retiran ---
  const flujo = flujoDeMuros(snapshots, ahora);
  // Se toman los N eventos MAS GRANDES del encuadre, sin umbral absoluto.
  //
  // Antes el corte era `maxUsd * 0.55` y eso lo hacia invisible en produccion:
  // el bid persistente de ~78M fija el maximo, el corte queda en ~43M y la
  // MEDIANA de muro es 1,8M, asi que 1 de 41 muros podia marcar. El fixture no
  // lo mostraba porque ahi no habia una ballena gigante fijando la vara. Un
  // ranking relativo no depende de la escala del muro mas grande.
  const marcables = flujo.eventos
    .filter((e) => e.p >= min && e.p <= max)
    .sort((a, b) => b.usd - a.usd)
    .slice(0, 40);
  for (const e of marcables) {
    const x = X(e.i), y = Y(e.p);
    ctx.lineWidth = 1.6;
    if (e.tipo === "nuevo") {
      ctx.strokeStyle = "#43bdd7";
      ctx.beginPath();
      ctx.moveTo(x, y - 4); ctx.lineTo(x + 4, y); ctx.lineTo(x, y + 4); ctx.lineTo(x - 4, y);
      ctx.closePath(); ctx.stroke();
    } else if (e.tipo === "consumido") {
      ctx.strokeStyle = "#24c88a";
      ctx.beginPath();
      ctx.moveTo(x - 4, y - 4); ctx.lineTo(x + 4, y + 4);
      ctx.moveTo(x + 4, y - 4); ctx.lineTo(x - 4, y + 4);
      ctx.stroke();
    } else {
      ctx.strokeStyle = "#e8b653";
      ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.stroke();
    }
  }

  // --- linea de PRECIO sobre el tiempo, con presencia ---
  ctx.strokeStyle = "rgba(9,11,16,.85)";
  ctx.lineWidth = 5;
  ctx.beginPath();
  snapshots.forEach((snap, i) => {
    const p = Number(snap.price);
    if (!Number.isFinite(p)) return;
    i === 0 ? ctx.moveTo(X(i), Y(p)) : ctx.lineTo(X(i), Y(p));
  });
  ctx.stroke();                                 // contorno para separarla del fondo
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  snapshots.forEach((snap, i) => {
    const p = Number(snap.price);
    if (!Number.isFinite(p)) return;
    i === 0 ? ctx.moveTo(X(i), Y(p)) : ctx.lineTo(X(i), Y(p));
  });
  ctx.stroke();
  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.arc(X(snapshots.length - 1), Y(ahora), 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.font = "700 11px ui-monospace, monospace";
  ctx.textAlign = "right";
  ctx.fillText(`${fmt(ahora, 0)} ahora`, width - R - 10, Y(ahora) - 12);

  // --- los muros MAS GRANDES quedan etiquetados, no solo sombreados ---
  // Dedup con Set, O(n). Antes era `findIndex` dentro de `filter`: con 288
  // capturas x ~40 muros son ~11.500 elementos y ~130M comparaciones EN CADA
  // redraw (zoom, resize). En movil eso congela la pestana.
  const vistos = new Set();
  const pasoDedup = Math.max(1, ahora * 0.001);
  const top = [...muros].filter((m) => m.p >= min && m.p <= max)
    .sort((a, b) => b.usd - a.usd)
    .filter((m) => {
      const k = `${m.lado}:${Math.round(m.p / pasoDedup)}`;
      if (vistos.has(k)) return false;
      vistos.add(k);
      return true;
    });
  ctx.font = "10px ui-monospace, monospace";
  ctx.textAlign = "left";
  const usadasY = [];
  for (const m of top) {
    const y = Y(m.p);
    // separacion en pixeles: sin esto las etiquetas se apilaban ilegibles
    if (usadasY.some((otra) => Math.abs(y - otra) < 24)) continue;
    if (usadasY.length >= 4) break;
    usadasY.push(y);
    ctx.strokeStyle = m.lado === "bid" ? "rgba(36,200,138,.55)" : "rgba(239,99,112,.55)";
    ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(width - R + 4, y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = m.lado === "bid" ? "#24c88a" : "#ef6370";
    ctx.fillText(`${compactUsd(m.usd)} ${m.lado === "bid" ? "compra" : "venta"}`,
                 width - R + 8, y);
    ctx.fillStyle = "#7d879a";
    ctx.fillText(fmt(m.p, 0), width - R + 8, y + 11);
  }

  // --- eje X: tiempo real de la primera y ultima captura ---
  const hora = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "" :
      d.toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });
  };
  ctx.fillStyle = "#7d879a";
  ctx.textAlign = "left";
  ctx.fillText(hora(snapshots[0].captured_at), L, height - 12);
  ctx.textAlign = "center";
  ctx.fillText(hora(snapshots[Math.floor(snapshots.length / 2)].captured_at),
               (L + width - R) / 2, height - 12);
  ctx.textAlign = "right";
  ctx.fillText(hora(snapshots[snapshots.length - 1].captured_at), width - R, height - 12);

  // resumen del flujo: la tasa de retirados es el dato de spoofing
  const salieron = flujo.consumidos + flujo.retirados;
  $("book-interval").textContent =
    `${snapshots.length} capturas · ${intervaloMedido(snapshots)} · flujo: ${flujo.nuevos} nuevos, ` +
    `${flujo.consumidos} consumidos, ${flujo.retirados} retirados` +
    (salieron ? ` (${Math.round(100 * flujo.retirados / salieron)}% de los que ` +
                `desaparecieron se retiraron sin que el precio llegara)` : "");
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
  // el resumen del pie lo escribe drawOrderbook con el conteo del flujo de muros
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

  const L = 78, R = 232, T = 22, B = 26;
  const niveles = visual.levels || {};
  // Muros del LIBRO en el mismo eje de precio: la confluencia entre un clUster de
  // liquidacion y una pared real de ordenes es la informacion que faltaba.
  const muros = [niveles.nearest_whale_ask, niveles.strongest_whale_ask,
                 niveles.nearest_whale_bid, niveles.strongest_whale_bid]
    .filter((m) => m && Number.isFinite(Number(m.price)))
    .filter((m, i, arr) => arr.findIndex((o) =>
      Math.round(Number(o.price)) === Math.round(Number(m.price))) === i);

  const todos = rows.map((r) => Number(r.price)).concat(price)
    .concat(muros.map((m) => Number(m.price)));
  let min = Math.min(...todos), max = Math.max(...todos);
  const pad = (max - min) * 0.05 || 1;
  min -= pad; max += pad;
  const fuerte = Math.max(...rows.map((r) => Number(r.intensity_usd)), 1);
  const Y = (v) => T + (max - v) / (max - min || 1) * (height - T - B);

  // --- eje Y con precios, no solo el precio actual ---
  ctx.font = "10px ui-monospace, monospace";
  ctx.textBaseline = "middle";
  for (let k = 0; k <= 5; k++) {
    const p = min + (max - min) * k / 5;
    const y = Y(p);
    ctx.strokeStyle = "#1e2532";
    ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(width - R, y); ctx.stroke();
    ctx.fillStyle = "#7d879a";
    ctx.textAlign = "right";
    ctx.fillText(fmt(p, 0), L - 8, y);
  }

  // --- barras de intensidad de liquidacion ---
  const masFuerte = rows.reduce((a, b) =>
    Number(b.intensity_usd) > Number(a.intensity_usd) ? b : a, rows[0]);
  ctx.textAlign = "left";
  for (const row of [...rows].sort((a, b) => Number(a.price) - Number(b.price))) {
    const p = Number(row.price);
    const usd = Number(row.intensity_usd);
    const y = Y(p);
    const ancho = Math.max(6, usd / fuerte * (width - L - R - 20));
    const esElMayor = row === masFuerte;
    ctx.fillStyle = p > price
      ? `rgba(239,99,112,${esElMayor ? .95 : .6})`
      : `rgba(36,200,138,${esElMayor ? .95 : .6})`;
    ctx.fillRect(L, y - 4, ancho, 8);
    if (esElMayor) {
      // dentro de la barra: afuera choca con la columna de alcance de la derecha
      const etiqueta = `mayor clúster ${compactUsd(usd)}`;
      const cabe = ancho > ctx.measureText(etiqueta).width + 16;
      ctx.fillStyle = cabe ? "#0b0e14" : "#edf1f7";
      ctx.textAlign = cabe ? "right" : "left";
      ctx.fillText(etiqueta, cabe ? L + ancho - 8 : L + ancho + 8, y);
      ctx.textAlign = "left";
    }
  }

  // --- muros del libro como rombos sobre el mismo eje ---
  for (const m of muros) {
    const y = Y(Number(m.price));
    const x = width - R - 10;
    ctx.fillStyle = "#43bdd7";
    ctx.beginPath();
    ctx.moveTo(x, y - 6); ctx.lineTo(x + 6, y); ctx.lineTo(x, y + 6); ctx.lineTo(x - 6, y);
    ctx.closePath(); ctx.fill();
    ctx.textAlign = "left";
    ctx.fillStyle = "#43bdd7";
    ctx.fillText(compactUsd(m.amount_usd), x + 12, y);
  }

  // --- precio actual y los dos imanes con su tasa de alcance ---
  const yPrecio = Y(price);
  ctx.strokeStyle = "#edf1f7";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([5, 4]);
  ctx.beginPath(); ctx.moveTo(L, yPrecio); ctx.lineTo(width - R, yPrecio); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#edf1f7";
  ctx.font = "700 11px ui-monospace, monospace";
  ctx.textAlign = "right";
  ctx.fillText(`BTC ${fmt(price, 0)}`, L - 8, yPrecio - 13);

  ctx.font = "10px ui-monospace, monospace";
  ctx.textAlign = "left";
  for (const [nivel, color] of [[niveles.nearest_above, "#ef6370"],
                                [niveles.nearest_below, "#24c88a"]]) {
    const p4 = Number(nivel?.alcance_historico?.["4h"]);
    if (!nivel || !Number.isFinite(Number(nivel.price)) || !Number.isFinite(p4)) continue;
    const y = Y(Number(nivel.price));
    ctx.strokeStyle = color;
    ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(width - 12, y); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color;
    ctx.textAlign = "right";
    // desplazado en vertical: en la primera version caia sobre la etiqueta del
    // muro que esta al mismo precio y quedaban ilegibles
    const dy = Number(nivel.price) > price ? -11 : 11;
    ctx.fillText(`el más cercano · ${fmt(p4, 0)}% en 4h`, width - 10, y + dy);
    ctx.textAlign = "left";
  }
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

// La pestaña decía "Flujo 4h" fijo. Ahora muestra el intervalo REALMENTE medido
// en los datos (`intervals_observed`), y avisa si difiere del que se pidió: el
// plan Hobbyist puede negociar a la baja y antes eso no se veía en ninguna parte.
function renderIntervaloReal() {
  const boton = $("tab-flow");
  if (!boton) return;
  const basic = state.basic || {};
  const observados = basic.intervals_observed || {};
  const pedidos = basic.intervals || {};
  const real = observados.open_interest || observados.price
    || pedidos.open_interest || pedidos.price;
  boton.textContent = real ? `Flujo ${real}` : "Flujo";
  const desfase = basic.interval_mismatch || [];
  boton.title = desfase.length
    ? `El intervalo recibido no coincide con el pedido en: ${desfase.join(", ")}`
    : (real ? `Intervalo medido en los datos: ${real}` : "");
  if (desfase.length) boton.textContent += " ⚠";
}

// Brújula de TERRENO. Deliberadamente no dibuja una direccion "probable": el
// largo de cada aguja es la probabilidad HISTORICA de alcanzar ese nivel, asi que
// la aguja mas larga es el iman mas alcanzable, no un pronostico. Las reglas
// direccionales de CoinGlass quedaron refutadas fuera de muestra.
function drawCompass(visual) {
  const canvas = $("compass-chart");
  if (!canvas) return;
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.clearRect(0, 0, width, height);
  const niveles = visual.levels || {};
  const precio = Number(visual.price);
  const arriba = niveles.nearest_above;
  const abajo = niveles.nearest_below;
  if (!Number.isFinite(precio) || (!arriba && !abajo)) {
    message("compass-message", "Sin captura visual vigente");
    return;
  }
  message("compass-message", "");

  const cx = width / 2;
  const cy = height / 2;
  const largoMax = Math.min(cy - 46, 150);
  const prob = (nivel) => Number(nivel?.alcance_historico?.["4h"]);

  // eje vertical y precio actual en el centro
  ctx.strokeStyle = "#222936";
  ctx.beginPath(); ctx.moveTo(cx, 22); ctx.lineTo(cx, height - 22); ctx.stroke();
  ctx.strokeStyle = "#edf1f7";
  ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(cx - 10, cy); ctx.lineTo(cx + 100, cy); ctx.stroke();
  ctx.font = "11px ui-monospace, monospace";
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  ctx.fillStyle = "#edf1f7";
  ctx.fillText(`${fmt(precio, 0)} ahora`, cx - 14, cy);

  // anillos de muros ballena, a su distancia relativa
  const muros = [niveles.nearest_whale_ask, niveles.strongest_whale_ask,
                 niveles.nearest_whale_bid, niveles.strongest_whale_bid]
    .filter((m) => m && Number.isFinite(Number(m.price)));
  const distMax = Math.max(1, ...muros.map((m) => Math.abs(Number(m.distance_pct) || 0)),
                           Math.abs(Number(arriba?.distance_pct) || 0),
                           Math.abs(Number(abajo?.distance_pct) || 0));
  // Separacion minima en PIXELES, no en %: dos muros a 0,12% quedan a la misma
  // altura y sus etiquetas se pisaban entre si y con el precio del centro.
  const usadas = [cy];
  const libre = (y) => usadas.every((otra) => Math.abs(y - otra) >= 26);
  for (const m of [...muros].sort((a, b) =>
       Math.abs(Number(b.amount_usd) || 0) - Math.abs(Number(a.amount_usd) || 0))) {
    const d = Math.abs(Number(m.distance_pct) || 0);
    const hacia = Number(m.price) > precio ? -1 : 1;
    const y = cy + hacia * (d / distMax) * largoMax;
    if (!libre(y)) continue;                   // se prioriza el muro mas grande
    usadas.push(y);
    ctx.strokeStyle = "rgba(67,189,215,.45)";
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.ellipse(cx, y, 58, 7, 0, 0, Math.PI * 2); ctx.stroke();
    // el monto del muro a la izquierda: el espacio estaba vacio y este dato
    // dice si el anillo es una pared real o una orden chica
    ctx.textAlign = "right";
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = "#43bdd7";
    ctx.fillText(`muro ${compactUsd(m.amount_usd)}`, cx - 74, y);
    ctx.fillStyle = "#7d879a";
    ctx.fillText(`${fmt(Number(m.price), 0)} · ${signed(m.distance_pct, "%")}`,
                 cx - 74, y + 12);
  }

  // agujas: LARGO = probabilidad de alcance
  // El color sigue la MISMA convencion que el libro y el mapa visual: lo que esta
  // ARRIBA del precio es rojo (asks/resistencia) y lo de ABAJO verde
  // (bids/soporte). Antes estaba invertido solo aca, asi que el mismo nivel se
  // pintaba de un color en el mapa y del opuesto en la brujula.
  for (const [nivel, signo, etiqueta, color] of [
    [arriba, -1, "ARRIBA", "#ef6370"], [abajo, 1, "ABAJO", "#24c88a"],
  ]) {
    if (!nivel || !Number.isFinite(Number(nivel.price))) continue;
    const p = prob(nivel);
    const fraccion = Number.isFinite(p) ? Math.max(0.12, Math.min(1, p / 50)) : 0.3;
    const punta = cy + signo * fraccion * largoMax;
    ctx.strokeStyle = color;
    ctx.lineWidth = 7;
    ctx.lineCap = "round";
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx, punta); ctx.stroke();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(cx, punta, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.textAlign = "left";
    ctx.font = "700 12px sans-serif";
    ctx.fillText(`${etiqueta} · ${fmt(nivel.price, 0)}`, cx + 22, punta - 8);
    ctx.font = "11px ui-monospace, monospace";
    ctx.fillStyle = "#919baa";
    ctx.fillText(`${signed(nivel.distance_pct, "%")} · ` +
                 `${Number.isFinite(p) ? fmt(p, 0) + "% en 4h" : "sin tasa"}`,
                 cx + 22, punta + 8);
  }
  ctx.lineCap = "butt";
  ctx.textAlign = "center";
  ctx.fillStyle = "#7d879a";
  ctx.font = "10px ui-monospace, monospace";
  ctx.fillText("aguja larga = mas alcanzable · terreno, no destino", cx, height - 10);
}

// Lectura principal del Radar: los dos imanes de liquidez más cercanos y la
// frecuencia HISTÓRICA con que el precio recorre esa distancia. Es lo único que
// los datos permiten afirmar: no dice hacia dónde va, dice cuán lejos suele
// llegar y qué hay en el camino.
function renderAlcance(visual) {
  const cuerpo = $("radar-alcance").querySelector("tbody");
  const niveles = visual.levels || {};
  const arriba = niveles.nearest_above;
  const abajo = niveles.nearest_below;
  const filas = [
    ["Clúster arriba", arriba, "up"],
    ["Clúster abajo", abajo, "down"],
  ].filter(([, nivel]) => nivel && nivel.price != null);

  if (!filas.length) {
    cuerpo.innerHTML = `<tr><td colspan="6" class="empty">Sin captura visual vigente.</td></tr>`;
    $("radar-veredicto").textContent = "Sin captura visual vigente: no hay lectura.";
    $("radar-alcance-nota").textContent = "";
    return;
  }

  cuerpo.innerHTML = filas.map(([etiqueta, nivel, clase]) => {
    const a = nivel.alcance_historico || {};
    const celda = (v) => v == null ? "—" : `${fmt(v, 0)}%`;
    return `<tr><td class="${clase}">${escapeHtml(etiqueta)}</td>` +
      `<td>${fmt(nivel.price, 1)}</td>` +
      `<td>${signed(nivel.distance_pct, "%")}</td>` +
      `<td>${celda(a["4h"])}</td><td>${celda(a["8h"])}</td><td>${celda(a["12h"])}</td></tr>`;
  }).join("");

  // El "veredicto" es deliberadamente descriptivo: cuál imán está más cerca y
  // qué tan seguido se alcanza. NO se publica una direccion probable porque los
  // componentes direccionales quedaron refutados fuera de muestra.
  const dArriba = arriba ? Math.abs(Number(arriba.distance_pct)) : null;
  const dAbajo = abajo ? Math.abs(Number(abajo.distance_pct)) : null;
  let veredicto = "Hay liquidez a ambos lados a distancia similar.";
  if (dArriba != null && dAbajo != null) {
    const cerca = dArriba < dAbajo ? "ARRIBA" : "ABAJO";
    const nivel = dArriba < dAbajo ? arriba : abajo;
    const p4 = (nivel.alcance_historico || {})["4h"];
    veredicto = `El imán de liquidez más cercano está ${cerca} ` +
      `(${fmt(Math.min(dArriba, dAbajo), 2)}% de distancia` +
      `${p4 != null ? `, alcanzado en 4h el ${fmt(p4, 0)}% de las veces` : ""}).`;
  }
  $("radar-veredicto").textContent = veredicto;
  const n = (arriba?.alcance_historico || abajo?.alcance_historico || {}).n;
  $("radar-alcance-nota").textContent =
    `Los porcentajes son la TASA BASE histórica de que BTC recorra esa distancia ` +
    `en ese plazo${n ? ` (n=${n} barras de 4h)` : ""}. No están condicionados al ` +
    `estado actual del mercado y NO son una predicción de dirección: dicen cuán ` +
    `lejos suele llegar el precio, no hacia dónde.`;
}

const GLOSARIO = [
  ["Heatmap: atracción", "Dónde se acumula liquidez de liquidación en el heatmap, ponderado por cercanía.",
   "Positivo = más liquidez arriba. Es un imán potencial, no una señal de compra."],
  ["Mapa: atracción", "Lo mismo sobre el mapa de liquidaciones acumulado.",
   "Si coincide con el heatmap, el imán es más consistente."],
  ["Delta del libro", "Diferencia bids − asks en el libro cercano al precio.",
   "Positivo = más volumen de compra en el libro. Se retira fácil: es el más frágil."],
  ["Muros ballena · observación", "Órdenes límite grandes activas cerca del precio.",
   "NO entra al puntaje. Un muro puede ser spoofing y desaparecer."],
  ["Posicionamiento contrarian", "Qué tan cargados están los traders a un lado.",
   "Observacional: viene del modelo API y NO entra a este puntaje."],
  ["Funding contrarian", "Costo de mantener la posición dominante.",
   "Observacional: NO entra a este puntaje."],
];

function renderGlosario(hasVisual) {
  const cuerpo = $("radar-glosario").querySelector("tbody");
  cuerpo.innerHTML = GLOSARIO.map(([nombre, mide, lee]) =>
    `<tr><td>${escapeHtml(nombre)}</td><td>${escapeHtml(mide)}</td><td>${escapeHtml(lee)}</td></tr>`
  ).join("");
  if (!hasVisual) {
    cuerpo.insertAdjacentHTML("afterbegin",
      `<tr><td colspan="3" class="empty">Sin captura visual: los componentes de abajo ` +
      `vienen del modelo API, que es otra fórmula.</td></tr>`);
  }
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
  scoreBox.querySelector("span").textContent = (model.label || "sin datos") + " · sin validar";
  const visualForward = Number(state.visual_shadow?.decisions || 0);
  const apiForward = Number(apiModel.forward_observations || 0);
  const observations = hasVisual ? visualForward : Number(apiModel.observations || 0);
  const minimum = hasVisual ? 2016 : Number(apiModel.minimum_for_calibration || 100);
  $("calibration-label").textContent = hasVisual
    ? `${visualForward} capturas visuales forward · ${apiForward} API forward`
    : `${Number(apiModel.historical_observations || 0)} históricas · ${apiForward} forward`;
  $("calibration-progress").max = minimum;
  $("calibration-progress").value = Math.min(observations, minimum);
  drawCompass(visual);
  renderAlcance(visual);
  renderGlosario(hasVisual);
  renderIntervaloReal();
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

// --- LECTURA DEL MOMENTO -----------------------------------------------------
// Los cuatro datos que cambian una decisión, juntos y siempre visibles. Nada se
// calcula de nuevo acá: se compone lo que ya producen el indicador visual y el
// historial del libro.

// Cuántas capturas seguidas lleva vivo un muro. Un bid de 78M que sobrevive días
// no es lo mismo que uno de 78M que nació hace 5 min, y hasta ahora cada captura
// lo pintaba como si fuera nuevo.
function edadDelMuro(snapshots, muro, referencia) {
  if (!muro || !snapshots.length) return null;
  const paso = Math.max(1, (referencia || 1) * 0.0005);
  const k = Math.round(Number(muro.price) / paso);
  const lado = Number(muro.price) > referencia ? "asks" : "bids";
  let seguidas = 0;
  for (let i = snapshots.length - 1; i >= 0; i--) {
    const hay = (snapshots[i][lado] || []).some(([p]) => Math.round(p / paso) === k);
    if (!hay) break;
    seguidas++;
  }
  return seguidas;
}

function renderAhora() {
  const visual = state.visual_indicator;
  const snapshots = state.visual_orderbook_history || [];
  const set = (id, valor, meta, clase = "") => {
    $(id).textContent = valor;
    $(id).className = clase;
    $(`${id}-meta`).textContent = meta || "";
  };

  // 1. Imán más cercano, con su tasa base de alcance
  const niveles = visual?.levels || {};
  const arriba = niveles.nearest_above, abajo = niveles.nearest_below;
  const dA = arriba ? Math.abs(Number(arriba.distance_pct)) : null;
  const dB = abajo ? Math.abs(Number(abajo.distance_pct)) : null;
  if (dA != null || dB != null) {
    const haciaArriba = dB == null || (dA != null && dA < dB);
    const nivel = haciaArriba ? arriba : abajo;
    const p4 = Number(nivel.alcance_historico?.["4h"]);
    set("ahora-iman", `${haciaArriba ? "ARRIBA" : "ABAJO"} · ${fmt(nivel.price, 0)}`,
        `${signed(nivel.distance_pct, "%")}` +
        (Number.isFinite(p4) ? ` · alcanzado ${fmt(p4, 0)}% de las veces en 4h` : ""),
        haciaArriba ? "down" : "up");   // arriba = rojo, misma convención que el resto
  } else {
    set("ahora-iman", "—", "sin captura visual vigente");
  }

  // 2. Muro dominante del libro, con su edad.
  // Se usan los `dominant_*`, que NO llevan el radio de ±5%: medido en producción,
  // los cuatro muros mayores caían fuera de ese radio y el mayor de todos quedaba
  // excluido por 6 dólares. Con `strongest_*` esta tarjeta mostraba 5,6M mientras
  // en el libro había una pared de 78,7M.
  const muros = [niveles.dominant_whale_bid, niveles.dominant_whale_ask]
    .filter((m) => m && Number.isFinite(Number(m.amount_usd)));
  const dominante = muros.sort((a, b) => b.amount_usd - a.amount_usd)[0];
  if (dominante) {
    const compra = Number(dominante.price) < Number(visual.price);
    const seguidas = edadDelMuro(snapshots, dominante, Number(visual.price));
    const vive = seguidas == null ? "" :
      seguidas >= snapshots.length ? ` · lleva toda la ventana` :
      ` · ${seguidas} capturas seguidas`;
    set("ahora-muro", `${compactUsd(dominante.amount_usd)} ${compra ? "compra" : "venta"}`,
        `${fmt(dominante.price, 0)} · ${signed(dominante.distance_pct, "%")}${vive}`,
        compra ? "up" : "down");
  } else {
    set("ahora-muro", "—", "sin muros cerca del precio");
  }

  // 3. Flujo de la ventana: la tasa de retirados es lo interesante
  if (snapshots.length >= 2) {
    const precio = Number(snapshots[snapshots.length - 1].price);
    const f = flujoDeMuros(snapshots, precio);
    const salieron = f.consumidos + f.retirados;
    set("ahora-flujo", `${f.nuevos} nuevos · ${f.consumidos} consumidos · ${f.retirados} retirados`,
        salieren(salieron, f));
  } else {
    set("ahora-flujo", "—", "hace falta más de una captura");
  }

  // 4. Frescura de la captura Y salud del archivo histórico. El estado ya publica
  // `visual_book_archive` desde ayer y la UI no lo mostraba en ninguna parte: el
  // modo de falla exacto que ese dato venía a evitar.
  const edad = Number(visual?.age_seconds);
  const archivo = state.visual_book_archive || {};
  const partes = [];
  if (archivo.existe && archivo.ultima_escritura) {
    const min = Math.round((Date.now() - Date.parse(archivo.ultima_escritura)) / 60000);
    partes.push(`archivo ${fmt(archivo.bytes / 1e6, 1)} MB` +
                (Number.isFinite(min) ? `, última escritura hace ${min} min` : ""));
    if (archivo.lleno) partes.push("ARCHIVO LLENO: dejó de guardar");
  } else if (archivo.existe === false) {
    partes.push("archivo histórico aún vacío");
  }
  if (Number.isFinite(edad)) {
    const min = Math.round(edad / 60);
    set("ahora-fresco", `hace ${min} min`, partes.join(" · "),
        min > 15 || archivo.lleno ? "down" : "");
  } else {
    set("ahora-fresco", "—", partes.join(" · "));
  }
}

function salieren(salieron, f) {
  if (!salieron) return "ningún muro desapareció en la ventana";
  const pct = Math.round(100 * f.retirados / salieron);
  return `${pct}% de los que desaparecieron se retiraron sin que el precio llegara`;
}

function render(data) {
  state = data;
  if (data.waiting) {
    $("updated").textContent = "Esperando primera captura del VPS";
    return;
  }
  $("price").textContent = data.advanced?.price ? `${fmt(data.advanced.price, 1)} USDT` : "BTCUSDT";
  // `age_seconds` es la edad del ARCHIVO, y el archivo se reescribe en cada ciclo
  // aunque la API haya fallado y el contenido sea el cacheado. Sin esto el panel
  // decía "hace 12 s" mostrando un precio de hace horas.
  const edadArchivo = `Actualizado hace ${fmt(data.age_seconds, 0)} s`;
  const capturaDato = data.advanced?.captured_at ? Date.parse(data.advanced.captured_at) : NaN;
  const edadDato = Number.isFinite(capturaDato)
    ? Math.round((Date.now() - capturaDato) / 60000) : null;
  $("updated").textContent = data.advanced?.stale
    ? `${edadArchivo} · DATO CACHEADO${edadDato != null ? ` de hace ${edadDato} min` : ""}: la API falló`
    : (edadDato != null && edadDato > 30
        ? `${edadArchivo} · el dato de mercado es de hace ${edadDato} min`
        : edadArchivo);
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
  renderAhora();
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

document.querySelectorAll("[data-zoom]").forEach((button) => {
  button.addEventListener("click", () => {
    bookZoom = Number(button.dataset.zoom);
    document.querySelectorAll("[data-zoom]").forEach((item) =>
      item.classList.toggle("active", item === button));
    drawOrderbook();
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
