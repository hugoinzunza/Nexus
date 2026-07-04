# Misión nocturna BTA - notas de trabajo

Estado: en progreso. Preparado para revisión de la mañana.

## Resumen honesto

La revisión inicial no fue prolija. La corrección importante fue hacer zoom-out real en el chart del profe: ahí aparecieron las zonas y anotaciones que no se veían en el paneo inicial. A partir de eso se guardaron capturas locales y se creó una auditoría visual más fiel.

También hubo un problema operativo: al intentar automatizar saltos por fecha con AppleScript, una fecha (`2026-06-17`) terminó pegada como texto sobre el chart. Intenté deshacer/borrar sin éxito. Chrome mostró aviso de recarga por cambios no guardados; no acepté recargar para no descartar posibles cambios tuyos sin confirmación. Por eso detuve la interacción con Chrome y seguí trabajando sobre capturas ya guardadas. En la mañana conviene limpiar eso manualmente o autorizar recarga del chart si quieres descartar cambios no guardados.

## Artefactos generados

- `research/README_BTA_REVIEW_PACKAGE_2026-07-01.md`
- `research/tradingview_bta_visual_audit_2026-06-30.md`
- `research/tradingview_bta_screenshots_2026-06-30/`
- `research/bta_visual_cases_data.py`
- `research/bta_visual_cases_data.json`
- `research/bta_fetch_btcusdtp_recent.py`
- `research/bta_btcusdtp_15m_recent.json`
- `research/bta_m15_structure_study.py`
- `research/bta_m15_structure_results.json`
- `research/bta_m15_structure_2026-06-30.md`
- `research/bta_visual_model_spec_2026-07-01.md`
- `research/bta_visual_backtest.py`
- `research/bta_visual_backtest_results.json`
- `research/bta_visual_backtest_2026-07-01.md`
- `research/bta_nexux_alignment_matrix_2026-07-01.md`
- `research/bta_nexux_implementation_backlog_2026-07-01.md`
- `research/bta_visual_zone_catalog_2026-07-01.md`
- `research/bta_screenshot_similarity.py`
- `research/bta_screenshot_similarity_2026-07-01.json`
- `research/bta_screenshot_similarity_2026-07-01.md`
- `research/bta_visual_inventory_2026-07-01.json`
- `research/bta_visual_inventory_summary.py`
- `research/bta_visual_inventory_summary_2026-07-01.md`
- `research/bta_visual_model.py`
- `research/test_bta_visual_model.py`
- `research/bta_morning_html.py`
- `research/bta_morning_review_2026-07-01.html`
- `research/bta_morning_review_agenda_2026-07-01.md`
- `research/bta_package_manifest.py`
- `research/bta_package_manifest_2026-07-01.json`
- `research/bta_package_manifest_2026-07-01.md`
- `research/bta_verify_package.py`
- `research/bta_package_zip.py`
- `research/bta_review_package_2026-07-01.zip`
- `research/bta_tradingview_renavigation_protocol_2026-07-01.md`
- `research/bta_clean_capture_checklist_2026-07-01.md`
- `research/bta_clean_capture_checklist_2026-07-01.json`
- `research/bta_clean_capture_ingest.py`
- `research/bta_clean_capture_coverage_2026-07-01.md`
- `research/bta_clean_capture_coverage_2026-07-01.json`
- `research/tradingview_bta_screenshots_clean_2026-07-01/`
- `research/bta_live_renavigation_notes_2026-07-01.md`
- `research/bta_live_capture_inventory.py`
- `research/bta_live_capture_inventory_2026-07-01.json`
- `research/bta_live_capture_inventory_2026-07-01.md`
- `research/bta_historical_navigation_atlas.py`
- `research/bta_historical_navigation_atlas_2026-07-01.json`
- `research/bta_historical_navigation_atlas_2026-07-01.md`
- `research/bta_recapture_priority_checklist.py`
- `research/bta_recapture_priority_checklist_2026-07-01.json`
- `research/bta_recapture_priority_checklist_2026-07-01.md`
- `research/bta_recapture_log_template.py`
- `research/bta_recapture_results_log_2026-07-01.json`
- `research/bta_recapture_results_log_2026-07-01.md`
- `research/bta_morning_brief_2026-07-01.md`
- `research/bta_review_index_2026-07-01.md`
- `research/bta_goal_completion_audit_2026-07-01.md`
- `research/bta_goal_completion_checklist_2026-07-01.json`
- `research/bta_goal_completion_status.py`
- `research/bta_goal_completion_status_2026-07-01.md`
- `research/bta_final_completion_audit_2026-07-01.md`
- `research/tradingview_bta_contact_sheet_2026-07-01.jpg`

## Evidencia visual fuerte

### Junio 2026, zona completa premium/discount

Capturas útiles:

- `2026-06-24_discount_poi_confirmacion.jpg`
- `2026-06-17_blue_range_premium_discount.jpg`
- `2026-06-11_premium_discount_check.jpg`

Elementos observados:

- `Premium POI`
- `Premium POI X Confirmación`
- `Discount POI`
- `Discount POI x confirmación`
- `counter POI`
- `CDC`
- `Alto Referencial (Resistencia)`
- `Strong High (Nivel De Resistencia)`
- checks verdes
- franjas verticales azules
- zonas grises de decisión
- máximos/mínimos naranjas
- niveles azules/rojos en el eje derecho

Lectura:

El profe no opera una caja aislada. Trabaja un mapa de rango: primero referencia superior/inferior, después POI premium/discount, luego CDC/confirmación y reacción. La zona cambia de rol según si el precio respeta o pierde el CDC.

Datos BTCUSDT.P futures agregados:

- Caso `2026-06-17`: rango de ventana `67.255 -> 60.193` (`11.73%`). Desde el centro del caso (`65.815`) el movimiento a 24h fue máximo `+0.92%` y mínimo `-5.44%`.
- Caso `2026-06-24`: rango de ventana `66.419 -> 57.758` (`14.99%`). Desde el centro del caso (`60.492`) el movimiento a 24h fue máximo `+2.38%` y mínimo `-4.07%`.
- Esto respalda la lectura visual: las zonas de premium/discount y CDC no eran decorativas; anticipaban un tramo de desplazamiento fuerte hacia liquidez baja.

### Mayo 2026, continuación bajista

Capturas útiles:

- `2026-05-27_drop_to_orange_target.jpg`
- `2026-05-15_discount_cdc_zones.jpg`

Elementos observados:

- zonas celestes horizontales
- `Discount POI`
- líneas `CDC`
- máximos/mínimos naranjas
- caja naranja de rango/objetivo
- caída por pérdida de estructura

Lectura:

Cuando el precio pierde una zona/CDC, los retests a POI funcionan como continuación. Las zonas celestes parecen actuar como soportes/resistencias intermedias o targets parciales.

### Capa swing/zigzag explícita

Captura útil, con cautela:

- `2025-11-05_zigzag_structure.jpg`

Elementos observados:

- zigzag morado entre pivotes
- círculos celestes en máximos/mínimos
- flechas de dirección
- líneas rojas horizontales de medición
- etiquetas tipo `0` y `1`

Lectura:

Esta capa no es simplemente POI/FVG. Es lectura de legs estructurales: pivote -> impulso -> retroceso -> siguiente pivote. Nexux no replica esta visualidad todavía.

Corrección tras revisar la contact sheet: `2025-04-16_liquidity_case.jpg`, `2025-08-01_structure_context.jpg` y `2025-11-05_zigzag_structure.jpg` quedaron visualmente iguales o muy parecidas. Sirven como evidencia de la capa zigzag, pero no como tres muestras históricas independientes.

Auditoría de similitud: `2025-04-16_liquidity_case.jpg` y `2025-11-05_zigzag_structure.jpg` son duplicados exactos por SHA-256; `2025-08-01_structure_context.jpg` queda como par visualmente similar y requiere re-navegación.

## Capturas no concluyentes

Algunas capturas guardadas después de saltos por fecha no muestran el tramo esperado o repiten contexto por estado del chart/zoom. No se deben usar como evidencia fuerte sin re-navegar manualmente.

Ejemplos a revisar de nuevo:

- `2026-01-15_level_cluster.jpg`
- `2025-11-05_zigzag_structure.jpg`
- `2025-08-01_structure_context.jpg`
- `2025-04-16_liquidity_case.jpg`

## Reglas inferidas del profe

1. Definir rango y extremos operativos (`Máximo`, `Mínimo`, `Alto Referencial`, `Strong High`).
2. Separar premium/discount.
3. Marcar POIs sólo dentro del contexto correcto, no todo OB.
4. Usar CDC como frontera de confirmación o invalidación.
5. Exigir reacción visible: checks, desplazamiento, rechazo o aceptación.
6. Tratar zonas perdidas como continuación en el retest.
7. Usar niveles celestes/rojos/azules como targets o referencias intermedias.
8. Superponer lectura swing/zigzag para no operar zonas contra la estructura dominante.

## Brecha contra Nexux

Nexux ya tiene:

- POI por barrido + FVG + displacement + premium/discount local.
- CDC posterior al toque.
- TP hacia liquidez opuesta no barrida.
- weak/strong highs/lows por pivotes.

Falta:

- Estado de zona: pendiente, validada, perdida, retesteada, convertida en continuación.
- Objetos explícitos `Alto Referencial`, `Strong High`, `Premium POI X Confirmación`, `Discount POI x confirmación`.
- Capa visual de zigzag/legs con pivotes celestes.
- Score de contexto: zona + CDC + estructura + liquidez, no señal plana.
- Catálogo histórico de zonas del profe por captura, con outcome manual.

## Backtest prototipo visual

Se creó un prototipo separado para no tocar el bot vivo. Traduce la lectura visual a filtros comparables:

- liquidez objetivo con RR>=2
- CDC dentro de ventana
- premium/discount de rango operativo reciente
- score visual por contexto

Resultado clave:

| variante | trades | WR | expR | PF | totalR | DD |
| --- | --- | --- | --- | --- | --- | --- |
| liquidez RR>=2 | 605 | 26.8% | -0.129 | 0.86 | -78.07 | 100.57 |
| CDC + liquidez | 272 | 44.9% | 0.700 | 1.99 | 190.38 | 13.49 |
| rango + CDC + liquidez | 176 | 44.3% | 0.626 | 1.88 | 110.22 | 11.69 |
| score visual >= 7 | 410 | 30.7% | 0.087 | 1.10 | 35.69 | 38.46 |

Lectura: el filtro que realmente aporta es `CDC + liquidez`. El score visual genérico todavía mezcla demasiado ruido; el rango debe calibrarse para parecerse más al rango manual visible del profe.

## Propuesta técnica para Nexux

Crear una capa `bta_visual_model` separada de `detect_pois`:

- `RangeMap`: extremos, EQ, premium, discount.
- `Zone`: tipo (`premium_poi`, `discount_poi`, `counter_poi`, `reference`, `target`), precio, fecha, estado.
- `CharacterLevel`: CDC y si fue respetado/perdido/recuperado.
- `SwingLeg`: pivotes conectados por zigzag, dirección, leg actual, invalidación.
- `ZoneOutcome`: reacción, desplazamiento, continuación, fallo.

Después se compara con el backtest existente:

- POI plano vs POI con estado visual.
- CDC inmediato vs CDC contextual.
- TP fijo vs target de liquidez visible.
- M15 aislado vs M15 como gatillo dentro de rango HTF.

## Pendiente para la mañana

1. Limpiar/recargar el chart de TradingView si autorizas descartar cambios no guardados.
2. Re-navegar manualmente desde el chart limpio con zoom-out: 2026 completo, 2025 por tramos, luego 2024 si el layout lo permite.
3. Hacer catálogo por zona: fecha, tipo, rango de precio, CDC, reacción, outcome.
4. Implementar prototipo `bta_visual_model` en Nexux usando esta taxonomía.

## Avance posterior de re-navegación en vivo

Se logró reclamar nuevamente la pestaña de Chrome y guardar capturas vivas sin recargar. El inventario complementario quedó en:

- `research/bta_live_capture_inventory_2026-07-01.md`

Resultado: 7 capturas útiles independientes, incluyendo trade box de junio 2026 y zigzag/pivotes de diciembre 2025. Aun así, TradingView cayó en margen blanco al panear meses completos; por eso el recorrido 2025/2024 sigue pendiente.

Para acelerar ese pendiente, se agregó un atlas histórico de candidatos `CDC + liquidez` con 339 fechas y 88 objetivos mensuales para revisar en TradingView limpio.

También se generó una checklist priorizada de 32 capturas objetivo con nombres de archivo y criterios de aceptación.
