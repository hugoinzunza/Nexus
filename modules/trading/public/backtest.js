/* Vista de backtest SMC (Fase 1.5). Lee /m/trading/api/backtest (JSON
 * precalculado) y muestra la validación in-sample vs out-of-sample, el
 * walk-forward y el veredicto honesto. Mobile-first. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const pf = (v) => (v === null || v === Infinity || v === "Infinity" ? "∞" : v);
  const rcol = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
  const trendName = { none: "Ninguno", ema: "EMA", structure: "Estructura HTF" };

  fetch("api/backtest")
    .then((r) => { if (!r.ok) throw new Error("sin resultados"); return r.json(); })
    .then(render)
    .catch(() => {
      $("verdict").innerHTML =
        '<p class="bt-note">Todavía no hay resultados. Corre <code>python3 -m modules.trading.run_backtest</code>.</p>';
    });

  function render(d) {
    $("generated").textContent = "generado " + new Date(d.generated_at_ms).toLocaleDateString("es");

    // Veredicto.
    const v = d.verdict;
    $("verdict").className = "verdict " + (v.robust ? "ok" : "warn");
    $("verdict").innerHTML =
      `<div class="v-tag">${v.robust ? "✅ Edge robusto fuera de muestra" : "⚠️ Edge NO robusto fuera de muestra"}</div>
       <p>${v.text}</p>`;

    // Meta.
    const c = d.costs;
    const cov = d.data.map((x) => `${x.symbol} ${x.timeframe}: ${x.bars} velas`).join(" · ");
    $("meta").innerHTML = `
      <div class="bt-chip">Grilla probada: <b>${d.grid_size}</b> configs</div>
      <div class="bt-chip">Corte: in-sample hasta <b>${d.split.is_until}</b> · OOS desde ahí</div>
      <div class="bt-chip">Comisión <b>${(c.commission_per_side * 100).toFixed(3)}%</b>/lado ·
        slippage <b>${(c.slippage * 100).toFixed(3)}%</b></div>
      <div class="bt-cov">${cov} · ${d.data[0].from} → ${d.data[0].to}</div>`;

    // Mejor config: IN vs OUT vs FULL.
    const b = d.best_overall;
    $("best-label").innerHTML = `<strong>Config:</strong> ${b.label}`;
    metricCompare($("inout"), [
      ["", "In-sample", "Out-of-sample", "Full"],
      ["Trades", b.in_sample.trades, b.out_sample.trades, b.full.trades],
      ["Win rate", b.in_sample.win_rate + "%", b.out_sample.win_rate + "%", b.full.win_rate + "%"],
      ["Expectativa (R)", rc(b.in_sample.expectancy_R), rc(b.out_sample.expectancy_R), rc(b.full.expectancy_R)],
      ["Profit factor", pfc(b.in_sample.profit_factor), pfc(b.out_sample.profit_factor), pfc(b.full.profit_factor)],
      ["Max drawdown (R)", b.in_sample.max_drawdown_R, b.out_sample.max_drawdown_R, b.full.max_drawdown_R],
      ["Total R", rc(b.in_sample.total_R), rc(b.out_sample.total_R), rc(b.full.total_R)],
    ]);

    window._btEquity = d.equity_oos;
    drawEquity($("equity"), d.equity_oos);

    // Walk-forward.
    const wfoRows = d.walkforward.folds.map((f) => [
      `${f.test_from}→${f.test_to}`, f.label.replace(/·/g, "·"),
      f.out_sample.trades, f.out_sample.win_rate + "%",
      rc(f.out_sample.expectancy_R), pfc(f.out_sample.profit_factor), rc(f.out_sample.total_R),
    ]);
    const agg = d.walkforward.oos_aggregate;
    wfoRows.push(["OOS agregado", "—", agg.trades, agg.win_rate + "%",
      rc(agg.expectancy_R), pfc(agg.profit_factor), rc(agg.total_R)]);
    table($("wfo"), ["Ventana OOS", "Config", "Trades", "Win%", "Exp.R", "PF", "Total R"], wfoRows, [wfoRows.length - 1]);

    // Tendencia.
    table($("trend"),
      ["Filtro", "Muestra", "Trades", "Win%", "Exp.R", "PF", "Total R"],
      d.trend_comparison.flatMap((t) => [
        [trendName[t.mode], "Full", t.full.trades, t.full.win_rate + "%",
          rc(t.full.expectancy_R), pfc(t.full.profit_factor), rc(t.full.total_R)],
        ["", "OOS", t.out_sample.trades, t.out_sample.win_rate + "%",
          rc(t.out_sample.expectancy_R), pfc(t.out_sample.profit_factor), rc(t.out_sample.total_R)],
      ]));

    // Ablación.
    $("ablation-base").innerHTML = `<strong>Base:</strong> ${d.ablation.base.label}`;
    const ab = d.ablation;
    const abRows = [["Base", ab.base.metrics.trades, ab.base.metrics.win_rate + "%",
      rc(ab.base.metrics.expectancy_R), pfc(ab.base.metrics.profit_factor), rc(ab.base.metrics.total_R)]];
    ab.steps.forEach((s) => abRows.push([s.name, s.metrics.trades, s.metrics.win_rate + "%",
      rc(s.metrics.expectancy_R), pfc(s.metrics.profit_factor), rc(s.metrics.total_R)]));
    table($("ablation"), ["Variante", "Trades", "Win%", "Exp.R", "PF", "Total R"], abRows, [0]);

    // Por par/timeframe.
    table($("per-dataset"),
      ["Par/TF", "Muestra", "Config", "Trades", "Win%", "Exp.R", "PF", "Total R"],
      d.per_dataset.flatMap((x) => [
        [`${x.symbol} ${x.timeframe}`, "IS", x.label, x.in_sample.trades, x.in_sample.win_rate + "%",
          rc(x.in_sample.expectancy_R), pfc(x.in_sample.profit_factor), rc(x.in_sample.total_R)],
        ["", "OOS", "", x.out_sample.trades, x.out_sample.win_rate + "%",
          rc(x.out_sample.expectancy_R), pfc(x.out_sample.profit_factor), rc(x.out_sample.total_R)],
      ]));
  }

  // Celda coloreada por signo (R).
  function rc(v) { return `<span class="${rcol(v)}">${v}</span>`; }
  function pfc(v) { const n = pf(v); return `<span class="${v >= 1 ? "up" : "down"}">${n}</span>`; }

  function metricCompare(el, rows) {
    const head = "<thead><tr>" + rows[0].map((h) => `<th>${h}</th>`).join("") + "</tr></thead>";
    const body = "<tbody>" + rows.slice(1).map((r) =>
      "<tr>" + r.map((c, i) => `<td>${i === 0 ? "<b>" + c + "</b>" : c}</td>`).join("") + "</tr>").join("") + "</tbody>";
    el.innerHTML = head + body;
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
      ctx.fillText("Sin trades fuera de muestra para esta config.", 12, cssH / 2);
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
