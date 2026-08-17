# Auditoria independiente - Capa Curso y Bot3 Curso BTA

**Fecha:** 2026-08-17  
**Alcance:** commits `48e99d4`, `05cbad5`, `e0a5a2b`, `88a1ffc` y `5304f08`
(equivalentes publicados en `main`: `abe4698`, `ce963bc`, `0ff0518`,
`2fc5748` y `a1b8031`).  
**Fuentes docentes:** transcripciones originales del `BOOTCAMP MAYO 2025`,
fichas S01-S11, `BITCOIN_TRADERS_SMC_PLAYBOOK.md` `playbook.v1` y la revision
independiente `CLAUDE_INDEPENDENT_REVIEW.md`.  
**Metodo:** revision adversarial de fidelidad, causalidad, aislamiento y
capacidad de evaluacion. No se modifico codigo, configuracion ni protocolo.

## Veredicto

**RECHAZADO.**

La capa Curso conserva correctamente su aislamiento visual y Bot3 no tiene
camino de ejecucion, credenciales ni escrituras sobre el diario real. Sin
embargo, Bot3 no puede iniciar ni acumular forward interpretable en su estado
actual por tres razones independientes:

1. existe look-ahead multi-timeframe reproducible en la disponibilidad de
   rupturas y zonas rectoras;
2. la entrada simulada no representa la confirmacion enseñada: usa cualquier
   iBOS del mismo timeframe, sin la geometria izquierda/derecha y sin operar
   desde la zona creada por el desplazamiento;
3. el supuesto diario es una recomputacion sobre ventanas y zonas truncadas,
   no una cohorte persistente, versionada y auditable.

El resultado actual puede describirse honestamente como un **prototipo paper de
una heuristica inspirada en el curso**. No mide todavia `la estrategia del
curso`, y sus metricas no deben incorporarse a una evaluacion de octubre.

## Hallazgos criticos

### C-1 - Look-ahead HTF por usar el tiempo de apertura como disponibilidad

**Archivos:** `modules/bot3/strategy.py:59-63`, `:109-117`, `:127-139`;
`modules/trading/smc_course.py:448-470`.

Las velas usan `t` como tiempo de apertura; el propio cierre causal se calcula
como `t + duracion` (`modules/trading/smc_live.py:74-89` y
`modules/inteligencia/precio.py:64-71`). No obstante:

- `_rector_dir_series` publica un BOS H4 en `rector[e["j"]]["t"]`, al inicio
  de la vela cuya **cierre** confirma la ruptura;
- `_zone_events` fecha el FVG rector en `candles[i]["t"]`, aunque la tercera
  vela solo completa el FVG al cierre;
- el escaneo M15 comienza inmediatamente despues de ese tiempo de apertura.

Reproduccion con `_bear_scenario` ya incluido en los tests: un evento H4 con
`t=460800000` solo esta disponible causalmente en `475200000`, pero
`_dir_as_of` ya devuelve `long` en `461700000`: **3 h 45 min antes**. Para una
zona rectora nacida en `302400000`, el simulador empieza a aceptar M15 desde
`303300000`, aunque la zona no existe hasta `316800000`.

Esto contamina direccion, toque, confirmacion, entrada y resultado. Un solo
look-ahead invalida el backtest y el forward reconstruido. La capa grafica
tambien puede dibujar retrospectivamente entradas asociadas a una zona HTF
antes de que esa zona estuviera disponible.

**Correccion propuesta:** introducir `available_at_ms` por evento y zona
(`open_t + TF_MS[tf]`), y usarlo en toda union HTF/LTF. Agregar una prueba de
prefix/as-of que prometa que ninguna vela M15 anterior al cierre H4 puede ver el
BOS o FVG rector.

## Hallazgos mayores

### M-1 - La confirmacion implementada no es el iBOS valido del curso

**Archivos:** `modules/bot3/strategy.py:115-149`;
`docs/BOT3_CURSO_PROTOCOLO.md:30-36`.

El codigo acepta el primer `_bos_events(..., INT_PIV)` del mismo sentido dentro
de 30 velas. No exige:

- toma de liquidez a la izquierda;
- creacion de liquidez a la derecha;
- zona nueva creada por el desplazamiento;
- entrada desde esa zona derivada.

La evidencia docente es explicita: S08 **00:39:27-00:41:50** exige tomar
liquidez a la izquierda y crearla a la derecha; si no se crea, el precio puede
formar otro rango y debe evitarse. El modelo completo aparece tambien en S08
**00:36:05-00:41:50** y en el playbook, seccion 7.

Ademas, se confirma siempre en la TF seleccionada. Eso contradice la tabla
docente: zona D -> H1, H4 -> M15, H1 -> M5 y M15 -> M5/M3/M1 (S06
**00:43:13-00:50:50**; S11 **00:31:14-00:32:35**). En Bot3, una zona M15 se
confirma en M15; una zona H4 vista en el libro 1h se confirma en H1. Ambas son
otra estrategia.

La advertencia de que el test mide "ESA concrecion" no basta: se ha eliminado
la condicion que distingue un iBOS valido de uno de liquidez, precisamente el
nucleo del curso. Esto desvirtua el objeto medido.

**Correccion propuesta:** antes de reiniciar forward, modelar por separado
`zone_tf`, `confirmation_tf`, liquidez izquierda, liquidez derecha y zona
derivada. Si no se operacionaliza aun, renombrar Bot3 como proxy experimental y
no atribuir sus resultados al curso.

### M-2 - Faltan gates nucleares y el TP no es el weak target rector

**Archivos:** `modules/bot3/strategy.py:96-169`.

Bot3 no evalua el fractal >=50% ni premium/discount. Tampoco construye el rango
operativo para elegir el objetivo: `_target_as_of` usa swings de la TF
seleccionada (`sh`/`sl_pts` de `sel`) y toma el mas cercano, no el weak high/low
del rango rector.

Estas no son decoraciones:

- fractal valido: S02 **00:16:33-00:41:11**;
- premium/discount coherente con direccion: S04
  **00:38:28-00:44:42**;
- weak como objetivo y finalizacion del rango: S03
  **01:05:15-01:24:54**;
- en confirmacion H4, el TP del ejemplo es el alto H4: S06
  **00:43:13-00:50:50**.

El playbook congelado clasifica fractal, rango/weak y premium/discount en verde.
Omitir los dos gates y reemplazar el weak rector por cualquier liquidez local
modifica seleccion y payoff. Es correccion obligatoria antes de acumular
forward atribuible al curso.

### M-3 - El rango visual no aplica las invariantes que documenta

**Archivos:** `modules/trading/smc_course.py:106-171`;
`docs/SMC_CURSO_V1.md:32-40`.

`_rango` siempre crea strong desde el minimo/maximo entre una ruptura opuesta y
el BOS actual. La toma de liquidez solo se agrega como bandera `sweep`; no es
requisito. Tambien devuelve un rango `en_desarrollo` sin que exista la
finalizacion por swing+iBOS que fija el weak.

El profesor enseña que el strong nace de **toma de liquidez + rompimiento**, y
que la finalizacion/weak requiere swing e iBOS (S03
**01:05:15-01:24:54**). Por ello la documentacion sobreafirma que el algoritmo
implementa el rango causal del curso. El mapa M15 compartido por Hugo (Strong
High aproximado 65,4k y Weak Low 62,2-62,4k) es compatible con la lectura
docente, pero una coincidencia puntual no valida esta heuristica general.

**Correccion propuesta:** fail closed: sin sweep causal no hay strong; sin
finalizacion causal no hay weak cerrado. Separar rango candidato/en desarrollo
de rango finalizado y validar el mapa de Hugo como fixture visual, no como
ajuste de constantes.

### M-4 - El timeframe rector es una simplificacion no enseñada y es internamente inconsistente

**Archivos:** `modules/trading/smc_course.py:46-53`;
`docs/SMC_CURSO_V1.md:34`; `modules/bot3/strategy.py:31`.

El curso enseña jerarquia y eleccion previa por horizonte, no una tabla universal
`TF vista -> rector`. S01 **01:44:15-01:46:39** dice que D, H4 y M15 poseen su
propia estructura principal y que depende del tiempo/horizonte. S09
**00:03:17-00:07:35** declara que no existe una unica estructura principal
intrinseca; debe fijarse segun lo que se busca. S11 **00:31:14-00:32:35**
describe un flujo D -> direccion H4 -> confirmacion M15 -> refinamiento M5/M3.

La tabla es aceptable como hipotesis de producto congelada, no como "la
jerarquia que enseno el profesor". Ademas, la documentacion afirma H4 para
`<=1h`, mientras el codigo asigna `1m -> 1h`. Esa divergencia debe cerrarse.

**Correccion propuesta:** declarar el horizonte como entrada explicita y
versionada; derivar de el rector, zona y confirmacion. Si se conserva una tabla
fija, rotularla `heuristica Bot3.v1`, con contrato y tests consistentes.

### M-5 - La direccion rectora falla abierta cuando es desconocida y no caduca

**Archivo:** `modules/bot3/strategy.py:153-155`.

La regla promete "solo a favor del rector", pero si `rd is None` la entrada se
acepta. En lateralidad, la ultima ruptura antigua permanece vigente sin regla de
expiracion, contradiccion o abstencion. El curso exige definir contexto superior
y reconoce ambiguedad/estructuras alternativas (S09 **00:03:17-00:07:35** y
**01:14:44-01:19:21**).

**Correccion propuesta:** `rd is None` debe abstenerse. Congelar una semantica
para lateralidad, conflicto entre D/H4 y antiguedad maxima; sin ella, reportar
`unknown`, nunca reutilizar indefinidamente el ultimo BOS.

### M-6 - El diario virtual no preserva una cohorte evaluable

**Archivos:** `modules/bot3/module.py:21-24`, `:47-64`, `:81-102`;
`modules/bot3/strategy.py:29-30`, `:106-115`, `:204-205`;
`modules/bot3/public/app.js:31-57`; `docs/BOT3_CURSO_PROTOCOLO.md:45-67`.

No existe un diario append-only. Cada consulta:

- mezcla historia versionada y push actual;
- toma una ventana movil de 8000 barras;
- conserva solo las 300 zonas mas recientes;
- devuelve solo los ultimos 120 trades;
- recalcula estados y resumen desde cero.

Al entrar nuevas zonas, observaciones anteriores pueden salir del universo. No
hay `setup_id`, fingerprint de fuente, manifest, secuencia, snapshot de politica
por operacion ni registro inmutable de descartes. El payload tampoco separa
backtest y forward, aunque el protocolo promete reportarlos separados.

La frontera declarada `2026-08-17 00:00 UTC` precede en 17 h 46 min al commit
del Bot3 (`5304f08`, 2026-08-17 17:46:48 UTC), por lo que etiquetaria como
forward un periodo en que el contrato aun no existia.

**Correccion propuesta:** no activar evaluacion hasta disponer de colector
append-only independiente, politica y codigo por hash, `available_at_ms`, IDs
estables, provenance, gaps explicitos y frontera posterior al despliegue
verificado. El simulador historico debe quedar separado del ledger forward.

## Hallazgos menores

### m-1 - Los parametros congelados no contradicen directamente el curso, pero no proceden de el

**Archivos:** `modules/bot3/strategy.py:25-30`;
`docs/BOT3_CURSO_PROTOCOLO.md:55-60`.

| Parametro | Veredicto docente |
|---|---|
| `STRUCT_PIV=8`, `INT_PIV=3` | No enseñados; concrecion externa U0. |
| `CONF_WINDOW=30` | No enseñado. No equivale a la regla amarilla de diez velas, que es descriptor de reaccion en la TF de la zona y el docente llama "un dato no mas" (S06 00:52:16-00:55:47). |
| `SL_BUFFER=0,1%` | No enseñado; el playbook registra buffer como U0. |
| `ZONE_TTL=2000` | No enseñado; no hay caducidad universal en clase. |
| RR neto `>=2` | Compatible con ejemplos de S06, no umbral universal demostrado. |
| costos `0,12%` | Supuesto externo; debe versionarse por proveedor/mercado. |
| vela ambigua = STOP | Convencion conservadora valida para OHLC, no regla docente. |
| salida completa | Concrecion defendible: BE/parciales carecen de disparador universal. |

La declaracion de defaults amarillos es honesta. Debe mantenerse, pero el
resultado solo valida esa parametrizacion y no el metodo docente abstracto.

### m-2 - La regla universal de dos entradas esta omitida del objeto medido

**Archivos:** `modules/bot3/strategy.py:13`, `:125-126`, `:184-185`;
`docs/BOT3_CURSO_PROTOCOLO.md:41-42`.

S08 **00:52:30-00:53:53** es categorica: dos entradas, riesgo total dividido
(`0,5 + 0,5` para 1%) y dos stops terminan el dia. S11
**02:28:11-02:29:52** conserva el reparto (`0,25 + 0,25`). El playbook la deja
amarilla porque faltan zonas admisibles, correlacion y secuencia.

Es aceptable excluirla de v1 mientras siga amarilla, pero el protocolo debe
declarar que omite una regla universal enseñada. "Una sola posicion" no explica
la diferencia. No debe incorporarse sin un subprotocolo propio.

### m-3 - La frescura existe de forma implicita, pero no esta contratada ni probada para HTF/LTF

**Archivos:** `modules/bot3/strategy.py:34-56`, `:127-145`.

El primer `touch` posterior al nacimiento actua como primer uso, por lo que no
hay una omision total. Sin embargo, no existe estado explicito de mitigacion ni
test que pruebe frescura rectora con disponibilidad causal. S04
**01:04:22-01:10:01** pide zona no mitigada/nuevo extremo y S05
**00:32:12-00:33:02** confirma que refinar no borra la trampa.

## Respuestas obligatorias consolidadas

1. **RECTOR_TF:** sobre-simplificacion externa e inconsistente para `1m`; no es
   la jerarquia cerrada del profesor.
2. **Rango:** coincide solo parcialmente con la nomenclatura y puede coincidir
   con el mapa del 17-ago, pero no exige las condiciones causales de strong y
   weak; no queda validado.
3. **Confirmacion Bot3:** desvirtua la estrategia. La advertencia actual no es
   suficiente para llamarlo forward del curso.
4. **Omisiones:** fractal y premium/discount son correcciones obligatorias;
   dos entradas puede permanecer excluida con declaracion explicita; frescura
   debe hacerse contractual y causal; BE/parciales pueden seguir fuera.
5. **Parametros:** ninguno contradice literalmente una cifra universal del
   curso porque esas cifras no existen; todos, salvo el ejemplo RR>=2, son
   decisiones externas y deben rotularse como tales.
6. **Causalidad:** falla por disponibilidad HTF/LTF (C-1). No se encontro otro
   uso directo de velas posteriores en `_target_as_of`; `confirm_idx` local y la
   resolucion desde `j+1` son correctos.
7. **Aislamiento:** aprobado. No hay import de ejecutor/setups store en Bot3,
   endpoints de escritura, credenciales ni planes `tpsl`; la capa Curso no es
   llamada por `_record_setups`. `execution_enabled` permanece `false`.
8. **Direccion rectora:** falla abierta sin eventos y conserva sesgo obsoleto en
   lateralidad.
9. **Embudo:** los 187 descartes por invalidacion no prueban selectividad del
   curso. Son coherentes con aplicar stop-before-confirm a cientos de OB/FVG,
   pero delatan el universo demasiado amplio y la confirmacion equivocada, no un
   bug en el orden de evaluar invalidacion. Debe reestimarse tras corregir C-1 y
   M-1/M-2.
10. **Protocolo:** insuficiente. Debe congelar disponibilidad temporal,
    persistencia append-only, IDs, hashes/provenance, frontera real de forward,
    tratamiento de gaps/revisiones, posiciones abiertas al corte, regla si el
    deadline llega con n bajo y multiplicidad entre 7 pares x 2 TF.

## Verificaciones positivas

- `_bos_events` respeta `confirm_idx` dentro de una misma temporalidad y exige
  ruptura por cierre/cuerpo.
- `_target_as_of` filtra pivotes no confirmados y liquidez ya barrida hasta `j`.
- La resolucion comienza en `j+1`; una vela que toca SL y TP se asigna a STOP.
- Capa Curso y Bot3 no modifican Bot, bot2, `setups_store` ni
  ECON-COHORT-001.
- `/m/bot3/api` solo expone `state` y `book`; no hay mutaciones ni ordenes.
- Las 15 pruebas existentes pasan, pero no cubren disponibilidad cruzada HTF/LTF,
  iBOS valido, zona derivada, gates fractal/premium, weak rector, `rd=None` ni
  persistencia de cohorte.

## Correcciones priorizadas

1. **Bloquear el forward y excluir toda metrica actual de la evaluacion de
   octubre.** Preservar resultados solo como evidencia de prototipo invalido.
2. **Eliminar el look-ahead multi-timeframe** con `available_at_ms` y pruebas
   prefix/as-of.
3. **Elegir el objeto cientifico:** implementar el modelo docente completo o
   renombrar explicitamente el sistema como proxy; no mezclar ambos.
4. **Implementar confirmacion por TF correcta**, iBOS valido izquierda/derecha,
   zona derivada, fractal, premium/discount y weak rector.
5. **Hacer fail closed la direccion** desconocida/conflictiva y definir
   lateralidad/expiracion.
6. **Separar backtest de forward** y crear ledger append-only con identidad,
   version, provenance, gaps y hashes.
7. **Reescribir el protocolo antes de mirar nuevos resultados**, fijando nueva
   frontera, regla de parada y tratamiento por mercado/TF.
8. Solo despues, reiniciar desde cero un `Bot3.v2` paper. Nada de lo anterior
   autoriza Testnet, Live ni cambios al Bot.

## Estado recomendado

`CAPA CURSO: PROTOTIPO VISUAL AISLADO / CORRECCIONES REQUERIDAS`  
`BOT3 CURSO BTA V1: FORWARD INVALIDO / NO ACUMULAR`  
`BOT / TESTNET / LIVE / ECON-COHORT-001: SIN CAMBIOS`  
`NO TRADING AUTHORIZATION`
