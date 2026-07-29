// NexUX BOT — espejo en vivo + control. Lee /m/bot/api/state; comandos a /api/command.
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => (n === null || n === undefined || n === "") ? "—" : Number(n).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d });
const pairLabel = (p) => (p || "").replace("_USDT", "").replace("USDT", "") || p;
const signed = (n) => (n >= 0 ? "+" : "") + fmt(n);
const PHASE1_V2 = "phase1_v2_2026-07-18";
const dt = (ts) => { if (!ts) return "—"; const d = new Date(ts * 1000); return d.toLocaleString("es-CL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); };
const tradeR = (t) => {
  const risk = Number(t.risk_usd_est ?? t.risk_usd ?? 0);
  if (risk && t.pnl_usd !== null && t.pnl_usd !== undefined) return Number(t.pnl_usd) / risk;
  if (t.result_r !== null && t.result_r !== undefined && t.result_r !== "") return Number(t.result_r);
  return null;
};

async function cmd(action, symbol) {
  const msg = action === "kill" ? "¿Detener el bot? No abrirá nuevas posiciones."
    : action === "resume" ? "¿Reanudar el bot?"
    : `¿Cerrar AHORA la posición ${pairLabel(symbol)} a mercado?`;
  if (!confirm(msg)) return;
  try {
    const r = await fetch("/m/bot/api/command", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, symbol }),
    });
    const d = await r.json();
    if (!r.ok) { alert("No se pudo: " + (d.error || r.status)); return; }
    alert("Orden enviada al bot: " + action + (symbol ? " " + pairLabel(symbol) : "") +
          ".\nSe aplica en el próximo ciclo (~15s).");
    setTimeout(load, 2000);
  } catch (e) { alert("Error: " + e); }
}

function header(data) {
  const el = $("mode");
  if (!data.active) { el.className = "mode off"; el.textContent = "Inerte (sin llaves)"; }
  else if (data.live) { el.className = "mode live"; el.textContent = "● En vivo (real)"; }
  else { el.className = "mode dry"; el.textContent = "Dry-run (simulado)"; }
  const lead = $("lead");
  if (lead) {
    lead.innerHTML = data.live
      ? `Espejo en vivo de la operación <strong>real</strong> en Binance Futuros (subcuenta aislada). El Diario sigue registrando el paper aparte, para estudio.`
      : `Dry-run activo: el bot registra operaciones <strong>simuladas</strong> en el libro con modo <strong>dry</strong>; no envía órdenes reales a Binance.`;
  }
  $("age").textContent = data.source === "vps" && data.age_seconds != null
    ? `actualizado hace ${Math.round(data.age_seconds)}s` : "";
  const killed = !!data.kill;
  $("kill-banner").hidden = !killed;
  $("btn-kill").hidden = killed;
  $("btn-resume").hidden = !killed;
}

function watchdog(data) {
  const el = $("watchdog-banner");
  if (!el) return;
  const positions = data.positions || [];
  const warns = [];
  const age = data.source === "vps" ? data.age_seconds : null;
  if (positions.length && age != null && age > 45) {
    warns.push(`espejo atrasado ${Math.round(age)}s con posición abierta`);
  }
  if (positions.length && data.kill) {
    warns.push("kill-switch activo mientras hay posición abierta");
  }
  if (positions.length && !data.active) {
    warns.push("bot inactivo mientras hay posición abierta");
  }
  el.hidden = !warns.length;
  el.textContent = warns.length ? "Watchdog: " + warns.join(" · ") : "";
}

function cards(data) {
  const a = data.account || {}, s = data.summary || {};
  const byMode = s.by_mode || {};
  const dryPnl = byMode.dry && byMode.dry.pnl_usd;
  const livePnl = byMode.live && byMode.live.pnl_usd;
  const pnlCls = (s.pnl_usd || 0) >= 0 ? "green" : "red";
  const dryCls = (dryPnl || 0) >= 0 ? "green" : "red";
  const liveCls = (livePnl || 0) >= 0 ? "green" : "red";
  const upnlCls = (a.upnl || 0) >= 0 ? "green" : "red";
  const list = [
    { k: "Balance (USDT)", v: a.balance != null ? fmt(a.balance) : "—" },
    { k: "uPnL abierto", v: a.upnl != null ? signed(a.upnl) : "—", cls: upnlCls },
    { k: "P&L dry (sim)", v: dryPnl != null ? fmt(dryPnl) : "—", cls: dryCls },
    { k: "P&L live (real)", v: livePnl != null ? fmt(livePnl) : "—", cls: liveCls },
    { k: "P&L libro total", v: fmt(s.pnl_usd), cls: pnlCls },
    { k: "Operaciones", v: s.total ?? 0 },
    { k: "Win rate", v: (s.win_rate == null) ? "—" : fmt(s.win_rate, 0) + "%" },
    { k: "Comisiones", v: fmt(s.fees_usd) },
  ];
  $("cards").innerHTML = list.map(c =>
    `<div class="card"><div class="k">${c.k}</div><div class="v ${c.cls || ""}">${c.v}</div></div>`).join("");
}

function testnet(data) {
  const el = $("testnet");
  if (!el) return;
  const t = data.testnet;
  if (!t) {
    el.innerHTML = `<p class="muted">Testnet no está conectado en este proceso.</p>`;
    return;
  }
  const a = t.account || {};
  const s = t.summary || {};
  const positions = t.positions || [];
  const recent = (t.trades || []).slice(0, 5);
  const state = t.kill ? "Detenido" : t.active && t.live_virtual ? "Operando virtual" : "Inerte";
  const rows = recent.map((trade) => `<tr>
    <td>${dt(trade.opened_at)}</td>
    <td>${pairLabel(trade.pair || trade.symbol)}</td>
    <td><span class="pill ${trade.dir}">${trade.dir === "long" ? "LONG" : "SHORT"}</span></td>
    <td>${trade.status}</td>
    <td class="${Number(trade.pnl_usd || 0) >= 0 ? "pos" : "neg"}">${trade.pnl_usd == null ? "—" : signed(trade.pnl_usd)}</td>
  </tr>`).join("");
  el.innerHTML = `<div class="testnet-head">
      <div><strong>Binance Demo</strong><span>Órdenes reales contra saldo virtual</span></div>
      <span class="testnet-state ${t.kill ? "stopped" : "running"}">${state}</span>
    </div>
    <div class="testnet-grid">
      <div><span>Balance virtual</span><b>${a.balance == null ? "—" : fmt(a.balance)} USDT</b></div>
      <div><span>Posiciones abiertas</span><b>${positions.length}</b></div>
      <div><span>P&L virtual</span><b class="${Number(s.pnl_usd || 0) >= 0 ? "pos" : "neg"}">${signed(Number(s.pnl_usd || 0))}</b></div>
      <div><span>Operaciones</span><b>${s.total || 0}</b></div>
    </div>
    ${rows ? `<div class="phase-table"><table><thead><tr><th>Fecha</th><th>Par</th><th>Dir</th><th>Estado</th><th>P&L virtual</th></tr></thead><tbody>${rows}</tbody></table></div>` : `<p class="phase-note">Esperando la próxima activación válida del Diario.</p>`}`;
}

function phase1(data) {
  const el = $("phase1");
  if (!el) return;
  const allDry = (data.trades || []).filter(t => t.mode === "dry");
  const dry = allDry.filter(t => t.phase_id === PHASE1_V2);
  const legacyClosed = allDry.filter(t => t.phase_id !== PHASE1_V2 && t.status === "cerrada");
  const closed = dry.filter(t => t.status === "cerrada");
  const open = dry.filter(t => t.status === "abierta");
  const rs = closed.map(tradeR).filter(r => r !== null && Number.isFinite(r));
  const n = closed.length;
  const wins = closed.filter(t => (t.pnl_usd || 0) > 0).length;
  const wr = n ? wins / n * 100 : null;
  const avgR = rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : null;
  const pnl = closed.reduce((acc, t) => acc + Number(t.pnl_usd || 0), 0);
  const progress = Math.min(100, n / 20 * 100);
  const passN = n >= 20;
  const passR = avgR !== null && avgR > 0.2;
  const passWr = wr !== null && wr >= 55;
  const statusCls = passN && passR && passWr ? "ok" : "wait";
  const status = passN && passR && passWr
    ? "Cumple criterio numerico; requiere decision manual antes de live"
    : "Observando; no autoriza live";
  const byPair = {};
  for (const t of closed) {
    const p = pairLabel(t.pair || t.symbol);
    const r = tradeR(t);
    byPair[p] ||= { n: 0, wins: 0, pnl: 0, rsum: 0, rn: 0 };
    byPair[p].n += 1;
    byPair[p].wins += (t.pnl_usd || 0) > 0 ? 1 : 0;
    byPair[p].pnl += Number(t.pnl_usd || 0);
    if (r !== null && Number.isFinite(r)) { byPair[p].rsum += r; byPair[p].rn += 1; }
  }
  const pairRows = Object.entries(byPair).sort((a, b) => b[1].n - a[1].n).map(([p, x]) => {
    const pwr = x.n ? x.wins / x.n * 100 : 0;
    const pr = x.rn ? x.rsum / x.rn : null;
    return `<tr><td>${p}</td><td>${x.n}</td><td>${fmt(pwr, 0)}%</td><td>${pr === null ? "—" : signed(pr)}</td><td>${signed(x.pnl)}</td></tr>`;
  }).join("");
  el.innerHTML = `<div class="phase-card">
    <div class="phase-head">
      <div>
        <strong>Fase 1 V2</strong>
        <span>20 trades dry o 3 semanas · avgR &gt; +0.20 · WR >= 55%</span>
      </div>
      <span class="phase-status ${statusCls}">${status}</span>
    </div>
    <div class="progress"><div style="width:${progress}%"></div></div>
    <div class="phase-grid">
      <div><span>Trades dry cerrados</span><b>${n}/20</b></div>
      <div><span>Dry abiertos</span><b>${open.length}</b></div>
      <div><span>WR dry</span><b class="${passWr ? "pos" : ""}">${wr === null ? "—" : fmt(wr, 0) + "%"}</b></div>
      <div><span>avgR neto</span><b class="${passR ? "pos" : (avgR !== null && avgR < 0 ? "neg" : "")}">${avgR === null ? "—" : signed(avgR)}</b></div>
      <div><span>P&L dry</span><b class="${pnl >= 0 ? "pos" : "neg"}">${signed(pnl)}</b></div>
      <div><span>Estado live</span><b>${data.live ? "REAL" : "DRY"}</b></div>
    </div>
    <div class="phase-note">Fill V2: cruce causal de la entrada central. Histórico V1 archivado: ${legacyClosed.length} cerrados, fuera de esta evaluación. Este bloque no abre/cierra trades y no autoriza live automaticamente.</div>
    ${abiertosHtml(open)}
    ${pairRows ? `<div class="phase-table"><table><thead><tr><th>Par</th><th>N</th><th>WR</th><th>avgR</th><th>P&L</th></tr></thead><tbody>${pairRows}</tbody></table></div>` : ""}
  </div>`;
}


/* Precio en vivo de los pares con trade abierto, pedido por el NAVEGADOR.
 *
 * El HTTP 451 de Binance es del datacenter de Railway, no de la ubicacion del que
 * mira (verificado el 2026-07-26: REST 200 y `access-control-allow-origin: *` desde
 * la maquina de Hugo). Asi no hay que cambiar nada en el VPS ni en la ingesta.
 *
 * Si falla —viaje, VPN, jurisdiccion restringida— se cae al `price_now` que ya trae
 * `watching`, y si tampoco esta, la fila muestra "—". Nunca inventa un precio.
 */
const preciosVivos = { mapa: {}, ts: 0, fuente: "—" };

async function refrescarPrecios(simbolos, respaldo) {
  for (const [sym, px] of Object.entries(respaldo || {})) {
    if (Number.isFinite(px)) preciosVivos.mapa[sym] = px;
  }
  if (Object.keys(respaldo || {}).length) preciosVivos.fuente = "ingesta VPS";
  if (!simbolos.length) return;
  try {
    const r = await fetch("https://fapi.binance.com/fapi/v1/ticker/price");
    if (!r.ok) throw new Error(String(r.status));
    const filas = await r.json();
    const quiero = new Set(simbolos);
    for (const f of filas) {
      if (quiero.has(f.symbol)) preciosVivos.mapa[f.symbol] = Number(f.price);
    }
    preciosVivos.ts = Date.now();
    preciosVivos.fuente = "Binance en vivo";
  } catch (e) {
    // Sin red a Binance queda el respaldo; el encabezado dice cual se uso.
  }
}

/* Resultado vivo de un trade con parciales ya tomados.
 *
 * NO se puede mirar solo el precio contra la entrada: si ya se cerro la mitad en TP1,
 * esa mitad esta realizada y el resto es lo unico que sigue expuesto. En el SOL real
 * de hoy, `qty` 18,633 -> `qty_open` 9,317: la mitad ya no depende del precio.
 *
 * R por unidad = |entrada - SL|. El tramo vivo se pondera por `qty_open/qty` para que
 * los dos sumandos esten en la misma escala, igual que `realized_r` que el store ya
 * guarda ponderado.
 */
function resultadoVivo(t, precio) {
  const entry = Number(t.entry_price ?? t.setup_entry);
  const sl = Number(t.sl);
  const runit = Math.abs(entry - sl);
  const q = Number(t.qty || 0), qo = Number(t.qty_open ?? t.qty ?? 0);
  const realizado = (t.partials || []).reduce((a, p) => a + Number(p.realized_r || 0), 0);
  if (!Number.isFinite(precio) || !runit || !q) {
    return { precio: null, rVivo: null, rTotal: realizado || null, realizado };
  }
  const signo = t.dir === "long" ? 1 : -1;
  const rVivo = ((precio - entry) * signo / runit) * (qo / q);
  return { precio, rVivo, rTotal: realizado + rVivo, realizado };
}

// Los trades ABIERTOS de la Fase 1, no solo su cantidad.
//
// Antes `open` se usaba unicamente para el contador "Dry abiertos: 2": se sabia que
// habia dos y no cuales. Estos son papel —el bot corre con `live=false` y el bloque
// `#position` de mas abajo, que muestra posiciones REALES de Binance, esta vacio a
// proposito—. Mezclar las dos cosas seria decir que hay exposicion donde no la hay.
function abiertosHtml(abiertos) {
  if (!abiertos.length) {
    return `<p class="phase-note">Sin trades abiertos en la fase.</p>`;
  }
  const filas = abiertos.map((t) => {
    const entry = Number(t.entry_price ?? t.setup_entry);
    const sl = Number(t.sl), tp = Number(t.tp);
    const largo = t.dir === "long";
    // Cuanto queda vivo de la posicion. Si hubo parciales, `qty_open` baja y el
    // numero de arriba dejaria de describir lo que hay expuesto.
    const q = Number(t.qty || 0), qo = Number(t.qty_open ?? t.qty ?? 0);
    const restante = q > 0 ? Math.round(qo / q * 100) : null;
    const legs = (t.partials || []).map((p) => p.leg).join(", ");
    const rGan = (t.partials || []).reduce((a, p) => a + Number(p.realized_r || 0), 0);
    const riesgo = Number(t.risk_usd);
    const res = resultadoVivo(t, preciosVivos.mapa[t.symbol]);
    // Verde/rojo solo cuando hay precio: sin dato no se pinta un color que sugiera
    // que vamos ganando o perdiendo.
    const clase = (r) => r === null ? "" : r >= 0 ? "pos" : "neg";
    const horas = t.opened_at ? (Date.now() / 1000 - t.opened_at) / 3600 : null;
    const tiempo = horas === null ? "—"
      : horas < 48 ? `${fmt(horas, 0)} h` : `${fmt(horas / 24, 0)} d`;
    // El RR se muestra tal cual y sin adornos: el estudio del 2026-07-26 encontro que
    // DENTRO de rr>=5, mas RR predice PEOR resultado (Q2 rr~8 -> +0,815R y 21,1% de TP;
    // Q5 rr>=21,2 -> +0,142R y 4,8%). No esta pre-registrado ni confirmado, asi que no
    // se filtra por eso, pero esconder el numero seria peor.
    const rrAlto = Number(t.rr) >= 15;
    return `<tr>
      <td>${pairLabel(t.pair || t.symbol)}</td>
      <td class="${largo ? "pos" : "neg"}">${largo ? "long" : "short"}</td>
      <td class="num">${fmt(entry, 4)}</td>
      <td class="num">${res.precio === null ? "—" : fmt(res.precio, 4)}</td>
      <td class="num neg">${fmt(sl, 4)}</td>
      <td class="num pos">${fmt(tp, 4)}</td>
      <td class="num${rrAlto ? " rr-alto" : ""}" title="${rrAlto
        ? "RR alto: dentro de rr>=5, mas RR predijo PEOR resultado en el estudio del 26-jul (no confirmado)"
        : ""}">${fmt(t.rr, 1)}</td>
      <td class="num">${restante === null ? "—" : restante + "%"}</td>
      <td>${legs ? `${legs} (${signed(rGan)})` : "—"}</td>
      <td class="num ${clase(res.rTotal)}">${res.rTotal === null ? "—" : signed(res.rTotal)}</td>
      <td class="num ${clase(res.rTotal)}">${res.rTotal === null || !Number.isFinite(riesgo)
        ? "—" : signed(res.rTotal * riesgo) + " USD"}</td>
      <td class="num">${tiempo}</td>
    </tr>`;
  }).join("");
  return `<div class="phase-table abiertos">
    <div class="abiertos-head">Abiertos ahora · <span>papel, no son posiciones reales · precio: ${preciosVivos.fuente}</span></div>
    <table><thead><tr>
      <th>Par</th><th>Dir</th><th>Entrada</th><th>Precio</th><th>SL</th><th>TP</th><th>RR</th>
      <th>Vivo</th><th>Parciales</th><th>R total</th><th>P&L</th><th>Tiempo</th>
    </tr></thead><tbody>${filas}</tbody></table>
  </div>`;
}

function position(data) {
  const ps = data.positions || [];
  if (!ps.length) { $("position").innerHTML = `<p class="muted">Sin posición abierta.</p>`; return; }
  $("position").innerHTML = ps.map(p => {
    const up = p.unrealized_pnl || 0;
    return `<div class="pos-card">
      <div class="pos-head">
        <span class="pill ${(p.side||'').toLowerCase()}">${p.side}</span>
        <strong>${pairLabel(p.symbol)}</strong>
        <span class="lev">${p.leverage}x</span>
      </div>
      <div class="pos-grid">
        <div><span>Qty</span>${fmt(p.qty, 4)}</div>
        <div><span>Entrada</span>${fmt(p.entry)}</div>
        <div><span>Precio actual</span>${p.mark ? fmt(p.mark) : "—"}</div>
        <div><span>uPnL</span><b class="${up>=0?'pos':'neg'}">${signed(up)}</b></div>
        <div><span>Notional</span>${p.notional != null ? fmt(p.notional) : "—"}</div>
        <div><span>Margen</span>${p.margin != null ? fmt(p.margin) : "—"}</div>
        <div><span>Riesgo est.</span>${p.risk_usd_est != null ? fmt(p.risk_usd_est) : "—"}</div>
        <div><span>Riesgo cuenta</span>${p.risk_pct_account != null ? fmt(p.risk_pct_account, 2) + "%" : "—"}</div>
        <div><span>Margen libro</span>${p.margin_used != null ? fmt(p.margin_used) : "—"}</div>
        <div><span>Fees est.</span>${p.fee_est_roundtrip != null ? fmt(p.fee_est_roundtrip, 4) : "—"}</div>
        <div><span>Calidad</span>${p.quality ? `<span class="pill ${p.quality}" title="${p.quality_reason || ''}">${p.quality}</span>` : "—"}</div>
        <div><span>SL %</span>${p.sl_pct != null ? fmt(p.sl_pct, 2) + "%" : "—"}</div>
        <div><span>Apalancamiento</span>${p.leverage ? p.leverage + "x" : "—"}</div>
        <div><span>Liq.</span>${p.liq_price ? fmt(p.liq_price) : "—"}</div>
      </div>
      <div class="pos-levels">
        <div class="lvl sl"><span>SL</span>${p.sl ? fmt(p.sl) : "—"}</div>
        <div class="lvl tp"><span>TP1 (50%) · 1R</span>${p.tp1 ? fmt(p.tp1) : "—"}</div>
        <div class="lvl tp"><span>TP2 (25%) · 2R</span>${p.tp2 ? fmt(p.tp2) : "—"}</div>
        <div class="lvl tp"><span>Runner (25%)</span>trailing ↗ (deja correr)</div>
      </div>
      <button class="btn btn-danger sm" onclick="cmd('close','${p.symbol}')">Cerrar posición ahora</button>
    </div>`;
  }).join("");
}

function watching(data) {
  const ws = data.watching || [];
  if (!ws.length) { $("watching").innerHTML = `<p class="muted">Nada en vigilancia en BTC/ETH ahora.</p>`; return; }
  $("watching").innerHTML = `<div class="table-wrap"><table><thead><tr>
    <th>Par</th><th>Dir</th><th>Zona entrada</th><th>Precio ahora</th><th>SL</th><th>TP</th><th>R:R</th><th>TF</th></tr></thead><tbody>` +
    ws.map(w => {
      const zona = (w.entry_lo && w.entry_hi && w.entry_lo !== w.entry_hi)
        ? `${fmt(w.entry_lo)}–${fmt(w.entry_hi)}` : fmt(w.entry);
      const dist = (w.dist_pct != null) ? ` <span class="muted">(${w.dist_pct > 0 ? "+" : ""}${w.dist_pct}%)</span>` : "";
      return `<tr>
        <td>${pairLabel(w.pair)}</td>
        <td><span class="pill ${w.dir}">${w.dir === "long" ? "LONG" : "SHORT"}</span></td>
        <td>${zona}</td>
        <td>${w.price_now ? fmt(w.price_now) : "—"}${dist}</td>
        <td>${fmt(w.sl)}</td><td>${fmt(w.tp)}</td>
        <td>${w.rr ? fmt(w.rr, 1) : "—"}</td><td>${w.poi_tf || "—"}</td></tr>`;
    }).join("") + `</tbody></table></div>`;
}

function orders(data) {
  const os = data.open_orders || [];
  if (!os.length) { $("orders").innerHTML = `<p class="muted">Sin órdenes activas.</p>`; return; }
  $("orders").innerHTML = `<div class="table-wrap"><table><thead><tr>
    <th>Par</th><th>Tipo</th><th>Lado</th><th>Stop</th><th>Cierra todo</th></tr></thead><tbody>` +
    os.map(o => `<tr><td>${pairLabel(o.symbol)}</td><td>${o.type}</td><td>${o.side}</td>
      <td>${o.stop_price ? fmt(o.stop_price) : "—"}</td><td>${o.close_position ? "sí" : "—"}</td></tr>`).join("") +
    `</tbody></table></div>`;
}

function trades(data) {
  const ts = data.trades || [];
  if (!ts.length) { $("rows").innerHTML = `<tr><td colspan="12" class="empty">Sin operaciones todavía. El bot anotará acá cada vez que un setup del Diario se active.</td></tr>`; return; }
  $("rows").innerHTML = ts.map(t => {
    const pnl = t.pnl_usd;
    const pnlCell = (pnl == null) ? "—" : `<span class="${pnl >= 0 ? "pos" : "neg"}">${signed(pnl)}</span>`;
    const risk = t.risk_usd_est ?? t.risk_usd;
    const fechaCell = t.closed_at
      ? `${dt(t.opened_at)}<br><span style="font-size:11px;opacity:.6">cierre ${dt(t.closed_at)}</span>`
      : dt(t.opened_at);
    return `<tr>
      <td>${fechaCell}</td>
      <td>${pairLabel(t.pair || t.symbol)}</td>
      <td><span class="pill ${t.dir}">${t.dir === "long" ? "LONG" : "SHORT"}</span></td>
      <td><span class="pill ${t.mode}">${t.mode}</span></td>
      <td>${fmt(t.qty, 4)}</td>
      <td>${fmt(t.entry_price)}</td>
      <td>${t.exit_price ? fmt(t.exit_price) : "—"}</td>
      <td>${t.leverage ? t.leverage + "x" : "—"}</td>
      <td>${risk != null ? fmt(risk) : "—"}</td>
      <td><span class="pill ${t.quality || 'manual'}" title="${t.quality_reason || ''}">${t.quality || "—"}</span></td>
      <td>${pnlCell}</td>
      <td><span class="pill ${t.status}">${t.status}</span></td>
    </tr>`;
  }).join("");
}

async function activarNotif() {
  const b = document.getElementById("btn-notif");
  try {
    if (!window.NexusPush) { alert("Notificaciones no disponibles en este navegador."); return; }
    await window.NexusPush.activar();
    alert("Notificaciones activadas. Te llegarán solo las operaciones del bot.");
    if (b) { b.textContent = "Notificaciones activas"; b.disabled = true; }
  } catch (e) {
    alert("No se pudo activar: " + (e.message || e));
  }
}

async function load() {
  try {
    const r = await fetch("/m/bot/api/state", { cache: "no-store" });
    if (r.status === 401) { location.href = "/login"; return; }
    const data = await r.json();
    header(data); watchdog(data); cards(data); testnet(data); phase1(data); position(data); watching(data); orders(data); trades(data);
    // Los precios se piden DESPUES del primer pintado para no retrasar la pantalla, y
    // la seccion se repinta cuando llegan. Sin esto la tabla mostraria "—" para
    // siempre en la primera carga.
    const abiertas = (data.trades || []).filter(
      (t) => t.mode === "dry" && t.phase_id === PHASE1_V2 && t.status === "abierta");
    if (abiertas.length) {
      const respaldo = {};
      for (const w of data.watching || []) {
        if (w.symbol && Number.isFinite(Number(w.price_now))) {
          respaldo[w.symbol] = Number(w.price_now);
        }
      }
      refrescarPrecios([...new Set(abiertas.map((t) => t.symbol))], respaldo)
        .then(() => phase1(data));
    }
  } catch (e) {
    $("rows").innerHTML = `<tr><td colspan="12" class="empty">No se pudo cargar: ${e}</td></tr>`;
  }
}

load();
setInterval(load, 5000);  // refresco del panel cada 5s
