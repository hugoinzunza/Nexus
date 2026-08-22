# Auditoría Acciones Chile — 2026-08-22

**Auditor:** Claude Opus, rol consultivo  
**Veredicto recibido:** bloqueado en capa de datos; fronteras de seguridad sostenidas  
**Decisión del owner:** corregir bloqueos y conservar `can_train=false`

## Evidencia validada

- Sin endpoints de órdenes ni credenciales Renta 4.
- Sin imports desde cripto o ejecutores.
- Cartera ausente del snapshot de auditoría.
- Telegram usa la fecha UTC del mensaje como disponibilidad causal.
- Cache preservado ante fallo y escrituras atómicas.

## Cierres implementados

| Hallazgo | Estado | Cierre |
|---|---|---|
| B1 horizontes mezclados | cerrado como riesgo de consumo | `months_covered`, `periods_behind`, `stale`, advertencia API y `cross_section_comparable=false` |
| B2 utilidad operacional vacía | cerrado | alias real plural validado con fixture CMF; cobertura observada 99,74% |
| B3 CMF sin `available_at` | cerrado para features | dataset fundamental marcado `forbidden`; join CMF↔Telegram produce candidatos solo con `available_at` |
| B4 Telegram rodante | en cierre | fusión acumulativa por `message_id`, backfill incremental, `oldest_message_id` y `window_truncated` |
| B5 endpoints personales públicos | cerrado | módulo detrás de sesión, cartera por `uid`, eventos exigen usuario |
| A1 procedencia incompleta | cerrado | URL con query, timestamp, HTTP status, bytes, Content-Length cuando existe y crudo gzip persistido |
| A2 completitud | cerrado como detección | `completeness_ratio_yoy`; 202606 marcado parcial (18,62%) |
| A3 gate global | cerrado | deduplicación empresa–trimestre y mínimo de trimestres medido por empresa |
| A5 emisores rancios | cerrado | `stale` y exclusión por defecto de `api/issuers` |
| A6 scope ambiguo | cerrado | selección consolidada explícita, scopes disponibles conservados |
| M1 duplicados | cerrado | `distinct_observations` separado de mensajes brutos |
| M2 joins silenciosos | cerrado | reporte explícito de empresas no mapeadas |
| M3 errores auditor | cerrado | error estructurado y salida fail-closed |

## Bloqueos vigentes

1. Fuente y cobertura separada para bancos listados.
2. Universo IPSA/ticker↔RUT versionado.
3. Backfill Telegram completo sin vulnerar la condición de uso personal.
4. Ocho trimestres por empresa, no globales.
5. Precios ajustados y benchmark IPSA con uso compatible.

El predictor y las señales permanecen deshabilitados hasta cerrar todos los
bloqueos relevantes y realizar una nueva auditoría independiente.
