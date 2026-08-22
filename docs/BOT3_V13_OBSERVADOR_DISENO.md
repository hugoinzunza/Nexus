# Bot3.v13 — Observador operativo · DISEÑO rev.12

**Estado: DISEÑO rev.12 — revisión de concurrencia de la transición,
propuesta para auditoría ANTES de seguir implementando. No desplegado. Cohorte
no iniciada.**
Contrato del motor: `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d` (congelado, no se toca).

rev.12 cierra la CONCURRENCIA de la transición: parte la barrera en fase de
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
 11. borrar terminal.request
 12. liberar la barrera y salir
```

**El orden dentro de la fase A importa** *(rev.11)*: rev.10 escribía el request
ANTES de tomar la barrera, y entre esos dos pasos otro ciclo podía empezar a
ingerir sobre una cohorte que ya estaba cerrándose.

#### 9.1.2 Qué cierra la ventana de recolección *(rev.12)*

La ventana existe para que la precedencia signifique algo: si se publicara con
la primera causa, ganaría la que llega antes.

**Se cierra cuando ningún productor puede aportar una causa de mayor
precedencia.** En la práctica hay un solo productor asíncrono —la comparación
fría—, porque el silencio y el corte los detecta el ciclo, que durante la
ventana no abre. Así que la condición es:

| estado de la verificación | ventana |
|---|---|
| `ok` o `divergent` | **cerrada**: ya aportó lo que tenía que aportar |
| `pending` o `deferred` | **abierta**: todavía puede producir `determinism_divergence` |

Una causa registrada con la comparación fría `pending` **espera** a que
resuelva. No es una demora arbitraria: es lo que hace cumplible
`determinism_divergence > silencio_h4`.

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
| `estado_esperado` | los 14 heads, firma del libro y hash de los sidecars |
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
  atender verify.request si lo hay, SIN readquirir la barrera (§9)
  cycle_barrier.release()
```

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

### 13.5 Matriz de reanudación *(rev.10)*

«Recargar y aplicar» admitía implementaciones distintas. Para un request cuyo
ganador es CIENTÍFICO, al reanudar se recarga `verificacion.json` desde disco
—el objeto en memoria se perdió con la caída— y se aplica esta matriz:

| estado del sidecar | qué se hace |
|---|---|
| `ok` y posterior a toda deferencia | se publica `COMPLETED` |
| `pending` | se MANTIENE el cierre en curso: ni ciclos ni publicación. La comparación fría se reanuda desde la copia (§13.5.1) |
| `deferred` con ganador CIENTÍFICO | **fallo cerrado**: estado inalcanzable (§13.5.0) |
| `deferred` con ganador de INTEGRIDAD | ventana abierta (§9.1.2); se espera a que la comparación resuelva |
| `divergent` | se ANEXA `determinism_divergence` con su evidencia al request y se publica `BLOCKED_INTEGRITY` |
| ausente, corrupto o de otra identidad | **fallo cerrado** |

Para un ganador de INTEGRIDAD la verificación no HABILITA nada —
`BLOCKED_INTEGRITY` no ejecuta cierre científico (§13.1)—, pero sí puede
RETENERLO: mientras la comparación fría siga `pending` o `deferred`, la
ventana está abierta (§9.1.2) y no se publica *(rev.12)*.

Sin esa retención, `silencio_h4` publicaba mientras la comparación corría, el
terminal quedaba inmutable y una divergencia posterior nunca ejercía su
precedencia — el orden `determinism_divergence > silencio_h4` era letra
muerta justo en el caso en que importa.

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
  de captura, que vive en el ciclo.

Por lo tanto `deferred` junto a un request cuyo ganador es científico es un
estado que la máquina no puede alcanzar. Observarlo significa que algo anterior
falló, y **falla cerrado** en vez de intentar resolverlo con una operación que
el diseño no contempla.

`deferred` con un ganador de INTEGRIDAD sí es alcanzable —la deferencia pudo
quedar de antes— y ahí rige §9.1.2: la ventana sigue abierta hasta que la
comparación fría resuelva.

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
| la copia existe y valida | se reanuda la comparación fría desde ella |
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
   la firma del libro y el hash de CADA sidecar—, no solo heads y firma;
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
`PRECEDENCIA_TERMINAL`, y las
rutas de estado, libro, lock, staging, los dos
marcadores terminales (`completed.json`, `blocked.json`) y los sidecars
(`silencio.json`, `verificacion.json`) y `terminal.request`.
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
40bis. **concurrencia de la transición** *(rev.12)*, con el mutex REAL, no un
    doble: un registrador B entra después de A y ANTES de publicar; ningún
    ciclo de ingesta entra en esa ventana; `silencio_h4` con la comparación
    fría `pending` NO publica, y al resolver `divergent` el terminal es por
    divergencia — en los dos órdenes de llegada; `deferred` con ganador
    científico falla cerrado; y caída durante CADA una de las dos fases de
    barrera, la de registro y la de publicación;
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

---

## Fuera de alcance

Gráfico del Command Center: siguiente pendiente prioritario, después de
estabilizar el gate 7.
