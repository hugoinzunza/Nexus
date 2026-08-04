(function () {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const esc = (value) => String(value ?? "—").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
  const num = (value, digits = 2) => Number.isFinite(value)
    ? new Intl.NumberFormat("es-CL", { maximumFractionDigits: digits }).format(value) : "—";
  const when = (ms) => Number.isFinite(ms)
    ? new Date(ms).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" }) : "Sin datos";
  const age = (seconds) => {
    if (!Number.isFinite(seconds)) return "Sin lectura";
    if (seconds < 60) return `hace ${Math.round(seconds)} s`;
    if (seconds < 3600) return `hace ${Math.round(seconds / 60)} min`;
    if (seconds < 86400) return `hace ${Math.round(seconds / 3600)} h`;
    return `hace ${Math.round(seconds / 86400)} d`;
  };
  const labels = { fresh: "al día", stale: "atrasado", missing: "sin datos", degraded: "con errores" };

  function renderObservers(observers) {
    const entries = [
      ["shadow_exit", "Protección del runner", "Comparación original vs stop protegido después de 3R"],
      ["cost_telemetry", "Costos de ejecución", "Spread, comisión y slippage realmente observados"],
    ];
    $("#observers").innerHTML = entries.map(([key, title, subtitle]) => {
      const row = observers[key] || {};
      const secondary = key === "shadow_exit"
        ? `<div><span>Cerradas pareadas</span><strong>${esc(row.paired_closed)}</strong></div><div><span>Alcanzaron 3R</span><strong>${esc(row.reached_3r)}</strong></div>`
        : `<div><span>Entradas live elegibles</span><strong>${esc(row.coverage?.entries_with_activation_reference || 0)}</strong></div><div><span>Comisiones confirmadas</span><strong>${esc(row.coverage?.closed_with_confirmed_fees || 0)}</strong></div>`;
      return `<article class="observer">
        <div class="observer-top"><div><span class="observer-id">${esc(row.hypothesis_id)}</span><h3>${title}</h3><small>${subtitle}</small></div><span class="badge ${esc(row.status)}">${esc(labels[row.status] || row.status)}</span></div>
        <div class="observer-metrics"><div><span>Observaciones</span><strong>${esc(row.records)}</strong></div>${secondary}</div>
        <small>${age(row.age_seconds)}</small>
      </article>`;
    }).join("");
  }

  function evidence(study) {
    const parts = [];
    if (Number.isFinite(study.n)) parts.push(`n ${num(study.n, 0)}`);
    if (Number.isFinite(study.avg_r)) parts.push(`avg ${num(study.avg_r, 3)}R`);
    if (Number.isFinite(study.avg_pct)) parts.push(`avg ${study.avg_pct >= 0 ? "+" : ""}${num(study.avg_pct, 2)}%`);
    if (Number.isFinite(study.profit_factor)) parts.push(`PF ${num(study.profit_factor, 2)}`);
    if (Number.isFinite(study.positive_rate)) parts.push(`${num(study.positive_rate * 100, 0)}% positivos`);
    if (Number.isFinite(study.baseline_rate)) parts.push(`base ${num(study.baseline_rate * 100, 0)}%`);
    if (Number.isFinite(study.delta_avg_r)) parts.push(`Δ ${study.delta_avg_r >= 0 ? "+" : ""}${num(study.delta_avg_r, 3)}R`);
    if (Array.isArray(study.ci95)) parts.push(`IC95 [${num(study.ci95[0], 3)}; ${num(study.ci95[1], 3)}]`);
    if (Number.isFinite(study.p_value)) parts.push(`p ${num(study.p_value, 2)}`);
    if (Number.isFinite(study.paired_closed)) parts.push(`${study.paired_closed} cerradas`);
    if (Number.isFinite(study.holm_rejections)) parts.push(`${study.holm_rejections} rechazos Holm`);
    return parts.join(" · ") || "Pendiente de datos";
  }

  function renderStudies(studies) {
    const stateLabels = { closed: "cerrado", collecting: "recolectando", candidate: "candidato", exploratory: "exploratorio" };
    $("#study-rows").innerHTML = studies.map((study) => `<tr>
      <td><strong>${esc(study.title)}</strong><small>${esc(study.id)}</small></td>
      <td>${esc(study.family)}</td>
      <td><span class="badge ${esc(study.state)}">${esc(stateLabels[study.state] || study.state)}</span></td>
      <td class="metric">${esc(evidence(study))}</td>
      <td>${esc(study.verdict)}</td>
      <td class="blocked">Bloqueada</td>
    </tr>`).join("");
  }

  function renderProtocol(protocol) {
    const promotion = protocol.promotion_requires_all || {};
    const cards = [
      ["Operaciones pareadas", protocol.minimum_paired_closed_operations],
      ["Operaciones que alcanzan 3R", protocol.minimum_operations_reaching_3r],
      ["Semanas mínimas", protocol.minimum_calendar_weeks],
      ["Mejora PF absoluta", `+${num(promotion.absolute_profit_factor_improvement, 2)}`],
      ["Reducción drawdown", `${num((promotion.relative_max_drawdown_reduction || 0) * 100, 0)}%`],
    ];
    $("#protocol-grid").innerHTML = cards.map(([label, value]) => `<div class="metric-card"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
    $("#terminal-rule").textContent = protocol.terminal_rule || "El protocolo todavía no está disponible.";
  }

  function renderSources(sources) {
    const names = { setups: "Diario de setups", main_ledger: "Libro principal", testnet_ledger: "Libro Testnet" };
    $("#source-list").innerHTML = Object.entries(sources).map(([key, source]) => `<div class="source-row">
      <strong>${esc(names[key] || key)}</strong><span class="badge ${esc(source.status)}">${esc(labels[source.status] || source.status)}</span>
      <code>${esc(key)}</code><time>${esc(when(source.updated_at_ms))}</time>
    </div>`).join("");
  }

  function render(data) {
    renderObservers(data.observers || {});
    renderStudies(data.studies || []);
    renderProtocol(data.protocol || {});
    renderSources(data.sources || {});
    const states = Object.values(data.observers || {}).map((item) => item.status);
    const status = $(".head-status");
    const healthy = states.length > 0 && states.every((item) => item === "fresh");
    const missing = states.some((item) => item === "missing" || item === "degraded");
    status.classList.toggle("ready", healthy);
    status.classList.toggle("bad", missing);
    $("#overall").textContent = healthy ? "Observadores al día" : missing ? "Observadores requieren atención" : "Datos atrasados";
    $("#updated").textContent = `Vista actualizada ${when(data.generated_at_ms)}`;
    $("#clock").textContent = when(data.generated_at_ms);
  }

  document.querySelectorAll(".tabs button").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button, .tab-panel").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    document.getElementById(button.dataset.tab).classList.add("active");
  }));

  fetch("api/state", { cache: "no-store" })
    .then((response) => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
    .then(render)
    .catch(() => {
      $("#overall").textContent = "Laboratorio no disponible";
      $(".head-status").classList.add("bad");
    });
}());
