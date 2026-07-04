# Brief mañana - estudio BTA TradingView vs Nexux

Fecha: 2026-07-01. Estado: preparado para revisión.

Índice de revisión:

- `/Users/hugh/crisol/nexux/research/bta_review_index_2026-07-01.md`

README del paquete:

- `/Users/hugh/crisol/nexux/research/README_BTA_REVIEW_PACKAGE_2026-07-01.md`

Reporte HTML local:

- `/Users/hugh/crisol/nexux/research/bta_morning_review_2026-07-01.html`

Agenda de revisión:

- `/Users/hugh/crisol/nexux/research/bta_morning_review_agenda_2026-07-01.md`

Playbook operativo:

- `/Users/hugh/crisol/nexux/research/bta_operational_playbook_2026-07-01.md`

Manifiesto/verificación del paquete:

- `/Users/hugh/crisol/nexux/research/bta_package_manifest_2026-07-01.md`
- `python3 /Users/hugh/crisol/nexux/research/bta_verify_package.py`
- `/Users/hugh/crisol/nexux/research/bta_review_package_2026-07-01.zip`

Atlas histórico para re-navegar:

- `/Users/hugh/crisol/nexux/research/bta_historical_navigation_atlas_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_recapture_priority_checklist_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_recapture_results_log_2026-07-01.md`

Protocolo para completar la navegación visual:

- `/Users/hugh/crisol/nexux/research/bta_tradingview_renavigation_protocol_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_checklist_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_ingest.py`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_coverage_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_live_renavigation_notes_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_live_capture_inventory_2026-07-01.md`

Auditoría de cobertura de la misión:

- `/Users/hugh/crisol/nexux/research/bta_goal_completion_audit_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_goal_completion_status_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_goal_completion_checklist_2026-07-01.json`
- `/Users/hugh/crisol/nexux/research/bta_final_completion_audit_2026-07-01.md`

## Veredicto corto

La primera pasada no fue suficientemente prolija; la auditoría válida empezó cuando se hizo zoom-out real en el TradingView del profe. Ahí quedó claro que la estrategia visible no es “operar cualquier OB/FVG”, sino una lectura por capas:

1. rango operativo;
2. premium/discount;
3. POI ubicado en la mitad correcta del rango;
4. CDC como frontera de confirmación/invalidez;
5. reacción/desplazamiento;
6. liquidez objetivo;
7. estructura swing/zigzag para no leer zonas aisladas.

Nexux hoy cubre partes de esa lógica, pero todavía no replica bien el estado visual de las zonas ni la capa de legs/pivotes que se ve en el chart.

## Evidencia visual fuerte

Fuente: TradingView abierto en Chrome, layout `Bitcoin Traders Academy`, `BTCUSDT.P`, `15m`.

Carpeta de capturas:

- `/Users/hugh/crisol/nexux/research/tradingview_bta_screenshots_2026-06-30/`

Lámina de capturas:

- `/Users/hugh/crisol/nexux/research/tradingview_bta_contact_sheet_2026-07-01.jpg`

Capturas más útiles:

- `2026-06-24_discount_poi_confirmacion.jpg`
- `2026-06-17_blue_range_premium_discount.jpg`
- `2026-06-11_premium_discount_check.jpg`
- `2026-05-27_drop_to_orange_target.jpg`
- `2026-05-15_discount_cdc_zones.jpg`
- `2025-11-05_zigzag_structure.jpg`

Elementos observados directamente:

- `Premium POI`
- `Premium POI X Confirmación`
- `Discount POI`
- `Discount POI x confirmación`
- `counter POI`
- `CDC`
- `Alto Referencial (Resistencia)`
- `Strong High (Nivel De Resistencia)`
- checks verdes de validación
- franjas verticales azules de reacción/desplazamiento
- zonas grises, celestes y naranjas
- pivotes celestes y zigzag morado
- máximos/mínimos naranjas

## Casos principales

### Junio 2026

El tramo `2026-06-17` a `2026-06-24` es el caso más valioso. Se ve mapa grande premium/discount, `Premium POI X Confirmación`, `counter POI`, `Discount POI`, `Discount POI x confirmación`, `CDC`, `Strong High` y mínimo operativo.

Datos cruzados con BTCUSDT perpetual M15:

- `2026-06-17`: rango `67.255 -> 60.193`, movimiento de ventana `11.73%`; desde el centro del caso, 24h después tuvo máximo `+0.92%` y mínimo `-5.44%`.
- `2026-06-24`: rango `66.419 -> 57.758`, movimiento de ventana `14.99%`; desde el centro del caso, 24h después tuvo máximo `+2.38%` y mínimo `-4.07%`.

Lectura: el profe estaba marcando un mapa de distribución/continuación bajista, no sólo una entrada puntual. Las zonas sirvieron para ordenar expectativa, invalidación y target de liquidez.

### Mayo 2026

Los casos `2026-05-15` y `2026-05-27` muestran continuación bajista después de perder CDC/zona. Las zonas celestes parecen funcionar como referencias intermedias, retests o targets parciales.

Datos:

- `2026-05-15`: rango `82.460 -> 76.014`, movimiento de ventana `8.48%`; desde el centro, 72h después llegó a `-3.97%`.
- `2026-05-27`: rango `78.180 -> 65.359`, movimiento de ventana `19.62%`; desde el centro, 24h después llegó a `-3.60%`.

Lectura: cuando se pierde el CDC, la zona no queda “muerta”; puede cambiar de rol y convertirse en retest de continuación.

### Capa zigzag / estructura

La captura `2025-11-05` muestra la capa que más le falta a Nexux: zigzag morado, pivotes celestes, flechas y mediciones tipo `0/1`.

Datos cuantitativos de referencia para el caso buscado:

- rango `111.250 -> 98.944`, movimiento `12.44%`;
- desde el centro, 24h después tuvo máximo `+2.60%` y mínimo `-0.69%`.

Lectura: hay una lectura explícita de legs/swing que gobierna si un POI tiene sentido o no. Detectar FVG/OB sin esa capa deja demasiado ruido.

Advertencia: la lámina de capturas muestra que `2025-04-16`, `2025-08-01` y `2025-11-05` quedaron visualmente iguales o muy parecidas. Por eso sirven como evidencia de la existencia de la capa zigzag, pero no como tres muestras históricas independientes. Es obligatorio re-navegar esos tramos en el chart limpio.

La auditoría de similitud está en:

- `/Users/hugh/crisol/nexux/research/bta_screenshot_similarity_2026-07-01.md`

Resultado clave: `2025-04-16_liquidity_case.jpg` y `2025-11-05_zigzag_structure.jpg` son duplicados exactos por SHA-256.

### Re-navegación en vivo adicional

Después se volvió a reclamar la pestaña real de Chrome sin recargar ni escribir en el chart. Se guardaron capturas nuevas en:

- `/Users/hugh/crisol/nexux/research/tradingview_bta_screenshots_clean_2026-07-01/`

Inventario complementario:

- `/Users/hugh/crisol/nexux/research/bta_live_capture_inventory_2026-07-01.md`

Resultado: `63` PNG auditados, `7` capturas útiles independientes, `44` descartadas por margen blanco/proyección.

Lo nuevo útil:

- junio 2026 con trade box completo: objetivo, stop, cierre PyG, ratio, CDC, pivotes y checkmarks;
- febrero/enero 2026 con pivotes celestes y extremos operativos;
- diciembre 2025 con zigzag morado y pivotes celestes.

Esto mejora la evidencia, pero no cierra la misión multi-año porque no hay recorrido limpio suficiente de 2025/2024.

Para completar la re-navegación limpia, se generó un atlas de fechas candidatas desde Nexux/backtest:

- `339` candidatos `CDC + liquidez RR>=2 + riesgo <= 1.2%`;
- `88` objetivos mensuales 2024-2026;
- top prioritarios 2024/2025 para saltar directo en TradingView.

Ese atlas no cuenta como prueba visual; sólo reduce el recorrido manual cuando el chart esté limpio.

También quedó una checklist concreta de `32` capturas objetivo, con nombres de archivo sugeridos y criterios de aceptación.

La ingesta `bta_clean_capture_ingest.py` ahora valida esa checklist priorizada además del checklist manual. En la cobertura actual hay `0/32` capturas priorizadas confirmadas, porque todavía falta la pasada limpia por TradingView.

El log `bta_recapture_results_log_2026-07-01.json` queda preparado para marcar cada fecha como `confirmed`, `no_annotation`, `blank_projection`, `not_matching` o `needs_review`.

La cobertura limpia ya lee ese log y muestra los conteos por estado; hoy está `pending=29`, `not_matching=2`, `needs_review=1`, `confirmed=0`.

La sesión nueva quedó documentada en:

- `/Users/hugh/crisol/nexux/research/bta_recapture_session_2026-07-01.md`

## Resultado cuantitativo de control

Con datos locales BTC M15 2022-06-12 a 2026-06-11:

- POI simple con TP fijo 2R: `1488` trades, win rate `36.8%`, expectativa `-0.129R`, profit factor `0.83`, total `-191.44R`.
- POI con TP hacia liquidez y RR>=2: `605` trades, win rate `26.8%`, expectativa `-0.129R`, profit factor `0.86`, total `-78.07R`.

Conclusión: el edge no está en automatizar “toque a POI” en M15. El edge, si existe, está en la selectividad visual: contexto de rango, CDC, estado de zona, liquidez y estructura.

## Prototipo BTA visual

Se agregó un backtest separado que traduce la lectura visual a filtros auditables, sin tocar el bot vivo:

- `/Users/hugh/crisol/nexux/research/bta_visual_backtest.py`
- `/Users/hugh/crisol/nexux/research/bta_visual_backtest_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_visual_backtest_results.json`

Resultados principales:

| variante | seleccionados | trades | WR | expR | PF | totalR | DD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| liquidez RR>=2 | 874 | 605 | 26.8% | -0.129 | 0.86 | -78.07 | 100.57 |
| CDC + liquidez | 390 | 272 | 44.9% | 0.700 | 1.99 | 190.38 | 13.49 |
| rango + CDC + liquidez | 245 | 176 | 44.3% | 0.626 | 1.88 | 110.22 | 11.69 |
| score visual >= 6 | 730 | 504 | 29.2% | -0.007 | 0.99 | -3.60 | 60.01 |
| score visual >= 7 | 587 | 410 | 30.7% | 0.087 | 1.10 | 35.69 | 38.46 |

Lectura: el hallazgo más fuerte no es “más score”, sino `CDC + liquidez`. Eso coincide con el chart del profe: la zona sola no dispara; primero debe existir target de liquidez razonable y luego confirmación de carácter. El filtro de rango premium/discount baja frecuencia y drawdown, pero también baja total R; hay que calibrar mejor el rango para que se parezca más al rango visible/manual del profe.

## Brecha concreta contra Nexux

Nexux ya tiene:

- POI por barrido + displacement + FVG + premium/discount local;
- CDC posterior al toque;
- TP hacia liquidez opuesta no barrida;
- weak/strong highs/lows por pivotes.

Falta:

- `RangeMap`: máximo/mínimo operativo, EQ, premium, discount.
- `Zone.state`: pendiente, tocada, confirmada, fallida, retesteada, target hit.
- `CharacterLevel`: CDC con estado, no sólo detección posterior.
- `SwingLeg`: pivotes conectados y leg dominante.
- objetos explícitos `Alto Referencial`, `Strong High`, `Premium POI X Confirmación`, `Discount POI x confirmación`.
- explicación legible por setup: por qué la zona vale, qué la invalida y qué liquidez busca.

La matriz caso por caso está separada en:

- `/Users/hugh/crisol/nexux/research/bta_nexux_alignment_matrix_2026-07-01.md`

El catálogo operativo por captura/zona está en:

- `/Users/hugh/crisol/nexux/research/bta_visual_zone_catalog_2026-07-01.md`

El inventario estructurado y validado está en:

- `/Users/hugh/crisol/nexux/research/bta_visual_inventory_2026-07-01.json`
- `/Users/hugh/crisol/nexux/research/bta_visual_inventory_summary_2026-07-01.md`

El backlog técnico para Nexux está en:

- `/Users/hugh/crisol/nexux/research/bta_nexux_implementation_backlog_2026-07-01.md`

## Decisión técnica propuesta

No mezclar esto dentro del detector actual de POI. Crear una capa separada:

- `modules/trading/bta_visual.py`
- `research/bta_visual_backtest.py`
- `tests/test_bta_visual.py`

La especificación inicial está en:

- `/Users/hugh/crisol/nexux/research/bta_visual_model_spec_2026-07-01.md`

El objetivo no debe ser sólo subir win rate. Debe reducir frecuencia, mejorar PF/expectativa fuera de muestra y reproducir visualmente los casos de junio 2026, mayo 2026 y noviembre 2025.

Prototipo research creado:

- `/Users/hugh/crisol/nexux/research/bta_visual_model.py`
- `/Users/hugh/crisol/nexux/research/test_bta_visual_model.py`

Estado del prototipo: define `RangeMap`, `Zone`, `CharacterLevel`, `SwingLeg` y `SetupCandidate`; incluye checks básicos para rango, CDC, legs, estado `confirmed`, estado `failed -> retest_continuation` y candidato válido por RR/CDC. No está conectado al bot vivo.

## Limitación operativa

Hay que ser transparente: durante el intento de automatizar saltos por fecha, se pegó accidentalmente un texto `2026-06-17` sobre el chart. Intenté deshacer/borrar, pero Chrome mostró aviso de recarga por cambios no guardados. No acepté recargar para no descartar cambios tuyos sin permiso.

Para seguir navegando el TradingView prolijamente en la mañana conviene:

1. autorizar recarga del chart si quieres descartar cambios no guardados;
2. o borrar manualmente ese texto desde TradingView;
3. después re-navegar 2026 completo, 2025 por tramos y 2024 si el layout mantiene anotaciones históricas;
4. repetir especialmente `2025-04-16`, `2025-08-01` y `2025-11-05`, porque las capturas actuales no prueban esas fechas por separado.

## Archivos de trabajo

- `/Users/hugh/crisol/nexux/research/tradingview_bta_visual_audit_2026-06-30.md`
- `/Users/hugh/crisol/nexux/research/bta_overnight_mission_notes_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_visual_cases_data.json`
- `/Users/hugh/crisol/nexux/research/bta_m15_structure_2026-06-30.md`
- `/Users/hugh/crisol/nexux/research/bta_visual_model_spec_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_visual_backtest_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_nexux_alignment_matrix_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_visual_zone_catalog_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_visual_inventory_2026-07-01.json`
- `/Users/hugh/crisol/nexux/research/bta_visual_inventory_summary_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_screenshot_similarity_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_nexux_implementation_backlog_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_visual_model.py`
- `/Users/hugh/crisol/nexux/research/test_bta_visual_model.py`
- `/Users/hugh/crisol/nexux/research/bta_morning_review_2026-07-01.html`
- `/Users/hugh/crisol/nexux/research/bta_morning_html.py`
- `/Users/hugh/crisol/nexux/research/bta_morning_review_agenda_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/README_BTA_REVIEW_PACKAGE_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_package_manifest_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_verify_package.py`
- `/Users/hugh/crisol/nexux/research/bta_review_package_2026-07-01.zip`
- `/Users/hugh/crisol/nexux/research/bta_package_zip.py`
- `/Users/hugh/crisol/nexux/research/bta_tradingview_renavigation_protocol_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_checklist_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_checklist_2026-07-01.json`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_ingest.py`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_coverage_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_coverage_2026-07-01.json`
- `/Users/hugh/crisol/nexux/research/bta_review_index_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_goal_completion_audit_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/tradingview_bta_contact_sheet_2026-07-01.jpg`
