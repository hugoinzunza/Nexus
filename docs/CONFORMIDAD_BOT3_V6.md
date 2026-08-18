# Conformidad pre-implementacion - Bot3.v6 candidato

**Fecha:** 2026-08-17
**Protocolo revisado:** `docs/BOT3_V6_PROTOCOLO.md`
**Commit:** `a486713`
**SHA-256 verificado:** `a342cd100d94482326fff31f5160e99e7131ae919f4681eff47339bbcd1cd393`
**Informe v5:** SHA-256 `8bb8ffe34923ccb559d6d1c3dc89800e5bb2e54c58dac062252eaf31a5354ab1`

## Veredicto

`NO CONFORME - TRES CIERRES CONTRACTUALES REQUERIDOS`

La v6 cierra correctamente los seis hallazgos expresos de la auditoria v5. El
watermark ya no depende de pulls, el lote tiene barrera de recuperacion, el
bootstrap conserva frescura, cada evento porta heads y los huecos tienen
temporalidad dual. Los vectores `h1`, `h2`, `hg` y `h3` fueron recalculados
desde sus bytes y coinciden exactamente.

Persisten tres bordes normativos: el nacimiento M15 aun depende del primer
ciclo, la finalidad global no progresa si un mercado habilitado deja de emitir
por completo, y la identidad estable no cubre los eventos sin jerarquia de
trade que sostienen la recuperacion. No se autoriza implementacion ni cohorte.

## Hallazgos bloqueantes

### B-1 - El ancla inicial M15 sigue dependiendo del primer ciclo

CF-22 conserva la regla de CF-17 segun la cual la primera vela M15 es el menor
`t` presente en el primer ciclo con buffer no vacio. Dos instalaciones pueden
leer las mismas fuentes historicas y producir almacenes distintos:

- A inicia con el repositorio versionado disponible y ancla en `t0`;
- B inicia durante una indisponibilidad del repositorio, ve solo el push VPS y
  ancla en `t100`;
- cuando el repositorio vuelve, B rechaza `t0..t99` por ser anteriores a su
  ancla.

La prioridad `versionado > push` no ayuda porque nunca coexistieron en el mismo
buffer. Esto cambia epocas, pivotes, frescura y estado de bootstrap.

Debe congelarse una unica regla de nacimiento, por ejemplo:

1. `GENESIS_M15` fijo por mercado; o
2. bootstrap prohibido hasta cargar y verificar un snapshot versionado
   canonico identificado por commit/hash, usando su menor `t` como ancla.

Si esa fuente no esta disponible o no cubre el ancla, la salida debe ser
`historia_insuficiente`; no se permite nacer desde el push reciente.

### B-2 - El watermark por mercado no garantiza finalidad ante silencio total

CF-23 afirma que la espera siempre termina gracias a CF-22. Eso solo ocurre si
el mercado ausente vuelve a entregar al menos tres timestamps posteriores. Si
un mercado con epoca habilitada deja de emitir completamente, no tiene vela,
marcador de hueco ni condicion (c); por tanto ningun lote posterior de los
otros seis mercados puede finalizar. El corte temporal tampoco llega a
registrarse.

Debe elegirse y congelarse una politica fail-closed para silencio total. Una
opcion determinista es un watermark global de exchange: cuando al menos una
regla predefinida de mercados sanos demuestra N cierres sincronizados
posteriores, se declara el hueco del mercado silencioso. Deben congelarse:

- quorum o conjunto de referencia;
- N y timestamps exactos;
- conducta si todo el exchange queda sin datos;
- salida al alcanzar `T_corte` sin un lote posterior;
- estado del mercado degradado y criterio de reingreso en una epoca nueva.

Esperar indefinidamente tambien seria una politica posible, pero entonces debe
declararse expresamente y no puede afirmarse que el corte o la espera siempre
terminan.

### B-3 - La barrera de crash no tiene identidad canonica completa

CF-23 basa la recuperacion en `lote_finalizado(T)` y CF-26 dice que los eventos
de dominio deduplican mediante jerarquia CF-9 mas tipo. Sin embargo,
`lote_finalizado`, `frontera`, `estado_inicial` y `epoca_m15` no tienen
`candidate_id`, `order_id` ni `trade_id`. Tampoco existe una preimagen exacta
para sus IDs.

Tras un crash posterior a escribir la barrera pero anterior a persistir estado
auxiliar, dos implementaciones pueden duplicarla, omitirla o elegir distintos
criterios para reconocerla. La afirmacion de reemision idempotente no esta
cerrada para el evento que precisamente define el commit del lote.

Debe definirse `event_id` para TODO tipo de evento. Como minimo:

- `lote_finalizado`: hash canonico de contrato, tipo y `T`;
- `frontera`: hash canonico de contrato, tipo y `T_frontera`;
- `estado_inicial`: hash canonico de contrato, tipo, mercado y frontera;
- `epoca_m15`: hash canonico de contrato, tipo, mercado y `t_inicio`;
- descartes/abstenciones sin orden o trade: su preimagen normativa completa.

La deduplicacion debe realizarse contra el ledger append-only ya escrito, no
solo contra memoria o un indice que pueda quedar adelantado/atrasado tras el
crash. Agregar vectores dorados de estas preimagenes y un crash en cada punto
entre ultimo evento de mercado y barrera.

## Hallazgos mayores

### M-1 - El marcador de hueco no preserva cuando se alcanzo el watermark

CF-27 exige `detected_at`, pero el marcador encadenado de CF-22 solo contiene
`desde`, `hasta` y `gap`. Dos ejecuciones pueden terminar con la misma cadena
de velas/huecos y haber detectado el hueco en timestamps de mercado distintos.
El almacen por si solo no permite reconstruir `detected_at` ni la latencia con
que se liberaron los lotes bloqueados.

El marcador canonico debe incluir el timestamp de mercado que completo el
watermark (o la lista/hash de los N timestamps probatorios). Ese valor debe
alimentar `detected_at` y quedar cubierto por `hash_acum`. Los vectores de CF-22
deben ampliarse con esta evidencia.

### M-2 - Los heads durante catch-up necesitan una definicion de prefijo

Para declarar un hueco, el buffer ya contiene velas posteriores y estas pueden
appendearse antes de que el motor procese los lotes atrasados. CF-25 pide el
head vigente a `ahora`, pero no explicita si se usa el head fisico final del
archivo o el head del prefijo causal correspondiente a `T`.

Debe usarse normativamente el `hash_acum` del ultimo registro cuyo intervalo
sea consumible en `ahora = T`; nunca el head fisico que incluya velas de lotes
posteriores. Un vector con hueco y cuatro lotes liberados en catch-up debe
demostrar heads distintos y causales por evento.

### M-3 - El procesamiento retrasado debe conservar availability operacional

Cuando el lote `T` espera tres cierres posteriores, sus decisiones se calculan
despues en catch-up. Aunque CF-16 impide usar velas futuras en el calculo, el
ledger necesita distinguir `effective_at/available_at = T` de
`processed_at/detected_at` real. De otro modo un resultado forward puede
parecer emitido en tiempo real cuando solo fue reconstruido 45 minutos o mas
tarde.

Agregar `processed_at` causal a los eventos liberados tras watermark y reportar
la latencia. Esto no invalida el estudio descriptivo, pero impide interpretar
la cohorte como politica ejecutable en tiempo real sin evidencia adicional.

## Cierres confirmados respecto de v5

- **B-1 anterior (llegada tardia):** cerrado despues del nacimiento del
  almacen mediante buffer, prefijo continuo y N=3; persiste solo el ancla M15.
- **B-2 anterior (mercado ausente):** cerrado cuando el mercado sigue
  publicando cierres posteriores; falta silencio total.
- **B-3 anterior (frescura bootstrap):** cerrado por transiciones completas y
  gate pre/post frontera.
- **M-1 anterior (heads):** cerrado en contenido; falta definir el head causal
  de prefijo durante catch-up.
- **M-2 anterior (incidencias):** cerrado por `incidencia_id` estable.
- **M-3 anterior (temporalidad dual):** cerrado para eventos de hueco; el
  marcador debe conservar la evidencia de deteccion.

## Evaluacion de CF-22..CF-27

- **CF-22:** watermark y vectores conformes despues del ancla; nacimiento M15
  y evidencia de deteccion incompletos.
- **CF-23:** lotes e inclusion simultanea conformes con fuentes activas;
  silencio total e identidad de barrera no cerrados.
- **CF-24:** conforme.
- **CF-25:** campos conformes; falta seleccionar normativamente el head de
  prefijo en catch-up.
- **CF-26:** incidencias conformes; identidad incompleta para eventos sin
  jerarquia CF-9.
- **CF-27:** semantica dual conforme; provenance de `detected_at` incompleta.

## Hash y vigencia

El SHA-256 del candidato coincide con el commit indicado. El mecanismo de
vigencia es suficiente una vez cerrados los hallazgos: la correccion requiere
protocolo v7 nuevo, hash nuevo, commit nuevo y otra conformidad. No editar v6
para convertirlo en conforme.

## Estado

- Bot3.v1: `SUSPENDIDO`.
- Protocolo v6 candidato (`a342cd10...`): `NO CONFORME`.
- Bot3.v6: `NO IMPLEMENTADO`.
- Cohorte: `NO INICIADA`.
- Implementacion: `NO AUTORIZADA`.
