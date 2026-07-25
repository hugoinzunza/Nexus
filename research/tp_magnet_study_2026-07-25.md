# TP en el imán vs TP lejano teórico — resultado

Fecha: 2026-07-25 · **Research only · No señal · No bot · NO usar para activar live.**

Script: `research/tp_magnet_study.py` · Datos: `tp_magnet_study_results.json`
7.904 setups, 10 datasets (1h × 7 pares + 15m × 3), split OOS en 2025-06-04.

## La idea que se probó

De Hugo: la dirección ya la da la estrategia SMC; lo que falta es estimar **hasta
dónde puede llegar el precio antes de girar** para poner ahí el TP y el SL, en vez
de esperar un TP teórico (tipo "TP4") que nunca llega porque el precio solo iba a
buscar una orden en un precio X y se dio la vuelta.

**Limitación de datos, declarada**: el mapa de liquidaciones y la profundidad
histórica del libro **no son descargables** con el plan API (sondeo 2026-07-25:
401 "Upgrade plan" en todos los rangos e intervalos). El imán se aproxima con
estructura de precio —pivotes confirmados y no barridos, y clústers de pivotes—
que es el mismo concepto (dónde hay órdenes esperando). La versión con niveles
reales de CoinGlass solo podrá validarse hacia adelante.

## Parte 1: el diagnóstico es CORRECTO

La tasa de llenado del TP confirma la mecánica que describe la idea:

| Variante de TP | rr medio | TP se llena |
|---|---|---|
| `lejano` (proxy del "TP4") | 11.0 | **13.0%** |
| `cluster` (imán más denso) | 5.6 | 21.7% |
| `cercano` (lo que hace el plan hoy) | 3.8 | 26.4% |
| `alcance_p35` (cap por alcance empírico) | 2.4 | 33.1% |
| `fijo_2r` (control) | 2.0 | 34.9% |

En 15m OOS el TP lejano se llena **8.4%** de las veces. El precio efectivamente
**no llega** al objetivo teórico: eso queda medido, no discutido.

## Parte 2: pero capar el TP EMPEORA el resultado

En el subconjunto más limpio (1h, out-of-sample) la degradación es **monótona**
según cuánto se capa:

| Combo (1h OOS) | n | TP lleno | avg netR |
|---|---|---|---|
| `lejano` \| estructural | 648 | 19.1% | **+0.279** |
| `cluster` \| estructural | 643 | 24.7% | +0.107 |
| `cercano` \| estructural | 638 | 25.9% | +0.040 |
| `alcance_p35` \| estructural | 629 | 29.1% | −0.026 |
| `fijo_2r` \| estructural | 649 | 33.9% | −0.064 |

**Por qué**: el payoff es de cola gorda. El TP lejano se llena poco pero cuando
llena paga 7-12R, y eso financia todas las pérdidas. Al capar, la tasa de acierto
sube (13% → 35%) pero **el pago promedio cae más rápido de lo que sube el acierto**.

Esto **reproduce de forma independiente** la evidencia previa: el playbook del
30-jun ya concluía que "capar winners mata la estrategia" (RR fijo 2: −0.096R vs
liquidez RR≥2: +0.371R). Con otra maquinaria y otro universo, `fijo_2r` vuelve a
ser el peor. Dos estudios distintos, misma conclusión.

**La mitad TP de la idea queda refutada.** Con la ironía de que el mecanismo que
describe es real (el TP no llega) pero la conclusión operativa es la opuesta:
conviene apuntar lejos *precisamente porque* las pocas veces que llega, paga todo.

## Parte 3: la mitad del SL sí sirve — y es lo aprovechable

Poner el stop **apenas más allá del imán opuesto más cercano** (en vez del stop
estructural puro) mejora en casi todos los cortes, y sobre todo reduce el riesgo:

| Corte | `lejano`\|estructural | `lejano`\|tras_imán | DD estructural → tras_imán |
|---|---|---|---|
| TODO | −0.010 | **+0.008** | 696 → 546 (−22%) |
| OOS | −0.080 | **+0.049** | 283 → 200 (−29%) |
| 15m OOS | −0.215 | **+0.000** | 457 → 212 (−54%) |
| 2025 | −0.162 | −0.067 | 366 → 280 |
| 2026 | +0.064 | **+0.235** | 132 → 106 |
| 2024 | −0.091 | −0.108 ✗ | 421 → 375 |
| 1h OOS | +0.279 | +0.185 ✗ | 44 → 37 |

En OOS **las cinco** variantes de TP mejoran con `tras_imán`. La reducción de
drawdown es el efecto más consistente de todo el estudio (−22% a −54%).

Pero no es universal: empeora en 2024 y en el subconjunto 1h. Igual que el estudio
de aborto, esto se comporta como **modulador de riesgo, no como alpha**.

## Veredicto

| Mitad de la idea | Veredicto |
|---|---|
| **TP en el imán** | **Refutada.** El diagnóstico es correcto, la conclusión es la inversa. No implementar. |
| **SL tras el imán opuesto** | **Candidato débil.** Mejora expectativa en 5 de 7 cortes y baja el DD entre 22% y 54%, pero falla en 2024 y en 1h. |

Nada en el universo completo supera cero de forma robusta: el mejor combo global
(`lejano`\|`tras_imán`) da **+0.008**, que es cero con pasos extra.

## Qué NO llevar al bot

Nada de esto. En particular: no cambiar la lógica de TP del plan, porque el
estudio dice que la actual (TP a liquidez, sin capar) es **mejor** que las
alternativas propuestas.

## Próximo paso, si se quiere seguir

Lo único con evidencia a favor es el SL tras el imán opuesto. Antes de considerarlo
hay que entender **por qué falla en 2024 y en 1h** — si es régimen, la mejora en el
resto es prestada. Un estudio de eso es barato y responde antes de tocar nada.

La versión con niveles **reales** de CoinGlass (mapa de liquidaciones, muros del
libro) no es backtesteable: solo se puede registrar hacia adelante y comparar en
unos meses.
