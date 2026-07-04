# Inventario capturas en vivo BTA

Fuente: `/Users/hugh/crisol/nexux/research/tradingview_bta_screenshots_clean_2026-07-01`

Estado: `supplemental_not_full_multiyear_completion`

## Conteo

| status | count |
| --- | --- |
| discard_blank_or_projection | 44 |
| duplicate_useful | 2 |
| partial | 2 |
| useful | 7 |
| weak_unclassified | 8 |

Capturas útiles independientes: `7`

## Capturas inventariadas

| file | status | period | role | objects |
| --- | --- | --- | --- | --- |
| live_2026-07-01_current_jun_range.png | useful | 2026-06 | range_map_premium_discount | grey_decision_zones, blue_reaction_band, green_checks, operational_high_low, reference_levels |
| live_autoscale_after_blank_windows.png | useful | 2026-02 | bearish_swing_sequence | cyan_pivots, downtrend_leg, horizontal_reference_zone |
| live_back_autoscale_2026_to_2025_01.png | useful | 2026-01 | january_reversal_context | candles, swing_reversal |
| live_back_autoscale_2026_to_2025_02.png | useful | 2025-12/2026-01 | late_december_impulse | candles, bullish_impulse |
| live_back_autoscale_2026_to_2025_03.png | useful | 2025-12 | december_range_sweep_context | candles, large_wick, range_context |
| live_back_autoscale_2026_to_2025_04.png | useful | 2025-12 | zigzag_pivot_structure | purple_zigzag, cyan_pivots, swing_arrows |
| live_drag_history_2026_2025_01.png | duplicate_useful | 2025-12 | zigzag_pivot_structure_duplicate | purple_zigzag, cyan_pivots, swing_arrows |
| live_drag_right_test.png | partial | 2026-01 | intraday_range_context | candles, operational_high_low |
| live_pan_test_after_scrollX_negative.png | useful | 2026-06 | trade_box_with_cdc_and_liquidity | trade_box, green_checks, cyan_pivots, orange_leg, red_diagonal_structure |
| live_reverse_from_blank_test.png | partial | 2026-01 | price_context_without_strong_annotations | candles, operational_low |
| live_zoom_test_scrollY_positive.png | duplicate_useful | 2026-06 | trade_box_duplicate | trade_box, cyan_pivots, green_checks |

## Lectura agregada

- Junio 2026 confirma que el profe dibuja una operación completa: POI, CDC, pivotes, objetivo, stop, ratio y resultado.
- Febrero/enero 2026 aportan contexto de pivotes y extremos operativos, pero no todos tienen POI/CDC rotulado.
- Diciembre 2025 vuelve a confirmar la capa `zigzag + pivotes celestes`, que debe traducirse a `SwingLeg`/`PivotGraph` en Nexux.
- Muchas capturas del paneo largo quedaron en margen blanco/proyección y no se usan como evidencia independiente.

## Pendiente

Sigue faltando re-navegar 2025/2024 con una forma estable de ir a fecha o con el chart recargado/limpio. Este inventario mejora la evidencia, pero no cierra la misión multi-año.
