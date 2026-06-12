# ¿Aporta el filtro de EQ GLOBAL (ventana de 400 velas) sobre los POIs?

**Backtest de investigación — 2026-06-12** · Pregunta de Hugo: el descuento/premium
de un POI se mide contra el fib 0.5 de su dealing range (swing relevante), no
contra el 50% de una ventana global. ¿Tiene razón?

---

## Veredicto en una línea

> **Sí, Hugo tenía razón.** El POI ya nace clasificado por el equilibrio LOCAL de
> su swing (así lo valida `detect_pois`, y así se backtesteó). El filtro EXTRA de
> EQ global de 400 velas que aplicaba la capa de plan en vivo **empeora el OOS en
> 1h (−0.096R → −0.130R) y los toques que descarta son justamente los mejores
> (+0.045R, PF 1.07)**. En 15m es ruido neutro. Se elimina de la capa de plan.

---

## 1. Qué se comparó

Mismo universo de toques de POI (correspondencia 1:1), 7 pares, ~4 años,
RR fijo = 2, anti-repaint estricto, costos 0.05%/lado + 0.02% slippage,
split temporal 70/30. Parámetros del research previo, sin tuneo.

| Var | Regla |
|-----|-------|
| **A** | POI solo — descuento/premium **LOCAL** al formarse (la regla validada de `detect_pois`: EQ = fib 0.5 del último swing high/low confirmado). |
| **B** | A ∩ **EQ global**: el POI además queda del lado correcto del EQ del dealing range de las últimas 400 velas (RANGE_PIV=10) al momento del toque — lo que exigía `smc_live._tpsl`. |
| **C** | A \ B: los toques que el filtro global descartaba. |

## 2. Resultados (con costos)

### TF 1h
| | n IS | exp IS | n OOS | **exp OOS** | PF OOS | wr OOS | P(exp>0) |
|---|---|---|---|---|---|---|---|
| A — regla validada | 1615 | −0.024 | 815 | **−0.096** | 0.87 | 36.1% | 0.03 |
| B — + EQ global | 1204 | −0.057 | 587 | **−0.130** | 0.82 | 35.3% | **0.01** |
| C — lo descartado | 578 | +0.005 | 300 | **+0.045** | 1.07 | 40.3% | 0.70 |

El filtro global retiene el 72% de la muestra y la EMPEORA; lo que bota era lo
mejor. Por pares (OOS): C le gana a B en **5 de 7** (ETH: B −0.335 vs C +0.588).

### TF 15m
| | n OOS | exp OOS | PF OOS |
|---|---|---|---|
| A | 967 | −0.099 | 0.85 |
| B | 813 | −0.090 | 0.86 |
| C | 189 | −0.092 | 0.87 |

Neutro: el filtro global no mueve la aguja en 15m.

## 3. Lectura honesta

1. **El concepto correcto es el local**: premium/descuento es una propiedad del
   POI respecto al fib 0.5 de SU dealing range (el swing relevante al formarse),
   tal como lo enseña el marco SMC y como lo replica `detect_pois`. Eso ya está
   dentro de la regla validada (A).
2. **El EQ global de 400 velas mezcla regímenes**: ancla el rango a extremos de
   hace semanas. Un POI en descuento local que queda "en premium global" suele
   estar en tendencia alcista reciente — y eso (comprar el pullback local en
   tendencia) era justamente el subconjunto bueno que el filtro botaba.
3. **C (+0.045R, P=0.70) NO es un edge para perseguir por sí solo** — la
   conclusión accionable es alinear la capa de plan con A (quitar el filtro
   global), no invertirlo.
4. Las bandas premium/descuento del gráfico siguen siendo CONTEXTO visual del
   rango visible; ya no son un veto del plan.

## 4. Acción aplicada

`smc_live._tpsl` deja de exigir el lado del EQ global: la corrección de zona
queda donde siempre estuvo validada — en la formación del POI (`detect_pois`,
EQ local del swing). El forward-test del Diario sigue midiendo el desempeño
real de los planes con la regla alineada al backtest.

---

*Reproducible:* `research/dealing_range_backtest.py` → `research/dealing_range_results.json`.
PIV=2, DISP=1·ATR, POI máx 30 días, RR=2, RANGE_PIV=10, RANGE_WINDOW=400,
split 70/30, bootstrap 2000 remuestreos. Sin tuneo sobre OOS.
