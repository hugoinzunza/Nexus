# Modelo visual BTA v2 — diseño de indicador (research)

Fecha: 2026-07-05 · Estado: **prototipo en research/**, cero contacto con el bot,
las señales, la config operativa o el dry-run de Fase 1.

## Qué es

Segunda iteración del modelo de objetos visuales inspirado en el TradingView del
profe/BTA, construida a partir de la auditoría `bta_visual_audit2_2026-07-05.md`.
Es una capa de LECTURA (indicador/panel), no de decisión.

## Dónde vive hoy el modelo visual en Nexux

| Capa | Archivo | Qué hace |
|---|---|---|
| Indicador vivo | `modules/trading/smc_live.py` | rango+EQ, niveles weak/strong, POIs con mitigación/invalidación, CDC micro tras toque, TP a liquidez |
| Formación de POI | `modules/trading/strategies.py` (`detect_pois`) | sweep+displacement+FVG+OB con EQ **local** al formarse |
| Prototipo v1 | `research/bta_visual_model.py` | RangeMap, Zone, CharacterLevel, SwingLeg, score |
| Prototipo v2 | `research/bta_visual_model2.py` (**nuevo**) | corrige D1–D3, agrega targets/repisas/estados completos |

## Defectos del v1 que v2 corrige (con test que lo demuestra)

| # | Defecto v1 | Corrección v2 | Test |
|---|---|---|---|
| D1 | `zone_from_poi` clasificaba la zona contra el EQ del rango **GLOBAL** — el mismo error del veto `disc_ok` que se sacó del bot | `leg_side()` + `zone_from_poi_v2()`: lado **LOCAL** por pierna activa, fib 0/0.5/1 del SwingLeg (como el zigzag del profe) | `test_d1_*` |
| D2 | Los CDC nacían ya `broken`, sin ciclo de vida ni convivencia | `cdc_ladder()`: escalera de niveles simultáneos con `pending → broken → reclaimed / retest` e historial | `test_d2_*` |
| D3 | Una zona se confirmaba con cualquier CDC roto, aunque el quiebre fuera ANTERIOR al toque (la "entrada tardía" que el Diario penaliza: confirmado-al-nacer +0.095R vs zona fresca +0.707R) | `ZoneV2.step()`: confirmación SOLO con quiebre posterior al toque y dentro de `CONFIRM_WINDOW` | `test_d3_*` |

## Modelo de datos propuesto

- **RangeMap** (v1, se reusa): rango visible + premium/discount como **contexto**, nunca veto.
- **SwingLeg** (v1) + `leg_fibs()`/`leg_side()` (v2): fib 0/0.5/1 y EQ local por pierna.
- **CDCLevel** (v2): peldaño de la escalera CDC con estados y timestamps auditables.
- **ZoneV2** (v2): máquina de estados `pending → tapped → confirmed → target_hit`,
  con `failed → retest_continuation` que **invierte el rol** de la zona
  (discount perdido pasa a resistencia de continuación short — capturas 05-27/06-24).
- **TargetLiquidity** (v2): weak high/low sin barrer, `alto_referencial`,
  `minimo_ref` y `repisa` (cluster de ≥2 pivotes casi iguales), con estado pending/hit.
- **visual_snapshot()**: payload único para la UI con `research_only: True`.

## Mockup

`research/bta_visual_mockup.py` genera `bta_visual_mockup_2026-07-05.svg` desde
las velas reales BTCUSDT.P M15 (may–jun 2026, mismo tramo de las capturas):
velas + bandas globales suaves + fib local de la pierna activa (dorado) +
escalera CDC con estado (gris/rojo/ámbar) + targets de liquidez capados a los
cercanos (azul). Sin emojis; etiquetas en español.

## Evidencia: qué es débil y qué no

| Pieza | Evidencia | Nivel |
|---|---|---|
| P/D local por pierna | dealing_range 06-12 OOS + Diario disc_ok + zigzag del profe | **Fuerte** (3 fuentes) — pero como LECTURA; el veto sigue fuera |
| CDC posterior al toque | deep backtest cdc_liq (+0.70R OOS M15-BTC) vs matiz del Diario (E4) | Prometedora pero **contradictoria entre datasets** — variante paralela, no gate |
| Escalera CDC / retest | solo capturas may–jun 2026 (n≈6, un régimen, sesgo retrospectivo) | **Débil** — solo visual |
| retest_continuation | ídem capturas; sin conteo OOS propio | **Débil** — hipótesis a contar en 4 años |
| Repisas/targets parciales | ídem | **Débil** — presentación, no edge |

## Qué NO debe llegar a producción todavía

1. Nada del v2 como **gate del bot** — es indicador/lectura.
2. `retest_continuation` y freshness como señal: primero contar casos OOS en el
   histórico de 4 años con el detector propio (anti-repaint).
3. CDC-tras-toque como gatillo: primero la columna paralela en el Diario
   (toque vs confirmación) hasta juntar muestra.
4. El score visual (v1) como decisión: quedó casi invalidado (+0.087R neto).
5. Cualquier regla calibrada contra las capturas 06-30/07-01 (duplicadas, un
   régimen, retrospectivas).

## Próximos pasos sugeridos (en orden)

1. **Replay histórico del v2** sobre los 4 años M15/1h propios: contar frecuencia
   y outcome de `retest_continuation`, `reclaimed` y `retest` de la escalera
   (research puro, sin operar).
2. **Columna paralela en el Diario**: registrar para cada setup si hubo CDC
   post-toque dentro de la ventana, y comparar netR de ambas variantes con la
   muestra que la Fase 1 va generando (solo lectura del dry-run, sin tocarlo).
3. Si (1)+(2) validan, recién ahí discutir exponer `visual_snapshot` en el panel
   SMC del hub como capa opcional (flag de UI, apagada por defecto).

## Archivos de esta entrega

- `research/bta_visual_model2.py` — modelo v2 (nuevo)
- `research/test_bta_visual_model2.py` — 11 tests (D1/D2/D3 + estados + targets + smoke real)
- `research/bta_visual_mockup.py` + `research/bta_visual_mockup_2026-07-05.svg` — mockup
- Este documento.

## Qué NO se tocó

`modules/bot/*`, `modules/trading/smc_live.py`, `strategies.py`, `config/nexus.json`,
el VPS (ni ssh de escritura), el dry-run de Fase 1, credenciales, BTA (sigue
`paper_only`). Suite completa verde (49 tests, incluye los 11 nuevos).
