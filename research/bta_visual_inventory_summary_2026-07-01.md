# Resumen inventario visual BTA

Fuente: `/Users/hugh/crisol/nexux/research/bta_visual_inventory_2026-07-01.json`

## Validación

Errores: 0

```text
OK
```

## Cobertura

Capturas inventariadas: 9

| confianza | capturas |
| --- | --- |
| high | 3 |
| low | 2 |
| low_medium | 1 |
| medium | 1 |
| medium_high | 2 |

## Objetos Nexux requeridos

| objeto | apariciones |
| --- | --- |
| CharacterLevel | 5 |
| RangeMap | 1 |
| ReferenceLevel | 4 |
| SwingLeg | 2 |
| TargetZone | 1 |
| Zone | 5 |

## Tipos de zona

| tipo | apariciones |
| --- | --- |
| counter_poi | 1 |
| discount_poi | 4 |
| intermediate_liquidity | 2 |
| premium_poi | 2 |
| reference | 2 |
| retest_continuation | 2 |
| strong_high | 1 |
| target | 1 |

## Estados requeridos

| estado | apariciones |
| --- | --- |
| broken | 1 |
| completed | 1 |
| confirmed | 3 |
| failed | 3 |
| forming | 1 |
| invalidated | 1 |
| pending | 1 |
| retest_continuation | 2 |
| tapped | 1 |
| target_hit | 2 |

## Hallazgo cuantitativo central

| filtro | trades | WR | expR | PF |
| --- | --- | --- | --- | --- |
| POI + liquidez RR>=2 | 605 | 26.8% | -0.129 | 0.86 |
| POI + CDC + liquidez | 272 | 44.9% | 0.7 | 1.99 |

## Capturas pendientes de re-navegación

| capture | confidence | next |
| --- | --- | --- |
| 2025-11-05_zigzag_structure | medium | Re-navigate 2025 dates on clean chart and recapture independent scenes. |
| 2026-01-15_level_cluster | low_medium | Re-navigate around January 2026 and capture context before/after levels. |
| 2025-08-01_structure_context | low | Re-navigate 2025-08-01 on clean chart. |
| 2025-04-16_liquidity_case | low | Re-navigate 2025-04-16 on clean chart. |
