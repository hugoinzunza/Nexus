# Auditoria rev.6 del diseno del observador Bot3.v13

**Fecha:** 2026-08-20  
**Documento auditado:** `docs/BOT3_V13_OBSERVADOR_DISENO.md` rev.6  
**Commit:** `70476bd`  
**SHA-256 verificado:** `2ed4318686e3fb6ee7637d81ab24dd00772e1d30dc729015f2fdc21fd22dae1d`  
**Contrato del motor:** `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d`

## Veredicto

`NO CONFORME / REQUIERE REVISION 7 ACOTADA`

La rev.6 cierra los cuatro blockers, el major y las tres precisiones de la
auditoria rev.5 en su direccion correcta. Restan dos blockers en la maquina de
silencio y dos precisiones de recuperacion terminal. El resto del diseno queda
aceptado y no debe reabrirse.

No se autoriza implementar, actualizar snapshots canonicos ni desplegar.

## Cierres aprobados de rev.6

- El silencio usa evidencia acumulada y deja de restar todo el tiempo offline.
- `TOPE_INTERVALO` limita la contribucion de una observacion tardia.
- La paginacion probatoria exige watermark unico, recorrido completo y pagina
  vacia final.
- Las 72 h quedan correctamente rotuladas como decision operacional `[U0]`.
- `observer_state_digest` incorpora el estado de silencio.
- La zona de corte impide escribir eventos terminales con verificacion no
  certificada.
- La transicion a bloqueo usa solicitud persistente y `cycle_barrier`.
- `COMPLETED` exige `ok` posterior a toda deferencia.
- Solo una cola final sin newline es recuperable como torn write; una trama
  cerrada con cualquier discrepancia falla cerrada.

## BLOCKER 1 - La maquina de silencio sigue incompleta

La formula de acumulacion ya es mejor, pero no define todos los estados y
transiciones necesarios para que dos implementaciones produzcan el mismo
`silencio.json` y el mismo terminal.

Falta congelar al menos:

1. Primera observacion ausente: valor inicial de `t_observacion_previa` y si la
   primera consulta aporta cero o un intervalo.
2. Resolucion: que ocurre si la vela faltante aparece despues, antes de las
   72 h; si el contador se elimina, se archiva o cambia al siguiente cierre
   faltante.
3. Multiplicidad: estructura normativa para silencios simultaneos de varios
   mercados y para mas de un cierre faltante en el mismo mercado.
4. Seleccion: cual ausencia gobierna el terminal cuando existen varias.
5. Reloj anomalo: `eligibility_time` igual o menor que la observacion previa,
   incluido un retroceso de `serverTime`; nunca se puede sumar un delta
   negativo ni reordenar evidencia silenciosamente.
6. Duplicados: una misma observacion reintentada no puede sumar dos veces.
7. Definicion exacta de `offline_ms`, sus intervalos y su relacion con errores,
   cierre del daemon y reinicio.

`silencio.json` debe ser un mapa canonico por `(mercado, tf, primer_cierre)` o
una estructura equivalente con orden total y transiciones explicitas. El
terminal debe elegir un ganador de forma determinista y conservar la evidencia
de los demas sin que el orden de iteracion cambie bytes.

Gates: primera ausencia, backfill antes del umbral, dos mercados simultaneos,
dos huecos del mismo mercado, observacion duplicada, `serverTime` repetido y
regresivo, y reinicio en cada transicion.

## BLOCKER 2 - La invariancia por ciclos contradice el acumulador con tope

Los gates 21 y 28 exigen que el terminal no dependa del numero de ciclos. Sin
embargo, la regla:

```
evidencia += min(t - t_previa, 2 * CADENCIA)
```

depende deliberadamente de los timestamps de observacion. Con consultas cada
15 minutos acumula aproximadamente tiempo real; con consultas validas cada 60
minutos acumula solo 30 minutos por hora. Dos corridas sobre la misma ausencia
de mercado pueden bloquear en instantes distintos.

Eso puede ser correcto si la evidencia causal incluye el calendario exacto de
consultas, pero entonces no puede afirmarse independencia del numero de ciclos.
La rev.7 debe distinguir:

- invariancia ante diferente agrupacion de las **mismas observaciones**; de
- sensibilidad intencional ante observaciones realmente ausentes o mas
  espaciadas.

Tambien debe definir la evidencia que entra a `blocked.json`. Si incluye la
lista cruda de consultas, dos cadencias producen bytes distintos aun cuando
alcancen el mismo acumulado. Debe congelarse si el terminal conserva toda la
lista, una cadena/hash de evidencia o un resumen canonico.

Gate discriminante: mismos timestamps probatorios repartidos en distinto
numero de llamadas internas producen bytes identicos; eliminar observaciones
produce el retraso exacto previsto por `TOPE_INTERVALO`, no el mismo terminal.

## MAJOR 1 - `silencio.json` carece de autenticacion y validacion normativa

Incluir el sidecar en `observer_state_digest` evita omitirlo, pero no autentica
su historia. Un `silencio.json` valido sintacticamente pero alterado se copia al
scratch y ambos lados calculan el mismo digest sobre la alteracion. La
comparacion vivo-frio no puede detectar que el contador o una observacion fue
modificada antes de la captura.

Como el sidecar decide `BLOCKED_INTEGRITY`, la rev.7 debe definir:

- schema cerrado y versionado;
- identidad de cohorte/contrato/commit;
- escritura atomica con `fsync` de archivo y directorio;
- checksum o cadena de evidencia recalculable;
- validacion fail-closed al rehidratar;
- monotonicidad de observaciones y consistencia del acumulado contra ellas.

Gate: modificar cada campo decisional conservando JSON valido debe fallar
cerrado, no producir simplemente otro digest aceptado.

## MAJOR 2 - `terminal.request` no tiene contrato de recuperacion suficiente

La secuencia serializada es correcta, pero el artefacto persistente que permite
reanudarla no tiene schema. Tras una caida entre los pasos 1 y 6, el reinicio
necesita saber de forma verificable:

- identidad de cohorte, contrato y commit;
- motivo exacto del bloqueo;
- evidencia que lo autorizo;
- instante y barrera de solicitud;
- verificacion/digest asociados cuando el motivo sea divergencia;
- estado esperado de almacenes, ledger y sidecars;
- version y checksum del propio request.

Debe definirse ademas la precedencia si aparecen simultaneamente
`terminal.request`, `completed.json` o `blocked.json`, y si dos causas de
bloqueo compiten. No se puede resolver por ultima escritura ni por orden de
hilos.

Gate: caida despues de cada byte/rename del request, request alterado,
duplicado, dos motivos concurrentes y carrera request-vs-completed.

## Precision requerida - Zona de corte

La formula usa el numero de mercados con posicion u orden viva como cota de
cuantos cierres puede producir el siguiente lote. La implementacion debe
acompanarse de un gate que demuestre esa cota contra el orden completo de fases
del motor, incluidos `fill+STOP`, posiciones, ordenes, candidatos y los siete
mercados. Si una sola rama puede producir mas de un cierre por estado vivo, la
zona quedaria subestimada.

La condicion temporal `T >= T_CORTE - CORTE_ADMIN_GRACIA_MS` es conservadora,
pero debe rotularse como tal: la gracia contractual ocurre despues del corte y
su resta no representa el instante real de cierre.

## Estado final

- Diseno rev.6: `NO CONFORME`.
- Revision requerida: `REV.7 ACOTADA`.
- Secciones fuera de los hallazgos anteriores: `ACEPTADAS`.
- Protocolo del observador: `NO AUTORIZADO TODAVIA`.
- Implementacion: `NO AUTORIZADA`.
- Snapshots canonicos: `SIN CAMBIOS`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte: `NO INICIADA`.
- Bot3.v1: `SUSPENDIDO`.
