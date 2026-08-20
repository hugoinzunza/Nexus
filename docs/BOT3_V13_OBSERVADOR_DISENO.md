# Bot3.v13 — Observador operativo · DISEÑO rev.2

**Estado: DISEÑO. No implementado. No desplegado. Cohorte no iniciada.**
Contrato del motor: `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d` (congelado, no se toca).

rev.2 responde a `docs/AUDITORIA_BOT3_V13_OBSERVADOR_DISENO.md` (3 blockers,
4 majors). Los apartados nuevos van marcados. Se pre-registra y se audita
ANTES de escribir una línea de implementación.

---

## 0. Por qué existe este documento

`modules/bot3/v9` no tiene punto de entrada de producción. Verificado:

- sin `__main__`, sin llamador fuera de `tests/`, sin servicio launchd;
- `correr()` no expone la ruta de push: `construir_almacenes` acepta `extra`
  y hace `alm.ofrecer(extra[mercado], "push")`, pero `correr` nunca se lo pasa;
- CF-28 prohíbe cambiar el snapshot después del nacimiento.

Hoy no existe forma de incorporar una vela nueva a una cohorte viva. El
observador es esa pieza, y como escribe el libro forward es parte de la
máquina científica, no del despliegue.

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

`modules.bot3` en `config/nexus.json` describe el Bot3.v1 suspendido
(`timeframes: ["15m","1h"]`) y **no se modifica**. El observador no lee esa
clave ni comparte proceso, estado ni libro con él.

El motor es H4→M15 y el rango rector sale de `motor.h4[mercado]`: si H4 no
avanza, el rector queda congelado en el fin del snapshot y la cohorte deriva
sin fallar. Por eso se observan las dos TF.

---

# BLOCKER 1 — Provenance del almacén con head mutable

## 3. El manifiesto deja de guardar estado mutable *(rev.2)*

Hoy la recuperación compara el `head` FÍSICO del archivo contra el `head`
guardado en el manifiesto. La primera vela push cambia ese head, y coordinar
14 almacenes más el manifiesto no es una operación atómica: cualquier orden de
escritura tiene una caída que deja un estado válido rechazado o un manifiesto
adelantado.

**La solución es quitar el estado mutable del manifiesto, no hacerlo
transaccional.** El manifiesto pasa a guardar únicamente el PREFIJO DE
NACIMIENTO, que es inmutable por CF-28:

| campo | qué es |
|---|---|
| `ancla` | ya existe |
| `snapshot_ruta`, `snapshot_sha256`, `commit_snapshot` | ya existen |
| `hash_acum_inicial` | ya existe |
| `snapshot_record_count` | **nuevo**: nº de registros al terminar el nacimiento |
| `snapshot_head` | **nuevo**: `hash_acum` del último registro de nacimiento |
| ~~`head`~~ | **se elimina**: era el único campo mutable |

La recuperación verifica:

1. `cargar()` revalida la cadena entera desde `SEMILLA` (ya vigente);
2. `registros[snapshot_record_count − 1]["hash_acum"] == snapshot_head`;
3. todo lo posterior es sufijo append-only de esa cadena, autenticado por la
   propia cadena.

**No hace falta transacción porque no queda nada que actualizar.** El
manifiesto se escribe una vez, al nacer, y nunca más.

La detección de intercambio de almacenes —única razón por la que se había
introducido `head`— se conserva y mejora: el prefijo de nacimiento deriva del
snapshot de ESE mercado, así que dos almacenes intercambiados tienen prefijos
distintos. La truncación la detecta `snapshot_record_count`; la corrupción, la
cadena.

**Esto cambia `runner.py`**, que está dentro del alcance de código de Bot3, así
que exige su propia ronda de auditoría de implementación. No es un cambio de
contrato: `docs/BOT3_V13_PROTOCOLO.md` no describe el manifiesto.

## 4. Orden de escritura por ciclo *(rev.2)*

```
drenar → fsync del archivo de cada almacén → append al libro → fsync del libro
```

Una caída en cualquier punto es recuperable sin metadata adicional: los
almacenes son cadenas append-only autenticadas, y el libro se repone por
`event_id` (idempotencia ya vigente y ya probada por la matriz de caídas).

---

# BLOCKER 2 — M15 no puede avanzar con H4 atrasado

## 5. Precondición de frescura H4 *(rev.2)*

`lote_finalizable(T)` inspecciona SOLO M15 (`engine.py:293`). Verificado. Si
las siete series M15 llegan y una consulta H4 falla, el motor procesaría el
lote con un rector congelado, y el replay no puede corregir un evento sellado.

El observador **no procesa ningún lote `T`** hasta demostrar, para los 7
mercados, una de estas dos condiciones:

1. **cobertura H4 completa**: toda vela H4 cuyo cierre sea `≤ T` está sellada
   en el almacén H4 (`cubre(t_h4) == "vela"`); o
2. **ausencia declarada causalmente**: el instante H4 faltante está cubierto por
   un marcador de hueco sellado, declarado por la misma maquinaria de watermark
   que ya usa M15.

`LAG_MAX` se evalúa **por mercado y por timeframe**: 14 evaluaciones, no una.
Un fallo H4 no puede quedar oculto por M15 fresco ni por el resto del universo.

**Por qué esto no rompe el determinismo.** Es una precondición del observador
sobre CUÁNDO llamar a `procesar_lote`, no un cambio en QUÉ decide el motor
para un estado de almacén dado. En un arranque en frío sobre datos completos la
precondición se satisface trivialmente y se procesan los mismos lotes. Si en
vivo hubo una ausencia H4, quedó SELLADA como marcador, y el arranque en frío
lee ese mismo marcador. El motor no se toca.

---

# BLOCKER 3 — Igualdad de estado, no solo de libro

## 6. `state_digest` *(rev.2)*

Comparar solo los bytes del libro detecta una divergencia ya materializada, no
una latente. Dos motores pueden tener libros idénticos y diferir en estado
vivo, y declarar un falso éxito.

`state_digest` = SHA-256 del JSON canónico de, en orden canónico:

- por mercado: `estado`, `degradado`, `candidato`, `orden`, `posicion`,
  `salida`, `zonas_tocadas` (ordenado);
- del motor: `cortado`, `motivo_corte`, `_frontera_cruzada`,
  `_epocas_anunciadas` (ordenado), `lotes_finalizados` (último y cardinalidad),
  `cierres` (cardinalidad), `bootstrap_hasta`;
- por almacén (14): `head` físico y `len(registros)`.

Excluye `_reloj_ciclo` y `_ciclo_externo`: son telemetría del ciclo, no estado
del modelo.

## 7. Captura consistente y sufijo desafío *(rev.2)*

La copia scratch **no** se toma mientras el daemon escribe. Secuencia:

1. tomar el lock del observador;
2. `finalizar_ciclo()` — barrera cerrada, nada a medio drenar;
3. `fsync` de los 14 almacenes y del libro;
4. copiar;
5. liberar.

Verificación, en la misma barrera:

- arranque **en frío** sobre la copia → comparar `firma()` del libro **y**
  `state_digest`;
- **sufijo desafío**: alimentar a los dos motores —el vivo y el frío— con el
  mismo sufijo sintético de velas y comparar libro y digest resultantes. Esto
  materializa una divergencia latente que el instante de control no mostraría.

Divergencia = incidente, cohorte marcada, sin excepción.

---

# MAJORS

## 8. Elegibilidad, reloj y paginación normativos *(rev.2 — MAJOR 1)*

**Reloj de elegibilidad: el de Binance**, `/fapi/v1/time`, muestreado una vez
por ciclo. El reloj del Mac no decide qué vela es elegible.

- elegible sii `serverTime ≥ closeTime + 1 + MARGEN_CIERRE`;
- `serverTime` indisponible → **no se ingiere nada en ese ciclo** (fail-closed).
  Nunca se cae en silencio al reloj local;
- se compara `serverTime` con el reloj local y una deriva mayor a `DERIVA_MAX`
  se registra como incidencia operacional: un Mac con la hora rota tiene que
  ser visible, aunque no decida nada.

**Paginación**, por mercado y TF:

- `startTime = ultimo_t + 1 − RESOLAPE·dur`, `limit = LIMITE_PAGINA`;
- se itera mientras la página vuelva llena, avanzando por `startTime`;
- página vacía → fin; fuera de orden, `t` desalineado de la grilla, duplicado
  dentro de la página o intervalo distinto del pedido → **fail-closed**, no se
  ofrece nada de esa página;
- se valida que el símbolo sea el perpetuo USD-M y la TF exactamente `15m`/`4h`.

**Mapeo OHLCV**: índice → campo explícito, `t = openTime`, y los numéricos se
parsean por **la misma ruta que el cargador del snapshot**. Si el push
produjera una serialización distinta para la misma vela, el solape generaría
una tormenta de `vela_revisada` sobre datos idénticos. Gate obligatorio:
re-ingerir por push una vela ya sellada desde el snapshot NO produce incidencia.

La cadencia de red no cambia los bytes aceptados ni el orden de sellado.

## 9. Modo `catch-up` *(rev.2 — MAJOR 2)*

«Detener el ciclo» ante `LAG_MAX` deja al observador bloqueado para siempre:
tras una caída larga el lag sigue excedido precisamente porque no se permitió
recuperar. Se define un modo explícito:

| | |
|---|---|
| Permite | descargar, ofrecer, drenar, sellar, paginar hasta el watermark común |
| Prohíbe | procesar lotes nuevos mientras cualquiera de los 14 streams siga stale |
| Nunca | saltar lotes, redefinir la frontera, ni reescribir lo sellado |
| Sale | cuando los 14 streams están frescos y la precondición H4 (§5) se cumple |

`processed_at` conserva el reloj real de materialización: un catch-up se ve en
la telemetría como lo que fue, no se disfraza de tiempo real.

## 10. La frontera congela las dos TF *(rev.2 — MAJOR 3)*

El acta de activación congela:

- el último `t` y el último cierre de **cada uno de los 14 snapshots**;
- `bootstrap_hasta = F`, el último cierre M15 común a los siete mercados;
- en H4, **exactamente** las velas con cierre `≤ F` como historia causal
  elegible;
- hashes, commit y auditoría de continuidad de ambas TF.

Una vela H4 que cierre después de `F` no influye en la primera decisión forward
aunque ya exista físicamente en un archivo o en una respuesta. Hoy los
snapshots terminan en instantes distintos (M15 2026-06-11 19:30, H4 2026-06-14
20:00), así que esto no es teórico.

## 11. Estado terminal *(rev.2 — MAJOR 4)*

Cuando el motor corta —por `CORTE_N_CIERRES` o por `T_CORTE`— el observador:

1. deja de ingerir y de procesar para esa cohorte;
2. `fsync` y sello final de almacenes y libro;
3. health `COMPLETED`, con motivo del corte y última barrera;
4. **no** reinicia la cohorte cerrada como si estuviera activa;
5. **no** extiende ni abre una cohorte nueva automáticamente.

Reactivar exige un acta nueva, con identidad de cohorte nueva.

---

## 12. Ciclo

Un pull = un ciclo = un reloj observado, muestreado una sola vez (CF-16/CF-34).

```
cada CADENCIA:
  serverTime ← Binance          (indisponible → fin del ciclo)
  iniciar_ciclo(ahora)
    para cada mercado × {M15, H4}:
      pull paginado desde ultimo_t − RESOLAPE·dur
      filtrar a velas elegibles
      alm.ofrecer(velas, "push")
      alm.drenar()
      declarar huecos locales cuando el watermark se cumpla
    fsync de los 14 almacenes
    si NO catch-up y se cumple la precondición H4 (§5):
      procesar los lotes globales finalizables
    fsync del libro
  finalizar_ciclo()
```

**El buffer no se persiste.** `ofrecer` deja las velas en `_buffer` y solo
`drenar` las appendea. Una caída con el buffer lleno pierde esas velas y el
arranque siguiente las re-pide desde `ultimo_t`. La recuperación no asume nada
del buffer.

### Proceso largo, no re-corrida completa

Medido en el ensayo a escala: corrida completa 345 s, reinicio 402 s. Re-correr
todo cada ciclo ya consume la mitad de un ciclo de 15 minutos y crece con la
cohorte hasta superarlo. Se elige daemon largo: replica la historia una vez al
arrancar (~7 min) y después procesa solo lotes nuevos. El riesgo de deriva en
RAM lo controlan §6 y §7.

## 13. Instancia única

Lock exclusivo (`flock`) sobre un archivo del directorio de estado, tomado
antes de abrir el libro y liberado solo al terminar. Dos observadores sobre el
mismo estado producirían dos historias bajo una identidad de cohorte.

## 14. Fail-closed

| Situación | Respuesta |
|---|---|
| `serverTime` indisponible | no se ingiere en ese ciclo |
| Deriva reloj local > `DERIVA_MAX` | incidencia operacional visible |
| Página inválida (orden, grilla, duplicado, TF) | se descarta entera |
| Lag > `LAG_MAX` en cualquiera de los 14 | modo `catch-up` (§9) |
| Precondición H4 incumplida | no se procesa ningún lote |
| Error de red / HTTP | backoff; agotado, fin del ciclo |
| Hueco local | `declarar_hueco_local` al cumplirse el watermark |
| Silencio de un mercado | `watermark_exchange` (CF-29), degradación |
| `vela_revisada` | se registra; **no** se reescribe lo sellado |
| Snapshot canónico alterado | fallo cerrado (ya vigente) |
| Árbol de `modules/bot3/v9` sucio | fallo cerrado (ya vigente) |
| Identidad de cohorte distinta | fallo cerrado (ya vigente) |
| Cohorte `COMPLETED` | no se reactiva (§11) |

Ninguna se resuelve con un reintento silencioso que cambie el libro.

## 15. Parámetros a congelar en el protocolo

`CADENCIA`, `MARGEN_CIERRE`, `RESOLAPE`, `LIMITE_PAGINA`, `LAG_MAX` (por TF),
`DERIVA_MAX`, `BACKOFF_BASE`, `BACKOFF_MAX`, `BACKOFF_INTENTOS`,
`TF_OBSERVADAS`, `UNIVERSO`, `ENDPOINT_KLINES`, `ENDPOINT_TIME`, rutas de
estado, libro y lock, `CADENCIA_VERIFICACION` y la definición del sufijo
desafío. Ninguno se elige en operación.

`bootstrap_hasta` **no** es parámetro del observador: es la identidad de la
cohorte y se congela en el acta de activación.

## 16. Gates de aceptación

Los diez de la auditoría, más el del mapeo:

1. append push y caída en **cada** frontera de almacén y de metadata;
2. M15 fresco con H4 atrasado o ausente → cero lotes procesados;
3. copia scratch consistente bajo barrera y lock;
4. divergencia latente de estado con libro aún idéntico → detectada;
5. paginación de backlog mayor que `LIMITE_PAGINA`;
6. `serverTime` indisponible o desalineado del reloj del Mac;
7. recuperación desde lag mayor que `LAG_MAX` sin procesar prematuramente;
8. activación con cierres terminales H4 y M15 distintos;
9. corte por N y corte temporal, seguidos de reinicio del servicio;
10. continuo sobre N+1 vs. N + reinicio + push de la vela N+1 → mismo libro y
    mismo `state_digest`;
11. re-ingesta por push de una vela ya sellada desde el snapshot → **sin**
    incidencia (mapeo idéntico).

## 17. Secuencia de activación

1. diseño (este documento) → auditoría → aprobación;
2. protocolo del observador pre-registrado con hash;
3. implementación **solo en scratch**, con datos sintéticos o copias;
4. gates §16;
5. auditoría de la implementación (incluye el cambio de manifiesto de §3);
6. recién entonces, actualizar los snapshots canónicos hasta el último M15
   cerrado común;
7. congelar snapshots, commit, hashes y `bootstrap_hasta` (§10);
8. desplegar el observador e iniciar la cohorte desde la vela siguiente.

Los snapshots canónicos **no** se actualizan antes del paso 6: volverían a
quedar atrasados mientras se diseña e implementa.

## 18. Registro de anomalía conocida

Hueco 2023-03-24 12:45 → 13:45 (5 velas M15) presente en los siete mercados.

Clasificación: **`common_upstream_gap` / causa no demostrada.** La
simultaneidad es compatible con una caída del exchange y también con una falla
de nuestra ingesta; sin evidencia externa no se afirma cuál.

---

## Fuera de alcance

Gráfico del Command Center: siguiente pendiente prioritario, después de
estabilizar el gate 7. No se integra hasta entonces.
