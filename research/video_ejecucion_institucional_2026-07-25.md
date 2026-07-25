# Video "Extrader de Goldman Sachs" — qué se puede cruzar con CoinGlass

Fecha: 2026-07-25 · **Research only · No señal · No bot.**
Fuente: canal **Alex Ruiz**, entrevista a **Roberto** (26), <https://www.youtube.com/watch?v=AU4_GdKRMyw>
Transcripción aportada por Hugo (yo no tengo acceso a YouTube desde este entorno).

## Primero, calibrar qué es el video

El título dice "revela los secretos del trading institucional". Lo que el entrevistado
hace es otra cosa, y él lo dice sin adornos:

- En Goldman Sachs estuvo **un año**, con contrato *contingent* vía recruiter, en
  **middle/back office**: confirmar *trade details* de derivados OTC. **Nunca operó**
  ahí. "Nunca he estado yo dentro de ese rol" cuando le preguntan cuánto gana un trader.
- Hoy es **execution trader** en un asset manager boutique de **acciones**. No decide
  dirección ni precio: el *portfolio manager* le da la orden y él busca ejecutarla con
  el menor impacto. Sus palabras: *"nosotros somos un execution desk"*.

Eso no lo descalifica — al contrario, lo hace **más** útil para nosotros que un gurú,
porque describe mecánica que sí conoce de primera mano. Pero define el alcance: es
testimonio sobre **cómo se ejecuta tamaño grande en acciones reguladas**, no sobre
cómo predecir el mercado, y menos sobre cripto. En perps no existe la separación
PM/execution desk que estructura todo su relato, ni el regulador que él cita como
freno. Trasladar su marco entero sería un error de categoría.

## Lo que sí se conecta con lo que tenemos, y es testeable

### 1. Tamaño relativo al volumen, no absoluto — el aporte más aprovechable

Es su marco central y lo repite tres veces con números:

- PM quiere 1.200.000 acciones de un papel con **400.000 de volumen medio a 30 días**:
  3× el ADV, *"claramente vas a mover el precio"*.
- Un papel con **20.000 de ADV** y quieres 200.000: *"eso sí lo divides durante semanas"*.

O sea el impacto no lo determina el monto, lo determina **monto / volumen habitual**.

**Dónde nos pega**: en `research/coinglass_risk_indicator.py` la feature
`book_imbalance` es un desbalance de profundidad **crudo**, sin normalizar por volumen.
Y en el gráfico del libro el umbral de "muro grande" es un corte en **USD absolutos**.
Un muro de 50 M USD no significa lo mismo con volumen horario de 2.000 M que de 200 M,
y hoy los tratamos igual. Eso hace que la métrica no sea comparable entre regímenes —
lo que es exactamente el problema que acabamos de encontrar en el estudio del SL.

**Estudio concreto**: `muro_usd / volumen_del_intervalo` contra el crudo, en las mismas
166 días de `ask-bids-history` a 4h que ya están en disco, con el mismo protocolo
IS/OOS. Barato, y responde si el marco de él aporta o no. **No implementar antes de
medirlo.**

### 2. Confirma que el libro visible subestima el real — y eso corrige nuestra leyenda

Describe la profundidad nivel por nivel igual que nuestro gráfico (bid 100 / ask 100,05,
después 99,95 y 100,10, *con el size de cada uno*). Y agrega el detalle que importa:

> si mandas 5.000 y sólo hay size de 100, el ask se va a ir… *"a menos que haya alguien
> escondido y que tenga muchísimo más de lo que está enseñando, que a veces también pasa"*

Y explica **por qué** fraccionan: para **disimular** la intención. *"Para evitar que
'esta persona está interesada en vender 100.000 shares'"*.

**Esto obliga a una corrección nuestra, ya aplicada.** La leyenda del libro decía que un
muro que desaparece sin ser tocado es *"la firma del spoofing"*. Es falso como
afirmación: tiene al menos tres explicaciones que nuestros datos no separan —orden falsa
para inducir, orden real fraccionada para ocultar tamaño, u orden real cancelada porque
cambió el plan de ejecución—. La leyenda ahora dice eso, y agrega que el tamaño visible
subestima el real. **El marcador ámbar sigue siendo útil, pero mide "se fue sin ser
tocado", no "spoofing".**

### 3. Costos que dependen de la liquidez de la hora

> *"el spread la mayoría del tiempo en el premarket y el postmarket es un poquito más
> amplio, porque hay menos liquidez… siempre tienes que ser con límite"*

Nuestro `_cost_fraction` es **constante**. Cripto no tiene premarket, pero sí tiene
horas delgadas. Si el costo real escala con la liquidez, nuestros backtests están
subestimando el costo en las horas malas — y el hallazgo de que **15m pierde y 1h gana**
podría estar en parte ahí, porque 15m toca muchas más de esas horas.

Es testeable con lo que hay: costo por hora del día contra volumen por hora del día.
Y es del tipo de corrección que hace los resultados **más** conservadores, no menos,
así que vale la pena aunque salga que no cambia nada.

### 4. Corrobora, desde afuera, lo que ya medimos sobre acierto vs pago

Cuenta que armó un modelo de machine learning con RSI y otros técnicos sobre 12 años,
con **65-70% de accuracy de dirección**, y él mismo pone el freno:

> *"que sea direction accuracy no significa que sea el retorno"*

Y cita a Ken Griffin: **56% de acierto alcanza**.

Eso es exactamente el resultado del estudio del imán: capar el TP subió el acierto de
13% a 35% y **empeoró** la expectativa, porque el pago promedio cae más rápido de lo que
sube el acierto. Es corroboración externa de algo que ya teníamos medido, no información
nueva — pero es útil que un tipo que ejecuta tamaño diga lo mismo.

## Lo que el video contradice

Alex le hace **exactamente** nuestra pregunta, en el minuto 59, sin rodeos: si no les
conviene llevar el precio a una zona de soporte para aprovechar esa liquidez de venta y
llenar mejor una orden de 400.000.

Su respuesta es **no**, y el motivo que da es institucional, no moral:

> *"nosotros nunca hacemos algo de una manera en que un regulador pues lo vea… si tú
> estás haciendo algo que te preguntas si va a ser red flags, es porque va a ser red
> flags"* — y todos los trades son auditables.

Cuando le preguntan si ICT / Smart Money permiten predecir lo que hace gente como él,
dice *"yo creo que sí"* pero hay que presionarlo tres veces, y al pedirle **cuál** sería
la huella concreta responde: *"ahorita es la primera vez que se me ocurre"*… **VWAP**.
Eso es una respuesta de cortesía, no evidencia. Y es revelador: la única huella
institucional que puede nombrar es un **calendario de participación por volumen**, no
barridas de liquidez ni fair value gaps.

Sobre manipulación sí afirma algo, pero es **otra** cosa: alguien que se le pone adelante
a 149,99 cuando él ofrece a 150, y cita a RBC y los milisegundos de latencia. Eso es
**front-running por latencia** (la historia de *Flash Boys*), que ocurre en la
microestructura de milisegundos y no tiene nada que ver con mover el precio a un soporte
en un gráfico de 15 minutos. Y su única anécdota de un print raro —100.000 acciones de
golpe en un papel de 300.000 ADV— la atribuye a error o a un PM al que no le importaba
el precio, y se niega explícitamente a llamarla manipulación.

**Honestidad sobre el peso de esto**: es el testimonio de una persona, en acciones
reguladas, con un año de banco en un rol que no operaba. No prueba nada sobre perps de
cripto, donde los actores dominantes son market makers y cascadas de liquidación, sin
regulador equivalente. Pero sí es evidencia **en contra** de la versión ingenua del
relato, y es notable que al pedirle mecanismo concreto no tuviera ninguno.

## Estado

| Punto | Estado |
|---|---|
| Leyenda del libro: "spoofing" → tres explicaciones posibles | **Aplicado** |
| Advertencia de que el tamaño visible subestima el real | **Aplicado** |
| Normalizar muros y `book_imbalance` por volumen | **Propuesto, sin implementar** — hay que medirlo primero |
| Costo dependiente de la liquidez horaria | **Propuesto** — se cruza con el hallazgo 15m vs 1h |
| Acierto vs pago | Ya medido por nosotros; el video lo corrobora |
| Barridas de liquidez institucionales | El video las **desmiente** en su mercado; no aplicable directo a perps |

## Recomendación

De las dos ideas nuevas, la que ordenaría primero es la **normalización por volumen**:
es el marco propio del entrevistado, apunta a un hueco real y medible de nuestro
indicador, y se prueba con datos que ya están en disco. La del costo horario va segunda
porque se cruza con la pregunta más grande que quedó abierta —**si 15m debe seguir en el
universo**—, y conviene responder esa antes de refinar costos dentro de un timeframe
que quizá haya que sacar.

Nada de esto toca el bot ni el plan.
