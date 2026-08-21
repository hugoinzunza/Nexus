# Auditoria rev.5 del diseno del observador Bot3.v13

**Fecha:** 2026-08-20  
**Documento auditado:** `docs/BOT3_V13_OBSERVADOR_DISENO.md` rev.5  
**Commit:** `3a6d377`  
**SHA-256 verificado:** `1b846b634c1cec5aba3cdcb4b81ea4305a111e66ce236d207667f9855a3f7691`  
**Contrato del motor:** `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d`

## Veredicto

`NO CONFORME / REQUIERE REVISION 6 ACOTADA`

La rev.5 cierra correctamente los dos blockers y los tres majors de la
auditoria rev.4 en su intencion general. En particular, son correctas la
separacion entre `COMPLETED` y `BLOCKED_INTEGRITY`, la persistencia operacional
de las verificaciones y la adopcion de un formato enmarcado para poder
recuperar una escritura final desgarrada.

Persisten cuatro bloqueos de especificacion y una precision del formato. No se
autoriza implementar, actualizar snapshots canonicos ni desplegar todavia.

## Cierres aprobados de rev.5

- `SILENCIO_MAX_H4` queda limitado a la cohorte activa y usa reloj de Binance.
- Errores HTTP, timeout y ausencia de `eligibility_time` no se interpretan como
  evidencia de mercado mudo.
- La liveness deja de presentarse como incondicional.
- Almacen y ledger adoptan una disciplina comun para torn writes.
- `BLOCKED_INTEGRITY` no ejecuta por si mismo el cierre cientifico.
- `verification_deferred` vive fuera del registro cerrado y sobrevive al
  reinicio.
- Una verificacion pendiente impide publicar `COMPLETED`.
- La divergencia de determinismo queda definida como terminal no evaluable.

## BLOCKER 1 - El comparador de silencio cuenta tiempo sin evidencia

La tabla normativa afirma simultaneamente:

- que el daemon apagado no avanza el silencio; y
- que el bloqueo ocurre cuando `eligibility_time - inicio > 72 h`, donde
  `inicio` es el primer cierre H4 faltante.

Estas reglas no son equivalentes. Si el daemon observa una ausencia, permanece
apagado mas de 72 horas y luego recibe una paginacion valida que sigue sin traer
la vela, el comparador bloquea inmediatamente. Por tanto, el periodo apagado si
queda incluido en la resta aunque no existieran consultas que lo sostuvieran.

La rev.6 debe escoger y congelar una semantica unica. Si se mantiene la regla
"solo evidencia valida avanza", `silencio.json` debe persistir una duracion de
evidencia acumulada o intervalos probatorios normativos, con reglas explicitas
para pausas, errores, reinicios y saltos de cadencia. Si se decide que una
paginacion historica posterior demuestra tambien el intervalo offline, debe
retirarse la afirmacion contraria y justificar esa inferencia.

Gate discriminante: misma ausencia H4; corrida A observa continuamente y
corrida B permanece apagada durante 80 horas. El terminal debe corresponder
exactamente a la semantica elegida y no depender del numero de ciclos.

## BLOCKER 2 - `silencio.json` es estado decisional fuera del digest

El documento afirma que `state_digest` cubre todo estado capaz de afectar
decisiones futuras, pero no incluye `silencio.json`. Dos observadores pueden
tener almacenes, ledger, motor y buffers identicos, pero origen o evidencia de
silencio distintos; producirian el mismo digest y bloquearian en instantes
distintos.

La captura fria copia solo almacenes y libro. Tampoco puede reconstruir el
estado de silencio desde ellos, porque la ausencia H4 permanente todavia no es
un marcador sellado. La verificacion puede declarar determinismo aun cuando el
terminal futuro ya diverge.

La rev.6 debe definir un `observer_state_digest` o ampliar el digest existente
para incluir la representacion canonica completa del estado de silencio. La
captura debe copiar y verificar el sidecar correspondiente bajo la misma
barrera. `verificacion.json` debe quedar tratado por separado para evitar una
dependencia circular, pero sus invariantes de publicacion tambien deben
verificarse.

Gate: alterar solamente el origen/evidencia de `silencio.json`, conservando
motor, almacenes y ledger, debe cambiar el digest o fallar cerrado.

## BLOCKER 3 - Una verificacion pendiente puede dejar eventos de cierre antes de bloquear

La rev.5 permite que, con verificacion `pending`, la ingesta continue y solo
prohibe publicar `COMPLETED`. Sin embargo, el motor emite
`abierta_al_corte`/`orden_al_corte` dentro de `_cerrar()` antes de que el
observador publique `completed.json`.

Por ello puede ocurrir esta secuencia:

1. la verificacion queda `pending`;
2. un ciclo posterior alcanza 50 cierres o `T_CORTE`;
3. el motor corta y escribe eventos terminales en el ledger;
4. la comparacion fria diverge;
5. se publica `BLOCKED_INTEGRITY`.

El estado final contradice entonces la tabla de la seccion 13.1 y el gate 25:
un terminal bloqueado contiene eventos de cierre cientifico.

La rev.6 debe impedir que el motor ejecute un lote capaz de cerrar mientras la
ultima verificacion no sea `ok` y posterior a toda deferencia, o definir una
publicacion transaccional equivalente que no escriba eventos terminales antes
de certificar. No basta con demorar `completed.json`.

Gate: verificacion pendiente justo antes del lote 50 y justo antes del corte
temporal, seguida tanto de igualdad como de divergencia. En la rama divergente
el ledger no puede contener ningun evento terminal nuevo.

## BLOCKER 4 - La transicion asincrona a bloqueo no esta serializada

La comparacion fria ocurre fuera de `cycle_barrier` mientras el daemon sigue
operando. Al detectar divergencia, la rev.5 ordena terminar en
`BLOCKED_INTEGRITY`, pero no especifica como se detiene la ingesta ni en que
barrera se congelan almacenes y ledger antes de publicar `blocked.json`.

Sin un arbitraje normativo, una implementacion puede publicar el marcador
antes del siguiente ciclo y otra despues de uno o mas ciclos adicionales. Los
heads y la firma asociados al bloqueo divergen, y el `fsync` puede competir con
escrituras activas.

La rev.6 debe definir una transicion unica, por ejemplo: solicitud terminal
persistente, adquisicion de `cycle_barrier`, prohibicion de abrir ciclos nuevos,
fsync y captura de heads/firma, publicacion atomica de `blocked.json`, y salida.
La misma regla debe cubrir la carrera entre resultado de verificacion y corte
del motor.

Gate: inyectar la divergencia en cada frontera entre ciclos y verificar que la
misma secuencia causal produce exactamente el mismo estado, libro y
`blocked.json`.

## MAJOR 1 - El framing no distingue toda truncacion de corrupcion

La regla actual clasifica como truncacion tanto `bytes < longitud` como la falta
de newline. Si el campo longitud de la ultima trama completa se corrompe hacia
un valor mayor, puede descartarse como torn write aunque el archivo termine en
newline. El hash cubre el payload, no el encabezado.

La regla debe quedar inequívoca. Una opcion minima es:

- ultimo segmento sin newline: unica cola truncable;
- trama terminada en newline: longitud, hash, UTF-8 y payload deben ser
  completamente validos; cualquier discrepancia es corrupcion;
- encabezado con gramatica y limites normativos;
- ninguna trama intermedia puede recuperarse por truncacion.

Agregar gates para longitud menor/mayor, hash o encabezado alterado, newline
presente/ausente y payload UTF-8 incompleto.

## Precisiones requeridas

1. Definir operacionalmente que constituye una paginacion H4 "valida y
   completa" para iniciar o avanzar silencio, incluida la pagina vacia final y
   el watermark de elegibilidad usado por toda la consulta.
2. `COMPLETED` debe exigir estado de verificacion `ok` posterior a la ultima
   deferencia, no solo ausencia de `pending`.
3. El valor de 72 h puede conservarse como decision operacional `[U0]`, pero la
   afirmacion sobre ventanas de mantenimiento y deslistado no debe presentarse
   como hecho demostrado sin provenance documental congelada.

## Estado final

- Diseno rev.5: `NO CONFORME`.
- Revision requerida: `REV.6 ACOTADA`.
- Protocolo del observador: `NO AUTORIZADO TODAVIA`.
- Implementacion: `NO AUTORIZADA`.
- Snapshots canonicos: `SIN CAMBIOS`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte: `NO INICIADA`.
- Bot3.v1: `SUSPENDIDO`.
