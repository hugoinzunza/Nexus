# Bot3.v13 — Observador operativo · DISEÑO rev.3

**Estado: DISEÑO. No implementado. No desplegado. Cohorte no iniciada.**
Contrato del motor: `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d` (congelado, no se toca).

rev.3 responde a `docs/AUDITORIA_BOT3_V13_OBSERVADOR_DISENO_REV2.md` (3 blockers,
3 majors, más la publicación atómica del nacimiento). Se pre-registra y se
audita ANTES de escribir una línea de implementación.

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

## 4. Nacimiento atómico desde staging *(rev.3)*

Una caída durante el primer nacimiento no puede dejar unos almacenes
interpretados como cohorte nacida y otros como primer arranque.

```
1. materializar los 14 almacenes COMPLETOS en state/staging/
2. fsync de los 14 archivos
3. escribir manifest.json.tmp con los 14 prefijos + identidad de cohorte
4. fsync del tmp
5. os.replace(staging/*, definitivo) para los 14
6. fsync del directorio
7. os.replace(manifest.json.tmp, manifest.json) + fsync del directorio
```

El manifiesto definitivo es el **único** testigo de nacimiento: mientras no
exista, cualquier resto de `staging/` se descarta y se renace desde cero. Un
manifiesto presente exige los 14 almacenes presentes y consistentes con sus
prefijos; si falta uno, fallo cerrado.

## 5. Orden de escritura por ciclo

```
drenar → fsync de cada almacén tocado → append al libro → fsync del libro
```

Recuperable en cualquier punto sin metadata adicional: los almacenes son
cadenas append-only autenticadas y el libro es idempotente por `event_id`.

---

# Dependencia H4

## 6. Precondición de frescura H4 *(rev.3, reescrito)*

`lote_finalizable(T)` inspecciona SOLO M15 (`engine.py:293`). Verificado.

El observador **no procesa ningún lote `T`** hasta que, para los 7 mercados, la
grilla H4 esté resuelta hasta `T`:

- **grilla esperada**: toda `t_h4` múltiplo de `DUR_H4` con `t_h4 + DUR_H4 ≤ T`,
  desde `GENESIS_H4`;
- **resuelta** significa `alm_h4.cubre(t_h4) ∈ {"vela", "hueco"}` para cada una.

`LAG_MAX` se evalúa **por mercado y por timeframe**: 14 evaluaciones.

### 6.1 Watermark H4: solo local *(rev.3)*

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

### 6.2 Consecuencia, que ya está en la máquina congelada *(rev.3)*

Un hueco H4 sellado parte las épocas, y `_calcular_h4` (`engine.py:688`) exige
época única continua desde `GENESIS_H4`: ese mercado devuelve
`historia_insuficiente` y se abstiene, **mientras los demás continúan**. No hay
que definir nada nuevo: es la regla vigente.

### 6.3 Coste aceptado *(rev.3)*

Sellar un hueco H4 exige 3 cierres H4 posteriores: **hasta 12 horas** en las que
el lote global no avanza. Es fail-closed y se acepta a propósito — la
alternativa es decidir con un rector congelado, que es exactamente la
divergencia que se quiere impedir. Al sellarse, el backlog se procesa en
`catch-up` (§10). La cota se registra en el protocolo, no se descubre operando.

**Por qué no rompe el determinismo.** Es una precondición sobre CUÁNDO llamar a
`procesar_lote`, no sobre QUÉ decide el motor para un estado de almacén dado. En
frío la precondición se satisface trivialmente y se procesan los mismos lotes; y
si en vivo hubo una ausencia H4, quedó SELLADA como marcador y el arranque en
frío lee ese mismo marcador. El motor no se toca.

---

# Verificación de determinismo

## 7. Dos primitivas de exclusión, no una *(rev.3 — BLOCKER 1)*

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

## 8. `state_digest` completo *(rev.3 — BLOCKER 2 + MAJOR 2)*

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
`_gap_por_desde`, `_buffer`.

## 9. Captura y comparación *(rev.3)*

1. el daemon toma `cycle_barrier` al terminar el ciclo;
2. `fsync` de los 14 almacenes y del libro;
3. calcula su `state_digest` vivo;
4. copia almacenes + libro a scratch;
5. suelta la barrera y sigue operando;
6. **fuera del ciclo**, reconstruye en frío desde la copia y compara
   `firma()` del libro **y** `state_digest`.

El daemon real no recibe nada durante la verificación. Gate: heads, digest y
libro del daemon deben quedar byte a byte iguales antes y después.

Divergencia = incidente, cohorte marcada, sin excepción.

---

# Ingesta

## 10. Elegibilidad, reloj y paginación normativos

**Reloj: el de Binance** (`/fapi/v1/time`), muestreado una vez por ciclo.

- elegible sii `serverTime ≥ closeTime + 1 + MARGEN_CIERRE`;
- `serverTime` indisponible → **no se ingiere nada en ese ciclo**. Nunca hay
  fallback silencioso al reloj del Mac;
- deriva contra el reloj local mayor que `DERIVA_MAX` → incidencia operacional
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
  serverTime ← Binance                    (indisponible → fin del ciclo)
  cycle_barrier.acquire()
  iniciar_ciclo(serverTime)
    para cada mercado × {M15, H4}:
      pull paginado (§10) desde ultimo_t − (RESOLAPE−1)·dur
      filtrar a elegibles → alm.ofrecer(velas, "push") → alm.drenar()
      declarar huecos locales cuando el watermark se cumpla
    fsync de los almacenes tocados
    si NO catch-up y se cumple la precondición H4 (§6):
      procesar los lotes globales finalizables
    fsync del libro
  finalizar_ciclo()
  atender verify.request si lo hay (§9)
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

## 13. Marcador `COMPLETED` persistente y atómico *(rev.3 — MAJOR 3)*

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

**Al arrancar**, el marcador se valida antes de abrir ningún ciclo:

- existe y coincide → health `COMPLETED`, no se ingiere nada;
- corrupto o discrepante con almacenes/libro → fallo cerrado.

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
| `completed.json` presente | no se reactiva (§13) |

## 15. Parámetros a congelar en el protocolo

`CADENCIA`, `MARGEN_CIERRE`, `RESOLAPE`, `LIMITE_PAGINA`, `LAG_MAX` (por TF),
`DERIVA_MAX`, `BACKOFF_BASE`, `BACKOFF_MAX`, `BACKOFF_INTENTOS`,
`TF_OBSERVADAS`, `UNIVERSO`, `ENDPOINT_KLINES`, `ENDPOINT_TIME`, rutas de
estado, libro, lock, staging y marcador terminal, y `CADENCIA_VERIFICACION`.
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
4. verificación periódica → heads, digest y libro del daemon byte a byte
   iguales antes y después;
5. digest cambia al alterar un cierre **intermedio** sin cambiar cardinalidad ni
   último elemento;
6. watermark H4 local con prueba reproducible; el mercado queda en
   `historia_insuficiente` **sin bloquear a los otros** una vez sellado;
7. paginación alineada, progreso estricto y backlog multipágina;
8. `serverTime` indisponible o desalineado del reloj del Mac;
9. recuperación desde lag mayor que `LAG_MAX` sin procesar prematuramente;
10. activación con cierres terminales H4 y M15 distintos;
11. corte por N y corte temporal, seguidos de reinicio del servicio →
    `COMPLETED` sobrevive; marcador corrupto → fallo cerrado;
12. caída durante el nacimiento parcial de los 14 almacenes;
13. continuo sobre N+1 vs. N + reinicio + push de N+1 → mismo libro y mismo
    `state_digest`;
14. re-ingesta por push de una vela ya sellada desde el snapshot → **sin**
    incidencia (mapeo idéntico).

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
