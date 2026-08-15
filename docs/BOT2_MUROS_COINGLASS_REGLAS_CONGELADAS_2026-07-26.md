# BOT2 — reglas congeladas antes de mirar resultados

Fecha de congelamiento: **2026-07-26**, ANTES de calcular ningún resultado.
Research only · paper por construcción · no toca BOT1, ni el Diario, ni Fase 2.

Este documento existe para que dentro de meses se pueda distinguir una **hipótesis
predefinida** de un **hallazgo post-hoc**. Si una regla se cambia, se agrega abajo
con fecha y motivo; **no se edita la original**. Una regla ajustada después de ver
sus resultados deja de ser evidencia y pasa a ser decoración.

## Qué es BOT2 (y qué NO es)

**NO es** un segundo bot con su propia estrategia y su propio universo. Eso se
descartó con una medición: el forward produce ~1,3 días independientes por semana,
y dos bots con universos distintos partirían esa evidencia escasa en dos pozos
incomparables — cualquier diferencia podría ser régimen, universo o suerte.

**ES** un evaluador contrafactual sobre los **mismos setups** que BOT1. Para cada
setup real, se registra el contexto CoinGlass del momento y se simula qué habría
pasado con cada regla. La comparación es **pareada**: mismos trades, misma ventana,
la única variable es la regla. Cada trade real se vuelve evidencia doble.

Mismo patrón que la columna diagnóstica CDC-8 que ya corre en el Diario.

## Las reglas

Todas operan sobre el contexto CoinGlass vigente **en el momento de la activación**
del setup (captura anterior o igual, nunca posterior).

### R1 — VETO por muro opuesto en el camino

> Si entre el precio de entrada y TP1 (1R) existe un muro del libro **contrario a
> la dirección del trade** cuyo monto sea ≥ `UMBRAL_MURO`, el trade se **anula**
> (no se abre).

- Long: se busca un muro **ask** en `(entry, entry + 1R]`.
- Short: se busca un muro **bid** en `[entry − 1R, entry)`.
- `UMBRAL_MURO = 5.000.000 USD`. Congelado ahora, sin mirar datos. Justificación
  previa: es el mismo umbral que ya usa el mapa visual para clústers, y la mediana
  de muro medida en producción es 1,8M, así que 5M selecciona la cola alta sin ser
  el máximo.

**Por qué esta es la regla principal**: sólo REMUEVE trades, así que no puede
inflar el edge por un error de ejecución — sólo reduce muestra. Y ataca la herida
medida: el 67% de los trades reales muere sin llegar nunca a 1R.

### R2 — TP recortado al muro

> Si existe un muro a favor de la dirección entre la entrada y el TP original, el
> TP se mueve **justo antes** de ese muro (a `muro × (1 ∓ 0,0005)`).

**Expectativa declarada: que PIERDA.** El estudio del imán (2026-07-25) probó que
capar ganadoras empeora la expectativa de forma monótona, y que `fijo_2r` es
negativo en ambos timeframes. R2 se incluye **como control negativo**: si saliera
positiva con muros reales, contradiría un resultado ya establecido y habría que
sospechar del pipeline antes que celebrar.

### R3 — SL tras el muro

> Si existe un muro a favor de la dirección **más allá** del SL estructural, el SL
> se corre justo detrás de ese muro.

**Expectativa declarada: que sea neutra o negativa en 1h.** Ya está refutada con
proxies de estructura: el efecto resultó ser régimen, no gestión, y **resta**
justo en 1h, el único timeframe donde la estrategia gana sola. Se incluye para ver
si los muros REALES se comportan distinto de los proxies — no porque se espere que
funcione.

## Predicciones registradas

Escribirlas antes evita el sesgo de retrospectiva ("ya lo sabía"):

| Regla | Predicción |
|---|---|
| R1 | La única con chance. Debería subir avgR **reduciendo** trades. Si sube avgR sin reducir cobertura, sospechar del pipeline. |
| R2 | Pierde. Es control negativo. |
| R3 | Neutra o negativa en 1h. |

## Criterios de éxito, también congelados

Una regla pasa el **Gate 2** sólo si cumple **todo**:

1. **n ≥ 50 setups afectados** (no 50 setups totales: 50 donde la regla cambió algo).
2. Mejora del avgR neto pareada, con **CI95 por bloques que no cruza cero**.
3. La mejora **sobrevive a quitar el 1% mejor de los trades** — en estos datos ese
   1% aporta ~48% del resultado.
4. Consistente en **IS y OOS** por separado.
5. **No se elige el mejor umbral a posteriori.** Si se prueban varios valores de
   `UMBRAL_MURO`, se publican **todos** y se aplica corrección por pruebas
   múltiples.

Nada pasa al bot sin Gate 3: flag en config, **apagado por defecto**, con su propio
período de dry-run, y sin tocar el criterio pre-registrado de Fase 2.

## Limitación grande, declarada ahora

El colector captura **sólo BTCUSDT**, y el Diario produce ~15 setups de BTC cada 43
días. Aunque todo funcione perfecto, llegar a n≥50 **afectados** toma **más de un
año**. BOT2 no va a responder pronto; existe para que cuando haya datos, existan
también las reglas escritas de antemano.

El estudio pareado `muros_vs_niveles_vacios` (~11.000 observaciones/día) es el que
decide **rápido** si la premisa vive. Si el Gate 1 falla, BOT2 se archiva y no se
invierte más.

## Bitácora de cambios

*(vacía — cualquier cambio va acá con fecha y motivo, sin editar lo de arriba)*
