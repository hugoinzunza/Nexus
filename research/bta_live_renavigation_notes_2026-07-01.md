# Re-navegación en vivo TradingView - BTA

Fecha: 2026-07-01.

Fuente: Chrome, pestaña existente `https://es.tradingview.com/chart/c07zDMmj/`, layout `Bitcoin Traders Academy`, símbolo `BTCUSDT.P`, temporalidad `15m`.

## Estado

Se logró volver a reclamar la pestaña real de TradingView y guardar capturas nuevas sin recargar ni escribir en el chart.

Limitación importante: el chart sigue con cambios no guardados y con el texto accidental `2026-06-17` visible sobre la zona de junio. No se aceptó recarga ni descarte de cambios.

## Capturas útiles nuevas

Carpeta:

```text
/Users/hugh/crisol/nexux/research/tradingview_bta_screenshots_clean_2026-07-01/
```

Láminas de control:

- `live_capture_contact_sheet_2026-07-01.jpg`
- `live_back_autoscale_contact_sheet_2026-07-01.jpg`
- `live_drag_history_contact_sheet_2026-07-01.jpg`

Capturas con evidencia visual útil o parcialmente útil:

- `live_2026-07-01_current_jun_range.png`: junio 2026, mapa completo con `Premium POI`, `Discount POI x confirmación`, `CDC`, `Strong High`, `Máximo`, `Mínimo` y zona azul de reacción.
- `live_pan_test_after_scrollX_negative.png`: junio 2026, trade box visible con objetivo, stop, cierre PyG, ratio riesgo/beneficio, CDC, pivotes celestes, línea diagonal roja y checkmarks verdes.
- `live_zoom_test_scrollY_positive.png`: mismo contexto del trade box; confirma que el scroll vertical no cambió escala pero conserva la evidencia del setup.
- `live_autoscale_after_blank_windows.png`: febrero 2026, tramo bajista con pivotes celestes, máximo/mínimo naranja y zona horizontal superior.
- `live_reverse_from_blank_test.png`: enero 2026, recuperación de candles desde el margen blanco; evidencia de movimiento histórico sin anotaciones fuertes.
- `live_drag_right_test.png`: enero 2026, rango intradía con máximo/mínimo naranja.
- `live_back_autoscale_2026_to_2025_01.png` a `live_back_autoscale_2026_to_2025_04.png`: enero/diciembre 2025-2026, primeras capturas del recorrido autoscalado. La `04` muestra zigzag morado, pivotes celestes y estructura tipo swing.
- `live_drag_history_2026_2025_01.png`: diciembre 2025, vuelve a mostrar zigzag morado y pivotes celestes.

## Capturas descartables o débiles

Las siguientes series tienen muchas pantallas de margen blanco/proyección o muy poca información de precio:

- `live_back_2026_jun_may_window_01.png` a `08.png`: viajaron a mayo/abril/febrero 2026, pero antes del autoscale muchas zonas quedaron fuera de pantalla.
- `live_back_autoscale_2026_to_2025_05.png` a `24.png`: se quedaron en margen blanco alrededor de noviembre 2025.
- `live_drag_history_2026_2025_02.png` a `24.png`: repiten el margen blanco de noviembre 2025; no sirven como evidencia histórica independiente.
- `live_after_wait_for_history_load.png`: esperar no cargó más datos útiles desde el margen blanco.

## Lectura agregada

La re-navegación en vivo refuerza dos capas del profe:

1. Setup con trade box:
   - el chart no sólo marca POI/CDC, también deja objetivo, stop, ratio y cierre PyG;
   - los checkmarks verdes validan reacción o cumplimiento;
   - la línea diagonal roja y los pivotes celestes conectan la operación con estructura.
2. Capa swing:
   - las capturas de diciembre 2025 muestran zigzag morado y pivotes celestes;
   - esta capa confirma que el profe decide POI dentro de una lectura de legs, no como zona aislada.

## Obstáculo actual

La navegación manual por pan/drag funciona sólo por tramos cortos. Al intentar recorrer muchos meses, TradingView cae en margen blanco/proyección y deja de mostrar candles útiles. El método seguro pendiente es:

1. recargar/limpiar el chart con autorización expresa;
2. usar una forma controlada de `Ir a fecha` o el calendario/time axis sin escribir sobre el canvas;
3. capturar 2025 y 2024 por ventanas independientes;
4. rearmar contact sheet e inventario sólo con capturas no blancas.

## Estado frente a la misión

Progreso real: sí. Se capturaron nuevas zonas y se confirmó directamente que el chart contiene trade boxes, zigzag/pivotes, CDC, premium/discount y liquidez.

Completo: no. Aún falta el recorrido multi-año limpio que pidió el usuario.
