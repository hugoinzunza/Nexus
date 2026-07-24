const $ = (id) => document.getElementById(id);
const num = (v, d = 2) => v == null ? "—" : Number(v).toLocaleString("es-CL", {maximumFractionDigits:d});
const signed = (v, suffix = "") => v == null ? "—" : `${v >= 0 ? "+" : ""}${num(v)}${suffix}`;
let state;

function metric(label, value, cls = "") { return `<div class="metric"><span>${label}</span><b class="${cls}">${value}</b></div>`; }
function renderBook(book) {
  const m = book.metrics, cls = (m.pnl_usdt || 0) >= 0 ? "up" : "down";
  return `<article class="book" data-book="${book.id}"><header><h3>${book.label}</h3><span class="count">${m.signals} señales</span></header><div class="metrics">${metric("Equity", `${num(m.equity_usdt)} USDT`, cls)}${metric("PnL", signed(m.pnl_usdt, " USDT"), cls)}${metric("avgR", signed(m.avg_r, "R"), (m.avg_r || 0) >= 0 ? "up" : "down")}${metric("PF", num(m.profit_factor, 3))}${metric("Win rate", m.win_rate_pct == null ? "—" : `${num(m.win_rate_pct,1)}%`)}${metric("Resueltos", m.resolved)}</div></article>`;
}
function renderTrades(id) {
  const book = state.books.find((item) => item.id === id), rows = book ? book.trades : [];
  $("trade-rows").innerHTML = rows.length ? rows.map((t) => `<tr><td>${new Date(t.date).toLocaleString("es-CL")}</td><td class="tag ${t.direction}">${t.direction.toUpperCase()}</td><td>${num(t.entry_plan_equal_cash,4)}</td><td>${num(t.entry_confirmed,4)}</td><td>${num(t.tp1_r_plan,2)}R</td><td>${t.status}</td><td class="${(t.pnl_r_net || 0) >= 0 ? "up" : "down"}">${t.pnl_r_net == null ? "—" : signed(t.pnl_r_net,"R")}</td></tr>`).join("") : `<tr><td colspan="7" class="empty">Esperando la primera señal forward</td></tr>`;
  document.querySelectorAll(".book").forEach((el) => el.classList.toggle("active", el.dataset.book === id));
}
function render(data) {
  state = data;
  if (data.waiting) { $("updated").textContent = "Esperando snapshot"; return; }
  $("updated").textContent = `Telegram ${data.source_exported_at ? new Date(data.source_exported_at).toLocaleString("es-CL") : "sin fecha"} · snapshot hace ${num(data.age_seconds,0)} s`;
  const [year, month, day] = data.forward_start.slice(0, 10).split("-");
  $("forward-start").textContent = `Forward desde ${day}-${month}-${year}`;
  $("books").innerHTML = data.books.map(renderBook).join("");
  const r = data.reference;
  $("reference").innerHTML = metric("Trades", r.resolved) + metric("Win rate", r.win_rate_pct == null ? "—" : `${num(r.win_rate_pct,1)}%`) + metric("avgR", signed(r.avg_r,"R"), (r.avg_r || 0) >= 0 ? "up" : "down") + metric("PF", num(r.profit_factor,3)) + metric("Total", signed(r.total_r,"R"), (r.total_r || 0) >= 0 ? "up" : "down");
  $("book-select").innerHTML = data.books.map((b) => `<option value="${b.id}">${b.label}</option>`).join("");
  renderTrades(data.books[0].id);
}
$("book-select").addEventListener("change", (event) => renderTrades(event.target.value));
fetch("api/state").then((r) => r.json()).then(render).catch(() => { $("updated").textContent = "Error cargando snapshot"; });
