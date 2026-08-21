# Bot3.v13 — Observador operativo · DISEÑO rev.5

**Estado: DISEÑO. No implementado. No desplegado. Cohorte no iniciada.**
Contrato del motor: `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d` (congelado, no se toca).

rev.5 responde a `docs/AUDITORIA_BOT3_V13_OBSERVADOR_DISENO_REV4.md` (2 blockers,
3 majors). Se pre-registra y se audita ANTES de escribir una línea de
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

Regla de lectura, única para ambos:

| condición de la ÚLTIMA trama | interpretación | acción |
|---|---|---|
| completa y hash correcto | registro bueno | se acepta |
| bytes < longitud, o falta el `\n` final | **truncación** por caída | se trunca esa trama y se recupera por replay |
| completa pero hash distinto | **corrupción** | **fallo cerrado** |
| cualquier trama NO final rota | corrupción | **fallo cerrado** |

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
| **Comparador** | `eligibility_time − inicio > SILENCIO_MAX_H4`, en milisegundos exactos |
| **Persistencia** | sidecar atómico `silencio.json` con el origen y su evidencia. **No se reinicia al relanzar el daemon** |

`blocked.json` por este motivo lleva: mercado, TF, primer cierre faltante,
último cierre H4 válido, instante de inicio, umbral, el `eligibility_time`
decisivo y la evidencia de las consultas que lo sostienen.

**Valor propuesto: `SILENCIO_MAX_H4 = 72 h`** (18 cierres H4). El argumento es
a priori y no mira ningún silencio real: excede con holgura cualquier ventana
de mantenimiento documentada de Binance, y queda por debajo del punto en que un
mercado mudo deja de ser una interrupción y pasa a ser un deslistado. Un valor
más corto bloquea cohortes por incidentes normales; uno más largo deja la
cohorte detenida sin decidir. **Se congela antes de activar y no se elige
después de ver un silencio**: hacerlo sería exactamente la contaminación que
todo este protocolo intenta impedir.

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

### 9.2 `verification_deferred` es sidecar, no evento *(rev.5 — MAJOR 2)*

`verification_deferred` **no es un tipo del registro cerrado CF-37** y no entra
al libro científico. Es observabilidad operacional, y vive en un sidecar
atómico `verificacion.json` con, como mínimo:

- instante de la deferencia y `eligibility_time` asociado;
- qué buffers estaban no vacíos;
- la última verificación **exitosa** (instante, digest, firma del libro);
- el estado pendiente vigente: `ok` | `deferred` | `pending` | `divergent`.

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

Al cortar el motor (por `CORTE_N_CIERRES` o `T_CORTE`):

```
1. cerrar motor y emitir los eventos terminales
2. fsync de almacenes y libro
3. escribir completed.json.tmp → fsync → os.replace → fsync del directorio
4. exponer health COMPLETED y salir, sin reactivación
```

`completed.json` contiene identidad de cohorte, contrato, commit, motivo del
corte, última barrera, los 14 heads y la firma del libro.

### 13.1 `BLOCKED_INTEGRITY` NO ejecuta el cierre científico *(rev.5 — MAJOR 1)*

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

`blocked.json` usa la misma mecánica atómica que `completed.json` y admite dos
motivos: `silencio_h4` (§6.5) y `determinism_divergence` (§9.1).

**Al arrancar**, el marcador que exista se valida antes de abrir ningún ciclo:

- existe y coincide → health `COMPLETED` / `BLOCKED_INTEGRITY`, no se ingiere;
- corrupto o discrepante con almacenes/libro → fallo cerrado;
- los dos presentes → fallo cerrado.

Reactivar exige acta nueva, con identidad de cohorte nueva. Ninguna extensión ni
cohorte nueva automática.

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
| Verificación `pending` | se sigue ingiriendo; **no** se publica `COMPLETED` (§9.1) |
| Divergencia de determinismo | `BLOCKED_INTEGRITY(determinism_divergence)` (§9.1) |
| `completed.json` o `blocked.json` presente | no se reactiva (§13) |

## 15. Parámetros a congelar en el protocolo

`CADENCIA`, `MARGEN_CIERRE`, `RESOLAPE`, `LIMITE_PAGINA`, `LAG_MAX` (por TF),
`DERIVA_MAX`, `SILENCIO_MAX_H4`, `BACKOFF_BASE`, `BACKOFF_MAX`, `BACKOFF_INTENTOS`,
`TF_OBSERVADAS`, `UNIVERSO`, `ENDPOINT_KLINES`, `ENDPOINT_TIME`,
`CADENCIA_VERIFICACION`, y las rutas de estado, libro, lock, staging, los dos
marcadores terminales (`completed.json`, `blocked.json`) y los sidecars
(`silencio.json`, `verificacion.json`).
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
21. **`SILENCIO_MAX_H4` normativo**: la misma secuencia causal repartida en
    distinto número de ciclos, y con un reinicio intermedio, produce el mismo
    `blocked.json`;
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
