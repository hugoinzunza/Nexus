# El backtest alineado con el bot no coincide con la realidad

Fecha: 2026-07-25 · **Research only · No señal · No bot.**
Script: `research/universo_alineado.py` · Datos: `universo_alineado_results.json`
Fuente: `data/setup_backtest_trades.json` (volcado de `run_setup_backtest`, traído del VPS).

La tarea era resolver la contradicción del decaimiento sobre el pipeline que
realmente corre. Se resolvió, pero por el camino apareció algo que la vuelve
prematura.

## Lo primero: los números publicados de ese backtest no eran comparables

`modules/trading/run_setup_backtest.py` es el único que reproduce el pipeline del
bot (reusa `smc_live.analyze`: POIs en 1D/4h/1h proyectados sobre 1h/4h). Pero:

1. **No aplicaba costos.** El `cost_rate` sólo vive dentro de `_equity_sim`; el
   `avg_r`, el `by_year` y el `out_sample` que publica son **brutos**. Con el modelo
   maker-aware del Diario y la mediana de `sl_pct` (0,8%) eso son ~0,05R por
   ganadora y ~0,11R por perdedora; en el decil de stops ajustados (0,4%), 0,10R y
   0,23R.
2. **Mide rr≥2** (`smc_live.MIN_RR = 2.0`), mientras el plan opera
   `SELECTIVE_MIN_RR = 5.0`.

Reagregué el volcado por-trade aplicando los costos del Diario y separando por rr.
No hubo que re-correr nada.

## La pregunta del decaimiento: respondida, y es que NO decae

rr≥5, pipeline del bot, **con costos**, 5.289 trades activados:

| Ventana | avg netR | PF | n |
|---|---|---|---|
| 2022-04 .. 2023-02 | +0,524 | 1,56 | 915 |
| 2023-02 .. 2023-12 | +0,476 | 1,49 | 940 |
| 2023-12 .. 2024-10 | +0,361 | 1,37 | 1.082 |
| 2024-10 .. 2025-08 | **+0,879** | 1,92 | 1.182 |
| 2025-08 .. 2026-06 | +0,659 | 1,69 | 1.169 |

**Las cinco ventanas positivas**, el valle en el medio y el tramo reciente fuerte.
Igual en rr≥2, rr≥3 y rr≥8. El bootstrap por bloques no cruza cero (CI95
[+0,414, +0,785] en todo; [+0,401, +1,173] en OOS).

Y sobrevive a sacarle la cola: quitando el **1% mejor de los trades** —que aporta
el 48% de la ganancia— queda en +0,313R, todavía positivo.

Así que la afirmación "1h × rr≥5 es decayente" del informe del 5-jul **no se
sostiene** sobre el pipeline alineado. Venía de un proxy que detecta POIs sobre una
sola serie, que es otra estrategia.

## Pero acá se cae todo: el backtest no describe lo que pasa

El Diario lleva **43 días** con 39 trades cerrados. Comparado con el mismo backtest
corriendo la variante `real_vivo` (el plan de salida en vivo: parciales + break-even):

| | Backtest `real_vivo` | Diario real |
|---|---|---|
| llegan a TP1 (1R) | **80,9%** | **33,3%** |
| ganadora mediana | 1,4R | 1,5R |
| avg netR | **+0,822** | **−0,170** |

La ganadora mediana **coincide** (1,4 vs 1,5R): el plan de salida está bien
modelado. Lo que no coincide es cuántos trades llegan siquiera al primer parcial.

**P(≤13 de 39 | p=0,809) = 1,2 × 10⁻¹⁰.**

Eso no es muestra chica ni mala suerte. Con 39 trades ya alcanza para descartar que
sea azar. El backtest cree que 8 de cada 10 activaciones tocan 1R; la realidad
entrega 3 de cada 10.

## Por qué esto importa más que el decaimiento

El plan de salida real (`setups_store.PARTIAL_LEGS`) cierra **50% en 1R y 25% en
2R**, mueve a break-even tras TP1 y deja un runner de 25%. O sea **75% de cada
posición topa en ≤2R**. Si el runner muere en break-even, el trade entero paga
0,5×1 + 0,25×2 = **1,0R** — que es justo la mediana real observada.

Ese diseño depende por completo de que las activaciones lleguen a 1R. Si llegan el
81% de las veces, funciona. Si llegan el 33%, no: la mitad de la posición nunca se
asegura y el break-even nunca se activa, así que los perdedores pagan −1R completo
mientras los ganadores siguen topados.

**Esa es la brecha, y es de modelo, no de mercado.**

## Qué NO se puede concluir todavía

- **No** que el edge exista: el backtest que lo dice está en desacuerdo con la
  realidad por un factor irreconciliable.
- **No** que no exista: 43 días de un solo régimen tampoco prueban lo contrario.
- **No** que el plan de salida esté mal: está bien modelado (la ganadora mediana
  calza). El problema está aguas arriba, en cuántos trades llegan a 1R.

Lo único firme es que **hay un error de modelo sin identificar**, y que ningún
número de backtest debe usarse para decidir sobre la Fase 1 hasta encontrarlo.

## Encontrado: look-ahead en la barra de activación

Mi primera sospecha era que a los tramos parciales les faltaba la regla conservadora
(SL y TP en la misma vela ⇒ SL). **Estaba equivocada**: `_simulate_scaled` sí revisa
el stop primero y retorna. El error es otro y más sutil.

`_resolve` marca `act_idx = j` en la barra que **entra a la zona**, y
`_simulate_scaled` recorre `range(act_idx, end)` — o sea **incluye esa misma barra**,
usando su máximo y su mínimo completos.

Para un long, activarse significa que el **mínimo** de la barra bajó a la zona. Pero
el **máximo** de esa misma barra pudo ocurrir *antes*, cuando el precio venía
cayendo. Contar ese máximo como TP1 lleno es mirar hacia atrás: esa subida ya había
pasado cuando se entró.

Reproducido con dos barras sintéticas (long, entrada 100, SL 99, TP 110):

| Barra de activación `h=101,5 / l=99,5`, siguiente barra al SL | R |
|---|---|
| empezando **en** la barra de activación | **+0,5** |
| empezando en la barra **siguiente** | **−1,0** |

**1,5R de diferencia por trade**, en la dirección exacta del desacuerdo observado. Y
pega justo donde tiene que pegar: TP1 está a 1R (~0,8% con el `sl_pct` mediano), una
distancia que el rango de una barra de 1h o 4h cubre casi siempre. El TP lejano
(rr mediano 9,9) casi nunca se llena en la misma barra, por eso el sesgo aparece en
la variante con parciales y no en la de TP completo.

## Qué queda en pie y qué no

| Número | Estado |
|---|---|
| `actual` / TP completo (+0,579R) y su walk-forward | **En pie.** No lo afecta: en esa ruta la revisión de SL en la barra de activación es *conservadora* (puede matar un trade de más), y el TP lejano casi nunca se llena intrabarra. |
| `real_vivo` (+0,822R), la variante que modela el plan que CORRE | **Inválido.** Es el que tiene el sesgo, y es el único que importa para el bot. |
| "el edge no decae" | **En pie**, porque se midió sobre TP completo. |
| "el plan de salida en vivo es rentable" | **Sin evidencia.** Nunca se midió bien. |

## Lo que esto significa

El bot opera con parciales: 50% en 1R, 25% en 2R, break-even tras TP1. La única
medición que existía de ese plan estaba inflada por look-ahead. Corregida, la
realidad del Diario (33% llega a TP1, −0,170R en 39 trades) deja de ser un misterio
y pasa a ser el dato.

Y hay una tensión que ahora queda expuesta: el estudio del imán demostró que **capar
ganadoras empeora la expectativa de forma monótona**, y el plan en vivo capa el 75%
de cada posición en ≤2R. Con el número inflado eso parecía compatible; sin él, no
hay nada que sostenga que el plan de salida actual sea mejor que dejar correr.

## Qué NO hacer con esto

No cambiar el plan de salida. La evidencia dice que la medición estaba mal, no que
la alternativa sea mejor — eso hay que medirlo, y con el `act_idx` corregido.

---

# APLICADO: el fix y lo que pasó después

`_simulate_scaled` arranca ahora en `act_idx + 1`. Backtest re-corrido completo
(~28 min de CPU, 11.815 registros, 6.263 activados).

## El sesgo era real y grande

| Variante | a TP1 antes | después | avg netR antes | después |
|---|---|---|---|---|
| `real_vivo` (el plan del bot) | 80,9% | **67,4%** | +0,822 | **+0,493** |
| `runner_agres` | 80,9% | 67,4% | +0,689 | +0,498 |
| `tu_idea` | 80,9% | 67,4% | +0,687 | +0,470 |
| `be_tardio` | 66,5% | 53,6% | +0,665 | +0,452 |
| `actual` (TP completo) | 17,8% | 18,6% | +0,579 | +0,688 |

13,5 puntos de tasa de acierto y **0,33R por trade** de aire en la variante que
modela el plan del bot. La ruta de TP completo casi no se movió, como estaba
previsto: su objetivo está a 8,4% del precio contra 0,80% de TP1, y sólo el 4% de
los trades tiene el TP a menos de 2%, que es lo que una barra podría cubrir.

## Pero la brecha con la realidad NO se cerró

| | Backtest `real_vivo` | Diario real |
|---|---|---|
| llegan a TP1 | **67,4%** | **33,3%** (CI95 21,3% – 50,0%) |

El 67,4% queda **fuera** del intervalo. O sea el fix corrigió un sesgo verdadero
pero queda una segunda fuente de optimismo sin identificar.

## Corrección importante a lo que yo mismo escribí más arriba

Dije que la brecha era decisiva con **P = 1,2 × 10⁻¹⁰**. **Ese número no vale.**
Asume 39 observaciones independientes, y los 39 trades del Diario caen en **8 días**,
con **31 de ellos en tres días seguidos** de mediados de junio. Están masivamente
agrupados: si esos tres días fueron un mal tramo, casi toda la muestra comparte un
solo evento.

Remuestreando **días** en vez de trades —la unidad que sí se aproxima a
independiente— el intervalo real es 21,3% a 50,0%. El 67,4% sigue quedando afuera,
así que la conclusión sobrevive, pero como **indicio, no como demostración**. Con 8
clusters incluso ese intervalo tiene cobertura discutible.

Segunda corrección, menor: comparar la variante `actual` con el resto era comparar
peras con manzanas. Ahí no existe TP1 —el único tramo es el TP lejano— así que su
tasa mide otro evento. Queda excluida y marcada como no comparable.

## Estado de la pregunta que decide la Fase 1

**Sigue sin respuesta.** El plan de salida del bot capa el 75% de cada posición en
≤2R y el estudio del imán probó que capar empeora la expectativa de forma monótona.
Medido bien, `real_vivo` da +0,493R contra +0,688R de dejar correr — o sea el
backtest ahora **también** dice que los parciales restan, pero ese mismo backtest
todavía predice el doble de aciertos de los que se observan. No se puede usar para
decidir hasta encontrar la segunda fuente de optimismo.

## Dónde seguir buscando

Descartadas: la regla SL-primero (existe) y el look-ahead de la barra de activación
(corregido, y no alcanzó).

Quedan, en orden de sospecha:

1. **El llenado de la entrada.** El backtest activa cuando el rango de la barra toca
   la zona; en vivo hace falta que una orden límite se llene a un precio concreto.
   Una barra que roza la zona con la mecha y sigue de largo cuenta como entrada
   llena en el backtest y probablemente no llene en la realidad — y esas entradas
   marginales son justo las que peor terminan.
2. **Régimen.** 43 días, y 31 de los 39 trades en tres días. Puede ser un tramo malo
   y punto. Se responde solo con más forward, no con más análisis.
3. **La resolución dentro de la barra de entrada en `_resolve`**, que decide
   `ganada`/`perdida` con el máximo de esa misma barra para el TP. Es el mismo tipo
   de error que acabo de corregir, en la otra función. Afecta poco por la distancia
   del TP lejano, pero conviene cerrarlo por consistencia.

La 1 es la que más explicaría, y se puede acotar midiendo cuántas activaciones del
backtest ocurren con la barra apenas rozando el borde de la zona.
