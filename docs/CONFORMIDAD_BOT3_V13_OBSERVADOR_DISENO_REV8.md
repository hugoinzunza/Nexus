# Conformidad del diseno rev.8 del observador Bot3.v13

**Fecha:** 2026-08-20  
**Documento auditado:** `docs/BOT3_V13_OBSERVADOR_DISENO.md` rev.8  
**Commit:** `bb4a4ff`  
**SHA-256 verificado:** `660c25d6f9151dfcde5db06abf31158f58e5ad3d65a370897299d080561aa781`  
**Contrato del motor:** `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d`

## Veredicto

`CONFORME PARA IMPLEMENTACION EN SCRATCH`

La rev.8 cierra los dos blockers y el major registral de la auditoria rev.7.
No queda una ambiguedad documental conocida capaz de cambiar causalidad,
contenido del libro o estado terminal entre dos implementaciones honestas.

Esta conformidad autoriza exclusivamente implementar y probar el observador en
scratch con datos sinteticos o copias. No autoriza actualizar snapshots
canonicos, desplegar, iniciar la cohorte ni reactivar Bot3.v1.

## Cierres verificados

1. **Reinicio frente a invariancia.** Un reinicio deja de tratarse como una
   reagrupacion. Dentro de un mismo `run_epoch`, las mismas observaciones deben
   producir bytes identicos; entre epochs, el primer intervalo aporta cero de
   forma deliberadamente conservadora.
2. **Acumulado reconstruible.** Cada observacion persiste
   `(eligibility_time, run_epoch)`, por lo que
   `evidencia_acumulada_ms` puede derivarse sin memoria del proceso.
3. **Documento completo protegido.** La cadena conserva la historia de
   observaciones y `doc_sha256` cubre el estado materializado completo.
4. **Mutacion terminal serializada.** Las anexiones a `terminal.request` son
   atomicas, recalculan checksum y quedan bajo `cycle_barrier`.
5. **Precedencia estable.** El motivo ganador depende de la precedencia
   congelada, no del orden de llegada de hilos.

## Condiciones para aceptar la implementacion

Los 44 gates del diseno son obligatorios. Ademas, la auditoria de implementacion
debe comprobar expresamente:

- `run_epoch` se obtiene de forma monotona y determinista del estado persistido;
- una caida durante la primera observacion de un epoch no puede acreditarla dos
  veces ni perder la frontera de reinicio;
- `doc_sha256` se valida antes de confiar en cualquier campo del sidecar;
- al anexar un motivo de mayor precedencia a `terminal.request`, su evidencia y
  `estado_esperado` se capturan bajo la misma barrera que la decision ganadora;
- ningun helper aprobado aisladamente queda desconectado de la ruta real del
  daemon;
- continuo y reinicio producen los resultados exactos definidos por los gates,
  incluido el delta conservador intencional de `run_epoch`.

Estas son condiciones verificables de codigo, no razones para otra revision del
diseno.

## Secuencia autorizada

1. Congelar rev.8 y su SHA-256 como diseno del observador.
2. Escribir el protocolo operativo pre-registrado si la secuencia del documento
   lo exige antes del codigo.
3. Implementar exclusivamente en scratch.
4. Ejecutar los 44 gates, suites y pruebas de crash/durabilidad.
5. Someter la implementacion a auditoria independiente.

Solo una aprobacion posterior y explicita puede autorizar actualizar snapshots,
congelar `bootstrap_hasta`, desplegar o iniciar la cohorte.

## Estado

- Diseno rev.8: `CONFORME PARA IMPLEMENTACION EN SCRATCH`.
- Arquitectura: `CONGELABLE`.
- Implementacion en scratch: `TECNICAMENTE AUTORIZABLE`, pendiente del visto
  bueno explicito del propietario.
- Snapshots canonicos: `SIN CAMBIOS`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte: `NO INICIADA`.
- Bot3.v1: `SUSPENDIDO`.
