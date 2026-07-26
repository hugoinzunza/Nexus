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
                velas: [], chart: null, series: null, lineas: [], marcas: [],
                loadSeq: 0 };
const TF_PRINCIPAL = { corto: "1h", medio: "4h", largo: "1d" };

const fmt = (v, d = 2) => (v == null || !Number.isFinite(Number(v))) ? "—"
  : Number(v).toLocaleString("es-CL", { minimumFractionDigits: d, maximumFractionDigits: d });
const signed = (v, suf = "") => v == null ? "—" : `${v > 0 ? "+" : ""}${fmt(v, 2)}${suf}`;

// Decimales según magnitud: BTC necesita 2 y DOGE 6. Un formato fijo convierte el
// precio de una moneda barata en "0.00", que es peor que no mostrarlo.
function decimales(px) {
  const a = Math.abs(px || 0);
  return a >= 10 ? 2 : a >= 1 ? 4 : a >= 0.1 ? 5 : a >= 0.01 ? 6 : 8;
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

  // Solo los niveles que caen en el rango de precio VISIBLE de las velas cargadas.
  // Sin este recorte, la rejilla anual llega a ±90% y aplasta el eje: es el mismo
  // error de encuadre que ya corregimos dos veces en los gráficos de CoinGlass,
  // donde un muro lejano estiraba el eje y dejaba todo lo demás en una franja.
  const precios = state.velas.flatMap((v) => [v.h, v.l]);
  const min = Math.min(...precios), max = Math.max(...precios);
  const margen = (max - min) * 0.15;
  const visible = (p) => p >= min - margen && p <= max + margen;
  const fuera = [];

  const linea = (precio, color, titulo, estilo = 0, ancho = 1) => {
    if (!visible(precio)) { fuera.push({ precio, titulo, color }); return; }
    state.lineas.push(state.series.createPriceLine({
      price: precio, color, lineWidth: ancho, lineStyle: estilo,
      axisLabelVisible: true, title: titulo }));
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
  if (d.apertura_semanal) {
    linea(d.apertura_semanal.precio, "#43bdd7", "apertura semanal", 1, 2);
  }
  if (d.apertura_anual) {
    linea(d.apertura_anual.precio, "#ffffff", `apertura ${d.anio}`, 0, 2);
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

// Los pivotes se marcan en la vela que los CONFIRMA, no en su extremo. El desfase de
// 5 velas es real y esconderlo sería exactamente el look-ahead que el resto del
// código evita con tanto cuidado.
function pintarPivotes(est) {
  if (!state.series || !window.LightweightCharts) return;
  const LC = window.LightweightCharts;
  const marcas = [];
  const at = (idx) => state.velas[idx] ? Math.floor(state.velas[idx].t / 1000) : null;
  for (const p of est.highs || []) {
    const t = at(p.confirm_idx);
    if (t) marcas.push({ time: t, position: "aboveBar", color: "#ef6370",
                         shape: "arrowDown", text: "H" });
  }
  for (const p of est.lows || []) {
    const t = at(p.confirm_idx);
    if (t) marcas.push({ time: t, position: "belowBar", color: "#24c88a",
                         shape: "arrowUp", text: "L" });
  }
  marcas.sort((a, b) => a.time - b.time);
  try {
    if (LC.createSeriesMarkers) LC.createSeriesMarkers(state.series, marcas);
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

  // Tabla de la rejilla, ordenada por cercanía al precio: lo primero que uno quiere
  // saber es qué nivel tiene más cerca, no el mapa completo.
  const filas = [...(d.rejilla || [])]
    .sort((a, b) => Math.abs(a.dist_pct) - Math.abs(b.dist_pct)).slice(0, 8);
  $("tabla-rejilla").innerHTML =
    "<thead><tr><th>nivel</th><th>precio</th><th>distancia</th></tr></thead><tbody>" +
    filas.map((f) => `<tr><td>${f.pct_del_ancla > 0 ? "+" : ""}${f.pct_del_ancla}% del ancla</td>` +
      `<td class="num">${fmt(f.precio, decimales(d.precio))}</td>` +
      `<td class="num" style="color:${f.dist_pct >= 0 ? "#ef6370" : "#24c88a"}">` +
      `${signed(f.dist_pct, "%")}</td></tr>`).join("") + "</tbody>";

  vacio("vac-arriba", "hacia arriba", d.vacio_arriba, d.precio);
  vacio("vac-abajo", "hacia abajo", d.vacio_abajo, d.precio);

  $("estructuras").innerHTML = [["1h", d.estructura_1h], ["1D", d.estructura_1D]]
    .map(([tf, e]) => `<div class="vac"><h3>${tf} · ventana ${e.piv}+1+${e.piv}</h3>` +
      `<div class="px">${e.tendencia}</div>` +
      `<div class="meta">${e.n_highs || 0} altos y ${e.n_lows || 0} bajos confirmados` +
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

function referencias(id, titulo, filas) {
  const el = $(id);
  if (!filas || !filas.length) {
    el.innerHTML = `<h3>${titulo}</h3><div class="px">sin referencias</div>`;
    return;
  }
  el.innerHTML = `<h3>${titulo}</h3>` + filas.map((r) =>
    `<div class="meta"><span class="cuenta">${fmt(r.precio, decimales(state.mapa.precio))}</span>` +
    ` · ${r.tf} · ${r.tipo}</div>`).join("");
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

  const m = d.mapa;
  if (!m || !m.pierna) {
    $("pierna-stats").innerHTML =
      '<div class="stat"><span>pierna</span><strong>sin contexto confirmado</strong></div>';
    tablaMapa("tabla-retrocesos", []);
    tablaMapa("tabla-extensiones", []);
  } else {
    const leg = m.pierna;
    $("pierna-stats").innerHTML = [
      ["Dirección descriptiva", leg.direccion, `${leg.tf} · ventana ${leg.piv}+1+${leg.piv}`],
      ["Pierna congelada", `${fmt(leg.inicio, decimales(d.precio))} → ${fmt(leg.fin, decimales(d.precio))}`,
        `confirmada ${new Date(leg.confirmed_at).toLocaleString("es-CL")}`],
      ["Estado de la pierna", `${m.estado} · ${fmt((m.profundidad_correccion || 0) * 100, 1)}%`,
        `invalidación de referencia ${fmt(m.invalidation_reference, decimales(d.precio))}`],
    ].map(([k, v, s]) =>
      `<div class="stat"><span>${k}</span><strong>${v}</strong><small>${s}</small></div>`).join("");
    tablaMapa("tabla-retrocesos", m.retrocesos);
    tablaMapa("tabla-extensiones", m.extensiones);
  }
  referencias("refs-arriba", "Referencias confirmadas arriba",
              (d.referencias_cercanas || {}).arriba);
  referencias("refs-abajo", "Referencias confirmadas abajo",
              (d.referencias_cercanas || {}).abajo);
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
    pintarVelas();
    pintarNiveles();
    if (vl.estructura) pintarPivotes(vl.estructura);
    pintarPaneles();
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
  for (const b of document.querySelectorAll(".ayuda")) {
    b.addEventListener("click", () => {
      const caja = $(`ayuda-${b.dataset.ayuda}`);
      caja.hidden = !caja.hidden;
      b.textContent = caja.hidden ? b.textContent.replace("ocultar", "qué") : "ocultar";
    });
  }
  setInterval(cargar, 60_000);
}

iniciar();
