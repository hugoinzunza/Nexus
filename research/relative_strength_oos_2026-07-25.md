# Fuerza relativa vs BTC: ¿mejora la selección de pares? — DESCARTADA

Fecha: 2026-07-25 (cómputo) · 2026-07-26 (verificación e informe)
**Research only · No señal · No bot · NO usar para activar live.**

Script: `research/relative_strength_oos.py` · Datos: `relative_strength_oos_results.json`
y `relative_strength_oos_trades.json` · Tests: `research/test_relative_strength_oos.py`

## Nota de procedencia, que importa para leer esto

El cómputo lo produjo un agente en segundo plano que **fue detenido antes de entregar
el informe, los tests y el commit**. Retomé su trabajo: verifiqué la metodología
—en particular la causalidad, que es lo único que no se puede dar por bueno—, y
escribí este informe y los tests. Lo que verifiqué línea a línea:

- El instante de decisión es el **cierre de la barra de señal** (`t + TF_MS[sel_tf]`).
  Confirmado que `t` en el volcado es el **open** de esa barra (`sel[i]["t"]`, formato
  Binance), así que sumarle el timeframe da su cierre y no una vela del futuro.
- `idx_cerrada(ms) = bisect_right(t, ms − 1h) − 1`: la última vela 1h cuyo **cierre**
  es anterior o igual al instante de decisión. La beta se calcula sólo con prefijos
  acotados por ese índice.
- BTC nunca se rankea contra sí mismo (`btc_en_el_ranking: NO`).
- Bootstrap por bloques **mensuales**, que es la unidad razonable acá.

## El universo es el correcto

Usa `data/setup_backtest_trades.json`, el volcado del **pipeline real del bot**
(`smc_live.analyze`, POIs en 1D/4h/1h, planeación 1h/4h). **No hay 15m**, que era el
riesgo grande: el 71% del universo de research antiguo era un timeframe que el bot no
opera, y eso contaminó los titulares de varios estudios previos.

Span 2022-04-30 → 2026-06-14, corte IS/OOS en 2025-03-19.
Baseline rr≥5: **n=3796** (descartados 697 por rr<5 y 4147 por no activarse).

| Universo | baseline OOS | n |
|---|---|---|
| plan de 5 pares (BTC, ETH, SOL, ADA, XRP) | **+1,001R** | 1.250 |
| los 7 pares con klines | +0,774R | 1.766 |

Aviso sobre esa cifra: es alta porque hereda la cola gorda del pipeline alineado. En
OOS el **1% mejor de los trades aporta el 30%** del resultado, y sin él el promedio
baja a +0,704R. No es una expectativa que deba leerse como estable.

## El resultado: no aporta información

### Filtro direccional (D) — nada sobrevive a la corrección múltiple

Se probaron **81 variantes** en el plan de 5 pares y **135** en el de 7: tres
definiciones de fuerza (bruta, residual ajustada por beta, z-score causal) × tres
ventanas (24 h, 3 d, 7 d) × tres cortes de ranking (top 1, 2 o 3 de 4) × tres lados
(solo long, solo short, ambas).

| | plan 5 pares | todos 7 pares |
|---|---|---|
| pruebas | 81 | 135 |
| **significativas tras Holm** | **0** | **0** |
| mejor p crudo | 0,0515 | 0,0140 |
| p tras Holm del mejor | 1,0 | 1,0 |

En la tabla de intervalos **sin corregir** aparecen 5 variantes cuyo CI95 no cruza
cero — y una de ellas es *peor* que el baseline. Con 81 pruebas al 5%, lo esperable
por puro azar son ~4. Es exactamente lo que produce el ruido, y Holm las elimina
todas. **Ninguna de esas 5 es un hallazgo: son el precio de haber probado 81 cosas.**

### Monotonía (B) — no existe

Si la fuerza relativa informara, el resultado debería empeorar de forma ordenada al
bajar en el ranking. Se midió la pendiente de resultado contra posición:

- plan 5 pares: **35 de 36** pendientes con CI que cruza cero.
- 7 pares: **36 de 36**.

Sin monotonía, cualquier umbral que funcione es un umbral elegido, no un efecto.

### Placebo contrario (E) — tampoco muestra nada

La variante invertida —longs débiles y shorts fuertes— cubre los **mismos lados y las
mismas 81 variantes**, y ninguna se separa de cero. Que el placebo no muestre señal es
lo correcto, y confirma que no hay estructura en ninguna dirección: no es que la señal
esté al revés, es que no hay señal.

**Asimetría que encontré al escribir los tests, y que hay que declarar**: al placebo
le falta el bootstrap específico de OOS (`OOS_dif_vs_baseline`) que sí tiene el filtro
direccional; sólo trae el del período completo. Así que **no es un control
perfectamente pareado**. No cambia el veredicto —el filtro ya muere en Holm y el
placebo sale plano donde sí se midió— pero si alguien quisiera reabrir esta línea,
tendría que corregir eso primero.

### Ranking como priorizador (C) — no supera al azar

Cuando varios setups coinciden en el tiempo, elegir por ranking en vez de al azar da
**+0,147R** de diferencia, con CI95 [−0,058, +0,358] que **cruza cero** (p=0,087).
En 7 pares: +0,116R, CI [−0,092, +0,327]. Es la variante más cercana a algo, y no
llega.

## CoinGlass: no se pudo cruzar, y está bien no haberlo forzado

| | |
|---|---|
| símbolos en el store | **sólo BTC** |
| ventana | 2026-01-25 → 2026-07-24 (6 meses) |
| snapshots | 1.146 a 4 h |
| trades del backtest dentro de la ventana | **392 de 3.796** |

Dos razones por las que no aplica, y las dos son estructurales:

1. Una fuerza relativa **transversal** necesita OI, funding y taker **por par**. El
   store sólo tiene BTC, así que no hay con qué comparar entre pares.
2. Aunque se usara como contexto de mercado, el solape deja ~6 meses efectivos, y la
   unidad válida de remuestreo es el mes. Seis observaciones no deciden nada.

El agente se negó a forzar el cruce y lo dejó declarado. Es la decisión correcta.

## Veredicto

| Uso propuesto | Veredicto |
|---|---|
| Filtro direccional (longs fuertes / shorts débiles) | **DESCARTADO.** 0 de 81 y 0 de 135 tras Holm. |
| Ranking para priorizar coincidencias | **DESCARTADO como regla.** +0,147R con CI que cruza cero. |
| Variable descriptiva / contexto visual | **Sin valor demostrado**, y sin monotonía no hay nada que mostrar. |
| Cruce con CoinGlass | **No evaluable** con el store actual. |

## Recomendación explícita

**NO USAR.** Ni como filtro, ni como ranking, ni como columna. No es "prometedor pero
débil": es un resultado negativo robusto, que es justamente el tipo de resultado que
sí permite descartar. Se probaron 216 variantes entre los dos universos y ninguna
sobrevivió a la corrección por pruebas múltiples, sin monotonía y con el placebo
igualmente plano.

Lo que sí queda es el **script reproducible**, por si alguna vez hay datos por par en
CoinGlass y vale la pena repetirlo con la maquinaria ya escrita.

## Limitaciones y datos faltantes

- El baseline hereda la cola gorda del pipeline alineado (1% de trades = 30% del
  resultado OOS). Cualquier comparación de promedios contra él es ruidosa por
  construcción, y eso **reduce el poder** para detectar mejoras chicas. Un efecto de
  +0,1R podría existir y no verse.
- 16 meses OOS = 16 bloques mensuales. Con esa cantidad, sólo efectos grandes son
  detectables.
- La beta usa una ventana fija de 720 velas (30 d). No se probó sensibilidad a esa
  ventana, y elegirla a posteriori habría sido sobreajuste.
- El backtest de origen tiene su propia brecha con la realidad, sin resolver: predice
  67,4% de llegada a TP1 contra 33,3% observado en el Diario (ver
  [`universo_alineado_2026-07-25.md`](universo_alineado_2026-07-25.md)). Todo lo de
  acá se apoya en ese backtest.
- No se evaluó fuerza relativa contra un índice de altcoins, sólo contra BTC.

## Siguiente experimento de menor riesgo

Ninguno en esta línea. El costo de oportunidad manda: lo que decide rápido es el
estudio pareado `muros_vs_niveles_vacios` (~11.000 observaciones diarias contra 16
bloques mensuales acá), y lo que está sin resolver y bloquea todo es la brecha entre
el backtest y el Diario. Insistir con fuerza relativa sería seguir cavando donde ya
se midió que no hay nada.
