# Auditoria rev.3 del diseno del observador Bot3.v13

**Fecha:** 2026-08-20  
**Documento auditado:** `docs/BOT3_V13_OBSERVADOR_DISENO.md` rev.3  
**Commit:** `ec6e6bcc3a54007c900fff08fa31dee4c12c1469`  
**SHA-256 verificado:** `b109cd5339f5e5f3f82be4e42d13f95c765257fc72fc0c97941dc2d9a17838e6`  
**Contrato del motor:** `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d`

## Veredicto

`NO CONFORME / REQUIERE REVISION 4 ACOTADA`

La rev.3 cierra correctamente los hallazgos documentales de rev.2: separa el
singleton de la barrera, elimina el desafio sobre el motor vivo, corrige la
paginacion, autentica el estado decisional completo, persiste `COMPLETED` y
define un nacimiento por staging. Quedan tres bloqueos operacionales nuevos y
tres precisiones menores antes de congelar el protocolo.

No se autoriza implementar ni actualizar snapshots canonicos todavia.

## Respuesta a las tres preguntas H4

### 1. El watermark local H4 reutiliza semantica existente, con una condicion

`Almacen.prueba_local()`, `hueco_pendiente()` y
`declarar_hueco_local()` son genericos por `self.dur`. Por tanto, cuando el
mismo mercado vuelve a publicar velas H4 posteriores, el observador puede
sellar el hueco sin modificar la estrategia ni el motor. La consecuencia
`historia_insuficiente` ya esta congelada en `_calcular_h4()`.

Esto requiere cablear explicitamente la emision inmediata de
`hueco_detectado(tf="4h")` en el daemon largo. Declarar el marcador en el
almacen no escribe por si solo el evento del ledger.

### 2. Las 12 horas son aceptables, pero no una cota absoluta

La espera es cientificamente conservadora: durante ella no se decide con un
rector congelado. Es aceptable para un observador no operativo.

La cota de 12 horas solo vale si, despues de la ausencia, el mismo mercado
publica normalmente tres velas H4 consecutivas. La latencia real incluye
`MARGEN_CIERRE`, cadencia, red y cualquier prolongacion del silencio. Debe
describirse como `12 h + margen/cadencia bajo reanudacion normal`, no como cota
incondicional.

### 3. Si no vuelven velas H4, la precondicion queda bloqueada para siempre

Con solo watermark local no existe prueba que permita sellar el hueco cuando el
mercado permanece completamente mudo. No hay una salida causal ya implementada.

Existen dos salidas honestas:

1. pre-registrar en el protocolo del observador un watermark exchange H4 que
   solo demuestra ausencia, nunca precio, con Q/N/prueba/detected_at congelados;
   el mercado afectado queda `historia_insuficiente` y los demas continuan; o
2. terminar operacionalmente la observacion como `BLOCKED_INTEGRITY`, sin
   resultado evaluable ni reapertura automatica.

Esperar indefinidamente tambien es fail-closed, pero deja toda la cohorte sin
una regla total de liveness. La recomendacion es la opcion 1, usando la misma
idea causal Q=4/N=3 ya aceptada en M15, implementada en el observador y auditada
por separado. Si no se desea introducirla, la opcion 2 debe ser obligatoria.
No se permite continuar con el ultimo rector conocido.

## BLOCKER 1 - `_buffer` queda fuera de un digest que se declara completo

La seccion 8 excluye `_buffer` como si fuera cache derivada, pero no lo es. Ante
un hueco contiene velas futuras aun no selladas y determina:

- los tres cierres de `prueba_local`;
- `detected_at`;
- el rango exacto del marcador;
- el siguiente head de la cadena.

Un motor vivo con buffer pendiente y un arranque frio sin ese buffer pueden
tener igual ledger, heads sellados y `state_digest`, pero distinto siguiente
evento si la fuente cambia antes del re-pull.

La verificacion periodica debe adoptar una regla unica:

- solo certificar una barrera cuando los 14 buffers estan vacios; si alguno no
  lo esta, registrar `verification_deferred` y esperar a que se selle o drene; o
- incluir y copiar canonicamente los buffers a ambos clones, lo que contradice
  la decision de no persistirlos.

Se recomienda la primera. Antes de reportar resultados debe existir una
verificacion exitosa posterior a la ultima deferencia.

Gate: un hueco con dos de las tres velas probatorias en buffer no puede producir
un falso `determinism_ok`.

## BLOCKER 2 - El orden de durabilidad no cubre gaps creados por el motor

El ciclo propuesto hace fsync de almacenes antes de procesar lotes. Sin embargo,
`Motor.watermark_exchange(T)` puede agregar despues un marcador M15 al almacen y
emitir inmediatamente `hueco_detectado`/`mercado_degradado` al ledger.

Una caida puede dejar durable el evento del ledger y perder el marcador del
almacen, porque el fsync del almacen ocurrio antes de ese append. Un fsync global
posterior tampoco garantiza el orden si el ledger ya fue escrito.

Cada transicion almacen->ledger debe respetar:

1. append del marcador al almacen;
2. flush + fsync de ESE almacen;
3. append de sus eventos al ledger;
4. flush + fsync del ledger al cierre del ciclo.

Para el watermark exchange actual, esto exige que
`declarar_hueco_exchange()` asegure durabilidad antes de retornar al motor, o
una primitiva equivalente que no permita `_emit` antes del fsync.

Gate: caida tras cada uno de los cuatro pasos; la recuperacion debe producir
exactamente el mismo almacen y ledger.

## BLOCKER 3 - El silencio H4 total no tiene salida registral

La precondicion H4 global detiene los siete mercados. Si un mercado no vuelve a
publicar, no aparecen los tres cierres propios y el hueco nunca se sella. El
catch-up tampoco puede resolverlo porque depende de la misma fuente ausente.

La rev.4 debe elegir y congelar una de las dos salidas de la respuesta H4. Si se
elige watermark exchange H4, debe especificar:

- Q y N;
- mercados de referencia y desempate;
- prueba exacta y `detected_at`;
- `effective_at`, `finalized_at`, heads y event_id existentes;
- no uso de `mercado_degradado/reingresado` M15;
- efecto unico: marcador H4 + `historia_insuficiente` para ese mercado.

Si se elige `BLOCKED_INTEGRITY`, debe persistirse atomicamente y sobrevivir a
launchd igual que `COMPLETED`, pero no presentarse como corte evaluable.

## MAJOR 1 - `processed_at` usa el reloj equivocado en el pseudocodigo

La seccion 12 llama `iniciar_ciclo(serverTime)`. Eso convierte el reloj Binance
de elegibilidad en `processed_at`. CF-34 define `processed_at` como reloj
observado de materializacion y la propia rev.3 registra la deriva del reloj del
Mac por separado.

Se deben muestrear dos valores disjuntos una vez por ciclo:

- `eligibility_time = serverTime` de Binance, solo filtra velas;
- `processed_at = local_observed_time`, solo telemetria de materializacion.

El primero nunca entra por el parametro que alimenta `_reloj_ciclo`.

## MAJOR 2 - El nacimiento parcial definitivo no se descarta explicitamente

Durante staging, los 14 `os.replace` se realizan uno a uno antes de publicar el
manifiesto. Una caida puede dejar algunos archivos ya en destino definitivo y
otros aun en staging. La regla actual solo dice descartar restos de `staging/`.

Si `manifest.json` no existe, el renacimiento debe eliminar o poner en
cuarentena tanto `staging/` como cualquier archivo definitivo parcial antes de
materializar de nuevo los 14. Alternativamente, publicar atomica una carpeta
completa en un unico rename dentro del mismo filesystem.

Gate: caida despues de cada uno de los 14 renames, no solo antes/despues del
manifiesto.

## MAJOR 3 - La captura no debe readquirir una barrera ya retenida

El pseudocodigo mantiene `cycle_barrier` desde el inicio del ciclo hasta despues
de atender `verify.request`; la seccion 9 dice que el daemon "toma" la barrera al
terminar. Con un mutex no reentrante, volver a adquirirla causa deadlock.

Debe decir normativamente que el ciclo continua reteniendo la barrera durante
fsync, digest y copia, sin readquirirla. La reconstruccion fria ocurre despues
de liberarla.

## Cierres aprobados de rev.3

- `singleton_lock` y `cycle_barrier` quedan correctamente separados.
- Ningun dato sintetico toca el motor vivo.
- El digest incluye listas completas de cierres y lotes.
- Paginacion alineada y progreso estricto.
- `COMPLETED` persistente, atomico y validado antes de ingerir.
- Prefijo de nacimiento inmutable en lugar de head mutable.
- Frontera conjunta H4/M15 y reloj Binance sin fallback para elegibilidad.
- Watermark local H4 reutiliza primitivas existentes cuando el mercado retoma.

## Gates requeridos para revision 4

1. Verificacion diferida con buffer no vacio; cero falso positivo.
2. Durabilidad store-before-ledger para watermark exchange M15.
3. Silencio H4 total: watermark exchange H4 o `BLOCKED_INTEGRITY` persistente.
4. Separacion `eligibility_time` / `processed_at`.
5. Caida despues de cada rename del nacimiento.
6. Solicitud de captura atendida sin readquirir el mutex.
7. Hueco H4 local emite una sola vez `hueco_detectado(tf="4h")` con heads y
   finalidad correctos.

## Estado final

- Diseno rev.3: `NO CONFORME`.
- Revision requerida: `REV.4 ACOTADA`.
- Protocolo del observador: `NO AUTORIZADO TODAVIA`.
- Implementacion: `NO AUTORIZADA`.
- Snapshots canonicos: `SIN CAMBIOS`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte: `NO INICIADA`.
- Bot3.v1: `SUSPENDIDO`.
