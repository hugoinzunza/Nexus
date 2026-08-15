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

---

## Resultados (2026-08-15, posteriores al freeze — `pivotes_dia_del_mes.py`)

400 pivotes 5+1+5 (190 highs, 210 lows) sobre 3.274 velas, 107 meses.

### 1. Día 5 (la hipótesis pre-declarada): NO confirmada

| Brazo | obs | esperado | p |
|---|---:|---:|---:|
| todos (primario) | 19 | 13,1 | **0,0517** |
| highs | 7 | 6,2 | 0,44 |
| lows | 12 | 6,9 | 0,035 |

El brazo primario queda un pelo por sobre el umbral (0,0517 vs 0,05). El matiz
de los mínimos (p=0,035) no sobrevive el ajuste por haber mirado tres brazos
(×3 → 0,105). Veredicto: **el "día 5" del folclore no se confirma** — hay una
inclinación leve, solo en mínimos, insuficiente.

### 2. Uniformidad global: al borde, no robusta

p=0,0447 en el brazo primario, pero 0,128 en lows y 0,059/0,17 en el pivote
secundario. Con 6 miradas, una p de 0,045 no es un rechazo serio.

### 3. El hallazgo exploratorio real: día 25 en MÍNIMOS

- p cruda = **0,0013**; único valor que sobrevive Holm dentro de su brazo
  (p_holm = 0,039).
- **Consistente en ambas definiciones de pivote** (5+1+5: 15 obs vs 6,9
  esperado; 3+1+3: 19 vs 10,5) y **en ambas mitades de la muestra** (post-hoc:
  2017-2021: 9 vs 3,3; 2022-2026: 6 vs 3,7).
- PERO: es 1 brazo de 6; contra la familia completa (~186 tests) la p ajustada
  ronda 0,24. **Candidato exploratorio, no evidencia.**
- Mecanismo candidato (especulación anotada, no verificada): la expiración
  mensual de opciones cae el último viernes del mes, típicamente entre el 24 y
  el 28.

### Veredicto

Como pregunta original: **no, no existe un día del mes con pivote confirmable
al estándar de la casa** — el día 5 falla su test pre-declarado. El día 25 en
mínimos es lo único que merece memoria: para creerle haría falta pre-registrar
PIVOT-DOM-002 sobre datos que este estudio no tocó (forward, u otros activos
como controles) con esa única hipótesis. Sin señal, sin bot, sin uso operativo.
