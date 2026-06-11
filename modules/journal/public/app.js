/* Diario · Binance (solo lectura). Lee el estado de las credenciales y, si están,
 * arma el panel de estadísticas. Mobile-first, sin librerías. */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const pf = (v) => (v === null || v === Infinity || v === "Infinity" ? "∞" : v);
  const col = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
  const usd = (v) => (v == null ? "—" : (v >= 0 ? "+" : "") + v.toLocaleString("es", { maximumFractionDigits: 2 }));
  const setDot = (s) => { $("dot").className = "dot " + s; };

  let lastData = null;

  function setStatus(txt, dot) { $("status-text").textContent = txt; if (dot) setDot(dot); }

  function load(force) {
    setStatus("cargando…");
    fetch("api/status").then((r) => r.json()).then((st) => {
      if (!st.configured) {
        $("connect").hidden = false; $("panel").hidden = true; $("error").hidden = true;
        setStatus("sin conectar", "bad");
        return;
      }
      fetch("api/stats" + (force ? "?refresh=1" : "")).then((r) => r.json()).then(render);
    }).catch(() => setStatus("error de red", "bad"));
  }

  function render(d) {
    if (!d.configured) { $("connect").hidden = false; $("panel").hidden = true; setStatus("sin conectar", "bad"); return; }
    if (d.error) {
      $("error").hidden = false; $("error-msg").textContent = d.error;
      $("panel").hidden = true; setStatus("error", "bad"); return;
    }
    lastData = d;
    $("connect").hidden = true; $("error").hidden = true; $("panel").hidden = false;
    setStatus("conectado", "ok");
    $("updated").textContent = "actualizado " + new Date(d.generated_at_ms).toLocaleTimeString("es") +
      " · " + d.lookback_days + " días";

    const fut = d.futures || {};
    if (fut.ok) {
      const s = fut.summary;
      $("summary").innerHTML = [
        card("PnL neto (USDT)", usd(s.net_pnl), col(s.net_pnl)),
        card("Trades", s.trades),
        card("Win rate", s.win_rate + "%"),
        card("Profit factor", pf(s.profit_factor), s.profit_factor >= 1 ? "up" : "down"),
        card("Ganancia prom.", usd(s.avg_win), "up"),
        card("Pérdida prom.", usd(s.avg_loss), "down"),
        card("Mejor trade", usd(s.best), "up"),
        card("Peor trade", usd(s.worst), "down"),
        card("Racha ganadora", s.max_win_streak),
        card("Racha perdedora", s.max_loss_streak),
        card("Comisiones", usd(s.gross_commission), "down"),
        card("Funding", usd(s.gross_funding), col(s.gross_funding)),
      ].join("");
      window._eq = fut.equity;
      drawEquity($("equity"), fut.equity);

      // Posiciones abiertas.
      const pos = fut.open_positions || [];
      table($("positions"),
        ["Símbolo", "Lado", "Tamaño", "Entrada", "Mark", "PnL no realizado", "Apal."],
        pos.length ? pos.map((p) => [p.symbol, sideTag(p.side), p.size, p.entry, p.mark,
          rc(p.unrealized), (p.leverage || "") + "x"]) : [["Sin posiciones abiertas", "", "", "", "", "", ""]]);

      tbl("by-pair", ["Par", "Trades", "Win%", "PnL"], fut.by_pair, true);
      tbl("by-session", ["Sesión", "Trades", "Win%", "PnL"], fut.by_session);
      tbl("by-weekday", ["Día", "Trades", "Win%", "PnL"], fut.by_weekday);
      drawHours($("hours"), fut.by_hour);
    } else {
      $("summary").innerHTML = `<p class="bt-note">Futuros no disponibles: ${fut.error || "sin datos"}.</p>`;
    }

    // Spot.
    const sp = d.spot || {};
    if (sp.ok) {
      $("spot-total").innerHTML = `<strong>Valor total aprox:</strong> ${usd(sp.total_value)} USDT`;
      table($("spot"), ["Activo", "Cantidad", "Valor aprox (USDT)"],
        (sp.holdings || []).length ? sp.holdings.map((h) => [h.asset,
          h.qty.toLocaleString("es", { maximumFractionDigits: 8 }),
          h.value == null ? "—" : h.value.toLocaleString("es", { maximumFractionDigits: 2 })])
          : [["Sin holdings", "", ""]]);
    } else {
      $("spot-total").innerHTML = `<span class="bt-note">Spot no disponible: ${sp.error || "sin datos"}.</span>`;
      $("spot").innerHTML = "";
    }
  }

  function card(k, v, cls) {
    return `<div class="metric"><span class="m-k">${k}</span><span class="m-v ${cls || ""}">${v}</span></div>`;
  }
  function rc(v) { return `<span class="${col(v)}">${usd(v)}</span>`; }
  function sideTag(s) { return `<span class="${s === "LONG" ? "up" : "down"}">${s}</span>`; }

  function tbl(id, headers, groups, sortByPnl) {
    let rows = Object.entries(groups || {}).map(([g, m]) => [g, m.trades, m.win_rate + "%", rc(m.net_pnl)]);
    if (sortByPnl) rows.sort((a, b) => parseFloat((groups[b[0]] || {}).net_pnl) - parseFloat((groups[a[0]] || {}).net_pnl));
    if (!rows.length) rows = [["Sin datos", "", "", ""]];
    table($(id), headers, rows);
  }

  function table(el, headers, rows) {
    el.innerHTML = "<thead><tr>" + headers.map((h) => `<th>${h}</th>`).join("") + "</tr></thead>" +
      "<tbody>" + rows.map((r) => "<tr>" + r.map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") + "</tbody>";
  }

  // --- Curva de equity ----------------------------------------------
  function drawEquity(canvas, points) {
    const ctx = prep(canvas);
    const cssW = canvas.clientWidth || 600, cssH = canvas.clientHeight || 240;
    if (!points || !points.length) { empty(ctx, cssH); return; }
    const padL = 8, padR = 60, padT = 12, padB = 18;
    const plotW = cssW - padL - padR, plotH = cssH - padT - padB;
    let hi = -Infinity, lo = Infinity;
    points.forEach((p) => { hi = Math.max(hi, p.pnl); lo = Math.min(lo, p.pnl); });
    hi = Math.max(hi, 0); lo = Math.min(lo, 0);
    if (hi === lo) { hi += 1; lo -= 1; }
    const padv = (hi - lo) * 0.08; hi += padv; lo -= padv;
    const x = (i) => padL + (i / (points.length - 1 || 1)) * plotW;
    const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * plotH;
    ctx.font = "10px -apple-system, sans-serif"; ctx.textBaseline = "middle";
    for (let g = 0; g <= 4; g++) {
      const v = lo + (hi - lo) * (g / 4), yy = y(v);
      ctx.strokeStyle = "rgba(255,255,255,0.05)"; ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + plotW, yy); ctx.stroke();
      ctx.fillStyle = "#8b93a7"; ctx.fillText(Math.round(v).toLocaleString("es"), padL + plotW + 6, yy);
    }
    const y0 = y(0);
    ctx.strokeStyle = "rgba(162,155,254,0.5)"; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(padL, y0); ctx.lineTo(padL + plotW, y0); ctx.stroke(); ctx.setLineDash([]);
    const last = points[points.length - 1].pnl;
    const c = last >= 0 ? "#16c784" : "#ea3943";
    ctx.beginPath(); points.forEach((p, i) => { const xx = x(i), yy = y(p.pnl); i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
    ctx.lineTo(x(points.length - 1), y0); ctx.lineTo(x(0), y0); ctx.closePath();
    ctx.fillStyle = last >= 0 ? "rgba(22,199,132,0.10)" : "rgba(234,57,67,0.10)"; ctx.fill();
    ctx.beginPath(); points.forEach((p, i) => { const xx = x(i), yy = y(p.pnl); i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy); });
    ctx.strokeStyle = c; ctx.lineWidth = 1.6; ctx.stroke();
  }

  // --- Barras por hora ----------------------------------------------
  function drawHours(canvas, byHour) {
    const ctx = prep(canvas);
    const cssW = canvas.clientWidth || 600, cssH = canvas.clientHeight || 160;
    if (!byHour) { empty(ctx, cssH); return; }
    const padL = 8, padR = 8, padT = 10, padB = 22;
    const plotW = cssW - padL - padR, plotH = cssH - padT - padB;
    const vals = [];
    for (let h = 0; h < 24; h++) vals.push((byHour[String(h)] || { net_pnl: 0 }).net_pnl);
    const maxA = Math.max(1, ...vals.map((v) => Math.abs(v)));
    const bw = plotW / 24;
    const y0 = padT + plotH / 2;
    ctx.font = "9px -apple-system, sans-serif"; ctx.textAlign = "center";
    for (let h = 0; h < 24; h++) {
      const v = vals[h];
      const bh = (Math.abs(v) / maxA) * (plotH / 2);
      ctx.fillStyle = v >= 0 ? "#16c784" : "#ea3943";
      const xx = padL + h * bw + 1;
      if (v >= 0) ctx.fillRect(xx, y0 - bh, bw - 2, bh);
      else ctx.fillRect(xx, y0, bw - 2, bh);
      if (h % 3 === 0) { ctx.fillStyle = "#8b93a7"; ctx.fillText(h, padL + h * bw + bw / 2, cssH - 6); }
    }
    ctx.strokeStyle = "rgba(255,255,255,0.12)"; ctx.beginPath(); ctx.moveTo(padL, y0); ctx.lineTo(padL + plotW, y0); ctx.stroke();
  }

  function prep(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 600, h = canvas.clientHeight || 200;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
    return ctx;
  }
  function empty(ctx, h) { ctx.fillStyle = "#8b93a7"; ctx.font = "13px -apple-system, sans-serif"; ctx.fillText("Sin datos.", 12, h / 2); }

  $("refresh").addEventListener("click", () => load(true));
  window.addEventListener("resize", () => { if (lastData) render(lastData); });
  load(false);
})();
