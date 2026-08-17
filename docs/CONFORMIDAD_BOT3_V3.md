# Conformidad pre-implementacion - Bot3.v3 candidato

**Fecha:** 2026-08-17
**Protocolo revisado:** `docs/BOT3_V3_PROTOCOLO.md`
**Commit:** `4bd4152`
**SHA-256 verificado:** `5688f4cf4b073c26533810baa0d45658fe5eddf008907dc50977173057c9be70`
**Diseno rev.3:** SHA-256 `5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`

## Veredicto

`NO CONFORME - CORRECCIONES CONTRACTUALES REQUERIDAS`

CF-6..CF-11 cierran buena parte de los hallazgos anteriores, pero persisten
contradicciones que permiten libros distintos o impiden calcular un cierre
append-only con su PnL definitivo. No se autoriza implementacion ni apertura de
cohorte.

## Hallazgos bloqueantes

### B-1 - Genesis y cobertura minima se contradicen, y M15 no tiene genesis

CF-6 ordena computar toda la estructura H4 desde `GENESIS_H4`, pero permite
procesar con continuidad de solo las ultimas 1000 velas H4. Un motor que carga
desde genesis y otro que carga 1000 velas pueden encontrar rupturas opuestas,
rangos y zonas distintos; ambos podrian considerar satisfecha una parte del
texto. La frase "independiente de cuanta historia cargue" no es realizable sin
estado estructural persistente o sin exigir toda la cobertura desde genesis.

Ademas, el submodelo usa pivotes, liquidez, iBOS y zonas derivadas M15, pero no
congela `GENESIS_M15`. Las ultimas 200 velas no garantizan contener los seis
swings previos ni el estado iBOS que veria una implementacion con mas historia.

Debe elegirse una unica regla:

- continuidad completa H4 y M15 desde un genesis canonico por mercado; o
- checkpoints estructurales append-only, versionados y verificables, cuyo hash
  sea parte de la entrada normativa.

Si falta esa entrada completa, la unica salida debe ser
`historia_insuficiente`. El gate de 1000/200 puede conservarse como requisito
operacional adicional, no como sustituto del genesis.

### B-2 - La precedencia consulta la direccion antes de actualizarla

CF-7 paso 4 cancela una orden por cambio/expiracion de direccion "disponible a
este cierre", pero el paso 5 actualiza BOS, rango y direccion con los eventos
disponibles en ese mismo cierre. Una implementacion puede usar la direccion
anterior en el paso 4 y conservar la orden; otra puede calcular primero el
evento nuevo y cancelarla. Las dos lecturas son razonables y producen libros
distintos.

Debe separarse calculo de aplicacion o cambiar el orden. Una solucion normativa
es: resolver eventos intravela; calcular en una fase pura todos los eventos de
cierre; aplicar funding; aplicar cancelaciones usando el estado de cierre
recién calculado; actualizar estado; arbitrar. La no retroactividad del fill
debe mantenerse.

### B-3 - Salida y funding del mismo cierre chocan con el ledger inmutable

CF-7 resuelve la posicion en el paso 1 y procesa funding en el paso 3. CF-8
ordena cobrar funding cuando la salida comparte el cierre del devengo. Si
`cerrado` se appendea en el paso 1, su PnL todavia no incluye ese cargo y el
ledger inmutable impide corregirlo. Si una implementacion difiere el evento
`cerrado` y otra lo registra inmediatamente, los resultados divergen.

Debe existir un estado transitorio normativo (`salida_detectada` o equivalente):
el precio/motivo de salida se determina intravela, se aplican todos los devengos
del cierre y solo entonces se calcula PnL/R y se appendea un unico evento
`cerrado` definitivo.

## Hallazgos mayores

### M-1 - La fuente canonica sigue siendo mutable y no queda fijada por evento

CF-6 fusiona archivos versionados con push VPS y hace prevalecer el push en
empates. Un backfill o correccion posterior del VPS puede cambiar una vela
historica y, por tanto, toda la estructura desde genesis. La provenance actual
registra fuente y `as_of`, pero no el contenido exacto de las series consumidas.

Debe congelarse una politica de revisiones: rechazar mutaciones de velas ya
cerradas o versionarlas como un nuevo segmento. Cada evaluacion/ledger debe
incluir al menos hash de las entradas H4/M15 o hash encadenado de un snapshot
canonico para que el libro sea reconstruible.

### M-2 - CF-10 no define que precios entran crudos o cuantizados en costos

CF-10 dice que fees, funding, PnL y R usan valores "crudos/cuantizados segun
CF-4", pero CF-4 solo nombra `P_in`, `P_out` y `C_k`; no decide si un fill al
open, una salida con gap, el slippage aplicado o `C_k` pasan por `Q` antes del
calculo. Dos motores pueden producir R e IDs distintos.

Debe congelarse, campo por campo:

- si `P_in = Q(open)` en gap o conserva el open float64;
- si `P_out` se cuantiza antes o despues del slippage;
- si `C_k` se cuantiza;
- si la cuantizacion posterior usa half-even y en que unico punto ocurre;
- que valor exacto alimenta `fill_precio` del `trade_id`.

Agregar vectores dorados numericos con al menos: empate half-even, fill favorable
al open, gap-SL largo/corto, slippage y un devengo de funding.

### M-3 - El mecanismo de datos no define el instante de `ahora`

CF-6 busca eventos en `[GENESIS_H4, ahora]`, mientras el motor se define por
velas M15. Para una reproduccion historica, `ahora` debe ser exactamente
`close_time(m)` y solo deben entrar velas H4 con cierre menor o igual a ese
instante. Usar reloj de pared o todas las velas cargadas reintroduciria
informacion futura.

## Evaluacion de las clausulas nuevas

- **CF-6:** no conforme; genesis H4 y cobertura 1000 se contradicen, falta
  genesis/estado canonico M15 y las fuentes pueden mutar.
- **CF-7:** no conforme; cancelacion por direccion precede al calculo de esa
  direccion y falta diferir el cierre hasta completar funding.
- **CF-8:** conforme en la seleccion causal de `C_k` y sus desigualdades;
  requiere integracion de ciclo de vida descrita en B-3.
- **CF-9:** conforme. Las preimagenes y el algoritmo de hash son univocos.
- **CF-10:** parcialmente conforme; SL y Q estan definidos, pero falta decidir
  raw versus Q en fill, salida, slippage y funding.
- **CF-11:** conforme. El timestamp fue verificado como
  `2026-12-31T23:59:59.999Z`, inclusivo.

## Hash y vigencia

El mecanismo es suficiente en principio: SHA-256 del texto, commit Git y regla
"cambio = v4 + cohorte nueva" forman un pre-registro verificable. No debe
editarse este archivo para cambiar `PENDIENTE` por `CONFORME`; la siguiente
version corregida necesita archivo/hash/commit nuevos y otra pasada. Este
informe vincula el dictamen al hash v3 candidato revisado.

## Estado

- Bot3.v1: `SUSPENDIDO`.
- Protocolo v3 candidato (`5688f4cf...`): `NO CONFORME`.
- Bot3.v3: `NO IMPLEMENTADO`.
- Cohorte: `NO INICIADA`.
- Implementacion: `NO AUTORIZADA`.
