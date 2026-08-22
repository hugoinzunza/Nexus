/**
 * NexUX · Primitive SMC canónico: FVG, OB y CDC.
 *
 * Gate 2 del renderer compartido. NexUX Trading y Command Center dibujaban las
 * mismas tres capas con dos implementaciones distintas —hasta con paletas
 * distintas para la misma zona—, así que la misma lectura se veía de dos
 * maneras según dónde la mirara uno.
 *
 * Este archivo es la ÚNICA implementación del dibujo. Los consumidores aportan
 * adaptadores que normalizan SU payload y una escena con los conversores de
 * coordenadas; el primitive no hace fetch, no lee el chart y no interpreta
 * mercado. Recibe geometría y la pinta.
 *
 * ALCANCE, deliberadamente acotado: solo FVG, OB y CDC. `curso`, `ribbon`,
 * trades y TP/SL son EXCLUSIVOS de NexUX y no viven acá — son capas de
 * estrategia o de operaciones, no geometría del gráfico.
 *
 * NO es Bot3. Es capa visual legada: no participa del libro causal, no declara
 * disponibilidad evento por evento y no es evidencia de nada.
 *
 * Sobre CDC: es un EVENTO DESCRIPTIVO LEGADO — describe un tramo de precio ya
 * ocurrido. No es señal, no es confirmación y no habilita ninguna decisión.
 */

export const CONTRATO_SMC = Object.freeze({
  id: "nexux.chart.smc-primitive.v1",
  validated: false,
  bot3_compatible: false,
  source_kind: "visual_layer",
  capas: Object.freeze(["fvg", "ob", "cdc"]),
  cdc: "evento descriptivo legado",
});

/** Rótulo del CDC. No decir «señal» ni «confirmación»: no lo es. */
export const CDC_ROTULO = Object.freeze({
  cerrado: "CDC",
  pendiente: "CDC pendiente",
});

const PALETA = Object.freeze({
  fvgAlcista: "162,155,254",
  fvgBajista: "245,166,35",
  obLargo: "22,199,132",
  obCorto: "234,57,67",
  cdc: "234,57,67",
});

/**
 * Etiqueta canónica. Vive acá para que las dos aplicaciones produzcan la
 * MISMA traza: si cada una pusiera su pill, las capas compartidas volverían a
 * verse distinto y el gate no probaría nada.
 */
function pill(ctx, escena, x, y, texto, color) {
  const { ancho, alto } = escena;
  ctx.font = "700 10px Inter, -apple-system, sans-serif";
  ctx.textBaseline = "middle";
  const anchoPill = ctx.measureText(texto).width + 20;
  const izq = Math.max(3, Math.min(x, ancho - anchoPill - 3));
  const arriba = Math.max(3, Math.min(y - 8, alto - 19));
  ctx.fillStyle = "rgba(5, 11, 18, 0.92)";
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(izq, arriba, anchoPill, 17, 4);
  else ctx.rect(izq, arriba, anchoPill, 17);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(izq + 8, arriba + 8.5, 2.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#f5f8fc";
  ctx.fillText(texto, izq + 14, arriba + 9);
}

function pillDerecha(ctx, escena, y, texto, color) {
  ctx.font = "700 10px Inter, -apple-system, sans-serif";
  const anchoPill = ctx.measureText(texto).width + 20;
  pill(ctx, escena, escena.ancho - anchoPill - 7, y, texto, color);
}

function caja(escena, hi, lo, t) {
  const y1 = escena.yAt(hi);
  const y2 = escena.yAt(lo);
  if (y1 == null || y2 == null) return null;
  let x = escena.xAt(t);
  if (x == null) x = 0;
  x = Math.max(0, x);
  return { x, top: Math.min(y1, y2), alto: Math.max(1, Math.abs(y2 - y1)) };
}

/** FVG normalizado: `{t, hi, lo, bullish}`. */
export function dibujarFvg(ctx, zonas, escena) {
  for (const zona of zonas) {
    const geo = caja(escena, zona.hi, zona.lo, zona.t);
    if (!geo) continue;
    const rgb = zona.bullish ? PALETA.fvgAlcista : PALETA.fvgBajista;
    const grad = ctx.createLinearGradient(geo.x, 0, escena.ancho, 0);
    grad.addColorStop(0, `rgba(${rgb},0.16)`);
    grad.addColorStop(1, `rgba(${rgb},0.05)`);
    ctx.fillStyle = grad;
    ctx.fillRect(geo.x, geo.top, escena.ancho - geo.x, geo.alto);
    ctx.strokeStyle = `rgba(${rgb},0.3)`;
    ctx.lineWidth = 1;
    ctx.strokeRect(geo.x + 0.5, geo.top + 0.5,
      Math.max(1, escena.ancho - geo.x - 1), geo.alto);
    pillDerecha(ctx, escena, geo.top + geo.alto / 2,
      zona.bullish ? "FVG ▲" : "FVG ▼", `rgb(${rgb})`);
  }
}

/** OB normalizado: `{t, hi, lo, long, valid, reference, tf, dist_pct}`. */
export function dibujarOb(ctx, zonas, escena) {
  for (const zona of zonas) {
    const geo = caja(escena, zona.hi, zona.lo, zona.t);
    if (!geo) continue;
    const rgb = zona.long ? PALETA.obLargo : PALETA.obCorto;
    const ancho = Math.max(1, escena.ancho - geo.x - 1);
    if (!zona.valid) {
      // Mitigado o roto: fondo tenue y borde punteado, sin etiqueta. Menos
      // ruido para lo que ya no está vivo.
      ctx.fillStyle = `rgba(${rgb},0.025)`;
      ctx.fillRect(geo.x, geo.top, escena.ancho - geo.x, geo.alto);
      ctx.strokeStyle = `rgba(${rgb},0.16)`;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 4]);
      ctx.strokeRect(geo.x + 0.5, geo.top + 0.5, ancho, geo.alto);
      ctx.setLineDash([]);
      continue;
    }
    if (zona.reference) {
      // Zona profunda de referencia: atenuada y punteada, con la distancia.
      ctx.fillStyle = `rgba(${rgb},0.05)`;
      ctx.fillRect(geo.x, geo.top, escena.ancho - geo.x, geo.alto);
      ctx.strokeStyle = `rgba(${rgb},0.22)`;
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 4]);
      ctx.strokeRect(geo.x + 0.5, geo.top + 0.5, ancho, geo.alto);
      ctx.setLineDash([]);
    } else {
      const grad = ctx.createLinearGradient(geo.x, 0, escena.ancho, 0);
      grad.addColorStop(0, `rgba(${rgb},0.20)`);
      grad.addColorStop(1, `rgba(${rgb},0.06)`);
      ctx.fillStyle = grad;
      ctx.fillRect(geo.x, geo.top, escena.ancho - geo.x, geo.alto);
      ctx.strokeStyle = `rgba(${rgb},0.55)`;
      ctx.lineWidth = 1;
      ctx.strokeRect(geo.x + 0.5, geo.top + 0.5, ancho, geo.alto);
      // Mitigación al 50% de la zona.
      const medio = geo.top + geo.alto / 2;
      ctx.strokeStyle = `rgba(${rgb},0.35)`;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(geo.x, medio);
      ctx.lineTo(escena.ancho, medio);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    const dist = Number.isFinite(zona.dist_pct)
      ? ` ${zona.dist_pct > 0 ? "+" : ""}${Math.round(zona.dist_pct)}%`
      : "";
    pillDerecha(ctx, escena, geo.top + geo.alto / 2,
      `OB ${zona.tf || ""}${dist}`.trim(), `rgb(${rgb})`);
  }
}

/**
 * CDC normalizado: `{t_from, t_to, price, pending}`.
 *
 * Evento DESCRIPTIVO: dibuja un tramo de precio ya ocurrido. No es señal ni
 * confirmación, y el rótulo no debe sugerir que lo sea.
 */
export function dibujarCdc(ctx, eventos, escena) {
  for (const evento of eventos) {
    const y = escena.yAt(evento.price);
    if (y == null) continue;
    let x1 = escena.xAt(evento.t_from);
    let x2 = escena.xAt(evento.t_to);
    if (evento.pending && x2 == null) x2 = escena.ancho;
    if (x2 == null) continue;
    if (x1 == null) x1 = 0;
    ctx.strokeStyle = `rgb(${PALETA.cdc})`;
    ctx.lineWidth = 1.2;
    ctx.setLineDash([]);
    ctx.globalAlpha = evento.pending ? 0.95 : 0.7;
    ctx.beginPath();
    ctx.moveTo(x1, y);
    ctx.lineTo(x2, y);
    ctx.stroke();
    if (!evento.pending) {                     // tick de cierre del tramo
      ctx.beginPath();
      ctx.moveTo(x2, y - 4);
      ctx.lineTo(x2, y + 4);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    pill(ctx, escena, (x1 + x2) / 2 - 18, y,
      evento.pending ? CDC_ROTULO.pendiente : CDC_ROTULO.cerrado,
      `rgb(${PALETA.cdc})`);
  }
}

/**
 * Dibuja las tres capas en orden fijo: FVG, OB y CDC encima.
 *
 * `capas` ya viene NORMALIZADO y FILTRADO por el adaptador de cada consumidor.
 * Este módulo no decide qué mostrar: si una lista llega vacía, no dibuja.
 */
export function dibujarSmc(ctx, capas, escena) {
  if (capas.fvg && capas.fvg.length) dibujarFvg(ctx, capas.fvg, escena);
  if (capas.ob && capas.ob.length) dibujarOb(ctx, capas.ob, escena);
  if (capas.cdc && capas.cdc.length) dibujarCdc(ctx, capas.cdc, escena);
}

/**
 * Adaptador del payload `analysis` del endpoint SMC legado, que es el mismo
 * en las dos aplicaciones. Normaliza y filtra; no dibuja.
 *
 * `mostrar` decide qué capas se piden; `soloHtf` es el filtro «Solo 4h/1D» de
 * NexUX, que vive en el adaptador y no en el primitive.
 */
export function normalizarAnalisis(analysis, mostrar = {}, opciones = {}) {
  const salida = { fvg: [], ob: [], cdc: [] };
  if (!analysis) return salida;
  if (mostrar.fvg) {
    salida.fvg = (analysis.fvgs || [])
      .filter((z) => !z.filled)
      .map((z) => ({ t: z.t, hi: z.hi, lo: z.lo, bullish: Boolean(z.bullish) }));
  }
  if (mostrar.ob) {
    salida.ob = (analysis.pois || [])
      .filter((z) => !opciones.soloHtf || z.tf === "4h" || z.tf === "1D")
      .map((z) => ({
        t: z.t_conf ?? 0,
        hi: z.hi,
        lo: z.lo,
        long: z.dir === "long",
        valid: Boolean(z.valid),
        reference: Boolean(z.reference),
        tf: z.tf || "",
        dist_pct: Number.isFinite(z.dist_pct) ? z.dist_pct : null,
      }));
  }
  if (mostrar.cdc) {
    salida.cdc = (analysis.cdc_events || []).map((e) => ({
      t_from: e.t_from,
      t_to: e.t_to,
      price: e.price,
      pending: Boolean(e.pending),
    }));
  }
  return salida;
}

if (typeof globalThis !== "undefined") {
  globalThis.NexuxSmcPrimitive = Object.freeze({
    CONTRATO_SMC,
    CDC_ROTULO,
    dibujarFvg,
    dibujarOb,
    dibujarCdc,
    dibujarSmc,
    normalizarAnalisis,
  });
}
