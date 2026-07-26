# Estudio "ruptura + retest" — el cuarto brazo del evento de entrada

Fecha: 2026-07-26 · **Research only · No señal · No bot · NO usar para activar live.**
`research_only: true` · `execution_enabled: false` · `validated: false`

Script: `research/ruptura_retest.py` · Datos: `research/ruptura_retest_results.json`
Tests: `research/test_ruptura_retest.py` (13 tests, todos verdes)

## Qué se midió y por qué

De los cuatro brazos posibles del evento de entrada —**toque**, **un cierre**,
**dos cierres (CDC)** y **ruptura + retest**— el estudio del abort (2026-07-05)
cubrió los tres primeros. Faltaba el cuarto. Este estudio lo cierra.

**Hipótesis pre-registrada:** el retest tras ruptura da mejor RR realizado que el
toque y que el CDC, porque confirma la ruptura **sin pagar la entrada tardía
completa**: en vez de entrar en la vela expansiva del quiebre, entra cuando el
precio vuelve al nivel. Mecanismo: si el problema del CDC es el **precio** y no
la **información**, un evento que conserve la información y recupere el precio
debería mejorar.

## Diseño (congelado antes de mirar resultados)

| Item | Valor |
|---|---|
| Universo | **los mismos 8.440 trades** del estudio del abort, pareado 1:1 (test automático lo verifica) |
| Datasets | 7 pares en 1h + 3 en 15m, ~4 años, costos maker-aware, intrabar conservador |
| Ruptura | **cierre** más allá del último swing confirmado (piv=2), con despeje mínimo 0,25·ATR(14) |
| Retest | vuelta al nivel dentro de **N ∈ {4, 8, 12}** velas tras la ruptura |
| Buffer de nivel | **0,25 · ATR(14) causal** — RELATIVO, nunca % fijo |
| Stop / target | **idénticos al plan del toque en TODOS los brazos**: lo único que cambia es la entrada |
| Costo de esperar | si el SL o el TP originales se tocan mientras el brazo espera, el brazo **no opera** (se cuenta) |
| Corte IS/OOS | 2025-06-01 (el mismo del estudio del abort); robustez con 2025-03-19 |
| CI | bootstrap **por bloques** (par × tf × mes), 2.000 iters, seed fija |
| Corrección múltiple | **Holm** sobre las 54 comparaciones pre-registradas |
| Gate de cobertura | ≥500 retests y ≥10% del universo, si no se cierra el estudio |

**Desviación declarada:** el corte IS/OOS es 2025-06-01, no 2025-03-19. Motivo:
es el que produce `IS_FRAC=0.70` sobre este mismo universo y es el que usó el
estudio del abort; con otro corte los brazos previos dejan de ser comparables. Se
reporta igual el corte 2025-03-19 como robustez (`OOS_alt`) y **no cambia nada**.

**Corrección de diseño hecha ANTES de mirar resultados:** la primera versión
definía la ruptura como cualquier cierre más allá del nivel. Con eso, una ruptura
de un tick dejaba el gatillo del retest *por encima* del precio y el "retest" se
llenaba en la vela siguiente sin que el precio volviera a ninguna parte —un
market disfrazado de límite—. Se agregó el despeje mínimo de 0,25·ATR (misma
unidad relativa, sin parámetro nuevo) y el chequeo de que todo gatillo sea una
orden límite válida. Sin esa corrección el brazo se veía artificialmente barato.

## Cobertura del brazo (gate: PASA)

| | n | % |
|---|---|---|
| Setups del universo | 8.440 | 100% |
| — mueren en el SL antes de romper | 4.403 | 52,2% |
| — nunca rompen dentro de la ventana | 1.394 | 16,5% |
| — llegan al target **sin** romper (ganador que el brazo se pierde) | 476 | 5,6% |
| **Rupturas con despeje válidas** | **2.167** | **25,7%** |
| Retest operado, N=4 / N=8 / N=12 | 1.682 / 1.769 / 1.807 | **19,9% / 21,0% / 21,4%** |

De las 2.167 rupturas (N=8): **81,6% retestea**, **7,7% rompe y nunca vuelve**,
**10,7% muere esperando** (SL o TP originales). Cobertura ≥10% y n≥500 en los
tres N: **el estudio sigue**, no se cierra por cobertura.

Dato incómodo del brazo: **52% de los fills tienen RR realizado < 1** (881 de
1.769 en N=8). El plan original exigía RR≥1 al toque; la entrada del retest lo
destruye en la mitad de los casos.

## Tabla principal — universo completo (netR)

| Brazo | n | cobertura | avg/trade | avg/setup | WR% | loser prom. | **RR real** | espera | DD (R) |
|---|---|---|---|---|---|---|---|---|---|
| **base (touch)** | 8.440 | 100% | −0,033 | −0,0327 | 25,5 | −1,149 | **4,25** | 0 | 589 |
| cap03_8 (mejor del abort) | 8.440 | 100% | **−0,004** | −0,0040 | 21,5 | −0,911 | — | 0 | 344 |
| mkt_4 | 8.440 | 100% | −0,012 | −0,0119 | 44,3 | −0,869 | — | 0 | 312 |
| cdc (publicado) | 2.667 | 31,6% | −0,096 | −0,0302 | 52,7 | −1,069 | 1,15 | 7,9 | 272 |
| cdc con despeje | 2.167 | 25,7% | −0,089 | −0,0227 | 55,3 | −1,064 | 1,02 | 8,4 | 212 |
| **rt4 (retest)** | 1.682 | 19,9% | −0,095 | −0,0190 | 49,5 | −1,076 | 1,28 | 9,8 | 171 |
| **rt8** | 1.769 | 21,0% | −0,094 | −0,0197 | 49,2 | −1,076 | 1,30 | 10,1 | 181 |
| **rt12** | 1.807 | 21,4% | −0,103 | −0,0220 | 48,8 | −1,076 | 1,30 | 10,3 | 196 |
| ctrl (a) nivel +0,5 ATR | 496 | 5,9% | −0,036 | −0,0021 | 57,3 | −1,067 | 1,01 | 10,1 | 53 |
| ctrl (a) nivel −0,5 ATR | 1.258 | 14,9% | −0,133 | −0,0199 | 40,1 | −1,090 | 1,79 | 11,3 | 185 |
| ctrl (b) mismo nivel, sin ruptura | 3.868 | 45,8% | −0,073 | −0,0333 | 52,7 | −1,040 | 1,17 | 8,9 | 306 |
| ctrl (c) retraso fijo 10 velas | 3.939 | 46,7% | −0,164 | −0,0767 | 39,2 | −1,185 | 4,15 | 10,0 | 675 |

**Trampa del "avg/setup":** el retest se ve mejor que el toque por setup
(−0,020 vs −0,033) **solo porque no opera el 79% de las veces**. Con expectativa
base negativa, no operar le gana a operar. Estaba pre-registrado que eso no
cuenta como promoción, y de hecho igual pierde contra `cap03_8` (−0,0040).

## Comparación pareada 1:1 (mismos setups, bootstrap por bloques, Holm)

Sobre los **1.769 setups donde el retest N=8 efectivamente operó**:

| Comparación | n | dif. media (R) | IC95% | p Holm | Lectura |
|---|---|---|---|---|---|
| rt8 − **base** | 1.769 | **−1,214** | [−1,34; −1,10] | <0,0001 | catastrófico |
| rt8 − cap03_8 | 1.769 | −1,180 | [−1,31; −1,06] | <0,0001 | catastrófico |
| rt8 − mkt_4 | 1.769 | −0,696 | [−0,78; −0,61] | <0,0001 | catastrófico |
| rt8 − cdc (publicado) | 1.769 | **+0,029** | [+0,020; +0,038] | <0,0001 | mejora real, minúscula |
| rt8 − cdc con despeje | 1.769 | +0,067 | [+0,059; +0,075] | <0,0001 | mejora real, minúscula |
| rt8 − **ctrl (c) retraso** | 1.598 | −0,130 | [−0,19; −0,08] | <0,0001 | pierde contra esperar sin mirar |
| rt8 − ctrl (b) mismo nivel | 1.769 | −0,017 | [−0,022; −0,011] | <0,0001 | la estructura no aporta |
| rt8 − ctrl (a) nivel +0,5 ATR | 354 | +0,123 | [+0,106; +0,142] | <0,0001 | — |
| rt8 − ctrl (a) nivel −0,5 ATR | 1.258 | −0,128 | [−0,142; −0,115] | <0,0001 | — |

En OOS (n=540) el cuadro es idéntico salvo un detalle: **rt8 − ctrl (c) = −0,027,
p=0,42, Holm=1,00** — o sea en OOS el retest ni siquiera se distingue del retraso
fijo sin condición de precio. 51 de las 54 comparaciones sobreviven a Holm; las
3 que no son justamente las del control (c) en OOS.

**Por par, en OOS, pareado:** rt8 pierde contra base en **0 de 7** pares
(BTC −0,63; ETH −1,30; SOL −1,50; XRP −1,56; ADA −0,64; BNB −1,48; DOGE −1,20).
Contra el control (c): gana en 3 de 7. Contra el CDC: gana en 7 de 7, con un
efecto medio de +0,02R.

> Aviso de trampa: la tabla **sin parear** por par sugiere que rt8 le gana a base
> en ETH, XRP, ADA y BNB. Es puro efecto de selección —el retest opera en otro
> subconjunto—. La comparación pareada, que es la válida, da 0/7.

## Los tres controles negativos

**(a) Nivel desplazado ±0,5 ATR.** Ordenamiento pareado: `−0,5 ATR` (entrada más
profunda) **>** nivel real **>** `+0,5 ATR` (entrada más superficial). El
resultado es **monótono en la profundidad del fill**, que es exactamente la firma
de la hipótesis nula: el nivel funciona como coordenada de precio, no como
información. Si el nivel tuviera contenido, el nivel real habría superado a los
dos desplazados; queda interpolado entre ellos.

**(b) Mismo nivel y mismo precio, sin exigir ruptura ni vuelta** (orden stop en el
nivel, refrescada cada vela con el último swing confirmado *antes* de esa vela):
**le gana al retest por +0,017R** con Holm<0,0001, opera más del doble (45,8% vs
21,0%) y tiene mejor cola (−1,040 vs −1,076). La estructura "ruptura confirmada +
vuelta" no agrega nada sobre "poner la orden en el nivel".

**(c) Retraso fijo de 10 velas sin condición de precio** (L = retraso medio
observado del retest): el retest **no lo supera**. En el universo completo el
retest pierde por −0,130R; en OOS empatan (p=0,42). Sobre el subconjunto donde el
retest opera, el retraso ciego rinde **+0,033** contra **−0,094** del retest.
Criterio pre-registrado: *"DESCARTAR si no supera al control (c), porque entonces
el efecto es esperar, no el retest"*. No lo supera.

## El mecanismo se confirma; la conclusión se refuta

Vale la pena separarlo, porque es el hallazgo fino:

- **El mecanismo de la hipótesis es correcto y medible.** El retest sí recupera
  precio respecto del CDC: RR realizado 1,30 vs 1,15, MFE 0,90 vs 0,80, y la
  diferencia pareada es +0,029R, robusta a Holm y positiva en 7/7 pares.
- **Pero la magnitud es irrelevante.** El toque tiene RR realizado 4,25. El CDC
  lo baja a 1,15. El retest lo devuelve a 1,30. Recupera **0,15 de los ~3,1
  puntos de RR** que destruye la confirmación: **el 5%**. La brecha pareada
  contra el toque sigue siendo **−1,21R**.
- Sobre el subconjunto donde el retest opera —que son los mejores setups del
  universo, los que rompen con desplazamiento— el toque simple rinde **+1,12R**
  promedio y el retest **−0,09R**. El brazo destruye un subconjunto ganador.

Traducido: **la información del CDC no es explotable en ninguna forma de
entrada.** Ni entrando en el cierre, ni esperando la vuelta al nivel. Lo único
que capturó algo de esa información fue el abort (entrar al toque y salir barato
si no confirma), y aun eso resultó ser modelador de riesgo, no alpha.

## Perfil de riesgo (¿aplica el criterio "SEGUIR"?)

No. Sobre el mismo subconjunto (n=1.769): DD del toque **13,4R** contra **180,5R**
del retest; loser promedio −1,147 vs −1,076 (mejora marginal e irrelevante al
lado del DD). El retest no es ni mejor expectativa ni mejor riesgo. A diferencia
del abort, acá no queda una faceta que rescatar.

## Robustez

- Corte alternativo 2025-03-19 (`OOS_alt`, n=2.971): base −0,098, rt8 −0,141.
  Mismo signo, misma conclusión.
- Por año, rt8 pierde contra base en **los cinco** (2022 −0,007 vs +0,196; 2023
  −0,015 vs +0,032; 2024 −0,061 vs −0,048; 2025 −0,186 vs −0,110; 2026 −0,164 vs
  −0,149).
- Por TF: 1h base +0,125 vs rt8 −0,007; 15m base −0,111 vs rt8 −0,135.
- En el corte `rr≥5` OOS (el filtro de Fase 1): base −0,065, cap03_8 −0,010,
  rt8 −0,186. El retest es el peor de los tres justo donde el bot mira.
- Los tres N dan lo mismo (−0,095 / −0,094 / −0,103). No hay un N que salve el
  brazo, y no se probó ningún N fuera de los pre-registrados.

## Limitaciones (honestas)

1. **Un solo valor de tolerancia** (0,25·ATR) y uno de desplazamiento (0,5·ATR).
   Se pre-registró así a propósito para no barrer parámetros; no se descarta que
   otra tolerancia mueva el margen, pero tendría que mover **1,2R**, no 0,03R.
2. El netR de cada brazo se mide en R **de su propio riesgo**; como el retest
   entra más lejos del stop, su R es más grande en términos absolutos. Es la
   misma convención de los estudios previos, y no favorece a ninguna dirección
   del veredicto porque el brazo pierde también en RR realizado, WR y DD.
3. La definición de ruptura usa swings piv=2 (micro-estructura). Con swings más
   grandes el evento sería más raro y probablemente no pasaría el gate de
   cobertura.
4. El control (b) usa el nivel refrescado vela a vela; no es literalmente "el
   mismo nivel de la ruptura" en el 100% de los casos, pero sí el mismo precio de
   fill y el mismo criterio causal.
5. Klines versionados en el repo, ~41 días de antigüedad. Es lo esperado: es un
   dataset, no un feed.

## VEREDICTO: **DESCARTAR**

El brazo ruptura+retest **no se promueve y no se sigue investigando**. Cumple los
tres criterios de descarte pre-registrados:

1. **No supera al mejor brazo actual en OOS**: pierde −1,11R pareado contra
   `cap03_8` y −1,14R contra el toque.
2. **Gana en 0 de 7 pares en OOS** (el criterio pedía ≥5 de 7).
3. **No supera al control (c)**: en OOS es indistinguible del retraso fijo sin
   condición de precio (p=0,42, Holm=1,00). El efecto es esperar, no el retest.

Y los otros dos controles cierran la puerta: el nivel desplazado muestra que el
efecto es puro precio de fill, y el control del mismo nivel sin ruptura le gana al
retest operando el doble.

**Consecuencia para el gate del curso:** con este brazo medido, los cuatro brazos
del evento de entrada están cubiertos y **ninguno rescata la exigencia de
confirmación**. La confirmación contiene información (eso sigue siendo cierto y
está medido), pero no existe forma de entrada que la convierta en expectativa.
El gate de "dos cierres consecutivos" sigue sin sustento en estos datos.

## Qué no se tocó

Bot, dry-run Fase 1, `config/`, `core/`, `modules/`, credenciales, VPS. `data/`
se leyó y no se escribió. Todo corrió local. Sin commits ni push.
