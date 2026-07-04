# Deep backtest BTA visual BTC

Fecha: 2026-07-01. Datos locales BTCUSDT M15: 2022-06-12 17:45 UTC a 2026-06-11 19:30 UTC, 140,163 velas.

Este backtest no toca producción. Evalúa la hipótesis operativa:

`POI -> toque -> CDC -> liquidez objetivo -> trade`

Costos netos: comisión/slippage del motor `engine.simulate`. Bruto: la misma lógica con costos en cero.

## Resumen

| variante | seleccionados | trades | WR | expR neta | PF neto | totalR neto | expR bruto | PF bruto | DD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| liq_rr2 | 874 | 605 | 26.8% | -0.129 | 0.86 | -78.07 | 0.11 | 1.15 | 100.57 |
| cdc_liq | 390 | 272 | 44.9% | 0.7 | 1.99 | 190.38 | 0.923 | 2.7 | 13.49 |
| range_cdc_liq | 245 | 176 | 44.3% | 0.626 | 1.88 | 110.22 | 0.85 | 2.56 | 11.69 |
| visual_score7 | 587 | 410 | 30.7% | 0.087 | 1.1 | 35.69 | 0.313 | 1.46 | 38.46 |

## In-sample / Out-of-sample

Split: `2025-03-30 00:00` UTC.

| variante | split | seleccionados | trades | WR | expR | PF | totalR | DD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| liq_rr2 | in_sample_until_2025_03_30 | 522 | 373 | 26.3% | -0.208 | 0.78 | -77.55 | 85.07 |
| liq_rr2 | out_sample_from_2025_03_30 | 352 | 232 | 27.6% | -0.002 | 1.0 | -0.53 | 26.34 |
| cdc_liq | in_sample_until_2025_03_30 | 230 | 166 | 42.8% | 0.476 | 1.66 | 79.03 | 11.79 |
| cdc_liq | out_sample_from_2025_03_30 | 160 | 106 | 48.1% | 1.05 | 2.55 | 111.34 | 9.76 |
| range_cdc_liq | in_sample_until_2025_03_30 | 151 | 110 | 44.5% | 0.499 | 1.7 | 54.85 | 9.81 |
| range_cdc_liq | out_sample_from_2025_03_30 | 94 | 66 | 43.9% | 0.839 | 2.16 | 55.37 | 10.34 |
| visual_score7 | in_sample_until_2025_03_30 | 349 | 251 | 29.9% | -0.043 | 0.95 | -10.68 | 26.16 |
| visual_score7 | out_sample_from_2025_03_30 | 238 | 159 | 32.1% | 0.292 | 1.33 | 46.36 | 17.07 |

## Estabilidad Por Año

| año | liq_rr2 trades | liq_rr2 expR | liq_rr2 PF | cdc_liq trades | cdc_liq expR | cdc_liq PF | range_cdc_liq trades | range_cdc_liq expR | range_cdc_liq PF | visual_score7 trades | visual_score7 expR | visual_score7 PF |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2022 | 48 | 0.004 | 1.01 | 18 | 1.346 | 4.25 | 13 | 1.009 | 3.12 | 26 | 0.333 | 1.48 |
| 2023 | 111 | -0.072 | 0.92 | 56 | 0.425 | 1.57 | 41 | 0.388 | 1.53 | 84 | -0.114 | 0.87 |
| 2024 | 179 | -0.307 | 0.68 | 76 | 0.401 | 1.53 | 44 | 0.567 | 1.8 | 116 | -0.038 | 0.96 |
| 2025 | 194 | -0.058 | 0.94 | 91 | 0.87 | 2.14 | 56 | 0.743 | 1.95 | 134 | 0.275 | 1.31 |
| 2026 | 73 | -0.054 | 0.94 | 31 | 1.053 | 2.99 | 22 | 0.663 | 2.02 | 50 | 0.083 | 1.1 |

## Lectura

- `liq_rr2` prueba que no basta tener liquidez objetivo: sin CDC el resultado neto sigue negativo.
- `cdc_liq` es el núcleo más fuerte: reduce frecuencia, sube winrate y mejora PF.
- `range_cdc_liq` agrega premium/discount del rango reciente; baja frecuencia y mantiene edge, aunque no supera a `cdc_liq` en expectativa total.
- `visual_score7` todavía mezcla demasiados casos; sirve como ranking, no como gatillo principal.

## Próximo paso recomendado

El candidato para implementar primero en modo paper es `cdc_liq`: POI tocado, CDC dentro de ventana corta y RR hacia liquidez >= 2. Luego se prueba si `range_cdc_liq` mejora la calidad en vivo sin matar demasiadas oportunidades.
