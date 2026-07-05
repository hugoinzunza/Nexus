# Replay OOS del modelo visual BTA v2 — 4 años, 10 datasets

Fecha: 2026-07-05 · **Research only · No señal · No bot · NO usar para activar live.**

Datos: klines locales 2022-06 → 2026-06. 1h × 7 pares (BTC/ETH/SOL/XRP/ADA/BNB/DOGE)
+ 15m × 3 (BTC/ETH/SOL). Split temporal IS 70% / OOS 30% (corte global) + walk-forward
por año. Costos maker-aware del Diario. Resolución intrabar **conservadora** (SL y TP
en la misma vela = SL). Anti-look-ahead: piernas causales (`active_leg as_of`, fix
02495b7), POIs anti-repaint, targets = pivotes no barridos al momento de la consulta.

Script: `research/bta_visual_oos.py` · Datos crudos: `bta_visual_oos_results.json`.

⚠️ **Qué mide y qué NO**: es un proxy CRUDO de cada hipótesis visual aislada
(entrada en el borde de la zona, TP = pivote piv-10 más cercano, rr≥1, sin cap de
SL). NO reproduce el plan validado del Diario (rr≥5 con TP a liquidez del plan,
SL estructural con tope). Sirve para comparar hipótesis ENTRE SÍ y contra OOS,
no para re-litigar la Fase 1.

## Tabla principal (netR, costos incluidos)

| Variante | N ALL | ALL avg | N OOS | OOS avg | Por año |
|---|---|---|---|---|---|
| `touch` (toque de POI) | 8.440 | −0.033 | 2.524 | −0.102 | +0.20 / +0.03 / −0.05 / −0.11 / −0.15 |
| `cdc_post` (entrar en el CDC tras el toque) | 1.288 | **−0.153** | 397 | −0.133 | negativo los 5 años |
| `retest_cont` (zona fallida → continuación) | 7.309 | **−0.123** | 2.190 | −0.134 | −0.14/−0.09/−0.17/−0.18/**+0.04 (2026)** |
| `reclaimed` (descriptivo) | 165.280 quiebres | **69% se reclama en ≤12 velas** | — | — | estable por año |

### Cortes clave

| Corte (touch) | N | avg netR |
|---|---|---|
| 1h | 2.808 | **+0.125** |
| 15m | 5.632 | −0.111 |
| rr≥5 | 2.284 | +0.079 |
| 1h × rr≥5 | 942 | +0.173 (IS +0.227 / **OOS +0.060**) |
| 1h × rr≥5 por año | — | 2022 +0.63 → 2023 +0.44 → 2024 −0.02 → 2025 +0.01 → 2026 +0.07 |
| 1h × rr≥5 × discount local | 432 | IS +0.637 / **OOS −0.284** |
| 1h × rr≥5 × premium local | 508 | IS ~0 / OOS +0.382 |

### El hallazgo que reconcilia todo (pareado, mismos POIs tocados)

| Subconjunto | N | WR | avg netR |
|---|---|---|---|
| touch en zonas que LUEGO confirmaron CDC | 1.261 | 32.3% | **+0.677** |
| touch en zonas que NO confirmaron | 7.179 | 24.3% | −0.157 |
| (solo 1h) con CDC / sin CDC | 444 / 2.364 | 35.6% / 24.2% | **+0.852** / −0.012 |

**El CDC post-toque tiene INFORMACIÓN real** (separa +0.68 de −0.16)… pero
**entrar al precio del CDC la destruye** (`cdc_post` = −0.153): cuando confirma,
el precio ya corrió y el RR quedó peor. Es la misma "entrada tardía" que mostró
el Diario (E4). El profe entra EN la zona; la confirmación valida MANTENER, no
perseguir. ⚠️ El pareado NO es operable tal cual (al tocar no sabes si confirmará
después) — es diagnóstico, no señal.

## Veredictos

### Robustos (N grande, multi-año, multi-par)
1. **`cdc_post` como gatillo mecánico: DESCARTAR.** n=1.288, negativo los 5 años,
   ambos TFs, ambas direcciones, ambos lados. El `cdc_liq` (+0.7R) del deep
   backtest del 07-01 NO generaliza (era BTC-15m con otra mecánica de plan) —
   queda invalidado como candidato a gate.
2. **`retest_cont` como señal: DESCARTAR.** n=7.309, negativo 2022–2025. Solo
   2026 (+0.04) es ~breakeven — **exactamente el tramo de las capturas**: la
   hipótesis visual nació del único régimen donde no pierde. Trampa de régimen
   de manual. Se queda como ESTADO visual en la UI, no como señal.
3. **15m no tiene edge** (touch −0.111, n=5.632): reconfirma "no operar 15m".
4. **69% de los quiebres micro (piv=2) se reclaman en ≤12 velas**: los quiebres
   CDC micro son ruido 2 de cada 3 veces — explica por qué perseguirlos pierde.
5. **El edge del toque se concentra en 1h** (+0.125 vs −0.111 en 15m; n>2.8k
   cada uno).

### Prometedores pero débiles
6. **CDC como información condicional** (pareado +0.85 vs −0.01 en 1h): la
   versión OPERABLE a testear no es entrar tarde, sino **abortar temprano**:
   entrar al toque y salir a pérdida reducida si el CDC no aparece en la ventana.
   Requiere diseño + test propio; muestra pareada aún no operable.
7. **1h × rr≥5 positivo pero DECAYENTE** (+0.63 en 2022 → ~0 en 2024-2026 en
   este proxy). No contradice la Fase 1 (el plan del Diario es distinto y tiene
   su propio forward), pero avisa: el edge no es estacionario; el criterio
   pre-registrado de Fase 2 es el árbitro correcto.

### Descartar como gate (confirmación adicional)
8. **P/D local como veto**: discount×1h×rr≥5 se INVIERTE OOS (IS +0.64 → OOS
   −0.28) mientras premium hace lo contrario. Ni el lado local es gate estable —
   consistente con dealing_range 06-12 y con haber sacado `disc_ok`. Lectura
   visual: sí. Filtro: no.

## Riesgos de overfitting de este mismo estudio
- El proxy tiene grados de libertad propios (borde de entrada, TP al pivote más
  cercano, ventanas TAP/SIM/RETEST): los NEGATIVOS son robustos (empeorarían con
  costos más duros), pero los POSITIVOS chicos (cdc_post 1h OOS +0.17, n=142;
  premium OOS +0.38, n=158) NO deben tomarse como edge — muestras chicas y
  sensibles al proxy.
- El pareado CDC usa información posterior al toque (diagnóstico, no señal).
- 15m solo 3 pares; 1h sí cubre los 7.

## Próximos pasos
1. Testear la variante **"abort si no hay CDC"** (entrada al toque, salida a
   −0.3R si no confirma en la ventana) — es la única forma operable de capturar
   la información del pareado. Research puro.
2. Dejar `retest_continuation` y la escalera CDC como **capas visuales** de la
   vista research (ya lo son); no promoverlas.
3. La Fase 1 dry-run sigue siendo el árbitro del plan real (rr≥5 global +
   5 pares): este estudio no la toca ni la contradice.

## Qué no se tocó
Bot, dry-run Fase 1, `config/nexus.json`, credenciales, VPS (sigue en 502fec5).
Todo corrió LOCAL con klines históricos ya presentes en `data/`.
