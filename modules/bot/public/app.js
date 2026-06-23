// NexUX BOT — panel del libro de operación real. Lee /m/bot/api/trades y pinta.
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) => (n === null || n === undefined) ? "—" : Number(n).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d });
const pairLabel = (p) => (p || "").replace("_USDT", "").replace("USDT", "") || p;

function modeBadge(data) {
  const el = $("mode");
  if (!data.active) { el.className = "mode off"; el.textContent = "Inerte (sin llaves)"; return; }
  if (data.live) { el.className = "mode live"; el.textContent = "● En vivo (real)"; }
  else { el.className = "mode dry"; el.textContent = "Dry-run (simulado)"; }
}

function cards(s, data) {
  const pnlCls = (s.pnl_usd || 0) >= 0 ? "green" : "red";
  const cards = [
    { k: "Operaciones", v: s.total ?? 0 },
    { k: "Abiertas", v: s.abiertas ?? 0 },
    { k: "Cerradas", v: s.cerradas ?? 0 },
    { k: "Win rate", v: s.win_rate === null || s.win_rate === undefined ? "—" : fmt(s.win_rate, 0) + "%" },
    { k: "P&L real (USD)", v: fmt(s.pnl_usd), cls: pnlCls },
    { k: "Comisiones (USD)", v: fmt(s.fees_usd) },
  ];
  $("cards").innerHTML = cards.map(c =>
    `<div class="card"><div class="k">${c.k}</div><div class="v ${c.cls || ""}">${c.v}</div></div>`
  ).join("");
}

function rows(trades) {
  if (!trades.length) { $("rows").innerHTML = `<tr><td colspan="9" class="empty">Sin operaciones todavía. El bot anotará acá cada vez que un setup del Diario se active.</td></tr>`; return; }
  $("rows").innerHTML = trades.map(t => {
    const pnl = t.pnl_usd;
    const pnlCell = pnl === null || pnl === undefined ? "—" : `<span class="${pnl >= 0 ? "pos" : "neg"}">${pnl >= 0 ? "+" : ""}${fmt(pnl)}</span>`;
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

async function load() {
  try {
    const r = await fetch("/m/bot/api/trades", { cache: "no-store" });
    const data = await r.json();
    modeBadge(data);
    cards(data.summary || {}, data);
    rows(data.trades || []);
  } catch (e) {
    $("rows").innerHTML = `<tr><td colspan="9" class="empty">No se pudo cargar el libro: ${e}</td></tr>`;
  }
}

load();
setInterval(load, 15000);  // refresco cada 15s
