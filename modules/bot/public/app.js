// NexUX BOT — espejo en vivo + control. Lee /m/bot/api/state; comandos a /api/command.
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => (n === null || n === undefined || n === "") ? "—" : Number(n).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d });
const pairLabel = (p) => (p || "").replace("_USDT", "").replace("USDT", "") || p;
const signed = (n) => (n >= 0 ? "+" : "") + fmt(n);
const dt = (ts) => { if (!ts) return "—"; const d = new Date(ts * 1000); return d.toLocaleString("es-CL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); };
const tradeR = (t) => {
  if (t.result_r !== null && t.result_r !== undefined && t.result_r !== "") return Number(t.result_r);
  const risk = Number(t.risk_usd_est ?? t.risk_usd ?? 0);
  if (!risk || t.pnl_usd === null || t.pnl_usd === undefined) return null;
  return Number(t.pnl_usd) / risk;
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

function phase1(data) {
  const el = $("phase1");
  if (!el) return;
  const dry = (data.trades || []).filter(t => t.mode === "dry");
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
        <strong>Fase 1</strong>
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
    <div class="phase-note">Este bloque solo observa la Fase 1. No cambia filtros, no abre/cierra trades y no autoriza live automaticamente.</div>
    ${pairRows ? `<div class="phase-table"><table><thead><tr><th>Par</th><th>N</th><th>WR</th><th>avgR</th><th>P&L</th></tr></thead><tbody>${pairRows}</tbody></table></div>` : ""}
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
    header(data); watchdog(data); cards(data); phase1(data); position(data); watching(data); orders(data); trades(data);
  } catch (e) {
    $("rows").innerHTML = `<tr><td colspan="12" class="empty">No se pudo cargar: ${e}</td></tr>`;
  }
}

load();
setInterval(load, 5000);  // refresco del panel cada 5s
