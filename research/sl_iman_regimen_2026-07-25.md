# Por qué el SL "tras el imán" ayuda en OOS y falla en 2024 y en 1h

Fecha: 2026-07-25 · **Research only · No señal · No bot · NO usar para activar live.**

Script: `research/sl_iman_regimen.py` · Datos: `sl_iman_regimen_results.json`
Tests: `research/test_sl_iman_regimen.py` (9) · 7.905 setups, 10 datasets, corte OOS heredado.
Viene de [`tp_magnet_study_2026-07-25.md`](tp_magnet_study_2026-07-25.md), que dejó
esta pregunta escrita como próximo paso: *"si es régimen, la mejora en el resto es prestada"*.

**Respuesta corta: es régimen. La mejora es prestada, y peor: está prestada justo
del subconjunto donde la estrategia no sirve.**

## La identidad contable

Ensanchar el stop no puede convertir un ganador en perdedor: el camino de precios es
el mismo y el stop nuevo está más lejos. El estudio verifica eso (**0 anomalías** en
7.905 setups) y por lo tanto toda la diferencia de P&L se descompone en tres términos
exactos, que el test obliga a cerrar:

| Término | Qué es | Signo |
|---|---|---|
| `rescate` | el stop estructural moría, el ancho aguanta hasta el TP | gana mucho |
| `dilucion` | los dos ganan, pero el ancho arriesga más y cobra menos R | pierde |
| `ahorro` | los dos mueren; el ancho paga menos costo relativo | gana poco |

Con eso, "por qué falla" tiene una respuesta aritmética, no narrativa:

| Corte | rescates | dilución | rescate/dilución | Δ avgR |
|---|---|---|---|---|
| 15m OOS | 115 (+647R) | 82 (−392R) | **1,40** | **+0,201** |
| 2026 | 85 (+444R) | 73 (−330R) | 1,16 | +0,152 |
| 2025 | — | — | 0,94 | +0,097 |
| 2024 | 110 (+453R) | 147 (−532R) | 0,75 | −0,005 |
| 2023 | — | — | 0,61 | −0,050 |
| **1h** | 121 (+414R) | 242 (−693R) | **0,50** | **−0,104** |
| 2022 | — | — | 0,71 | −0,114 |

No falla porque el imán deje de funcionar en 2024. Falla porque **en 2024 y en 1h hay
menos trades que rescatar y más ganadores que diluir**. Cuando por cada rescate hay
dos diluciones, la suma es negativa. Es todo.

## Y lo que decide el ratio es la tasa de stop-out del baseline

| Corte | n | stop-out baseline | Δ avgR |
|---|---|---|---|
| 1h | 2.254 | **79,1%** | −0,104 |
| 2022 | 811 | 81,4% | −0,114 |
| 1h OOS | 648 | 80,9% | −0,085 |
| 2024 | 2.004 | 86,8% | −0,005 |
| 2023 | 1.870 | 87,1% | −0,050 |
| 15m | 5.640 | 90,1% | +0,072 |
| 2026 | 1.022 | 88,2% | +0,152 |
| 15m OOS | 1.717 | **91,6%** | **+0,201** |

**Spearman = 0,867.** El corte está en ~87-88%: por debajo, todos negativos; por
encima, todos positivos. El test fija ese umbral para que no se pierda.

Tiene sentido mecánico y por eso es creíble: mientras más pierde el baseline, más hay
para rescatar y menos ganadores quedan para diluir. Las dos fuerzas empujan al mismo
lado, así que el efecto es monótono en la tasa de stop-out. **`tras_imán` no es una
mejora de gestión: es una apuesta a que el stop-out se quede sobre ~88%.**

## El detalle que lo mata como regla operativa

| Timeframe | baseline `lejano` | con `tras_imán` |
|---|---|---|
| **1h** | **+0,229** | +0,114 |
| 15m | −0,105 | −0,032 |

1h es el **único** timeframe donde la estrategia gana plata sola. Y es exactamente
donde `tras_imán` resta. Aplicarlo global significaría sabotear la única parte del
universo que funciona para maquillar la que no. El patrón es el peor posible:
**ayuda donde la estrategia está rota y estorba donde funciona.**

## Corrección a lo que dijo el informe anterior

El informe del imán decía que *"la reducción de drawdown es el efecto más consistente
de todo el estudio (−22% a −54%)"*. Esa tabla no incluía el corte 1h completo. Ahí el
drawdown **empeora**: 89,0 → 137,5 R (**+55%**). En `cercano|1h` también: 60,6 → 104,2.
La baja de drawdown no es un efecto del método, es otra cara del mismo régimen.

## El placebo: ¿aporta el nivel, o solo el ancho?

Control decisivo: un stop con la **misma distribución de ensanche** pero barajada entre
setups del mismo par y timeframe. Mismo riesgo típico, misma dilución, ubicación
desacoplada del imán de ese setup.

| Corte | Δ vs estructural (imán) | Δ vs estructural (placebo) | **ubicación (imán − placebo)** |
|---|---|---|---|
| TODO | +171R · cruza cero | +33R · cruza cero | +99R · **cruza cero** |
| OOS | +291R · no cruza | +46R · cruza cero | **+238R · no cruza cero** |
| 2026 | +156R · no cruza | −13R · cruza cero | **+163R · no cruza cero** |
| 1h | −234R · no cruza | −167R · no cruza | −0,034 avgR |

Acá aparece lo único que no era obvio: **en OOS el nivel sí aporta por encima del puro
ancho** (+238R, CI95 [+0,034, +0,184], no cruza cero). O sea el imán no es decorativo:
poner el stop *en el nivel* rinde más que ponerlo *a esa distancia* en cualquier parte.

Pero ese efecto de ubicación también es parcialmente régimen (**Spearman 0,519** contra
la tasa de stop-out) y en el universo completo **cruza cero**. No alcanza para nada
operativo.

## Veredicto

| Componente | Veredicto |
|---|---|
| `tras_imán` como regla del bot o del plan | **Refutado.** Es una apuesta al régimen, y resta justo en 1h, el único corte que gana solo. |
| La baja de drawdown | **Explicada, no es mérito.** Es el término `ahorro` más los rescates del régimen de alto stop-out. En 1h el drawdown sube 55%. |
| El efecto de ubicación del nivel | **Señal débil pero real en OOS** (+238R, no cruza cero). Insuficiente en el universo completo. Es lo único que justifica seguir midiendo. |

## Qué NO llevar al bot

Nada. Ni el SL tras el imán, ni una versión condicionada a la tasa de stop-out: eso
último sería ajustar el parámetro al régimen ya observado, que es la definición de
overfitting. El plan mantiene su stop estructural.

## Lo que sí queda, y es una conclusión distinta a la buscada

El estudio empezó preguntando por el stop y termina con un hallazgo sobre el universo:
**la estrategia gana en 1h (+0,229R) y pierde en 15m (−0,105R)**, y buena parte de las
"mejoras" que han aparecido en estos estudios (aborto-si-no-CDC, SL tras imán) son
mecanismos que rescatan 15m sin aportar nada en 1h. Antes de seguir buscando parches
de gestión, la pregunta barata es si 15m debería estar en el universo.

Eso responde con los datos que ya están en disco y no toca nada operativo.

## Sobre la versión con niveles reales de CoinGlass

Sigue sin ser backtesteable (la profundidad histórica del libro y el mapa de
liquidaciones dan 401 con el plan actual). El resultado de ubicación en OOS es el
argumento a favor de **registrar hacia adelante** los muros y clústers reales en el
momento del setup, para poder repetir exactamente esta comparación —imán real vs
placebo del mismo ancho— en unos meses. Sin ese registro no habrá nunca con qué
validarlo.
