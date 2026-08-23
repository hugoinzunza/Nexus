# Bot3.v13 — Observador operativo · DISEÑO rev.28

**Estado: DISEÑO rev.28 — §20 acotada: la acreditación se invoca contra un
checksum esperado, y toda salida clausura el trabajador. §1–§19 y §13 no se
reabren. No desplegado. Cohorte no iniciada.**
Contrato del motor: `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d` (congelado, no se toca).

rev.28 cierra dos bloqueos: la máquina de acreditación exigía al segundo
operador comprobar que su acto fuera idéntico, pero tras el primero ya no queda
`fallo_cerrado.json` y el segundo caía en «no-op» sin poder comparar nada; y
nada definía qué pasa con el proceso trabajador cuando el padre termina por
cualquier vía que no sea el deadline — en macOS no hay garantía de que el hijo
muera con el padre.
rev.27 cierra tres problemas ejecutables: §20.4 y §20.4.1 se contradecían
sobre qué se reintenta y el campo `error` no tenía enum; `poll` sin
`O_NONBLOCK` no garantiza el deadline, porque un descriptor marcado escribible
puede aceptar menos bytes de los que el `write` intenta poner; y la
acreditación humana, que son dos artefactos y varias operaciones, no era
recuperable ante una caída intermedia ni estaba serializada.
rev.26 cierra tres puntos del IPC: descartar una respuesta con ID ajeno hacía
que una corrupción del protocolo pareciera un deadline de red reintentable; el
deadline arrancaba DESPUÉS de una escritura que puede bloquear, así que no era
cota total; y la «intervención humana» del gate 48bis no tenía herramienta,
campos ni procedimiento.
rev.25 cierra dos bloqueos de rev.24: el gate 48bis prometía que «el arranque
siguiente continúa» tras un `SIGKILL`, contradiciendo la propia taxonomía
—toda muerte por señal clasifica `codigo: 1` y BLOQUEA—; y el protocolo del
trabajador de transporte quedaba en «devuelve el cuerpo por una tubería», que
no determina ni cuándo empieza el deadline ni cómo se descartan las respuestas
de una generación muerta.
rev.24 corrige que rev.23 declaró «fase A junto con la publicación» como un
tramo indivisible, **contradiciendo §9.1.1**, que congela exactamente lo
contrario: fase A → liberar barrera → ventana de recolección → fase B. Y le da
al `REQUEST_DEADLINE` un mecanismo que realmente lo garantice: ningún timeout
de socket acota una resolución DNS bloqueada, porque el socket todavía no
existe.
rev.23 cierra dos cotas que rev.22 declaró sin serlo:
`CONNECT_TIMEOUT + READ_TIMEOUT` no acota una petición —`READ_TIMEOUT` limita
la inactividad entre lecturas, no la duración total, y un servidor que gotea
bytes la sostiene para siempre—, y la fase posterior del ciclo, declarada
indivisible, no tiene duración acotada tras una caída larga. Además congela una
primitiva de archivado realmente exclusiva: `rename` no tiene `O_EXCL`.
rev.22 cierra dos contradicciones ejecutables de rev.21: `ExitTimeOut` no
tenía cota —una señal dentro de una petición HTTP no encontraba ningún punto
de cancelación, y los timeouts de transporte ni siquiera estaban congelados—,
y la fila «falla el wrapper al escribir» exigía un documento que, por
definición, no se pudo escribir. Además hace el archivado append-only y
corrige una afirmación demasiado fuerte sobre el replay.
rev.21 cierra dos bloqueos de rev.20 en la ruta de diagnóstico: el primer
transitorio bloqueaba TODOS los reintentos —el arranque rechazaba cualquier
`fallo_cerrado.json`, así que `MAX_TRANSITORIOS` era inalcanzable y la cota no
existía—, y la recuperación de un daemon muerto por señal producía un
documento que el propio schema rechazaba, porque `128+N` no es `1` ni `2`.
Además serializa la activación y hace explícita la durabilidad del rename
exterior.
rev.20 cierra tres bloqueos de rev.19: §20.2 creaba un `Motor` VACÍO y pasaba
directo a `reanudar()` —el motor no persiste candidatos, órdenes, posiciones ni
`lotes_finalizados`, y su recuperación contractual es por replay—; el wrapper
tenía que registrar «la excepción» sin más canal que el código de salida; y
`ExitTimeOut = 300 s` contradecía «terminar el ciclo» contra los 402 s de
replay que el ensayo a escala ya midió. Además hace recuperable la activación,
acota la taxonomía transitoria —`ENOSPC` y `EIO` NO son transitorios y el lock
ocupado significa que hay otra instancia sana— y da tratamiento registral a
`fallo_cerrado.json`.
rev.19 cierra §20, acotada exclusivamente a esa sección y sus gates. rev.18
tenía dos bloqueos operacionales: la política de reinicio NO era realizable
—`KeepAlive.SuccessfulExit=false` reinicia ante cualquier salida no cero, así
que `1` y `2` eran indistinguibles para launchd—, y nadie creaba el estado
inicial que §20.2 exige cargar, con §20.7 prohibiéndoselo al propio servicio:
el primer lanzamiento fallaba cerrado siempre.
rev.18 agrega §20, el punto de entrada y el servicio, que hasta acá no existía
en ninguna sección: §15 congela los parámetros pero nadie decía en qué ORDEN
arranca el proceso, quién lo reinicia, ni cuándo sale. Es aditiva: §1–§19 no
cambian, y §13 queda tal como se aprobó contra rev.17.
rev.17 corrige una INCOMPATIBILIDAD entre §13.4 y §9.1.3 que hacía
inalcanzable la ruta principal del diseño: «el hash de CADA sidecar» congelaba
`verificacion.json`, pero la comparación fría lo REESCRIBE al pasar de
`pending` a `ok` —que es el disparador normal de la fase B—, así que el estado
autorizado nunca podía coincidir y la cohorte no cerraba jamás. rev.17 la
reemplaza por una identidad de CAPTURA con transiciones autorizadas (§13.4.1),
que conserva la causalidad sin congelar bytes mutables.
rev.16 agrega el tercer disparador de la fase B —el arranque— que §9.1.3
omitía aunque §13.5 lo exigiera. rev.15 corrigió que el orden congelado en
rev.14 era literalmente indeadlockable
—mandaba readquirir un mutex ya retenido—, declara quién dispara la fase B tras
un corte científico, y separa borrar de archivar. rev.14 congeló el ORDEN del
final del ciclo, que era el agujero de la
demostración de §13.5.0: con el orden de rev.13, un corte podía ser seguido por
una deferencia ANTES de registrar la causa científica, y esa combinación
—declarada imposible— habría fallado cerrado ante una secuencia legítima.
rev.13 normalizó la condición que cierra la ventana: la hace depender del
ganador actual, resuelve `deferred` sin productor activo, garantiza que un
`divergent` observado esté SIEMPRE en el request antes de calcular el ganador,
y declara quién reactiva la fase B. Acotada a §9.1.2/§13.5 y sus gates.
rev.12 cerró la CONCURRENCIA de la transición: parte la barrera en fase de
registro y fase de publicación, define qué evento cierra la ventana de
recolección, e impide que un silencio le gane a una divergencia que todavía se
está calculando. rev.11 cerró los puntos registrales que rev.10 dejó abiertos: el ORDEN de la
transición, el flujo de §9.1.1 como terminal y no solo como bloqueo, la
comparación normativa terminal/request, la salida de la verificación pendiente
tras un reinicio y los gates del contrato nuevo. rev.10 fue una revisión
REGISTRAL de rev.9, acotada a la transición
terminal: completa la precedencia de los cinco motivos, acota cuándo un
terminal publicado domina un request residual, define la matriz de reanudación,
versiona el schema y RECONCILIA las reglas de rev.8 que la ampliación dejó
contradictorias. rev.9 fue una revisión mínima acotada a §13/§9.1.1: la
transición terminal. La arquitectura de rev.8 no se reabre; lo que se corrige es que la
implementación amplió el alcance de `terminal.request` a los cortes
CIENTÍFICOS sin que el diseño lo dijera, y de esa discordancia salieron cuatro
rondas de parches que abrían rutas nuevas. Ver §13.2.

rev.8 fue la **revisión registral final** de la arquitectura y responde a
`docs/AUDITORIA_BOT3_V13_OBSERVADOR_DISENO_REV7.md`: resuelve la contradicción
entre los gates 21 y 38, persiste `run_epoch` y cierra la protección de los dos
artefactos persistentes. La arquitectura quedó aceptada en rev.7 y no se reabre. Se pre-registra y se audita ANTES de escribir una línea de
implementación.

---

## 0. Por qué existe este documento

`modules/bot3/v9` no tiene punto de entrada de producción: sin `__main__`, sin
llamador fuera de `tests/`, sin servicio launchd; `correr()` no expone la ruta
de push; y CF-28 prohíbe cambiar el snapshot tras el nacimiento. Hoy no existe
forma de incorporar una vela nueva a una cohorte viva. El observador es esa
pieza, y como escribe el libro forward es parte de la máquina científica.

## 1. Alcance

**Hace:** pull de velas cerradas desde la API pública de Binance, las ofrece al
almacén como `push`, corre el ciclo del motor, persiste estado y libro.

**No hace:** ejecutar órdenes, tocar credenciales, conectarse a Bot, Testnet o
Live, ni modificar snapshots canónicos.

## 2. Identidad y aislamiento

| | |
|---|---|
| Servicio | `com.hugo.nexux-bot3v13-observador` (launchd, propio) |
| Config | `modules.bot3v13`, namespace nuevo |
| Estado | `~/Library/Application Support/NexUX/Bot3/v13/state` |
| Libro | `~/Library/Application Support/NexUX/Bot3/v13/ledger/events.jsonl` |
| Universo | ADA, BNB, BTC, DOGE, ETH, SOL, XRP — fijo |
| Timeframes | **H4 y M15**, ambos |

`modules.bot3` describe el Bot3.v1 suspendido (`timeframes: ["15m","1h"]`) y no
se modifica. El observador no lee esa clave ni comparte proceso, estado ni libro.

---

# Provenance del almacén

## 3. El manifiesto no guarda estado mutable

*(aprobado conceptualmente en rev.2)*

| campo | qué es |
|---|---|
| `ancla`, `snapshot_ruta`, `snapshot_sha256`, `commit_snapshot`, `hash_acum_inicial` | ya existen |
| `snapshot_record_count` | **nuevo**: nº de registros al terminar el nacimiento |
| `snapshot_head` | **nuevo**: `hash_acum` del último registro de nacimiento |
| ~~`head`~~ | **se elimina**: era el único campo mutable |

Recuperación: `cargar()` revalida la cadena desde `SEMILLA`; se verifica
`registros[snapshot_record_count − 1]["hash_acum"] == snapshot_head`; el resto
es sufijo append-only autenticado por la propia cadena. No queda nada que
actualizar por ciclo, así que no hay transacción que coordinar.

## 4. Nacimiento atómico: un solo rename *(rev.4 — MAJOR 2)*

Una caída durante el primer nacimiento no puede dejar unos almacenes
interpretados como cohorte nacida y otros como primer arranque.

rev.3 hacía 14 `os.replace` uno a uno antes de publicar el manifiesto: una
caída a mitad dejaba archivos ya definitivos y otros en staging, y la regla
«descartar `staging/`» no los alcanzaba. Se publica **un directorio completo
con un único rename**:

```
1. materializar los 14 almacenes COMPLETOS en state/almacenes.new/
2. fsync de los 14 archivos y del directorio almacenes.new/
3. os.replace(state/almacenes.new, state/almacenes)   ← ATÓMICO, uno solo
4. fsync del directorio state/
5. escribir manifest.json.tmp → fsync → os.replace → fsync del directorio
```

`os.replace` sobre directorios es atómico dentro del mismo filesystem, y
`state/almacenes` no existe antes del nacimiento. No hay estado intermedio con
algunos almacenes publicados y otros no.

El manifiesto definitivo es el **único** testigo de nacimiento. Mientras no
exista, se descartan `almacenes.new/` **y** `almacenes/` —esta última en
cuarentena, no borrada— y se renace desde cero. Un manifiesto presente exige
los 14 almacenes presentes y consistentes con sus prefijos; si falta uno,
fallo cerrado.

## 5. Durabilidad: el almacén antes que el libro *(rev.4 — BLOCKER 2)*

**Verificado: hoy no hay un solo `fsync` en `store.py` ni en `ledger.py`.**
Nada es durable en ningún punto, y el orden en que el sistema operativo baja
las páginas a disco es arbitrario.

El orden de rev.3 —fsync de almacenes y *después* procesar— no alcanza:
`watermark_exchange(T)` appendea un marcador al almacén DURANTE
`procesar_lote` y emite `hueco_detectado`/`mercado_degradado` acto seguido. Una
caída podía dejar durable el evento y perdido el marcador que lo justifica.

Regla, para **cada** transición almacén→libro:

```
1. append del marcador al almacén
2. flush + fsync de ESE almacén          ← antes de que exista el evento
3. append de sus eventos al libro
4. flush + fsync del libro al cerrar el ciclo
```

Implementación: `Almacen` gana un **modo durable** que hace `flush`+`fsync` en
cada `_append`. Se activa solo en el observador, después del nacimiento; el
replay de bootstrap corre sin él (un `fsync` por vela sobre ~1M velas es
inviable, y ahí nada depende del orden porque no se emite al libro).

Coste en operación: ~14 `fsync` por ciclo de 15 minutos. Despreciable.

Esto cambia `store.py`, dentro del alcance de código de Bot3 → su propia ronda
de auditoría de implementación. No es cambio de contrato.

### 5.1 Escritura desgarrada: encuadre con longitud y hash *(rev.5 — BLOCKER 2)*

`fsync` ordena la durabilidad pero **no hace atómico un registro**. Una caída
puede dejar la última línea truncada, y hoy `Almacen.cargar()` y
`Ledger._releer()` parsean línea a línea: una cola rota falla cerrado, lo que
contradice la recuperación exacta que exige el gate de durabilidad.

Los dos archivos —almacén y libro— adoptan **el mismo encuadre**:

```
<longitud_bytes>\t<sha256(payload)>\t<payload>\n
```

**Gramática del encabezado**, normativa: `^([0-9]{1,9})\t([0-9a-f]{64})\t`.
`longitud_bytes` es el tamaño exacto del `payload` en bytes UTF-8.

Regla de lectura, única para ambos *(rev.6 — corregida)*. **El único criterio
de truncación es la ausencia del `\n` final**:

| condición | interpretación | acción |
|---|---|---|
| trama termina en `\n` y encabezado, longitud, hash, UTF-8 y payload son todos válidos | registro bueno | se acepta |
| trama termina en `\n` y **cualquiera** de esos falla | **corrupción** | **fallo cerrado** |
| ÚLTIMO segmento del archivo **sin `\n`** | **truncación** por caída | se descarta y se recupera por replay |
| cualquier segmento NO final | nunca es truncable | **fallo cerrado** si falla algo |

rev.5 clasificaba `bytes < longitud` como truncación, y eso era un agujero: un
campo de longitud corrompido **hacia arriba** en una trama que sí termina en
`\n` se habría descartado como torn write. El hash cubre el payload, no el
encabezado, así que el encabezado no puede ser juez de su propia integridad.
Con la regla nueva, el newline final —que el SO escribe al final de la trama—
es el único testigo de completitud.

La distinción truncación / corrupción es explícita: **no se ignora una última
línea inválida sin clasificarla**. Solo la última trama incompleta puede
descartarse, y su ausencia se recupera reprocesando —el almacén por re-pull
desde `ultimo_t`, el libro por reemisión idempotente vía `event_id`.

El encuadre **no cambia ninguna identidad**: `hash_acum` encadena `payload`, y
`Ledger.firma()` hashea los eventos canónicos. El marco es contenedor, no
contenido.

Cambia el formato en disco de `store.py` y `ledger.py`. Nada desplegado lo usa
todavía, así que el costo es cero — pero exige su propia ronda de auditoría de
implementación.

---

# Dependencia H4

## 6. Precondición de frescura H4

`lote_finalizable(T)` inspecciona SOLO M15 (`engine.py:293`). Verificado.

El observador **no procesa ningún lote `T`** hasta que, para los 7 mercados, la
grilla H4 esté resuelta hasta `T`:

- **grilla esperada**: toda `t_h4` múltiplo de `DUR_H4` con `t_h4 + DUR_H4 ≤ T`,
  desde `GENESIS_H4`;
- **resuelta** significa `alm_h4.cubre(t_h4) ∈ {"vela", "hueco"}` para cada una.

`LAG_MAX` se evalúa **por mercado y por timeframe**: 14 evaluaciones.

### 6.1 Watermark H4: solo local

`prueba_local` y `hueco_pendiente` usan `self.dur`: son **genéricas por TF** y
funcionan en H4 sin tocar nada (`store.py:285`). El observador usa esa
maquinaria tal cual, con `WATERMARK_LOCAL_N = 3` cierres H4 posteriores.

**No se define watermark exchange para H4.** `prueba_exchange` está acoplada a
M15 (`TF_MS["15m"]` fijo) y darle semántica H4 —Q, N, prueba, `detected_at`—
sería inventar contrato. Queda explícitamente fuera: si una vela H4 falta, se
espera la prueba local.

Los gaps H4 locales ya llegan al libro como `hueco_detectado(tf="4h")` por la
vía canónica del motor, con heads y finalidad completos.

**Prohibido** reutilizar `mercado_degradado` / `mercado_reingresado` —que son
M15 por CF-29— para fabricar continuidad H4.

### 6.2 Consecuencia, que ya está en la máquina congelada

Un hueco H4 sellado parte las épocas, y `_calcular_h4` (`engine.py:688`) exige
época única continua desde `GENESIS_H4`: ese mercado devuelve
`historia_insuficiente` y se abstiene, **mientras los demás continúan**. No hay
que definir nada nuevo: es la regla vigente.

### 6.3 Emisión del marcador H4 en el daemon largo *(rev.4)*

Declarar el hueco en el almacén **no escribe por sí solo** el evento del libro:
en `correr()` esa emisión ocurre una vez, al arrancar. El daemon largo cablea
explícitamente, tras cada `declarar_hueco_local()` que devuelva un registro, la
emisión de `hueco_detectado(tf="4h")` por la vía canónica del motor —con heads,
finalidad y `event_id` completos— exactamente una vez.

### 6.4 Latencia de sellado *(rev.4, corregido)*

Sellar un hueco H4 exige 3 cierres H4 propios posteriores. Bajo **reanudación
normal** eso son **12 h + `MARGEN_CIERRE` + una `CADENCIA`**, no 12 h exactas: la
latencia real incluye el margen de cierre, la cadencia del ciclo, la red y
cualquier prolongación del silencio.

**No es una cota incondicional.** Si el mercado no vuelve a publicar, no hay
tres cierres propios y el hueco no se sella nunca. Eso es §6.5.

Durante la espera el lote global no avanza. Es fail-closed a propósito: la
alternativa es decidir con un rector congelado. Al sellarse, el backlog se
procesa en `catch-up` (§11).

### 6.5 Salida del silencio H4 permanente *(rev.4 — BLOCKER 3)*

Confirmado: con solo watermark local, un mercado permanentemente mudo bloquea a
los siete para siempre. El `catch-up` no lo resuelve, porque depende de la misma
fuente ausente.

La auditoría ofrece dos salidas y recomienda la primera. **Se elige la segunda,
y esta es la razón.**

Un watermark exchange H4 no sería «puramente observacional». Su prueba produce
un **marcador sellado en el almacén H4**, ese marcador entra en la cadena de
hashes, parte las épocas y cambia lo que `_calcular_h4` decide. Es semántica
causal nueva —Q, N, prueba, `detected_at`— inventada fuera del contrato
congelado, sobre la TF que gobierna el rector. Después de ocho rondas
estableciendo que inventar semántica es exactamente como se contamina la
evidencia, no voy a hacerlo para comprar liveness.

**La liveness se obtiene con un estado terminal, no con una prueba fabricada.**

`SILENCIO_MAX_H4`, parámetro congelado en el protocolo. rev.4 lo dejaba sin
reloj ni origen, y así dos implementaciones honestas bloquean en instantes
distintos, o confunden una caída del daemon con un mercado mudo. Definición
normativa *(rev.5)*:

| | |
|---|---|
| **Inicio** | el primer cierre H4 esperado que ya es elegible según `eligibility_time` y que **falta después de una paginación válida y COMPLETA** de Binance para ese mercado y TF |
| **Reloj** | `eligibility_time` de Binance. Nunca `processed_at`, nunca «tiempo desde el último ciclo local» |
| **Evidencia** | solo una respuesta válida y completa que no trae la vela hace avanzar el silencio. Error HTTP, timeout, `eligibility_time` indisponible y **daemon apagado** NO lo avanzan |
| **Ámbito** | solo la cohorte activa, después de que la activación declaró los 14 streams frescos. **Nunca** durante el nacimiento ni durante el catch-up prefrontera |
| **Comparador** | `evidencia_acumulada_ms > SILENCIO_MAX_H4` (§6.5.1), NO una resta de relojes |
| **Persistencia** | sidecar atómico `silencio.json` con el origen y su evidencia. **No se reinicia al relanzar el daemon** |

`blocked.json` por este motivo lleva: mercado, TF, primer cierre faltante,
último cierre H4 válido, instante de inicio, umbral, el `eligibility_time`
decisivo y la evidencia de las consultas que lo sostienen.

### 6.5.1 Máquina de silencio *(rev.7 — BLOCKER 1, reescrita)*

rev.6 arregló el comparador pero dejó la máquina incompleta: sin inicialización,
sin resolución, sin multiplicidad, sin reloj anómalo y sin duplicados. Dos
implementaciones honestas producirían `silencio.json` distintos.

#### Estructura

`silencio.json` es un **mapa canónico** con clave `(mercado, tf, primer_cierre)`
—orden total: `mercado` asc, `tf` asc, `primer_cierre` asc— y cada entrada:

| campo | qué es |
|---|---|
| `estado` | `activo` \| `resuelto` |
| `primer_cierre` | el cierre H4 esperado que falta |
| `ultimo_cierre_valido` | último cierre H4 sellado antes de la ausencia |
| `observaciones` | lista ordenada de `{eligibility_time, run_epoch}` probatorios (§6.5.2) |
| `evidencia_acumulada_ms` | **derivado**, no fuente de verdad (ver abajo) |
| `offline_ms`, `offline_intervalos` | tiempo sin observar, registrado y no computado |

#### Acumulación

**`run_epoch`** *(rev.8)*: entero monotónico creciente, uno por **continuidad de
ejecución** del daemon. Se incrementa en cada arranque y se persiste **en cada
observación**. Sin él, tras un reinicio no hay forma de reconstruir qué
intervalos aportaron cero, y el acumulado dejaba de ser derivable.

```
al abrir la entrada (primera observación probatoria que falta la vela):
    observaciones = [{t, e}];  aporta CERO

en cada observación probatoria posterior {t, e}:
    si t <= ultima.eligibility_time:      # duplicado o retroceso de serverTime
        aporta CERO, NO se agrega a `observaciones`, NO mueve el puntero
        si t < ultima.eligibility_time: se registra incidencia operacional
    si e != ultima.run_epoch:             # primera observación de esta corrida
        aporta CERO                       # nadie observó ese intervalo
        se agrega y mueve el puntero
    si no:
        aporta min(t − ultima.eligibility_time, TOPE_INTERVALO)
```

**El primer intervalo de cada corrida aporta cero, no el tope** *(rev.7,
mantenido en rev.8)*. Darle el tope contaría como evidencia un intervalo que
nadie observó. Con cero, el tiempo apagado no acumula **nada**, y
`TOPE_INTERVALO` queda para lo que corresponde: acotar un intervalo largo dentro
de una corrida viva.

`evidencia_acumulada_ms` **se recomputa desde `observaciones` al rehidratar** —y
la recomputación es exacta **porque `run_epoch` está persistido**— y se compara
con el valor guardado: si difieren, fallo cerrado. El acumulador no se cree, se
deriva.

#### Resolución

Si la vela aparece antes de cruzar el umbral, la entrada pasa a `resuelto` —se
conserva para auditoría, no se borra— y deja de gobernar. Si después falta otro
cierre, es **otra clave**, con su propio contador desde cero.

#### Selección del terminal

Con varias entradas activas, gana la **primera que cruza el umbral**; empate a
la misma observación, gana el menor en el orden total de la clave.
`blocked.json` nombra a la ganadora y conserva el resumen de las demás. El orden
de iteración no cambia un byte: el mapa es canónico.

#### Autenticación *(rev.7 — MAJOR 1)*

Incluir el sidecar en el digest evita omitirlo, pero no autentica su historia:
un `silencio.json` alterado antes de la captura se copia al scratch y los dos
lados calculan el mismo digest sobre la alteración. Como este archivo decide
`BLOCKED_INTEGRITY`, lleva:

- `schema_version` cerrada y versionada;
- identidad de cohorte, `contrato` y `commit`;
- **cadena de evidencia**: `h_0 = SEMILLA_SILENCIO`,
  `h_i = SHA-256(h_{i−1} ‖ canon(observacion_i))`, y el `h_n` final persistido;
- **`doc_sha256`** *(rev.8)*: `SHA-256(canon(documento sin `doc_sha256`))`, que
  cubre el **documento entero**. La cadena solo autentica `observaciones`, y
  `estado`, `primer_cierre`, `ultimo_cierre_valido`, `offline_ms` y el propio
  `evidencia_acumulada_ms` también deciden el terminal;
- escritura atómica con `fsync` de archivo **y** de directorio.

Al rehidratar se valida, **fail-closed**: `doc_sha256`, schema, identidad,
monotonicidad estricta de `eligibility_time`, monotonicidad no decreciente de
`run_epoch`, recálculo de la cadena y recálculo del acumulado. Cualquier
discrepancia detiene el observador; no produce «otro digest aceptado».

### 6.5.1.1 Qué evidencia viaja al terminal *(rev.7 — BLOCKER 2)*

`blocked.json` **no** lleva la lista cruda: lleva `h_n` (la cadena), el número de
observaciones, la primera, la última y `evidencia_acumulada_ms`. La lista
completa queda en `silencio.json`, que es el artefacto auditable.

### 6.5.1.2 Qué es invariante y qué no *(rev.7 — BLOCKER 2)*

rev.6 se contradecía: los gates exigían independencia del número de ciclos y el
acumulador depende deliberadamente del calendario de observaciones. Se separan
las dos afirmaciones, y solo la primera es una invariancia:

| | |
|---|---|
| **Invariante** | dadas las mismas observaciones probatorias **dentro de una misma continuidad de ejecución** (mismo `run_epoch`), cualquier reagrupación en distinto número de llamadas internas o de ciclos produce **bytes idénticos** |
| **Sensible a propósito** | observaciones **realmente ausentes o más espaciadas** retrasan el terminal, exactamente según la aritmética de `TOPE_INTERVALO`. Observar cada 60 min acumula 30 min por hora, y eso es correcto: la evidencia es lo observado, no lo transcurrido |

Es decir: el terminal no depende de cómo se agrupan las observaciones, pero sí
depende de cuáles hubo.

**Un reinicio NO es una reagrupación** *(rev.8)*. rev.7 se contradecía: el gate
21 pedía bytes idénticos «con reinicio intermedio» y el 38 pedía que el reinicio
perdiera un intervalo. Las dos no pueden valer. Un reinicio **cambia el conjunto
de observaciones efectivas** —introduce un `run_epoch` nuevo cuya primera
observación aporta cero— y por lo tanto cae del lado sensible, no del
invariante. La invariancia rige **dentro** de una continuidad; a través de un
reinicio rige la pérdida del gate 38, que es estrictamente conservadora: una
corrida partida acumula **menos** que la continua, nunca más.

### 6.5.2 Paginación H4 «válida y completa» *(rev.6 — precisión 1)*

Cuenta como observación probatoria solo la que cumple **todas**:

- se obtuvo `eligibility_time` en ese ciclo, y es el mismo watermark para toda
  la consulta del mercado/TF;
- la paginación recorrió desde `startTime_0` (§10) **hasta la página vacía
  final**, con progreso estricto en cada paso;
- ninguna página fue rechazada por orden, grilla, duplicado o TF;
- ningún error HTTP ni timeout en ninguna página de esa secuencia.

Si cualquiera falla, la consulta **no es evidencia**: no inicia el silencio, no
lo avanza y no mueve `t_observacion_previa`.

### 6.5.3 El umbral *(rev.6 — precisión 3)*

**`SILENCIO_MAX_H4 = 72 h` (18 cierres H4) es una decisión operacional `[U0]`,
no un hecho demostrado.** rev.5 la justificaba con ventanas de mantenimiento de
Binance y un umbral de deslistado como si fueran datos; no tengo provenance
documental congelada de ninguna de las dos cosas, así que retiro la afirmación.

Lo que sí sostengo es la forma del compromiso: un valor más corto bloquea
cohortes por incidentes normales, uno más largo deja la cohorte detenida sin
decidir, y 72 h está en un orden de magnitud razonable entre ambos. Si se quiere
respaldo documental, se congela junto con el protocolo y se cita ahí.

**Se congela antes de activar y no se elige después de ver un silencio real**:
hacerlo sería exactamente la contaminación que todo este protocolo impide.

### 6.6 Límite honesto de la liveness *(rev.5)*

«El sistema siempre alcanza un terminal» vale **solo mientras el observador siga
obteniendo `eligibility_time` y respuestas válidas**. Si toda la infraestructura
queda muda —sin reloj de Binance— no hay con qué certificar el vencimiento, y el
observador espera. Es fail-closed y correcto, pero no es liveness incondicional
y no se presenta como tal.

Con esa condición, el sistema alcanza un estado terminal: `COMPLETED` o
`BLOCKED_INTEGRITY`.

**Por qué no rompe el determinismo.** Es una precondición sobre CUÁNDO llamar a
`procesar_lote`, no sobre QUÉ decide el motor para un estado de almacén dado. En
frío la precondición se satisface trivialmente y se procesan los mismos lotes; y
si en vivo hubo una ausencia H4, quedó SELLADA como marcador y el arranque en
frío lee ese mismo marcador. El motor no se toca.

---

# Verificación de determinismo

## 7. Dos primitivas de exclusión, no una

rev.2 se contradecía: el `flock` se retenía toda la vida del daemon y a la vez
la captura pretendía adquirirlo. Se separan:

| | |
|---|---|
| `singleton_lock` | `flock` de vida completa sobre `state/observador.lock`. Impide un segundo observador. **Nunca se libera para auditar.** |
| `cycle_barrier` | mutex interno del proceso, tomado por el ciclo y por la captura |

La captura la ejecuta **el proceso propietario**, no un verificador externo. Un
tercero que quiera una captura deja una solicitud (archivo `verify.request` en
el directorio de estado); el daemon la atiende al cerrar el ciclo en curso. Si
el proceso no está vivo, no hay captura: no existe forma de obtener una desde
afuera, y eso es deliberado.

## 8. `state_digest` completo

**El sufijo desafío se elimina.** rev.2 proponía alimentar «al motor vivo y al
frío» con velas sintéticas: eso contaminaría el estado y el libro de la cohorte
real, que es append-only y sin rollback autorizado. No hay forma de hacerlo sin
tocar el daemon real, así que se toma la salida que la propia auditoría admite:
**el digest cubre todo el estado que pueda afectar decisiones futuras**, y la
comparación es vivo vs. frío en la misma barrera.

`state_digest` = SHA-256 del JSON canónico de:

- **por mercado** (7): `estado`, `degradado`, `candidato`, `orden`, `posicion`,
  `salida`, `zonas_tocadas` (ordenado canónicamente);
- **del motor**: `cortado`; `motivo_corte` (ausente ⇒ `null` explícito, nunca
  omitido); `_frontera_cruzada`; `_epocas_anunciadas` (ordenado);
  `bootstrap_hasta`; **`lotes_finalizados` completo** y **`cierres` completo**,
  ambos en su serialización canónica íntegra — no cardinalidad ni último
  elemento: `cierres` participa del corte por semanas ISO, así que su contenido
  afecta decisiones futuras;
- **por almacén** (14): `head` físico y `len(registros)`.

**Excluidos por derivados**, se recomputan sin cambiar resultados:
`_reloj_ciclo`, `_ciclo_externo`, `_cache_h4`, `_swm15`, y en el almacén
`_epocas_cache`, `_por_t`, `_ts`, `_prefix_max`, `_vela_hashes`,
`_gap_por_desde`.

### 8.0 `observer_state_digest` *(rev.6 — BLOCKER 2)*

`state_digest` cubre el motor y los almacenes, pero el estado de silencio
(§6.5.1) también decide un futuro terminal y vivía fuera. Dos observadores con
motor, almacenes, libro y buffers idénticos pueden tener origen o evidencia de
silencio distintos: mismo digest, bloqueo en instantes distintos. Y el clon frío
no puede reconstruirlo, porque una ausencia H4 permanente todavía **no** es un
marcador sellado.

```
observer_state_digest = SHA-256( canon({
    "motor": state_digest,          # §8
    "silencio": <silencio.json canónico, completo>
}) )
```

La captura (§9) copia y verifica **`silencio.json` bajo la misma barrera** que
almacenes y libro, y la comparación vivo↔frío usa `observer_state_digest`.

`verificacion.json` queda **fuera** del digest, a propósito: es el registro de
la propia verificación y meterlo adentro crearía una dependencia circular. Sus
invariantes de publicación se verifican aparte (§9.2).

### 8.1 `_buffer` no es derivado *(rev.4 — BLOCKER 1)*

rev.3 lo excluía como si fuera caché. No lo es: ante un hueco, el buffer
contiene velas futuras aún no selladas y determina los tres cierres de
`prueba_local`, el `detected_at`, el rango exacto del marcador y el head
siguiente de la cadena. Un motor vivo con buffer pendiente y un arranque en
frío sin él pueden tener libro, heads y digest idénticos **y decidir distinto**
en el evento siguiente.

Tampoco puede incluirse en el digest: el buffer no se persiste, así que el
clon frío nunca lo tendría, y persistirlo contradiría §12.

**Regla: solo se certifica una barrera con los 14 buffers vacíos.**

- algún buffer no vacío → se registra `verification_deferred` con el motivo, y
  se espera a que drene o se selle;
- **antes de reportar cualquier resultado** debe existir una verificación
  exitosa POSTERIOR a la última deferencia. Una cohorte cuya última
  verificación quedó diferida no tiene determinismo demostrado y no se reporta.

## 9. Captura y comparación *(rev.4 — MAJOR 3)*

El ciclo **ya retiene** `cycle_barrier` desde que abre (§12) y **la sigue
reteniendo** durante fsync, digest y copia: no la readquiere. Con un mutex no
reentrante, readquirirla sería un deadlock *(rev.4 — MAJOR 3)*.

1. el ciclo termina de procesar, **sin soltar** `cycle_barrier`;
2. si hay `verify.request` y los 14 buffers están vacíos (§8.1):
   `fsync` de los 14 almacenes y del libro;
3. calcula su `state_digest` vivo;
4. copia almacenes + libro a scratch;
5. **recién ahí** suelta la barrera y sigue operando;
6. **fuera de la barrera**, reconstruye en frío desde la copia y compara
   `firma()` del libro **y** `state_digest`.

Si algún buffer no está vacío, se salta a (5) y se registra
`verification_deferred` (§9.2).

### 9.0 Zona de corte: no se procesa sin verificación `ok` *(rev.6 — BLOCKER 3)*

rev.5 permitía seguir procesando con la verificación `pending` y solo prohibía
publicar `completed.json`. Eso no alcanza: el motor emite `abierta_al_corte` y
`orden_al_corte` **dentro del corte**, antes de que el observador publique nada.
La secuencia «pending → el lote 50 corta → la comparación diverge → se publica
`BLOCKED_INTEGRITY`» dejaba un terminal bloqueado **con eventos de cierre
científico dentro**, contradiciendo §13.1.

Demorar `completed.json` no sirve. Hay que impedir que el motor llegue a cortar.

**Zona de corte**, evaluada por el observador ANTES de procesar cada lote `T`,
con estado observable:

```
en_zona_de_corte(T)  ⟺
    CORTE_N_CIERRES − len(motor.cierres) ≤ (nº de mercados con posición u orden viva)
  ∨ T ≥ T_CORTE − CORTE_ADMIN_GRACIA_MS
```

Es deliberadamente conservadora: cubre todo lote en el que el corte **podría**
ocurrir, sin predecir si ocurrirá.

**Las dos cotas hay que demostrarlas, no afirmarlas** *(rev.7 — precisión)*:

- la primera supone que **un lote no puede producir más cierres que mercados con
  posición u orden viva**. Es plausible —un mercado cierra a lo sumo una
  posición por lote— pero exige un gate contra el orden completo de fases,
  incluido `fill+STOP` en el mismo lote (CF-20), posiciones, órdenes y
  candidatos, sobre los siete mercados. Si una sola rama produjera más de un
  cierre por estado vivo, la zona quedaría subestimada y el blocker 3 volvería;
- la segunda, `T ≥ T_CORTE − CORTE_ADMIN_GRACIA_MS`, es conservadora **por
  construcción y hay que rotularla así**: la gracia contractual ocurre *después*
  del corte, así que restarla no representa el instante real de cierre — solo
  garantiza entrar en la zona antes de tiempo, que es lo que se busca.

- **fuera** de la zona de corte → se procesa normalmente aunque la verificación
  esté `pending`;
- **dentro** de la zona → **no se procesa ningún lote** hasta que el estado de
  verificación sea `ok` **y posterior a toda deferencia**. Se sigue ingiriendo
  de forma durable, como en `catch-up`.

Así, ningún evento terminal puede escribirse mientras el determinismo no esté
demostrado, y la rama divergente termina con el libro **sin un solo evento de
cierre nuevo**.

### 9.1 Divergencia detectada después de soltar la barrera *(rev.5 — MAJOR 3)*

La comparación en frío ocurre fuera de la barrera y el daemon sigue operando,
así que cuando se detecta una divergencia ya puede haber ciclos posteriores.
Regla total:

1. al copiar, la verificación queda marcada **`pending`** en el sidecar;
2. con una verificación `pending` la ingesta durable **puede continuar**, pero
   **no puede publicarse `COMPLETED`** bajo ninguna circunstancia;
3. si la comparación da igual → `ok`, y el flujo normal se restablece;
4. si da distinto → la cohorte termina en
   **`BLOCKED_INTEGRITY(determinism_divergence)`**, sin resultado y sin
   evaluación, aunque el motor ya hubiera cortado.

Una cohorte cuyo determinismo se rompió no se reporta, y ningún ciclo posterior
la rehabilita.

#### 9.1.1 La transición TERMINAL va serializada *(rev.10: toda causa)*

La comparación fría corre fuera de `cycle_barrier` y el daemon sigue operando,
así que sin arbitraje una implementación publicaría el marcador antes del ciclo
siguiente y otra después de varios: heads y firma distintos para la misma causa,
y el `fsync` compitiendo con escrituras vivas. Transición única:

La transición son **dos fases con la barrera SOLTADA entre medio**, y una
ventana de recolección en el medio *(rev.12)*. rev.11 retenía la barrera desde
el registro hasta la publicación y a la vez decía que otros registradores
podían entrar: con un mutex ordinario eso es imposible — el segundo solo entra
cuando ya hay un terminal inmutable, que es justo lo que se quería evitar.

```
FASE A — registro (por cada causa, serializada)
  1. adquirir cycle_barrier
  2. marcar `cierre_en_curso`                  (§13.3)
  3. escribir/anexar terminal.request atómico  (sobrevive a la caída)
  4. LIBERAR la barrera

VENTANA DE RECOLECCIÓN
  - los ciclos de INGESTA no abren (§13.3);
  - los REGISTRADORES de causas sí entran, uno por vez, repitiendo la fase A;
  - se cierra cuando ningún productor puede aportar ya una causa (§9.1.2).

FASE B — publicación (una sola vez)
  5. adquirir cycle_barrier
  6. reevaluar la condición de cierre de la ventana (§9.1.2)
  7. fsync de los 14 almacenes, del libro y de silencio.json
  8. capturar los 14 heads y la firma del libro
  9. verificar estado autorizado (§13.4) y verificación (§13.5)
 10. publicar el marcador DERIVADO del motivo ganador (§13.2)
 11. borrar terminal.request y ARCHIVAR verify.request si quedó sin atender
 12. liberar la barrera y salir
```

**El orden dentro de la fase A importa** *(rev.11)*: rev.10 escribía el request
ANTES de tomar la barrera, y entre esos dos pasos otro ciclo podía empezar a
ingerir sobre una cohorte que ya estaba cerrándose.

#### 9.1.2 Qué cierra la ventana de recolección *(rev.13)*

La ventana existe para que la precedencia signifique algo: si se publicara con
la primera causa, ganaría la que llega antes.

**Regla previa, y es incondicional** *(rev.13)*: quien entra en la fase B y
observa la verificación en `divergent` **anexa `determinism_divergence` con su
evidencia ANTES de calcular el ganador**.

Sin eso, la condición era inobservable: la comparación fría escribe
`verificacion.json = divergent` y recién después pide la barrera para
registrar su causa. Entre esos dos pasos, la fase B podía adquirir la barrera,
ver `divergent`, dar la ventana por cerrada y publicar el ganador anterior —un
`silencio_h4`— sin que la divergencia hubiera llegado nunca al request.

Con la causa ya anexada, la ventana se cierra según el **ganador actual**, no
según el estado de la verificación a secas:

| ganador en el request | estado de la comparación | qué se hace |
|---|---|---|
| `determinism_divergence` | cualquiera | **publicar ya**: nada lo supera |
| `silencio_h4` | `pending` | **esperar**: hay una comparación activa que puede superarlo |
| `silencio_h4` | `deferred`, `ok` | **publicar**: no hay productor que pueda aportar más |
| científico | `ok` posterior a toda deferencia | **publicar** `COMPLETED` |
| científico | `pending` | **esperar** |
| científico | `deferred` | **fallo cerrado**: estado inalcanzable (§13.5.0) |

`divergent` no aparece en la tabla porque, por la regla previa, para cuando se
calcula el ganador ya es `determinism_divergence` quien gana.

rev.12 mantenía abierta cualquier ventana con `pending`, incluso cuando el
request ya contenía el motivo de máxima precedencia: esperar ahí era esperar
algo que no podía cambiar el resultado.

#### 9.1.3 Quién reactiva la fase B *(rev.13)*

Cuando una comparación pasa de `pending` a `ok` no hay causa nueva que
registrar, así que nadie volvería a intentar publicar y la cohorte quedaría
detenida.

Hay exactamente **tres disparadores**, y entre los tres cubren todas las
causas *(rev.16)*:

| quién | cuándo |
|---|---|
| el CICLO que registra una causa | apenas libera `cycle_barrier` (§12) |
| la comparación fría al terminar | en sus cuatro salidas: `ok`, `divergent`, y el fallo cerrado por copia ausente o corrupta |
| el ARRANQUE | al encontrar un `terminal.request` validado SIN terminal publicado, antes de abrir ningún ciclo (§13.5) |

Ninguno depende de polling ni de otro ciclo — los de ingesta están prohibidos
durante la ventana, precisamente.

Cada disparador cubre un hueco que los otros dejan:

- **sin el del ciclo**, un corte científico sin comparación pendiente no tenía
  quién publicara: no hay comparación que termine *(el hueco de rev.15)*;
- **sin el del arranque**, una caída entre registrar y publicar dejaba el
  request sin nadie que lo retomara — §13.5 exige esa reanudación, pero
  §9.1.3 no la listaba como disparador *(el hueco de rev.16)*.

**Contrato de `terminal.request`** *(rev.7 — MAJOR 2)*. El artefacto que
permite reanudar necesita schema propio, o el reinicio no puede verificar qué
autorizó el terminal *(rev.11: «el bloqueo» era de cuando el request solo
cubría integridad)*:

| campo | qué es |
|---|---|
| `schema_version` | cerrada y versionada |
| `cohorte`, `contrato`, `commit` | identidad |
| `motivo` | el GANADOR por precedencia, del registro cerrado de §13.2 |
| `evidencias` | evidencia POR MOTIVO: el ganador se publica con la suya |
| `evidencia` | la que lo autorizó: `h_n` y resumen (§6.5.1.1), o digest y firma comparados |
| `solicitado_en` | instante y barrera de la solicitud |
| `estado_esperado` | los 14 heads, firma del libro y hash de `silencio.json` |
| `captura_autorizada` | identidad de la comparación en curso, si la hay (§13.4.1) |
| `checksum` | del propio request |

Al arrancar, un `terminal.request` **sin terminal publicado** significa que la
caída ocurrió a mitad: se **valida fail-closed** (schema, identidad, checksum)
y se reanuda la transición desde (2) según la matriz de §13.5. Nunca se
ingiere. *(rev.10: «sin `blocked.json`» era de cuando el request solo cubría
integridad.)*

**Precedencia**, congelada — no se resuelve por última escritura ni por orden de
hilos:

| situación | resolución |
|---|---|
| `completed.json` **y** `blocked.json` | **fallo cerrado**: la única contradicción que queda |
| terminal publicado **y** request COINCIDENTE (§13.6) | el terminal manda; el request se archiva |
| terminal publicado **y** request DISCREPANTE | **fallo cerrado** *(rev.10)* |
| dos o más motivos en el request | gana el de mayor precedencia (§13.2) |
| dos motivos CIENTÍFICOS a la vez | **fallo cerrado**: el motor corta una sola vez *(rev.10)* |
| request ya existente | **no se sobrescribe**; el motivo nuevo se anexa y el ganador se recalcula por precedencia |

**La anexión también es una escritura, y va atómica** *(rev.8)*: se lee el
request, se valida su `checksum`, se agrega el motivo, se recalcula el
`checksum` y se publica por `tmp` → `fsync` → `os.replace` → `fsync` del
directorio. Las anexiones concurrentes quedan serializadas por `cycle_barrier`,
igual que la transición terminal (§9.1.1), así que no hay dos escritores. El
`motivo` ganador **no cambia** por una anexión posterior: se decide por la
precedencia de la tabla, no por orden de llegada.

**La carrera entre la verificación y el corte del motor NO la decide quién
llega primero a la barrera** *(rev.10: rev.8 decía lo contrario y quedó
obsoleto al partir la transición en dos fases)*. Las dos causas se ANOTAN en el
request y la publicación resuelve por precedencia; además la publicación
reevalúa la verificación (§13.4), así que un `COMPLETED` no sale si entretanto
pasó a `divergent` o `deferred`.

### 9.2 `verification_deferred` es sidecar, no evento *(rev.5 — MAJOR 2)*

`verification_deferred` **no es un tipo del registro cerrado CF-37** y no entra
al libro científico. Es observabilidad operacional, y vive en un sidecar
atómico `verificacion.json` con, como mínimo:

- instante de la deferencia y `eligibility_time` asociado;
- qué buffers estaban no vacíos;
- la última verificación **exitosa** (instante, digest, firma del libro);
- el estado pendiente vigente: `ok` | `deferred` | `pending` | `divergent`;
- con `pending`, la RUTA de la copia scratch más el `digest` y la `firma`
  capturados, para que la comparación fría sobreviva a un reinicio (§13.5.1).

Sin este sidecar, un reinicio olvidaría que la última verificación quedó
diferida y el reporte tomaría por válida una anterior. El requisito «una
verificación exitosa POSTERIOR a la última deferencia» (§8.1) se evalúa contra
este archivo, no contra memoria ni contra logs.

El daemon real no recibe nada durante la verificación. Gate: heads, digest y
libro del daemon deben quedar byte a byte iguales antes y después.

Divergencia = incidente, cohorte marcada, sin excepción.

---

# Ingesta

## 10. Elegibilidad, reloj y paginación normativos

**Dos relojes disjuntos, muestreados una vez por ciclo cada uno**
*(rev.4 — MAJOR 1)*:

| | qué es | qué hace |
|---|---|---|
| `eligibility_time` | `serverTime` de Binance (`/fapi/v1/time`) | **solo** filtra qué velas son elegibles |
| `processed_at` | reloj local observado | **solo** telemetría de materialización (CF-34) |

rev.3 pasaba `iniciar_ciclo(serverTime)`, lo que convertía el reloj de Binance
en `processed_at`. Es incorrecto: CF-34 define `processed_at` como el reloj
observado en que el motor materializa el evento. `eligibility_time` **nunca**
entra por el parámetro que alimenta `_reloj_ciclo`.

- elegible sii `eligibility_time ≥ closeTime + 1 + MARGEN_CIERRE`;
- `eligibility_time` indisponible → **no se ingiere nada en ese ciclo**. Nunca
  hay fallback silencioso al reloj del Mac;
- `|eligibility_time − processed_at| > DERIVA_MAX` → incidencia operacional
  visible (un Mac con la hora rota tiene que verse, aunque no decida nada).

**Paginación** *(rev.3 — MAJOR 1, borde corregido)*, por mercado y TF:

```
startTime_0        = ultimo_t − (RESOLAPE − 1)·dur      # alineado a la grilla
startTime_{k+1}    = openTime(última fila de la página k) + dur
```

La expresión de rev.2 (`ultimo_t + 1 − RESOLAPE·dur`) quedaba un milisegundo
fuera de la grilla y no decía cuántas velas selladas se reingerían. La nueva
incluye exactamente `RESOLAPE` velas, la última sellada incluida.

- se itera mientras la página vuelva llena;
- **progreso estricto**: una página llena cuyo `startTime` siguiente no avance
  es fallo cerrado, nunca un loop;
- página vacía → fin; fuera de orden, `t` desalineado, duplicado interno o
  intervalo distinto del pedido → fallo cerrado, no se ofrece nada de esa página;
- se valida símbolo perpetuo USD-M y TF exactamente `15m` / `4h`.

**Mapeo OHLCV**: índice → campo explícito, `t = openTime`, numéricos parseados
por **la misma ruta que el cargador del snapshot**. Si el push serializara
distinto para la misma vela, el solape produciría una tormenta de
`vela_revisada` sobre datos idénticos.

## 11. Modo `catch-up`

| | |
|---|---|
| Permite | descargar, ofrecer, drenar, sellar, paginar hasta el watermark común |
| Prohíbe | procesar lotes mientras cualquiera de los 14 streams siga stale |
| Nunca | saltar lotes, redefinir la frontera, reescribir lo sellado |
| Sale | con los 14 frescos y la precondición H4 (§6) cumplida |

`processed_at` conserva el reloj real de materialización: un catch-up se ve en
la telemetría como lo que fue.

## 12. Ciclo

```
cada CADENCIA:
  eligibility_time ← Binance /fapi/v1/time   (indisponible → fin del ciclo)
  cycle_barrier.acquire()                    # se retiene TODO el ciclo
  iniciar_ciclo()                            # processed_at = reloj LOCAL
    para cada mercado × {M15, H4}:
      pull paginado (§10) desde ultimo_t − (RESOLAPE−1)·dur
      filtrar por eligibility_time → alm.ofrecer(velas,"push") → alm.drenar()
      si declarar_hueco_local() devuelve registro:
        emitir hueco_detectado(tf) por la vía canónica  (§6.3)
    si NO catch-up y se cumple la precondición H4 (§6):
      procesar los lotes globales finalizables
      # cada marcador creado aquí hace fsync de SU almacén antes del libro (§5)
    fsync del libro
  finalizar_ciclo()

  # ORDEN CONGELADO del final del ciclo (rev.14/15). Ver abajo por qué.
  si motor.cortado:                      # con cycle_barrier YA RETENIDA
      marcar cierre_en_curso
      anexar la causa CIENTÍFICA al request   (fase A, SIN readquirir)
      NO se atiende ningún verify.request nuevo
  si no:
      atender verify.request si lo hay, SIN readquirir la barrera (§9)

  cycle_barrier.release()

  si se registró una causa terminal en este ciclo:
      intentar la FASE B inmediatamente (§9.1.1)
```

**Por qué ese orden es normativo** *(rev.14)*. Con el orden anterior —procesar,
finalizar, atender `verify.request`, y recién después registrar— esta secuencia
era posible y legítima:

1. la verificación está `ok`;
2. el motor alcanza `muestra` o `tiempo`;
3. antes de registrar la causa se atiende un `verify.request`;
4. la captura encuentra buffers y pasa a `deferred`;
5. recién ahí se registra la causa científica.

Resultado: `deferred` + causa científica, que §13.5.0 declara imposible. El
sistema habría fallado cerrado ante una operación normal — la peor clase de
fallo cerrado, el que castiga lo correcto.

**Y se anexa SIN readquirir** *(rev.15)*: el ciclo ya retiene `cycle_barrier`,
y la fase A de §9.1.1 empieza adquiriéndola. Una implementación literal del
orden de rev.14 entraba en deadlock contra el mutex no reentrante que el propio
diseño congela. La adquisición y la liberación son del LLAMADOR; los pasos
propios de la fase A son marcar y anexar.

**Y alguien tiene que disparar la fase B** *(rev.15)*: §9.1.3 se la asignaba
solo a la finalización de una comparación fría. En un corte científico sin
comparación pendiente no había ninguna, así que el request quedaba registrado
para siempre y la cohorte nunca cerraba. El ciclo que registra una causa
intenta la fase B apenas suelta la barrera.

Registrar la causa ANTES de atender la captura cierra el hueco, y con eso la
demostración de §13.5.0 queda completa: una comparación que ya estuviera
`pending` habría impedido el corte por la zona de corte (§9.0), y una
deferencia NUEVA ya no puede aparecer entre el corte y el registro.

**Qué pasa con el `verify.request` no atendido**: no se atiende —no habría
ciclos posteriores que usaran su resultado— y no se borra —alguien lo pidió y
eso queda registrado—: se ARCHIVA.

**Borrar y archivar no son lo mismo** *(rev.15)*, y rev.14 los confundía:

| momento | `terminal.request` | `verify.request` |
|---|---|---|
| flujo normal, tras publicar el terminal | se BORRA: cumplió su función y su contenido ya está en el marcador | se ARCHIVA |
| reinicio tras caída entre publicar y borrar | se valida (§13.6) y, si COINCIDE, se ARCHIVA | se ARCHIVA |
| request DISCREPANTE | **fallo cerrado** | — |

El residual coincidente se archiva en vez de borrarse porque es la evidencia de
que la caída ocurrió ahí: borrarlo dejaría la recuperación sin rastro.

**El buffer no se persiste.** Solo `drenar` appendea; una caída con el buffer
lleno pierde esas velas y el arranque siguiente las re-pide desde `ultimo_t`. La
recuperación no asume nada del buffer.

### Proceso largo

Medido en el ensayo a escala: corrida completa 345 s, reinicio 402 s. Re-correr
todo cada ciclo consume la mitad de un ciclo de 15 minutos y crece hasta
superarlo. Daemon largo: replay único al arrancar (~7 min) y después solo lotes
nuevos. La deriva en RAM la controlan §8 y §9.

---

# Terminación

## 13. Estados terminales persistentes y atómicos

Un health solo en RAM permitiría que launchd reiniciara el servicio y
reconstruyera la cohorte como activa.

Al cortar el motor (por `CORTE_N_CIERRES` o `T_CORTE`), el cierre pasa por las
DOS FASES como cualquier otra causa terminal *(rev.10)*:

```
1. cerrar motor y emitir los eventos terminales
2. ANOTAR la causa en terminal.request (§13.2) → cierre en curso (§13.3)
3. fsync de almacenes y libro
4. verificar el estado autorizado (§13.4) y la verificación (§13.5)
5. escribir completed.json.tmp → fsync → os.replace → fsync del directorio
6. borrar terminal.request
7. exponer health COMPLETED y salir, sin reactivación
```

Una caída entre (5) y (6) deja terminal y request a la vez: es recuperación
normal si coinciden (§13.6), no una contradicción.

`completed.json` contiene identidad de cohorte, contrato, commit, motivo del
corte, última barrera, los 14 heads y la firma del libro.

**Condición de publicación** *(rev.6 — precisión 2)*: `COMPLETED` exige que el
estado de verificación sea **`ok` y posterior a toda deferencia**. No basta con
la ausencia de `pending`: un `deferred` sin verificación exitosa posterior
tampoco habilita el cierre.

### 13.1 `BLOCKED_INTEGRITY` NO ejecuta el cierre científico

rev.4 presentaba `blocked.json` como «la misma mecánica», y eso confundía dos
cosas que deben quedar separadas normativamente:

| | `COMPLETED` | `BLOCKED_INTEGRITY` |
|---|---|---|
| Corte del motor | **sí**, contractual | **no se llama** |
| `abierta_al_corte`, `orden_al_corte` | sí | **no se emiten** |
| Resultado / muestra | sí | **ninguno** |
| Toca el libro científico | sí, con sus eventos terminales | **no** |

Orden en `BLOCKED_INTEGRITY`: `fsync` del estado y del libro **tal como están**,
y después publicar `blocked.json` atómico. Nada se agrega al libro para simular
una evaluación. Las incidencias operacionales del bloqueo viven en health y en
los sidecars, no en el registro cerrado CF-37.

### 13.2 `terminal.request` cubre TODAS las causas terminales *(rev.9)*

rev.8 limitaba el request a `silencio_h4 | determinism_divergence` y declaraba
`completed.json` + `terminal.request` como contradicción fatal. Eso era
coherente mientras solo las causas de integridad usaban el request.

Pero la transición tiene que ser en dos fases —anotar y después publicar—
para que la precedencia signifique algo: con una sola fase, dos causas del
mismo turno quedan serializadas y gana la que publica primero, no la que
manda. Y si el corte científico no pasa por el request, queda fuera de esa
resolución y vuelve a decidir el orden de ejecución.

Se amplía el alcance, y con él las reglas que dependían de él:

- **el request cubre toda causa terminal**, científica o de integridad;
- **registro CERRADO de motivos**, con fallo cerrado para cualquier otro:

  | familia | motivos | terminal |
  |---|---|---|
  | científica | `muestra`, `tiempo`, `administrativo` | `COMPLETED` |
  | integridad | `determinism_divergence`, `silencio_h4` | `BLOCKED_INTEGRITY` |

  Un motivo fuera del registro —un typo, uno nuevo sin declarar— **no** cae
  por omisión en `COMPLETED`: falla cerrado. Fallar abierto acá significa
  publicar como evaluable una cohorte cuya causa de cierre nadie definió.

- **el terminal se DERIVA del motivo ganador**. Ningún llamador lo elige;
- **`completed.json` + `terminal.request` deja de ser contradicción**: es el
  estado normal de una caída entre publicar y borrar el request. La regla
  pasa a ser la misma que para `blocked.json` — el terminal publicado manda y
  el request se archiva. La contradicción fatal queda reservada a la única
  que sigue siéndolo: `completed.json` **y** `blocked.json` a la vez.

### 13.2.1 Precedencia COMPLETA de los cinco motivos *(rev.10)*

rev.9 introdujo cinco motivos pero la tabla de §9.1.1 solo ordenaba dos. Orden
total, congelado:

```
determinism_divergence  >  silencio_h4  >  { muestra, tiempo, administrativo }
```

- **la integridad precede a lo científico**, siempre. Un cierre evaluable no
  puede publicarse si en el mismo turno hay una causa que dice que la
  evidencia no es confiable: reportar la muestra sería reportar un resultado
  cuya trazabilidad está en duda;
- **entre los motivos científicos NO hay orden, porque no pueden coexistir**.
  El motor corta UNA vez: `_fase8` da `muestra`, el corte por tiempo da
  `tiempo` y `cerrar_administrativo` da `administrativo`, y los tres apagan
  `cortado`. Dos motivos científicos en un mismo request significan que algo
  ya está mal, así que **falla cerrado** en vez de elegir uno.

### 13.3 Un request PENDIENTE prohíbe abrir ciclos *(rev.9)*

Anotar una causa cierra la cohorte tanto como publicarla: entre el último
registro y la publicación, otro ciclo podía mover almacenes o libro y dejar
obsoleto el `estado_esperado` que el request autoriza.

Desde el primer `registrar_causa`, la barrera queda en **cierre en curso** y
`ciclo()` no abre ninguno nuevo. La bandera se distingue de `terminal` —
publicado— porque una es reversible por reanudación y la otra no.

### 13.4 El estado autorizado se verifica también AL PUBLICAR *(rev.9)*

rev.8 lo verificaba solo al reanudar. Refrescarlo en cada registro no cubre una
mutación posterior al último. La publicación compara `estado_esperado` contra
el estado actual y falla cerrado si difieren, igual que la reanudación.

#### 13.4.1 Qué congela `estado_esperado` y qué NO *(rev.17)*

Hasta rev.16 esta sección decía «el hash de CADA sidecar». Con `silencio.json`
es correcto: su evidencia VIAJA al terminal, así que congelar sus bytes es
congelar el contenido de lo que se publica.

Con `verificacion.json` es **imposible**, y no por un detalle de
implementación. §9.1.3 establece que el segundo disparador de la fase B es la
comparación fría al terminar, y terminar significa exactamente reescribir ese
sidecar: `pending → ok`. Es decir, el propio disparador de la publicación
invalida el hash que autorizaría publicar. Las dos cláusulas juntas no dejan
ninguna ruta viva: toda cohorte con una comparación en curso al momento de
registrar la causa queda detenida para siempre.

La distinción que resuelve el choque es entre **contenido** y **compuerta**:

| sidecar | qué es | cómo se autoriza |
|---|---|---|
| `silencio.json` | CONTENIDO: su evidencia se publica en el terminal | hash de los bytes, congelado en `estado_esperado` |
| `verificacion.json` | COMPUERTA: habilita o retiene, y no viaja al terminal | identidad de CAPTURA y transiciones autorizadas |

Congelar bytes mutables no es lo que hace falta: lo que hace falta es que el
`ok` que habilita el cierre sea **el de la misma comparación** que estaba
`pending` cuando se registró la causa. `habilita_cierre()` no alcanza — mira
estado y tiempos, no procedencia—, así que un `ok` de OTRA captura habilitaría
un `COMPLETED` que nadie autorizó.

Por eso el request congela, cuando hay una comparación en curso:

```
captura_autorizada = {desde, digest, firma, copia}
```

y al publicar se exige una de estas dos transiciones, y ninguna otra:

| transición | qué se exige |
|---|---|
| `pending → ok` | `ultima_ok.digest` y `ultima_ok.firma` iguales a los de la captura autorizada |
| `pending → divergent` | `detalle.esperado` identifica ESA captura (`digest` y `firma`) |

Cualquier otra procedencia —un `ok` cuyo digest no es el autorizado, una
divergencia contra otra captura, o un sidecar que volvió a `pending` con una
captura distinta— es **fallo cerrado**. Sin comparación en curso al registrar,
`captura_autorizada` es `null` y no se exige nada: no hay causalidad que
preservar porque no hay comparación de la cual derivar.

#### 13.4.2 El sidecar de verificación tiene registro cerrado *(rev.17)*

Un sidecar AUSENTE, con un estado fuera de `{ok, deferred, pending,
divergent}`, o con los campos de su estado mal formados, es **fallo cerrado
para CUALQUIER ganador** — no solo para los científicos.

rev.16 solo lo exigía para los científicos, con el argumento de que
`BLOCKED_INTEGRITY` no ejecuta cierre científico. Pero §9.1.2 hace que
`silencio_h4` sea RETENIDO mientras haya una comparación `pending`: sin poder
leer el sidecar no se sabe si la hay, y publicar el bloqueo asumiendo `ok`
—que es lo que devuelve un objeto recién construido— saltea justamente la
retención que impide que una divergencia posterior nunca ejerza su
precedencia.

### 13.5 Matriz de reanudación *(rev.10)*

«Recargar y aplicar» admitía implementaciones distintas. Para un request cuyo
ganador es CIENTÍFICO, al reanudar se recarga `verificacion.json` desde disco
—el objeto en memoria se perdió con la caída— y se aplica esta matriz:

| estado del sidecar | qué se hace |
|---|---|
| `ok` y posterior a toda deferencia | se publica `COMPLETED` |
| `pending` | se MANTIENE el cierre en curso: ni ciclos ni publicación. La comparación fría se reanuda desde la copia (§13.5.1) y al terminar intenta la fase B (§9.1.3) |
| `deferred` con ganador CIENTÍFICO | **fallo cerrado**: estado inalcanzable (§13.5.0) |
| `deferred` con ganador de INTEGRIDAD | se PUBLICA: no hay comparación activa que pueda aportar más (§9.1.2) |
| `divergent` | se ANEXA `determinism_divergence` con su evidencia al request y se publica `BLOCKED_INTEGRITY` |
| ausente, corrupto o de otra identidad | **fallo cerrado** |

Para un ganador de INTEGRIDAD la verificación no HABILITA nada —
`BLOCKED_INTEGRITY` no ejecuta cierre científico (§13.1)—, pero un
`silencio_h4` sí queda RETENIDO mientras haya una comparación fría realmente
`pending` (§9.1.2). Sin esa retención, el silencio publicaba mientras la
comparación corría, el terminal quedaba inmutable y una divergencia posterior
nunca ejercía su precedencia.

**`deferred` NO retiene** *(rev.13)*: una deferencia significa que no hay
captura ni comparación activa, y resolverla exigiría una captura nueva, que
vive en un ciclo — prohibido durante la ventana. Esperar ahí sería esperar a
un productor que no existe, y el bloqueo quedaría detenido para siempre. Con
`deferred` y ganador de integridad se **publica**.

`COMPLETED` exige verificación `ok` y posterior a toda deferencia, y esa
comprobación se hace en la reanudación igual que en la publicación en vivo: sin
ella, una caída durante `pending`, `deferred` o `divergent` deja que el
arranque siguiente publique el `COMPLETED` que antes se rechazó. `reanudar`
RECARGA el sidecar desde disco; no confía en un objeto en memoria que la caída
perdió *(rev.9, fusionado acá en rev.11)*.

#### 13.5.0 `deferred` con un request científico es IMPOSIBLE *(rev.12)*

Una deferencia exige vaciar buffers y volver a capturar, y capturar ocurre
dentro de un ciclo — que durante `cierre_en_curso` no abre. Si esa combinación
existiera, la cohorte quedaría trabada sin salida.

No existe, y por construcción:

- una causa CIENTÍFICA solo puede registrarse con la verificación `ok`: la
  zona de corte (§9.0) no deja procesar lotes sin ella, y el corte
  administrativo tampoco corre sin ella (§13.5);
- durante la ventana de recolección no se abre ningún ciclo, así que **no
  puede aparecer una deferencia nueva**: las deferencias las produce el intento
  de captura, que vive en el ciclo;
- y dentro del ciclo que corta, la causa se registra ANTES de atender ningún
  `verify.request` (§12, orden congelado en rev.14). Sin esa regla el hueco
  quedaba abierto: bastaba que la captura del mismo ciclo encontrara buffers
  para producir la deferencia justo antes del registro.

Por lo tanto `deferred` junto a un request cuyo ganador es científico es un
estado que la máquina no puede alcanzar. Observarlo significa que algo anterior
falló, y **falla cerrado** en vez de intentar resolverlo con una operación que
el diseño no contempla.

`deferred` con un ganador de INTEGRIDAD sí es alcanzable —la deferencia pudo
quedar de antes—, y ahí la ventana NO espera: sin comparación activa no hay
nada que aportar, así que se publica el bloqueo (§9.1.2) *(rev.13)*.

#### 13.5.1 Quién resuelve un `pending` tras el reinicio *(rev.11)*

«Se espera» dejaba un vacío: con `cierre_en_curso` no se abre ningún ciclo, así
que si la comparación fría dependiera de un ciclo, la cohorte quedaría trabada
para siempre.

La comparación fría **no es un ciclo y no ingiere**: reconstruye desde una
copia y compara. Puede y debe continuar durante `cierre_en_curso`, y es el
registrador de la causa de divergencia si corresponde (§9.1.1).

Para que sobreviva a un reinicio, la captura tiene que ser recuperable:
`verificacion.json` guarda, además del estado, la RUTA de la copia scratch, el
`digest` y la `firma` capturados. Al arrancar con `pending`:

| situación | qué se hace |
|---|---|
| la copia existe y valida | el ARRANQUE reanuda la comparación fría desde ella, la COMPLETA y dispara la fase B con su resultado — no se queda esperando: nadie más la despertaría (§9.1.3) |
| la copia falta o no valida | **fallo cerrado**: no se puede certificar ni descartar el determinismo, y sin eso no hay `COMPLETED` posible |

No se re-captura sobre el estado actual: sería comparar contra una barrera
distinta de la que quedó pendiente.

### 13.6 Cuándo un terminal publicado domina un request residual *(rev.10)*

«El terminal manda» sin condiciones permitía que un `COMPLETED` sobreviviera a
un request residual cuyo ganador es `determinism_divergence` — es decir,
conservar como evaluable una cohorte que ya tenía una causa de integridad
anotada.

El request se archiva como recuperación NORMAL solo tras pasar esta secuencia,
**en este orden** *(rev.11)*:

1. **forma**: `schema_version` == 2 (§13.7), `checksum` válido, identidad
   (`cohorte`, `contrato`, `commit`) igual a la de la cohorte viva. Sin esto no
   se calcula nada más: un request malformado no puede aportar un ganador;
2. **motivos**: todos en el registro cerrado (§13.2); **dos motivos
   científicos → fallo cerrado ANTES de calcular ganador** (§13.2.1);
3. **coherencia interna**: `evidencia == evidencias[motivo]`. Un ganador con
   la evidencia de otra causa es un request corrupto, no uno discutible;
4. **estado autorizado**: TODOS los campos de `estado_esperado` —los 14 heads,
   la firma del libro y el hash de `silencio.json`—, no solo heads y firma; y
   la `captura_autorizada`, si la hay, con una de las dos transiciones
   permitidas (§13.4.1);
5. **familia**: el terminal publicado es exactamente el que deriva del ganador
   (§13.2). `completed.json` con un ganador de integridad no coincide.

Cualquier discrepancia es **fallo cerrado**. En particular, `completed.json`
con un request de INTEGRIDAD nunca es normal.

### 13.7 El schema del request se versiona *(rev.10)*

El request pasó de dos motivos y una evidencia a cinco motivos, `evidencias`
por motivo, ganador derivado y coexistencia normal con un terminal publicado.
Eso es otro formato: `SCHEMA_TERMINAL` sube a **2**.

Como nunca se desplegó, **no hay migración**: cualquier `schema_version`
anterior se rechaza con fallo cerrado. Migrar un formato que nunca existió en
producción solo agregaría una ruta sin probar.

## 14. Fail-closed

| Situación | Respuesta |
|---|---|
| `serverTime` indisponible | no se ingiere en ese ciclo |
| Deriva del reloj local > `DERIVA_MAX` | incidencia operacional visible |
| Página inválida (orden, grilla, duplicado, TF) | se descarta entera |
| Página llena sin progreso | fallo cerrado |
| Lag > `LAG_MAX` en cualquiera de los 14 | modo `catch-up` (§11) |
| Precondición H4 incumplida | no se procesa ningún lote |
| Hueco local (M15 o H4) | `declarar_hueco_local` al cumplirse el watermark |
| Silencio de un mercado en M15 | `watermark_exchange` (CF-29), degradación |
| Ausencia H4 | solo watermark local; el mercado cae en `historia_insuficiente` |
| `vela_revisada` | se registra; **no** se reescribe lo sellado |
| Nacimiento parcial sin manifiesto | se descarta `staging/` y se renace |
| Manifiesto sin sus 14 almacenes | fallo cerrado |
| Snapshot canónico alterado | fallo cerrado (ya vigente) |
| Árbol de `modules/bot3/v9` sucio | fallo cerrado (ya vigente) |
| Identidad de cohorte distinta | fallo cerrado (ya vigente) |
| Última trama truncada | se descarta y se recupera por replay (§5.1) |
| Trama con hash distinto, o rota no final | fallo cerrado (§5.1) |
| Silencio H4 > `SILENCIO_MAX_H4` | `BLOCKED_INTEGRITY(silencio_h4)`, no evaluable (§6.5) |
| Verificación `pending` fuera de la zona de corte | se procesa normal; **no** se publica `COMPLETED` (§9.1) |
| Verificación no-`ok` **en** la zona de corte | no se procesa ningún lote (§9.0) |
| `terminal.request` sin terminal publicado | se valida y se reanuda según la matriz (§13.5), no se ingiere |
| terminal publicado **y** request COINCIDENTE | recuperación normal: se archiva el request (§13.6) |
| terminal publicado **y** request DISCREPANTE | fallo cerrado (§13.6) |
| motivo fuera del registro cerrado | fallo cerrado (§13.2) |
| dos motivos científicos a la vez | fallo cerrado (§13.2) |
| `SCHEMA_TERMINAL` anterior a la versión vigente | fallo cerrado, sin migración (§13.7) |
| `silencio.json` con `doc_sha256`, cadena, monotonicidad o acumulado inconsistentes | fallo cerrado (§6.5.1) |
| Divergencia de determinismo | `BLOCKED_INTEGRITY(determinism_divergence)` (§9.1) |
| `completed.json` o `blocked.json` presente | no se reactiva (§13) |

## 15. Parámetros a congelar en el protocolo

`CADENCIA`, `MARGEN_CIERRE`, `RESOLAPE`, `LIMITE_PAGINA`, `LAG_MAX` (por TF),
`DERIVA_MAX`, `SILENCIO_MAX_H4`, `TOPE_INTERVALO`, `BACKOFF_BASE`, `BACKOFF_MAX`, `BACKOFF_INTENTOS`,
`TF_OBSERVADAS`, `UNIVERSO`, `ENDPOINT_KLINES`, `ENDPOINT_TIME`,
`CADENCIA_VERIFICACION`, `MOTIVOS_CIENTIFICOS`, `MOTIVOS_INTEGRIDAD`,
`PRECEDENCIA_TERMINAL`, `MAX_TRANSITORIOS` y `EXIT_TIMEOUT` *(rev.20)*,
`CONNECT_TIMEOUT`, `READ_TIMEOUT` *(rev.22)*, `REQUEST_DEADLINE` *(rev.23)*,
`MAX_SOBRE` *(rev.26)* y `CIERRE_COOPERATIVO` *(rev.28)*, y las
rutas de estado, libro, lock, staging, los dos
marcadores terminales (`completed.json`, `blocked.json`) y los sidecars
(`silencio.json`, `verificacion.json`, `fallo_cerrado.json` *(rev.20)*) y
`terminal.request`.
Ninguno se elige en operación.

`bootstrap_hasta` **no** es parámetro del observador: es la identidad de la
cohorte y se congela en el acta de activación.

## 16. La frontera congela las dos TF

El acta de activación congela el último `t` y el último cierre de **cada uno de
los 14 snapshots**; `bootstrap_hasta = F`, último cierre M15 común a los siete
mercados; en H4, **exactamente** las velas con cierre `≤ F` como historia causal
elegible; y hashes, commit y auditoría de continuidad de ambas TF.

Una vela H4 que cierre después de `F` no influye en la primera decisión forward
aunque ya exista físicamente. Hoy los snapshots terminan en instantes distintos
(M15 2026-06-11 19:30, H4 2026-06-14 20:00), así que no es teórico.

## 17. Gates de aceptación

1. append push y caída en **cada** frontera de almacén y de metadata;
2. M15 fresco con H4 atrasado o ausente → cero lotes procesados;
3. `singleton_lock` retenido mientras la captura espera la barrera interna, y
   ninguna segunda instancia admitida durante la espera;
4. solicitud de captura atendida **sin readquirir** el mutex (§9);
5. verificación periódica → heads, digest y libro del daemon byte a byte
   iguales antes y después;
6. **verificación diferida con buffer no vacío**: un hueco con dos de las tres
   velas probatorias en buffer NO puede producir un `determinism_ok` (§8.1);
7. digest cambia al alterar un cierre **intermedio** sin cambiar cardinalidad ni
   último elemento;
8. **durabilidad almacén→libro**: caída tras cada uno de los cuatro pasos de §5
   —incluido el marcador que crea `watermark_exchange` durante el lote— y la
   recuperación produce exactamente el mismo almacén y el mismo libro;
9. watermark H4 local con prueba reproducible; el mercado queda en
   `historia_insuficiente` **sin bloquear a los otros** una vez sellado;
10. hueco H4 local emite `hueco_detectado(tf="4h")` **exactamente una vez**, con
    heads y finalidad correctos (§6.3);
11. **silencio H4 total** más allá de `SILENCIO_MAX_H4` → `BLOCKED_INTEGRITY`
    persistente, que sobrevive al reinicio y no se presenta como evaluable;
12. separación `eligibility_time` / `processed_at`: ningún evento lleva el reloj
    de Binance como `processed_at`;
13. paginación alineada, progreso estricto y backlog multipágina;
14. `eligibility_time` indisponible o desalineado del reloj del Mac;
15. recuperación desde lag mayor que `LAG_MAX` sin procesar prematuramente;
16. activación con cierres terminales H4 y M15 distintos;
17. corte por N y corte temporal, seguidos de reinicio del servicio →
    `COMPLETED` sobrevive; marcador corrupto → fallo cerrado; los dos
    marcadores presentes → fallo cerrado;
18. **caída después de cada uno de los renames del nacimiento**, incluido el
    rename único del directorio (§4);
19. continuo sobre N+1 vs. N + reinicio + push de N+1 → mismo libro y mismo
    `state_digest`;
20. re-ingesta por push de una vela ya sellada desde el snapshot → **sin**
    incidencia (mapeo idéntico).
21. **`SILENCIO_MAX_H4` normativo**: las **mismas observaciones probatorias**
    (mismos `eligibility_time`) reagrupadas en distinto número de ciclos o de
    llamadas internas, **dentro de una misma continuidad de ejecución**,
    producen **bytes idénticos**. Un reinicio NO entra acá: cae en el gate 38;
22. errores HTTP, `eligibility_time` indisponible, daemon apagado y catch-up
    **no** avanzan el silencio H4;
23. **torn write** en almacén y en libro: caída en bytes representativos de la
    última escritura, antes y después del `fsync`; tras recuperar, cadena y
    libro idénticos a la ejecución continua;
24. trama completa con hash alterado → fallo cerrado, distinguible de la
    truncación;
25. `BLOCKED_INTEGRITY` **no** emite eventos de cierre ni resultado, y no toca
    el libro científico;
26. `verificacion.json` sobrevive al reinicio: tras una deferencia, el reporte
    exige una verificación exitosa posterior;
27. divergencia detectada después de soltar la barrera → impide `COMPLETED` y
    termina en `BLOCKED_INTEGRITY(determinism_divergence)`.
28. **semántica de silencio discriminante**: misma ausencia H4; la corrida A
    observa continuamente y la B queda 80 h apagada. A bloquea al acumular la
    evidencia; **B no**. Y el complemento: **quitar** observaciones retrasa el
    terminal exactamente lo que predice `TOPE_INTERVALO` —no produce el mismo
    terminal—, que es la sensibilidad buscada (§6.5.1.2);
29. `offline_ms` queda registrado en `silencio.json` aunque no cuente como
    evidencia;
30. paginación H4 incompleta (error HTTP en una página, o sin página vacía
    final) **no** inicia ni avanza el silencio ni mueve `t_observacion_previa`;
31. **`observer_state_digest`**: alterar solo el origen o la evidencia de
    `silencio.json`, con motor, almacenes y libro intactos, **cambia el digest**;
32. **zona de corte**: verificación `pending` justo antes del cierre 50 y justo
    antes del corte temporal, con las dos ramas (igualdad y divergencia). En la
    rama divergente el libro **no contiene ningún evento terminal nuevo**;
33. **transición serializada**: inyectar la divergencia en cada frontera entre
    ciclos produce exactamente el mismo estado, libro y `blocked.json`;
34. caída a mitad de la transición terminal → al arrancar se reanuda desde la
    barrera y no se ingiere;
35. **encuadre**, gates por caso: longitud menor, longitud mayor, hash alterado,
    encabezado fuera de gramática, payload UTF-8 incompleto, y cada uno con
    `\n` presente y ausente. Solo el último segmento sin `\n` es truncable;
36. `COMPLETED` rechazado con estado `deferred` sin verificación exitosa
    posterior, no solo con `pending`.
37. **máquina de silencio**, un gate por transición: primera ausencia (aporta
    cero); backfill antes del umbral (pasa a `resuelto` y deja de gobernar);
    dos mercados simultáneos; dos huecos del mismo mercado; observación
    duplicada; `eligibility_time` repetido y **regresivo** (aportan cero y no
    mueven el puntero); y reinicio en **cada** una de esas transiciones;
38. **primer intervalo tras arranque aporta cero**, no `TOPE_INTERVALO`: una
    corrida partida en dos por un reinicio acumula estrictamente menos que la
    continua, y nunca más;
39. **autenticación de `silencio.json`**: alterar cada campo decisional
    conservando JSON válido → **fallo cerrado**, no otro digest aceptado.
    Incluye cadena de evidencia rota, monotonicidad violada y acumulado que no
    se deriva de `observaciones`;
40. **`terminal.request`, contrato completo** *(rev.11)*: `SCHEMA_TERMINAL`
    anterior rechazado sin migración; los cinco motivos válidos aceptados y
    cualquier otro rechazado; DOS motivos científicos rechazados antes de
    calcular ganador; integridad sobre científico en LOS DOS órdenes de
    llegada; publicación con `estado_esperado` alterado —heads, firma o hash
    de cualquier sidecar— falla cerrado; la matriz de reanudación completa
    (`ok`, `pending`, `deferred` con cada familia, `divergent`, sidecar
    ausente o de otra identidad); terminal + request COINCIDENTE se recupera
    archivando; cada una de las cinco discrepancias de §13.6 falla cerrado; y
    caída en CADA frontera entre barrera, request, terminal y archivado;
40bis. **concurrencia de la transición** *(rev.12/13)*, con el mutex REAL, no
    un doble: un registrador B entra después de A y ANTES de publicar; ningún
    ciclo de ingesta entra en esa ventana; `silencio_h4` con la comparación
    fría `pending` NO publica, y al resolver `divergent` el terminal es por
    divergencia — en los dos órdenes de llegada; caída durante CADA una de las
    dos fases de barrera;
40ter. **condición de cierre por GANADOR** *(rev.13)*: con
    `determinism_divergence` en el request se publica aunque la comparación
    siga `pending`; `silencio_h4` con `deferred` PUBLICA y no queda detenido;
    `deferred` con ganador científico falla cerrado; una fase B que observa
    `divergent` sin la causa en el request la ANEXA antes de calcular el
    ganador —gate con la escritura del sidecar y el registro separados, que es
    la carrera real—; y la finalización de la comparación intenta la fase B en
    sus cuatro salidas, sin que ningún ciclo la despierte;
40quinquies. **los tres disparadores de la fase B** *(rev.16)*: reinicio con
    un `terminal.request` pendiente inicia la fase B SIN ingerir —ningún ciclo
    se abre— y produce EXACTAMENTE el mismo terminal que la ejecución continua
    que no se cayó: mismo motivo, misma evidencia, mismos heads y misma firma;
40quater. **orden del final del ciclo** *(rev.14)*: corte número 50 y un
    `verify.request` pendiente en el MISMO ciclo, con buffers NO vacíos. La
    causa científica se registra ANTES, no se crea ninguna deferencia nueva, la
    verificación conserva el estado que tenía, y el `verify.request` queda sin
    atender y se ARCHIVA con el terminal. Con el mutex REAL: sin readquisición
    dentro del ciclo —una implementación literal de rev.14 hacía deadlock— y
    con la fase B invocada DESPUÉS de liberar. Más la distinción borrar vs.
    archivar: `terminal.request` borrado en el flujo normal y ARCHIVADO cuando
    es un residual coincidente tras caída, y fallo cerrado si discrepa;
41. **cota de la zona de corte demostrada** contra el orden completo de fases
    del motor —`fill+STOP` en el mismo lote incluido— sobre los siete mercados:
    ningún lote produce más cierres que mercados con posición u orden viva.
42. **`run_epoch` reconstruye el acumulado** *(rev.8)*: tras N reinicios, el
    recálculo desde `observaciones` da exactamente el valor persistido. Sin
    `run_epoch` el gate falla, que es lo que demuestra que hace falta;
43. **`doc_sha256` cubre el documento entero**: alterar `estado`,
    `primer_cierre`, `ultimo_cierre_valido`, `offline_ms` o
    `evidencia_acumulada_ms` —campos que la cadena de evidencia NO cubre—
    conservando JSON válido → fallo cerrado;
44. **anexión atómica a `terminal.request`**: caída en cada paso de la anexión;
    el `motivo` ganador no cambia por orden de llegada, solo por precedencia;
    dos anexiones concurrentes quedan serializadas por `cycle_barrier`.

## 18. Secuencia de activación

1. diseño (este documento) → auditoría → aprobación;
2. protocolo del observador pre-registrado con hash;
3. implementación **solo en scratch**, con datos sintéticos o copias;
4. gates §17;
5. auditoría de la implementación (incluye el cambio de manifiesto de §3-§4);
6. recién entonces, actualizar los snapshots canónicos hasta el último M15
   cerrado común;
7. congelar snapshots, commit, hashes y `bootstrap_hasta` (§16);
8. desplegar el observador e iniciar la cohorte desde la vela siguiente.

## 19. Registro de anomalía conocida

Hueco 2023-03-24 12:45 → 13:45 (5 velas M15) en los siete mercados.
Clasificación: **`common_upstream_gap` / causa no demostrada.**

## 20. Punto de entrada y servicio *(rev.18)*

Todo lo anterior describe QUÉ hace el observador. Falta quién lo arranca, en
qué orden, y qué pasa cuando se cae o cuando termina. Sin congelarlo, cada
detalle admite dos implementaciones honestas con resultados distintos — que es
lo que §10 evita para la ingesta y acá quedaba abierto.

### 20.0 Fase de activación: quién crea el estado inicial *(rev.19)*

§20.2 exige manifiesto, 14 almacenes, libro y `verificacion.json` ANTES de
arrancar, y §20.7 le prohíbe al servicio crearlos. rev.18 no decía quién los
creaba, así que el primer lanzamiento fallaba cerrado siempre.

Los crea una **herramienta de activación de una sola pasada**, que no es el
servicio y no ingiere: corresponde a los pasos 6–7 de §18 y corre una vez,
antes de habilitar el daemon.

**Todo se construye en `cohorte.new/` y se publica con UN SOLO rename**
*(rev.20)*. rev.19 creaba seis artefactos por etapas sobre el directorio
definitivo, y cualquier caída después de `acta.json` dejaba «estado existente»
— que la propia herramienta declara motivo de fallo cerrado. La activación era
irreintentable justo en el momento más probable de fallar.

**Serializada por un lock EXTERIOR al directorio publicado** *(rev.21)*:
`<raiz>/activacion.lock`, un `flock` tomado ANTES de mirar, borrar o crear
`cohorte.new/`, y sostenido hasta después del rename. Sin él, dos activaciones
concurrentes escriben el mismo staging y publican una mezcla de las dos; el
lock no puede vivir dentro de `cohorte.new/` porque el primer paso de la
herramienta es borrarlo entero.

```
en cohorte.new/  (descartable entero, nunca es el estado vivo)
  1. acta.json          cohorte, commit, bootstrap_hasta y la frontera de §16
  2. nacimiento de los 14 almacenes desde los snapshots canónicos (§4)
  3. libro y manifiesto  con el prefijo de nacimiento de cada stream (§3)
  4. REPLAY del prefijo sellado sobre ese motor recién nacido      (§20.2.1)
  5. comparación fría REAL en la frontera: se copia el estado, se reconstruye
     en frío y se comparan digest y firma — DOS motores reconstruidos, no dos
     instancias vacías que coinciden por estar ambas en cero
  6. verificacion.json   `ok`, con el digest y la firma de ESA comparación
publicación
  7. un solo rename: cohorte.new/ → el directorio de estado, con la MISMA
     secuencia de durabilidad de §4: fsync de cada archivo, fsync de
     cohorte.new/, rename, fsync del directorio PADRE. Sin el último, el
     rename puede no sobrevivir a un corte de energía y el estado publicado
     desaparece aunque su contenido esté en disco
  8. habilitación del servicio
```

La recuperación es trivial y no tiene matriz: si existe `cohorte.new/`, se
BORRA entero y se empieza de nuevo. Nunca fue el estado vivo, así que no hay
frontera intermedia que reconciliar — el mismo argumento de §4, un nivel más
arriba.

El paso 5 no es ceremonial. `verificacion.json` inicial en `ok` es lo que
§13.4.2 exige leer y lo que §13.4.1 usa como procedencia; escribirlo sin haber
comparado nada sería declarar acreditado un determinismo que nadie verificó, y
la primera comparación real —seis horas después— ya no tendría con qué
contrastar el nacimiento.

La herramienta **falla cerrado si el estado vivo ya existe**: no re-nace una
cohorte viva, no pisa un `acta.json` publicado y no toca marcadores terminales.

**Una cohorte cerrada se ARCHIVA, no se borra** *(rev.20)*. rev.19 decía que
borrar el directorio «deja rastro»: es falso, borra exactamente la evidencia
—el libro, los almacenes sellados y el marcador terminal— que hace evaluable a
la cohorte. El directorio se renombra a `cohortes/<id>/` y queda intacto.

Y una reactivación **exige identidad NUEVA**: otra `cohorte`, con su propia
acta y su propia frontera. Reusar el identificador haría que dos libros
distintos afirmaran ser la misma cohorte, y ningún resultado publicado podría
atribuirse sin ambigüedad.

### 20.1 Identidad: de dónde sale, y no se elige en operación

| campo | origen | por qué no puede ser un argumento |
|---|---|---|
| `contrato` | `CONTRATO_HASH` del módulo | es el contrato del motor, congelado |
| `commit` | `git rev-parse HEAD` del árbol que corre | un despliegue tiene que salir del commit versionado, nunca del working tree |
| `cohorte` | `acta.json`, escrita en el paso 7 de §18 | la identidad de la cohorte se congela ANTES de arrancar |
| `bootstrap_hasta` | `acta.json` | §15: no es parámetro del observador |

El arranque **exige árbol limpio** (`validar_arbol_limpio`) y que el `commit`
del acta sea el `HEAD` vigente. Un árbol sucio o un commit distinto es fallo
cerrado: si el proceso corriera desde código no versionado, el `commit` que
firma cada evento del libro no identificaría lo que realmente produjo el
evento, y el libro dejaría de ser reproducible — que es la única propiedad que
la cohorte tiene que sostener.

### 20.2 Orden CONGELADO del arranque

```
1. tomar singleton_lock          (flock de vida completa, §7)
2. validar árbol limpio y commit == acta.commit
3. clasificar fallo_cerrado.json si existe: `1` bloquea, `2` continúa (§20.6.4)
4. cargar manifiesto y los 14 almacenes  (Almacen.cargar, requerido=True)
5. cargar libro; construir Motor con acta.bootstrap_hasta
6. REPLAY canónico del prefijo sellado, SIN ingerir      (§20.2.1)
7. cargar sidecars: silencio.json (si existe) y verificacion.json (OBLIGATORIO)
8. reanudar()                    (§13.5) — ANTES de abrir ningún ciclo
9. si hay terminal publicado o reanudar lo produjo: NO se abre ningún ciclo
10. recién entonces, el bucle de ciclos
```

Los pasos 1–8 no ingieren nada. El orden importa en los dos extremos: el lock
va PRIMERO porque dos procesos sobre los mismos almacenes es la corrupción que
§7 impide, y `reanudar()` va antes del bucle porque un `terminal.request`
pendiente prohíbe abrir ciclos (§13.3) y el arranque es uno de los tres
disparadores de la fase B (§9.1.3).

#### 20.2.1 El replay NO es opcional *(rev.20)*

El `Motor` **no persiste** candidatos, órdenes vivas, posiciones abiertas ni
`lotes_finalizados`. Su recuperación contractual es por REPLAY: se reconstruye
procesando otra vez la secuencia canónica sobre el prefijo ya sellado.

rev.19 construía un motor y pasaba directo a `reanudar()`. Con eso, un reinicio
con `terminal.request` pendiente evaluaba la reanudación contra un motor
**vacío**: sin posiciones que cerrar al corte, sin `cierres` que acreditaran el
motivo `muestra`, y con `watermark_lotes()` en `None` — el ciclo siguiente
habría reprocesado la historia entera sobre el motor vivo.

El replay:

- recorre **solo los cierres ya sellados** en los almacenes, nunca ingiere ni
  crea lotes nuevos. Es la misma secuencia de `reconstruir_en_frio` (§9), con
  la única diferencia de que corre sobre los almacenes vivos;
- **no DUPLICA eventos, pero sí puede REPONER los que falten** *(rev.22)*: el
  libro es idempotente por `event_id`, así que cada evento que el replay
  reemite y ya existe se descarta. rev.20 decía «no muta nada durable» y era
  demasiado fuerte: §5 ordena almacén → `fsync` → libro, así que una caída en
  esa ventana deja un marcador durable cuyo evento no alcanzó a escribirse, y
  el replay lo repone. Es exactamente la reparación que la ordenación de §5
  hace posible, y es idempotente: reponer lo faltante y descartar lo presente
  convergen al mismo libro;
- y por eso es, además, una **verificación**: si el prefijo sellado dejara de
  reproducir los mismos eventos, el libro rechazaría el append por «payload
  distinto» y el arranque fallaría cerrado. Un reinicio prueba, gratis, que la
  historia sigue siendo la que se selló.

**`verificacion.json` es obligatorio** también en el primer arranque de la
cohorte: el acta lo escribe en estado `ok` con la captura de la frontera. Un
observador que lo cree por su cuenta al no encontrarlo estaría fabricando la
acreditación que §13.4.2 exige leer.

### 20.3 El bucle: un pull, un ciclo, una cadencia

`CADENCIA` (60 s) se mide contra un reloj **monótono** local, no contra el
`serverTime` ni contra el reloj de pared: el reloj de pared puede saltar
—NTP, cambio de hora— y un salto hacia atrás detendría los pulls hasta
alcanzarlo, mientras que uno hacia adelante dispararía una ráfaga.

El proceso es de **un solo hilo de ciclo**. No hay ciclos concurrentes: si un
ciclo tarda más que la cadencia, el siguiente arranca apenas termina el
anterior, sin acumular deuda ni ejecutar dos a la vez. La `cycle_barrier`
sigue siendo necesaria —la comparación fría corre fuera del ciclo—, pero
nunca se usa para serializar dos ingestas.

Un ciclo que no puede ingerir —sin reloj, `cierre_en_curso`, terminal— **no es
un error**: registra su motivo y espera la cadencia siguiente.

**Algoritmo exacto tras un ciclo atrasado** *(rev.19)*. Con `t0` el instante
monótono en que arrancó el ciclo:

```
proximo = t0 + CADENCIA
espera  = max(0, proximo - monotonic())     # 0 si el ciclo se pasó
```

La deuda **se descarta**: no se encadenan pulls para «recuperar» los que la
cadencia perdió. Un ciclo que tardó cinco minutos no dispara cinco pulls
seguidos — traerían las mismas velas, y la única diferencia sería cinco
oportunidades de tropezar con el límite de tasa del exchange.

### 20.4 Reintentos: el backoff vive en el `fetch`, no en el ciclo

`BACKOFF_BASE` → `BACKOFF_MAX`, `BACKOFF_INTENTOS`, exponencial. Se agota
DENTRO de una llamada `fetch`; el ciclo nunca reintenta por su cuenta.

Es la separación que hace que un error de red no pueda convertirse en
evidencia: si el `fetch` agota los intentos, `paginar` falla cerrado y §11
deja el ciclo sin ingerir. La máquina de silencio solo cuenta observaciones
PROBATORIAS —paginación válida y completa que no trajo la vela exigible—, y
una paginación que falló no lo es. Un ciclo que reintentara por su cuenta
podría cerrar la paginación con una página vacía de una respuesta parcial, y
eso sí sería evidencia falsa de que el mercado enmudeció.

**Enum CERRADO de resultados, y una sola política** *(rev.27)*. rev.26 dejaba
dos frases que se contradecían —§20.4 hablaba de «timeout, 5xx, conexión caída
y 429», §20.4.1 afirmaba que «el único reintentable es el deadline»— y el campo
`error` del sobre no tenía valores definidos. La tabla es esta, y no hay otra:

| `error` del sobre | qué es | consume intento y entra al backoff |
|---|---|---|
| `dns` | la resolución falló | sí |
| `conexion` | conexión rechazada o caída | sí |
| `tls` | handshake fallido | sí |
| `lectura` | `READ_TIMEOUT` o corte a mitad del cuerpo | sí |
| `http_429` | límite de tasa | sí, y respeta `Retry-After` (§20.4) |
| `http_5xx` | error del servidor | sí |
| `http_4xx` | cualquier otro 4xx | **NO**: `codigo: 1` |
| `interno` | el trabajador falló por su cuenta | **NO**: `codigo: 1` |
| *(cualquier otro valor)* | protocolo desconocido | **NO**: `codigo: 1` |

Más el `deadline`, que lo determina el PADRE y no viene en ningún sobre:
consume intento y entra al backoff.

`http_4xx` falla cerrado porque los parámetros del pedido están congelados
(§15): un `400` significa que el contrato del exchange cambió y un `403`/`418`
que estamos bloqueados. Ninguno se arregla reintentando, y reintentar un baneo
lo empeora.

Y una respuesta bien formada que no cumple el contrato de datos
—`PaginaInvalida`— **tampoco se reintenta**: pedir de nuevo lo mismo no la va a
arreglar, y reintentar sobre datos incoherentes es cómo se cuela una serie
ajena.

**Fórmula CONGELADA** *(rev.19)*. Para el intento `n = 1 … BACKOFF_INTENTOS`:

```
techo_n = min(BACKOFF_MAX, BACKOFF_BASE * 2**(n-1))
espera_n = uniform(0, techo_n)                        # full jitter
```

`BACKOFF_INTENTOS` (5) es el número de INTENTOS totales, no de reintentos.
**Solo se DUERME después de los fallos 1 a 4**; el quinto fallo levanta de
inmediato, sin esperar. Dormir tras el último sería retrasar el fracaso sin
cambiarlo, y la espera se la comería el `ExitTimeOut` de §20.6. El jitter completo es deliberado —los 14
streams de un ciclo reintentando en fase sincronizada son una ráfaga contra el
mismo endpoint—, y es **la única fuente de aleatoriedad del observador**: vive
en la capa de transporte, no entra en ningún hash, ningún evento ni ninguna
decisión, así que no afecta la reproducibilidad del libro.

**`Retry-After`** *(rev.20, interpretación congelada)*. Si la respuesta `429`
o `503` lo trae, reemplaza al jitter de ESE intento:

- se aceptan las dos formas del estándar: **segundos** enteros y **HTTP-date**,
  esta última convertida a `max(0, fecha − ahora)` con el reloj local;
- un valor malformado, negativo o no numérico **se ignora** y se usa el jitter:
  una cabecera rota no debe poder detener ni acelerar el ciclo;
- el resultado se acota a `[0, BACKOFF_MAX]` — sin la cota, un `Retry-After`
  hostil o mal configurado dormiría el ciclo por horas;
- consume un intento igual, así que el total sigue acotado;
- y **no se respeta tras el último fallo**: ahí se levanta, como arriba.

### 20.5 Quién escribe `verify.request`

Dos escritores, y ninguno es el ciclo:

| quién | cuándo |
|---|---|
| el propio proceso, al iniciar un ciclo | si pasaron ≥ `CADENCIA_VERIFICACION` (6 h) desde la última captura |
| un operador | dejando el archivo a mano, para auditar bajo demanda |

El ciclo lo **atiende**, no lo crea (§12), y solo si el motor no cortó. El
instante de la última captura sale de `verificacion.json`, no de una variable
en memoria: si viviera en memoria, cada reinicio reiniciaría el reloj de las
6 h y una cohorte que se reinicia seguido no se verificaría nunca.

**Referencia temporal por estado** *(rev.19)*, porque «la última captura» no
está en el mismo campo en los cuatro:

| estado | campo | qué instante es |
|---|---|---|
| `ok` | `ultima_ok.instante` | cuándo terminó la comparación conforme |
| `pending` | `detalle.desde` | cuándo se tomó la captura en curso |
| `deferred` | `ultima_deferencia` | cuándo se intentó capturar y había buffers |
| `divergent` | `detalle.instante` | cuándo se detectó la divergencia |

Todos son el `eligibility_time` del ciclo que los produjo, nunca el reloj local:
la cadencia de verificación se mide en el mismo tiempo que la elegibilidad, y
mezclarlos haría que una deriva del host adelantara o atrasara las capturas.

Con `pending` NO se escribe un pedido nuevo: ya hay una comparación corriendo.
Con `divergent`, tampoco — la fase B va a publicar `BLOCKED_INTEGRITY`.

**Creación ATÓMICA y sin pisar al operador** *(rev.19)*: el archivo se crea con
`O_CREAT | O_EXCL`. Si ya existe —porque lo dejó un operador, o porque un
ciclo anterior lo escribió y todavía no se atendió— **no se toca**. Escribirlo
con `escribir_atomico` reemplazaría la solicitud manual con una idéntica, pero
tras un `rename` que borra el `mtime` con que el operador la reconoce; y peor,
si algún día el pedido llevara contenido, lo perdería.

### 20.6 Apagado, códigos de salida y reinicio *(rev.19)*

`SIGTERM` y `SIGINT` marcan una bandera; **no matan una operación a mitad**.
Qué se termina depende de dónde llegue la señal:

| llega durante | qué se hace |
|---|---|
| un ciclo | se aborta en el punto seguro más cercano —entre streams, o entre unidades de la fase posterior— respetando las CINCO unidades indivisibles de abajo *(rev.25: decía «tres», de antes de que fase A y fase B se separaran)*. Lo sellado queda sellado; lo que falta se rehace el ciclo siguiente *(rev.23: rev.22 decía «termina completo», que contradecía sus propios puntos de cancelación)* |
| la copia de una captura | se ABORTA y se borra el destino incompleto. El sidecar NO queda `pending`: una copia parcial no se puede reanudar (§13.5.1) y dejaría la cohorte trabada |
| la comparación fría | se ABORTA. El sidecar queda `pending` con su copia COMPLETA, y el arranque siguiente la retoma — que es exactamente el caso que §13.5.1 cubre |
| la fase B, entre publicar y borrar | no se interrumpe: es una secuencia de dos operaciones atómicas y §13.6 ya resuelve el estado intermedio |

**Cancelación COOPERATIVA con cota medida** *(rev.20)*. rev.19 fijaba
`ExitTimeOut = 300 s`, y el ensayo a escala ya había medido ~402 s de
reinicio/replay: un `SIGTERM` durante ese camino terminaba en `SIGKILL`, que es
exactamente lo que la tabla de arriba dice evitar. Prometer «terminar el ciclo»
con un plazo menor al peor caso conocido no es una promesa.

Se resuelve por los dos lados:

1. **puntos de cancelación declarados**, donde la bandera se consulta y el
   proceso puede salir sin dejar nada a medias:

   | punto | por qué es seguro |
   |---|---|
   | entre lotes del REPLAY (§20.2.1) | reconstruye estado en memoria y sus appends son idempotentes —reponen lo faltante, nunca duplican—. Se aborta en cualquier lote y el arranque siguiente rehace el mismo camino |
   | entre INTENTOS de un `fetch` *(rev.22)* | nada se ofreció todavía; la página se vuelve a pedir entera |
   | entre PÁGINAS de una paginación *(rev.22)* | `paginar` acumula en memoria y no ofrece nada hasta terminar: abortar descarta la acumulación, no deja media serie |
   | antes de `ofrecer` de cada stream | lo ingerido hasta ahí ya está sellado y sincronizado; lo que falta se pide de nuevo el ciclo siguiente |
   | después de `finalizar_ciclo` | el ciclo cerró completo |
   | entre archivos de la copia | la copia es descartable: se borra el destino incompleto |

   **Regla ÚNICA del ciclo** *(rev.22)*. rev.21 decía a la vez que un ciclo
   «termina completo» y que se podía abortar entre streams: dos
   implementaciones honestas elegían distinto. La regla es:

   > un ciclo se aborta **entre streams** durante la ingesta, y **entre
   > unidades** durante la fase posterior. Las unidades INDIVISIBLES son
   > cinco, y ninguna abarca a otra:
   >
   > | unidad | qué incluye |
   > |---|---|
   > | silencio | actualizar los 14 streams **y persistir `silencio.json`** |
   > | un lote | cada `procesar_lote_canonico`, uno por uno |
   > | fase A | marcar `cierre_en_curso` y anexar la causa al request |
   > | *(ventana de recolección)* | **NO es una unidad**: acá se puede apagar |
   > | fase B | evaluar el ganador y publicar el terminal |

   **Fase A y fase B son unidades SEPARADAS** *(rev.24)*. rev.23 las declaró un
   solo tramo indivisible, que contradice §9.1.1: la transición está congelada
   en dos fases justamente para que la barrera se libere entre ellas y la
   ventana de recolección exista. Un apagado entre A y B es un caso NORMAL y
   ya resuelto — el request queda en disco y el arranque siguiente lo retoma
   por el tercer disparador de §9.1.3, con la equivalencia que el gate
   40quinquies exige. Hacerlas indivisibles habría eliminado la ventana, que
   es lo único que hace real la precedencia.

   Por qué cada una de las otras:

   - **la actualización de silencio** se hace unidad porque abortarla a mitad
     dejaría observaciones de algunos mercados y no de otros: evidencia
     sesgada sobre la que después se decide un terminal;
   - **entre lotes SÍ hay punto seguro**. rev.22 declaraba la fase posterior
     entera indivisible, y eso no tiene cota: tras una caída larga, un ciclo
     ingiere mucho backlog y procesa miles de lotes ahí. `ExitTimeOut` volvía
     a depender de que el futuro se pareciera al ensayo. Cada lote finalizado
     es durable por sí mismo y el reinicio reconstruye por replay (§20.2.1)
     exactamente hasta donde se llegó, así que abortar entre dos no pierde
     nada. La cota pasa a ser **un lote**, no el backlog;
   - **cada fase por separado** es indivisible por lo que ya dice §13: anexar
     al request es atómico (gate 44) y publicar más borrar es la secuencia que
     §13.6 resuelve.

   **`silencio.json` se persiste DENTRO de su unidad, antes de los lotes**
   *(rev.24)*. rev.23 lo dejaba para el camino de salida ordenada, y eso no
   cubre un `SIGKILL`, un pánico ni un corte de energía: la evidencia
   acumulada de los 14 streams se perdía y las 72 h volvían a empezar. La
   escritura atómica y durable es parte de la unidad de silencio, no del
   apagado, así que no depende de por qué el proceso terminó.

   Esto **adelanta** `silencio.guardar()` respecto de dónde lo hace hoy
   `ciclo()` —después de `avanzar_lotes`—, y es un cambio que la
   implementación de §20 tiene que aplicar. Es estrictamente más durable y
   nada posterior toca el sidecar, así que no altera ningún resultado.

2. **timeouts de transporte CONGELADOS** *(rev.22)*, sin los cuales no hay
   cota posible: `CONNECT_TIMEOUT` = 5 s y `READ_TIMEOUT` = 20 s, ambos en
   §15. Una petición sin timeout puede colgarse indefinidamente, y ahí ningún
   punto de cancelación llega nunca.

   **Y un `REQUEST_DEADLINE` absoluto de 30 s** *(rev.23)*, que es la cota
   real. Los dos anteriores NO acotan una petición: `READ_TIMEOUT` limita la
   inactividad entre lecturas, así que un servidor que entrega un byte cada
   19 s la sostiene indefinidamente sin disparar nada, y la resolución DNS no
   está cubierta por `CONNECT_TIMEOUT`.

   **Mecanismo CONGELADO** *(rev.24)*. «Abortar el socket» al vencer no es un
   mecanismo: durante una resolución DNS bloqueada el socket todavía no
   existe, y `getaddrinfo` no es cancelable desde el proceso que la llamó. El
   transporte vive en un **proceso trabajador aislado**:

   - un único subproceso hace TODO el I/O de red. No tiene estado propio: no
     escribe almacenes, ni libro, ni sidecars;
   - el proceso principal espera con el deadline. Vencido, **`SIGKILL` al
     trabajador** y lo respawnea. Matar cubre DNS, TLS y cuerpo por igual,
     porque no depende de que la operación colgada sea cancelable;
   - matarlo es seguro precisamente porque no tiene estado: la página se
     descarta entera —que es lo que §10 ya exige de cualquier página
     inválida— y el intento cuenta para el backoff;
   - es UNO solo, no uno por petición: el ciclo es de un hilo y nunca hay dos
     peticiones en vuelo, así que el costo de arranque se amortiza y el
     razonamiento sigue siendo de un solo trabajador a la vez.

   `CONNECT_TIMEOUT` y `READ_TIMEOUT` siguen configurados en el trabajador
   porque detectan antes el caso común y evitan el `SIGKILL`, pero la cota
   que vale es el deadline del padre.

#### 20.4.1 Protocolo del trabajador, congelado *(rev.25)*

«Devuelve el cuerpo por una tubería» dejaba abiertas seis decisiones, y cada
una admite dos implementaciones honestas con resultados distintos.

**Identificadores.** `generation_id` se incrementa en cada respawn;
`request_id` se incrementa en cada petición. Todo mensaje lleva los dos.

**Sobres CERRADOS**, con el mismo enmarcado durable de §5
—`<longitud>\t<sha256>\t<payload>\n`— para que un sobre a medio escribir sea
detectable y no un JSON plausible:

| pedido | respuesta |
|---|---|
| `generation_id`, `request_id`, `url`, `params`, `connect_timeout`, `read_timeout` | `generation_id`, `request_id`, `ok`, `status`, `retry_after`, y `body` **o** `error` |

`status` y `Retry-After` viajan en el sobre como campos propios: el cuerpo
solo no permite distinguir un `429` de un `200`, y §20.4 decide el backoff con
los dos.

**El deadline arranca ANTES del primer byte del pedido** *(rev.26)*. rev.25 lo
hacía arrancar cuando el padre TERMINABA de escribir, y eso no es cota total:
escribir en una tubería bloquea cuando el buffer del kernel se llena, así que
el padre podía quedarse detenido antes de que el reloj empezara a correr.
`REQUEST_DEADLINE` cubre despacho **y** respuesta, desde el instante anterior
al primer `write` hasta el último byte de la trama de respuesta.

**`MAX_SOBRE` = 4 MiB**, en §15. Una página de `LIMITE_PAGINA` velas ronda las
centenas de kilobytes, así que es techo de protocolo y no expectativa de
datos: un sobre que lo supere es fallo cerrado antes de reservar memoria por
lo que diga un campo de longitud que ya no es confiable.

**El I/O es INCREMENTAL y NO BLOQUEANTE en los dos sentidos** *(rev.27)*. Sin
esto había un abrazo mortal real: una respuesta de Binance supera holgadamente
el buffer de la tubería, así que el trabajador se bloquea escribiendo mientras
el padre espera sin drenar, y los dos quedan detenidos hasta que el deadline
mata una respuesta **válida** — un fallo inventado por el transporte, no por la
red.

`poll` solo no alcanza: un descriptor marcado escribible garantiza que acepta
**al menos un byte**, no el bloque entero, así que un `write` bloqueante mayor
al espacio libre detiene al padre DENTRO de la syscall y el deadline deja de
gobernar. Se congela:

- los cuatro descriptores en **`O_NONBLOCK`**;
- **escrituras y lecturas PARCIALES** en bucle, avanzando por lo que la syscall
  efectivamente movió, nunca asumiendo que movió todo;
- **`EAGAIN`/`EWOULDBLOCK`** vuelven al `poll` con el timeout recalculado como
  `deadline − monotonic()`; **`EINTR`** reintenta la syscall sin consumir nada
  ni alterar el deadline — una señal no es un fallo de transporte;
- el `poll` nunca se llama con timeout infinito: siempre el remanente del
  deadline, y un remanente ≤ 0 es vencimiento.

**Aceptación por el borde** *(rev.27, precisado)*: `monotonic()` se muestrea
**después de recibir la trama COMPLETA**, y se acepta si `fin ≤ deadline`. Es
la única lectura que no depende de en qué punto del bucle se miró el reloj:
muestrear antes del último `read` haría que una trama completa pareciera
tardía, y muestrear al entrar al `poll`, lo contrario.

**Qué falla cerrado con `codigo: 1`** *(rev.26)*, sin consumir intento ni
entrar al backoff:

| condición | por qué no es de red |
|---|---|
| EOF con la trama a medias | el trabajador murió sin que el padre lo matara |
| checksum del enmarcado que no cuadra | el canal corrompió bytes |
| sobre que no valida contra su schema | el trabajador habla otro protocolo |
| longitud declarada > `MAX_SOBRE` | idem, y además no se reserva la memoria |
| `(generation_id, request_id)` ajeno | ver arriba |
| muerte del trabajador en CUALQUIER tramo sin que el padre lo matara | falla del observador, no del exchange |

Dicho de otro modo, y sin contradecir §20.4: **en la capa IPC** el único
resultado reintentable es el deadline vencido; un sobre BIEN FORMADO que trae
un `error` de la tabla de §20.4 también lo es, porque ahí el IPC funcionó y lo
que falló fue la red. Corrupción del canal y muerte espontánea no son ninguno
de los dos: son el observador roto.

**Correlación estricta, y un ID ajeno es FALLO CERRADO** *(rev.26)*. El padre
acepta una respuesta solo si `(generation_id, request_id)` coincide con la
petición pendiente. Cualquier otra combinación **falla cerrado con
`codigo: 1`**, no se descarta.

rev.25 decía «se descarta», y eso era un fail-open disfrazado: con **una sola
petición en vuelo** y **un canal nuevo por generación**, un ID que no coincide
es IMPOSIBLE en operación válida. Solo puede venir de un protocolo corrupto —un
trabajador que responde dos veces, un sobre mal serializado, un descriptor
reusado por error—. Descartarlo lo convertía en un tiempo de espera que
terminaba venciendo el deadline, y el deadline es un fallo de transporte
REINTENTABLE: una corrupción del observador se habría reintentado cinco veces y
seguido como si nada.

**Un canal NUEVO por generación**, en este orden exacto:

```
SIGKILL → waitpid → cerrar los DOS extremos del canal viejo
        → crear tuberías nuevas → respawn con generation_id + 1
```

**Clausura COMÚN a toda salida** *(rev.28)*. rev.27 solo definía
`SIGKILL → waitpid` al vencer el deadline. Por cualquier otra vía —salida
ordenada, `SIGTERM`, corrupción del IPC, fallo cerrado, o el propio wrapper
terminando— el padre podía irse dejando al trabajador vivo, y en macOS no hay
ninguna garantía de que un hijo muera con su padre: quedaban trabajadores
huérfanos hablando con el exchange sin nadie que los leyera. La misma secuencia
corre en TODA salida, sin excepción:

```
cerrar el extremo de ESCRITURA del pedido      (el trabajador ve EOF)
esperar CIERRE_COOPERATIVO = 2 s a que salga solo
si sigue vivo → SIGKILL
waitpid  (siempre, o queda zombi)
cerrar los descriptores restantes
```

El EOF primero para que el caso normal sea una salida limpia del trabajador y
no un `SIGKILL`; los 2 s porque no tiene nada durable que cerrar —no escribe
almacenes, libro ni sidecars (§20.4)—, así que un plazo largo solo retrasaría
la salida del padre y comería el `ExitTimeOut` de §20.6; y el `waitpid`
siempre, incluso tras el `SIGKILL`, porque si no el zombi sobrevive al padre.

`CIERRE_COOPERATIVO` se agrega a §15.

Cerrar los descriptores viejos ANTES de crear los nuevos es lo que hace
imposible leer bytes residuales tras el respawn: los bytes que el trabajador
muerto alcanzó a escribir viven en un buffer de kernel que se destruye con el
canal. Reusar la tubería habría dejado media respuesta de la generación
anterior esperando al principio del flujo.

**Muerte del trabajador: dos casos, y NO son lo mismo.**

| qué pasó | cómo se clasifica |
|---|---|
| el padre lo mató por deadline vencido | fallo de TRANSPORTE: consume un intento y entra al backoff (§20.4) |
| murió solo —crash, OOM, sobre truncado sin que el padre matara— | **fallo cerrado**, `codigo: 1` |

Un trabajador que muere por su cuenta no es una falla de red: es una falla del
observador. Tratarla como transitoria la haría reintentar cinco veces y seguir
como si nada, cuando lo que corresponde es que un humano mire por qué el
proceso que habla con el exchange se cae solo.

   El **sueño del backoff es interruptible**: se espera sobre un evento que el
   manejador de señal levanta, no con un `sleep` ciego. Sin eso, un `SIGTERM`
   durante la última espera podía costar `BACKOFF_MAX` completo.

3. **`ExitTimeOut` supera las DOS cotas** *(rev.22)*, no solo la medición:

   | cota | de dónde sale |
   |---|---|
   | analítica | peor tramo no interrumpible = una petición en vuelo acotada por `REQUEST_DEADLINE` (30 s), más el sellado del stream en curso y el lote más largo de la fase posterior |
   | empírica | peor tiempo MEDIDO a escala completa entre dos puntos de cancelación |

   `EXIT_TIMEOUT = 3 × max(analítica, empírica)`. La analítica sola no basta
   —no cubre un disco lento— y la empírica sola tampoco: una medición hecha
   con la red sana nunca observa los 25 s de un timeout. El gate 48 comprueba
   las dos y falla si el plist quedó por debajo. Un número escrito a mano en
   el plist envejece en silencio; uno derivado de un gate no.

   Nótese que la cota NO es `timeout × 5 intentos + 4 backoffs`: con la
   comprobación de señal entre intentos, la salida no espera a que el `fetch`
   agote su serie.

#### 20.6.1 Taxonomía CERRADA de salidas

| código | qué significa | ejemplos |
|---|---|---|
| `0` | terminal publicado; apagado ordenado; **o el lock ya lo tiene otra instancia** | `completed.json`/`blocked.json` al arrancar; `SIGTERM`; `singleton_lock` ocupado |
| `2` | error transitorio ACOTADO del host | `EBUSY`, `EAGAIN`, `ETIMEDOUT` del sistema de archivos |
| `1` | **todo lo demás**, incluida cualquier excepción no prevista | `ENOSPC`, `EIO`, `MarcoCorrupto`, `VerificacionInvalida`, `RequestInvalido`, `PaginaInvalida`, árbol sucio, commit distinto del acta, estado ausente |

Tres correcciones sobre rev.19 *(rev.20)*:

- **el lock ocupado sale `0`**, no `2`. Significa que hay otra instancia SANA
  corriendo; este proceso no tiene nada que hacer y reintentar en loop es
  ruido contra un sistema que funciona;
- **`ENOSPC` y `EIO` bajan a `1`**. No son transitorios: un disco lleno o un
  error de E/S del medio exigen intervención, y reintentarlos indefinidamente
  contradice el fail-closed declarado — la cohorte parecería viva mientras no
  puede escribir nada;
- **`2` está ACOTADO**. `fallo_cerrado.json` lleva un contador de salidas `2`
  consecutivas; a los `MAX_TRANSITORIOS` (5) el arranque siguiente escala a
  `1` y deja de reintentar. Un `EBUSY` que no se despeja en cinco intentos ya
  no es transitorio, sea lo que sea.

El registro de `2` es **cerrado, corto y con cota**; el de `1` es el default.
Fallar abierto acá significaría reintentar para siempre una condición que solo
un humano puede resolver.

#### 20.6.2 Por qué el plist solo no alcanza

`KeepAlive.SuccessfulExit = false` reinicia ante **cualquier** salida no cero.
`1` y `2` son indistinguibles para launchd, y `ThrottleInterval` solo limita la
frecuencia del loop, no lo evita. La política de rev.18 no era realizable.

El daemon sigue emitiendo `0/1/2` —es la taxonomía que un operador lee— y un
**wrapper** traduce.

**Quién escribe el diagnóstico** *(rev.20)*. rev.19 le pedía al wrapper
registrar «la excepción», pero un proceso padre solo recibe el ESTADO DE
SALIDA: no tiene el traceback ni el motivo. El canal se invierte:

| quién | qué escribe |
|---|---|
| el DAEMON, antes de salir `1` o `2` | `fallo_cerrado.json` completo: motivo, clase de excepción, traceback, código, instante e identidad |
| el WRAPPER | nada, si el daemon ya lo dejó válido |

| salida del daemon | qué hace el wrapper | efecto en launchd |
|---|---|---|
| `0` | sale `0` | no reinicia |
| `1` con `fallo_cerrado.json` válido | sale `0` | no reinicia |
| `1` SIN diagnóstico válido | escribe uno con `motivo: "sin_diagnostico"`, el código crudo y la cola de `stderr`, y sale `0` | no reinicia |
| `1` y NO puede escribirlo | sale distinto de `0` | reinicia — el loop ES el síntoma visible |
| `2` | sale distinto de `0` | reinicia tras `ThrottleInterval`, hasta la cota de §20.6.1 |

La tercera fila cubre el caso que rev.19 perdía: un daemon muerto por `SIGKILL`
o por un fallo antes de poder escribir. Traducir `1→0` ahí, sin diagnóstico,
habría hecho creer a launchd —y a un operador— que la cohorte terminó
limpiamente. El wrapper **solo traduce si el diagnóstico existe y valida**.

Los dos fallos del propio wrapper son distintos y rev.21 los confundía en una
sola fila que además era imposible —pedía un documento `motivo: wrapper` en el
caso en que la escritura falló—:

- **error interno con la escritura todavía disponible** —un bug suyo, un
  estado que no supo clasificar—: escribe `motivo: wrapper`, `codigo: 1`, y
  sale `0`. Bloquea el arranque siguiente, que es lo correcto: un bug del
  wrapper no se arregla reintentando;
- **imposibilidad de escribir** —disco lleno, permiso roto, directorio que no
  existe—: **no hay documento**, porque no puede haberlo. Sale distinto de `0`
  y launchd reinicia. Es el único caso en que el loop se acepta: el reinicio
  repetido es la señal más ruidosa disponible, y mejor que un silencio que
  parece éxito.

`stderr` del daemon se redirige a `diagnostico.err` por el plist
(`StandardErrorPath`), que es de dónde sale esa cola.

#### 20.6.4 El arranque distingue por CÓDIGO, no por presencia *(rev.21)*

rev.20 rechazaba el arranque ante **cualquier** `fallo_cerrado.json`, y el
daemon escribía uno también antes de salir `2`. La secuencia real era:

```
EBUSY → escribe codigo=2, transitorios=1 → el wrapper reinicia
      → el arranque ve el sidecar y sale 1
```

Nunca se llegaba al segundo intento, así que `MAX_TRANSITORIOS` era inoperante
y la cota que rev.20 introdujo no existía. Presencia y bloqueo no son lo
mismo:

| qué encuentra el arranque | qué hace |
|---|---|
| nada | arranca normal, serie transitoria en cero |
| `codigo = 1` | **BLOQUEA**: sale `1` sin cargar estado. Solo un humano lo saca |
| `codigo = 2` válido y de ESTA cohorte | **CONTINÚA**, reanudando la serie con `transitorios` como valor de partida |
| `codigo = 2` con `transitorios ≥ MAX_TRANSITORIOS` | lo reescribe como `transitorios_agotados` / `codigo = 1` y sale `1` |
| de otra cohorte, corrupto o inválido | fallo cerrado (§20.6.3) |

**Quién mueve el contador**, congelado:

- **el DAEMON, al salir `2`**: lee el diagnóstico vigente —si es `codigo = 2` y
  de esta cohorte— y escribe `transitorios + 1`. Si ese valor alcanza
  `MAX_TRANSITORIOS`, escribe `transitorios_agotados` con `codigo = 1` y sale
  `1` en vez de `2`: un `EBUSY` que no se despeja en cinco intentos ya no es
  transitorio;
- **el ARRANQUE completo lo ARCHIVA**: al terminar el paso 10 —con el replay
  hecho, `reanudar()` corrido y el bucle por abrir— el diagnóstico transitorio
  se archiva y la serie vuelve a cero. Archivar y no borrar, por lo mismo que
  §20.0: el rastro de cinco reintentos seguidos es dato operacional, no
  basura.

  **La ruta de archivo es ÚNICA y append-only** *(rev.22)*: renombrar siempre
  al mismo `fallo_cerrado.json.archivado` hacía que una segunda serie
  transitoria pisara la primera — archivar y perder la historia a la vez. Va a
  `diagnosticos/fallo_cerrado.<ocurrido_en>.<sha8 del checksum>.json`.

  **Primitiva CONGELADA** *(rev.23)*. rev.22 decía «renombrar creado con
  `O_EXCL`», que no es una operación realizable: `os.rename`/`os.replace`
  sobrescriben en silencio y no admiten esa bandera, y crear el destino antes
  con `O_EXCL` solo consigue que el rename lo pise igual. Se usa **enlace duro
  exclusivo**:

  ```
  os.link(origen, destino)      # EEXIST si el destino ya existe → fallo cerrado
  fsync del directorio diagnosticos/
  os.unlink(origen)
  fsync del directorio de estado
  ```

  `link` es atómico y falla si el destino existe, que es exactamente la
  exclusión que hacía falta. `renameatx_np(..., RENAME_EXCL)` de macOS haría lo
  mismo, pero exige `ctypes` y no existe en Linux: se elige el camino portable
  para que no haya dos implementaciones honestas distintas.

  **Caída entre `link` y `unlink`**: quedan las dos rutas apuntando al MISMO
  archivo. El arranque siguiente lo detecta comparando **`(st_dev, st_ino)`**
  *(rev.24)* —el inodo solo no identifica un archivo: el mismo número existe en
  cada filesystem montado—, y si coinciden completa el `unlink` del origen: no
  es ambigüedad, es la mitad de una operación cuya otra mitad ya es durable.
  Si difieren, son dos documentos distintos con el mismo nombre de destino:
  fallo cerrado.

  `diagnosticos/` vive **en el mismo filesystem** que el estado, porque `link`
  no cruza montajes. Un `EXDEV` es fallo cerrado y no se degrada a copiar y
  borrar: esa degradación pierde la exclusión atómica, que es lo único por lo
  que se eligió `link`.

El punto de éxito es el ARRANQUE COMPLETO, no el primer ciclo: los transitorios
que `2` cubre son de arranque —lock, sistema de archivos—, y esperar al primer
ciclo mezclaría la serie con fallas de red, que no salen por acá.

#### 20.6.5 La acreditación humana es una operación registral *(rev.26)*

§20.6.4 define el archivado AUTOMÁTICO del diagnóstico transitorio tras un
arranque exitoso. Un diagnóstico `codigo: 1` no tiene esa salida —bloquea, y
solo un humano lo levanta—, pero rev.25 decía «acreditar y archivar» sin
herramienta, campos ni procedimiento. Una operación normativa que nadie puede
ejecutar no es una operación.

Existe una **herramienta de acreditación**, separada del daemon y del wrapper.
Son DOS artefactos y varias operaciones, así que es una máquina IDEMPOTENTE
bajo lock, no una pasada lineal *(rev.27)*:

**Se invoca contra un `checksum` ESPERADO, obligatorio** *(rev.28)*. rev.27
hacía que el segundo operador comprobara que su acto fuera idéntico al primero,
pero tras el primero ya no hay `fallo_cerrado.json`: el segundo caía en
«no-op» y nunca llegaba a comparar. El acto que se acredita se nombra en la
invocación, y por eso se puede resolver esté el diagnóstico o no:

```
0. tomar acreditacion.lock                    (flock exclusivo, §7)
1. resolver el caso contra el `checksum` esperado que trae la invocación
2. exigir `operador` y `motivo_humano` no vacíos
3. publicar la acreditación                   (durable, §20.6.5.1)
4. archivar el diagnóstico: link → fsync → unlink → fsync       (§20.6.4)
```

| qué hay en disco | qué se hace |
|---|---|
| diagnóstico activo cuyo `checksum` COINCIDE | se continúa por los pasos 2–4 |
| diagnóstico ausente y acreditación archivada IDÉNTICA | **éxito idempotente**: el acto ya ocurrió, no se repite nada |
| diagnóstico ausente y acreditación archivada con OTRO `operador` o `motivo_humano` | **conflicto**: otro humano ya decidió sobre este diagnóstico. No se sobrescribe |
| diagnóstico o acreditación con un `checksum` DISTINTO del esperado | **fallo cerrado**: se está acreditando otra cosa que la que el operador miró |
| nada de lo anterior | fallo cerrado: no hay nada que acreditar con ese checksum |

Exigir el checksum en la invocación es además lo que hace que la acreditación
sea de un documento **leído**: sin él, acreditar sería «lo que haya ahí», y el
diagnóstico pudo haber cambiado entre que el operador lo miró y que corrió la
herramienta.

**Recuperación en cada frontera**:

| dónde cayó | qué hace el reintento |
|---|---|
| antes del paso 3 | nada quedó escrito: se empieza de nuevo |
| durante el paso 3 | la fuente temporal queda huérfana y se descarta; el `link` no llegó a ocurrir |
| después de 3, antes de 4 | la acreditación ya está: idéntica continúa por el paso 4, distinta es conflicto |
| entre `link` y `unlink` del paso 4 | las dos rutas comparten `(st_dev, st_ino)`: se completa el `unlink` (§20.6.4) |

**Dos operadores a la vez** los serializa `acreditacion.lock`, y ahora el
segundo SÍ puede resolverse: entra con su checksum esperado, encuentra el
diagnóstico ya archivado, y la tabla decide entre éxito idempotente y
conflicto. Sin el lock, los dos podían escribir su acreditación y quedarse cada
uno con la mitad de la operación del otro.

Recién con el diagnóstico archivado, el arranque siguiente deja de estar
bloqueado.

##### 20.6.5.1 El registro de acreditación es un sidecar registral *(rev.28)*

Mismo tratamiento que los demás; rev.26 lo introdujo sin schema propio:

| campo | qué es |
|---|---|
| `schema_version` | cerrada y versionada |
| `cohorte`, `contrato`, `commit` | identidad, igual que el diagnóstico |
| `diagnostico_checksum` | el documento acreditado, citado por su checksum |
| `acreditado_por` | operador, no vacío |
| `motivo_humano` | por qué se decidió continuar, no vacío |
| `acreditado_en` | instante entero |
| `checksum` | del propio registro |

**Publicación durable**, con la fuente temporal declarada —`link` necesita un
origen, y rev.27 no decía de dónde salía—:

```
escribir diagnosticos/acreditacion.<sha8>.json.tmp   (atómico) → fsync del archivo
link(tmp, diagnosticos/acreditacion.<sha8>.json)     EEXIST → comparar contenido
fsync del directorio
unlink(tmp) → fsync del directorio
```

El `.tmp` vive en `diagnosticos/` porque `link` no cruza filesystems (§20.6.4),
y un `.tmp` huérfano de una caída se descarta: no es la acreditación, que es
solo el nombre definitivo.

**El arranque comprueba ausencia, no acreditación**: si hay un
`fallo_cerrado.json` con `codigo: 1` en el directorio de estado, bloquea. La
acreditación lo saca de ahí, no lo marca. Un campo `acreditado: true` sobre el
mismo archivo habría hecho que el bloqueo dependiera de leer bien un booleano
en un documento que justamente se está leyendo porque algo salió mal.

La acreditación **no** re-ejecuta nada, no toca almacenes ni libro, y no puede
levantar un terminal publicado: eso es §20.0 y exige identidad nueva.

#### 20.6.3 `fallo_cerrado.json` es un sidecar registral *(rev.20)*

Gobierna el arranque, así que recibe el MISMO tratamiento que los demás
sidecars —rev.19 lo introdujo sin ninguno—:

| campo | qué es |
|---|---|
| `schema_version` | cerrada y versionada |
| `cohorte`, `contrato`, `commit` | identidad, igual que `terminal.request` |
| `motivo` | registro CERRADO: `excepcion`, `transitorios_agotados`, `senal`, `sin_diagnostico`, `wrapper` |
| `excepcion` | clase y mensaje; solo con `motivo: excepcion` o `transitorios_agotados` |
| `traceback` | texto, para el operador; no participa de ninguna decisión |
| `codigo` | **clasificado**: `1` o `2`, siempre. No es el estado crudo |
| `estado_crudo` | lo que el wrapper observó, tal cual; solo cuando lo escribe él |
| `senal` | número de señal, entero; presente solo con `motivo: senal` |
| `ocurrido_en` | instante entero |
| `transitorios` | contador de salidas `2` consecutivas (§20.6.1, §20.6.4) |
| `checksum` | del propio documento |

**`codigo` es CLASIFICADO, no crudo** *(rev.21)*. rev.20 hacía que el wrapper
registrara «el código crudo» de un daemon muerto por señal, pero un proceso
terminado por señal no devuelve `1`: el shell entrega `128 + N` —`137` para
`SIGKILL`— y el schema solo admite `1` o `2`. El documento que el wrapper
intentaba crear era inválido contra su propio schema.

Tabla de clasificación, congelada:

| lo que observa el wrapper | `motivo` | `codigo` | otros campos |
|---|---|---|---|
| salida `0` | — | — | no escribe nada |
| salida `1` con diagnóstico válido del daemon | el del daemon | `1` | — |
| salida `1` sin diagnóstico válido | `sin_diagnostico` | `1` | `estado_crudo: 1` |
| salida `2` con diagnóstico válido | el del daemon | `2` | — |
| salida `2` sin diagnóstico válido | `sin_diagnostico` | `2` | `estado_crudo: 2` |
| terminado por SEÑAL | `senal` | `1` | `senal: N`, `estado_crudo` |
| cualquier otra salida | `sin_diagnostico` | `1` | `estado_crudo: <el valor>` |
| error INTERNO del wrapper, todavía pudiendo escribir | `wrapper` | `1` | documento válido; sale `0` |
| **no puede escribir** el diagnóstico | — | — | ningún documento; sale ≠ 0 |

Muerte por señal clasifica `1` —bloquea— y no `2`: un `SIGKILL` es el
`ExitTimeOut` vencido o un OOM, y reintentarlo en loop repetiría la misma
muerte. El apagado ordenado por `SIGTERM` **no** cae acá: el daemon lo atiende
y sale `0` por su cuenta (§20.6).

El wrapper lee el **estado de espera del proceso**, no la convención del
shell: con `128 + N` no se distingue un `SIGKILL` de un daemon que salió `137`
por su cuenta. Es un proceso Python que llama `subprocess`/`os.waitpid` y
clasifica por `WIFSIGNALED` —`returncode < 0` en la convención de Python—,
nunca un script de shell leyendo `$?`.

Escritura ATÓMICA (`escribir_atomico`), validación fail-closed al leerlo, y
**identidad exigida**: un `fallo_cerrado.json` de otra cohorte no bloquea a
esta —bloquearía a la equivocada— pero tampoco se ignora en silencio: es fallo
cerrado, porque un archivo de otra identidad en este directorio significa que
algo mezcló dos estados.

Se agrega a la lista de §15 junto con `MAX_TRANSITORIOS` y `ExitTimeOut`.

### 20.7 Lo que el servicio NO hace

- no escribe en el repositorio, ni siquiera logs: el árbol tiene que quedar
  limpio para que §20.1 siga siendo comprobable en el arranque siguiente;
- no toca Bot, Testnet, Live ni Railway;
- no reabre una cohorte cerrada, ni borra marcadores terminales;
- no crea `verificacion.json` ni `acta.json` si faltan — falla cerrado;
- no elige ningún parámetro de §15 en operación.

### 20.8 Gates de aceptación de §20 *(rev.19)*

Numerados a continuación de §17, que termina en 44:

45. **primer nacimiento completo**: la herramienta corre sobre un directorio
    VACÍO y produce acta, los 14 almacenes, libro, manifiesto y
    `verificacion.json` en `ok` **con el digest y la firma de una comparación
    fría real entre dos motores RECONSTRUIDOS** —no dos vacíos que coinciden
    por estar ambos en cero, y no fabricado—; todo aparece por UN SOLO rename
    desde `cohorte.new/`; correrla de nuevo sobre el estado publicado falla
    cerrado sin tocar nada; una caída simulada en CADA etapa deja solo
    `cohorte.new/` y el reintento la borra y completa; DOS activaciones
    concurrentes se serializan por `activacion.lock` y la segunda falla cerrado
    sin tocar el staging de la primera *(rev.21)*; el rename cumple la
    secuencia de `fsync` de §4, padre incluido; y el servicio arranca contra
    ese estado sin fallar;
45bis. **replay del arranque** *(rev.20)*: con posiciones vivas, órdenes y
    `lotes_finalizados` en el prefijo sellado, un reinicio los RECONSTRUYE
    —`watermark_lotes()` idéntico, `cierres` idénticos, estados por mercado
    idénticos— sin appendear ningún evento nuevo al libro y sin ingerir; un
    prefijo alterado hace fallar el arranque por «payload distinto»; y un
    reinicio con `terminal.request` pendiente y ganador `muestra` publica el
    MISMO terminal que la corrida continua, que contra un motor vacío era
    imposible;
45ter. **archivo, no borrado** *(rev.20)*: cerrar una cohorte y reactivar deja
    la anterior íntegra en `cohortes/<id>/` —libro, almacenes y marcador— y
    exige una `cohorte` NUEVA: reusar el identificador falla cerrado;
46. **orden del arranque**: sin lock no se carga nada; sin `acta.json`,
    `verificacion.json` o manifiesto se falla cerrado; `reanudar()` corre ANTES
    del primer ciclo —gate con un `terminal.request` pendiente, comprobando que
    ningún almacén se movió—; y un terminal publicado sale `0` sin abrir
    ninguno;
47. **taxonomía de salidas**: una excepción de cada familia produce el código
    que le corresponde; una excepción DESCONOCIDA produce `1`, no `2`;
    `ENOSPC` y `EIO` producen `1` y el lock ocupado produce `0`; y `2`
    ESCALA a `1` al llegar a `MAX_TRANSITORIOS` consecutivos;
47ter. **la serie transitoria es alcanzable** *(rev.21)*: `MAX_TRANSITORIOS`
    fallos `EBUSY` seguidos llegan efectivamente al quinto —un diagnóstico con
    `codigo = 2` NO bloquea el arranque—, el contador avanza uno por intento,
    el quinto publica `transitorios_agotados` con `codigo = 1` y ahí sí
    bloquea; y un arranque COMPLETO intermedio archiva el diagnóstico y
    reinicia la serie en cero;
47quater. **clasificación de la salida** *(rev.21)*: cada fila de la tabla de
    §20.6.3, incluida la muerte por `SIGKILL` —que produce `motivo: senal`,
    `codigo: 1` y `senal: 9`, NO `codigo: 137`—, una salida arbitraria como
    `42` que cae en `sin_diagnostico` con su `estado_crudo`, y el error INTERNO
    del wrapper. Todos esos documentos VALIDAN contra el schema. La fila
    «no puede escribir» se ejerce por separado —directorio sin permiso— y se
    exige lo contrario: NINGÚN documento y salida ≠ 0 *(rev.22)*;
47quinquies. **el archivado no pisa historia** *(rev.22)*: dos series
    transitorias seguidas dejan DOS archivos en `diagnosticos/`, ninguno
    sobrescrito; una colisión de nombre forzada falla cerrado por `EEXIST` del
    `link`, no por una comprobación previa que otro proceso podría ganar; el
    directorio recibe `fsync`; y una caída simulada ENTRE `link` y `unlink`
    deja las dos rutas sobre el mismo inodo, que el arranque siguiente
    completa —y falla cerrado si los inodos difieren— *(rev.23)*;
47bis. **el canal de diagnóstico** *(rev.20)*: el daemon escribe
    `fallo_cerrado.json` ANTES de salir; el wrapper traduce `1→0` solo si
    valida; un daemon muerto por `SIGKILL` sin diagnóstico hace que el wrapper
    escriba `motivo: sin_diagnostico` con la cola de `stderr` y salga `0`; un
    wrapper que NO puede escribirlo sale distinto de `0`; con
    `fallo_cerrado.json` presente el arranque siguiente sale `1` sin cargar
    estado; y uno de OTRA cohorte falla cerrado en vez de bloquear o de
    ignorarse. Vectores adversariales sobre cada campo del schema, como los de
    §13.4.2;
48. **SIGTERM en cada frontera**: durante el REPLAY, durante un ciclo, durante
    la copia, durante la comparación fría y entre publicar y borrar. En los
    cinco: el proceso sale `0`, el estado en disco es consistente, y el
    arranque siguiente continúa sin pérdida — en particular, la señal durante
    la copia NO deja el sidecar en `pending` y la señal durante la comparación
    SÍ lo deja, con la copia completa. Se agrega la señal **dentro de una
    petición HTTP colgada** y **durante el sueño del backoff**: en las dos, el
    proceso sale sin esperar a que el `fetch` agote su serie de intentos
    *(rev.22)*. Se agrega un servidor que entrega **bytes periódicamente sin
    terminar nunca** —el caso que `READ_TIMEOUT` no detecta—: la petición se
    corta por `REQUEST_DEADLINE` y el proceso sale dentro de la cota
    *(rev.23)*. Y una **resolución DNS bloqueada** —el caso que ningún timeout
    de socket alcanza, porque el socket no existe todavía—: el trabajador
    recibe `SIGKILL`, se respawnea, el intento cuenta para el backoff y el
    proceso sale dentro de la cota *(rev.24)*. Y con **miles de lotes pendientes** en la fase posterior, la
    señal aborta entre dos lotes finalizados, no al final del backlog; los
    cinco unidades indivisibles se respetan; y el reinicio reconstruye por
    replay exactamente hasta donde se llegó *(rev.23)*. Se agrega la señal
    **entre fase A y fase B**: el proceso sale `0` con el `terminal.request` en
    disco, y el arranque siguiente publica el MISMO terminal que la corrida
    continua —que es el gate 40quinquies, ejercido ahora desde un apagado
    ordenado y no solo desde una caída *(rev.24)*;
48bis. **la evidencia de silencio sobrevive a un `SIGKILL`** *(rev.24,
    reconciliado en rev.25)*. Con observaciones acumuladas y la señal aplicada
    DESPUÉS de la unidad de silencio pero ANTES del primer lote, se exige, en
    este orden:

    1. **recuperación de ALMACENAMIENTO**, comprobada fuera del wrapper:
       `silencio.json` en disco contiene el acumulado, no se perdió ni
       retrocedió, y valida contra su schema;
    2. **la clasificación NO se debilita**: el wrapper escribe
       `motivo: senal`, `codigo: 1`, y el arranque siguiente **BLOQUEA**. El
       gate lo exige explícitamente — rev.24 prometía que «el arranque
       siguiente continúa», que contradecía §20.6.3 y habría obligado a tratar
       un `SIGKILL` como transitorio;
    3. **reanudación por INTERVENCIÓN HUMANA**, por la operación registral de
       §20.6.5: la herramienta rechaza un diagnóstico que no valida, rechaza
       un `motivo_humano` vacío, deja el registro de acreditación citando el
       `checksum` del diagnóstico, y lo archiva con el enlace exclusivo. Recién
       ahí el arranque continúa la serie de 72 h desde el sidecar en vez de
       reiniciarla.

    La propiedad que se prueba es la durabilidad del artefacto, no un reinicio
    operativo automático: una muerte por señal sigue exigiendo que un humano
    mire antes de seguir; Además **MIDE**, a escala
    completa, el peor tiempo entre dos puntos de cancelación, calcula la cota
    analítica desde `REQUEST_DEADLINE` más el sellado y el lote más largo, y
    **falla si el `ExitTimeOut` del plist es menor a 3 × el mayor de los dos**
    (§20.6);
48octies. **ningún trabajador huérfano** *(rev.28)*: tras salida ordenada,
    `SIGTERM`, corrupción del IPC, fallo cerrado y muerte del wrapper, no queda
    NINGÚN proceso trabajador vivo ni zombi —se comprueba por PID, no por
    ausencia de log—; el caso normal sale por EOF sin llegar al `SIGKILL`; un
    trabajador que ignora el EOF recibe `SIGKILL` tras `CIERRE_COOPERATIVO`; y
    en todos los casos hay `waitpid`;
48sexies. **enum de errores y política de reintento** *(rev.27)*: cada valor
    de la tabla de §20.4 produce lo que declara —`dns`, `conexion`, `tls`,
    `lectura`, `http_429`, `http_5xx` consumen intento; `http_4xx`, `interno` y
    cualquier valor DESCONOCIDO fallan cerrado con `codigo: 1`—; y un `429` con
    `Retry-After` lo respeta acotado, mientras un `4xx` no reintenta ni una
    vez;
48septies. **el I/O no bloquea al padre** *(rev.27)*: con el buffer de la
    tubería lleno, un `write` del padre NO lo detiene dentro de la syscall —los
    descriptores son `O_NONBLOCK` y el bucle avanza por lo efectivamente
    movido—; `EAGAIN` vuelve al `poll` con el remanente del deadline y `EINTR`
    reintenta sin consumir nada; ningún `poll` se llama con timeout infinito; y
    el veredicto del borde se resuelve con `monotonic()` muestreado DESPUÉS de
    la trama completa;
48ter. **protocolo del trabajador** *(rev.25, ampliado en rev.26)*: cada fila
    de la tabla de fallo cerrado de §20.4.1 produce `codigo: 1` y **NO**
    consume intento —`request_id` ajeno, `generation_id` ajeno, sobre
    truncado, checksum roto, schema inválido, longitud sobre `MAX_SOBRE`, y
    muerte espontánea del trabajador—; entre los fallos de la CAPA IPC, solo
    el deadline vencido consume intento y entra al backoff *(rev.28: decía
    «solo el deadline», que contradecía los seis errores de red de 48sexies —
    esos viajan en un sobre bien formado y no son fallos del IPC)*; tras un respawn no se lee ni un byte de la
    generación anterior, con el trabajador escribiendo una respuesta parcial
    justo antes de morir; y `status` y `Retry-After` llegan como campos del
    sobre, no inferidos del cuerpo;
48quater. **el IPC no se abraza ni se escapa** *(rev.26)*: una respuesta MUY
    superior al buffer de la tubería se transfiere completa —el padre drena
    incrementalmente mientras el trabajador escribe— y NO vence el deadline,
    que es el abrazo mortal que el diseño evita; el deadline se mide desde
    ANTES del primer byte del pedido, con un gate que bloquea la escritura del
    padre y comprueba que el reloj ya corría; una trama completa justo en el
    borde se ACEPTA y una incompleta al vencer no; y una longitud declarada
    por encima de `MAX_SOBRE` falla cerrado sin reservar la memoria;
48quinquies. **la acreditación humana** *(rev.26, ampliado en rev.27)*: un
    diagnóstico con checksum roto, de otra identidad, o con `motivo_humano`
    vacío NO se puede acreditar; una acreditación válida deja el registro
    citando el `checksum`, archiva con enlace exclusivo sin pisar historia
    previa, y recién entonces el arranque deja de bloquear; y la herramienta no
    puede levantar un terminal publicado. Además, **interrupción después de
    CADA escritura** —tras la acreditación y entre `link` y `unlink`—: el
    reintento completa sin duplicar y sin colisionar; y **dos procesos
    concurrentes** se serializan por `acreditacion.lock`, con el segundo
    entrando cuando el diagnóstico YA fue archivado y resolviéndose por su
    `checksum` esperado: éxito idempotente si su acto es idéntico, conflicto si
    el `operador` o el `motivo_humano` difieren, y fallo cerrado si el checksum
    no es el mismo *(rev.28: rev.27 exigía una comparación que el segundo
    operador no podía llegar a hacer)*. Más: invocar sin `checksum` esperado se
    rechaza; una caída DURANTE la publicación deja un `.tmp` huérfano que se
    descarta; y el registro de acreditación valida contra el schema de
    §20.6.5.1 con vectores adversariales por campo;
49. **cadencia y backoff deterministas**: un ciclo que dura más que `CADENCIA`
    no acumula deuda —el siguiente arranca una sola vez—; el backoff respeta
    la fórmula y el número de intentos con un reloj y un generador
    inyectados; `Retry-After` se respeta acotado a `BACKOFF_MAX` y consume
    intento; y una `PaginaInvalida` NO se reintenta;
50. **`verify.request` sin carrera**: con una solicitud manual presente, el
    ciclo no la pisa —mismo inodo y mismo `mtime`—; con `pending` o
    `divergent` no se escribe ninguna; y la cadencia se mide contra el campo
    que corresponde a cada estado del sidecar;
51. **árbol y commit**: árbol sucio, `HEAD` distinto del acta, y acta de otra
    cohorte: los tres fallan cerrado ANTES de tomar cualquier dato, y ninguno
    deja rastro en los almacenes.

---

## Fuera de alcance

Gráfico del Command Center: siguiente pendiente prioritario, después de
estabilizar el gate 7.
