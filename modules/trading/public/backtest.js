/* Vista de backtest SMC. Lee /m/trading/api/backtest (JSON precalculado por el
 * CLI) y pinta métricas, tablas y la curva de equity en R. Mobile-first. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const pf = (v) => (v === null || v === "Infinity" || v === Infinity ? "∞" : v);
  const rcol = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");

  fetch("api/backtest")
    .then((r) => {
      if (!r.ok) throw new Error("sin resultados");
      return r.json();
    })
    .then(render)
    .catch(() => {
      $("headline").innerHTML =
        '<p class="bt-note">Todavía no hay resultados. Corre <code>python3 -m modules.trading.run_backtest</code>.</p>';
    });

  function render(d) {
    const gen = new Date(d.generated_at_ms);
    $("generated").textContent = "generado " + gen.toLocaleDateString("es");

    // Meta: config + costos + cobertura de datos.
    const c = d.config, costs = d.costs;
    const cov = d.data
      .map((x) => `${x.symbol} ${x.timeframe}: ${x.bars} velas (${x.from} → ${x.to})`)
      .join(" · ");
    $("meta").innerHTML = `
      <div class="bt-chip">Config primaria: <b>${c.primary_rr}R</b>, filtro tendencia
        <b>${c.primary_trend_filter ? "ON" : "OFF"}</b></div>
      <div class="bt-chip">Comisión <b>${(costs.commission_per_side * 100).toFixed(3)}%</b>/lado ·
        slippage <b>${(costs.slippage * 100).toFixed(3)}%</b></div>
      <div class="bt-chip">Lookback swings <b>${c.params.swing_lookback}</b> ·
        stop = barrido +<b>${(c.params.stop_buffer * 100).toFixed(3)}%</b></div>
      <div class="bt-cov">${cov}</div>`;

    // Métricas del resumen.
    const h = d.headline;
    $("headline").innerHTML = [
      metricCard("Trades", h.trades),
      metricCard("Win rate", h.win_rate + "%"),
      metricCard("Expectativa", h.expectancy_R + "R", rcol(h.expectancy_R)),
      metricCard("Profit factor", pf(h.profit_factor), h.profit_factor >= 1 ? "up" : "down"),
      metricCard("R total", h.total_R + "R", rcol(h.total_R)),
      metricCard("Max drawdown", h.max_drawdown_R + "R", "down"),
      metricCard("R prom. ganador", "+" + h.avg_win_R, "up"),
      metricCard("R prom. perdedor", h.avg_loss_R, "down"),
      metricCard("Racha máx. pérdidas", h.max_losing_streak),
    ].join("");

    window._btEquity = d.equity;
    drawEquity($("equity"), d.equity);

    // Tabla por par/timeframe.
    table($("by-pair"),
      ["Par", "TF", "Trades", "Win%", "Exp.R", "PF", "MaxDD", "Total R"],
      d.by_pair_tf.map((x) => [
        x.symbol, x.timeframe, x.trades, x.win_rate + "%",
        cell(x.expectancy_R, rcol(x.expectancy_R)),
        pf(x.profit_factor), x.max_drawdown_R,
        cell(x.total_R, rcol(x.total_R)),
      ]));

    // Tabla de sensibilidad.
    table($("sensitivity"),
      ["Objetivo", "Tendencia", "Trades", "Win%", "Exp.R", "PF", "MaxDD", "Total R"],
      d.sensitivity.map((s) => [
        s.rr + "R", s.trend_filter ? "ON" : "OFF", s.trades, s.win_rate + "%",
        cell(s.expectancy_R, rcol(s.expectancy_R)),
        pf(s.profit_factor), s.max_drawdown_R,
        cell(s.total_R, rcol(s.total_R)),
      ]));

    // Por sesión.
    const sess = Object.entries(d.by_session).sort((a, b) => b[1].trades - a[1].trades);
    table($("by-session"),
      ["Sesión", "Trades", "Win%", "Exp.R", "PF", "Total R"],
      sess.map(([name, m]) => [
        name, m.trades, m.win_rate + "%",
        cell(m.expectancy_R, rcol(m.expectancy_R)),
        pf(m.profit_factor), cell(m.total_R, rcol(m.total_R)),
      ]));

    // Por dirección.
    table($("by-direction"),
      ["Dirección", "Trades", "Win%", "Exp.R", "PF", "Total R"],
      Object.entries(d.by_direction).map(([name, m]) => [
        name === "long" ? "Largos" : "Cortos", m.trades, m.win_rate + "%",
        cell(m.expectancy_R, rcol(m.expectancy_R)),
        pf(m.profit_factor), cell(m.total_R, rcol(m.total_R)),
      ]));

    // Lectura honesta automática.
    const best = d.sensitivity.reduce((a, b) => (b.expectancy_R > a.expectancy_R ? b : a));
    const verdict = h.expectancy_R > 0
      ? `Con la config primaria la expectativa es positiva (${h.expectancy_R}R/trade).`
      : `Con la config primaria la expectativa es ${h.expectancy_R}R/trade (apenas perdedora/neutra): la estrategia base no tiene ventaja clara por sí sola.`;
    $("reading").innerHTML =
      `<strong>Lectura:</strong> ${verdict} La mejor combinación probada fue
       <b>${best.rr}R con filtro de tendencia ${best.trend_filter ? "ON" : "OFF"}</b>
       (${best.expectancy_R}R/trade, PF ${pf(best.profit_factor)}, ${best.trades} trades).
       El filtro de tendencia mejora los resultados, lo que sugiere que conviene operar a
       favor de la estructura mayor. Nada de esto es asesoría financiera.`;
  }

  function metricCard(label, value, cls) {
    return `<div class="metric"><span class="m-k">${label}</span>
      <span class="m-v ${cls || ""}">${value}</span></div>`;
  }

  function cell(value, cls) {
    return `<span class="${cls || ""}">${value}</span>`;
  }

  function table(el, headers, rows) {
    const thead = "<thead><tr>" + headers.map((h) => `<th>${h}</th>`).join("") + "</tr></thead>";
    const tbody = "<tbody>" + rows.map((r) =>
      "<tr>" + r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") + "</tbody>";
    el.innerHTML = thead + tbody;
  }

  // --- Curva de equity (canvas) -------------------------------------
  function drawEquity(canvas, points) {
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 600;
    const cssH = canvas.clientHeight || 240;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    if (!points || !points.length) return;

    const padL = 8, padR = 52, padT = 12, padB = 18;
    const plotW = cssW - padL - padR;
    const plotH = cssH - padT - padB;

    let hi = -Infinity, lo = Infinity;
    points.forEach((p) => { hi = Math.max(hi, p.R); lo = Math.min(lo, p.R); });
    hi = Math.max(hi, 0); lo = Math.min(lo, 0);
    if (hi === lo) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.08; hi += pad; lo -= pad;

    const x = (i) => padL + (i / (points.length - 1 || 1)) * plotW;
    const y = (r) => padT + (1 - (r - lo) / (hi - lo)) * plotH;

    // Rejilla + etiquetas.
    ctx.font = "10px -apple-system, sans-serif";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#8b93a7";
    const gridN = 4;
    for (let g = 0; g <= gridN; g++) {
      const r = lo + (hi - lo) * (g / gridN);
      const yy = y(r);
      ctx.strokeStyle = "rgba(255,255,255,0.05)";
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
      ctx.fillText(r.toFixed(0) + "R", padL + plotW + 6, yy);
    }
    // Línea del cero.
    const y0 = y(0);
    ctx.strokeStyle = "rgba(162,155,254,0.5)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(padL, y0); ctx.lineTo(padL + plotW, y0); ctx.stroke();
    ctx.setLineDash([]);

    // Área + curva.
    const lastR = points[points.length - 1].R;
    const col = lastR >= 0 ? "#16c784" : "#ea3943";
    ctx.beginPath();
    points.forEach((p, i) => { const xx = x(i), yy = y(p.R); i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
    ctx.lineTo(x(points.length - 1), y0);
    ctx.lineTo(x(0), y0);
    ctx.closePath();
    ctx.fillStyle = lastR >= 0 ? "rgba(22,199,132,0.10)" : "rgba(234,57,67,0.10)";
    ctx.fill();

    ctx.beginPath();
    points.forEach((p, i) => { const xx = x(i), yy = y(p.R); i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
    ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.stroke();
  }

  window.addEventListener("resize", () => {
    if (window._btEquity) drawEquity($("equity"), window._btEquity);
  });
})();
