# Protocolo de re-navegación TradingView BTA

Fecha: 2026-07-01.

Objetivo: completar la parte faltante de la misión: recorrer historia visual real del chart del profe en `BTCUSDT.P M15`, con zoom-out, capturas independientes y catálogo actualizado.

## Principio de seguridad

No tocar el chart sin autorización explícita si TradingView muestra cambios no guardados.

Estado conocido:

- Existe o puede existir un texto accidental `2026-06-17` pegado sobre el chart.
- Chrome mostró aviso de recarga por cambios no guardados.
- No se aceptó recargar para evitar descartar cambios del usuario.

Antes de re-navegar:

1. Pedir autorización para recargar el chart o borrar manualmente el texto.
2. Si se autoriza recarga, aceptar el aviso sólo si Hugo confirma que se pueden descartar cambios no guardados del chart.
3. Si no se autoriza recarga, limpiar manualmente el objeto accidental desde TradingView antes de capturar.

## Configuración visual

- Símbolo: `BTCUSDT.P`.
- Temporalidad: `15m`.
- Layout: `Bitcoin Traders Academy`.
- Modo: preferir sólo lectura si está disponible.
- Zoom: alejar lo suficiente para ver zonas completas, no sólo velas individuales.
- Paneles: mantener visible la escala de precios y etiquetas de zonas.

## Qué capturar en cada tramo

Para cada fecha/tramo:

1. Una captura general con zoom-out del rango completo.
2. Una captura de la zona de decisión donde se lean etiquetas.
3. Una captura posterior con el outcome si cabe en pantalla.

Campos mínimos por captura:

- fecha objetivo;
- rango visible aproximado;
- etiquetas visibles: `Premium POI`, `Discount POI`, `CDC`, `Strong High`, `Alto Referencial`, etc.;
- dirección esperada o lectura dominante;
- liquidez objetivo;
- si hay check verde / ojos / franja azul;
- si la zona fue respetada, perdida o retesteada.

## Fechas prioritarias

### Alta prioridad: reemplazar capturas repetidas

| fecha | motivo | nombre sugerido |
| --- | --- | --- |
| `2025-04-16` | El backtest tiene trade destacado, pero la captura actual no prueba el chart visual. | `2025-04-16_clean_liquidity_case.jpg` |
| `2025-08-01` | Captura actual repetida/no independiente. | `2025-08-01_clean_structure_context.jpg` |
| `2025-11-05` | Capa zigzag relevante, pero debe recapturarse como escena independiente. | `2025-11-05_clean_zigzag_structure.jpg` |

### Media prioridad: ampliar muestra 2026

| tramo | motivo | nombre sugerido |
| --- | --- | --- |
| `2026-01-15` | Cluster de niveles no clasificado. | `2026-01-15_clean_level_cluster.jpg` |
| `2026-03` | Buscar POI/CDC antes de mayo. | `2026-03-clean_poi_cdc_sample.jpg` |
| `2026-04` | Buscar transición o rango previo a mayo. | `2026-04-clean_structure_sample.jpg` |
| `2026-06-11` | Ya hay evidencia fuerte; recapturar sólo si el chart queda limpio y fácil. | `2026-06-11_clean_premium_discount_check.jpg` |
| `2026-06-17` | Confirmar CDC y precios exactos. | `2026-06-17_clean_premium_discount_range.jpg` |
| `2026-06-24` | Confirmar `Discount POI x confirmación`. | `2026-06-24_clean_discount_confirmation.jpg` |

### Baja/media prioridad: 2024

Buscar al menos tres escenas:

- un caso de premium/discount con CDC;
- un caso de zona perdida -> retest -> continuación;
- un caso de zigzag/swing leg.

Nombres sugeridos:

- `2024-q1-clean_poi_cdc.jpg`
- `2024-q2-clean_retest_continuation.jpg`
- `2024-q3-clean_zigzag_structure.jpg`

## Nomenclatura

Usar:

```text
YYYY-MM-DD_clean_descripcion_corta.jpg
```

Evitar sobrescribir las capturas actuales. Guardar las nuevas en:

```text
/Users/hugh/crisol/nexux/research/tradingview_bta_screenshots_clean_2026-07-01/
```

## Criterio de aceptación por captura

Una captura cuenta como evidencia fuerte sólo si:

1. muestra fecha/tramo claramente reconocible;
2. no repite otra captura por error de navegación;
3. contiene al menos una etiqueta o zona visible;
4. permite inferir contexto antes/después o outcome;
5. queda registrada en `bta_visual_inventory_2026-07-01.json` o inventario nuevo.

## Actualización posterior

Después de capturar:

1. Crear/actualizar contact sheet limpia.
2. Agregar cada captura al inventario estructurado.
3. Marcar confianza: `high`, `medium_high`, `medium`, `low_medium`, `low`.
4. Re-ejecutar:

```bash
python3 /Users/hugh/crisol/nexux/research/bta_visual_inventory_summary.py
python3 /Users/hugh/crisol/nexux/research/bta_morning_html.py
python3 /Users/hugh/crisol/nexux/research/bta_package_manifest.py
python3 /Users/hugh/crisol/nexux/research/bta_verify_package.py
```

## Criterio para completar la misión

La misión se puede marcar como completa sólo si:

- se limpió o recargó el chart con autorización;
- hay capturas limpias independientes de 2025;
- hay al menos una muestra visual confiable de 2024 o se documenta que el layout no conserva anotaciones allí;
- el inventario incluye las nuevas capturas;
- el verificador del paquete pasa con `errors=0`.
