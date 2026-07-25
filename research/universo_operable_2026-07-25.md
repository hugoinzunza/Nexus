# Re-lectura de todos los estudios sobre el universo que el bot opera

Fecha: 2026-07-25 · **Research only · No señal · No bot.**
Script: `research/universo_operable.py` · Datos: `universo_operable_results.json`
No recalcula nada: vuelve a leer lo ya calculado, con el corte correcto.

## El problema no era de datos, era de lectura

El detector del Diario ([`smc_live.py:58`](../modules/trading/smc_live.py)) usa
`POI_TFS = ["1D", "4h", "1h"]`. **No hay 15m.** El bot es espejo del Diario.

Pero el universo de research son 7 datasets de 1h y 3 de 15m, y como 15m genera
~2,5× más setups por par, la cuenta quedó **5.648 de 15m contra 2.257 de 1h: 71%
contra 29%**. Los titulares que veníamos citando —los cortes ALL y OOS— son
promedios dominados por un timeframe que el bot no opera.

Tres cosas para no exagerar esto:

1. **Los datos siempre estuvieron.** 14 de 19 estudios guardan el desglose por
   timeframe. No hubo que recalcular nada.
2. **La configuración del bot nunca estuvo mal.** Nunca operó 15m.
3. **Esto ya estaba escrito.** El informe del 5 de julio
   ([`bta_visual_oos_2026-07-05.md`](bta_visual_oos_2026-07-05.md)) concluía, con
   estos mismos números: *"15m no tiene edge (touch −0.111, n=5.632): reconfirma
   'no operar 15m'"* y *"el edge del toque se concentra en 1h"*.

**Lo que falló fue la disciplina de los estudios del 25 de julio —los míos— que
volvieron a encabezar con el agregado mixto pese a que esto ya estaba resuelto.**
No es un hallazgo nuevo; es una regresión metodológica que hay que corregir.

## ¿Es cherry-picking elegir 1h ahora que sabemos que gana?

Es la objeción correcta y hay que responderla con evidencia, no con argumentos.
`POI_TFS = ["1D","4h","1h"]` se fijó en `15895ba`, el **2026-06-11**. El primero de
los estudios re-leídos (`liq_tp_backtest.py`) es del **2026-06-12**, un día después;
los recientes, seis semanas después. **El universo se eligió antes de ver cualquiera
de estos resultados.** No es selección post-hoc.

## El resultado

**1h supera a 15m en 45 de 49 variantes comparables.** Expectativa positiva: **32
variantes en 1h contra 4 en 15m.**

Las 4 excepciones no resisten mirarlas: una tiene **n=4** (ruido puro), dos son
negativas en ambos timeframes (da igual cuál pierde menos), y la cuarta
(`cdc_struct piv10`, +0,031 con n=122) es indistinguible de cero. No hay
excepciones reales.

Lo mejor de todo el inventario, en OOS con costos:

| Variante | 1h | 15m |
|---|---|---|
| **`LIQ20` — liquidez rr≥5** | **+0,371R** · DD 23,8 | +0,036R · DD 46,0 |
| `LIQ15` — liquidez rr≥2 | +0,269R | −0,074R |
| `lejano\|estructural` (imán) | +0,279R | −0,215R |
| `touch` (replay visual) | +0,125R | −0,111R |
| `cluster\|estructural` | +0,107R | −0,239R |
| `abort base` | +0,076R | −0,186R |
| `RR2` — RR fijo 2 (control) | −0,096R | −0,099R |

El filtro que ya está en el plan —**rr≥5**— es lo mejor que tenemos, con **+0,371R
y drawdown de 24R** en el universo que efectivamente se opera. Lo veníamos citando
diluido.

## Qué conclusiones escritas hay que corregir

### 1. `tp_magnet_study_2026-07-25.md` — corrección real

Cierra diciendo: *"Nada en el universo completo supera cero de forma robusta: el
mejor combo global (`lejano|tras_imán`) da +0.008, que es cero con pasos extra."*

En el universo operable eso es **falso**: `lejano|estructural` da **+0,279R** en 1h
OOS con n=648. La frase mide el universo completo, que incluye 71% de un timeframe
que no operamos. **Corregido en ese informe.**

### 2. `sl_iman_regimen_2026-07-25.md` — se refuerza, no cambia

Su hallazgo central ya era sobre 1h y sigue en pie: `tras_imán` **resta** ahí
(+0,185 contra +0,279 del baseline). La re-lectura lo refuerza — el corte donde la
idea ayudaba era justamente el que no operamos. **Sin cambios.**

### 3. `bta_visual_abort_2026-07-05.md` — el veredicto sobrevive y queda más limpio

Decía "candidato débil, NO promover". En 1h el baseline es +0,076 y la mejor
variante de aborto es +0,084: **el aborto aporta 0,008R, o sea nada**. El veredicto
era correcto y ahora se puede decir con más fuerza. **Sin cambios.**

### 4. Lo que NO cambia

`RR2` (RR fijo 2) es negativo en ambos timeframes: −0,096 y −0,099. La conclusión
de que capar winners mata la estrategia **no dependía** del universo. Se sostiene.

## Qué significa para la Fase 1

Nada que obligue a cambiar el plan, y esa es la buena noticia: el criterio
pre-registrado no se toca, el bot ya operaba el universo correcto y el filtro rr≥5
está mejor validado de lo que decíamos, no peor.

Lo que sí cambia es el **piso de expectativa razonable**: +0,371R en OOS con costos
y DD de 24R, en vez de los números diluidos que veníamos citando. Eso importa para
juzgar el forward de la Fase 1 sin sorprenderse.

## Una advertencia sobre esto mismo

Este informe hace ver la estrategia mejor que ayer, y eso es exactamente cuando hay
que desconfiar. Tres frenos explícitos:

- **No es evidencia nueva.** Es la misma evidencia leída con el corte correcto. No
  se ganó información; se dejó de perder.
- **Sigue siendo OOS de backtest**, con el mismo proxy y los mismos costos. El
  árbitro sigue siendo el forward de la Fase 1, no esto.
- **El informe del 5 de julio ya avisaba que el edge de 1h×rr≥5 es DECAYENTE**
  (+0,63 en 2022 → ~0 en 2024-2026 en ese proxy). El promedio OOS de +0,371 no
  contradice eso, pero tampoco lo borra: puede ser un promedio sobre un edge que se
  está apagando. **Esa es la próxima pregunta a responder**, y es más importante que
  cualquiera de las dos pistas que quedaron en cola.

## Pendiente que este trabajo destapó

El universo de research y el del bot **no son idénticos**: acá los POIs se detectan
sobre la serie de 1h, mientras el bot los detecta en 1D/4h/1h y los proyecta.
`liq_tp_backtest.py` sí usa `POI_SOURCES = ["1h","4h","1d"]` y por eso es el más
cercano a lo real; los demás no. Alinear eso vale más que agregar cualquier filtro
nuevo, porque hoy estamos validando algo *parecido* a lo que corre, no lo que corre.
