/* Co-piloto de Trading — frontend.
 *
 * Se conecta al stream SSE del backend (/m/trading/api/stream), que empuja el
 * estado del mercado en vivo. Por cada instrumento dibuja: precio + variación,
 * estadísticas, gráfico de velas (canvas propio, sin librerías), libro de
 * órdenes y un panel de señales.
 *
 * Si SSE falla, cae a polling de /api/state cada 3s como respaldo.
 */
(function () {
  "use strict";

  const container = document.getElementById("instruments");
  const tpl = document.getElementById("card-tpl");
  const statusDot = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  const lastUpdateEl = document.getElementById("last-update");
  const cryptoSelect = document.getElementById("crypto-select");

  // Guardamos el estado de cada tarjeta (nodo DOM + último precio) por símbolo.
  const cards = {};
  // Un solo gráfico visible a la vez: el del símbolo elegido en el selector.
  let activeSymbol = null;
  let lastLabels = {};   // símbolo → etiqueta (para poblar el dropdown)

  // Temporalidades del selector. Se sobreescriben con lo que diga el backend
  // (api/config); estos son el respaldo por si esa llamada falla.
  let TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1D"];
  let DEFAULT_TF = "15m";
  const CANDLE_REFRESH_MS = 6000; // cada cuánto refrescamos las velas del par
  const SMC_REFRESH_MS = 20000;   // cada cuánto recalculamos el análisis SMC

  // --- Primitive custom de Lightweight Charts para las cajas SMC -----
  // Lightweight Charts no trae rectángulos; lo resolvemos con un series
  // primitive que dibuja en el canvas usando priceToCoordinate / timeToCoordinate,
  // así las cajas (premium/discount, FVG, POIs) quedan alineadas al hacer zoom/paneo.
  class SMCRenderer {
    constructor(src) { this._src = src; }
    draw(target) {
      const src = this._src;
      const D = src._data;
      if (!D || !src._series) return;
      const smc = D.smc;
      const show = D.show || {};
      const series = src._series;
      const ts = src._chart.timeScale();
      const py = (p) => series.priceToCoordinate(p);
      const tx = (tms) => ts.timeToCoordinate(Math.floor(tms / 1000));
      // X para CUALQUIER tiempo (no solo barras): timeToCoordinate devuelve null en
      // tiempos que no caen en una vela, y anclar a barras enteras hacía que la caja
      // del trade colapsara a una línea en timeframes altos (pocas barras desde la
      // entrada). Interpolamos con el espaciado de barra real → ancho proporcional al
      // TIEMPO, correcto en cualquier temporalidad. tsec en segundos epoch.
      const bm = D.barMeta;
      const xAt = (tsec) => {
        if (!bm || !bm.interval) return tx(tsec * 1000);
        const xL = ts.timeToCoordinate(bm.lastT);
        const xP = ts.timeToCoordinate(bm.lastT - bm.interval);
        if (xL == null || xP == null) return tx(tsec * 1000);
        return xL + ((tsec - bm.lastT) / bm.interval) * (xL - xP);
      };
      // Ancho de UNA barra en px (para un ancho mínimo de caja legible). Un trade recién
      // activado abarca <1 barra; sin un mínimo decente la caja se ve como una línea.
      const pxBar = (() => {
        if (!bm || !bm.interval) return 12;
        const a = ts.timeToCoordinate(bm.lastT), b = ts.timeToCoordinate(bm.lastT - bm.interval);
        return (a != null && b != null) ? Math.abs(a - b) : 12;
      })();
      const BOX_MIN_W = Math.max(14, pxBar * 3);   // caja siempre ≥ ~3 barras de ancho
      target.useMediaCoordinateSpace((scope) => {
        const ctx = scope.context;
        const W = scope.mediaSize.width, H = scope.mediaSize.height;

        // --- Capa LuxAlgo: cinta de tendencia (EMA 21/55), detrás de todo ---
        if (show.ribbon && D.ribbon && D.ribbon.length) {
          const pts = D.ribbon;
          for (let i = 1; i < pts.length; i++) {
            const a = pts[i - 1], b = pts[i];
            if (a.f == null || a.s == null || b.f == null || b.s == null) continue;
            const xa = ts.timeToCoordinate(a.t), xb = ts.timeToCoordinate(b.t);
            if (xa == null || xb == null) continue;
            const yaf = py(a.f), yas = py(a.s), ybf = py(b.f), ybs = py(b.s);
            if (yaf == null || yas == null || ybf == null || ybs == null) continue;
            const bull = (a.f + b.f) >= (a.s + b.s);
            ctx.fillStyle = bull ? "rgba(22,199,132,0.10)" : "rgba(234,57,67,0.10)";
            ctx.beginPath(); ctx.moveTo(xa, yaf); ctx.lineTo(xb, ybf);
            ctx.lineTo(xb, ybs); ctx.lineTo(xa, yas); ctx.closePath(); ctx.fill();
          }
          const drawEma = (key, color) => {
            ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.beginPath(); let on = false;
            for (const p of pts) {
              const x = ts.timeToCoordinate(p.t), y = py(p[key]);
              if (x == null || y == null) { on = false; continue; }
              if (!on) { ctx.moveTo(x, y); on = true; } else ctx.lineTo(x, y);
            }
            ctx.stroke();
          };
          drawEma("f", "rgba(162,155,254,0.55)");
          drawEma("s", "rgba(139,147,167,0.5)");
        }

        if (!smc) return;
        // Anti-solape de etiquetas: cuando dos price-lines/cajas tienen precios muy
        // juntos, sus títulos se encimarían. `place` busca la altura libre más cercana
        // (arriba o abajo) y la reserva, así cada etiqueta queda legible. Se llevan dos
        // columnas: izquierda (nombres de cajas/Entrada) y derecha (SL/TP/R:R).
        const _LH = 16, _leftB = [], _rightB = [], _divB = [];   // alto de banda = alto de pill
        const _free = (bands, y) => !bands.some((b) => y < b + _LH && y + _LH > b);
        const _place = (bands, yTop) => {
          if (_free(bands, yTop)) { bands.push(yTop); return yTop; }
          for (let k = 1; k <= 12; k++) {
            const d = yTop + k * _LH; if (d + _LH < H && _free(bands, d)) { bands.push(d); return d; }
            const u = yTop - k * _LH; if (u > 0 && _free(bands, u)) { bands.push(u); return u; }
          }
          bands.push(yTop); return yTop;
        };
        const placeL = (y) => _place(_leftB, y);
        const placeR = (y) => _place(_rightB, y);
        const placeD = (y) => _place(_divB, y);   // etiquetas de divergencias (en los pivotes)
        // Etiqueta tipo "pill" (fondo oscuro redondeado) para que el texto se lea
        // sobre velas y cajas — estilo LuxAlgo. opts.right ancla al borde derecho.
        const pill = (y, text, color, opts = {}) => {
          ctx.font = opts.font || "9.5px -apple-system, sans-serif";
          ctx.textBaseline = "top";
          const w = ctx.measureText(text).width + 10;
          let px = opts.x != null ? opts.x : 6;
          if (opts.right) px = W - w - 6;
          px = Math.max(2, Math.min(px, W - w - 2));
          ctx.fillStyle = "rgba(9,11,17,0.82)";
          if (ctx.roundRect) { ctx.beginPath(); ctx.roundRect(px, y, w, 15, 4); ctx.fill(); }
          else ctx.fillRect(px, y, w, 15);
          ctx.fillStyle = color;
          ctx.fillText(text, px + 5, y + 3.5);
        };
        // --- Overlay SMC (siempre): premium/descuento, FVG, POIs ---
        // Premium/descuento como lo dibuja LuxAlgo: TRES BANDAS discretas dentro
        // del dealing range — premium pegada a los máximos (ahí se buscan cortos),
        // equilibrium alrededor del 50% (fib del rango) y descuento pegada a los
        // mínimos (ahí se buscan largos). NO mitades completas: las zonas marcan
        // dónde buscar la operación, el 50% solo separa caro de barato.
        if (smc.range && smc.range.eq) {
          const pHi = smc.range.strong_high, pLo = smc.range.weak_low;
          const d = pHi - pLo;
          if (d > 0) {
            const BAND = 0.08;   // ancho de las bandas premium/descuento (8% del rango)
            const band = (pTop, pBot, rgb, label) => {
              const y1 = py(pTop), y2 = py(pBot);
              if (y1 == null || y2 == null) return;
              const top = Math.max(0, Math.min(y1, y2));
              const bot = Math.min(H, Math.max(y1, y2));
              if (bot - top < 2) return;
              ctx.fillStyle = `rgba(${rgb},0.09)`;
              ctx.fillRect(0, top, W, bot - top);
              ctx.strokeStyle = `rgba(${rgb},0.22)`; ctx.lineWidth = 1; ctx.setLineDash([2, 4]);
              ctx.beginPath(); ctx.moveTo(0, top + 0.5); ctx.lineTo(W, top + 0.5);
              ctx.moveTo(0, bot - 0.5); ctx.lineTo(W, bot - 0.5); ctx.stroke(); ctx.setLineDash([]);
              if (label && bot - top > 16) {
                ctx.globalAlpha = 0.85;
                pill((top + bot) / 2 - 7, label, `rgba(${rgb},0.95)`,
                  { right: true, font: "600 9px -apple-system, sans-serif" });
                ctx.globalAlpha = 1;
              }
            };
            band(pHi, pHi - BAND * d, "234,57,67", "PREMIUM");          // pegada al máximo
            band(smc.range.eq + 0.025 * d, smc.range.eq - 0.025 * d,
                 "162,155,254", null);                                   // equilibrium (50%)
            band(pLo + BAND * d, pLo, "22,199,132", "DESCUENTO");        // pegada al mínimo
          }
        }
        // FVG: caja desde su origen hacia la derecha, gradiente que decae y
        // etiqueta pill a la derecha (solo si la caja tiene alto suficiente).
        (smc.fvgs || []).filter((f) => !f.filled).forEach((f) => {
          const y1 = py(f.hi), y2 = py(f.lo); if (y1 == null || y2 == null) return;
          let x = tx(f.t); if (x == null) x = 0; x = Math.max(0, x);
          const top = Math.min(y1, y2), h = Math.max(1, Math.abs(y2 - y1));
          const col = f.bullish ? "162,155,254" : "245,166,35";
          const g = ctx.createLinearGradient(x, 0, W, 0);
          g.addColorStop(0, `rgba(${col},0.16)`); g.addColorStop(1, `rgba(${col},0.05)`);
          ctx.fillStyle = g; ctx.fillRect(x, top, W - x, h);
          ctx.strokeStyle = `rgba(${col},0.3)`; ctx.lineWidth = 1;
          ctx.strokeRect(x + 0.5, top + 0.5, Math.max(1, W - x - 1), h);
          if (h > 10) pill(placeR(top + h / 2 - 7), f.bullish ? "FVG ▲" : "FVG ▼",
            f.bullish ? "#a29bfe" : "#f5a623", { right: true });
        });
        // POI / order blocks: nacen en su vela de confirmación y se extienden a
        // la derecha. Válido = relleno con gradiente + borde + línea de
        // mitigación al 50%; mitigado/roto = fondo no sólido y sin etiqueta
        // (estilo breaker de LuxAlgo: menos ruido).
        (smc.pois || []).forEach((poi) => {
          // Toggle "Solo 4h/1D": muestra únicamente order blocks de timeframe alto
          // (el edge robusto del backtest: avgR 0,90 vs 0,76, win 85%).
          if (show.htf && poi.tf !== "4h" && poi.tf !== "1D") return;
          const y1 = py(poi.hi), y2 = py(poi.lo); if (y1 == null || y2 == null) return;
          const top = Math.min(y1, y2), h = Math.max(1, Math.abs(y2 - y1));
          let x = poi.t_conf ? tx(poi.t_conf) : 0; if (x == null) x = 0; x = Math.max(0, x);
          const long = poi.dir === "long";
          const base = long ? "22,199,132" : "234,57,67";
          if (poi.valid && poi.reference) {
            // Zona PROFUNDA de referencia ("qué hay si el mercado se va"): atenuada
            // y punteada para no saturar al alejar el zoom; etiqueta con la distancia.
            ctx.fillStyle = `rgba(${base},0.05)`; ctx.fillRect(x, top, W - x, h);
            ctx.strokeStyle = `rgba(${base},0.22)`; ctx.lineWidth = 1; ctx.setLineDash([2, 4]);
            ctx.strokeRect(x + 0.5, top + 0.5, Math.max(1, W - x - 1), h);
            ctx.setLineDash([]);
            const d = poi.dist_pct != null ? ` ${poi.dist_pct > 0 ? "+" : ""}${Math.round(poi.dist_pct)}%` : "";
            pill(placeR(top + 2), `${poi.tf}${d}`, `rgba(${base},0.7)`, { right: true });
          } else if (poi.valid) {
            const g = ctx.createLinearGradient(x, 0, W, 0);
            g.addColorStop(0, `rgba(${base},0.20)`); g.addColorStop(1, `rgba(${base},0.06)`);
            ctx.fillStyle = g; ctx.fillRect(x, top, W - x, h);
            ctx.strokeStyle = `rgba(${base},0.55)`; ctx.lineWidth = 1;
            ctx.strokeRect(x + 0.5, top + 0.5, Math.max(1, W - x - 1), h);
            ctx.strokeStyle = `rgba(${base},0.35)`; ctx.setLineDash([2, 3]);
            ctx.beginPath(); ctx.moveTo(x, top + h / 2); ctx.lineTo(W, top + h / 2); ctx.stroke();
            ctx.setLineDash([]);
            pill(placeR(top + 2), `POI ${poi.tf}`, long ? "#16c784" : "#ea3943", { right: true });
          } else {
            ctx.fillStyle = `rgba(${base},0.04)`;
            ctx.fillRect(x, top, W - x, h);
            ctx.strokeStyle = `rgba(${base},0.18)`; ctx.lineWidth = 1; ctx.setLineDash([3, 4]);
            ctx.strokeRect(x + 0.5, top + 0.5, Math.max(1, W - x - 1), h);
            ctx.setLineDash([]);
          }
        });

        // --- Capa LuxAlgo: niveles Weak/Strong con % ---
        if (show.levels && smc.levels) {
          smc.levels.forEach((lv) => {
            const y = py(lv.price); if (y == null) return;
            const high = lv.type === "high";
            const col = high ? "#ea3943" : "#16c784";
            ctx.strokeStyle = col; ctx.globalAlpha = lv.kind === "weak" ? 0.55 : 0.3;
            ctx.setLineDash([1, 4]); ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
            ctx.setLineDash([]); ctx.globalAlpha = 1;
            pill(placeL(y - (high ? 16 : 2)),
              `${lv.label}${lv.pct != null ? " · " + lv.pct + "%" : ""}`, col);
          });
        }

        // --- Capa CDC: cambios de carácter (CHoCH) sobre velas cerradas ---
        // SIEMPRE visible (sin toggle, pedido de Hugo): línea desde el swing
        // ESTRUCTURAL roto hasta la vela cuyo CIERRE lo rompió, con etiqueta
        // "CDC" en el eje de la línea — roja siempre, como el indicador de
        // referencia (calibrado con los ejemplos M15 de Hugo).
        if (smc.cdc_events && smc.cdc_events.length) {
          smc.cdc_events.forEach((ev) => {
            const y = py(ev.price); if (y == null) return;
            let x1 = tx(ev.t_from), x2 = tx(ev.t_to);
            if (ev.pending && x2 == null) x2 = W;   // pendiente: hasta el presente
            if (x2 == null) return;
            if (x1 == null) x1 = 0;
            const col = "#ea3943";
            ctx.strokeStyle = col; ctx.lineWidth = 1.2; ctx.setLineDash([]);
            ctx.globalAlpha = ev.pending ? 0.95 : 0.7;
            ctx.beginPath(); ctx.moveTo(x1, y); ctx.lineTo(x2, y); ctx.stroke();
            // Tick de quiebre solo en los históricos (el pendiente sigue vivo).
            if (!ev.pending) {
              ctx.beginPath(); ctx.moveTo(x2, y - 4); ctx.lineTo(x2, y + 4); ctx.stroke();
            }
            ctx.globalAlpha = 1;
            // Etiqueta EN el eje de la línea (centrada sobre ella, al medio del
            // tramo): el fondo de la pill corta la línea, como el indicador.
            pill(y - 8, "CDC", col,
                 { x: Math.max(2, Math.min((x1 + x2) / 2 - 14, W - 44)),
                   font: "600 9px -apple-system, sans-serif" });
          });
        }

        // --- Cajita del trade ACTIVO (forward-test), acotada desde la entrada ---
        // Zona de RIESGO (entrada→SL, rojo) y RECOMPENSA (entrada→TP, verde), desde
        // la barra de activación hacia la derecha, como el indicador del curso.
        if (show.tpsl && D.trades && D.trades.length) {
          D.trades.forEach((tr) => {
            const yE = py(tr.entry);
            // Ancho = tiempo real entrada→ahora (xAt interpola entre barras), así la
            // caja es proporcional en cualquier timeframe y no colapsa a una línea.
            const t0 = tr.ts_activated || tr.ts_created;
            let x1 = t0 ? xAt(t0) : null;
            let x2 = xAt(Date.now() / 1000);          // borde derecho = ahora
            if (x1 == null) x1 = 0;                   // activación fuera de vista por la izq.
            if (x2 == null) x2 = W;
            x1 = Math.max(0, Math.min(x1, W));
            x2 = Math.max(0, Math.min(x2, W));
            // Ancho mínimo legible (~3 barras): un trade recién activado abarca <1 barra;
            // se ensancha hacia la izquierda manteniendo el borde derecho en "ahora".
            if (x2 - x1 < BOX_MIN_W) x1 = Math.max(0, x2 - BOX_MIN_W);
            if (x2 - x1 < 2) x2 = Math.min(W, x1 + BOX_MIN_W);
            const drawBox = (p2, rgb) => {
              const y2 = py(p2);
              if (yE == null || y2 == null) return;
              const top = Math.min(yE, y2), h = Math.max(1, Math.abs(y2 - yE));
              ctx.fillStyle = `rgba(${rgb},0.12)`;
              ctx.fillRect(x1, top, x2 - x1, h);
              ctx.strokeStyle = `rgba(${rgb},0.5)`;
              ctx.lineWidth = 1;
              ctx.strokeRect(x1 + 0.5, top + 0.5, Math.max(1, x2 - x1 - 1), h);
            };
            // En break-even ya no hay riesgo de SL → no dibujamos la caja roja.
            if (!tr.sl_be) drawBox(tr.sl, "234,57,67");  // entrada → SL: riesgo
            drawBox(tr.tp, "22,199,132");                 // entrada → TP: recompensa
            // Runner en trailing: la zona ASEGURADA (entrada→trailing stop) crece a
            // medida que el stop sube, y se dibuja la línea del trailing stop (se mueve).
            if (tr.trailing && tr.sl_cur != null) {
              const yT = py(tr.sl_cur);
              if (yE != null && yT != null) {
                const top = Math.min(yE, yT), h = Math.max(1, Math.abs(yT - yE));
                ctx.fillStyle = "rgba(22,199,132,0.18)"; ctx.fillRect(x1, top, x2 - x1, h);  // asegurado
                ctx.strokeStyle = "rgba(245,166,35,0.95)"; ctx.lineWidth = 1.4; ctx.setLineDash([4, 3]);
                ctx.beginPath(); ctx.moveTo(x1, yT); ctx.lineTo(x2, yT); ctx.stroke(); ctx.setLineDash([]);
                pill(yT - 8, "Trail SL " + fmtPrice(tr.sl_cur), "#f5a623",
                     { x: Math.max(2, Math.min(x1 + 2, W - 90)), font: "600 9px -apple-system, sans-serif" });
              }
            }
          });
        }

        // --- Capa LuxAlgo: escenario TP/SL anclado a estructura (NO una orden) ---
        // Solo llega aquí si el backend validó: POI ✓ que el precio toca, en su
        // zona correcta (descuento/premium) y con R:R real >= 2. Es contexto.
        if (show.tpsl && smc.tpsl && (!show.htf || smc.tpsl.tf === "4h" || smc.tpsl.tf === "1D")) {
          const t = smc.tpsl;
          const long = t.dir === "long";
          const line = (price, color, label) => {
            if (price == null) return;
            const y = py(price); if (y == null) return;
            ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); ctx.setLineDash([]);
            pill(placeR(y - 16), label, color, { right: true });
          };
          // Estado del plan: "pendiente" (en vigilancia, precio aún fuera de la zona)
          // o "activo" (el precio ya está dentro). Pendiente se ve más tenue/dashed.
          const pend = t.state === "pendiente";
          const outReg = t.regime_ok === false;   // plan fuera de régimen → más tenue
          // Piso de 0.55: atenuado pero siempre legible (las pills ya dan contraste).
          const alpha = Math.max(0.55, (pend ? 0.65 : 1) * (outReg ? 0.6 : 1));
          // Zona del POI. Si el trade está ACTIVO, acotamos la banda desde la barra
          // de activación (caja, no banda de borde a borde); pendiente sigue full.
          const activeMatch = (D.trades || []).find((tr) => tr.dir === t.dir);
          // Si el trade está ACTIVO acotamos la banda a una CAJA (barra de activación
          // → última barra), igual que la cajita del trade. Pendiente sigue full.
          let xPlan = 0, xPlanEnd = W;
          if (activeMatch) {
            const t0 = activeMatch.ts_activated || activeMatch.ts_created;
            const xp = t0 ? xAt(t0) : null;
            const xe = xAt(Date.now() / 1000);
            if (xp != null) xPlan = Math.max(0, Math.min(xp, W - 2));
            if (xe != null) xPlanEnd = Math.max(xPlan + 6, Math.min(xe, W));
          }
          const yhi = py(t.entry_hi), ylo = py(t.entry_lo);
          if (yhi != null && ylo != null) {
            const top = Math.min(yhi, ylo), h = Math.max(2, Math.abs(ylo - yhi));
            const g = ctx.createLinearGradient(0, top, 0, top + h);
            g.addColorStop(0, pend ? "rgba(108,92,231,0.14)" : "rgba(108,92,231,0.22)");
            g.addColorStop(1, pend ? "rgba(108,92,231,0.06)" : "rgba(108,92,231,0.10)");
            ctx.fillStyle = g; ctx.fillRect(xPlan, top, xPlanEnd - xPlan, h);
            ctx.strokeStyle = "rgba(162,155,254,0.6)"; ctx.lineWidth = 1;
            ctx.setLineDash([4, 3]); ctx.strokeRect(xPlan + 0.5, top + 0.5, Math.max(1, xPlanEnd - xPlan - 1), h); ctx.setLineDash([]);
            pill(placeL(top + 2), `Plan ${t.tf} ${long ? "▲ largo" : "▼ corto"}`, "#a29bfe",
              { font: "600 9.5px -apple-system, sans-serif" });
          }
          // SL y TP: línea punteada + etiqueta pill con su precio (a la derecha).
          ctx.globalAlpha = alpha;
          const slPctTxt = (typeof t.sl_pct === "number")
            ? ` (−${t.sl_pct.toFixed(1)}%${t.sl_capped ? " · tope 1,5%" : ""})` : "";
          line(t.sl, t.sl_capped ? "#f5a623" : "#ea3943", `SL ${fmtPrice(t.sl)}${slPctTxt}`);
          line(t.tp, "#16c784", `TP · ${t.tp_label} ${fmtPrice(t.tp)}`);
          // ENTRADA: línea propia, con su precio (a la izquierda para no chocar con el
          // badge). Sólida si está activa, punteada si está pendiente. Tercer nivel del plan.
          const yEntry = py(t.entry);
          if (yEntry != null) {
            ctx.strokeStyle = "#a29bfe"; ctx.lineWidth = 1.6;
            ctx.setLineDash(pend ? [6, 4] : []);
            ctx.beginPath(); ctx.moveTo(0, yEntry); ctx.lineTo(W, yEntry); ctx.stroke();
            ctx.setLineDash([]);
            pill(placeL(yEntry - 16), `Entrada ${fmtPrice(t.entry)}`, "#cfc9ff",
              { font: "bold 10px -apple-system, sans-serif" });
            ctx.globalAlpha = 1;
            // Badge: R:R real + estado (⏳ en vigilancia / ● activo). Es escenario, no orden.
            const rr = (typeof t.rr === "number") ? t.rr.toFixed(1) : t.rr;
            const estado = pend ? "⏳ en vigilancia" : "● activo";
            const reg = outReg ? " · ⚠ fuera de régimen" : "";
            // CDC (cambio de carácter) como confirmación del plan (hipótesis 1h).
            const cdcTag = t.cdc_status === "confirmado" ? " · ✓ CDC"
              : t.cdc_status === "vencido" ? " · ✕ CDC venció"
              : t.cdc_status ? " · ⏳ CDC" : "";
            pill(placeR(yEntry - 8), `R:R ${rr} · ${estado}${reg}${cdcTag}`,
              outReg ? "#f5a623" : (pend ? "#a29bfe" : "#16c784"),
              { right: true, font: "bold 10px -apple-system, sans-serif" });
          }
          ctx.globalAlpha = 1;
        }

        // --- Capa: divergencias precio vs RSI (alcista verde / bajista roja) ---
        if (show.div && D.div && D.div.length) {
          ctx.textBaseline = "top"; ctx.font = "bold 9px -apple-system, sans-serif";
          D.div.forEach((dv) => {
            const x1 = tx(dv.t1), x2 = tx(dv.t2), y1 = py(dv.p1), y2 = py(dv.p2);
            if (x1 == null || x2 == null || y1 == null || y2 == null) return;
            const col = dv.bullish ? "#16c784" : "#ea3943";
            // Línea entre los dos pivotes.
            ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.setLineDash([]);
            ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
            // Puntos en cada pivote.
            ctx.fillStyle = col;
            ctx.beginPath(); ctx.arc(x1, y1, 2.6, 0, Math.PI * 2); ctx.fill();
            ctx.beginPath(); ctx.arc(x2, y2, 2.6, 0, Math.PI * 2); ctx.fill();
            // Etiqueta junto al segundo pivote (abajo si alcista, arriba si bajista),
            // con anti-solape para no encimarse con otras etiquetas de divergencia.
            const label = dv.bullish ? "Div ▲" : "Div ▼";
            const lw = ctx.measureText(label).width;
            const ly = placeD(dv.bullish ? y2 + 4 : y2 - 14);
            let lx = x2 - lw / 2;
            lx = Math.max(2, Math.min(W - lw - 2, lx));
            ctx.fillStyle = col; ctx.fillText(label, lx, ly);
          });
        }
      });
    }
  }
  class SMCPaneView {
    constructor(src) { this._src = src; this._renderer = new SMCRenderer(src); }
    update() {}
    renderer() { return this._renderer; }
    zOrder() { return "bottom"; }   // detrás de las velas
  }
  class SMCPrimitive {
    constructor() { this._data = null; this._views = [new SMCPaneView(this)]; }
    attached(p) { this._series = p.series; this._chart = p.chart; this._requestUpdate = p.requestUpdate; }
    detached() { this._series = null; this._chart = null; }
    setData(d) { this._data = d; if (this._requestUpdate) this._requestUpdate(); }
    updateAllViews() { this._views.forEach((v) => v.update()); }
    paneViews() { return this._views; }
  }

  // --- Indicadores (Vol / RSI / ADX) ---------------------------------
  // Estado global (mismo para todos los pares), recordado en localStorage.
  const IND_KEY = "nexus_trading_ind";
  // TP/SL (la capa del PLAN) parte encendida: es el corazón del indicador y ahí
  // viven las etiquetas de régimen y CDC del badge.
  const IND_DEFAULTS = { vol: true, rsi: false, adx: false, ribbon: false, levels: false, tpsl: true, div: false, htf: false };
  let indState = (() => {
    try { return Object.assign({}, IND_DEFAULTS, JSON.parse(localStorage.getItem(IND_KEY) || "{}")); }
    catch (e) { return Object.assign({}, IND_DEFAULTS); }
  })();
  function emaArr(values, period) {
    const k = 2 / (period + 1), out = [];
    for (let i = 0; i < values.length; i++) out.push(i === 0 ? values[0] : values[i] * k + out[i - 1] * (1 - k));
    return out;
  }
  function luxShow() { return { ribbon: indState.ribbon, levels: indState.levels, tpsl: indState.tpsl, div: indState.div, htf: indState.htf }; }
  function saveIndState() { try { localStorage.setItem(IND_KEY, JSON.stringify(indState)); } catch (e) {} }

  function rsiCalc(closes, p) {
    const n = closes.length, out = new Array(n).fill(null);
    if (n <= p) return out;
    let g = 0, l = 0;
    for (let i = 1; i <= p; i++) { const d = closes[i] - closes[i - 1]; if (d >= 0) g += d; else l -= d; }
    let ag = g / p, al = l / p;
    out[p] = 100 - 100 / (1 + (al === 0 ? 1e9 : ag / al));
    for (let i = p + 1; i < n; i++) {
      const d = closes[i] - closes[i - 1];
      ag = (ag * (p - 1) + (d > 0 ? d : 0)) / p;
      al = (al * (p - 1) + (d < 0 ? -d : 0)) / p;
      out[i] = 100 - 100 / (1 + (al === 0 ? 1e9 : ag / al));
    }
    return out;
  }

  function adxCalc(h, l, c, p) {
    const n = h.length, out = new Array(n).fill(null);
    if (n < 2 * p + 1) return out;
    const tr = [0], pdm = [0], ndm = [0];
    for (let i = 1; i < n; i++) {
      const up = h[i] - h[i - 1], dn = l[i - 1] - l[i];
      pdm.push(up > dn && up > 0 ? up : 0);
      ndm.push(dn > up && dn > 0 ? dn : 0);
      tr.push(Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1])));
    }
    let atr = 0, sp = 0, sn = 0;
    for (let i = 1; i <= p; i++) { atr += tr[i]; sp += pdm[i]; sn += ndm[i]; }
    const dx = new Array(n).fill(null);
    for (let i = p + 1; i < n; i++) {
      atr = atr - atr / p + tr[i]; sp = sp - sp / p + pdm[i]; sn = sn - sn / p + ndm[i];
      const pdi = atr ? 100 * sp / atr : 0, ndi = atr ? 100 * sn / atr : 0, sum = pdi + ndi;
      dx[i] = sum ? 100 * Math.abs(pdi - ndi) / sum : 0;
    }
    let adxv = null, cnt = 0, acc = 0;
    for (let i = p + 1; i < n; i++) {
      if (dx[i] == null) continue;
      if (adxv == null) { acc += dx[i]; cnt++; if (cnt === p) { adxv = acc / p; out[i] = adxv; } }
      else { adxv = (adxv * (p - 1) + dx[i]) / p; out[i] = adxv; }
    }
    return out;
  }

  // (Re)crea las series de indicadores de una tarjeta según indState.
  function buildIndicators(card) {
    if (!card.chart || !window.LightweightCharts) return;
    const LC = window.LightweightCharts;
    card.ind = card.ind || {};
    ["vol", "rsi", "adx"].forEach((k) => {
      if (card.ind[k]) { try { card.chart.removeSeries(card.ind[k]); } catch (e) {} card.ind[k] = null; }
    });
    if (indState.vol) {
      const v = card.chart.addSeries(LC.HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" }, 0);
      v.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
      card.ind.vol = v;
    }
    let pane = 1;
    if (indState.rsi) {
      const r = card.chart.addSeries(LC.LineSeries, { color: "#a29bfe", lineWidth: 1, priceLineVisible: false,
        priceFormat: { type: "price", precision: 1, minMove: 0.1 } }, pane);
      [[70, "rgba(234,57,67,0.45)"], [30, "rgba(22,199,132,0.45)"], [50, "rgba(139,147,167,0.3)"]].forEach(
        ([pr, co]) => r.createPriceLine({ price: pr, color: co, lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true }));
      card.ind.rsi = r; pane++;
    }
    if (indState.adx) {
      const a = card.chart.addSeries(LC.LineSeries, { color: "#f5a623", lineWidth: 1, priceLineVisible: false,
        priceFormat: { type: "price", precision: 1, minMove: 0.1 } }, pane);
      a.createPriceLine({ price: 25, color: "rgba(139,147,167,0.4)", lineWidth: 1, lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true });
      card.ind.adx = a; pane++;
    }
    const panes = card.chart.panes();
    for (let i = 1; i < panes.length; i++) { try { panes[i].setHeight(card.expanded ? 130 : 84); } catch (e) {} }
    setIndicatorData(card);
  }

  function _ohlc(card) {
    const cs = card.candles || [];
    const closes = cs.map((c) => c.c), highs = cs.map((c) => c.h), lows = cs.map((c) => c.l);
    if (card.lastPrice != null && cs.length) {
      const i = cs.length - 1;
      closes[i] = card.lastPrice;
      highs[i] = Math.max(highs[i], card.lastPrice);
      lows[i] = Math.min(lows[i], card.lastPrice);
    }
    return { cs, closes, highs, lows };
  }

  function setIndicatorData(card) {
    if (!card.ind) return;
    const { cs, closes, highs, lows } = _ohlc(card);
    if (!cs.length) return;
    const ts = (c) => Math.floor(c.t / 1000);
    if (card.ind.vol) {
      card.ind.vol.setData(cs.map((c, i) => ({ time: ts(c), value: c.v,
        color: (i === cs.length - 1 ? card.lastPrice ?? c.c : c.c) >= c.o ? "rgba(22,199,132,0.5)" : "rgba(234,57,67,0.5)" })));
    }
    if (card.ind.rsi) {
      const r = rsiCalc(closes, 14);
      card.ind.rsi.setData(cs.map((c, i) => (r[i] == null ? null : { time: ts(c), value: r[i] })).filter(Boolean));
    }
    if (card.ind.adx) {
      const a = adxCalc(highs, lows, closes, 14);
      card.ind.adx.setData(cs.map((c, i) => (a[i] == null ? null : { time: ts(c), value: a[i] })).filter(Boolean));
    }
  }

  function updateIndicatorsLast(card) {
    if (!card.ind || card.lastPrice == null) return;
    const { cs, closes, highs, lows } = _ohlc(card);
    if (!cs.length) return;
    const t = Math.floor(cs[cs.length - 1].t / 1000);
    if (card.ind.vol) {
      const c = cs[cs.length - 1];
      card.ind.vol.update({ time: t, value: c.v, color: card.lastPrice >= c.o ? "rgba(22,199,132,0.5)" : "rgba(234,57,67,0.5)" });
    }
    if (card.ind.rsi) { const r = rsiCalc(closes, 14); const v = r[r.length - 1]; if (v != null) card.ind.rsi.update({ time: t, value: v }); }
    if (card.ind.adx) { const a = adxCalc(highs, lows, closes, 14); const v = a[a.length - 1]; if (v != null) card.ind.adx.update({ time: t, value: v }); }
  }

  // Botones de toggle por tarjeta; el estado es global y se aplica a todos.
  // Indicadores en panes (recrean series) y capas Lux (solo redibujan el primitive).
  const TOGGLE_GROUPS = {
    ".ind-toggles": [["vol", "Vol"], ["rsi", "RSI"], ["adx", "ADX"]],
    ".lux-toggles": [["ribbon", "Cinta"], ["levels", "Niveles"], ["tpsl", "TP/SL"], ["div", "Diverg."], ["htf", "Solo 4h/1D"]],
  };
  const PANE_INDICATORS = new Set(["vol", "rsi", "adx"]);

  function buildToggles(card) {
    Object.entries(TOGGLE_GROUPS).forEach(([sel, items]) => {
      const box = card.node.querySelector(sel);
      if (!box) return;
      box.innerHTML = "";
      items.forEach(([k, label]) => {
        const b = document.createElement("button");
        b.className = "tf-btn ind-btn" + (indState[k] ? " active" : "");
        b.textContent = label;
        b.dataset.ind = k;
        b.addEventListener("click", () => {
          indState[k] = !indState[k];
          saveIndState();
          if (PANE_INDICATORS.has(k)) Object.values(cards).forEach((c) => buildIndicators(c));
          else Object.values(cards).forEach((c) => { computeRibbon(c); pushPrim(c); });
          refreshToggleUI();
        });
        box.appendChild(b);
      });
    });
  }
  function refreshToggleUI() {
    Object.values(cards).forEach((c) => {
      c.node.querySelectorAll(".ind-btn").forEach((b) => {
        b.classList.toggle("active", !!indState[b.dataset.ind]);
      });
    });
  }

  // --- Formateo ------------------------------------------------------
  function fmtPrice(n) {
    if (n >= 1000) return n.toLocaleString("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (n >= 1) return n.toLocaleString("es", { maximumFractionDigits: 4 });
    return n.toLocaleString("es", { maximumFractionDigits: 6 });
  }
  function fmtQty(n) {
    return n.toLocaleString("es", { maximumFractionDigits: 4 });
  }
  function fmtCompact(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return n.toFixed(2);
  }

  // --- Estado de conexión -------------------------------------------
  function setStatus(state) {
    statusDot.className = "dot";
    if (state === "ok") { statusDot.classList.add("ok"); statusText.textContent = "en vivo"; }
    else if (state === "bad") { statusDot.classList.add("bad"); statusText.textContent = "error de datos"; }
    else { statusText.textContent = "conectando…"; }
  }

  // --- Crear / obtener la tarjeta de un instrumento ------------------
  function getCard(symbol, label) {
    if (cards[symbol]) return cards[symbol];
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.querySelector(".ic-symbol").textContent = label || symbol;
    container.appendChild(node);
    const chartEl = node.querySelector(".chart");
    const card = { node, chartEl, symbol, lastPrice: null, timeframe: DEFAULT_TF,
                   candles: [], bars: [], smc: null, priceLines: [], fitted: false };
    cards[symbol] = card;

    createChart(card);
    card.ind = {};
    buildToggles(card);
    buildIndicators(card);     // indicadores según el estado guardado
    buildTimeframeSelector(symbol, card);
    setupExpand(card);
    loadCandles(symbol, card); // primera carga
    loadSMC(symbol, card);     // análisis SMC en vivo
    card.refreshTimer = setInterval(() => loadCandles(symbol, card), CANDLE_REFRESH_MS);
    card.smcTimer = setInterval(() => loadSMC(symbol, card), SMC_REFRESH_MS);
    return card;
  }

  // Pausa/reanuda los timers de una tarjeta (las ocultas no consumen red ni CPU).
  function pauseCard(card) {
    if (card.refreshTimer) { clearInterval(card.refreshTimer); card.refreshTimer = null; }
    if (card.smcTimer) { clearInterval(card.smcTimer); card.smcTimer = null; }
  }
  function resumeCard(card) {
    if (!card.refreshTimer) {
      loadCandles(card.symbol, card);
      card.refreshTimer = setInterval(() => loadCandles(card.symbol, card), CANDLE_REFRESH_MS);
    }
    if (!card.smcTimer) {
      loadSMC(card.symbol, card);
      card.smcTimer = setInterval(() => loadSMC(card.symbol, card), SMC_REFRESH_MS);
    }
  }

  // Muestra SOLO el gráfico del símbolo elegido; oculta y pausa los demás.
  function setActiveSymbol(symbol, label) {
    if (!symbol) return;
    activeSymbol = symbol;
    const card = getCard(symbol, label || lastLabels[symbol]);  // se crea visible (ancho OK)
    Object.values(cards).forEach((c) => {
      const on = c.symbol === symbol;
      c.node.hidden = !on;
      if (on) resumeCard(c); else pauseCard(c);
    });
    if (cryptoSelect && cryptoSelect.value !== symbol) cryptoSelect.value = symbol;
    return card;
  }

  // Rellena el dropdown con los instrumentos que manda el backend (una vez / al cambiar).
  function populateSelector(insts) {
    const names = Object.keys(insts);
    if (!names.length) return;
    const sig = names.join(",");
    if (cryptoSelect.dataset.sig === sig) return;   // sin cambios → no rehacer
    cryptoSelect.dataset.sig = sig;
    cryptoSelect.innerHTML = "";
    names.forEach((name) => {
      lastLabels[name] = (insts[name] && insts[name].label) || name;
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = lastLabels[name];
      cryptoSelect.appendChild(opt);
    });
    if (!activeSymbol || !insts[activeSymbol]) setActiveSymbol(names[0]);
    else cryptoSelect.value = activeSymbol;
  }

  if (cryptoSelect) {
    cryptoSelect.addEventListener("change", () => setActiveSymbol(cryptoSelect.value));
  }

  // Encuadre por defecto: las últimas ~220 velas (el resto queda para scroll).
  function frameRecent(card) {
    if (!card.chart || !card.bars.length) return;
    const n = card.bars.length;
    if (n > 240) card.chart.timeScale().setVisibleLogicalRange({ from: n - 220, to: n + 4 });
    else card.chart.timeScale().fitContent();
  }

  // Leyenda OHLC (estilo TradingView): la vela bajo el cursor, o la última
  // (con el precio en vivo) cuando el cursor no está sobre el gráfico.
  function renderLegend(card, t) {
    const el = card.legendEl;
    if (!el) return;
    const cs = card.candles || [];
    if (!cs.length) { el.textContent = ""; return; }
    let c = cs[cs.length - 1];
    if (t != null) {
      const i = card.barIndex ? card.barIndex.get(t) : null;
      if (i == null) { el.textContent = ""; return; }
      c = cs[i];
    } else if (card.lastPrice != null) {
      c = { o: c.o, h: Math.max(c.h, card.lastPrice), l: Math.min(c.l, card.lastPrice),
            c: card.lastPrice, v: c.v };
    }
    const pct = c.o ? (c.c - c.o) / c.o * 100 : 0;
    el.innerHTML = `O <b>${fmtPrice(c.o)}</b> H <b>${fmtPrice(c.h)}</b> ` +
      `L <b>${fmtPrice(c.l)}</b> C <b>${fmtPrice(c.c)}</b> ` +
      `<span class="${pct >= 0 ? "up" : "down"}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</span>` +
      ` · Vol <b>${fmtCompact(c.v || 0)}</b>`;
  }

  // --- Gráfico interactivo (TradingView Lightweight Charts) ----------
  function createChart(card) {
    if (!window.LightweightCharts) return;
    const LC = window.LightweightCharts;
    const chart = LC.createChart(card.chartEl, {
      autoSize: true,
      // Sin el logo/link de TradingView dentro del canvas; la atribución de
      // Lightweight Charts (Apache-2.0) va en el pie de la página.
      layout: { background: { color: "transparent" }, textColor: "#8b93a7",
                fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif",
                attributionLogo: false },
      grid: { vertLines: { color: "rgba(255,255,255,0.04)" }, horzLines: { color: "rgba(255,255,255,0.04)" } },
      crosshair: { mode: LC.CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#262b38" },
      timeScale: { borderColor: "#262b38", timeVisible: true, secondsVisible: false },
      localization: { locale: "es" },
    });
    const series = chart.addSeries(LC.CandlestickSeries, {
      upColor: "#16c784", downColor: "#ea3943", borderVisible: false,
      wickUpColor: "#16c784", wickDownColor: "#ea3943",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    const prim = new SMCPrimitive();
    series.attachPrimitive(prim);
    card.chart = chart;
    card.series = series;
    card.smcPrim = prim;

    // Leyenda OHLC superpuesta (arriba a la izquierda del gráfico).
    const legend = document.createElement("div");
    legend.className = "chart-legend";
    card.chartEl.appendChild(legend);
    card.legendEl = legend;
    card.legendLast = true;   // sin cursor encima, la leyenda sigue a la última vela
    chart.subscribeCrosshairMove((param) => {
      const t = param && param.time != null ? param.time : null;
      card.legendLast = t == null;
      renderLegend(card, t);
    });

    // Botón «ir al presente»: aparece cuando el usuario se desplazó hacia atrás.
    const goBtn = document.createElement("button");
    goBtn.className = "goto-now";
    goBtn.type = "button";
    goBtn.title = "Ir al presente";
    goBtn.setAttribute("aria-label", "Ir al presente");
    goBtn.textContent = "»";
    goBtn.addEventListener("click", () => chart.timeScale().scrollToRealTime());
    const wrap = card.node.querySelector(".chart-wrap");
    if (wrap) wrap.appendChild(goBtn);
    chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      const n = card.bars.length;
      goBtn.classList.toggle("show", !!(r && n && r.to < n - 2));
      // Cerca del borde izquierdo → trae más historia (scroll años hacia atrás).
      if (r && r.from < 10 && card.hasMore && !card.loadingOlder) loadOlder(card);
    });

    // Doble clic sobre el gráfico = reencuadrar las últimas velas (reset).
    card.chartEl.addEventListener("dblclick", () => frameRecent(card));
  }

  // Decimales del eje de precio según la magnitud (BTC 2 dec; DOGE necesita 6).
  function applyPriceFormat(card, price) {
    if (!card.series || !price) return;
    const ax = Math.abs(price);
    const prec = ax >= 10 ? 2 : ax >= 1 ? 4 : ax >= 0.1 ? 5 : ax >= 0.01 ? 6 : 8;
    if (card._pricePrec === prec) return;
    card._pricePrec = prec;
    card.series.applyOptions({ priceFormat: { type: "price", precision: prec, minMove: Math.pow(10, -prec) } });
  }

  // Actualiza la última vela con el precio en vivo del SSE.
  function liveUpdate(card) {
    if (!card.series || !card.bars.length || card.lastPrice == null) return;
    const last = card.bars[card.bars.length - 1];
    card.series.update({
      time: last.time, open: last.open,
      high: Math.max(last.high, card.lastPrice),
      low: Math.min(last.low, card.lastPrice),
      close: card.lastPrice,
    });
    updateIndicatorsLast(card);
    if (indState.ribbon) { computeRibbon(card); pushPrim(card); }
    if (card.legendLast) renderLegend(card, null);   // leyenda viva con el último precio
  }

  // Pide el análisis SMC en vivo y lo proyecta como price lines + primitive.
  async function loadSMC(symbol, card) {
    const tf = card.timeframe;
    try {
      const r = await fetch(`api/smc?instrument=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(tf)}`);
      if (!r.ok) return;
      const j = await r.json();
      if (card.timeframe !== tf) return;
      card.smc = j;
      // Trades ACTIVOS del forward-test (para dibujar la cajita acotada del trade).
      try {
        const sj = await fetch("/m/journal/api/setups").then((r) => (r.ok ? r.json() : null));
        card.trades = ((sj && sj.setups) || []).filter((x) => x.status === "activo" && x.pair === symbol);
        // El ancho de la caja lo calcula el primitive con xAt() (interpola por tiempo
        // real entrada→ahora), así que ya no anclamos a barras acá.
      } catch (e) { /* sin trades activos */ }
      applySMC(card);
      renderSMCPanel(card);
    } catch (err) { /* mantenemos el análisis previo */ }
  }

  function applySMC(card) {
    if (!card.series || !window.LightweightCharts) return;
    const LC = window.LightweightCharts;
    // Niveles de liquidez y equilibrio como price lines (se alinean solas).
    card.priceLines.forEach((pl) => card.series.removePriceLine(pl));
    card.priceLines = [];
    const addLine = (price, color, title) => {
      if (!price) return;
      card.priceLines.push(card.series.createPriceLine({
        price, color, lineWidth: 1, lineStyle: LC.LineStyle.Dashed,
        axisLabelVisible: true, title,
      }));
    };
    const rng = card.smc && card.smc.range;
    if (rng) {
      addLine(rng.strong_high, "#ea3943", "Strong High");
      addLine(rng.weak_low, "#16c784", "Weak Low");
      addLine(rng.eq, "#a29bfe", "EQ 50%");
    }
    pushPrim(card);
  }

  // Recalcula la cinta de tendencia (EMA 21/55) desde las velas, con el precio en vivo.
  function computeRibbon(card) {
    const cs = card.candles || [];
    if (!cs.length) { card.ribbon = []; return; }
    const closes = cs.map((c) => c.c);
    if (card.lastPrice != null) closes[closes.length - 1] = card.lastPrice;
    const f = emaArr(closes, 21), s = emaArr(closes, 55);
    card.ribbon = cs.map((c, i) => ({ t: Math.floor(c.t / 1000), f: f[i], s: s[i] }));
  }

  // Empuja al primitive todo lo que dibuja: overlay SMC + cinta + niveles + TP/SL.
  // Divergencias precio vs RSI: alcista (precio mínimo más bajo + RSI más alto) y
  // bajista (precio máximo más alto + RSI más bajo). Se calculan sobre velas cerradas
  // (los pivotes necesitan barras a ambos lados → anti-repintado natural).
  function computeDivergences(card) {
    card.div = [];
    const cs = card.candles || [];
    if (cs.length < 40) return;
    const closes = cs.map((c) => c.c), highs = cs.map((c) => c.h), lows = cs.map((c) => c.l);
    const rsi = rsiCalc(closes, 14);
    const L = 3;                       // barras a cada lado para confirmar un pivote
    const phs = [], pls = [];
    for (let i = L; i < cs.length - L; i++) {
      let isH = true, isL = true;
      for (let k = 1; k <= L; k++) {
        if (highs[i] <= highs[i - k] || highs[i] < highs[i + k]) isH = false;
        if (lows[i] >= lows[i - k] || lows[i] > lows[i + k]) isL = false;
      }
      if (isH && rsi[i] != null) phs.push(i);
      if (isL && rsi[i] != null) pls.push(i);
    }
    const MAXBARS = 60, out = [];
    for (let a = 0; a < phs.length - 1; a++) {           // bajistas (en los máximos)
      const i = phs[a], j = phs[a + 1];
      if (j - i > MAXBARS) continue;
      if (highs[j] > highs[i] && rsi[j] < rsi[i])
        out.push({ bullish: false, t1: cs[i].t, p1: highs[i], t2: cs[j].t, p2: highs[j] });
    }
    for (let a = 0; a < pls.length - 1; a++) {           // alcistas (en los mínimos)
      const i = pls[a], j = pls[a + 1];
      if (j - i > MAXBARS) continue;
      if (lows[j] < lows[i] && rsi[j] > rsi[i])
        out.push({ bullish: true, t1: cs[i].t, p1: lows[i], t2: cs[j].t, p2: lows[j] });
    }
    // Las más recientes (para no saturar el gráfico).
    card.div = out.sort((x, y) => y.t2 - x.t2).slice(0, 4);
  }

  function pushPrim(card) {
    const bars = card.bars || [];
    const barMeta = bars.length
      ? { lastT: bars[bars.length - 1].time,
          interval: bars.length > 1 ? bars[bars.length - 1].time - bars[bars.length - 2].time : 900 }
      : null;
    if (card.smcPrim) card.smcPrim.setData({
      smc: card.smc, ribbon: card.ribbon || [], div: card.div || [],
      trades: card.trades || [], show: luxShow(), barMeta,
    });
  }

  // --- Selector de temporalidad --------------------------------------
  function buildTimeframeSelector(symbol, card) {
    const sel = card.node.querySelector(".tf-selector");
    if (!sel) return;
    sel.innerHTML = "";
    TIMEFRAMES.forEach((tf) => {
      const btn = document.createElement("button");
      btn.className = "tf-btn" + (tf === card.timeframe ? " active" : "");
      btn.textContent = tf;
      btn.dataset.tf = tf;
      btn.setAttribute("aria-pressed", tf === card.timeframe ? "true" : "false");
      btn.addEventListener("click", () => {
        if (card.timeframe === tf) return;
        card.timeframe = tf;
        card.candles = [];     // reset: no mezclar velas de otra temporalidad
        card.hasMore = false;
        card.loadingOlder = false;
        sel.querySelectorAll(".tf-btn").forEach((b) => {
          const on = b.dataset.tf === tf;
          b.classList.toggle("active", on);
          b.setAttribute("aria-pressed", on ? "true" : "false");
        });
        card.smc = null;      // el SMC depende de la TF seleccionada (estructura/FVG)
        card.fitted = false;  // reajustamos la vista a la nueva resolución
        loadCandles(symbol, card);
        loadSMC(symbol, card);
      });
      sel.appendChild(btn);
    });
  }

  // --- Expandir / colapsar el gráfico (pantalla completa) ------------
  function setupExpand(card) {
    const wrap = card.node.querySelector(".chart-wrap");
    const btn = card.node.querySelector(".chart-expand");
    if (!btn || !wrap) return;
    btn.addEventListener("click", () => {
      const open = wrap.classList.toggle("expanded");
      card.expanded = open;
      document.body.classList.toggle("chart-open", open);
      btn.textContent = open ? "✕" : "⤢";
      btn.title = open ? "Cerrar" : "Expandir";
      // autoSize redimensiona solo; ajustamos el alto de los subpanes y reencuadramos.
      setTimeout(() => {
        if (!card.chart) return;
        const panes = card.chart.panes();
        for (let i = 1; i < panes.length; i++) { try { panes[i].setHeight(open ? 130 : 84); } catch (e) {} }
        card.chart.timeScale().scrollToRealTime();
      }, 60);
    });
  }

  // Fusiona velas por timestamp (lo nuevo pisa lo viejo), ordenado por tiempo.
  function mergeCandles(a, b) {
    const by = new Map();
    for (const c of a) by.set(c.t, c);
    for (const c of b) by.set(c.t, c);
    return Array.from(by.values()).sort((x, y) => x.t - y.t);
  }

  function rebuildBars(card) {
    card.bars = card.candles.map((c) => ({
      time: Math.floor(c.t / 1000), open: c.o, high: c.h, low: c.l, close: c.c,
    }));
    card.barIndex = new Map(card.bars.map((b, i) => [b.time, i]));
    if (card.bars.length) applyPriceFormat(card, card.bars[card.bars.length - 1].close);
  }

  // Pide al backend el tramo RECIENTE y lo carga/fusiona en el gráfico. Conserva
  // la historia ya traída por scroll (loadOlder); en los refrescos solo redibuja
  // si apareció una vela nueva (si no, basta liveUpdate → barato con años cargados).
  async function loadCandles(symbol, card) {
    const tf = card.timeframe;
    try {
      const r = await fetch(`api/candles?instrument=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(tf)}&limit=1500`);
      if (!r.ok) return;
      const j = await r.json();
      if (card.timeframe !== tf || !Array.isArray(j.candles) || !card.series) return;
      const first = !card.candles.length;
      const prevLen = card.candles.length;
      card.candles = first ? j.candles : mergeCandles(card.candles, j.candles);
      if (first) card.hasMore = !!j.has_more;   // ¿hay historia más vieja para scroll?
      if (first || card.candles.length !== prevLen) {
        rebuildBars(card);
        const range = card.chart.timeScale().getVisibleLogicalRange();
        card.series.setData(card.bars);
        if (card.fitted && range) card.chart.timeScale().setVisibleLogicalRange(range);
        else { frameRecent(card); card.fitted = true; }
        if (card.legendLast) renderLegend(card, null);
        setIndicatorData(card);
        computeRibbon(card);
        computeDivergences(card);
        pushPrim(card);
      }
      liveUpdate(card);
    } catch (err) {
      /* dejamos las velas que ya teníamos */
    }
  }

  // Back-load: trae el tramo ANTERIOR al más viejo cargado (scroll a la izquierda),
  // hasta el fondo de la historia. Mantiene la vista anclada desplazando el rango
  // lógico por las velas agregadas adelante.
  async function loadOlder(card) {
    if (card.loadingOlder || !card.hasMore || !card.candles.length) return;
    card.loadingOlder = true;
    const tf = card.timeframe;
    const before = card.candles[0].t;
    try {
      const r = await fetch(`api/candles?instrument=${encodeURIComponent(card.symbol)}&timeframe=${encodeURIComponent(tf)}&before=${before}&limit=3000`);
      if (!r.ok) return;
      const j = await r.json();
      if (card.timeframe !== tf || !Array.isArray(j.candles) || !card.series) return;
      const older = j.candles.filter((c) => c.t < before);
      card.hasMore = !!j.has_more && older.length > 0;
      if (!older.length) return;
      const added = older.length;
      card.candles = mergeCandles(older, card.candles);
      rebuildBars(card);
      const range = card.chart.timeScale().getVisibleLogicalRange();
      card.series.setData(card.bars);
      if (range) {
        card.chart.timeScale().setVisibleLogicalRange({ from: range.from + added, to: range.to + added });
      }
      setIndicatorData(card);
      computeRibbon(card);
      computeDivergences(card);
      pushPrim(card);
    } catch (err) {
      /* nada: reintenta en el próximo scroll */
    } finally {
      card.loadingOlder = false;
    }
  }

  // --- Render principal ----------------------------------------------
  // Auto-actualización: si llega un deploy nuevo (cambia state.version), la
  // página se recarga sola — la PWA abierta no vuelve a pedir app.js por sí
  // misma y quedaba corriendo código viejo.
  let appVersion = null;
  function checkVersion(v) {
    if (!v) return;
    if (appVersion == null) { appVersion = v; return; }
    if (v !== appVersion) window.location.reload();
  }

  function render(state) {
    checkVersion(state.version);
    if (state.upstream_ok) setStatus("ok");
    else if (Object.keys(state.instruments || {}).length) setStatus("bad");

    if (state.updated) {
      lastUpdateEl.textContent = new Date(state.updated).toLocaleTimeString("es");
    }

    const insts = state.instruments || {};
    populateSelector(insts);         // dropdown de criptos (un solo gráfico a la vez)
    const d = insts[activeSymbol];
    if (!d) return;
    const card = getCard(activeSymbol, d.label);
    if (card.node.hidden) setActiveSymbol(activeSymbol, d.label);
    renderTicker(card, d.ticker);    // fija card.lastPrice
    renderStats(card, d.ticker);
    renderSMCStats(card);            // análisis SMC en vivo (reemplaza al libro)
    liveUpdate(card);                // mueve la última vela con el precio en vivo
  }

  function renderTicker(card, t) {
    if (!t) return;
    const priceEl = card.node.querySelector(".ic-price");
    const newPrice = t.last;
    if (card.lastPrice !== null && newPrice !== card.lastPrice) {
      const dir = newPrice > card.lastPrice ? "flash-up" : "flash-down";
      priceEl.classList.remove("flash-up", "flash-down");
      void priceEl.offsetWidth; // reinicia la animación
      priceEl.classList.add(dir);
      setTimeout(() => priceEl.classList.remove(dir), 350);
    }
    card.lastPrice = newPrice;
    priceEl.textContent = fmtPrice(newPrice);

    const changeEl = card.node.querySelector(".ic-change");
    const pct = (t.change || 0) * 100;
    changeEl.textContent = (pct >= 0 ? "▲ " : "▼ ") + Math.abs(pct).toFixed(2) + "%";
    changeEl.className = "ic-change " + (pct >= 0 ? "up" : "down");
  }

  function renderStats(card, t) {
    if (!t) return;
    card.node.querySelector(".ic-high").textContent = fmtPrice(t.high);
    card.node.querySelector(".ic-low").textContent = fmtPrice(t.low);
    card.node.querySelector(".ic-vol").textContent = fmtCompact(t.volume);
  }

  // --- Análisis SMC en vivo (panel que reemplaza al libro de órdenes) ------
  // Sesión de trading activa (horas UTC, aprox.): útil para saber el contexto.
  function activeSession() {
    const h = new Date().getUTCHours();
    const london = h >= 7 && h < 16, ny = h >= 12 && h < 21, asia = h >= 0 && h < 9;
    if (london && ny) return { label: "Londres + NY (solape)", active: true };
    if (ny) return { label: "Nueva York", active: true };
    if (london) return { label: "Londres", active: true };
    if (asia) return { label: "Asia", active: true };
    return { label: "Fuera de sesión", active: false };
  }

  function renderSMCStats(card) {
    const n = card.node, smc = card.smc, price = card.lastPrice;
    const set = (cls, html, klass) => {
      const e = n.querySelector(cls); if (!e) return;
      e.innerHTML = html; e.className = "v " + cls.slice(1) + (klass ? " " + klass : "");
    };
    // Régimen (VIX + ADX) — semáforo del filtro de la investigación (forward-test).
    const rg = smc && smc.regime;
    if (rg) {
      const vix = rg.vix == null ? "s/d" : rg.vix;
      const adx = rg.adx == null ? "s/d" : rg.adx;
      const mark = rg.ok === true ? "✓ favorable" : rg.ok === false ? "✕ desfavorable" : "s/d";
      set(".smc-regime", `${mark} · VIX ${vix} · ADX ${adx}`,
        rg.ok === true ? "up" : rg.ok === false ? "down" : "");
    } else set(".smc-regime", "—");
    const rng = smc && smc.range;
    // Sesgo premium/descuento respecto al equilibrio (EQ), con el precio en vivo.
    if (rng && rng.eq && price) {
      const disc = price < rng.eq;
      const pct = (price - rng.eq) / rng.eq * 100;
      set(".smc-bias", (disc ? "Descuento" : "Premium") + " · " + (pct >= 0 ? "+" : "") + pct.toFixed(2) + "% vs EQ",
        disc ? "up" : "down");
    } else set(".smc-bias", "—");
    // Estructura: extremos del dealing range.
    if (rng) set(".smc-struct", "SH " + fmtPrice(rng.strong_high) + " · WL " + fmtPrice(rng.weak_low));
    else set(".smc-struct", "—");
    // Sesión activa.
    const ses = activeSession();
    set(".smc-session", ses.label, ses.active ? "up" : "");
    // POI válido más cercano al precio.
    const pois = (smc && smc.active_pois) || [];
    if (pois.length) {
      const p = pois.slice().sort((a, b) => Math.abs(a.dist_pct) - Math.abs(b.dist_pct))[0];
      const here = p.in_zone ? " · ● en zona" : "";
      set(".smc-poi-near", "POI " + p.tf + " " + (p.discount ? "desc." : "prem.") + " · " +
        (p.dist_pct > 0 ? "+" : "") + p.dist_pct + "%" + here, p.discount ? "up" : "down");
    } else set(".smc-poi-near", "sin POI válido cerca");
    // Setup vigente (plan TP/SL), con su confirmación CDC (cambio de carácter).
    const t = smc && smc.tpsl;
    if (t) {
      const est = t.state === "activo" ? "● activo" : "⏳ en vigilancia";
      const reg = t.regime_ok === false ? " · ⚠ fuera de régimen" : "";
      const cdc = t.cdc_status === "confirmado" ? " · ✓ CDC confirmado"
        : t.cdc_status === "vencido" ? " · ✕ CDC venció sin confirmar"
        : t.cdc_status ? " · ⏳ esperando CDC" : "";
      const slTxt = (typeof t.sl_pct === "number")
        ? " · SL −" + t.sl_pct.toFixed(1) + "%" + (t.sl_capped ? " (tope, excede estructura)" : "") : "";
      set(".smc-setup", "Plan " + t.tf + " " + (t.dir === "long" ? "▲ largo" : "▼ corto") +
        " · R:R " + t.rr + slTxt + " · " + est + reg + cdc, t.regime_ok === false ? "" : (t.dir === "long" ? "up" : "down"));
    } else set(".smc-setup", "sin plan en " + card.timeframe +
      " (sin R:R≥2 ahora) · los planes salen sobre todo en 1h/4h");
  }

  // --- Panel "POIs activos" ------------------------------------------
  function renderSMCPanel(card) {
    const el = card.node.querySelector(".smc-list");
    if (!el) return;
    const pois = (card.smc && card.smc.active_pois) || [];
    if (!pois.length) {
      el.innerHTML = '<div class="smc-empty">Sin POIs válidos cerca del precio ahora.</div>';
      return;
    }
    el.innerHTML = pois.map((p) => {
      const zona = p.discount ? "descuento" : "premium";
      const cls = p.discount ? "discount" : "premium";
      const dist = (p.dist_pct > 0 ? "+" : "") + p.dist_pct + "%";
      const here = p.in_zone ? '<span class="smc-here">● en zona</span>' : "";
      return `<div class="smc-poi ${cls}">
        <span class="smc-tf">POI ${p.tf}</span>
        <span class="smc-range">${fmtPrice(p.lo)}–${fmtPrice(p.hi)}</span>
        <span class="smc-zone">${zona}</span>
        <span class="smc-dist">${dist}</span>${here}
      </div>`;
    }).join("");
  }

  // El gráfico (Lightweight Charts) se redimensiona solo con autoSize.
  let lastState = null;

  // --- Conexión: SSE con respaldo a polling --------------------------
  function connectSSE() {
    const es = new EventSource("api/stream");
    es.onmessage = (e) => {
      try {
        lastState = JSON.parse(e.data);
        render(lastState);
      } catch (err) { /* ignoramos frames mal formados */ }
    };
    es.onerror = () => {
      setStatus("");
      // EventSource reintenta solo; si no, el respaldo de polling cubre.
    };
  }

  async function pollOnce() {
    try {
      const r = await fetch("api/state");
      lastState = await r.json();
      render(lastState);
    } catch (err) { setStatus("bad"); }
  }

  // --- Contador de cierre de vela (mm:ss / h:mm:ss) ------------------
  // Los límites de vela se alinean al epoch UTC (1m/5m/15m/1h/4h/1D), así que el
  // tiempo restante = duración_TF − (ahora_UTC mod duración_TF). Se ajusta solo al
  // cambiar de temporalidad (lee card.timeframe en cada tick).
  const TF_SECONDS = { "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600,
    "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200, "1D": 86400, "7D": 604800 };
  function fmtCountdown(s) {
    s = Math.max(0, Math.floor(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const p = (n) => String(n).padStart(2, "0");
    return h > 0 ? `${h}:${p(m)}:${p(sec)}` : `${p(m)}:${p(sec)}`;
  }
  function tickCountdowns() {
    const nowS = Date.now() / 1000;
    Object.values(cards).forEach((c) => {
      const el = c.node && c.node.querySelector(".ct-val");
      if (!el) return;
      const dur = TF_SECONDS[c.timeframe];
      if (!dur) { el.textContent = "—"; return; }
      el.textContent = fmtCountdown(dur - (nowS % dur));
    });
  }

  // Cargamos la config del módulo (temporalidades + default) y luego arrancamos
  // la conexión en vivo. Si la config falla, usamos los valores por defecto.
  async function init() {
    try {
      const cfg = await fetch("api/config").then((r) => r.json());
      if (Array.isArray(cfg.timeframes) && cfg.timeframes.length) TIMEFRAMES = cfg.timeframes;
      if (cfg.default_timeframe) DEFAULT_TF = cfg.default_timeframe;
    } catch (err) {
      /* nos quedamos con TIMEFRAMES/DEFAULT_TF por defecto */
    }

    // Arrancamos con SSE; además un polling lento de respaldo por si acaso.
    if (window.EventSource) {
      connectSSE();
    } else {
      pollOnce();
      setInterval(pollOnce, 3000);
    }
    setupAlerts();
    tickCountdowns();
    setInterval(tickCountdowns, 1000);   // contador de cierre de vela, en vivo
  }

  // --- Alertas push (reusa el web push ya cableado) ------------------
  function setupAlerts() {
    const btn = document.getElementById("alert-btn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      if (!window.NexusPush) { btn.textContent = "🔕 Push no soportado"; return; }
      btn.disabled = true;
      btn.textContent = "Activando…";
      try {
        await window.NexusPush.activar();
        btn.classList.add("on");
        btn.textContent = "🔔 Alertas activas";
      } catch (err) {
        btn.textContent = "🔕 " + (err && err.message ? err.message : "no se pudo activar");
        setTimeout(() => { btn.textContent = "🔔 Alertas SMC"; btn.disabled = false; }, 4000);
        return;
      }
      btn.disabled = false;
    });
  }

  init();
})();
