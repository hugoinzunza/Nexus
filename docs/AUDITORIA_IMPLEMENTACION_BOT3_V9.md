# Re-auditoria de implementacion - Bot3.v9

**Fecha:** 2026-08-17  
**Implementacion revisada:** commit `25357858b0af1c87a04b38e57e16c59e52be5c60`  
**Protocolo:** `docs/BOT3_V9_PROTOCOLO.md`  
**contrato_hash verificado:** `9d24166a33aa74af7f2b2dd7d0bdf4e2d16866e13eec7c48e7b1480512001530`

## Veredicto

`NO CONFORME / NO DESPLEGAR / NO INICIAR COHORTE`

Los vectores numericos y registrales reproducen el contrato, pero el ciclo
integrado no implementa varias invariantes causales y operacionales obligatorias.
Los defectos cambian la inclusion de candidatos y el contenido del libro; no son
solo deuda de observabilidad.

Bot3.v1 permanece suspendido. Esta auditoria no autoriza Bot, Testnet, Live,
despliegue ni cohorte forward.

## Hallazgos bloqueantes

### B-1 - El futuro fisico del almacen cambia decisiones de prefijos pasados

En `engine.py`, la habilitacion M15 comprueba `len(ep) >= 200` sobre la epoca
fisica completa y no sobre las velas cerradas en `T`. Una epoca con 220 velas
cargadas queda habilitada cuando en el reloj causal solo han cerrado 10.

La validacion H4 presenta la misma clase de defecto: calcula `h4 = velas_hasta(T)`
pero exige `len(alm.epocas()) == 1` sobre todo el almacen. Un hueco situado despues
de `T` convierte retrospectivamente un resultado anterior en
`historia_insuficiente`.

Reproducciones:

- M15: `closed_at_T=10`, `physical_epoch=220`, resultado `enabled=True`.
- H4, mismo prefijo causal: sin hueco futuro produce
  `direccion_desconocida`; al agregar un hueco posterior produce
  `historia_insuficiente`.

Esto viola CF-13/CF-16 y la invariancia por prefijo. El gate actual carga el
mismo futuro fisico en ambas corridas, por lo que no puede detectar el defecto.

Referencias: `modules/bot3/v9/engine.py:177`, `modules/bot3/v9/engine.py:339`,
`tests/test_bot3_v9_prefijo.py:59`.

### B-2 - La confirmacion M15 esta invertida respecto del contrato

En la vela del toque H4, `_fase7` consume inmediatamente la frescura de la zona
y llama `_confirmar`. Esa funcion solo inspecciona `ep[ini:k]`, es decir, velas
anteriores o iguales al toque. Si todavia no existe iBOS, devuelve `None`; en
velas posteriores la zona ya figura en `zonas_tocadas` y nunca vuelve a
considerarse.

Por tanto, la implementacion:

- acepta un iBOS anterior al toque;
- no puede esperar el primer iBOS posterior al toque durante hasta 48 velas;
- no conserva un candidato vivo mientras aparece la confirmacion;
- no modela la secuencia toque -> toma izquierda -> iBOS -> zona derivada ->
  orden -> retest.

Ademas, la zona derivada se elige entre cualquier OB/FVG historico anterior al
iBOS y no especificamente entre los creados por su desplazamiento. Esto explica
la frecuencia anormalmente baja observada y significa que el libro implementado
no representa la fila H4 -> M15 congelada.

Referencias: `modules/bot3/v9/engine.py:394`, `modules/bot3/v9/engine.py:436`,
`modules/bot3/v9/engine.py:468`, `docs/BOT3_V2_DISENO_CONTRACTUAL.md:49`.

### B-3 - La frontera forward y el estado inicial no existen en el motor

`bootstrap_hasta` solo silencia escrituras. No existe una transicion al cruzar
la frontera que fuerce `orden_viva`, `posicion` o `salida_detectada` a `flat`,
ni se emiten `frontera` y `estado_inicial` con provenance.

Una posicion sintetica mantenida durante bootstrap continua en `posicion` al
procesar el primer lote posterior a la frontera. El ledger solo recibe
`lote_finalizado`.

El gate denominado `test_cf24_frescura_sobrevive_a_la_frontera` no ejecuta el
motor: crea un `EstadoMercado`, inserta manualmente una clave en un set y la
vuelve a leer. No prueba CF-21/CF-24.

Referencias: `modules/bot3/v9/engine.py:138`, `modules/bot3/v9/engine.py:151`,
`tests/test_bot3_v9_gates.py:349`, `docs/BOT3_V6_PROTOCOLO.md:77`.

### B-4 - Watermark global, finalidad y corte administrativo no estan integrados

`store.py` contiene funciones de prueba y declaracion de hueco exchange, pero
`runner.py` nunca las invoca. Ante un mercado ausente, el runner omite el lote y
continua; no degrada el mercado, no declara el hueco, no crea una epoca de
reingreso y no finaliza el lote con el maximo `detected_at` de sus marcadores.

El corte CF-35 tampoco esta implementado. El primer `T > T_CORTE` corta de forma
inmediata segun tiempo de mercado, sin esperar `T_corte + 24 h` del reloj de
pull, sin comprobar ausencia de lote global posterior y sin emitir
`corte_administrativo` ni `degradacion_de_cobertura`.

Reproduccion del gate actual: `cortado=True`, lista de eventos vacia,
`has_admin=False`, `coverage=False`. El test solo comprueba la bandera y el
motivo `tiempo`, por lo que aprueba una conducta distinta de CF-35.

Referencias: `modules/bot3/v9/runner.py:66`, `modules/bot3/v9/store.py:289`,
`modules/bot3/v9/engine.py:209`, `modules/bot3/v9/engine.py:522`,
`tests/test_bot3_v9_gates.py:284`.

### B-5 - Los gates operacionales exigidos por la conformidad pre-implementacion fallan

Los eventos globales no llevan el mapa canonico de heads duales de los siete
mercados. `_emit` agrega heads solo si recibe un mercado; `lote_finalizado` se
emite sin mercado. `processed_at` cae por defecto en `T`, aunque la finalidad
sea posterior, y el runner no aporta reloj observado. Tampoco existe el calculo
del maximo de varios marcadores que hicieron finalizable un lote.

Reproduccion con un lote finalizado 45 minutos tarde:

- `effective_at=T`;
- `finalized_at=T+45m`;
- `processed_at=T`;
- `input_head_asof_T` ausente;
- `provenance_head_at_finality` ausente.

Falla G1, G2 y G3 del informe de conformidad pre-implementacion. Cualquiera de
ellos rechazaba expresamente la implementacion.

Referencias: `modules/bot3/v9/engine.py:156`, `modules/bot3/v9/engine.py:219`,
`docs/CONFORMIDAD_BOT3_V9.md`.

## Hallazgos mayores

### M-1 - Recovery no reconstruye almacen ni estado del motor

`Almacen(ruta=...)` siempre nace vacio y nunca relee el archivo existente.
El runner, ademas, crea almacenes sin ruta. Tras un reinicio no se reconstruyen
buffer, marcadores, incidencias ni estado del motor desde el ultimo
`lote_finalizado`.

La supuesta matriz de crash solo escribe una lista fija de eventos directamente
en `Ledger`, lo vuelve a abrir y comprueba dedupe. No interrumpe ni reejecuta el
motor entre fases, no restaura el estado y no compara ledgers byte a byte.

Referencias: `modules/bot3/v9/store.py:64`, `modules/bot3/v9/runner.py:31`,
`tests/test_bot3_v9_gates.py:296`.

### M-2 - El head causal congelado sub-identifica inputs consumidos

El propio gate documenta que, durante catch-up posterior a un hueco,
`input_head_asof_T` queda detenido antes del marcador aunque el modelo ya consume
velas posteriores. El evento no identifica todos los bytes usados para producir
la decision.

Este punto no puede corregirse cambiando silenciosamente v9: la semantica y la
cadena congeladas requieren una aclaracion contractual v10 antes de iniciar una
cohorte cientificamente reconstruible.

Referencia: `tests/test_bot3_v9_gates.py:329`, `modules/bot3/v9/store.py:198`.

### M-3 - Disponibilidad causal incompleta en el sweep y arbitraje incompleto

El sweep del origen selecciona pivotes confirmados antes del extremo `k0`, pero
permite que cualquier vela anterior del tramo los barra aunque esa vela ocurra
antes de `confirm_idx`. Eso consume como liquidez un pivote todavia no disponible
en el momento del supuesto sweep.

Ademas, `descartada_por_arbitraje` no conserva referencia al ganador, pese a que
el diseño lo exige, por lo que la decision de arbitraje no queda completamente
auditable.

Referencias: `modules/bot3/v9/primitives.py:204`,
`modules/bot3/v9/engine.py:424`, `docs/BOT3_V2_DISENO_CONTRACTUAL.md:84`.

## Verificacion ejecutada

- SHA-256 del protocolo: coincide exactamente con el `contrato_hash` compilado.
- Gates Bot3.v9: `29 passed`.
- Suite `tests/`: `851 passed`, 2 warnings.
- `python3 -m compileall -q modules/bot3/v9`: correcto.
- `git diff --check`: correcto.
- Activacion productiva de `modules/bot3/v9`: no encontrada.
- Test root sin `PYTHONPATH=.`: 12 errores de coleccion de `research/` por
  imports, ajenos a Bot3.v9; la suite canonica `tests/` pasa.

Los tests verdes confirman vectores y varias funciones locales. No refutan los
hallazgos anteriores porque los gates afectados son vacuos, parciales o prueban
el componente sin el ensamblado real.

## Before / after esperado para una correccion

Antes de una nueva re-auditoria deben existir reproducciones que demuestren:

1. cargar futuro fisico no cambia habilitacion M15 ni continuidad H4 as-of;
2. el candidato sobrevive desde el toque y solo acepta iBOS/zona derivada
   posteriores y causales;
3. bootstrap cruza frontera en `flat`, emite frontera/estado inicial y conserva
   frescura real;
4. silencio local/exchange converge a lotes finalizados con degradacion y
   reingreso deterministas;
5. CF-35 se dispara por reloj observado y emite toda su evidencia;
6. crash entre fases recompone almacen, estado y ledger byte a byte;
7. cada evento global porta los heads de los siete mercados y temporalidad
   triple correcta;
8. el defecto contractual del head post-hueco queda resuelto mediante v10.

## Estado final

- Bot3.v9 implementacion: `RECHAZADA`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte forward: `NO INICIAR`.
- Bot3.v1: `SUSPENDIDO`.
- Bot/Testnet/Live: `SIN CAMBIOS / SIN AUTORIZACION`.
- Proximo paso recomendado: separar primero el defecto contractual M-2 en un
  candidato v10 minimo; despues corregir implementacion y gates adversariales.

