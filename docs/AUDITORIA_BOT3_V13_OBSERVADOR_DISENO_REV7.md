# Auditoria rev.7 del diseno del observador Bot3.v13

**Fecha:** 2026-08-20  
**Documento auditado:** `docs/BOT3_V13_OBSERVADOR_DISENO.md` rev.7  
**Commit:** `5537c35`  
**SHA-256 verificado:** `fdf600a2d859794eea9f9259f6301fa2f5ff9b06841f961972f838406aa9c72b`  
**Contrato del motor:** `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d`

## Veredicto

`NO CONFORME / REQUIERE REVISION 8 REGISTRAL FINAL`

La rev.7 cierra la arquitectura del observador. No se reabren ingesta,
durabilidad, dependencia H4, verificacion, zona de corte ni estados terminales.
Resta una contradiccion directamente ejecutable en la semantica de reinicio y
una precision de integridad del sidecar.

Tras corregirlas, la recomendacion es congelar el diseno para implementacion en
scratch y trasladar los bordes restantes a los 41 gates. No se recomienda otra
ronda arquitectonica.

## Secciones aprobadas

- Mapa canonico y seleccion determinista entre silencios concurrentes.
- Primera observacion con aporte cero.
- Backfill como transicion a `resuelto`, sin borrar evidencia.
- Duplicados y retrocesos de `serverTime` con aporte cero.
- Separacion entre invariancia de agrupacion y sensibilidad al calendario real.
- Resumen terminal mediante cadena de evidencia, sin copiar la lista cruda.
- Contrato y precedencia de `terminal.request`.
- Cota de zona de corte trasladada correctamente a un gate demostrativo.

## BLOCKER 1 - Los gates 21 y 38 se contradicen sobre el reinicio

El gate 21 exige que las mismas observaciones probatorias, con un reinicio
intermedio, produzcan bytes identicos. El gate 38 exige que el primer intervalo
tras ese reinicio aporte cero y que la corrida partida acumule estrictamente
menos que la continua.

Ambas propiedades no pueden cumplirse simultaneamente. Con los mismos
`eligibility_time`, introducir un reinicio cambia el acumulado y, por tanto, el
sidecar, su cadena, el digest y potencialmente el terminal.

La regla substantiva elegida por rev.7 es coherente: **un reinicio rompe la
continuidad observacional y el primer intervalo posterior aporta cero**. Por
ello la rev.8 debe:

1. retirar del gate 21 la invariancia ante reinicio;
2. conservar la invariancia solo para reagrupar las mismas observaciones dentro
   de una misma continuidad de proceso;
3. mantener el gate 38 como comportamiento normativo del reinicio;
4. declarar que misma ausencia + mismas consultas + distinto calendario de
   reinicios puede producir distinto acumulado, deliberadamente.

Gate final: sin reinicio, reagrupar las mismas observaciones da bytes identicos;
con reinicio entre dos observaciones, el unico delta admisible es la perdida
exacta del intervalo que pasa a ser primero tras arranque.

## BLOCKER 2 - El acumulado no puede recomputarse desde los campos definidos

Cada entrada persiste `observaciones` como lista de `eligibility_time`. Esa
lista no identifica cuales observaciones fueron las primeras despues de un
arranque. Sin esa informacion, al rehidratar no se puede saber que intervalos
aportaron cero por reinicio y no se puede recalcular
`evidencia_acumulada_ms` como promete el documento.

La rev.8 debe hacer persistente la frontera de continuidad. Solucion minima:

- cada observacion lleva un `run_epoch` entero monotono;
- el primer elemento de cada `run_epoch` aporta cero;
- el cambio de epoch se persiste atomicamente antes de aceptar observaciones;
- al rehidratar, el acumulado se deriva exclusivamente de
  `(eligibility_time, run_epoch)` y `TOPE_INTERVALO`;
- duplicados/regresiones no crean epoch ni observacion;
- el contador de epoch pertenece a la identidad del sidecar y sobrevive al
  siguiente reinicio antes de incrementarse.

Puede usarse una representacion equivalente, pero no memoria del proceso ni un
`boot_id` aleatorio que vuelva no reproducibles los bytes.

Gates: reinicio antes de la primera observacion, entre dos observaciones, dos
reinicios sin observacion intermedia y caida durante el incremento de epoch.

## MAJOR 1 - La cadena no cubre todo el estado materializado

`h_n` encadena las observaciones, pero no autentica necesariamente
`estado`, `ultimo_cierre_valido`, `offline_ms`, `offline_intervalos`, identidad
ni el resumen materializado. Alterar `estado: activo` a `resuelto` puede dejar
intactas la cadena y la monotonicidad de observaciones.

Para cumplir el gate 39, la rev.8 debe elegir una de estas reglas:

- todos los campos materiales se derivan de un journal encadenado de
  transiciones y nunca se creen desde el JSON; o
- `silencio.json` incorpora checksum del documento canonico completo
  (excluido el propio checksum), ademas de la cadena de evidencia, y valida
  contra almacenes todo campo derivable.

El schema debe declarar cuales campos son fuente de verdad, cuales son
derivados y cuales son solo telemetria. `offline_ms` y sus intervalos necesitan
formula normativa o deben salir del estado certificado.

## Precision - `terminal.request`

La frase "no se sobrescribe" y la accion "se anexa a
`motivos_adicionales`" implican una mutacion. La implementacion debe hacerla
mediante reemplazo atomico, recalcular checksum y preservar la solicitud
original. El motivo ganador y su `estado_esperado` deben quedar vinculados a la
misma barrera; un motivo posterior no puede reutilizar heads capturados para
otro instante.

Esto puede cerrarse mediante tests de implementacion y no requiere otra
revision documental si la rev.8 declara esa invariante en una frase.

## Criterio de cierre

Una rev.8 que resuelva exclusivamente los dos blockers y el major anteriores
queda `CONFORME PARA IMPLEMENTACION EN SCRATCH`, no aprobada para despliegue.

La implementacion debera pasar los gates completos y una auditoria independiente
antes de actualizar snapshots, desplegar o iniciar la cohorte.

## Estado final

- Diseno rev.7: `NO CONFORME`.
- Revision requerida: `REV.8 REGISTRAL FINAL`.
- Arquitectura del observador: `ACEPTADA`.
- Implementacion en scratch: `AUN NO AUTORIZADA`.
- Snapshots canonicos: `SIN CAMBIOS`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte: `NO INICIADA`.
- Bot3.v1: `SUSPENDIDO`.
