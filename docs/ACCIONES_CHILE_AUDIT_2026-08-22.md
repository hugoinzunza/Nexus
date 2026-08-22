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
| B4 Telegram rodante | cerrado | backfill hasta `message_id=1`, 1.978 eventos fusionados y `window_truncated=false` |
| B5 endpoints personales públicos | cerrado | módulo detrás de sesión, cartera por `uid`, eventos exigen usuario |
| A1 procedencia incompleta | cerrado | URL con query, timestamp, HTTP status, bytes, Content-Length cuando existe y crudo gzip persistido |
| A2 completitud | cerrado como detección | `completeness_ratio_yoy`; 202606 marcado parcial (18,62%) |
| A3 gate global | cerrado | deduplicación empresa–trimestre y mínimo de trimestres medido por empresa |
| A5 emisores rancios | cerrado | `stale` y exclusión por defecto de `api/issuers` |
| A6 scope ambiguo | cerrado | selección consolidada explícita, scopes disponibles conservados |
| M1 duplicados | cerrado | `distinct_observations` separado de mensajes brutos |
| M2 joins silenciosos | cerrado | reporte explícito de empresas no mapeadas |
| M3 errores auditor | cerrado | error estructurado y salida fail-closed |
| M7 ticker↔RUT ausente | en cierre | top 10 público con RUT/DV; lista completa local/licenciada e historia pendientes |
| Precios sin contrato | cerrado como frontera | importador exige licencia, ajuste total-return, timestamps y benchmark alineado; no scrapea producto pagado |
| CMF sólo último período | cerrado | seis cierres disponibles, 2.121 observaciones históricas y 460 joins causales con Telegram |

## Bloqueos vigentes

1. Fuente y cobertura separada para bancos listados.
2. Importar localmente el universo IPSA completo autorizado; los cambios públicos 2024–2026 ya están registrados.
3. Esperar u obtener una fuente autorizada adicional para ocho trimestres por empresa; Telegram sólo contiene siete períodos.
4. Adquirir o autorizar precios ajustados y benchmark IPSA, y validarlos con el nuevo contrato.

El predictor y las señales permanecen deshabilitados hasta cerrar todos los
bloqueos relevantes y realizar una nueva auditoría independiente.
