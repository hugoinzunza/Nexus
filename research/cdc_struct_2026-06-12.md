# ¿La confirmación CDC del plan debe usar el swing micro (PIV=2) o el estructural (PIV=10)?

**Backtest de validación — 2026-06-12** · Tras calibrar los CDC *dibujados* contra
los ejemplos M15 del indicador de referencia (swings estructurales), se probó si
la CONFIRMACIÓN del plan también debía subir de jerarquía.

Misma metodología del estudio CDC (variante B: toque del POI → esperar CDC en
16 velas → entrada en apertura siguiente), solo cambia el pivote del swing que
el cierre debe romper. 7 pares, ~4 años, RR=2, costos, split 70/30, bootstrap.

## Resultados (con costos, OOS)

| TF | Confirmación | n | exp | PF | wr | P(exp>0) |
|----|---|---|---|---|---|---|
| 1h | **PIV=2 (validada)** | 287 | **+0.066R** | 1.13 | 45.3% | **0.82** |
| 1h | PIV=10 (estructural) | 139 | −0.013R | 0.98 | 43.9% | 0.44 |
| 15m | PIV=2 | 378 | −0.055R | 0.89 | 41.5% | 0.18 |
| 15m | PIV=10 | 122 | +0.031R | 1.08 | 49.2% | 0.63 |

(El piv2 de 1h reproduce exactamente el estudio CDC original: +0.066R / P≈0.81 —
chequeo de sanidad del montaje, OK.)

## Veredicto honesto

1. **En 1h — donde vive el edge — la confirmación estructural es PEOR**: pierde
   la mitad de la muestra y la expectativa cae de +0.066R (P=0.82) a −0.013R
   (P=0.44). **La confirmación del plan se queda con PIV=2.**
2. El brillo de PIV=10 en 15m (+0.031R) **no es accionable**: P=0.63, n=122 y el
   in-sample sigue negativo (inconsistente IS/OOS → probable ruido).
3. La explicación tiene sentido: dentro de una ventana de 16 velas tras el toque,
   el quiebre de un swing estructural es un evento tardío y raro — cuando ocurre,
   gran parte del movimiento ya pasó. El CDC micro captura el giro temprano en el
   POI, que es lo que paga.
4. **Convivencia de las dos jerarquías** (decisión de diseño): el gráfico DIBUJA
   los CDC estructurales (la lectura del curso, calibrada con los ejemplos de
   Hugo) y el plan CONFIRMA con el CDC micro (la regla estadísticamente
   validada). Son capas distintas con propósitos distintos.

---

*Reproducible:* `research/cdc_struct_backtest.py` → `research/cdc_struct_results.json`.
Parámetros del estudio CDC original, sin tuneo: PIV(POI)=2, DISP=1·ATR,
ventana=16, RR=2, 70/30, bootstrap 2000.
