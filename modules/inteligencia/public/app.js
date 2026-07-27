/* Acción del precio — vista research del curso CreceTrader.
 *
 * Dibuja SOLO lo que tiene definición objetiva: la rejilla anclada en la apertura
 * anual, la apertura semanal y los pivotes confirmados. Lo que en el curso es
 * lectura visual —numerar fases I-V, trazar una directriz a mano— no está y no debe
 * agregarse: el propio material admite que cambiando los extremos de la directriz la
 * misma vela rompe o no rompe.
 *
 * Nada de acá es señal. La franja de aviso de arriba no es decorativa: es lo único
 * que impide leer esta pantalla como una recomendación.
 */
const $ = (id) => document.getElementById(id);
const API = "/m/inteligencia/api";

const state = { symbol: null, tf: "4h", horizonte: "medio", data: null, mapa: null,
                velas: [], chart: null, series: null, lineas: [], marcas: null,
                estructura: null, loadSeq: 0 };
const TF_PRINCIPAL = { corto: "1h", medio: "4h", largo: "1d" };
const LABEL_ALINEACION = {
  alineado: "alineado",
  principal_alineado_sin_sincronismo: "principal alineado · sin sincronismo",
  principal_no_alineado: "principal no alineado",
  contexto_superior_mixto_o_indefinido: "contexto superior mixto / indefinido",
};
const LABEL_PIERNA = {
  correccion: "corrección",
  extension: "extensión",
  mas_alla_origen: "precio más allá del origen",
  sin_datos: "sin datos",
};

const fmt = (v, d = 2) => (v == null || !Number.isFinite(Number(v))) ? "—"
  : Number(v).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d });
const signed = (v, suf = "") => v == null ? "—" : `${v > 0 ? "+" : ""}${fmt(v, 2)}${suf}`;

// Decimales según magnitud: BTC necesita 2 y DOGE 6. Un formato fijo convierte el
// precio de una moneda barata en "0.00", que es peor que no mostrarlo.
function decimales(px) {
  const a = Math.abs(px || 0);
  return a >= 10 ? 2 : a >= 1 ? 4 : a >= 0.1 ? 5 : a >= 0.01 ? 6 : 8;
}


/* Cola en vivo directo desde Binance para el grafico.
 *
 * Sin esto el grafico quedaba con 13,3 minutos de atraso —medido: push cada 10 min mas
 * la cache de 5 min del modulo— y Hugo lo vio como un precio congelado. El navegador SI
 * puede hablar con Binance: el HTTP 451 es del datacenter de Railway, no de la
 * ubicacion del que mira.
 *
 * Stream COMBINADO porque el de klines calla con el mercado quieto (medido: 0 frames en
 * 10 s en 15m) mientras `bookTicker` manda 65-740 por segundo. Los frames de bookTicker
 * se descartan ANTES de parsear; los de kline nunca, que son los autoritativos.
 *
 * LO QUE NO CAMBIA: los paneles de abajo se calculan en el SERVIDOR y siguen con el
 * push. Medido que no les afecta —BTC se mueve 0,072% en 15 min y "desde la apertura
 * anual" pasa de -26,01% a -25,95%— pero la edad se declara igual.
 */
const vivo = {
  ws: null, stream: null, frames: 0, ultimo: 0, _bt: 0, intentos: 0, timer: null,

  conectar(stream) {
    if (this.stream === stream && this.ws && this.ws.readyState <= 1) return;
    this.cerrar();
    this.stream = stream;
    this.frames = 0;
    const partes = `${stream}/${stream.split("@")[0]}@bookTicker`;
    let ws;
    try { ws = new WebSocket(`wss://fstream.binance.com/stream?streams=${partes}`); }
    catch (e) { return; }
    this.ws = ws;
    ws.onopen = () => { this.intentos = 0; this.ultimo = Date.now(); this.sello(); };
    ws.onmessage = (ev) => {
      if (ev.data.indexOf('"e":"bookTicker"') > 0) {
        const t = Date.now();
        if (t - this._bt < 150) return;
        this._bt = t;
      }
      let d;
      try { d = (JSON.parse(ev.data)).data; } catch (e) { return; }
      if (!d) return;
      this.ultimo = Date.now();
      this.frames += 1;
      if (d.k) tickVela({ t: Number(d.k.t), o: +d.k.o, h: +d.k.h, l: +d.k.l, c: +d.k.c });
      else if (d.e === "bookTicker" && d.b && d.a) tickPrecio((+d.b + +d.a) / 2);
      this.sello();
    };
    ws.onclose = () => { if (this.stream === stream) this.reintentar(stream); };
  },

  reintentar(stream) {
    this.sello();
    this.intentos += 1;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { if (this.stream === stream) this.conectar(stream); },
                            Math.min(60_000, 2_000 * Math.pow(2, this.intentos - 1)));
  },

  cerrar() {
    clearTimeout(this.timer);
    this.stream = null;
    if (this.ws) { try { this.ws.onclose = null; this.ws.close(); } catch (e) {} }
    this.ws = null;
  },

  estado() {
    if (!this.ws || this.ws.readyState !== 1) return "sin vivo";
    if (!this.frames) return "conectando";
    return (Date.now() - this.ultimo) < 30_000 ? "en vivo" : "stream mudo";
  },

  sello() {
    const e = $("updated");
    if (!e) return;
    const st = this.estado();
    // La edad del push va al lado del estado del stream: son dos cosas distintas —el
    // grafico puede ir en vivo mientras los paneles siguen con datos de hace 13 min— y
    // callar la segunda es lo que hizo que Hugo viera un precio congelado sin saber por que.
    const edad = state.data && Number(state.data.push_edad_s);
    const min = Number.isFinite(edad) ? Math.round(edad / 60) : null;
    e.textContent = (st === "en vivo" ? "gráfico en vivo" : `gráfico ${st}`)
      + (min != null ? ` · paneles hace ${min} min` : "");
  },
};

// El tick mueve la vela en curso Y el precio del encabezado. Si la vela que tenemos ya
// no es la actual, se CREA: estirar una vieja fabrica una vela que nunca existio, y eso
// ya nos paso en el grafico de trading.
function tickPrecio(px) {
  if (!Number.isFinite(px) || !state.velas.length) return;
  const paso = state.velas.length > 1
    ? state.velas[state.velas.length - 1].t - state.velas[state.velas.length - 2].t : 0;
  let ult = state.velas[state.velas.length - 1];
  if (paso > 0) {
    const abre = Math.floor(Date.now() / paso) * paso;
    if (abre > ult.t) {
      ult = { t: abre, o: px, h: px, l: px, c: px, v: 0 };
      state.velas.push(ult);
    }
  }
  ult.c = px;
  if (px > ult.h) ult.h = px;
  if (px < ult.l) ult.l = px;
  pintarTick(ult, px);
}

function tickVela(k) {
  if (!state.velas.length) return;
  const ult = state.velas[state.velas.length - 1];
  if (k.t < ult.t) return;
  if (k.t === ult.t) Object.assign(ult, k);
  else state.velas.push({ ...k, v: 0 });
  pintarTick(state.velas[state.velas.length - 1], k.c);
}

let _pintado = 0;
function pintarTick(vela, px) {
  const ahora = Date.now();
  if (ahora - _pintado < 100) return;      // ~10/s: continuo sin ahogar el DOM
  _pintado = ahora;
  if (state.series) {
    state.series.update({ time: Math.floor(vela.t / 1000), open: vela.o,
                          high: vela.h, low: vela.l, close: vela.c });
  }
  const el = $("price");
  if (el) el.textContent = fmt(px, decimales(px));
}

// --- gráfico ---------------------------------------------------------
function crearGrafico() {
  if (!window.LightweightCharts || state.chart) return;
  const LC = window.LightweightCharts;
  state.chart = LC.createChart($("chart"), {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: "#888e9c",
              fontFamily: "-apple-system, BlinkMacSystemFont, sans-serif",
              attributionLogo: false },
    grid: { vertLines: { color: "rgba(130,140,160,0.10)" },
            horzLines: { color: "rgba(130,140,160,0.10)" } },
    crosshair: { mode: LC.CrosshairMode.Normal },
    rightPriceScale: { borderColor: "rgba(130,140,160,0.28)" },
    timeScale: { borderColor: "rgba(130,140,160,0.28)", timeVisible: true,
                 secondsVisible: false },
    localization: { locale: "es" },
  });
  state.series = state.chart.addSeries(LC.CandlestickSeries, {
    upColor: "#0a9d63", downColor: "#d8394e", borderVisible: false,
    wickUpColor: "#0a9d63", wickDownColor: "#d8394e",
  });
}

function pintarVelas() {
  if (!state.series) return;
  if (!state.velas.length) {
    state.series.setData([]);
    return;
  }
  const prec = decimales(state.velas[state.velas.length - 1].c);
  state.series.applyOptions({ priceFormat: { type: "price", precision: prec,
                                             minMove: Math.pow(10, -prec) } });
  state.series.setData(state.velas.map((v) => ({
    time: Math.floor(v.t / 1000), open: v.o, high: v.h, low: v.l, close: v.c })));
}

function limpiarLineas() {
  for (const l of state.lineas) { try { state.series.removePriceLine(l); } catch (e) { /* ya removida */ } }
  state.lineas = [];
}

function pintarNiveles() {
  if (!state.series || !state.data) return;
  limpiarLineas();
  const d = state.data;
  const verPlacebo = $("ver-placebo").checked;
  const verHistoricas = $("ver-historicas").checked;
  const verMapa = $("ver-mapa").checked;

  // Solo los niveles que caen en el rango de precio VISIBLE de las velas cargadas.
  // Sin este recorte, la rejilla anual llega hasta +150% y aplasta el eje: es el mismo
  // error de encuadre que ya corregimos dos veces en los gráficos de CoinGlass,
  // donde un muro lejano estiraba el eje y dejaba todo lo demás en una franja.
  const precios = state.velas.flatMap((v) => [v.h, v.l]);
  const min = Math.min(...precios), max = Math.max(...precios);
  const margen = (max - min) * 0.15;
  const visible = (p) => p >= min - margen && p <= max + margen;
  const fuera = [];

  const linea = (precio, color, titulo, estilo = 0, ancho = 1,
                 contarFuera = true, etiqueta = true) => {
    if (!visible(precio)) {
      if (contarFuera) fuera.push({ precio, titulo, color });
      return;
    }
    state.lineas.push(state.series.createPriceLine({
      price: precio, color, lineWidth: ancho, lineStyle: estilo,
      axisLabelVisible: etiqueta, title: etiqueta ? titulo : "" }));
  };

  for (const f of d.rejilla || []) {
    linea(f.precio, "#e8b653", `${f.pct_del_ancla > 0 ? "+" : ""}${f.pct_del_ancla}%`,
          0, f.k % 5 === 0 ? 2 : 1);
  }
  if (verPlacebo) {
    for (const [paso, filas] of Object.entries(d.rejilla_placebo || {})) {
      const pct = (Number(paso) * 100).toFixed(1).replace(".", ",");
      for (const f of filas) linea(f.precio, "rgba(91,98,114,.75)", `${pct}%`, 2);
    }
  }
  if (verHistoricas) {
    for (const historia of d.rejillas_historicas || []) {
      linea(historia.ancla.precio, "#b7a7e8", `apertura ${historia.anio}`, 2, 2, false);
      const cercanosHistoria = [...(historia.niveles || [])]
        .sort((a, b) => Math.abs(a.precio - d.precio) - Math.abs(b.precio - d.precio))
        .slice(0, 2);
      const etiquetasHistoria = new Set(cercanosHistoria.map((n) => n.precio));
      for (const nivel of historia.niveles || []) {
        const signo = nivel.pct_del_ancla > 0 ? "+" : "";
        linea(nivel.precio, "#b7a7e8",
              `${historia.anio} ${signo}${nivel.pct_del_ancla}%`, 2, 1, false,
              etiquetasHistoria.has(nivel.precio));
      }
    }
  }
  for (const refugio of d.refugios_promovidos || []) {
    linea(refugio.precio, "#f4f6f8", `refugio ${refugio.nombre || ""}`.trim(),
          0, 3, false);
  }
  if (d.apertura_semanal) {
    linea(d.apertura_semanal.precio, "#43bdd7", "apertura semanal", 1, 2);
  }
  if (d.apertura_anual) {
    linea(d.apertura_anual.precio, "#ffffff", `apertura ${d.anio}`, 0, 2);
  }
  if (verMapa && state.mapa) {
    const colores = { principal: "#35c9c1", panorama: "#7698d9",
                      sincronismo: "#d88ab0" };
    const estilos = { principal: 0, panorama: 2, sincronismo: 1 };
    const candidatos = [];
    for (const capa of Object.values(state.mapa.mapas_temporales || {})) {
      if (!capa.mapa) continue;
      for (const nivel of capa.mapa.retrocesos || []) {
        candidatos.push({ capa, nivel, familia: "C" });
      }
      for (const nivel of capa.mapa.extensiones || []) {
        candidatos.push({ capa, nivel, familia: "P" });
      }
    }
    // Todas las líneas permanecen. Para las etiquetas se usa una separación mínima
    // sobre el rango visible; de otro modo 30-40 precios se pisan en el eje y dejan
    // de ser legibles. La tabla inferior conserva el detalle completo.
    const prioridad = { principal: 0, sincronismo: 1, panorama: 2 };
    const umbralEtiqueta = Math.max((max - min) * 0.025, d.precio * 0.001);
    const elegidas = [];
    for (const c of candidatos.filter((x) => visible(x.nivel.precio))
      .sort((a, b) =>
        Math.abs(a.nivel.precio - d.precio) - Math.abs(b.nivel.precio - d.precio) ||
        (prioridad[a.capa.rol] ?? 3) - (prioridad[b.capa.rol] ?? 3))) {
      if (elegidas.length >= 10) break;
      if (elegidas.every((x) => Math.abs(x - c.nivel.precio) >= umbralEtiqueta)) {
        elegidas.push(c.nivel.precio);
      }
    }
    for (const c of candidatos) {
      linea(c.nivel.precio, colores[c.capa.rol] || "#9aa4b5",
            `${String(c.capa.tf).toUpperCase()} ${c.familia}` +
              `${fmt(c.nivel.ratio * 100, 1)}%`,
            estilos[c.capa.rol] ?? 2, c.capa.rol === "principal" ? 2 : 1, false,
            elegidas.includes(c.nivel.precio));
    }
  }

  // Un nivel fuera del encuadre NO puede desaparecer en silencio. En 1h la rejilla
  // anual queda casi entera afuera —es un instrumento diario, el propio curso dice
  // "construir en diario y consultar en temporalidades inferiores"— y esconderla
  // hace que la pantalla parezca decir "no hay nada cerca" cuando lo que pasa es que
  // no estamos mirando tan lejos. Se nombra el más cercano de cada lado con su
  // distancia; el resto se cuenta.
  const px = d.precio;
  const arriba = fuera.filter((f) => f.precio > px).sort((a, b) => a.precio - b.precio)[0];
  const abajo = fuera.filter((f) => f.precio < px).sort((a, b) => b.precio - a.precio)[0];
  const dist = (f) => `${f.titulo} a ${signed((f.precio / px - 1) * 100, "%")}`;
  const partes = [`${state.symbol} ${state.tf}`];
  if (arriba || abajo) {
    const cercanos = [arriba && `↑ ${dist(arriba)}`, abajo && `↓ ${dist(abajo)}`]
      .filter(Boolean).join(" · ");
    partes.push(`fuera del encuadre: ${cercanos}` +
                (fuera.length > 2 ? ` (+${fuera.length - 2} más)` : ""));
  }
  $("g-sub").textContent = partes.join(" · ");
}

// El marcador vive en el extremo para señalar el precio estructural correcto, pero
// declara el retraso de confirmación en su texto. En el payload viajan ambos tiempos.
function pintarPivotes(est) {
  if (!state.series || !window.LightweightCharts) return;
  const LC = window.LightweightCharts;
  const marcas = [];
  const verFractales = $("ver-fractales").checked;
  const highs = verFractales ? est.fractales_highs : est.highs;
  const lows = verFractales ? est.fractales_lows : est.lows;
  const prefijo = verFractales ? "F" : "";
  const at = (idx) => state.velas[idx] ? Math.floor(state.velas[idx].t / 1000) : null;
  for (const p of highs || []) {
    const t = at(p.idx);
    if (t) marcas.push({ time: t, position: "aboveBar", color: "#ef6370",
                         shape: "arrowDown", text: `${prefijo}H · conf +${est.piv}` });
  }
  for (const p of lows || []) {
    const t = at(p.idx);
    if (t) marcas.push({ time: t, position: "belowBar", color: "#24c88a",
                         shape: "arrowUp", text: `${prefijo}L · conf +${est.piv}` });
  }
  marcas.sort((a, b) => a.time - b.time);
  try {
    if (state.marcas && state.marcas.setMarkers) state.marcas.setMarkers(marcas);
    else if (LC.createSeriesMarkers) {
      state.marcas = LC.createSeriesMarkers(state.series, marcas);
    }
    else if (state.series.setMarkers) state.series.setMarkers(marcas);
  } catch (e) { /* la versión bundleada no soporta marcadores: no es crítico */ }
}

// --- paneles ---------------------------------------------------------
function pintarPaneles() {
  const d = state.data;
  if (!d) return;
  $("price").textContent = fmt(d.precio, decimales(d.precio));
  $("anio").textContent = d.anio;

  if (d.apertura_anual) {
    $("pa").textContent = fmt(d.apertura_anual.precio, decimales(d.precio));
    $("pa-fecha").textContent = d.apertura_anual.fecha;
  } else {
    $("pa").textContent = "sin ancla";
    $("pa-fecha").textContent = `el par no tiene datos desde el 1 de enero de ${d.anio}`;
  }
  $("pa-dist").textContent = signed(d.desde_apertura_anual_pct, "%");
  $("pa-dist-box").className = "stat " + (d.desde_apertura_anual_pct == null ? ""
    : d.desde_apertura_anual_pct >= 0 ? "up" : "down");

  if (d.apertura_semanal) {
    $("ps").textContent = fmt(d.apertura_semanal.precio, decimales(d.precio));
    $("ps-fecha").textContent = `semana del ${d.apertura_semanal.fecha} (lunes UTC)`;
  } else {
    $("ps").textContent = "—";
    // Que diga POR QUÉ falta. Un guion mudo se lee como error de la pantalla; esto
    // dice que los datos no llegan a la semana en curso, que es otra cosa.
    $("ps-fecha").textContent = "los datos no alcanzan la semana en curso";
  }

  // Tabla completa, ordenada por cercanía. El indicador del profesor permite muchos
  // niveles; recortarla a ocho hacía parecer que faltaban cálculos.
  const filas = [...(d.rejilla || [])]
    .sort((a, b) => Math.abs(a.dist_pct) - Math.abs(b.dist_pct));
  $("tabla-rejilla").innerHTML =
    "<thead><tr><th>nivel</th><th>precio</th><th>distancia</th></tr></thead><tbody>" +
    filas.map((f) => `<tr><td>${f.pct_del_ancla > 0 ? "+" : ""}${f.pct_del_ancla}% del ancla</td>` +
      `<td class="num">${fmt(f.precio, decimales(d.precio))}</td>` +
      `<td class="num" style="color:${f.dist_pct >= 0 ? "#ef6370" : "#24c88a"}">` +
      `${signed(f.dist_pct, "%")}</td></tr>`).join("") + "</tbody>";

  const nHistoricos = (d.rejillas_historicas || [])
    .reduce((n, h) => n + (h.niveles || []).length, 0);
  const rlp = (d.catalogo_formulas || {}).rlp_historico || {};
  $("familias-historicas").innerHTML = [
    ["RMP vigente", `${(d.rejilla || []).length} niveles`, `${d.anio} · dorado sólido`],
    ["Cálculos históricos", `${nHistoricos} niveles`,
      `${(d.rejillas_historicas || []).length} años · violeta discontinuo`],
    ["Refugios promovidos", `${(d.refugios_promovidos || []).length}`,
      (d.nota_refugios || "sin regla de promoción")],
    ["RLP histórico", rlp.aplicado ? "aplicado" : "no aplicado",
      rlp.motivo || "sin ancla causal"],
  ].map(([k, v, s]) =>
    `<div class="stat"><span>${k}</span><strong>${v}</strong><small>${s}</small></div>`
  ).join("");

  vacio("vac-arriba", "hacia arriba", d.vacio_arriba, d.precio);
  vacio("vac-abajo", "hacia abajo", d.vacio_abajo, d.precio);

  $("estructuras").innerHTML = [["1h", d.estructura_1h], ["1D", d.estructura_1D]]
    .map(([tf, e]) => `<div class="vac"><h3>${tf} · ventana ${e.piv}+1+${e.piv}</h3>` +
      `<div class="px">${e.tendencia}</div>` +
      `<div class="meta">${e.n_highs || 0} altos y ${e.n_lows || 0} bajos estructurales` +
      `<br>${e.n_fractales_highs || 0} / ${e.n_fractales_lows || 0} fractales H/L` +
      `<br>un pivote recién existe ${e.retraso_velas} velas después de su extremo` +
      `${e.motivo ? `<br>${e.motivo}` : ""}</div></div>`).join("");
}

function tablaMapa(id, filas) {
  $(id).innerHTML =
    "<thead><tr><th>nivel</th><th>precio</th><th>desde ahora</th></tr></thead><tbody>" +
    (filas || []).map((f) =>
      `<tr><td>${fmt(f.ratio * 100, 1)}%</td>` +
      `<td class="num">${fmt(f.precio, decimales(state.mapa && state.mapa.precio))}</td>` +
      `<td class="num">${signed(f.dist_pct, "%")}</td></tr>`).join("") +
    "</tbody>";
}

function mapasTemporales(d, principal) {
  const capas = Object.values(d.mapas_temporales || {})
    .filter((c) => c.tf !== principal);
  $("mapas-temporales").innerHTML = capas.map((c) => {
    const m = c.mapa;
    if (!m || !m.pierna) {
      return `<div class="tf-map"><h4>${String(c.tf).toUpperCase()} · ${c.rol}</h4>` +
        '<p class="tf-map-meta">sin pierna confirmada</p></div>';
    }
    const niveles = [
      ...m.retrocesos.map((x) => ({ ...x, familia: "corrección" })),
      ...m.extensiones.map((x) => ({ ...x, familia: "proyección" })),
    ].sort((a, b) => b.precio - a.precio);
    return `<div class="tf-map"><h4>${String(c.tf).toUpperCase()} · ${c.rol}</h4>` +
      `<p class="tf-map-meta">${m.pierna.direccion} · ` +
      `${fmt(m.pierna.inicio, decimales(d.precio))} → ` +
      `${fmt(m.pierna.fin, decimales(d.precio))} · confirmada ` +
      `${new Date(m.pierna.confirmed_at).toLocaleString("es-CL")}</p>` +
      '<div class="scroll-x"><table><thead><tr><th>familia</th><th>nivel</th>' +
      '<th>precio</th><th>desde ahora</th></tr></thead><tbody>' +
      niveles.map((n) => `<tr><td>${n.familia}</td><td>${fmt(n.ratio * 100, 1)}%</td>` +
        `<td class="num">${fmt(n.precio, decimales(d.precio))}</td>` +
        `<td class="num">${signed(n.dist_pct, "%")}</td></tr>`).join("") +
      "</tbody></table></div></div>";
  }).join("");
}

function referencias(id, titulo, filas, total) {
  const el = $(id);
  if (!filas || !filas.length) {
    el.innerHTML = `<h3>${titulo}</h3><div class="px">sin referencias</div>`;
    return;
  }
  const conteo = Number.isFinite(Number(total)) && Number(total) > filas.length
    ? ` · mostrando ${filas.length} de ${total}`
    : ` · ${filas.length}`;
  el.innerHTML = `<h3>${titulo}${conteo}</h3>` + filas.map((r) =>
    `<div class="meta"><span class="cuenta">${fmt(r.precio, decimales(state.mapa.precio))}</span>` +
    ` · ${r.tf} · ${r.tipo}${r.rol ? ` · ${r.rol}` : ""}</div>`).join("");
}

function pintarMapa() {
  const d = state.mapa;
  if (!d) return;
  const p = d.perfil || {};
  $("mapa-sub").textContent = `${p.label || state.horizonte} · ${d.symbol}`;
  $("roles").innerHTML = [
    ["Panorama", (p.panorama || []).map((x) => x.toUpperCase()).join(" + ")],
    ["Principal", String(p.principal || "—").toUpperCase()],
    ["Sincronismo", String(p.sincronismo || "—").toUpperCase()],
  ].map(([k, v]) => `<div class="role"><span>${k}</span><strong>${v}</strong></div>`).join("");

  const a = d.alineacion || {};
  const vh = d.vacio_horizonte || {};
  const tendencia = (tf) => (a.tendencias || {})[tf] || "—";
  const vacioTxt = vh.evaluado && vh.primer_obstaculo
    ? `${fmt(vh.vacuum_rr, 2)}R`
    : "no evaluable";
  const vacioSub = vh.evaluado && vh.primer_obstaculo
    ? `${vh.primer_obstaculo.tipo} · stop ${fmt(vh.stop_estructural.price,
      decimales(d.precio))}`
    : (vh.motivo || "sin primer referente");
  $("alineacion-stats").innerHTML = [
    ["Contexto superior", a.direccion_contexto || "mixto / indefinido",
      (p.panorama || []).map((tf) => `${tf.toUpperCase()} ${tendencia(tf)}`).join(" · ")],
    ["Principal / sincronismo", LABEL_ALINEACION[a.estado] || a.estado || "—",
      `${String(p.principal || "").toUpperCase()} ${tendencia(p.principal)} · ` +
      `${String(p.sincronismo || "").toUpperCase()} ${tendencia(p.sincronismo)}`],
    ["Vacío estructural", vacioTxt, vacioSub],
  ].map(([k, v, s]) =>
    `<div class="stat"><span>${k}</span><strong>${v}</strong><small>${s}</small></div>`).join("");

  const m = d.mapa;
  const capasCalculadas = Object.values(d.mapas_temporales || {})
    .filter((c) => c.mapa);
  const totalCalculados = capasCalculadas.reduce((n, c) =>
    n + c.mapa.retrocesos.length + c.mapa.extensiones.length, 0);
  const nivelesPorPierna = capasCalculadas.length
    ? capasCalculadas[0].mapa.retrocesos.length +
      capasCalculadas[0].mapa.extensiones.length
    : 0;
  const resumenCalculos = ["Precios calculados", `${totalCalculados} niveles · ` +
    `${capasCalculadas.length} TF`,
    `${nivelesPorPierna} niveles por cada pierna confirmada`];
  if (!m || !m.pierna) {
    $("pierna-stats").innerHTML =
      '<div class="stat"><span>pierna</span><strong>sin contexto confirmado</strong></div>' +
      `<div class="stat"><span>${resumenCalculos[0]}</span>` +
      `<strong>${resumenCalculos[1]}</strong><small>${resumenCalculos[2]}</small></div>`;
    tablaMapa("tabla-retrocesos", []);
    tablaMapa("tabla-extensiones", []);
  } else {
    const leg = m.pierna;
    $("pierna-stats").innerHTML = [
      ["Dirección descriptiva", leg.direccion, `${leg.tf} · ventana ${leg.piv}+1+${leg.piv}`],
      ["Pierna congelada", `${fmt(leg.inicio, decimales(d.precio))} → ${fmt(leg.fin, decimales(d.precio))}`,
        `confirmada ${new Date(leg.confirmed_at).toLocaleString("es-CL")}`],
      ["Ubicación en la pierna", `${LABEL_PIERNA[m.estado] || m.estado} · ` +
        `${fmt((m.profundidad_correccion || 0) * 100, 1)}%`,
        `origen de referencia ${fmt(m.invalidation_reference, decimales(d.precio))} · ` +
        "invalidación estructural no evaluada"],
      resumenCalculos,
    ].map(([k, v, s]) =>
      `<div class="stat"><span>${k}</span><strong>${v}</strong><small>${s}</small></div>`).join("");
    tablaMapa("tabla-retrocesos", m.retrocesos);
    tablaMapa("tabla-extensiones", m.extensiones);
  }
  mapasTemporales(d, p.principal);
  const refs = d.referencias_cercanas || {};
  referencias("refs-arriba", "Referencias confirmadas arriba",
              refs.arriba, refs.total_arriba);
  referencias("refs-abajo", "Referencias confirmadas abajo",
              refs.abajo, refs.total_abajo);
  $("mapa-nota").textContent = d.nota || "";
}

function vacio(id, titulo, v, precio) {
  const el = $(id);
  if (!v || !v.primer_obstaculo) {
    el.innerHTML = `<h3>${titulo}</h3><div class="px">sin referencias</div>` +
      `<div class="meta">${(v && v.nota) || "no hay niveles conocidos en esa dirección"}</div>`;
    return;
  }
  const o = v.primer_obstaculo;
  el.innerHTML = `<h3>${titulo}</h3>` +
    `<div class="px">${fmt(o.precio, decimales(precio))}</div>` +
    `<div class="meta">${o.tipo} · ${o.tf} · a ${signed(v.distancia_pct, "%")}<br>` +
    `ratio contra el riesgo de referencia: <span class="cuenta">${v.vacuum_rr ?? "—"}</span><br>` +
    `hay <span class="cuenta">${v.n_adelante}</span> referencias conocidas en esa dirección</div>`;
}


// Un fallo de datos NO puede verse como una pantalla vacía.
//
// Railway está geo-bloqueado por Binance (HTTP 451, verificado el 2026-07-26).
// La ruta normal es el snapshot del colector VPS; si tampoco está disponible, la
// pantalla debe decirlo en vez de parecer vacía.
function mostrarFallo(msg) {
  const geo = /451|restricted location/i.test(String(msg));
  const caja = document.querySelector(".disclaimer");
  if (caja) {
    caja.innerHTML = geo
      ? "<strong>Sin datos en este despliegue.</strong> Binance responde 451 " +
        "(ubicación restringida) al servidor de Railway y el snapshot del colector " +
        "VPS no está disponible o está vencido."
      : `<strong>Sin datos.</strong> ${String(msg).slice(0, 200)}`;
  }
  $("updated").textContent = geo ? "bloqueo geográfico" : "sin datos";
  $("price").textContent = "—";
  state.velas = [];
  pintarVelas();
}

// --- carga -----------------------------------------------------------
async function cargar() {
  const seq = ++state.loadSeq;
  const q = `symbol=${encodeURIComponent(state.symbol)}`;
  try {
    const [st, vl, mp] = await Promise.all([
      fetch(`${API}/state?${q}`).then((r) => r.json()),
      fetch(`${API}/velas?${q}&tf=${state.tf}`).then((r) => r.json()),
      fetch(`${API}/mapa?${q}&horizonte=${state.horizonte}`).then((r) => r.json()),
    ]);
    if (seq !== state.loadSeq) return;
    if (st.error || vl.error || mp.error) {
      mostrarFallo(st.error || vl.error || mp.error);
      return;
    }
    state.data = st;
    state.mapa = mp;
    state.velas = vl.velas || [];
    state.estructura = vl.estructura || null;
    pintarVelas();
    pintarNiveles();
    if (state.estructura) pintarPivotes(state.estructura);
    pintarPaneles();
    if (vl.stream_vivo) vivo.conectar(vl.stream_vivo); else vivo.cerrar();
    pintarMapa();
    // La fuente de los datos NO es un detalle: si viene del respaldo versionado,
    // el precio y la estructura estan viejos y todo lo demas hay que leerlo distinto.
    // `vps_binance` = el colector del VPS empujo klines frescas: es la fuente
    // buena y no hay nada que advertir. Las otras dos si.
    if (vl.fuente === "klines_versionados") {
      const ult = state.velas.length
        ? new Date(state.velas[state.velas.length - 1].t).toLocaleDateString("es-CL")
        : "?";
      $("updated").textContent = `datos históricos hasta ${ult}`;
      const caja = document.querySelector(".disclaimer");
      // Aviso PROPIO, no pegado adentro del otro: son dos cosas distintas —de dónde
      // salen los datos, y qué se midió sobre ellos— y mezclarlas en un párrafo hace
      // que ninguna de las dos se lea.
      if (caja && !document.getElementById("aviso-datos")) {
        caja.insertAdjacentHTML("beforebegin",
          '<p class="disclaimer aviso-datos" id="aviso-datos">' +
          "<strong>Datos históricos, no en vivo.</strong> Binance bloquea a este " +
          "servidor (HTTP 451), así que la vista usa los klines versionados del " +
          "repo. La apertura anual sigue siendo correcta —el 1 de enero ya pasó y no " +
          "cambia—; el precio y la apertura semanal, no." +
          "</p>");
      }
    } else {
      const meta = vl.fuente_meta || {};
      const edad = Number(meta.push_age_seconds);
      $("updated").textContent = Number.isFinite(edad)
        ? `Binance VPS · hace ${Math.max(0, Math.round(edad / 60))} min`
        : `${vl.fuente || "Binance"} · ${new Date().toLocaleTimeString("es-CL",
          { hour: "2-digit", minute: "2-digit" })}`;
    }
  } catch (exc) {
    $("updated").textContent = `sin datos: ${exc}`;
  }
}

function iniciar() {
  crearGrafico();
  fetch(`${API}/state`).then((r) => r.json()).then((st) => {
    state.symbol = st.symbol;
    $("par").innerHTML = (st.pares || []).map((p) =>
      `<option value="${p}"${p === st.symbol ? " selected" : ""}>${p}</option>`).join("");
    cargar();
  });
  $("par").addEventListener("change", (e) => { state.symbol = e.target.value; cargar(); });
  $("tf").addEventListener("change", (e) => { state.tf = e.target.value; cargar(); });
  for (const b of document.querySelectorAll("[data-horizonte]")) {
    b.addEventListener("click", () => {
      state.horizonte = b.dataset.horizonte;
      for (const x of document.querySelectorAll("[data-horizonte]")) {
        x.classList.toggle("active", x === b);
      }
      state.tf = TF_PRINCIPAL[state.horizonte];
      $("tf").value = state.tf;
      cargar();
    });
  }
  $("ver-placebo").addEventListener("change", pintarNiveles);
  $("ver-historicas").addEventListener("change", pintarNiveles);
  $("ver-mapa").addEventListener("change", pintarNiveles);
  $("ver-fractales").addEventListener("change", () => {
    if (state.estructura) pintarPivotes(state.estructura);
  });
  for (const b of document.querySelectorAll(".ayuda")) {
    b.addEventListener("click", () => {
      const caja = $(`ayuda-${b.dataset.ayuda}`);
      caja.hidden = !caja.hidden;
      b.textContent = caja.hidden ? b.textContent.replace("ocultar", "qué") : "ocultar";
    });
  }
  setInterval(cargar, 60_000);
  // Latido del sello: nadie dispara un evento cuando los frames PARAN.
  setInterval(() => vivo.sello(), 20_000);
}

iniciar();
