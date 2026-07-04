# Sesión de recaptura TradingView BTA

Fecha: 2026-07-01.

## Contexto

Se continuó desde Chrome en el chart:

```text
BTCUSDT.P · 15 · Binance
Bitcoin Traders Academy
https://es.tradingview.com/chart/c07zDMmj/
```

La temporalidad visible era `15`, es decir M15. Los `1h`/`4h` en nombres de archivos vienen del `source_tf` de candidatos Nexux, no del chart.

## Resultado

Se logró usar el modal `Ir a`, pero al pedir fechas antiguas el chart no aterrizó en la fecha solicitada. En ambos casos cayó en una zona de diciembre 2025 con el mensaje `Última barra disponible`.

## Intentos

### `2024-06-12 14:15`

Objetivo:

- `2024-06-12_1415_short_1h_bta_recapture.jpg`

Resultado:

- status: `not_matching`
- evidencia: `attempt_2024-06-12_1415_after_go_check.png`
- observación: el chart cayó en diciembre 2025, no en 2024.

### `2025-03-03 19:45`

Objetivo:

- `2025-03-03_1945_long_1h_bta_recapture.jpg`

Resultado:

- status: `not_matching`
- evidencia: `attempt_2025-03-03_1945_after_go_check.png`
- observación: volvió a caer en diciembre 2025 con `Última barra disponible`.

### `2025-12-29 10:45`

Objetivo:

- `2025-12-29_1045_long_1h_bta_recapture.jpg`

Resultado:

- status: `needs_review`
- evidencia: `2025-12-29_1045_long_1h_bta_recapture.jpg`
- observación: se ve zona morada, arco naranja, caída y `Mínimo`, pero no etiquetas `POI/CDC` suficientemente legibles para marcar `confirmed`.

## Lectura

El layout actual parece tener un límite de historia visual alrededor de diciembre 2025. Esto explica por qué los intentos de 2024 y marzo 2025 no producen capturas válidas. No basta para cerrar 2024/2025, pero sí documenta una limitación reproducible del chart actual.

## Próximo paso

Si se quiere cerrar el requisito multi-año, hace falta una de estas opciones:

1. encontrar una forma de cargar historia anterior a diciembre 2025 en el layout;
2. usar otra copia del layout del profe que tenga anotaciones antiguas;
3. documentar formalmente que el layout disponible no contiene historia visual anterior a diciembre 2025.
