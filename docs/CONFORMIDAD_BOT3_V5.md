# Conformidad pre-implementacion - Bot3.v5 candidato

**Fecha:** 2026-08-17
**Protocolo revisado:** `docs/BOT3_V5_PROTOCOLO.md`
**Commit:** `4be054a68eaa25bffba48da1f22d537568285f62`
**SHA-256 verificado:** `d5504d5029139f6a2c99e1de6a89c96a02afd69bb360e2e57113938f57465979`
**Informe v4:** SHA-256 `7260c166a6264ec94923fef45ea05a958078700fd54c558e39f7bf34cce16c49`

## Veredicto

`NO CONFORME - CORRECCIONES CONTRACTUALES FINALES REQUERIDAS`

La v5 cierra correctamente los cinco hallazgos expresos de la auditoria v4:
serializa y encadena los crudos de forma reproducible, se abstiene ante una
trayectoria M15 desconocida, procesa cierres simultaneos por lotes, explicita
`fill+STOP` y separa bootstrap de cohorte. Los vectores de cadena fueron
recalculados y coinciden byte por byte.

Persisten tres ambiguedades operacionales capaces de producir libros distintos
con fuentes equivalentes: llegada tardia entre ciclos, lote global con un
mercado ausente y estado de frescura durante bootstrap. No se autoriza aun la
implementacion ni la cohorte.

## Hallazgos bloqueantes

### B-1 - La prioridad por ciclo no elimina la dependencia del momento de llegada

CF-17 ordena las velas disponibles dentro de cada ciclo, pero permite appendear
una vela futura aunque falte su predecesora. El resultado sigue dependiendo del
momento en que arriben los datos:

1. Implementacion A recibe `t2` en el ciclo 1, lo appendea; `t1` llega en el
   ciclo 2 y se rechaza por `t1 <= ultimo_t`.
2. Implementacion B recibe `t1` y `t2` juntas; appendea ambas.

Las dos cumplen CF-17, consumieron finalmente las mismas fuentes y terminan con
almacenes, epocas y libros distintos. La prioridad `versionado > VPS` solo
resuelve empates dentro del mismo ciclo; no resuelve que la copia versionada
llegue despues de que el push ya fue appendeado.

Debe congelarse un watermark causal de ingestion. Una solucion determinista:

- mantener `expected_t` por mercado/TF;
- bufferizar velas con `t > expected_t` sin appendearlas;
- appendear solo el prefijo continuo desde `expected_t`;
- declarar un hueco mediante una regla temporal basada exclusivamente en
  timestamps de mercado (por ejemplo, despues de observar N cierres
  posteriores), no en cantidad/horario de pulls;
- incorporar al hash un marcador canonico de hueco antes de continuar;
- aplicar la prioridad de fuentes durante toda la permanencia en buffer.

La regla y N deben quedar congeladas. Sin watermark, el almacen es inmutable
despues de cada decision, pero la decision inicial no es reproducible.

### B-2 - Un lote global no define que hacer cuando falta un mercado

CF-19 dice que los siete mercados se procesan sincronizados por `close_time`,
pero CF-17/CF-18 admiten huecos por mercado. Para un timestamp `T` donde falta
BTC y existen los otros seis, el texto permite al menos tres conductas:

- esperar BTC indefinidamente y bloquear todo el motor;
- procesar los seis mercados y detectar el hueco de BTC cuando aparezca su
  sucesor;
- procesar despues el BTC tardio como parte retroactiva del lote `T`.

Estas opciones cambian orden del ledger, deteccion de huecos y el lote que
alcanza el corte de 50. Debe definirse el cierre/finalidad de cada lote usando
el mismo watermark de B-1. Una vez finalizado `T`, su conjunto de mercados es
inmutable; un mercado ausente genera el evento de hueco correspondiente y una
vela tardia nunca reabre el lote.

Tambien debe establecerse si el lote se appendea como una transaccion atomica o
como siete eventos secuenciales recuperables. Tras un crash intermedio, el
reinicio debe completar exactamente el mismo lote sin duplicar ni omitir
mercados.

### B-3 - El bootstrap no congela la semantica de consumo de zonas

CF-21 reconstruye zonas y direccion con las mismas reglas, pero prohibe emitir
candidatos, ordenes, fills o cierres. No define si un toque historico que habria
creado un candidato consume la frescura de una zona H4. Dos implementaciones
honestas pueden:

- ejecutar todas las transiciones historicas y suprimir solo la escritura al
  ledger; o
- omitir la logica de candidatos y dejar fresca una zona tocada antes de
  `T_frontera`.

La primera vela posterior a la frontera puede entonces producir candidatos
distintos. Debe congelarse que bootstrap ejecuta todas las transiciones que
afectan estado estructural, frescura, mitigacion, TTL, invalidacion y arbitraje,
suprimiendo unicamente eventos evaluables. Al cruzar la frontera se fuerzan
`orden_viva/posicion/salida_detectada -> flat`, pero no se resucitan zonas ni
se borra su historia de toques.

El gate debe incluir un vector donde una zona se toca antes de la frontera y se
vuelve a tocar despues: no puede crear un candidato forward si la frescura ya
se consumio.

## Hallazgos mayores

### M-1 - CF-17 reemplazo la vinculacion entre eventos y heads del almacen

CF-12 exigia que todo evento del ledger incluyera los `hash_acum` H4 y M15
consumidos. Al reemplazar CF-12 integramente, CF-17 conserva la cadena pero ya
no exige enlazar cada evento con sus heads. La provenance generica del diseno
rev.3 contiene fuente y `as_of`, pero no identifica necesariamente los bytes
exactos consumidos.

Restaurar explicitamente en cada evento de dominio:

- `h4_hash_acum` y `m15_hash_acum` correspondientes a su `ahora`;
- inicio/identidad de epoca M15;
- `contrato_hash` y commit de implementacion.

Asi la afirmacion replay == vivo queda verificable por evento, no solo por la
existencia externa de dos archivos JSONL.

### M-2 - Los eventos de ingestion pueden duplicarse segun frecuencia de pull

Una revision ignorada o vela tardia puede reaparecer en cada ciclo. CF-17 dice
que se registra `vela_revisada`/`vela_no_incorporada`, pero no establece
deduplicacion. Dos pollers con distinta frecuencia pueden producir cantidades
distintas de estos eventos para la misma anomalía.

Cada incidencia debe tener identidad estable, por ejemplo hash de
`(mercado, TF, t, tipo, hash_contenido_observado)`, y registrarse una sola vez.
Esto no cambia el estadistico primario, pero si la integridad replay == vivo y
la auditabilidad del ledger.

### M-3 - Un hueco necesita tiempo efectivo y tiempo de deteccion separados

`trayectoria_indeterminada` usa como timestamp el cierre anterior al hueco,
pero el motor solo conoce el hueco al alcanzar su watermark o recibir una vela
posterior. El ledger append-only debe conservar ambos:

- `effective_at`: primer intervalo no observado o ultimo cierre verificable,
  segun la convencion que se congele;
- `detected_at`: cierre del lote/watermark que hizo observable el hueco.

Backdatear un unico timestamp oculta cuando la abstencion estuvo realmente
disponible y dificulta reconstruir causalmente la secuencia.

## Cierres confirmados respecto de v4

- **B-1 anterior (bytes):** shortest-repr, concatenacion ASCII y semilla estan
  cerrados; `h1`, `h2` y `h3` coinciden exactamente. Persiste solo la finalidad
  entre ciclos descrita en B-1 actual.
- **B-2 anterior (posicion en hueco):** cerrado por
  `trayectoria_indeterminada`, sin salida, funding ni R imputados.
- **B-3 anterior (corte simultaneo):** cerrado cuando el lote ya esta formado;
  falta definir la formacion/finalidad del lote ante mercados ausentes.
- **M-1 anterior (fill+STOP):** cerrado por la transicion directa a
  `salida_detectada` y consolidacion en el mismo lote.
- **M-2 anterior (bootstrap forward):** cerrada la frontera y la no emision;
  falta congelar las transiciones de frescura durante bootstrap.

## Evaluacion de CF-17..CF-21

- **CF-17:** serializacion/hash conformes; ingestion entre ciclos no conforme.
- **CF-18:** conforme en abstencion cientifica; requiere temporalidad dual para
  auditabilidad.
- **CF-19:** conforme para lotes completos; no conforme ante mercado ausente y
  recuperacion de crash parcial.
- **CF-20:** conforme.
- **CF-21:** frontera/no emision conformes; estado historico de frescura no
  definido completamente.

## Hash y vigencia

El SHA-256 del candidato coincide con el commit indicado. El mecanismo de
vigencia sigue siendo suficiente una vez cerrados los hallazgos: cualquier
cambio requiere protocolo v6, SHA-256 nuevo, commit nuevo y otra conformidad.
No editar v5 para convertirlo en conforme.

## Estado

- Bot3.v1: `SUSPENDIDO`.
- Protocolo v5 candidato (`d5504d50...`): `NO CONFORME`.
- Bot3.v5: `NO IMPLEMENTADO`.
- Cohorte: `NO INICIADA`.
- Implementacion: `NO AUTORIZADA`.
