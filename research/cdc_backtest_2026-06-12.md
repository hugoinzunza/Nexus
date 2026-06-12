# ¿Qué aporta el CDC (Cambio De Carácter / CHoCH) a las entradas SMC?

**Backtest de investigación — 2026-06-12**
Indicador de referencia: *Bitcoin Traders Academy* (Ing. Carlos García), el mismo SMC POI multi-TF ya replicado en el repo.
Motor, datos Binance y lógica POI reutilizados de `modules/trading` (`strategies.py` / `smc` / `engine`).

---

## Veredicto en una línea

> El **CDC en contexto** (esperar el cambio de carácter tras tocar el POI correcto) **sí aporta en 1h**: da vuelta el out-of-sample de perdedor claro a probablemente rentable, subiendo el winrate de 36% a 45% — pero el edge es **modesto y no concluyente**. En **15m no rescata** (sigue negativo). Y el CDC **mecánico** (exigirlo en la misma vela del toque, lo de anoche) **solo recorta la muestra**: confirmado, colapsa a 4–16 trades.

---

## 1. Qué se probó

Tres variantes corridas sobre **el mismo universo de POIs** (correspondencia 1:1 de setups, para aislar el efecto del CDC):

| Var | Regla de entrada |
|-----|------------------|
| **A** | **POI solo.** Entra al toque del POI (en descuento/premium, lado correcto). |
| **B0** | **POI + CDC mecánico.** Exige que el cierre rompa el último swing **en la misma vela del toque** → *esto es lo de anoche*. |
| **B** | **POI + CDC en contexto.** Toca el POI, **espera** a que aparezca el CDC (cierre que rompe el último swing relevante) dentro de una ventana de 16 velas, y recién ahí entra. |

En las tres el SL es el mismo (bajo el POI/barrido) y el objetivo es R:R fijo = 2. La única diferencia entre A y B es **el gate del CDC y el timing de entrada**. Así, todo delta es atribuible al CDC, no a otro cambio.

### Metodología (innegociable)
- **Anti-repaint estricto:** POIs de TFs superiores solo cuando la vela está **cerrada** (`t_conf`); el CDC se detecta **solo con cierres hasta la vela actual**; los swings usan `confirm_idx` (un pivote se conoce recién `lookback` velas después). Señal al cierre → **entrada en la apertura de la vela siguiente**. Cero look-ahead.
- **Costos:** 0.05%/lado + 0.02% slippage por fill. Se reporta **con y sin costos**.
- **Datos:** 7 pares (BTC, ETH, SOL, BNB, XRP, ADA, DOGE), **~4 años** (2022-06 → 2026-06), TFs de entrada **15m y 1h**, POIs detectados en 1h/4h/1d.
- **Split temporal 70/30** por par/TF + **walk-forward** de 5 ventanas cronológicas.
- POIs detectados con la misma `detect_pois` del repo (FVG + displacement≥1·ATR + order block + barrido de weak low/high + filtro premium/discount sobre el EQ 50% del dealing range).

---

## 2. Resultado agregado — A vs B0 vs B (RR fijo = 2, 7 pares)

### TF 1h

| | n (IS) | exp IS | n (OOS) | **exp OOS** | **PF OOS** | wr OOS |
|---|---|---|---|---|---|---|
| **Con costos** | | | | | | |
| A — POI solo | 1615 | −0.024R | 815 | **−0.096R** | 0.87 | 36.1% |
| B0 — CDC mecánico | 10 | +0.612R | **4** | (sin muestra) | — | — |
| **B — CDC en contexto** | 622 | −0.05R | **287** | **+0.066R** | **1.13** | **45.3%** |
| **Sin costos** | | | | | | |
| A | 1615 | +0.088R | 815 | +0.036R | 1.06 | 36.1% |
| B | 622 | −0.004R | 287 | +0.114R | 1.24 | 45.3% |

**Delta B − A (OOS, con costos):** expectativa **+0.162R**, PF **+0.26**, winrate **+9.2 pts**, reteniendo **35%** de la muestra (287 de 815). No es el colapso de anoche.

### TF 15m

| | n (IS) | exp IS | n (OOS) | **exp OOS** | **PF OOS** | wr OOS |
|---|---|---|---|---|---|---|
| **Con costos** | | | | | | |
| A — POI solo | 1969 | −0.022R | 967 | −0.099R | 0.85 | 39.7% |
| B0 — CDC mecánico | 16 | +0.013R | **4** | (sin muestra) | — | — |
| **B — CDC en contexto** | 823 | −0.056R | 378 | **−0.055R** | 0.89 | 41.5% |
| **Sin costos** | | | | | | |
| A | 1969 | +0.101R | 967 | +0.041R | 1.07 | 40.4% |
| B | 823 | +0.011R | 378 | +0.023R | 1.05 | 44.7% |

**Delta B − A (OOS, con costos):** expectativa **+0.044R**, winrate **+1.8 pts** — mejora, pero **ambos quedan negativos** con costos. El CDC no alcanza para hacer rentable el scalp 15m.

---

## 3. Desglose por par — OOS, con costos (A vs B, RR=2)

### TF 1h — B mejora a A en **5 de 7** pares

| Par | A (n / wr / exp / PF) | B (n / wr / exp / PF) |
|-----|----------------------|----------------------|
| BTC | 105 / 42.9% / +0.021 / 1.03 | 38 / 47.4% / −0.019 / 0.96 |
| ETH | 104 / 37.5% / −0.026 / 0.96 | 40 / 55.0% / **+0.475 / 2.28** |
| SOL | 113 / 34.5% / −0.110 / 0.85 | 38 / 42.1% / +0.099 / 1.18 |
| BNB | 149 / 37.6% / −0.085 / 0.88 | 52 / 42.3% / −0.020 / 0.97 |
| XRP | 117 / 36.8% / −0.082 / 0.88 | 42 / 54.8% / **+0.265 / 1.60** |
| ADA | 118 / 29.7% / −0.248 / 0.68 | 39 / 43.6% / −0.085 / 0.84 |
| DOGE | 109 / 33.9% / −0.124 / 0.82 | 38 / 31.6% / −0.259 / 0.56 |

El positivo agregado lo cargan **ETH y XRP**; BTC y DOGE no mejoran. No es un edge parejo entre pares.

### TF 15m — irregular, sin patrón ganador

| Par | A (exp / PF) | B (exp / PF) |
|-----|-------------|-------------|
| BTC | −0.129 / 0.82 | −0.076 / 0.85 |
| ETH | +0.065 / 1.11 | −0.029 / 0.94 |
| SOL | −0.140 / 0.79 | **+0.133 / 1.32** |
| BNB | −0.174 / 0.76 | −0.176 / 0.71 |
| XRP | +0.011 / 1.02 | −0.149 / 0.72 |
| ADA | −0.159 / 0.76 | +0.044 / 1.09 |
| DOGE | −0.140 / 0.79 | −0.083 / 0.83 |

---

## 4. Walk-forward (5 ventanas cronológicas, con costos, agregado) — `exp_R [n]`

**TF 1h:**
| | V1 | V2 | V3 | V4 | V5 (reciente) |
|---|---|---|---|---|---|
| A | +0.051 [496] | −0.009 [397] | −0.137 [480] | −0.005 [509] | −0.127 [547] |
| **B** | −0.170 [189] | −0.003 [151] | −0.049 [185] | **+0.048 [194]** | **+0.108 [190]** |

Dato honesto clave: el positivo de B en 1h **se concentra en los dos tramos más recientes**, justo donde A se desangra (−0.005, −0.127). B **aguanta el régimen reciente** que rompe a A. Pero el primer tramo de B es claramente negativo → **no** es un edge de todo clima.

**TF 15m:**
| | V1 | V2 | V3 | V4 | V5 |
|---|---|---|---|---|---|
| A | +0.002 [588] | −0.079 [505] | −0.060 [572] | +0.008 [628] | −0.109 [643] |
| B | −0.024 [250] | −0.004 [200] | −0.136 [241] | −0.049 [261] | −0.057 [249] |

En 15m, B es negativo en 4 de 5 ventanas. No hay rescate.

---

## 5. Confianza estadística (bootstrap, 2000 remuestreos, OOS con costos)

| Celda | n | exp | IC 90% | **P(exp > 0)** |
|-------|---|-----|--------|----------------|
| 1h — A | 815 | −0.096R | [−0.173, −0.016] | **0.02** (negativo casi seguro) |
| **1h — B** | 287 | +0.066R | [−0.059, +0.183] | **0.81** (probable, no concluyente) |
| 15m — A | 967 | −0.099R | [−0.168, −0.031] | 0.01 |
| 15m — B | 378 | −0.055R | [−0.148, +0.040] | 0.17 |

El CDC en contexto **gira el 1h de P=0.02 a P=0.81**. Es una señal genuina, pero el IC todavía incluye el 0: **probable, no demostrado**. (Como referencia, el filtro VIX<25+ADX>25 del estudio de anoche llegó a P=0.97; el CDC no llega a ese nivel.)

---

## 6. Robustez: TP = "siguiente liquidez opuesta sin barrer" (RR≥2)

Probé también el objetivo fiel del profe (apuntar a la liquidez opuesta sin barrer, exigiendo RR≥2) en vez de RR fijo:

| | A OOS (con costos) | B OOS |
|---|---|---|
| 1h | n=383 / +0.371R / PF 1.44 | n=**4** (sin muestra) |
| 15m | n=266 / +0.036R / PF 1.04 | n=**3** (sin muestra) |

Hallazgo lateral interesante: **el objetivo de liquidez por sí solo mejora a A** (1h A OOS +0.371R, PF 1.44) — apuntar a liquidez real rinde más que un RR fijo de 2. **Pero** exigir *además* el CDC deja a B con 3–4 trades: la combinación liquidez+CDC es demasiado restrictiva para concluir. Por eso la comparación válida del CDC es la de RR fijo (sección 2). El TP de liquidez queda como **línea de investigación aparte**, prometedora pero a verificar.

---

## 7. Veredicto honesto

1. **El CDC mecánico (B0) es solo recorte de muestra.** Exigir el cambio de carácter en la *misma vela* del toque colapsa a 4–16 trades — sin valor estadístico. Queda confirmado lo de anoche: **no se debe exigir así**.
2. **El CDC en contexto (B) NO es solo recortar muestra.** Retiene 35–40% de los setups (287–378 trades OOS) y produce un cambio medible en el comportamiento: más winrate, mejor PF.
3. **En 1h, el CDC aporta de verdad** — gira el OOS de −0.096R (P(>0)=0.02) a +0.066R (P=0.81), winrate 36%→45%, mejora en 5/7 pares, y sobre todo **resiste el régimen reciente** donde el POI crudo se rompe. Pero el edge es **modesto y no concluyente** (IC incluye 0; lo cargan ETH/XRP).
4. **En 15m el CDC no rescata.** Mejora marginal de winrate, pero ambos siguen negativos con costos y el walk-forward es mayormente rojo. El scalp 15m con esta lógica no tiene edge.
5. **Los costos deciden.** Sin costos el POI crudo (A) ya es levemente positivo; con costos se vuelve negativo. Parte de lo que "aporta" el CDC es **operar menos y mejor** (menos sangría por comisión).
6. **El POI crudo, sin filtros, es perdedor con costos.** El edge real del setup vino de los filtros del estudio previo (VIX<25 + ADX>25, P=0.97). El CDC es **otra capa de permiso** que ayuda especialmente en 1h, pero por sí sola no es tan fuerte como ese filtro de régimen.

**Recomendación de uso:** usar el CDC como confirmación **en 1h**, en el POI correcto del lado correcto (tal como lo enseña el profe), idealmente **combinado** con el filtro de régimen ya validado — no como regla aislada ni en 15m. Confirma la intuición discrecional: el CDC es contexto, no gatillo mecánico.

---

## Resumen ejecutivo (para Hugo)

El profe tiene razón en *cómo* lo usa: el CDC sirve como **confirmación en el POI correcto**, no como regla ciega. Lo medimos honestamente sobre 4 años y 7 pares, separando in-sample de out-of-sample y con costos reales.

- **Exigir el CDC "a la mecánica" (en la misma vela del toque) no sirve**: deja ~4 trades, justo el colapso que viste anoche. Eso queda descartado.
- **Esperar el CDC en contexto sí cambia las cosas, pero solo en 1h**: la entrada pasa de perder plata (−0.10R por trade out-of-sample, con costos) a ganar un poquito (+0.07R, profit factor 1.13), y el winrate sube de 36% a 45%. Y lo más rescatable: **aguanta los últimos meses**, donde el POI sin filtro se cae.
- **En 15m no ayuda**: sigue en rojo. No lo uses para scalp con esta lógica.
- **El aporte es real pero chico** (81% de probabilidad de ser positivo, no es certeza), y lo cargan sobre todo ETH y XRP. No es magia.

En corto: **el CDC en 1h es una buena capa de confirmación, mejor todavía si la sumas al filtro de régimen (VIX<25 + ADX>25) que ya validamos**. Como gatillo aislado o en 15m, no. La honestidad manda: ayuda, pero no convierte el POI crudo en una máquina — es un ladrillo más, no la pared.

---

*Reproducible:* `research/cdc_backtest.py` → `research/cdc_results.json`. Parámetros: PIV=2, displacement=1·ATR, ventana CDC=16 velas, POI máx 30 días, RR=2, split 70/30. Sin tuneo sobre OOS.
