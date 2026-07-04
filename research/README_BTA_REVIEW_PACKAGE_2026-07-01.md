# README paquete BTA Review

Fecha: 2026-07-01.

Este paquete resume el estudio del TradingView del profe en `BTCUSDT.P M15` y la comparación contra Nexux.

## Abrir primero

1. Reporte HTML:
   - `/Users/hugh/crisol/nexux/research/bta_morning_review_2026-07-01.html`
2. Agenda de decisiones:
   - `/Users/hugh/crisol/nexux/research/bta_morning_review_agenda_2026-07-01.md`
3. Estado corto:
   - `/Users/hugh/crisol/nexux/research/bta_morning_status_2026-07-01.md`
4. Playbook operativo:
   - `/Users/hugh/crisol/nexux/research/bta_operational_playbook_2026-07-01.md`
5. Atlas histórico para re-navegar:
   - `/Users/hugh/crisol/nexux/research/bta_historical_navigation_atlas_2026-07-01.md`
6. Checklist priorizada de recaptura:
   - `/Users/hugh/crisol/nexux/research/bta_recapture_priority_checklist_2026-07-01.md`
7. Log de resultados de recaptura:
   - `/Users/hugh/crisol/nexux/research/bta_recapture_results_log_2026-07-01.md`
8. Auditoría final de completitud:
   - `/Users/hugh/crisol/nexux/research/bta_final_completion_audit_2026-07-01.md`

## Hallazgo principal

La lectura visible del profe no es “tocar cualquier OB/FVG”. La secuencia observada es:

```text
rango -> premium/discount -> POI -> CDC -> reacción -> liquidez objetivo -> estado de zona
```

Backtest de control:

- POI + liquidez RR>=2: `605` trades, `26.8%` WR, `-0.129R`, PF `0.86`.
- POI + CDC + liquidez: `272` trades, `44.9%` WR, `+0.700R`, PF `1.99`.

## Corrección importante

Las capturas antiguas `2025-04-16`, `2025-08-01` y `2025-11-05` quedaron visualmente iguales o muy parecidas. No cuentan como tres muestras históricas independientes. Sirven sólo como evidencia de que existe una capa zigzag/swing.

## Estado de la misión

El paquete de revisión está listo, pero la misión no está completa.

Estado de completitud:

- `/Users/hugh/crisol/nexux/research/bta_goal_completion_status_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_goal_completion_checklist_2026-07-01.json`

Falta:

1. autorización para limpiar o recargar el chart de TradingView;
2. re-navegar visualmente 2025 y 2024;
3. capturar escenas independientes;
4. actualizar inventario y contact sheet limpia.

## Verificación

Para comprobar integridad:

```bash
python3 /Users/hugh/crisol/nexux/research/bta_verify_package.py
```

Resultado esperado:

```text
errors=0
```

## ZIP portátil

Archivo:

```text
/Users/hugh/crisol/nexux/research/bta_review_package_2026-07-01.zip
```

Regenerar ZIP:

```bash
python3 /Users/hugh/crisol/nexux/research/bta_package_zip.py
```

## Para completar la parte visual pendiente

Abrir:

- `/Users/hugh/crisol/nexux/research/bta_tradingview_renavigation_protocol_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_checklist_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_live_renavigation_notes_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_live_capture_inventory_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_recapture_priority_checklist_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_recapture_results_log_2026-07-01.md`

Guardar nuevas capturas en:

```text
/Users/hugh/crisol/nexux/research/tradingview_bta_screenshots_clean_2026-07-01/
```

Después correr:

```bash
python3 /Users/hugh/crisol/nexux/research/bta_clean_capture_ingest.py
python3 /Users/hugh/crisol/nexux/research/bta_package_manifest.py
python3 /Users/hugh/crisol/nexux/research/bta_package_zip.py
python3 /Users/hugh/crisol/nexux/research/bta_verify_package.py
```
