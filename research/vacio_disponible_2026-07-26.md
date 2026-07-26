# Vacío disponible: ¿el TP del bot atraviesa paredes?

**Fecha:** 2026-07-26 · `research_only` · `execution_enabled: false` · `validated: false`
**Artefactos:** `research/vacio_disponible.py` · `research/vacio_disponible_results.json` ·
`research/vacio_disponible_trades.json` (caché por-trade, 9 MB, regenerable) ·
`research/test_vacio_disponible.py`

> **VEREDICTO: DESCARTAR** como columna del Diario o como filtro.
> El conteo de obstáculos **no** predice peor realización una vez controlado el RR.
> El control negativo (b) sale plano (no hay fuga), así que el resultado negativo es
> creíble, no un artefacto.
>
> **Pero hay un hallazgo descriptivo que sí queda en pie y no es lo mismo que la
> hipótesis:** el `rr` que el gate `rr>=5` filtra **no** mide la distancia al primer
> referente. Mediana de `rr` planificado **11,6** contra mediana de `vacuum_rr` (a la
> primera pared) **1,52**; correlación de rangos entre ambos **0,24**. El 90,4 % de los
> TP están detrás de **dos o más** referentes. El gate es internamente incoherente con
> lo que dice medir. Lo que este estudio agrega es que **corregirlo no mejora nada**.

---

## 1. Qué se midió

El punto de partida (ya verificado antes de este estudio, no se re-verificó acá):
`modules/trading/smc_live.py:525`, `_opposite_liquidity()` pone el TP en
`min(weak highs > ref)` para largos — la liquidez **weak** (sin barrer) más cercana.
Ese cálculo no mira si en el camino hay niveles **strong**, POIs de otras
temporalidades, o liquidez del lado contrario. `strong_high`/`strong_low` (`rhi`/`rlo`)
entran sólo como **respaldo** cuando no hay weak, nunca como obstrucción intermedia.
No existe en el repo ninguna variable de conteo de obstáculos.

La clase 7 de CreceTrader (`research/crecetrader/07_vacio_disponible.md`) llama **vacío
disponible** a la distancia entrada → primer referente capaz de obstaculizar, y advierte
que "un RR alto construido con un target posterior a varios obstáculos puede ser
matemáticamente correcto pero operativamente ilusorio".

### Hipótesis pre-registrada

`obstacle_count_before_target > 0` predice **menor** realización del objetivo,
controlando por RR planificado, par, dirección y régimen.

### Definición de obstáculo (congelada antes de ver resultados)

Nivel **Weak** o **Strong** (ambos), o **POI** de cualquier `POI_TFS` (1D/4h/1h),
confirmado en el `as_of` del plan, cuyo precio cae **estrictamente** entre `entry` y
`tp` en la dirección del trade. Para una zona se usa el **borde cercano** (`lo` si el
recorrido va hacia arriba, `hi` si va hacia abajo), no el centro — la clase 7 lo pide
explícito y además es lo conservador.

Cuatro definiciones anidadas, las cuatro pre-declaradas y las cuatro dentro de la
familia de Holm:

| definición | qué cuenta |
|---|---|
| `obst_all` | la literal del pre-registro: niveles + **todos** los POIs (mitigados incluidos) |
| `obst_valid` | niveles + POIs **válidos** (sin mitigar, sin invalidar) |
| `obst_levels` | sólo niveles Weak/Strong |
| `obst_htf` | niveles + POIs válidos de **1D/4h** |

### Universo

Trades **activados** del pipeline alineado del bot (`smc_live.analyze`: POIs 1D/4h/1h
proyectados sobre TF de planeación 1h/4h), `rr>=5`, **sin 15m** (el bot no opera 15m).

**n = 5.289 trades activados en 1.221 días, 2022-04-30 .. 2026-06-14, 7 pares.**

El colector re-corre el pipeline instrumentando `smc_live._pois_for_tf` en runtime (no
se modificó ningún archivo de `modules/`). **Reproduce el volcado oficial exactamente**:
11.815 planes, mismas claves `(par, tf, t, dir, rr)`, mismo reparto de estados
(1.116 ganadas / 5.147 perdidas / 5.351 anuladas / 201 abiertas). Es decir: lo que se
midió es el universo del bot, no un universo parecido.

---

## 2. Lo que sí es cierto: el gate `rr>=5` no mide el vacío disponible

Descriptivo, sin contraste — **no** entra en la familia de Holm.

| medida | valor |
|---|---|
| `rr` planificado, mediana | **11,6** |
| `vacuum_rr` (a la primera pared), mediana | **1,52** |
| correlación de rangos `rr` ↔ `vacuum_rr` | **0,24** |
| planes con ≥1 pared entre entry y TP | **97,9 %** |
| planes con ≥2 paredes | **90,4 %** |
| distancia al TP, mediana | **9,69 %** del precio |
| primera pared antes de 1R | 36,0 % |
| primera pared antes de 2R | 58,4 % |

Composición de la **primera** pared (n=5.176): POI 3.320 · Strong 1.741 · Weak 115.
Por temporalidad: TF de planeación 1.856 · 1h 1.777 · 4h 1.114 · 1D 429.

Léase así: el TP es por construcción la liquidez weak más cercana, y sin embargo en
5.176 de 5.289 casos hay algo antes — casi siempre un **POI** o un nivel **Strong**,
que son exactamente las dos cosas que `_opposite_liquidity()` no mira. Y el `rr` que
el gate filtra ordena los trades de manera casi distinta al vacío disponible (ρ=0,24).

**Eso es un problema de coherencia interna del gate, y está medido.** Lo que sigue es
si arreglarlo sirve para algo.

---

## 3. Lo que no es cierto: el conteo no predice

### 3.1 Tabla por celda (obstáculos entre entry y TP)

`netR` = R neto con el modelo maker-aware del Diario (`_cost_fraction`/`sl_pct`).
`vivo` = netR con la gestión que corre en vivo (TP1 1R/50 %, TP2 2R/25 %, runner con
trailing 1R). `TP1` / `TP` = tasa de llegada.

**`obst_valid`** (las cuatro celdas por encima del mínimo de 300):

| celda | n | netR medio | netR mediano | vivo | TP1 | TP | MFE | MAE | rr mediano |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 633 | +0,731 | −1,122 | +0,459 | 64,3 % | 18,6 % | 4,35 | 2,35 | 8,6 |
| 1 | 1.546 | +0,740 | −1,106 | +0,519 | 66,8 % | 17,9 % | 4,58 | 2,25 | 10,0 |
| 2 | 1.689 | +0,625 | −1,097 | +0,473 | 65,9 % | 15,4 % | 4,58 | 2,20 | 11,9 |
| 3+ | 1.421 | +0,327 | −1,094 | +0,533 | 68,6 % | 11,3 % | 4,47 | 2,45 | 16,0 |

**`obst_all`** (la definición literal del pre-registro):

| celda | n | netR medio | vivo | TP1 | TP | rr mediano |
|---|---|---|---|---|---|---|
| 0 | **113** | +0,807 | +0,378 | 59,3 % | 20,4 % | 8,0 |
| 1 | 393 | +0,566 | +0,445 | 65,6 % | 19,8 % | 8,1 |
| 2 | 648 | +0,639 | +0,544 | 68,2 % | 19,4 % | 8,5 |
| 3+ | 4.135 | +0,580 | +0,503 | 66,8 % | 14,2 % | 12,7 |

**La celda 0 de `obst_all` tiene n=113 < 300: por el propio pre-registro NO se
interpreta.** Con la definición literal (que cuenta POIs ya mitigados) prácticamente
todo plan tiene al menos una pared. Las otras tres definiciones tienen las cuatro
celdas pobladas y coinciden entre sí.

Nótese la mediana de `netR`: **−1,1 en todas las celdas**. La expectativa positiva la
sostienen unos pocos runners, no la mayoría de los trades. No hay gradiente en MFE ni
en MAE.

### 3.2 Contrastes con CI por bloques diarios

Diferencia (con obstáculos) − (sin obstáculos), 2.000 remuestreos de **días** (no de
trades: 1.221 días para 5.289 trades; remuestrear trades sueltos fingiría independencia
y estrecharía el CI hasta mentir).

| contraste | crudo (CI95) | estratificado por RR×dirección (CI95) |
|---|---|---|
| `obst_valid` → netR vivo | +0,048 (−0,069 … +0,174) | +0,050 (−0,081 … +0,184) |
| `obst_valid` → TP1 | +0,027 (−0,014 … +0,071) | +0,041 (−0,006 … +0,088) |
| `obst_valid` → TP | **−0,037 (−0,074 … −0,003)** | −0,011 (−0,043 … +0,022) |
| `obst_levels` → TP | **−0,032 (−0,063 … −0,001)** | −0,009 (−0,038 … +0,019) |
| `obst_htf` → TP | **−0,043 (−0,078 … −0,009)** | −0,017 (−0,049 … +0,015) |
| `obst_all` → netR vivo | +0,126 (−0,149 … +0,404) | +0,217 (−0,250 … +0,563) |
| `obst_all` → TP1 | +0,076 (−0,017 … +0,172) | +0,138 (−0,007 … +0,238) |

Los tres únicos efectos crudos cuyo CI excluye el cero son sobre **llegar al TP lejano**,
en la dirección de la hipótesis… **y los tres se mueren al estratificar por RR**
(p pasa de 0,036 / 0,035 / 0,007 a 0,575 / 0,534 / 0,292). No es un descubrimiento: más
paredes significa recorrido más largo significa `rr` más alto significa menos
probabilidad de llegar a un objetivo lejano. Lo estaba haciendo el RR, no las paredes.

Para netR y para TP1 el signo es **positivo**, o sea el contrario al de la hipótesis.

### 3.3 Holm sobre la familia pre-declarada (4 definiciones × 3 desenlaces)

**Ninguno de los 12 contrastes sobrevive.** El mejor p crudo es 0,038
(`obst_levels|reach_tp1`, y con signo **positivo**, contrario a la hipótesis) y su
p-Holm es 0,456. Esto era exactamente lo esperable después de lo de fuerza relativa,
donde 5 de 81 variantes se veían significativas sin corregir y ninguna sobrevivió.

### 3.4 Regresión: ¿aporta por encima de lo que el RR ya dice?

MCO con CI por bloques diarios; covariables: `log_rr`, dirección, `log(ATR/precio)`,
retorno de 200 barras, TF de planeación, TF del POI y dummies de par.

| desenlace | coeficiente | valor (CI95) |
|---|---|---|
| netR vivo | `obst_flag` (all) | +0,141 (−0,138 … +0,447) |
| netR vivo | `obst_n` (all) | −0,004 (−0,032 … +0,023) |
| netR vivo | `log_vacuum_rr` | −0,022 (−0,054 … +0,013) |
| TP1 | `obst_flag` (valid) | −0,014 (−0,061 … +0,035) |
| TP1 | `log_vacuum_rr` | **−0,013 (−0,024 … −0,001)** |
| TP | `obst_n` (all) | **−0,008 (−0,015 … −0,0004)** |

Sólo dos coeficientes quedan nominalmente fuera de cero, ambos diminutos y **sin
corrección por multiplicidad** (no estaban en la familia pre-declarada): cada pared
adicional baja 0,8 puntos porcentuales la probabilidad de llegar al TP lejano, sobre
una base del 15 %. Con la mediana de 3+ paredes son ~2,4 pp. No es una señal, es ruido
con signo.

En cambio `log_rr` es el que manda en los tres desenlaces — en el modelo baseline
(sólo covariables, sin obstáculos): netR vivo −0,092 (−0,166 … −0,014), TP1 −0,073
(−0,100 … −0,046), TP −0,125 (−0,143 … −0,108), CI fuera de cero en los tres.
**Dentro del universo `rr>=5`, más RR planificado predice PEOR resultado.** Ver §6.

---

## 4. Los tres controles negativos

### (b) Obstáculos **detrás del entry** — el que podía invalidar todo

Mismo conteo en la banda espejo (misma distancia, dirección contraria, con el borde de
choque recalculado para esa dirección y excluyendo la zona que contiene la entrada —
sin esa exclusión el control quedaba con flag=1 en el 100 % de los trades y no
controlaba nada).

| desenlace | crudo (CI95) | estratificado (CI95) | p |
|---|---|---|---|
| netR vivo | −0,031 (−0,158 … +0,102) | −0,030 (−0,166 … +0,108) | 0,673 |
| TP1 | +0,000 (−0,046 … +0,046) | +0,010 (−0,037 … +0,059) | 0,664 |
| TP | −0,011 (−0,047 … +0,027) | +0,003 (−0,035 … +0,039) | 0,841 |

**PLANO.** No hay fuga. El estudio es válido y su resultado negativo se puede creer.
Verificado además que el conteo espejo tiene variación real (606 trades en celda 0) y
que no es una copia del conteo hacia adelante — hay un test para ambas cosas.

### (c) Conteo **permutado dentro de deciles de distancia** — el que refuta

Los conteos se barajaron entre trades del mismo decil de `|tp−entry|/ATR`: el conteo
permutado conserva toda la información de distancia y pierde la del trade.

| desenlace | estratificado (CI95) | p |
|---|---|---|
| netR vivo | +0,296 (−0,060 … +0,576) | 0,109 |
| TP1 | **+0,146 (+0,022 … +0,244)** | **0,019** |
| TP | +0,004 (−0,070 … +0,073) | 0,814 |

**Un conteo aleatorio predice TP1 igual o mejor que el real** (+0,146 contra +0,138 del
conteo verdadero). Es la evidencia más limpia del informe: lo poco que se veía era la
distancia, no las paredes. Si el conteo verdadero llevara información propia, tendría
que superar a su versión barajada, y no lo hace.

### (a) Placebo ±0,3 ATR — **poco informativo por construcción, y hay que decirlo**

| desenlace | estratificado (CI95) | p |
|---|---|---|
| netR vivo | +0,394 (+0,009 … +0,755) | 0,045 |
| TP1 | +0,180 (+0,048 … +0,316) | 0,010 |
| TP | +0,035 (−0,049 … +0,100) | 0,421 |

El placebo "predice", pero eso **no es evidencia de nada**: la banda entry→TP mide
varios ATR, así que desplazar las paredes ±0,3 ATR casi no cambia su pertenencia a la
banda (celda 0: 77 trades en el placebo contra 113 en el real). El placebo es
prácticamente la misma variable. Su único aporte real es señalar que la celda de
referencia de `obst_all` (n≈100) es tan chica que la diferencia contra ella es
inestable — que es justo por lo que el pre-registro exigía 300 por celda.

Este control quedó mal diseñado y lo digo acá en vez de esconderlo: para discriminar
placement habría que desplazar en múltiplos del **ancho de la banda**, no del ATR.

---

## 5. Estabilidad temporal

Diferencia netR (con obstáculos − sin obstáculos), por año:

| año | n | n sin obst. | netR con | netR sin | dif | TP1 con | TP1 sin |
|---|---|---|---|---|---|---|---|
| 2022 | 707 | 20 | +0,722 | +0,270 | +0,452 | 74,7 % | 65,0 % |
| 2023 | 1.169 | 29 | +0,435 | +0,542 | −0,107 | 64,9 % | 62,1 % |
| 2024 | 1.323 | 33 | +0,543 | +0,111 | +0,433 | 68,6 % | 51,5 % |
| 2025 | 1.430 | 26 | +0,503 | +0,373 | +0,130 | 65,9 % | 53,8 % |
| 2026 | 660 | 5 | +0,316 | +1,642 | −1,326 | 60,8 % | 100,0 % |

Sólo **2 de 5** años apuntan en la dirección de la hipótesis, y el grupo de referencia
tiene entre 5 y 33 trades por año: esta tabla es ruido y se reporta por completitud,
no como evidencia. El criterio pre-registrado pedía ≥3 de 5.

IS/OOS (corte 2025-03-19): IS con obst. n=3.430 netR +0,495 vs sin obst. n=91 +0,695;
OOS con obst. n=1.746 +0,765 vs sin obst. n=22 +1,269. Los grupos de referencia son
demasiado chicos para leer nada.

---

## 6. Dos cosas que aparecieron de lado (descriptivas, NO probadas acá)

**a) El `vacuum_rr` discrimina PEOR que el `rr` planificado** — al revés de la
hipótesis 1 de la clase 7.

| quintil | por `rr`: TP1 / TP / netR vivo | por `vacuum_rr`: TP1 / TP / netR vivo |
|---|---|---|
| Q1 | 71,7 % / 25,0 % / +0,540 | 69,5 % / 15,2 % / +0,537 |
| Q2 | 72,5 % / 21,1 % / +0,550 | 69,6 % / 16,2 % / +0,527 |
| Q3 | 68,1 % / 15,5 % / +0,529 | 64,3 % / 16,3 % / +0,403 |
| Q4 | 63,8 % / 11,0 % / +0,470 | 68,4 % / 15,9 % / +0,570 |
| Q5 | 57,6 % / 4,8 % / +0,416 | 62,7 % / 12,9 % / +0,480 |

El `rr` ordena monótonamente; el `vacuum_rr` es plano y no monótono.

**b) Dentro de `rr>=5`, más RR predice peor resultado.** El quintil superior (rr≥21,2)
rinde netR +0,142 y llega al TP lejano 4,8 % de las veces, contra +0,815 y 21,1 % del
Q2. El coeficiente `log_rr` es negativo con CI fuera de cero en los tres desenlaces.
Esto **no** se probó acá (no estaba pre-registrado, no tiene controles negativos, no
pasó por Holm) y **no se debe actuar sobre esto desde este informe**. Merece un estudio
pre-registrado propio sobre un **techo** de RR, no un piso.

---

## 7. Limitaciones y datos que faltan

1. **La celda 0 de `obst_all` (n=113) queda bajo el mínimo de 300** y no se interpreta.
   Con la definición literal del pre-registro casi todo plan tiene una pared, así que
   el contraste binario de esa definición es frágil. Las otras tres definiciones sí
   tienen las cuatro celdas pobladas y dan lo mismo.
2. **El control (a) quedó mal diseñado** (§4): ±0,3 ATR sobre una banda de varios ATR
   no mueve la pertenencia. No invalida nada, pero no aporta.
3. **Modelo lineal de probabilidad** para `reach_tp1` / `reach_tp`, no logit. El
   coeficiente se lee como diferencia de probabilidad, que es lo que interesa, pero no
   respeta el rango [0,1] en los extremos.
4. **p bootstrap con piso 1/B**: con B=2.000 un p de 0,0005 significa "≤ el piso", no
   un valor exacto.
5. **Régimen** entra como covariables continuas (ATR/precio y retorno de 200 barras),
   no como clasificación de régimen del proyecto. Ambas son causales (sólo pasado).
6. **No hay datos de libro ni de liquidaciones.** Las "paredes" son estructura de
   precio (pivotes y POIs). Un obstáculo real puede ser un clúster de liquidaciones que
   no coincide con ningún pivote. La versión con niveles reales sólo se podrá validar
   hacia adelante, cuando el colector acumule (mismo límite que anotó
   `tp_magnet_study`).
7. **La barra de activación no se cuenta** (`act_idx + 1`): con OHLC no se sabe el
   orden intrabarra y contarla regalaba TP1 — el bug de 2026-07-25 que costaba 1,5R.
   Eso hace que las tasas de TP1 de acá sean conservadoras y comparables entre celdas,
   pero no directamente comparables con números viejos que sí la contaban.
8. **Los klines del repo son un dataset versionado, no un feed**: terminan el
   2026-06-14, ~41 días antes de hoy. Es lo esperado.

### Alcance: esto NO explica la brecha backtest vs Diario

El backtest da 67,4 % de llegada a TP1 y el Diario real 33,3 % (CI95 21,3 %–50,0 %).
Este estudio **no** explica esa diferencia y no pretendía hacerlo: backtest y Diario
usan el **mismo** `_tpsl`, y una ceguera **compartida** no puede producir divergencia
entre dos sistemas que la comparten. Lo que este estudio ponía en duda era la
coherencia interna del gate `rr>=5`, y esa duda queda **confirmada como descripción**
(§2) y **descartada como señal** (§3).

---

## 8. VEREDICTO

**DESCARTAR.** Criterio pre-registrado, aplicado tal cual:

- ¿Sobrevive Holm? **No** — 0 de 12 contrastes (mejor p-Holm: 0,456).
- ¿El control (b) sale plano? **Sí** — no hay fuga, el resultado negativo es creíble.
- ¿El efecto desaparece al controlar por RR? **Sí** — los tres contrastes crudos con CI
  fuera de cero (`obst_valid|TP`, `obst_levels|TP`, `obst_htf|TP`) se mueren al
  estratificar. Esa es literalmente la condición de DESCARTAR del pre-registro.
- ¿Dirección repetida en ≥3 de 5 años? **No** — 2 de 5, y con celdas de 5 a 33 trades.
- Además: el conteo **permutado al azar** predice TP1 tan bien como el real (control c).

**No agregar una columna de obstáculos al Diario. No tocar el gate `rr>=5` desde este
informe. No hay cambio de código que se derive de acá.**

Lo que sí queda escrito, y es un entregable en sí mismo: el `rr` del bot **no** es el
vacío disponible (ρ=0,24; mediana 11,6 vs 1,52; 90,4 % de los TP detrás de ≥2
referentes). Es una incoherencia real entre lo que el gate dice medir y lo que mide.
Medirla bien y comprobar que **no** mejora la predicción es el resultado: la ceguera
existe, y arreglarla no paga.

---

## 9. Cómo reproducir

```bash
.venv/bin/python3 research/vacio_disponible.py --recolectar   # ~20 min, re-corre el pipeline
.venv/bin/python3 research/vacio_disponible.py                # sólo el análisis, desde el caché
.venv/bin/python3 -m pytest research/test_vacio_disponible.py -q
```

`research/vacio_disponible_trades.json` (9 MB) es caché regenerable; conviene
gitignorearlo como ya se hizo con `relative_strength_oos_trades.json`.
