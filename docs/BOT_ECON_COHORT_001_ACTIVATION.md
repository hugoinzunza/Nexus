# ECON-COHORT-001 — Acta de activacion

## Estado

- Release desplegado: `006fb3051fdd74b225c92c9c3b28fdb70313e144`.
- Rama: `codex/bot-econ-release`.
- Inicio elegible pre-registrado: `2026-08-15 04:30:00 UTC`.
- Cierre: 50 operaciones elegibles cerradas o `2026-10-10 04:30:00 UTC`, lo
  primero que ocurra.
- Evaluacion: una sola vez al cierre.
- `live:false`; `automatic_live:false`.
- Cero posiciones reales verificadas antes y despues del despliegue.

## Identidad

- Protocolo SHA-256:
  `a46d073e1e069a7eb61e7000e19cf21b4ef0abf902f00b5a85e2e7ffc098eddf`.
- Politica completa SHA-256:
  `6d1b2d7a045e98f6e95bb4a0b8a5faca5efa038b78bf26ce50733ea7ff30820a`.
- Libro canonico al armar la cohorte SHA-256:
  `ff389904de6bbe74527ec6d9bad5e68c88ca6cc9997fe0a0a81fb41d16e19986`.
- Baseline del libro: 65 registros, 0 abiertos, 0 pertenecientes a la cohorte.

## Despliegue

`nexus.service` y `nexus-watchdog.service` ejecutan desde el checkout aislado
`/home/hugo/Nexus-bot-econ-release-v3`. El entorno Python y los secretos permanecen
en `/home/hugo/Nexus`; `data/` apunta al directorio canonico existente para preservar
una sola fuente y las escrituras atomicas del libro.

Ambos servicios quedaron `active/running`, con cero reinicios y heartbeat del
watchdog vigente. El kill-switch estuvo presente durante cada restart y se retiro
solo despues de verificar `live:false`, la politica congelada, el endpoint y cero
posiciones. Antes de la hora de inicio el ejecutor rechaza aperturas ECON; no existe
backfill.

Dos intentos de preflight abortaron y revirtieron automaticamente antes del release
final: el VPS no posee `pytest` en su venv y el primer endpoint no exponia el estado
ECON. No se instalaron dependencias en produccion. La paridad del endpoint fue
corregida y los dos servicios volvieron a su ruta previa tras cada aborto.

## Verificacion

- Suite local del release: `391 passed`.
- VPS: `compileall`, imports, protocolo, politica y consulta read-only a Binance.
- Estado previo al inicio: `scheduled`, 0/50, metricas de resultado ocultas.
- HYP-COST-003 se referencia por su contrato congelado; no se creo telemetria de
  costos paralela y sus observaciones live no se mezclan con esta cohorte dry.
- Escenario 6 del watchdog: documentado como opcional y no bloqueante; no ejecutado.

## Rollback

El rollback consiste en poner primero `/home/hugo/Nexus/data/bot_kill`, retirar los
drop-ins `90-bot-econ-release.conf`, ejecutar `systemctl daemon-reload` y reiniciar
ambos servicios. Esto devuelve `WorkingDirectory=/home/hugo/Nexus` sin modificar el
libro canonico.

## Decision

`NO LIVE` hasta el cierre y revision humana de ECON-COHORT-001. No se permiten
cambios de config, politica, definicion de R, costos, inclusion ni regla de parada;
cualquier cambio exige una cohorte nueva.
