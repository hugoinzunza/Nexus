# HYP-EXIT-003-SHADOW — Protocolo forward congelado

> Research only - No señal - No bot

## Cohorte

- Inicio: `2026-08-01T14:07:28Z`.
- Unidad: toda operación activada después del inicio.
- Comparación: ramas original y `protect_3r_runner_original` pareadas por
  `operation_id`.
- Las operaciones que no alcanzan 3R permanecen en la cohorte.
- Datos: velas cerradas de 1 minuto y book ticker públicos de Binance Futures.
- Precisión del momento de 3R: un minuto; no se afirma conocer el orden de ticks
  dentro de la vela.

## Política observada

- Entrada, stop original y target original permanecen iguales.
- Al alcanzar 3R, el stop protegido pasa a break-even desde la vela siguiente.
- Si stop y target aparecen en la misma vela, prevalece el stop.
- La vela de activación puede acreditar SL, pero nunca TP.
- Horizonte máximo por operación: 90 días.

## Costos

- Entrada maker: 0,02%.
- Target maker: 0,02%.
- Stop/timeout taker: 0,05%.
- Slippage market modelado: 0,02%.
- Cruce de spread: medio spread observado mediante `bookTicker` al detectar la
  salida. Si falta, el resultado neto queda sin resolver; no se inventa.

## Decisión predefinida

La evaluación no comienza antes de reunir simultáneamente:

- 100 operaciones pareadas cerradas;
- 25 operaciones que hayan alcanzado 3R;
- 12 semanas calendario.

Promoción a revisión manual únicamente si se cumplen **todos**:

- límite inferior del IC95 bootstrap semanal de `delta AvgR neto` mayor que 0;
- mejora absoluta de PF de al menos 0,10;
- mejora relativa de PF de al menos 5%;
- reducción relativa de drawdown de al menos 10%;
- ninguna pérdida de AvgR neto.

Descarte anticipado, después de la muestra mínima, si el límite superior del
IC95 no supera 0, el PF empeora 5%, el drawdown aumenta 10% o el AvgR cae al
menos 0,05R.

Tope terminal: 200 cierres pareados o 26 semanas. Si entonces no satisface todos
los criterios de promoción, se descarta para producción.

Los cortes por par o timeframe son diagnósticos y no pueden reemplazar la
decisión primaria. Las reglas no pueden cambiar después del inicio.
