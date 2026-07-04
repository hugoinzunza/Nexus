# Checklist capturas limpias TradingView BTA

Estado: pendiente de limpiar/recargar chart con autorización.

Carpeta destino:

```text
/Users/hugh/crisol/nexux/research/tradingview_bta_screenshots_clean_2026-07-01/
```

## Alta prioridad

| hecho | fecha | archivo | objetivo |
| --- | --- | --- | --- |
| [ ] | `2025-04-16` | `2025-04-16_clean_liquidity_case.jpg` | Reemplazar captura no independiente; validar candidato de backtest y liquidez. |
| [ ] | `2025-08-01` | `2025-08-01_clean_structure_context.jpg` | Reemplazar captura repetida; buscar estructura/POI/CDC. |
| [ ] | `2025-11-05` | `2025-11-05_clean_zigzag_structure.jpg` | Recapturar capa zigzag como escena independiente. |

## Media prioridad

| hecho | fecha | archivo | objetivo |
| --- | --- | --- | --- |
| [ ] | `2026-01-15` | `2026-01-15_clean_level_cluster.jpg` | Clasificar cluster de niveles. |
| [ ] | `2026-03` | `2026-03_clean_poi_cdc_sample.jpg` | Ampliar muestra 2026 antes de mayo. |
| [ ] | `2026-04` | `2026-04_clean_structure_sample.jpg` | Buscar estructura/rango/liquidez. |
| [ ] | `2024` | `2024-qx_clean_three_examples.jpg` | Conseguir evidencia visual 2024 o documentar ausencia. |

## Criterios

Cada captura debe:

- mostrar un rango con zoom-out suficiente;
- tener etiquetas/zonas legibles cuando existan;
- no repetir otra captura por error de navegación;
- incluir contexto y outcome si cabe;
- quedar registrada en inventario después.

## Comandos tras capturar

```bash
python3 /Users/hugh/crisol/nexux/research/bta_visual_inventory_summary.py
python3 /Users/hugh/crisol/nexux/research/bta_morning_html.py
python3 /Users/hugh/crisol/nexux/research/bta_package_manifest.py
python3 /Users/hugh/crisol/nexux/research/bta_verify_package.py
```
