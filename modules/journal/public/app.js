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

  function ageStr(sec) {
    if (sec == null) return "—";
    if (sec < 90) return "hace " + Math.round(sec) + " s";
    if (sec < 5400) return "hace " + Math.round(sec / 60) + " min";
    return "hace " + (sec / 3600).toFixed(1) + " h";
  }

  function load(force) {
    setStatus("cargando…");
    fetch("api/status").then((r) => r.json()).then((st) => {
      if (!st.has_data) {
        $("waiting").hidden = false; $("panel").hidden = true;
        setStatus("esperando colector", "bad");
        $("waiting-detail").textContent = st.ingest_ready
          ? "La ingesta está lista en el servidor; falta que el colector del Mac mini envíe el primer dato."
          : "Falta configurar NEXUS_INGEST_TOKEN en Railway para habilitar la ingesta.";
        return;
      }
      fetch("api/stats").then((r) => r.json()).then(render);
    }).catch(() => setStatus("error de red", "bad"));
  }

  function render(d) {
    if (!d.has_data) { $("waiting").hidden = false; $("panel").hidden = true; setStatus("esperando colector", "bad"); return; }
    lastData = d;
    $("waiting").hidden = true; $("panel").hidden = false;
    const stale = d.age_seconds != null && d.age_seconds > 1200; // >20 min
    setStatus(stale ? "desactualizado" : "al día", stale ? "" : "ok");
    $("updated").textContent = "actualizado " + ageStr(d.age_seconds) +
      " · " + (d.lookback_days || 365) + " días";

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
      $("summary").innerHTML =
        `<p class="bt-note">Futuros no disponibles: ${fut.error || "sin datos"}.${hint(fut.error)}</p>`;
    }

    // Spot.
    const sp = d.spot || {};
    if (sp.ok) {
      $("spot-total").innerHTML = `<strong>Valor total aprox:</strong> ${usd(sp.total_value)} USDT`;
      table($("spot"), ["Activo", "Cantidad", "Valor aprox (USDT)"],
        (sp.holdings || []).length ? sp.holdings.map((h) => [
          h.asset + (h.earn ? ' <span class="muted">· Earn</span>' : ""),
          h.qty.toLocaleString("es", { maximumFractionDigits: 8 }),
          h.value == null ? "—" : h.value.toLocaleString("es", { maximumFractionDigits: 2 })])
          : [["Sin holdings", "", ""]]);
    } else {
      $("spot-total").innerHTML =
        `<span class="bt-note">Spot no disponible: ${sp.error || "sin datos"}.${hint(sp.error)}</span>`;
      $("spot").innerHTML = "";
    }
  }

  // Pista accionable según el error de Binance.
  function hint(err) {
    const e = (err || "").toLowerCase();
    if (e.includes("-2015") || e.includes("permission") || e.includes("invalid api")) {
      return " <strong>Pista:</strong> suele ser permisos o IP. Para Futuros necesitas " +
        "<strong>Enable Futures</strong>; para Spot, <strong>Enable Reading</strong>. " +
        "Si la key está restringida por IP, agrega la IP del servidor.";
    }
    if (e.includes("-1021") || e.includes("timestamp") || e.includes("recvwindow")) {
      return " <strong>Pista:</strong> el reloj del servidor está desfasado respecto a Binance.";
    }
    return "";
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

  // --- Setups SMC (forward-test) ------------------------------------
  const fmtP = (v) => (v == null ? "—" : v.toLocaleString("es", { maximumFractionDigits: 2 }));
  const STATUS_LABEL = {
    pendiente: "⏳ en vigilancia", activo: "● activo",
    ganada: "✅ ganada", perdida: "❌ perdida", anulada: "⊘ anulada",
  };
  const STATUS_CLS = { ganada: "up", perdida: "down", activo: "up", anulada: "muted", pendiente: "" };

  function dt(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleDateString("es", { day: "2-digit", month: "2-digit" }) + " " +
      d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  }

  function loadSetups() {
    fetch("api/setups").then((r) => r.json()).then(async (d) => {
      const s = d.summary || {};
      const wr = s.win_rate == null ? "—" : s.win_rate + "%";
      const pfv = (s.pf == null) ? (s.ganadas > 0 ? "∞" : "—") : s.pf;
      const metaTxt = d.has_data
        ? `${s.total} registrados · ${s.cerradas} cerrados`
        : "sin registros todavía";
      let status = "";
      if (d.source === "macmini") {
        const ageMin = d.age_seconds != null ? Math.round(d.age_seconds / 60) : null;
        const collectorStale = d.age_seconds != null && d.age_seconds > 900;  // >15 min sin enviar
        const appDown = d.health && d.health.alive === false;
        if (appDown) status = ' · <span class="down">● app del Mac mini caída — el forward-test no avanza</span>';
        else if (collectorStale) status = ` · <span class="down">● colector sin enviar hace ${ageMin}m</span>`;
        else status = ` · <span class="up">● al día</span> <span class="muted">(Binance, hace ${ageMin}m)</span>`;
      }
      $("setups-meta").innerHTML = metaTxt + status;
      $("setups-summary").innerHTML = [
        card("Cerrados", s.cerradas || 0),
        card("Win rate", wr, s.win_rate != null && s.win_rate >= 50 ? "up" : ""),
        card("R promedio", s.avg_r == null ? "—" : s.avg_r, (s.avg_r || 0) > 0 ? "up" : (s.avg_r || 0) < 0 ? "down" : ""),
        card("Profit factor", pfv, (s.pf != null && s.pf >= 1) || (s.pf == null && s.ganadas > 0) ? "up" : "down"),
        card("R acumulado", s.total_r == null ? "—" : (s.total_r > 0 ? "+" : "") + s.total_r, (s.total_r || 0) > 0 ? "up" : (s.total_r || 0) < 0 ? "down" : ""),
        card("Ganadas / Perdidas", `${s.ganadas || 0} / ${s.perdidas || 0}`),
        card("Activos", s.activos || 0, "up"),
        card("En vigilancia", s.pendientes || 0),
      ].join("");

      // Cuenta PAPER: el forward-test traducido a USD con sizing sano (dinero simulado).
      const p = d.paper;
      if (p) {
        const sec = p.asegurado_abierto || 0;
        const eqV = (p.equity_vivo != null) ? p.equity_vivo : p.equity;
        const pnlV = (p.pnl_vivo != null) ? p.pnl_vivo : p.pnl;
        const retV = (p.return_vivo_pct != null) ? p.return_vivo_pct : p.return_pct;
        $("setups-paper-meta").textContent =
          `inicial $${p.capital_inicial.toLocaleString("es")} · ${p.riesgo_pct}% riesgo/trade · ${p.trades} cerrados`
          + (sec > 0 ? ` · +$${Math.round(sec).toLocaleString("es")} asegurado en ${p.abiertos_asegurados} abiertos` : "");
        const sign = (v) => (v > 0 ? "+" : "") + v;
        const usd = (v) => (v < 0 ? "-$" : "+$") + Math.abs(Math.round(v)).toLocaleString("es");
        $("setups-paper").innerHTML = [
          card("Equity en vivo", "$" + Math.round(eqV).toLocaleString("es"), pnlV >= 0 ? "up" : "down"),
          card("P&L en vivo", usd(pnlV), pnlV >= 0 ? "up" : "down"),
          card("Asegurado (abiertos)", sec > 0 ? "+$" + Math.round(sec).toLocaleString("es") : "—", sec > 0 ? "up" : ""),
          card("Equity cerrada", "$" + Math.round(p.equity).toLocaleString("es"), p.pnl >= 0 ? "up" : "down"),
          card("Retorno vivo", sign(retV) + "%", retV >= 0 ? "up" : "down"),
          card("Drawdown máx", p.max_dd_pct + "%", "down"),
          card("Win rate", p.win_rate == null ? "—" : p.win_rate + "%"),
        ].join("");
        // Curva de equity paper (reusa drawEquity, que plotea .pnl desde 0).
        const wrap = $("paper-equity-wrap");
        if (p.curve && p.curve.length) {
          wrap.hidden = false;
          drawEquity($("paper-equity-chart"), p.curve.map((c) => ({ pnl: c.equity - p.capital_inicial })));
        } else {
          wrap.hidden = true;
        }
      }
      // Cuenta SELECTIVA (solo POI 4h/1D) — comparación calidad vs cantidad.
      const ps = d.paper_selectivo;
      if (ps) {
        const sign = (v) => (v > 0 ? "+" : "") + v;
        $("setups-paper-sel-meta").textContent =
          `${ps.trades} trades selectivos · vs ${p ? p.trades : "?"} de la completa`;
        $("setups-paper-sel").innerHTML = [
          card("Equity", "$" + ps.equity.toLocaleString("es"), ps.pnl >= 0 ? "up" : "down"),
          card("P&L", "$" + sign(Math.round(ps.pnl)).toLocaleString("es"), ps.pnl >= 0 ? "up" : "down"),
          card("Retorno", sign(ps.return_pct) + "%", ps.return_pct >= 0 ? "up" : "down"),
          card("Drawdown máx", ps.max_dd_pct + "%", "down"),
          card("Win rate", ps.win_rate == null ? "—" : ps.win_rate + "%"),
        ].join("");
      }

      // --- Operaciones en curso (activas): dinero, apalancamiento y P&L en vivo ---
      const active = (d.setups || []).filter((x) => x.status === "activo");
      $("live-meta").textContent = active.length ? `${active.length} activa(s)` : "";
      const liveEl = $("setups-live");
      if (!active.length) {
        liveEl.innerHTML = '<p class="bt-note"><span class="muted">Ninguna operación activa ahora. Aparecen acá cuando un setup se llena.</span></p>';
      } else {
        let prices = {};
        try {
          const stt = await fetch("/m/trading/api/state").then((r) => (r.ok ? r.json() : null));
          Object.entries((stt && stt.instruments) || {}).forEach(([k, v]) => { prices[k] = (v.ticker || {}).last; });
        } catch (e) { /* sin precio en vivo */ }
        const sg = (v) => (v >= 0 ? "+" : "");
        const px = (n) => Number(n).toLocaleString("es", { maximumFractionDigits: 2 });
        liveEl.innerHTML = active.map((x) => {
          const long = x.dir === "long";
          const cur = prices[x.pair];
          const slf = Math.abs(x.entry - x.sl) / x.entry;
          const move = cur ? ((cur - x.entry) / x.entry) * (long ? 1 : -1) : null;
          const remaining = (x.remaining != null) ? x.remaining : 1;
          const realized = x.realized_r || 0;
          // 1R en dólares = el riesgo del trade (paper_risk; respaldo: notional × SL%).
          const riskUsd = (x.paper_risk != null) ? x.paper_risk
            : (x.paper_notional ? x.paper_notional * slf : null);
          // P&L vivo = solo la porción remanente; Total = asegurado + no realizado del resto.
          const pnl = (move != null && x.paper_notional) ? move * x.paper_notional * remaining : null;
          const r = (move != null && slf > 0) ? realized + remaining * (move / slf) : null;
          const dinero = (rv) => (riskUsd != null && rv != null) ? rv * riskUsd : null;   // R → USD
          const usdCard = (v) => v == null ? "—" : sg(v) + "$" + Math.round(v).toLocaleString("es");
          const cls = r == null ? "" : (r >= 0 ? "up" : "down");
          const badge = x.source === "profe" ? ' <span class="up" style="font-size:10px;border:1px solid;border-radius:4px;padding:0 3px">profe</span>' : "";
          // Plan de parciales + break-even (la estrategia del bot).
          const risk = Math.abs(x.entry - x.sl);
          const legs = x.legs_filled || 0;
          const legsTxt = (legs >= 2 ? "TP1✓ TP2✓" : legs >= 1 ? "TP1✓ TP2·" : "—") + (x.sl_be ? " · BE" : "") + (x.trailing ? " · 🏃trail" : "");
          let nextLabel, nextPx;
          if (x.trailing && x.sl_cur != null) { nextLabel = "Trailing stop"; nextPx = x.sl_cur; }
          else if (legs < 1) { nextLabel = "TP1 1R"; nextPx = long ? x.entry + risk : x.entry - risk; }
          else if (legs < 2) { nextLabel = "TP2 2R"; nextPx = long ? x.entry + 2 * risk : x.entry - 2 * risk; }
          else { nextLabel = "Runner→TP"; nextPx = x.tp; }
          // Asegurado = parciales cerrados + lo que el TRAILING STOP ya garantiza del
          // runner (si el stop está en ganancia). El trailing bloquea profit extra.
          const rStop = (x.sl_cur != null && risk > 0) ? ((long ? x.sl_cur - x.entry : x.entry - x.sl_cur) / risk) : 0;
          const guaranteedR = realized + remaining * Math.max(0, rStop);
          const securedUsd = guaranteedR > 0 ? dinero(guaranteedR) : null;
          return `<div style="margin:6px 0 14px">
            <div class="v-title">${x.pair.replace("_", "/")} ${long ? "▲ Long" : "▼ Short"} · ${x.poi_tf}${badge}</div>
            <section class="metric-grid">
              ${card("Entrada", px(x.entry))}
              ${card("Ahora", cur ? px(cur) : "—")}
              ${card("Parciales", legsTxt, legs > 0 ? "up" : "")}
              ${card("Asegurado", securedUsd == null ? "—" : usdCard(securedUsd), legs > 0 ? "up" : "")}
              ${card("Próx. " + nextLabel, px(nextPx))}
              ${card("Apalanc.", x.paper_leverage != null ? x.paper_leverage + "x" : "—")}
              ${card("Notional", x.paper_notional != null ? "$" + Math.round(x.paper_notional).toLocaleString("es") : "—")}
              ${card("P&L vivo", usdCard(pnl), cls)}
              ${card("P&L total", usdCard(dinero(r)), cls)}
            </section>
          </div>`;
        }).join("");
      }

      // Comparativas del forward-test: régimen (VIX+ADX) y CDC (cambio de carácter).
      const cf = s.con_filtro, sf = s.sin_filtro, cc = s.con_cdc, sc = s.sin_cdc;
      const line = (lab, m) => `<strong>${lab}:</strong> ${m.cerradas} cerrados · win ${m.win_rate == null ? "—" : m.win_rate + "%"} · R prom ${m.avg_r == null ? "—" : m.avg_r} · PF ${m.pf == null ? (m.ganadas > 0 ? "∞" : "—") : m.pf} · R acum ${m.total_r == null ? "—" : (m.total_r > 0 ? "+" : "") + m.total_r}`;
      const blocks = [];
      if (cf && sf && (cf.cerradas || sf.cerradas)) {
        blocks.push(`<div class="v-title">Régimen · ¿el filtro VIX&lt;25 + ADX&gt;25 ayuda? (forward-test en vivo)</div>` +
          `<p class="bt-note">${line("✓ con filtro (régimen OK)", cf)}<br>${line("✕ sin filtro (régimen desfav.)", sf)}</p>`);
      }
      if (cc && sc && (cc.cerradas || sc.cerradas)) {
        blocks.push(`<div class="v-title">CDC · ¿la confirmación por cambio de carácter ayuda? (hipótesis 1h)</div>` +
          `<p class="bt-note">${line("✓ con CDC (apareció en el POI)", cc)}<br>${line("✕ sin CDC (nunca apareció)", sc)}</p>`);
      }
      const pr = s.profe, ind = s.indicador;
      if (pr && ind && (pr.cerradas || ind.cerradas)) {
        blocks.push(`<div class="v-title">Fuente · entradas del profe (manual) vs indicador (auto)</div>` +
          `<p class="bt-note">${line("👤 profe", pr)}<br>${line("🤖 indicador", ind)}</p>`);
      }
      if (blocks.length) {
        $("setups-regime").hidden = false;
        $("setups-regime").innerHTML = blocks.join("") +
          `<p class="bt-note"><span class="muted">Hipótesis de la investigación (no garantías): los setups en régimen favorable y con CDC deberían rendir mejor. Se valida con datos reales en el tiempo.</span></p>`;
      }

      const regCell = (x) => {
        if (x.regime_ok == null) return '<span class="muted">s/d</span>';
        const vix = x.regime_vix == null ? "s/d" : x.regime_vix;
        const adx = x.regime_adx == null ? "s/d" : x.regime_adx;
        return `<span class="${x.regime_ok ? "up" : "down"}">${x.regime_ok ? "✓" : "✕"}</span> <span class="muted">V${vix}·A${adx}</span>`;
      };
      // CDC: ✓ si el cambio de carácter apareció en el POI (aunque sea después de
      // generarse el plan); en setups abiertos sin CDC todavía, ⏳.
      const cdcCell = (x) => {
        if (x.cdc_ok == null) return '<span class="muted">s/d</span>';
        if (x.cdc_ok) return '<span class="up">✓</span>';
        const open = x.status === "pendiente" || x.status === "activo";
        return open ? '<span class="muted">⏳</span>' : '<span class="down">✕</span>';
      };
      const rows = (d.setups || []).map((x) => [
        dt(x.ts_created),
        x.pair.replace("_", "/") + (x.source === "profe" ? ' <span class="up" style="font-size:10px;border:1px solid;border-radius:4px;padding:0 3px">profe</span>' : ""),
        x.poi_tf,
        `<span class="${x.dir === "long" ? "up" : "down"}">${x.dir === "long" ? "Largo" : "Corto"}</span>`,
        fmtP(x.entry_lo) + "–" + fmtP(x.entry_hi),
        fmtP(x.sl),
        fmtP(x.tp),
        (typeof x.rr === "number" ? x.rr.toFixed(1) : x.rr),
        regCell(x),
        cdcCell(x),
        `<span class="${STATUS_CLS[x.status] || ""}">${STATUS_LABEL[x.status] || x.status}</span>`,
        x.result_r == null ? "—" : `<span class="${x.result_r > 0 ? "up" : "down"}">${x.result_r > 0 ? "+" : ""}${x.result_r}R</span>`,
        x.paper_pnl == null ? "—" : `<span class="${x.paper_pnl >= 0 ? "up" : "down"}">${x.paper_pnl >= 0 ? "+" : ""}$${Math.round(x.paper_pnl).toLocaleString("es")}</span>`,
      ]);
      table($("setups-table"),
        ["Fecha", "Par", "TF", "Dir", "Entrada", "SL", "TP", "R:R", "Régimen", "CDC", "Estado", "Resultado", "P&L"],
        rows.length ? rows : [["Aún no se registran setups. Aparecen cuando el indicador genera un plan válido (R:R≥2).", "", "", "", "", "", "", "", "", "", "", "", ""]]);
    }).catch(() => {});

    // Backtest histórico de referencia (mismo criterio sobre datos de Binance).
    fetch("/m/trading/api/setup_backtest").then((r) => r.ok ? r.json() : null).then((b) => {
      if (!b) return;
      const el = $("setups-bt");
      el.hidden = false;
      const usd = (v) => "$" + Math.round(v).toLocaleString("es");
      const yr = (ms) => ms ? new Date(ms).getUTCFullYear() : "?";
      const blk = (t, m) => m ? `<strong>${t}:</strong> ${m.trades} trades · win ${m.win_rate}% · R prom ${m.avg_r} · PF ${pf(m.pf)} · R acum ${m.total_r >= 0 ? "+" : ""}${m.total_r}` : "";
      const pairs = (b.params && b.params.symbols) ? b.params.symbols.length : Object.keys(b.by_pair || {}).length;
      // Traducción a plata: la fila más importante para decidir si es aplicable.
      const EQ = b.equity || {};
      const eqRow = (label, e) => e ? `<tr><td>${label}</td><td style="text-align:right">${usd(e.capital_final)}</td><td style="text-align:right;color:${e.retorno_pct >= 0 ? "#16c784" : "#ea3943"}">${e.retorno_pct >= 0 ? "+" : ""}${e.retorno_pct}%</td><td style="text-align:right;color:#f5a623">−${e.max_drawdown_pct}%</td>${e.quebro ? '<td style="color:#ea3943">⚠ quebró</td>' : "<td></td>"}</tr>` : "";
      const cap0 = (EQ.fijo_2pct ? EQ.fijo_2pct.capital_inicial / 1000 : 38);
      const eqTable = EQ.fijo_2pct ? `
        <div style="margin-top:8px"><strong>Si tus $${cap0}k hubieran seguido esto (${pairs} pares, ${yr(b.span && b.span.from)}–${yr(b.span && b.span.to)}):</strong></div>
        <table class="bt-eq" style="width:100%;font-size:12px;margin-top:4px;border-collapse:collapse">
          <tr style="color:#8a8f98"><td>escenario</td><td style="text-align:right">capital final</td><td style="text-align:right">retorno</td><td style="text-align:right">peor caída</td><td></td></tr>
          ${eqRow("2% riesgo fijo", EQ.fijo_2pct)}
          ${eqRow("2% · TP capado 3R", EQ.comp_2pct_cap3R)}
        </table>
        <div class="muted" style="margin-top:4px">Capar la ganancia en 3R quiebra la cuenta: el edge vive en dejar correr los winners.</div>` : "";
      // Sensibilidad al cap: dónde vive el edge.
      const CS = b.cap_sensitivity || {};
      const capLine = Object.keys(CS).length
        ? `<div style="margin-top:8px"><strong>Dónde vive el edge (R promedio si capas la ganancia):</strong> ` +
          ["sin_tope", "10R", "5R", "3R"].filter((k) => CS[k]).map((k) =>
            `${k.replace("_", " ")} ${CS[k].avg_r}`).join(" · ") + `</div>` : "";
      // Por par: ¿generaliza o es de un par?
      const bp = b.by_pair || {};
      const pairRows = Object.keys(bp).map((k) =>
        `<tr><td>${k.replace("_USDT", "")}</td><td style="text-align:right">${bp[k].trades}</td><td style="text-align:right">${bp[k].win_rate}%</td><td style="text-align:right;color:${bp[k].avg_r >= 0 ? "#16c784" : "#ea3943"}">${bp[k].avg_r}</td><td style="text-align:right">${pf(bp[k].pf)}</td><td style="text-align:right">+${bp[k].total_r}R</td></tr>`).join("");
      const pairTable = pairRows ? `
        <div style="margin-top:8px"><strong>Por par:</strong></div>
        <table style="width:100%;font-size:12px;margin-top:4px;border-collapse:collapse">
          <tr style="color:#8a8f98"><td>par</td><td style="text-align:right">n</td><td style="text-align:right">win</td><td style="text-align:right">R prom</td><td style="text-align:right">PF</td><td style="text-align:right">R acum</td></tr>
          ${pairRows}
        </table>` : "";
      const rk = b.risk ? `<div style="margin-top:8px"><span class="muted">Dureza: peor racha ${b.risk.max_losing_streak} pérdidas seguidas · drawdown ${b.risk.max_drawdown_r}R.</span></div>` : "";
      // Comparación salida escalonada (scale-out) vs actual.
      const SO = b.scale_out || {};
      const soName = { actual: "Actual (100% al TP lejano)", tu_idea: "Scale-out (50/25/25, BE tras TP1)", runner_agres: "Runner agresivo (TP2 en 3R)", be_tardio: "BE tardío (tras TP2)" };
      const soRows = Object.keys(SO).map((k) => {
        const s = SO[k];
        return `<tr><td>${soName[k] || k}</td><td style="text-align:right">${s.win_rate}%</td><td style="text-align:right">${s.avg_r}</td><td style="text-align:right">+${s.total_r}R</td><td style="text-align:right;color:#f5a623">−${s.max_drawdown_pct}%</td><td style="text-align:right">${s.risk ? s.risk.max_losing_streak : "?"}</td><td style="text-align:right;color:${s.retorno_pct >= 0 ? "#16c784" : "#ea3943"}">${usd(s.capital_final)}</td></tr>`;
      }).join("");
      const soTable = soRows ? `
        <div style="margin-top:10px"><strong>Salida escalonada vs actual</strong> <span class="muted">(mismos trades, 2% riesgo fijo desde $${(EQ.fijo_2pct ? EQ.fijo_2pct.capital_inicial / 1000 : 38)}k)</span></div>
        <table style="width:100%;font-size:12px;margin-top:4px;border-collapse:collapse">
          <tr style="color:#8a8f98"><td>estrategia</td><td style="text-align:right">win</td><td style="text-align:right">R prom</td><td style="text-align:right">R acum</td><td style="text-align:right">peor caída</td><td style="text-align:right">racha</td><td style="text-align:right">capital final</td></tr>
          ${soRows}
        </table>
        <div class="muted" style="margin-top:4px">El scale-out sube el win rate y baja el drawdown a costa de retorno total. Elige según tu estómago.</div>` : "";
      el.innerHTML = `<div class="v-title">Backtest de referencia · mismo criterio sobre ${pairs} pares de Binance (anti-repaint, IS/OOS)</div>` +
        `<p class="bt-note">${blk("In-sample", b.in_sample)}<br>${blk("Out-of-sample", b.out_sample)}<br>${blk("Todo", b.all)}` +
        eqTable + capLine + soTable + pairTable + rk +
        `<div style="margin-top:8px"><span class="muted">${b.note || ""}</span></div></p>`;
    }).catch(() => {});
  }

  // --- Calculadora de posición / riesgo ------------------------------
  function calc() {
    const num = (id) => parseFloat($(id).value);
    const cap = num("calc-cap"), riskp = num("calc-risk"), entry = num("calc-entry"), sl = num("calc-sl"), tp = num("calc-tp");
    const out = $("calc-out");
    if (!(cap > 0 && riskp > 0 && entry > 0 && sl > 0) || entry === sl) {
      out.innerHTML = '<p class="bt-note"><span class="muted">Completa capital, riesgo, entrada y SL.</span></p>';
      return;
    }
    const long = sl < entry;
    const slFrac = Math.abs(entry - sl) / entry;
    const riskUsd = cap * riskp / 100;
    const notional = riskUsd / slFrac;
    const units = notional / entry;
    const lev = notional / cap;
    const liq = long ? entry * (1 - 1 / lev + 0.004) : entry * (1 + 1 / lev - 0.004);
    const liqDist = Math.abs(liq - entry) / entry * 100;
    const usd = (v) => "$" + Math.round(v).toLocaleString("es");
    const cards = [
      card("Dirección", long ? "Long" : "Short", long ? "up" : "down"),
      card("SL distancia", slFrac * 100 < 0.005 ? "—" : (slFrac * 100).toFixed(2) + "%"),
      card("Riesgo", usd(riskUsd), "down"),
      card("Notional", usd(notional)),
      card("Tamaño", units.toFixed(units < 1 ? 4 : 2)),
      card("Apalanc. efectivo", lev.toFixed(1) + "x", lev > 5 ? "down" : ""),
      card("Liquidación", usd(liq) + ` (${liqDist.toFixed(1)}%)`, "down"),
    ];
    const tpOk = tp > 0 && ((long && tp > entry) || (!long && tp < entry));
    if (tpOk) {
      const rr = Math.abs(tp - entry) / Math.abs(entry - sl);
      const profit = notional * Math.abs(tp - entry) / entry;
      cards.push(card("R:R", rr.toFixed(1), rr >= 2 ? "up" : ""));
      cards.push(card("Ganancia pot.", "+" + usd(profit), "up"));
    }
    out.innerHTML = cards.join("");
  }
  ["calc-cap", "calc-risk", "calc-entry", "calc-sl", "calc-tp"].forEach((id) => {
    const el = $(id); if (el) el.addEventListener("input", calc);
  });
  calc();

  $("refresh").addEventListener("click", () => { load(true); loadSetups(); });
  window.addEventListener("resize", () => { if (lastData) render(lastData); });
  load(false);
  loadSetups();
})();
