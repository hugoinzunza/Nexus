# Backlog técnico Nexux - BTA visual

Fecha: 2026-07-01.

Objetivo: convertir el estudio BTA/TradingView en trabajo técnico ordenado para Nexux, sin tocar producción antes de validar la evidencia visual faltante.

## Regla de entrada

No llevar a bot vivo hasta cumplir:

- capturas limpias independientes de 2025;
- al menos una muestra 2024 confiable o documentación de ausencia de anotaciones;
- inventario actualizado;
- paquete verificado con `errors=0`.

## Prioridad P0 - Mantener en research

### BTA-001 - Consolidar `CDC + liquidez` como filtro base

Evidencia:

- POI + liquidez RR>=2: `605` trades, `26.8%` WR, `-0.129R`, PF `0.86`.
- POI + CDC + liquidez: `272` trades, `44.9%` WR, `+0.700R`, PF `1.99`.

Trabajo:

- Mantener `bta_visual_backtest.py` como benchmark.
- Separar métricas por año, sesión, fuente del POI y régimen.
- Agregar muestra fuera de entrenamiento cuando existan datos/capturas limpias.

Criterio de aceptación:

- El reporte distingue POI plano, liquidez, CDC+liquidez y rango+CDC+liquidez.
- El filtro no se promociona a producción sin validar 2025/2024 visual.

### BTA-002 - Completar capturas limpias TradingView

Evidencia:

- Las capturas antiguas `2025-04-16`, `2025-08-01`, `2025-11-05` quedaron repetidas o casi iguales.

Trabajo:

- Seguir `bta_tradingview_renavigation_protocol_2026-07-01.md`.
- Capturar los archivos definidos en `bta_clean_capture_checklist_2026-07-01.md`.
- Ejecutar `bta_clean_capture_ingest.py`.

Criterio de aceptación:

- `bta_clean_capture_coverage_2026-07-01.md` muestra al menos las tres capturas 2025 de alta prioridad como existentes.
- Las nuevas capturas no son duplicadas visuales.

## Prioridad P1 - Modelo estructural

### BTA-003 - `Zone.state`

Problema:

Nexux trata zonas como señales demasiado pronto. BTA separa pendiente, toque, CDC, reacción, fallo, retest y target.

Trabajo:

- Evolucionar `research/bta_visual_model.py`.
- Estados mínimos:
  - `pending`
  - `tapped`
  - `confirmed`
  - `failed`
  - `retest_continuation`
  - `target_hit`

Criterio de aceptación:

- Tests cubren `pending -> tapped -> confirmed`.
- Tests cubren `failed -> retest_continuation` sólo en vela posterior.
- Reporte explica el estado de cada zona candidata.

### BTA-004 - `CharacterLevel` persistente

Problema:

El CDC no debería ser sólo un check posterior. Debe vivir como nivel con estado.

Trabajo:

- Persistir CDC como objeto:
  - `pending`
  - `broken`
  - `respected`
  - `reclaimed`
  - `invalidated`
- Vincular `Zone.cdc_level_id`.

Criterio de aceptación:

- Una zona `requires_cdc=True` no genera setup válido sin CDC.
- Si CDC se pierde contra la idea, el setup queda `skip` o `invalidated`.

### BTA-005 - `RangeMap` visual/mejorado

Problema:

El rango mecánico de 7 días ayudó, pero no necesariamente replica el rango visual del profe.

Trabajo:

- Comparar rango por:
  - ventana fija;
  - pivotes PIV10/PIV20;
  - swing HTF;
  - último impulso-distribución.
- Medir contra casos de junio/mayo 2026.

Criterio de aceptación:

- El rango elegido reproduce mejor las capturas fuertes que una ventana fija.
- El reporte muestra cuándo una entrada está en premium, discount o equilibrium.

### BTA-006 - `SwingLeg`

Problema:

Nexux tiene pivotes, pero no leg activa comparable al zigzag del profe.

Trabajo:

- Conectar pivotes confirmados en legs.
- Marcar dirección, EQ, invalidación y targets.
- Usar leg para filtrar setups contra estructura dominante.

Criterio de aceptación:

- El modelo puede explicar “alineado con leg” o “contra leg”.
- La capa se valida con capturas limpias, especialmente 2025.

## Prioridad P2 - Objetos visuales y explicación

### BTA-007 - `ReferenceLevel`

Objetos:

- `Alto Referencial`
- `Strong High`
- niveles celestes/rojos/azules

Trabajo:

- Tratar estos niveles como objetivos, invalidaciones o referencias intermedias.

Criterio de aceptación:

- Un setup puede declarar: target, invalidación y resistencia/soporte de referencia.

### BTA-008 - `TargetZone`

Problema:

La caja naranja/celeste de llegada no existe en Nexux.

Trabajo:

- Modelar zonas de llegada como `TargetZone`.
- Relacionarlas con `Zone.state=target_hit`.

Criterio de aceptación:

- Caso `2026-05-27` queda explicado como continuación hacia target, no sólo como POI.

### BTA-009 - Explicaciones legibles

Trabajo:

- Generar explicación por setup:

```text
Discount POI + CDC confirmado + liquidez weak low/high + RR>=2 -> valid
```

o:

```text
Zona perdida -> retest -> continuación -> target zone
```

Criterio de aceptación:

- Cada candidato tiene `decision`, `score`, `reasons` y `missing_requirements`.

## Prioridad P3 - Integración controlada

### BTA-010 - Mover de research a módulo real

Condición previa:

- Capturas limpias 2025/2024.
- Backtest fuera de muestra aceptable.
- Revisión manual de Hugo.

Trabajo:

- Migrar de `research/bta_visual_model.py` a `modules/trading/bta_visual.py`.
- Agregar tests bajo `tests/`.
- No activar alertas por defecto.

Criterio de aceptación:

- Tests pasan.
- No cambia comportamiento del bot vivo sin flag.
- Las señales se exponen primero como observación/diagnóstico.

## Decisión recomendada

Siguiente paso real:

1. Limpiar/re-navegar TradingView si Hugo autoriza.
2. Completar capturas limpias 2025/2024.
3. Recalibrar `RangeMap` y `SwingLeg`.
4. Recién después decidir integración controlada.
