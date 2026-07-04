# Playbook BTA/SMC del profe vs Nexux

Fecha: 2026-06-30

Objetivo: estudiar el lenguaje operativo del profe de Bitcoin Traders Academy
(OB, FVG, weak/strong high/low, dealing range, CDC/CHoCH, liquidez) y compararlo
contra lo que Nexux ya implementa/backtestea.

## Resumen ejecutivo

Nexux ya replica buena parte del marco BTA/SMC:

- swings/fractales confirmados,
- weak/strong highs/lows,
- dealing range y EQ 50%,
- premium/descuento,
- liquidity sweep,
- FVG,
- order block,
- POI multi-timeframe,
- mitigacion/invalidacion,
- CDC/CHoCH para dibujo y para confirmacion,
- TP a liquidez opuesta sin barrer,
- SL estructural ajustado.

La diferencia clave: el profe lo usa visual/discrecional; Nexux lo convierte en
reglas mecanicas y luego las valida con historia. En varios puntos conviven dos
capas:

- capa visual fiel al lenguaje del curso,
- capa estadistica validada para decidir si operar o solo mostrar contexto.

## Glosario operativo

### Swing / fractal

Un swing high/low es un pivote confirmado por velas a ambos lados.

Nexux:

- `smc.swing_points(candles, lookback)`
- Un pivote no existe hasta `confirm_idx = idx + lookback`.
- Esto evita repaint/lookahead.

Uso BTA:

- Sirve para construir estructura, weak/strong highs/lows, CDC y targets de liquidez.

### Weak High / Weak Low

Nivel de liquidez aun no barrido. Es objetivo probable porque el mercado tiende a
ir por liquidez pendiente.

Nexux:

- `smc_live._levels`
- Para un high: si ninguna vela posterior lo supera, queda como `Weak High`.
- Para un low: si ninguna vela posterior lo perfora, queda como `Weak Low`.
- Se muestran pocos niveles recientes para no saturar.

Rol:

- Target preferente: siguiente weak high para largos, siguiente weak low para cortos.

### Strong High / Strong Low

Nivel ya barrido/defendido o extremo estructural que define rango. En el grafico
del profe suele marcar el techo/piso mayor desde donde se mide el contexto.

Nexux:

- `smc_live._range`
- Dealing range = swing alto mas alto y swing bajo mas bajo de la ventana.
- `strong_high`, `weak_low`, `eq`.

Nota:

El nombre puede sonar asimetrico porque la convencion actual del payload usa
`strong_high` y `weak_low` para el rango mayor, pero los niveles recientes pueden
tener etiquetas `Strong High`, `Weak High`, `Strong Low`, `Weak Low`.

### Dealing Range y EQ 50%

Rango de decision entre el extremo superior/inferior de la pierna relevante.
El 50% separa premium/descuento.

Uso BTA:

- Largos: se prefieren zonas en descuento.
- Cortos: se prefieren zonas en premium.

Nexux:

- `smc_live._range` dibuja contexto global.
- `strategies.detect_pois` valida el POI contra EQ local del swing al formarse.

Hallazgo importante:

El filtro de EQ GLOBAL como veto empeoro el out-of-sample. La regla correcta
validada es el EQ LOCAL del swing relevante al formar el POI. Ver
`research/dealing_range_2026-06-12.md`.

### Liquidity Sweep / Barrido

Toma de liquidez sobre/bajo un swing previo. En BTA es requisito fuerte para que
un OB sea interesante: el precio barre liquidez y luego desplaza en contra.

Nexux:

- En la version primitiva: wick mas alla de swing y cierre de vuelta adentro.
- En POI: se exige que el order block venga de barrer un weak low/high previo.

Regla POI long:

- Antes del impulso alcista, el OB viene de una zona que toma un weak low previo.

Regla POI short:

- Simetrico: toma un weak high previo.

### FVG / Fair Value Gap

Ineficiencia de tres velas:

- FVG alcista: `high[i-2] < low[i]`
- FVG bajista: `low[i-2] > high[i]`

Uso BTA:

- Confirma displacement/ineficiencia; da evidencia de impulso institucional.

Nexux:

- `smc.find_fvgs`
- `smc_live._fvgs`
- `smc_live.deep_fvgs`

Solo se considera relevante si esta asociado a displacement y contexto de barrido,
no como gap aislado.

### Displacement

Cuerpo impulsivo que sale de la zona. En Nexux se exige cuerpo >= `DISP * ATR`.

Parametros actuales:

- `DISP = 1.0`
- ATR 14.

Rol:

- Filtra OBs sin energia. Sin displacement, un OB es solo una vela opuesta mas.

### Order Block / OB

Ultima vela opuesta antes del impulso con displacement/FVG.

Nexux:

- `smc.find_order_block`
- En POI: se busca la ultima vela opuesta antes del FVG.

POI long:

- Ultima vela bajista antes del impulso alcista.
- Zona = high/low de esa vela.
- Stop estructural = debajo del barrido.

POI short:

- Ultima vela alcista antes del impulso bajista.
- Stop estructural = encima del barrido.

### POI / Point of Interest

OB que cumple condiciones suficientes para vigilar.

Regla Nexux (`strategies.detect_pois`):

POI long valido:

1. FVG alcista.
2. Displacement alcista >= 1 ATR.
3. OB = ultima vela bajista antes del impulso.
4. Viene de barrido de weak low.
5. OB en descuento contra EQ local.
6. Confirmacion solo con vela cerrada (`t_conf`).

POI short:

Misma logica inversa: FVG bajista, displacement bajista, OB alcista, barrido de
weak high, premium local.

Timeframes:

- POIs de `1D`, `4h`, `1h`.
- Planificacion en `1h` y `4h`.
- 15m se usa mas como observacion, no como edge validado.

### Mitigacion

Un POI se mitiga cuando el precio vuelve a tocar la zona del OB.

Nexux:

- `smc_live._pois_for_tf`
- Marca `mitigated`, `valid`, `in_zone`.

Matiz importante:

Cuando el precio toca la zona, tecnicamente se mitiga, pero el plan no debe
desaparecer inmediatamente. Nexux mantiene una fase `cdc_phase` durante una
ventana para esperar confirmacion de CDC.

### Invalidacion

Un POI se invalida cuando el precio rompe el stop estructural:

- long: precio bajo el stop,
- short: precio sobre el stop.

Nexux:

- `invalid = last_price < stop` para long,
- `invalid = last_price > stop` para short.

### CDC / CHoCH / Cambio de Caracter

Cambio de caracter = cierre que rompe el swing relevante en direccion del plan
despues de tocar el POI.

Nexux separa dos capas:

1. CDC estructural para dibujar:
   - `RANGE_PIV = 10`
   - mas parecido a lo visual del profe.
   - niveles pegajosos, filtrados por proximidad.

2. CDC micro para confirmar plan:
   - `CDC_PIV = 2`
   - ventana `CDC_WINDOW = 16`
   - se valida porque en 1h mejora la muestra.

Hallazgo:

- CDC en contexto ayuda en 1h: OOS pasa de -0,096R a +0,066R con costos.
- CDC en 15m no rescata.
- CDC estructural como confirmacion empeora 1h; sirve mejor como lectura visual.

### TP a liquidez

El profe apunta a liquidez, no a un R fijo arbitrario.

Nexux:

- `_opposite_liquidity`
- Long: siguiente `Weak High` sobre referencia.
- Short: siguiente `Weak Low` bajo referencia.
- Si no existe, usa extremo del dealing range como respaldo.
- Exige `RR >= 2`.

Hallazgo mas fuerte:

En 1h OOS con costos, TP a liquidez RR>=2 mejora mucho frente a RR fijo:

- RR fijo 2: -0,096R, PF 0,87.
- Liquidez RR>=2: +0,371R, PF 1,44, P(exp>0)=0,993.

Esto ratifica el criterio del profe: el edge vive en ir por la liquidez opuesta,
no en tomar 2R/3R mecanicamente.

### SL estructural

El SL protege el setup al otro lado del barrido/estructura, no un porcentaje
arbitrario ancho.

Nexux:

- Stop del POI + buffer.
- `SWEEP_BUFFER_PCT = 0.0015`.
- Techo de riesgo: `MAX_SL_PCT = 0.015`.

Hallazgo:

El SL ancho sube win rate, pero destruye R:R. El edge vive en stop estructural
ajustado.

## Que hace Nexux igual que el profe

- Lee estructura multi-TF.
- Busca liquidez pendiente.
- Forma POIs desde OB + FVG + displacement + sweep.
- Distingue premium/descuento.
- No opera POIs mitigados/invalidos.
- Usa TP a liquidez opuesta.
- Dibuja CDC estructural.
- Considera CDC tras toque de POI.

## Donde Nexux se aparta por evidencia

| Concepto | Lectura visual BTA | Decision Nexux |
| --- | --- | --- |
| EQ premium/descuento | Puede mirarse contra rango visible | El veto operativo usa EQ local al formar POI; EQ global queda como contexto |
| CDC estructural | Muy importante visualmente | Se dibuja, pero no veta el plan en 1h |
| CDC micro | Menos visible | Mejor para confirmar entrada en 1h |
| 15m | Util para mirar ejecucion | No hay edge suficiente para scalp |
| TP 2R/3R | Psicologicamente tentador | No captura el edge; capar winners mata la estrategia |
| POI crudo | Parece setup completo | Sin TP liquidez/filtros puede ser perdedor con costos |

## Parametros actuales relevantes

- POI fractal: `PIV = 2`
- Displacement: `DISP = 1.0 ATR`
- Dealing range pivote visual: `RANGE_PIV = 10`
- Dealing range window: `800` velas
- CDC confirmacion: `CDC_PIV = 2`
- CDC window: `16` velas
- POI TFs: `1D`, `4h`, `1h`
- Plan TFs/backtest: `1h`, `4h`
- Min R:R: `2.0`
- Max SL: `1.5%`
- Sweep buffer: `0.15%`

## Checklist manual para estudiar una operacion del profe

1. Identificar la pierna/rango relevante.
2. Marcar strong high/low y weak high/low.
3. Ubicar EQ 50%.
4. Definir si buscamos long en descuento o short en premium.
5. Ver si hubo barrido de liquidez.
6. Ver si despues hubo displacement con FVG.
7. Marcar el OB que origina el impulso.
8. Revisar si el POI sigue sin mitigar e invalidar.
9. Esperar toque/entrada a la zona.
10. Buscar CDC/CHoCH en contexto, si se usa como confirmacion.
11. SL bajo/sobre el extremo estructural protegido.
12. TP en la siguiente liquidez opuesta sin barrer.
13. Exigir R:R real >= 2.
14. No cortar winners en 3R si el plan es el edge de liquidez.

## Proxima tarea recomendada

Para estudiar "todo lo que hace el profe" con mas fidelidad, conviene juntar 10-20
capturas anotadas del curso o del layout BTA en distintos casos:

- long ganador,
- short ganador,
- POI mitigado que falla,
- POI que nunca llena,
- CDC estructural,
- CDC micro,
- weak high tomado,
- weak low tomado,
- FVG profundo,
- OB 1D/4h/1h.

Por cada captura, Nexux deberia decir:

- que nivel detecta,
- que POI detecta,
- si coincide con el profe,
- si no coincide, por que,
- y si el backtest justifica cambiar regla o dejarlo como lectura visual.

Ese seria el camino correcto: calibracion visual caso a caso + validacion historica,
sin convertir intuiciones en filtros hasta que pasen datos.

