# PIVOT-DOM-001 — ¿Los pivotes de BTC 1D prefieren días del mes?

**Método congelado el 2026-08-15 ANTES de computar.** `research_only` · sin
señal · sin bot.

## Origen de la pregunta

Hugo leyó que "los días 5 del mes existe un pivote" y pide verificar si algún
día del mes concentra pivotes de forma repetible. La afirmación del día 5 llega
de afuera (no de mirar estos datos), así que se trata como **hipótesis única
pre-declarada** sin castigo por multiplicidad. El barrido de los otros 30 días
es **exploratorio** y paga corrección de Holm.

## Datos y definiciones

- BTCUSDT **spot 1D**, 2017-08-17 → 2026, velas cerradas UTC (dataset versionado
  `BINANCE_BTCUSDT_DAILY_2017_2026.json`, el mismo de SEASON/TREND).
- Pivote: confirmado **5+1+5** (canon clase 03). Secundario publicado: 3+1+3.
- Día del mes: el del extremo del pivote (UTC), no el de su confirmación.

## El nulo — por qué no vale un chi-cuadrado de tabla

Los pivotes no son independientes (un 5+1+5 impone separación mínima entre
mismos tipos) y los días 29–31 existen menos veces. Nulo por **rotación
circular**: se desplazan los índices de TODOS los pivotes por un corrimiento
k uniforme (4.000 repeticiones, semilla 11) y se relee el día del mes del
calendario real. Preserva exactamente el espaciamiento entre pivotes y la
frecuencia de cada día; destruye solo la alineación con el calendario.

## Tests congelados

1. **Global:** estadístico chi-cuadrado observado vs su distribución bajo el
   nulo rotado → p empírico. Si no rechaza, los "días calientes" son ruido.
2. **Día 5 (pre-declarado):** p empírico unilateral = fracción de rotaciones
   con conteo del día 5 ≥ al observado. Umbral 0,05.
3. **Barrido exploratorio:** p empírico por día × 31 días, corrección de Holm.
   Se publica la tabla completa, no los ganadores.

Highs y lows se publican juntos y separados. Predicción registrada: **nulo en
los tres tests** — los efectos de calendario documentados en cripto (funding,
expiraciones) no tienen por qué fijar *extremos estructurales* en fechas fijas
del mes, y la casa lleva tres estudios de niveles/estacionalidad sin superar
controles.
