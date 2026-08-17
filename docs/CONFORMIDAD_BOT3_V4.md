# Conformidad pre-implementacion - Bot3.v4 candidato

**Fecha:** 2026-08-17
**Protocolo revisado:** `docs/BOT3_V4_PROTOCOLO.md`
**Commit:** `8b59838908d28463523c96a4305e68c351787b50`
**SHA-256 verificado:** `6210e5bb578e2af2569b1041538f53acbccee9eb1b0dae388fdd9f832b79cf67`
**Diseno rev.3:** SHA-256 `5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`
**Informe v3:** SHA-256 `a60b3a708c5b7eec2eb5bfb46de4fceaa7c89b06cfbcc1c6941dac39c10020ec`

## Veredicto

`NO CONFORME - CORRECCIONES CONTRACTUALES ACOTADAS REQUERIDAS`

La v4 cierra correctamente la precedencia estructural, el cierre diferido con
funding, la cuantizacion de precios y el reloj causal que bloquearon la v3. Sin
embargo, el nuevo almacen canonico no define todavia una unica secuencia de
bytes/ingestion, una posicion puede atravesar una ventana M15 no observada y el
corte agregado no tiene arbitraje global entre mercados. Esos tres puntos aun
permiten libros diferentes o resultados basados en trayectorias inexistentes.

No se autoriza implementacion ni apertura de cohorte.

## Hallazgos bloqueantes

### B-1 - El almacen no tiene una serializacion ni un orden de ingestion univocos

CF-12 define `hash_acum` como `hash_previo || serializacion CF-9 de la vela`,
pero CF-9 solo congela preimagenes de identidades. No congela la preimagen
exacta de `{t,o,h,l,c,v}` ni resuelve:

- si `hash_previo` se concatena como 32 bytes o como 64 bytes ASCII hex;
- el tipo y formato de `v`;
- el formato de los OHLC crudos;
- el orden estricto de append por `t`;
- el desempate inicial entre la fuente versionada y el push VPS;
- la forma de incorporar un backfill posterior al sello pero anterior a una
  vela que ya fue appendeada.

Hay ademas una incompatibilidad directa con CF-15: el calculo usa OHLC crudos,
pero aplicar la regla generica de CF-9 cuantiza precios a seis decimales. Dos
valores crudos distintos, por ejemplo `1.00000040` y `1.00000049`, serializan
ambos como `"1.000000"`; pueden producir el mismo `hash_acum` y decisiones
intravela diferentes. El hash deja de identificar la entrada efectiva.

`first-write-wins` tampoco define una fuente canonica: si dos implementaciones
reciben primero contenidos distintos para el mismo `t`, ambas cumplen el texto
y conservan velas diferentes para siempre.

Debe congelarse:

1. preimagen exacta de vela, incluidos todos los tipos y bytes;
2. representacion exacta del hash previo;
3. append estrictamente creciente por `t` o un mecanismo de segmentos que
   permita backfill sin reescritura;
4. prioridad/dedupe deterministas antes del primer append;
5. vectores dorados de una cadena con al menos dos velas, una revision y un
   hueco.

El hash debe cubrir exactamente los valores crudos consumidos por el motor.

### B-2 - Una posicion no puede continuar causalmente a traves de un hueco M15

CF-13 mantiene viva una posicion durante un hueco y la gestiona desde la
primera vela de la epoca siguiente. La trayectoria ausente puede haber tocado
SL, TP o ambos; el OHLC posterior no permite saber si, cuando ni a que precio
salio. Aplicar CF-2 en la primera vela posterior fabrica una salida.

El fallback de funding tambien reemplaza un `C_k` ausente por el cierre de la
ultima vela anterior. Es determinista, pero no es el cierre causal exigido por
CF-8 y no es necesariamente conservador.

Ante un hueco que intersecta una posicion debe existir una unica salida
fail-closed, por ejemplo `trayectoria_indeterminada`, excluida del estadistico
primario y conservada en el ledger. Solo una fuente causal externa, congelada
en el contrato, podria resolver despues la trayectoria. No se debe imputar
precio de salida ni funding desde una vela distinta.

### B-3 - El corte agregado no define simultaneidad entre mercados

CF-14 opera por mercado y CF-11 corta cuando el ledger alcanza 50 cierres. Si
dos o mas mercados cierran en el mismo `close_time` y el primero lleva el
conteo a 50, el libro depende del orden en que se recorran los siete mercados:
una implementacion incluye solo el primer cierre; otra procesa el timestamp
como lote e incluye todos; otra obtiene un mercado distinto como observacion
50.

Debe congelarse una de estas reglas:

- procesamiento global por lotes de `close_time`, incluyendo todos los cierres
  simultaneos aunque `n` termine por encima de 50; o
- orden total canonico de mercados y truncado exacto en la observacion 50.

La primera preserva mejor la simultaneidad. El corte por fecha tambien necesita
un pre-gate: si `close_time(m) > T_corte`, esa vela no ejecuta Fases 1-7. En ese
instante se registran `abierta_al_corte`/`orden_al_corte` usando el ultimo estado
elegible. Dejar el unico chequeo en Fase 8 permite procesar una vela posterior
al limite antes de descubrir el corte.

## Hallazgos mayores

### M-1 - El fill con STOP en la misma vela no tiene transicion explicita

CF-14 Fase 1b remite a la seccion 4.5, que permite `fill + STOP` en la misma
vela, pero la maquina solo describe `orden_viva -> posicion` y la resolucion de
`posicion` ocurre antes, en Fase 1a. Debe decir expresamente que Fase 1b puede
producir `salida_detectada` de forma directa, que no devenga funding en ese
cierre por CF-8 y que se consolida en Fase 4. Esto evita que una implementacion
difiera el STOP a la vela siguiente.

### M-2 - La frontera forward no define el bootstrap sin emision historica

CF-13 exige reconstruir estado desde genesis y la regla de vigencia fija la
frontera en el primer pull post-despliegue. Falta especificar que el bootstrap
historico construye exclusivamente estado y no appendea candidatos, ordenes o
trades anteriores a la frontera en el ledger forward. Tambien falta fijar el
primer `m` elegible y su tratamiento cuando el pull contiene varias velas ya
cerradas.

Debe existir una fase normativa de bootstrap sin emision de cohorte y luego un
inicio exacto: solo eventos con `available_at`/fill/cierre posterior a la
frontera definida pueden entrar al ledger evaluable.

## Cierres confirmados respecto de v3

- **B-1 anterior (profundidad estructural):** conceptualmente cerrado por
  genesis H4 completo y epocas M15; pendiente hacer canonico el almacen que las
  alimenta (B-1 actual).
- **B-2 anterior (precedencia de direccion):** cerrado por Fase 2 pura y
  cancelacion en Fase 5.
- **B-3 anterior (salida/funding):** cerrado para series continuas mediante
  `salida_detectada`, funding y un unico `cerrado` definitivo.
- **M-1 anterior (mutacion posterior):** el sellado y first-write-wins protegen
  una instancia ya creada; falta determinismo de creacion/bytes (B-1 actual).
- **M-2 anterior (raw vs Q):** cerrado para niveles, fills, salidas, costos y
  funding. Los vectores A/B/C fueron recalculados y coinciden.
- **M-3 anterior (`ahora`):** cerrado por CF-16.

## Evaluacion de CF-12..CF-16

- **CF-12:** no conforme; faltan bytes, orden de append y arbitraje de fuentes.
- **CF-13:** no conforme para posiciones que atraviesan huecos; conforme en la
  separacion estructural por epocas.
- **CF-14:** conforme en precedencia y consolidacion de cierres continuos;
  requiere cerrar fill+STOP y corte global.
- **CF-15:** conforme para el dominio numerico operativo. Sus cuatro casos Q y
  los vectores A/B/C coinciden con Python 3 float64.
- **CF-16:** conforme.
- **CF-8/CF-9/CF-11 heredadas:** conservan su conformidad individual; CF-11
  requiere integracion global/pre-gate descrita en B-3.

## Hash y vigencia

El SHA-256 del candidato coincide exactamente con el commit indicado. El
mecanismo `cambio = v5 + cohorte nueva`, commit Git y nueva conformidad es
suficiente como pre-registro una vez cerrados los hallazgos. No editar v4 para
convertirla en conforme: la correccion debe ser un protocolo v5 nuevo, con hash
y commit nuevos.

## Estado

- Bot3.v1: `SUSPENDIDO`.
- Protocolo v4 candidato (`6210e5bb...`): `NO CONFORME`.
- Bot3.v4: `NO IMPLEMENTADO`.
- Cohorte: `NO INICIADA`.
- Implementacion: `NO AUTORIZADA`.
