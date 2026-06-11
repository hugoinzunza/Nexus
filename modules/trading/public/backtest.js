/* Vista del laboratorio de estrategias (Fase 2). Lee /m/trading/api/backtest
 * (JSON precalculado) y muestra el ranking por out-of-sample, el veredicto
 * honesto y los detalles. Mobile-first. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const pf = (v) => (v === null || v === Infinity || v === "Infinity" ? "∞" : v);
  const rcol = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
  const rc = (v) => `<span class="${rcol(v)}">${v}</span>`;
  const pfc = (v) => `<span class="${v >= 1 ? "up" : "down"}">${pf(v)}</span>`;

  fetch("api/backtest")
    .then((r) => { if (!r.ok) throw new Error("sin resultados"); return r.json(); })
    .then(render)
    .catch(() => {
      $("verdict").innerHTML =
        '<p class="bt-note">Todavía no hay resultados. Corre <code>python3 -m modules.trading.run_backtest</code>.</p>';
    });

  function render(d) {
    $("generated").textContent = "generado " + new Date(d.generated_at_ms).toLocaleDateString("es");

    const v = d.verdict;
    $("verdict").className = "verdict " + (v.any_robust ? "ok" : "warn");
    $("verdict").innerHTML =
      `<div class="v-tag">${v.any_robust ? "✅ Hay edge robusto fuera de muestra" : "⚠️ Sin edge robusto fuera de muestra"}</div>
       <p>${v.text}</p>`;

    const c = d.costs;
    $("meta").innerHTML = `
      <div class="bt-chip"><b>${d.ranking.length}</b> estrategias · <b>${d.pairs.length}</b> pares ·
        <b>${d.timeframes.join("/")}</b></div>
      <div class="bt-chip">Corte: in-sample hasta <b>${d.split.is_until}</b> · OOS desde ahí</div>
      <div class="bt-chip">Comisión <b>${(c.commission_per_side * 100).toFixed(3)}%</b>/lado ·
        slippage <b>${(c.slippage * 100).toFixed(3)}%</b></div>
      <div class="bt-cov">${d.data.length} datasets · ${d.data[0].from} → ${d.data[0].to}</div>`;

    $("rule").innerHTML = `<strong>Umbral de robustez:</strong> ${d.robustness_rule.rule}.`;

    // Ranking.
    table($("ranking"),
      ["#", "Estrategia", "Familia", "IS exp", "OOS exp", "OOS PF", "OOS n", "WFO exp", "Robusta"],
      d.ranking.map((s, i) => [
        i + 1, s.name, s.family,
        rc(s.in_sample.expectancy_R), rc(s.out_sample.expectancy_R),
        pfc(s.out_sample.profit_factor), sampleCell(s.out_sample.trades),
        rc(s.wfo_oos.expectancy_R), badge(s),
      ]), d.ranking.map((s, i) => (s.robust ? i : -1)).filter((i) => i >= 0));

    // Equity de la top.
    if (d.ranking.length) {
      const top = d.ranking[0];
      $("equity-label").innerHTML =
        `<strong>${top.name}</strong> · ${top.label} · ${d.equity_best.length} trades OOS`;
    }
    window._btEquity = d.equity_best;
    drawEquity($("equity"), d.equity_best);

    // Detalle por estrategia.
    table($("detail"),
      ["Estrategia", "Mejor config", "Muestra", "Trades", "Win%", "Exp.R", "PF", "DD(R)"],
      d.ranking.flatMap((s) => [
        [s.name, s.label, "IS", s.in_sample.trades, s.in_sample.win_rate + "%",
          rc(s.in_sample.expectancy_R), pfc(s.in_sample.profit_factor), s.in_sample.max_drawdown_R],
        ["", "", "OOS", s.out_sample.trades, s.out_sample.win_rate + "%",
          rc(s.out_sample.expectancy_R), pfc(s.out_sample.profit_factor), s.out_sample.max_drawdown_R],
      ]));

    // Mejores combos.
    table($("combos"),
      ["Estrategia", "Par/TF", "Config", "OOS exp", "OOS PF", "OOS n"],
      d.best_combos.map((b) => [
        b.strategy, `${b.symbol} ${b.timeframe}`, b.label,
        rc(b.out_sample.expectancy_R), pfc(b.out_sample.profit_factor),
        sampleCell(b.out_sample.trades),
      ]));
  }

  function badge(s) {
    if (s.robust) return '<span class="up">✅ sí</span>';
    if (!s.confident) return '<span class="down">⚠ pocos</span>';
    return '<span class="muted">no</span>';
  }
  function sampleCell(n) {
    return n >= 30 ? `${n}` : `<span class="down">${n} ⚠</span>`;
  }

  function table(el, headers, rows, highlight) {
    const thead = "<thead><tr>" + headers.map((h) => `<th>${h}</th>`).join("") + "</tr></thead>";
    const tbody = "<tbody>" + rows.map((r, ri) =>
      `<tr class="${highlight && highlight.includes(ri) ? "hl" : ""}">` +
      r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") + "</tbody>";
    el.innerHTML = thead + tbody;
  }

  // --- Curva de equity OOS (canvas) ---------------------------------
  function drawEquity(canvas, points) {
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 600;
    const cssH = canvas.clientHeight || 240;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    if (!points || !points.length) {
      ctx.fillStyle = "#8b93a7"; ctx.font = "13px -apple-system, sans-serif";
      ctx.fillText("Sin trades fuera de muestra.", 12, cssH / 2);
      return;
    }
    const padL = 8, padR = 52, padT = 12, padB = 18;
    const plotW = cssW - padL - padR, plotH = cssH - padT - padB;
    let hi = -Infinity, lo = Infinity;
    points.forEach((p) => { hi = Math.max(hi, p.R); lo = Math.min(lo, p.R); });
    hi = Math.max(hi, 0); lo = Math.min(lo, 0);
    if (hi === lo) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.08; hi += pad; lo -= pad;
    const x = (i) => padL + (i / (points.length - 1 || 1)) * plotW;
    const y = (r) => padT + (1 - (r - lo) / (hi - lo)) * plotH;

    ctx.font = "10px -apple-system, sans-serif"; ctx.textBaseline = "middle";
    for (let g = 0; g <= 4; g++) {
      const r = lo + (hi - lo) * (g / 4), yy = y(r);
      ctx.strokeStyle = "rgba(255,255,255,0.05)";
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
      ctx.fillStyle = "#8b93a7"; ctx.fillText(r.toFixed(0) + "R", padL + plotW + 6, yy);
    }
    const y0 = y(0);
    ctx.strokeStyle = "rgba(162,155,254,0.5)"; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(padL, y0); ctx.lineTo(padL + plotW, y0); ctx.stroke();
    ctx.setLineDash([]);

    const lastR = points[points.length - 1].R;
    const col = lastR >= 0 ? "#16c784" : "#ea3943";
    ctx.beginPath();
    points.forEach((p, i) => { const xx = x(i), yy = y(p.R); i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
    ctx.lineTo(x(points.length - 1), y0); ctx.lineTo(x(0), y0); ctx.closePath();
    ctx.fillStyle = lastR >= 0 ? "rgba(22,199,132,0.10)" : "rgba(234,57,67,0.10)"; ctx.fill();
    ctx.beginPath();
    points.forEach((p, i) => { const xx = x(i), yy = y(p.R); i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
    ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.stroke();
  }

  window.addEventListener("resize", () => {
    if (window._btEquity) drawEquity($("equity"), window._btEquity);
  });
})();
