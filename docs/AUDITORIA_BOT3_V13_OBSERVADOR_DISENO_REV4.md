# Auditoria rev.4 del diseno del observador Bot3.v13

**Fecha:** 2026-08-20  
**Documento auditado:** `docs/BOT3_V13_OBSERVADOR_DISENO.md` rev.4  
**Commit:** `7a561136683fc619cc088b10bade67789b56b380`  
**SHA-256 verificado:** `87a98bbcc091f135ffe085aa367d833dceda266666caa993ef405e63d1b6573e`  
**Contrato del motor:** `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d`

## Veredicto

`NO CONFORME / REQUIERE REVISION 5 ACOTADA`

La rev.4 cierra los seis hallazgos de la auditoria anterior. En particular,
elegir `BLOCKED_INTEGRITY` es mas conservador que crear una semantica exchange
H4 fuera del contrato congelado y queda aprobado conceptualmente.

Restan dos bloqueos de especificacion y tres precisiones operacionales. No se
autoriza implementar ni actualizar snapshots canonicos todavia.

## Cierres aprobados de rev.4

- La verificacion solo se certifica con los 14 buffers vacios.
- Una verificacion exitosa posterior a la ultima deferencia es requisito para
  reportar resultados.
- La precedencia durable almacen -> libro queda explicitada.
- `eligibility_time` y `processed_at` quedan separados.
- El nacimiento usa un unico rename de directorio y cuarentena sin manifiesto.
- La captura continua reteniendo `cycle_barrier`; no intenta readquirirlo.
- El hueco H4 local se emite explicitamente al ledger una sola vez.
- La latencia H4 ya no se presenta como una cota incondicional de 12 horas.
- No se inventa un watermark exchange H4 que altere la historia rectora.

## BLOCKER 1 - `SILENCIO_MAX_H4` no tiene un reloj ni un origen normativos

La rev.4 define el terminal correcto, pero no define como se decide que el
silencio excedio el umbral. Dos implementaciones honestas pueden bloquear en
instantes distintos o interpretar como silencio de mercado una caida del
daemon, una pagina fallida o un backlog inicial.

La rev.5 debe congelar, como minimo:

1. **Inicio:** el primer cierre H4 esperado que ya es elegible segun
   `eligibility_time` y que falta despues de una respuesta valida y completa de
   Binance para ese mercado/TF.
2. **Reloj:** `eligibility_time` de Binance, no `processed_at` ni tiempo desde
   el ultimo ciclo local.
3. **Evidencia minima:** una pagina vacia/ausente solo cuenta tras completar la
   paginacion valida del mercado H4; errores HTTP, timeout, `serverTime`
   indisponible y daemon apagado no avanzan el silencio.
4. **Ambito:** no puede dispararse durante nacimiento o catch-up prefrontera.
   Solo rige para la cohorte activa despues de que los 14 streams fueron
   declarados frescos en la activacion.
5. **Comparador:** `>` o `>=`, expresado en milisegundos exactos.
6. **Reinicio:** el origen y la evidencia que lo sostiene deben persistirse o
   derivarse univocamente del almacen y de observaciones persistidas. No puede
   reiniciarse el contador al relanzar el daemon.
7. **Payload terminal:** mercado, TF, primer cierre faltante, ultimo cierre H4
   valido, inicio, umbral, `eligibility_time` decisivo y evidencia de las
   consultas.

La frase "el sistema siempre alcanza un terminal" tambien debe condicionarse a
que el observador siga obteniendo `serverTime` y respuestas validas. Si la
infraestructura completa queda muda, fail-closed es correcto, pero no hay reloj
Binance con el que certificar el vencimiento.

Gate: la misma secuencia causal, repartida entre distintos numeros de ciclos y
con un reinicio intermedio, debe producir el mismo `blocked.json`; errores de
red y tiempo offline no deben adelantarlo.

## BLOCKER 2 - `fsync` ordena durabilidad, pero no hace atomico un registro

La nueva precedencia resuelve correctamente que el evento nunca sea durable
antes que el marcador que lo justifica. Sin embargo, los almacenes y el ledger
siguen siendo JSONL append-only. Una caida puede dejar la ultima linea truncada
o parcialmente escrita. `flush` + `fsync` no convierte una llamada `write` en
una transaccion de registro.

Las rutas actuales de `Almacen.cargar()` y `Ledger._releer()` intentan parsear
cada linea; una cola rota falla cerrado, pero no produce la recuperacion
identica que exige el gate 8. Por tanto, la rev.4 promete simultaneamente
recuperacion exacta y un formato que no define como recuperar un torn write.

La rev.5 debe elegir una regla unica para ambos archivos:

- escritura por registro mediante journal/segmento temporal durable y
  publicacion atomica; o
- formato enmarcado con longitud/hash y permiso explicito para truncar
  **solamente** una ultima trama incompleta cuya ausencia se recupera por
  replay; cualquier corrupcion interna sigue fallando cerrada.

No se permite ignorar una ultima linea JSON invalida sin distinguir truncacion
de corrupcion. El ledger debe aplicar la misma disciplina que el almacen.

Gates: caida en cada byte representativo de la ultima escritura del almacen y
del ledger, antes y despues del fsync; tras recuperar, cadena y libro deben ser
identicos a la ejecucion continua.

## MAJOR 1 - `BLOCKED_INTEGRITY` no debe ejecutar el cierre cientifico

La seccion 13 comienza con "Al cortar el motor" y luego presenta
`blocked.json` como la misma mecanica. Debe separarse de forma normativa:

- `COMPLETED` ejecuta el cierre contractual y sus eventos terminales;
- `BLOCKED_INTEGRITY` no llama al corte del motor, no emite
  `abierta_al_corte`, `orden_al_corte` ni resultados, y no altera el ledger
  cientifico para simular una evaluacion;
- primero se fsyncan estado y libro existentes, despues se publica
  `blocked.json` atomico.

Las incidencias operacionales sobre el bloqueo deben vivir en health/sidecar,
salvo que ya pertenezcan al registro cerrado del contrato.

## MAJOR 2 - `verification_deferred` carece de canal contractual

`verification_deferred` no es un tipo del registro cerrado CF-37. La rev.4 debe
decir que es observabilidad operacional fuera del ledger cientifico y definir
su persistencia minima: instante, buffers no vacios, ultima verificacion exitosa
y estado pendiente.

De lo contrario, un reinicio puede olvidar que la ultima verificacion fue
diferida y permitir que el reporte considere valida una verificacion anterior.
El requisito "posterior a la ultima deferencia" necesita un sidecar atomico y
rehidratable, no solo memoria o logs.

## MAJOR 3 - Divergencia posterior sin transicion definida

La copia se toma bajo barrera, pero la comparacion fria ocurre despues de
soltarla y el daemon sigue operando. Si se detecta divergencia, pueden haberse
procesado ciclos adicionales.

La rev.5 debe definir una salida total. Recomendacion: la verificacion queda
marcada `pending`; mientras exista puede continuar la ingesta durable, pero no
puede publicarse `COMPLETED`; una divergencia termina en
`BLOCKED_INTEGRITY(determinism_divergence)` sin resultado. Alternativamente, el
daemon puede permanecer pausado hasta terminar la comparacion.

Tambien debe aclararse que `blocked.json` admite este motivo ademas de
`silencio_h4`, o crear un terminal de integridad equivalente sin tocar el
ledger cientifico.

## Gates requeridos para revision 5

1. Reloj, origen, evidencia y persistencia exactos de `SILENCIO_MAX_H4`.
2. Reinicio y diferente cadencia no cambian el terminal de silencio.
3. Errores HTTP, daemon offline y catch-up no cuentan como silencio H4.
4. Torn write en almacen y ledger: recuperacion exacta o fallo cerrado
   normativamente distinguible de corrupcion interna.
5. `BLOCKED_INTEGRITY` no emite eventos de cierre ni resultado.
6. `verification_deferred` persiste fuera del ledger y sobrevive al reinicio.
7. Divergencia posterior a la copia impide `COMPLETED` y termina de forma
   no evaluable.
8. Se conservan los 20 gates de rev.4.

## Estado final

- Diseno rev.4: `NO CONFORME`.
- Revision requerida: `REV.5 ACOTADA`.
- Protocolo del observador: `NO AUTORIZADO TODAVIA`.
- Implementacion: `NO AUTORIZADA`.
- Snapshots canonicos: `SIN CAMBIOS`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte: `NO INICIADA`.
- Bot3.v1: `SUSPENDIDO`.
