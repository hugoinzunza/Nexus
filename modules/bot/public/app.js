// NexUX BOT — espejo en vivo + control. Lee /m/bot/api/state; comandos a /api/command.
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => (n === null || n === undefined || n === "") ? "—" : Number(n).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d });
const pairLabel = (p) => (p || "").replace("_USDT", "").replace("USDT", "") || p;
const signed = (n) => (n >= 0 ? "+" : "") + fmt(n);

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
  $("age").textContent = data.source === "vps" && data.age_seconds != null
    ? `actualizado hace ${Math.round(data.age_seconds)}s` : "";
  const killed = !!data.kill;
  $("kill-banner").hidden = !killed;
  $("btn-kill").hidden = killed;
  $("btn-resume").hidden = !killed;
}

function cards(data) {
  const a = data.account || {}, s = data.summary || {};
  const pnlCls = (s.pnl_usd || 0) >= 0 ? "green" : "red";
  const upnlCls = (a.upnl || 0) >= 0 ? "green" : "red";
  const list = [
    { k: "Balance (USDT)", v: a.balance != null ? fmt(a.balance) : "—" },
    { k: "uPnL abierto", v: a.upnl != null ? signed(a.upnl) : "—", cls: upnlCls },
    { k: "P&L libro (USD)", v: fmt(s.pnl_usd), cls: pnlCls },
    { k: "Operaciones", v: s.total ?? 0 },
    { k: "Win rate", v: (s.win_rate == null) ? "—" : fmt(s.win_rate, 0) + "%" },
    { k: "Comisiones", v: fmt(s.fees_usd) },
  ];
  $("cards").innerHTML = list.map(c =>
    `<div class="card"><div class="k">${c.k}</div><div class="v ${c.cls || ""}">${c.v}</div></div>`).join("");
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
        <div><span>Apalancamiento</span>${p.leverage ? p.leverage + "x" : "—"}</div>
        <div><span>Liq.</span>${p.liq_price ? fmt(p.liq_price) : "—"}</div>
      </div>
      <button class="btn btn-danger sm" onclick="cmd('close','${p.symbol}')">✋ Cerrar posición ahora</button>
    </div>`;
  }).join("");
}

function watching(data) {
  const ws = data.watching || [];
  if (!ws.length) { $("watching").innerHTML = `<p class="muted">Nada en vigilancia en BTC/ETH ahora.</p>`; return; }
  $("watching").innerHTML = `<div class="table-wrap"><table><thead><tr>
    <th>Par</th><th>Dir</th><th>Estado</th><th>Zona entrada</th><th>SL</th><th>TP</th><th>R:R</th><th>TF</th></tr></thead><tbody>` +
    ws.map(w => {
      const zona = (w.entry_lo && w.entry_hi && w.entry_lo !== w.entry_hi)
        ? `${fmt(w.entry_lo)}–${fmt(w.entry_hi)}` : fmt(w.entry);
      const stCls = w.status === "activo" ? "abierta" : "dry";
      return `<tr>
        <td>${pairLabel(w.pair)}</td>
        <td><span class="pill ${w.dir}">${w.dir === "long" ? "LONG" : "SHORT"}</span></td>
        <td><span class="pill ${stCls}">${w.status}</span></td>
        <td>${zona}</td><td>${fmt(w.sl)}</td><td>${fmt(w.tp)}</td>
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
  if (!ts.length) { $("rows").innerHTML = `<tr><td colspan="9" class="empty">Sin operaciones todavía. El bot anotará acá cada vez que un setup del Diario se active.</td></tr>`; return; }
  $("rows").innerHTML = ts.map(t => {
    const pnl = t.pnl_usd;
    const pnlCell = (pnl == null) ? "—" : `<span class="${pnl >= 0 ? "pos" : "neg"}">${signed(pnl)}</span>`;
    return `<tr>
      <td>${pairLabel(t.pair || t.symbol)}</td>
      <td><span class="pill ${t.dir}">${t.dir === "long" ? "LONG" : "SHORT"}</span></td>
      <td><span class="pill ${t.mode}">${t.mode}</span></td>
      <td>${fmt(t.qty, 4)}</td>
      <td>${fmt(t.entry_price)}</td>
      <td>${t.exit_price ? fmt(t.exit_price) : "—"}</td>
      <td>${t.leverage ? t.leverage + "x" : "—"}</td>
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
    alert("✅ Notificaciones activadas. Te llegarán solo las operaciones del bot.");
    if (b) { b.textContent = "🔔 Notificaciones activas"; b.disabled = true; }
  } catch (e) {
    alert("No se pudo activar: " + (e.message || e));
  }
}

async function load() {
  try {
    const r = await fetch("/m/bot/api/state", { cache: "no-store" });
    if (r.status === 401) { location.href = "/login"; return; }
    const data = await r.json();
    header(data); cards(data); position(data); watching(data); orders(data); trades(data);
  } catch (e) {
    $("rows").innerHTML = `<tr><td colspan="9" class="empty">No se pudo cargar: ${e}</td></tr>`;
  }
}

load();
setInterval(load, 12000);
