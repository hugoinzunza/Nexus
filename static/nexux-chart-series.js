/**
 * NexUX · Series y cálculos canónicos del gráfico.
 *
 * Gate 1 del renderer compartido. Antes, NexUX Trading (`app.js`) y Command
 * Center (`nexux-chart-provider.js`) calculaban EMA, RSI y ADX con dos copias
 * del mismo algoritmo, escritas por separado. Los datos ya venían de una sola
 * fuente, pero los NÚMEROS se derivaban dos veces — y dos implementaciones del
 * mismo cálculo pueden divergir sin que nadie lo note.
 *
 * Este archivo es la ÚNICA definición. Los dos consumidores lo importan; nadie
 * mantiene una copia local ni un respaldo silencioso.
 *
 * Alcance: agregación de temporalidades sintéticas e indicadores de serie.
 * Los primitives SMC (dibujo) son el gate 2 y NO viven acá.
 *
 * NO es Bot3. Estos cálculos son de la capa visual legada: no participan del
 * libro causal, no declaran disponibilidad evento por evento y no deben
 * presentarse como evidencia.
 */

export const CONTRATO_SERIES = Object.freeze({
  id: "nexux.chart.series.v1",
  validated: false,
  bot3_compatible: false,
  source_kind: "visual_layer",
});

export const INTERVALS = Object.freeze({
  "1m": { source: "1m", durationMs: 60_000, aggregate: 1 },
  "3m": { source: "1m", durationMs: 180_000, aggregate: 3 },
  "5m": { source: "5m", durationMs: 300_000, aggregate: 1 },
  "15m": { source: "15m", durationMs: 900_000, aggregate: 1 },
  "30m": { source: "15m", durationMs: 1_800_000, aggregate: 2 },
  "45m": { source: "15m", durationMs: 2_700_000, aggregate: 3 },
  "1h": { source: "1h", durationMs: 3_600_000, aggregate: 1 },
  "2h": { source: "1h", durationMs: 7_200_000, aggregate: 2 },
  "3h": { source: "1h", durationMs: 10_800_000, aggregate: 3 },
  "4h": { source: "4h", durationMs: 14_400_000, aggregate: 1 },
  "1D": { source: "1D", durationMs: 86_400_000, aggregate: 1 },
  "1W": { source: "1D", durationMs: 604_800_000, aggregate: 7 },
});

export class SeriesError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "SeriesError";
    this.code = code;
  }
}

export function intervalSpec(interval) {
  const spec = INTERVALS[interval];
  if (!spec) {
    throw new SeriesError("nexux-chart.invalid-interval",
      "Temporalidad no disponible.");
  }
  return spec;
}

function bucketStart(timestamp, durationMs) {
  return Math.floor(timestamp / durationMs) * durationMs;
}

/** Agrega velas canónicas a una temporalidad sintética. */
export function aggregateCandles(candles, interval) {
  const spec = intervalSpec(interval);
  if (spec.aggregate === 1) return candles.map((candle) => ({ ...candle }));
  const buckets = new Map();
  for (const candle of candles) {
    const time = bucketStart(candle.t, spec.durationMs);
    const existing = buckets.get(time);
    if (!existing) {
      buckets.set(time, { ...candle, t: time });
      continue;
    }
    existing.h = Math.max(existing.h, candle.h);
    existing.l = Math.min(existing.l, candle.l);
    existing.c = candle.c;
    existing.v += candle.v;
  }
  return [...buckets.values()].sort((left, right) => left.t - right.t);
}

/** EMA sembrada con el primer valor. Un punto por entrada. */
export function emaValues(values, period) {
  if (!Array.isArray(values) || !values.length || period < 1) return [];
  const alpha = 2 / (period + 1);
  const output = [Number(values[0])];
  for (let index = 1; index < values.length; index += 1) {
    output.push(Number(values[index]) * alpha + output[index - 1] * (1 - alpha));
  }
  return output;
}

/** RSI de Wilder. `null` hasta que hay período suficiente. */
export function rsiValues(values, period = 14) {
  const output = new Array(values.length).fill(null);
  if (values.length <= period) return output;
  let gains = 0;
  let losses = 0;
  for (let index = 1; index <= period; index += 1) {
    const delta = Number(values[index]) - Number(values[index - 1]);
    if (delta >= 0) gains += delta;
    else losses -= delta;
  }
  let averageGain = gains / period;
  let averageLoss = losses / period;
  const value = () =>
    100 - (100 / (1 + (averageLoss === 0 ? 1e9 : averageGain / averageLoss)));
  output[period] = value();
  for (let index = period + 1; index < values.length; index += 1) {
    const delta = Number(values[index]) - Number(values[index - 1]);
    averageGain = (averageGain * (period - 1) + Math.max(delta, 0)) / period;
    averageLoss = (averageLoss * (period - 1) + Math.max(-delta, 0)) / period;
    output[index] = value();
  }
  return output;
}

/** ADX de Wilder sobre velas `{h,l,c}`. `null` hasta que hay período. */
export function adxValues(candles, period = 14) {
  const output = new Array(candles.length).fill(null);
  if (candles.length < period * 2 + 1) return output;
  const trueRange = [0];
  const positiveDm = [0];
  const negativeDm = [0];
  for (let index = 1; index < candles.length; index += 1) {
    const current = candles[index];
    const previous = candles[index - 1];
    const up = current.h - previous.h;
    const down = previous.l - current.l;
    positiveDm.push(up > down && up > 0 ? up : 0);
    negativeDm.push(down > up && down > 0 ? down : 0);
    trueRange.push(Math.max(
      current.h - current.l,
      Math.abs(current.h - previous.c),
      Math.abs(current.l - previous.c),
    ));
  }
  let atr = 0;
  let smoothedPositive = 0;
  let smoothedNegative = 0;
  for (let index = 1; index <= period; index += 1) {
    atr += trueRange[index];
    smoothedPositive += positiveDm[index];
    smoothedNegative += negativeDm[index];
  }
  const dx = new Array(candles.length).fill(null);
  for (let index = period + 1; index < candles.length; index += 1) {
    atr = atr - atr / period + trueRange[index];
    smoothedPositive = smoothedPositive - smoothedPositive / period + positiveDm[index];
    smoothedNegative = smoothedNegative - smoothedNegative / period + negativeDm[index];
    const positiveDi = atr ? 100 * smoothedPositive / atr : 0;
    const negativeDi = atr ? 100 * smoothedNegative / atr : 0;
    const sum = positiveDi + negativeDi;
    dx[index] = sum ? 100 * Math.abs(positiveDi - negativeDi) / sum : 0;
  }
  let currentAdx = null;
  let accumulator = 0;
  let count = 0;
  for (let index = period + 1; index < candles.length; index += 1) {
    if (dx[index] == null) continue;
    if (currentAdx == null) {
      accumulator += dx[index];
      count += 1;
      if (count === period) {
        currentAdx = accumulator / period;
        output[index] = currentAdx;
      }
    } else {
      currentAdx = (currentAdx * (period - 1) + dx[index]) / period;
      output[index] = currentAdx;
    }
  }
  return output;
}

// Los scripts clásicos (NexUX Trading carga `app.js` sin `type="module"`) leen
// el módulo desde acá. No hay copia de respaldo: si esto falta, el consumidor
// falla ruidosamente en vez de recalcular por su cuenta.
if (typeof globalThis !== "undefined") {
  globalThis.NexuxChartSeries = Object.freeze({
    CONTRATO_SERIES,
    INTERVALS,
    SeriesError,
    intervalSpec,
    aggregateCandles,
    emaValues,
    rsiValues,
    adxValues,
  });
}
