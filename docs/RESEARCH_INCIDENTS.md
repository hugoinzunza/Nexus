# Incidencias independientes de research

## INC-RESEARCH-001 — Umbral del Diario 79,2% vs 80%

- Estado: abierto.
- Alcance: presentacion/criterio del Diario.
- Observacion: una lectura de 79,2% aparece en conflicto con un umbral mostrado
  como 80%.
- Evidencia reproducible: `research/test_comparar_salidas_vs_diario.py::test_los_cerrados_del_diario_usan_la_misma_regla_de_entrada_que_el_backtest`
  falla con `38/48 = 79,17%` porque el guard exige estrictamente `> 0.8`.
- Suite al registrar la incidencia: 871 pruebas aprobadas y este unico fallo.
- Decision: no corregir dentro de HYP-EXIT-003-SHADOW ni HYP-COST-001.
- Motivo: separar mantenimiento del Diario de la instrumentacion y los estudios
  pre-registrados.
- Impacto sobre los estudios: ninguno; no se usa este indicador como entrada,
  filtro, resultado ni criterio de promocion.
