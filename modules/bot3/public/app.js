const $ = (id) => document.getElementById(id);
const API = "/m/bot3/api";

const fmt = (v, d = 2) => v == null || !Number.isFinite(Number(v)) ? "—"
  : Number(v).toLocaleString("es-CL", { maximumFractionDigits: d, minimumFractionDigits: d });
const fecha = (ms) => ms == null ? "—" : new Date(Number(ms)).toLocaleString("es-CL",
  { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

async function loadState() {
  const st = await fetch(`${API}/state`).then((r) => r.json());
  const fill = (sel, items) => {
    sel.innerHTML = "";
    items.forEach((v) => { const o = document.createElement("option"); o.value = v; o.textContent = v; sel.appendChild(o); });
  };
  fill($("symbol"), st.pairs);
  fill($("tf"), st.timeframes);
  $("symbol").addEventListener("change", loadBook);
  $("tf").addEventListener("change", loadBook);
  await loadBook();
}

function metric(label, value, cls = "") {
  return `<div class="metric"><span>${label}</span><strong class="${cls}">${value}</strong></div>`;
}

async function loadBook() {
  const symbol = $("symbol").value, tf = $("tf").value;
  $("book-sub").textContent = "Cargando…";
  const r = await fetch(`${API}/book?symbol=${symbol}&tf=${tf}`);
  if (!r.ok) { $("book-sub").textContent = "Error cargando el libro"; return; }
  const d = await r.json();
  const s = d.summary || {};
  const sumCls = (s.sum_r || 0) > 0 ? "win" : (s.sum_r || 0) < 0 ? "loss" : "";
  $("metrics").innerHTML = [
    metric("Cerradas", s.cerradas ?? "—"),
    metric("Win rate", s.win_rate != null ? s.win_rate + "%" : "—"),
    metric("R acumulado", fmt(s.sum_r), sumCls),
    metric("R promedio", fmt(s.avg_r, 3), (s.avg_r || 0) > 0 ? "win" : (s.avg_r || 0) < 0 ? "loss" : ""),
    metric("Profit factor", fmt(s.profit_factor)),
    metric("Abierta", d.abierta ? (d.abierta.dir === "long" ? "▲ largo" : "▼ corto") : "no"),
  ].join("");
  $("book-sub").textContent = `${symbol} ${tf} · rector ${d.rector_tf || "—"} · ${d.bars} velas · al ${fecha(d.as_of)}`;
  const tb = $("trades");
  tb.innerHTML = "";
  (d.trades || []).slice().reverse().forEach((t) => {
    const tr = document.createElement("tr");
    const estado = t.estado === "target" ? '<span class="win">✓ target</span>'
      : t.estado === "stop" ? '<span class="loss">✗ stop</span>' : "⏳ abierta";
    tr.innerHTML = `<td>${fecha(t.t_entrada)}</td>`
      + `<td class="${t.dir}">${t.dir === "long" ? "▲ largo" : "▼ corto"}</td>`
      + `<td>${t.zona.toUpperCase()} ${t.zona_tf === "rector" ? "· rector" : ""}</td>`
      + `<td>${fmt(t.entry)}</td><td>${fmt(t.sl)}</td><td>${fmt(t.tp)}</td>`
      + `<td>${fmt(t.net_rr, 1)}</td><td>${estado}</td>`
      + `<td class="${(t.result_r || 0) > 0 ? "win" : (t.result_r || 0) < 0 ? "loss" : ""}">${t.result_r != null ? fmt(t.result_r) : "—"}</td>`;
    tb.appendChild(tr);
  });
  if (!(d.trades || []).length) tb.innerHTML = '<tr><td colspan="9">Sin entradas confirmadas en la ventana.</td></tr>';
  const rej = $("rejections");
  rej.innerHTML = "";
  const entries = Object.entries(d.descartadas || {}).sort((a, b) => b[1] - a[1]);
  entries.forEach(([k, v]) => {
    const div = document.createElement("div");
    div.className = "reject";
    div.innerHTML = `<span>${k}</span><strong>${v}</strong>`;
    rej.appendChild(div);
  });
  if (!entries.length) rej.innerHTML = '<div class="reject"><span>sin descartes registrados</span></div>';
}

loadState();
