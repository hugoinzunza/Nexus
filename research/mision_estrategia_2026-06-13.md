# Misión: estudio de la estrategia — mejoras, patrones y fractales

**2026-06-13** · Encargo de Hugo: "estudiar la estrategia, buscar mejoras,
patrones, revisar fractales (los estructurales, no los pequeños)".

Metodología común a los 5 estudios: 7 pares (BTC, ETH, SOL, BNB, XRP, ADA,
DOGE), ~4 años de Binance, anti-repaint estricto (POIs HTF con vela cerrada,
swings con confirm_idx, señal al cierre → entrada en apertura siguiente),
costos 0.05%/lado + 0.02% slippage, split temporal 70/30, bootstrap 2000
remuestreos, **cero tuneo sobre OOS**.

---

## El hallazgo mayor: el TP de LIQUIDEZ está validado (y el vivo ya lo usa)

`research/liq_tp_backtest.py` → `liq_tp_results.json`

Apuntar a la **siguiente liquidez opuesta sin barrer** (exigiendo RR efectivo
≥ 2) en vez de un RR fijo de 2, sobre el mismo universo de toques de POI:

| 1h OOS con costos | n | exp | PF | wr | máx DD | P(exp>0) |
|---|---|---|---|---|---|---|
| RR fijo 2 (referencia) | 815 | −0.096R | 0.87 | 36.1% | 99R | 0.03 |
| Liquidez RR≥1.5 | 507 | +0.269R | 1.33 | 32.1% | 32R | 0.987 |
| **Liquidez RR≥2.0** | 383 | **+0.371R** | **1.44** | 29.5% | **24R** | **0.993** |

- **Positivo en 7 de 7 pares** OOS (SOL +0.94, XRP +0.52, BTC +0.48, ETH +0.36,
  BNB/ADA/DOGE +0.11). Robustez entre pares que ninguna otra capa logró.
- El umbral no es de filo de navaja (RR≥1.5 también gana) → no es un artefacto
  del parámetro.
- Drawdown 4× menor que el RR fijo (24R vs 99R).
- **La señal más fuerte medida hasta ahora** (P=0.993 > régimen 0.97 > CDC 0.81).
- En 15m no rescata (+0.036, P=0.59): el scalp sigue sin edge.

**Caveats honestos:** el in-sample es levemente negativo (−0.04R) — el edge se
concentra en la mitad reciente (walk-forward: −0.15 / +0.15 / −0.15 / **+0.36 /
+0.25**). Win rate ~30%: rachas perdedoras largas, se cobra con pocos trades
grandes — psicológicamente exigente. Y puede ser dependiente de régimen.

**Integración: ya está hecha.** El plan en vivo (smc_live) apunta a liquidez
weak con RR≥2 desde el rediseño — esta misión RATIFICA ese diseño con datos.
La expectativa de referencia del forward-test del Diario pasa a ser la de esta
tabla (≈ +0.37R/trade OOS, wr ~30%), no la del RR fijo.

---

## Fractales pequeños (detección del POI): piv=2 no es frágil, y no es el edge

`research/fractal_piv_backtest.py` → `fractal_piv_results.json`

Curva de sensibilidad del pivote de detección (2 → 3 → 5), 1h OOS con costos:
exp −0.096 → −0.046 → −0.019; 15m: −0.099 → −0.064 → −0.080. La zona es suave
(piv=2 no es un pico aislado de sobreajuste) y **ninguna escala fractal vuelve
positivo el POI crudo**. El edge no vive en el fractal de detección; vive en
las capas (TP de liquidez, CDC, régimen). Nada que cambiar.

## Fractales ESTRUCTURALES (pedido de Hugo): el carácter orienta, no transforma

`research/structural_char_backtest.py` → `structural_char_results.json`

Con la misma lógica calibrada del gráfico (CDC mayor: swings calificados
pegajosos, quiebre por cierre) se computó el carácter por vela y se midió la
alineación del setup (1h OOS):

| Filtro | n | exp | PF | P |
|---|---|---|---|---|
| Sin filtro | 815 | −0.096 | 0.87 | 0.03 |
| Alineado (piv 10) | 430 | −0.035 | 0.95 | 0.30 |
| Contra (piv 10) | 466 | −0.110 | 0.85 | 0.05 |
| Alineado (piv 20) | 422 | −0.008 | 0.99 | 0.46 |
| Contra (piv 20) | 474 | −0.133 | 0.82 | 0.02 |

**El efecto direccional es real y consistente en ambas escalas** (a favor del
carácter > en contra, siempre), pero alineado solo no alcanza el umbral de
integración. Veredicto: el carácter estructural es CONTEXTO — exactamente el
rol que ya tiene como capa visual de CDC en el gráfico. El timing "CDC mayor
reciente" quedó sin muestra (n=33).

## Patrones (exploratorio — hipótesis, no filtros)

`research/patterns_backtest.py` → `patterns_results.json` · 1h OOS con costos:

- **TF de origen del POI**: los POIs de **1D** son otra cosa: +0.292R, PF 2.17,
  wr 57% — pero **n=42**. Hipótesis fuerte para el forward-test (el Diario ya
  guarda `poi_tf`; en unos meses se compara en vivo). NO aplicar como filtro
  aún. 4h y 1h: −0.09 ambos.
- **Sesión**: NY la menos mala (−0.04, n=363), Asia la peor (−0.18). Dirección
  plausible (liquidez real), insuficiente por sí sola.
- **Día de la semana**: "sábado +0.53R" con n=61 es el típico espejismo de
  celda chica. No se lee.

## El stack completo: las capas no se suman gratis

`research/stack_backtest.py` → `stack_results.json` · 1h OOS con costos:

| Variante | n | exp | PF | P |
|---|---|---|---|---|
| BASE (RR2) | 815 | −0.096 | 0.87 | 0.03 |
| + Régimen | 311 | −0.012 | 0.98 | 0.44 |
| + CDC | 287 | +0.066 | 1.13 | 0.82 |
| Régimen + CDC | 105 | +0.066 | 1.14 | 0.71 |
| **TP liquidez** | 383 | **+0.371** | 1.44 | **0.993** |
| Liquidez + Régimen + CDC | 4 | — | — | colapso |

- CDC reproduce su estudio (+0.066, P=0.82). Régimen+CDC **no mejora** a CDC
  solo (se canibalizan: filtran trades parecidos).
- **El TP de liquidez es la capa dominante** y NO se combina con CDC (la
  exigencia conjunta colapsa la muestra a 4 trades, igual que en el estudio
  CDC original).
- El walk-forward del TP de liquidez aguanta el régimen reciente (las dos
  ventanas más nuevas: +0.36 y +0.25), justo donde el RR fijo se desangra.

---

## Recomendaciones (solo lo que pasa umbral)

1. **Ratificar el TP de liquidez como el criterio del plan** (ya está en vivo).
   Leer el forward-test del Diario contra su expectativa real: ~+0.37R/trade,
   wr ~30%, rachas largas. Paciencia: el perfil es "pocos trades grandes".
2. **No agregar el carácter estructural como veto** — mantenerlo como capa
   visual (ya está). Re-evaluar si el forward-test acumula evidencia.
3. **Vigilar la hipótesis de POIs 1D** en el Diario (campo `poi_tf` ya se
   registra): si en vivo replican el PF>2 del backtest, considerar priorizarlos
   en el plan (hoy el plan elige por cercanía).
4. **No combinar liquidez+CDC como exigencia conjunta** (colapso de muestra).
   El CDC sigue como etiqueta de confirmación informativa, no como veto.
5. **15m sigue sin edge** con ninguna capa: el módulo hace bien en planear en
   1h/4h.

*Todo reproducible en `research/`: liq_tp_backtest.py, fractal_piv_backtest.py,
structural_char_backtest.py, patterns_backtest.py, stack_backtest.py y sus
JSON de resultados. Hipótesis, no garantías: el juez final es el forward-test.*
