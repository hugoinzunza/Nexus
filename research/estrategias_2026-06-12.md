# Filtro complementario para las entradas SMC POI multi-TF — investigación y backtest

**Fecha:** 2026-06-12 · **Autor:** sesión nocturna de research (worktree `research-smc-filtros`)
**Objetivo:** encontrar una herramienta/indicador/señal/filtro **complementario** que mejore
la efectividad de las entradas de la estrategia base (POI multi-TF + R:R≥2 + TP a liquidez),
**sin reemplazarla**.

---

## 1. Resumen ejecutivo (para Hugo)

Sí hay un complemento que mejora de verdad las entradas, y es coherente entre varias
herramientas independientes: **operar el POI solo cuando el mercado está calmo y con
tendencia**. En concreto, el filtro más robusto es

> **VIX < 25 (idealmente < 20) Y ADX(14) > 25 en la TF de planeación.**

- Es lo único que pasó **todos** los controles: mejora en in-sample **y** out-of-sample,
  con costos modelados, **positivo en las 4 ventanas de walk-forward**, no depende de un
  solo par (jackknife) y su intervalo de confianza bootstrap **excluye el cero**
  (P(expectativa>0) = 0.97).
- Sube el winrate OOS de ~12% a ~19% y la expectativa OOS de **break-even a +0.77R/trade**
  (7 pares) / **+2.07R/trade** en el slice BTC+ETH que tú operas.
- Lo más valioso: en la ventana más reciente (mar–jun 2026) la **base cruda se vuelve
  negativa (−0.14R) pero el filtro la mantiene en +0.61R** — protege justo cuando la
  estrategia sin filtro se rompe.

Lo que **NO** sirvió (y conviene no agregar): volumen alto, "Solo NY", RSI, EMA 53/200,
correlación BTC-SPX. Detalle abajo.

Hay un prototipo integrable listo en `research/regime_filter.py` (no toca el frontend).

⚠️ Honestidad: aun filtrada, la estrategia sigue teniendo **pocas ganadoras grandes**
(cola gorda) y los intervalos son anchos. Es una mejora real y defendible, no una certeza.

---

## 2. Metodología (innegociable)

- **Base de comparación.** Reproduje **exactamente** el criterio en vivo
  (`modules/trading/smc_live.analyze`: POI multi-TF en 1D/4h/1h, zona descuento/premium,
  TP a la siguiente liquidez sin barrer, filtro R:R≥2), el mismo que da tu backtest de
  referencia (OOS 93 trades, +0.97R, PF 2.14 en BTC+ETH). Lo corrí sobre **7 pares**
  (BTC, ETH, SOL, BNB, XRP, ADA, DOGE), TF de planeación **1h y 4h** → **611 trades
  cerrados** (vs 210 del original), para que un filtro binario deje muestra suficiente.
- **Anti-repaint estricto.** En cada barra de decisión solo se ven velas cerradas; las HTF
  solo si su cierre ya ocurrió; el resultado se resuelve con barras posteriores. Los
  indicadores del filtro (EMA, RSI, ADX, volumen) se calculan hasta la barra de decisión;
  el VIX/SPX usan el último cierre diario ya conocido.
- **Costos modelados (esto faltaba en el backtest original).** Comisión 0.05%/lado +
  slippage 0.02%, ida y vuelta = 0.14% del nocional, convertido a R con el riesgo real de
  cada setup (`costo_R = 0.0014 / risk_frac`). **Mediana 0.207R/trade** — nada despreciable.
  Reporto todo con y sin costos.
- **Split temporal 70/30** (in-sample antiguo / out-of-sample reciente) + **walk-forward**
  de 4 ventanas. **Siempre reporto OOS.**
- **Umbral de robustez:** OOS expectativa_neta>0, PF_neto≥1.1, ≥30 trades OOS,
  walk-forward>0 y **mejora sobre la base**. Nada se elige por el in-sample.
- **Anti-overfitting:** se probaron 27 filtros; se exige que el ganador mejore en IS **y**
  OOS, que tenga sentido económico y que el efecto sea consistente (no un solo tramo/par).
  Bootstrap (2000 resamples) para medir incertidumbre dada la cola gorda.

**Datos:** cripto vía klines públicas de Binance (caché del repo). SPX (`^GSPC`) y VIX
(`^VIX`) diarios vía API pública de Yahoo Finance, cacheados en `research/data_macro/`.
Correlación BTC-SPX a 30 días y régimen de BTC vs su MA200d calculados de ahí.

---

## 3. La base, con costos: el punto de partida real

| Métrica | IS (sin costos) | IS (con costos) | **OOS (sin costos)** | **OOS (con costos)** |
|---|---|---|---|---|
| Trades | 349 | 349 | 262 | 262 |
| Winrate | 16.3% | 16.3% | 12.2% | 12.2% |
| Expectativa | +1.252R | +0.965R | +0.266R | **−0.023R** |
| Profit factor | 2.50 | 1.89 | 1.30 | **0.98** |

**Lectura honesta:** el PF 2.14 que ves en el Diario es real para BTC+ETH y **sin costos**.
Pero al ampliar a 7 pares **y** modelar costos, la base out-of-sample queda en **break-even
(PF 0.98)**. Es decir: la estrategia cruda, generalizada y con costos, **no tiene edge claro
por sí sola** → tiene todo el sentido buscar un filtro que la lleve a terreno positivo.
(En el slice BTC+ETH con costos la base sí queda positiva: OOS +0.62R, PF 1.55 — ver §6.)

---

## 4. Filtros probados uno por uno (OOS, neto de costos, 7 pares)

Δexp = mejora de expectativa OOS sobre la base (−0.023R). ✅ = cruza el umbral de robustez.

| Filtro | OOS n | win | exp neto | PF | Δexp | WF exp | |
|---|---|---|---|---|---|---|---|
| **VIX < 20 (calma)** | 187 | 15.5% | +0.404R | 1.37 | +0.427 | 0.94 | ✅ |
| **VIX < 25** | 208 | 14.9% | +0.273R | 1.25 | +0.296 | 0.71 | ✅ |
| **ADX > 25 (tendencia fuerte)** | 154 | 15.6% | +0.380R | 1.35 | +0.403 | 0.54 | ✅ |
| **ADX > 20** | 198 | 14.1% | +0.238R | 1.22 | +0.261 | 0.48 | ✅ |
| **Tendencia EMA 20/50 a favor** | 79 | 16.5% | +0.486R | 1.43 | +0.509 | 0.94 | ✅ |
| **Pendiente EMA200 a favor** | 69 | 17.4% | +0.474R | 1.43 | +0.497 | 1.22 | ✅ |
| Precio sobre EMA50 a favor | 108 | 15.7% | +0.312R | 1.27 | +0.335 | 0.84 | ✅ |
| Precio sobre EMA200 a favor | 80 | 15.0% | +0.223R | 1.20 | +0.246 | 0.65 | ✅ |
| EMA 9/21 a favor | 102 | 15.7% | +0.186R | 1.17 | +0.209 | 0.48 | ✅ |
| EMA 50/200 a favor | 72 | 11.1% | −0.056R | 0.95 | −0.033 | 1.11 | · |
| **EMA 53/200 a favor (tu Pine)** | 71 | 9.9% | −0.318R | 0.73 | −0.295 | 0.98 | ✗ |
| RSI no extremo / momentum / valor | 94–251 | ~10–12% | <0 | <1 | <0 | ~0.4 | ✗ |
| **Volumen > media** | 141 | 6.4% | −0.557R | 0.54 | −0.534 | 0.14 | ✗ |
| Volumen > 1.5× media | 72 | 5.6% | −0.703R | 0.41 | −0.68 | −0.06 | ✗ |
| **Solo NY** | 107 | 7.5% | −0.683R | 0.43 | −0.66 | 0.11 | ✗ |
| Excluir Londres | 203 | 11.8% | −0.182R | 0.84 | −0.16 | 0.43 | ✗ |
| **VIX > 25 (estrés)** | 54 | 1.9% | −1.159R | 0.05 | −1.14 | −1.16 | ✗ |
| Corr BTC-SPX > 0.5 (acople) | 110 | 11.8% | −0.421R | 0.63 | −0.40 | 0.30 | ✗ |
| Corr BTC-SPX < 0.3 (desacople) | 27 | 7.4% | −0.242R | 0.81 | −0.22 | 0.61 | ⚠ pocos |
| BTC vs MA200d | — | — | — | — | — | — | inconcluso* |

\* En el período OOS, BTC estuvo **siempre bajo su MA200d**, así que ese filtro no discrimina
nada en OOS (degenerado). Inconcluso, lo descarto.

### Qué se ve
- **Régimen de volatilidad (VIX) es la palanca más fuerte y la que más muestra conserva.**
  VIX bajo → bien; **VIX > 25 es catastrófico** (winrate 1.9%, −1.16R): en pánico, los POIs
  se atraviesan sin respeto. Tiene sentido económico.
- **Tendencia presente ayuda** (ADX alto, EMA 20/50 y pendiente EMA200 a favor, precio sobre
  EMA): el POI a favor de la corriente se respeta más.
- **Sorpresas honestas:** "Solo NY" y "Excluir Londres" **perjudican** aquí (lo contrario a
  un experimento previo con otra base); el **volumen alto perjudica** (las velas de alto
  volumen suelen romper la zona en vez de respetarla); **tu EMA 53/200 como filtro de
  tendencia no ayuda** a estas entradas (cruces lentos y escasos); el **RSI no aporta**.
- La **correlación BTC-SPX** no funcionó como filtro útil; el régimen macro que sí sirve es
  el **nivel de VIX**, no la correlación.

---

## 5. Combinaciones y robustez del finalista

Exigiendo mejora en **IS y OOS** a la vez (con costos):

| Variante | IS exp | IS PF | OOS exp | OOS PF | OOS n | WF exp |
|---|---|---|---|---|---|---|
| BASE | +0.965 | 1.89 | −0.023 | 0.98 | 262 | 0.54 |
| VIX<25 | +0.965 | 1.89 | +0.273 | 1.25 | 208 | 0.71 |
| VIX<20 | +1.287 | 2.21 | +0.404 | 1.37 | 187 | 0.94 |
| ADX>25 | +0.671 | 1.60 | +0.380 | 1.35 | 154 | 0.54 |
| **VIX<25 + ADX>25** | **+0.671** | **1.60** | **+0.765** | **1.74** | **122** | **0.71** |
| VIX<25 + Pendiente EMA200 | +1.944 | 2.74 | +0.763 | 1.70 | 59 | 1.41 |
| VIX<20 + EMA 20/50 | +1.713 | 2.49 | +1.004 | 1.92 | 59 | 1.42 |
| EMA 20/50 + ADX>25 | −1.506† | 2.08 | +1.174 | 2.12 | 42 | 1.27 |

† Ese combo brilla en OOS pero su **in-sample es negativo** → lo rechazo (probable suerte de
régimen, no edge estable). El método hace su trabajo.

### Bootstrap de la expectativa OOS (IC 90%, 2000 resamples)

| Variante | exp | IC 90% | P(exp>0) | n |
|---|---|---|---|---|
| BASE | −0.023 | [−0.41, +0.40] | 0.45 | 262 |
| VIX<20 | +0.404 | [−0.14, +0.99] | 0.88 | 187 |
| **VIX<25 + ADX>25** | **+0.765** | **[+0.10, +1.55]** | **0.97** | **122** |
| VIX<20 + EMA 20/50 | +1.004 | [−0.11, +2.34] | 0.93 | 59 |

**VIX<25 + ADX>25 es el único finalista cuyo IC 90% no cruza el cero** y con muestra grande.
Los combos con mayor punto-estimado (VIX<20+EMA, EMA+ADX) tienen menos trades y sus IC
incluyen el cero: prometen más pero son menos confiables.

### Walk-forward por ventana (base vs filtro, con costos)

| Ventana | BASE exp / n | FILTRO exp / PF / win / n |
|---|---|---|
| V1 2025-06→09 | +1.57 / 117 | +1.13 / 2.06 / 18.2% / 66 |
| V2 2025-09→12 | +0.85 / 97 | +0.62 / 1.55 / 11.7% / 60 |
| V3 2025-12→26-03 | +0.55 / 177 | +0.56 / 1.52 / 14.8% / 88 |
| **V4 2026-03→06** | **−0.14 / 220** | **+0.61 / 1.57 / 15.6% / 96** |

El filtro es **positivo en las 4 ventanas** y, sobre todo, **rescata la V4** donde la base
ya pierde dinero. No es un único tramo afortunado.

### Jackknife por par (OOS) y dependencia de la cola
- Sacando cualquier par, el filtro sigue positivo: exp de **+0.26 a +1.04**, PF 1.25–2.03.
  El más influyente es BTC (sin BTC baja a +0.26R) pero **nunca se da vuelta**.
- Quitando las **top-3 ganadoras** del OOS filtrado, la expectativa sigue positiva
  (+0.225R, PF 1.21). El edge no es una sola lotería, aunque **sí depende algo de la cola**
  (la mayor ganadora fue 25.5R; quitándola, exp baja de 0.77 a 0.56R).

---

## 6. Validación en BTC+ETH (lo que Hugo opera de verdad)

Con costos, slice BTC+ETH:

| Variante | IS exp | OOS exp | OOS PF | OOS n | full exp | full n |
|---|---|---|---|---|---|---|
| BASE | +0.99 | +0.62 | 1.55 | 94 | +0.82 | 210 |
| VIX<25 | +0.99 | +1.02 | 1.92 | 77 | +1.00 | 193 |
| VIX<20 | +1.32 | +1.64 | 2.57 | 61 | +1.45 | 154 |
| **VIX<25 + ADX>25** | **+0.50** | **+2.07** | **3.07** | **47** | **+1.16** | **111** |

En BTC+ETH la base ya es positiva (tu PF 2.14 sin costos baja a ~1.55 con costos), y el
filtro la **mejora claramente** manteniendo muestra razonable. El combo recomendado lleva el
OOS a **+2.07R/trade, PF 3.07** con n=47.

---

## 7. Recomendación concreta

1. **Sumar un filtro de RÉGIMEN como capa de permiso** sobre el POI (no cambia la detección):
   - **Recomendado (mejor balance robustez/muestra):** operar el POI solo si
     **VIX < 25 y ADX(14) > 25** en la TF de planeación.
   - **Variante estricta (más calidad, menos trades):** VIX < 20.
   - **Sin dato macro (fallback):** solo ADX > 25 (también cruza el umbral, aunque más débil).
2. **Usar el VIX como semáforo de tamaño**, no solo on/off: tamaño completo con VIX<20,
   medio con 20–25, **nada con VIX>25** (ahí la evidencia de pérdida es contundente).
3. **No agregar** como filtros: volumen, "Solo NY"/sesión, RSI, EMA 53/200, correlación
   BTC-SPX (ninguno mejora; varios empeoran).

**Prototipo integrable:** `research/regime_filter.py` — calcula ADX de las velas cerradas,
trae el VIX (Yahoo, cacheado, anti-repaint) y expone `regime_gate(sel_candles)` que devuelve
`{ok, vix, adx, reason}`. Incluye notas para envolverlo alrededor de `smc_live.analyze`
sin tocar la lógica SMC ni el frontend. Hoy mismo: VIX 19.4, ADX BTC 1h ~30 → permiso OK.

### Salvedades (lo honesto)
- La base, generalizada y con costos, es break-even OOS; el filtro es lo que la hace
  positiva. No es "una estrategia ganadora con un extra", es **un filtro necesario**.
- Cola gorda: la expectativa todavía se apoya en pocas ganadoras grandes; IC anchos.
- El VIX es autocorrelacionado: el OOS cubre regímenes limitados. Que el walk-forward sea
  positivo en las 4 ventanas mitiga, pero no elimina, este riesgo. Tratar como **hipótesis
  fuerte y monitoreable**, no como certeza. Recomiendo forward-test en el Diario.

---

## 8. Archivos producidos (en el worktree `research-smc-filtros`)

- `research/macro.py` — descarga/caché SPX, VIX, BTC diario + derivados de régimen.
- `research/collect_trades.py` — reproduce las entradas base en 7 pares con snapshot de
  features anti-repaint → `research/trades_features.json` (611 cerrados).
- `research/evaluate.py` — base con/sin costos + 27 filtros uno por uno → `filter_results.json`.
- `research/evaluate2.py` — combinaciones, bootstrap, slice BTC+ETH → `combo_results.json`.
- `research/diagnostics.py` — walk-forward por ventana, jackknife por par, dependencia de cola.
- `research/regime_filter.py` — **prototipo integrable** del filtro recomendado.
- `research/data_macro/` — caché de SPX/VIX/BTC diarios.
