# Bot3.v13 — Observador operativo · DISEÑO rev.1

**Estado: DISEÑO. No implementado. No desplegado. Cohorte no iniciada.**
Contrato del motor: `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d` (congelado, no se toca).

Este documento se pre-registra y se audita ANTES de escribir una línea de
implementación, por la misma vía que el protocolo v13.

---

## 0. Por qué existe este documento

`modules/bot3/v9` no tiene punto de entrada de producción. Verificado:

- sin `__main__`, sin llamador fuera de `tests/`, sin servicio launchd;
- `correr()` no expone la ruta de push: `construir_almacenes` acepta `extra`
  y hace `alm.ofrecer(extra[mercado], "push")`, pero `correr` nunca se lo pasa;
- CF-28 prohíbe cambiar el snapshot después del nacimiento (la recuperación
  falla con `snapshot de {nombre} cambió desde el nacimiento`).

De las tres cosas juntas se sigue que **hoy no existe forma de incorporar una
vela nueva a una cohorte viva**. El observador es esa pieza, y como escribe el
libro forward, es parte de la máquina científica, no del despliegue.

## 1. Alcance

**Hace:** pull de velas cerradas desde la API pública de Binance, las ofrece
al almacén como `push`, corre el ciclo del motor, persiste estado y libro.

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

**Hallazgo sobre el alcance pedido.** La lista de requisitos decía «solo velas
M15 cerradas». Es insuficiente: el motor es H4→M15 y el rango rector sale del
almacén H4 (`motor.h4[mercado]`). Si H4 no avanza, el rector queda congelado en
el fin del snapshot y la cohorte deriva en silencio. El observador debe hacer
pull de **las dos** TF. Nota adicional: hoy los snapshots terminan en instantes
distintos (M15 el 2026-06-11 19:30, H4 el 2026-06-14 20:00).

## 3. Fuente de datos

- REST público de Binance Futuros (`/fapi/v1/klines`), **sin credenciales**.
- El módulo no importa nada de ejecución, ni `BINANCE_TRADE_*`.
- Sin claves, la falla máxima posible es no obtener datos: fail-closed, nunca
  una orden.

### Vela cerrada

Se acepta una vela `t` solo si el exchange la reporta con su `closeTime`
cumplido y `ahora ≥ t + dur + MARGEN_CIERRE`. La vela en curso se descarta
siempre. `MARGEN_CIERRE` se congela en el protocolo, no se elige en operación.

## 4. Inmutabilidad del snapshot

El almacén **nace** del snapshot versionado del commit de despliegue (CF-28) y
ese snapshot no vuelve a tocarse mientras la cohorte viva. Toda vela posterior
entra por `ofrecer(..., "push")`. Actualizar el archivo canónico durante la
cohorte es un fallo cerrado, y así debe seguir siendo.

## 5. Ciclo

Un pull = un ciclo = un reloj observado, muestreado una sola vez
(`iniciar_ciclo`, CF-16/CF-34).

```
cada CADENCIA:
  iniciar_ciclo(ahora)
    para cada mercado y TF:
      pull desde ultimo_t del almacén (con solape de RESOLAPE velas)
      filtrar a velas cerradas
      alm.ofrecer(velas, "push")
    alm.drenar()
    declarar huecos locales cuando el watermark se cumpla
    procesar los lotes globales ahora finalizables
  finalizar_ciclo()
```

El **solape** es deliberado: se re-piden `RESOLAPE` velas ya selladas para que
una revisión del exchange aparezca como `vela_revisada` (CF-26) en vez de pasar
inadvertida. Reofrecer una vela idéntica no genera incidencia.

**El buffer no se persiste.** `ofrecer` deja las velas en `_buffer` y solo
`drenar` las appendea. Una caída con el buffer lleno (típicamente porque un
hueco bloquea el avance) pierde esas velas, y el arranque siguiente debe
re-pedirlas desde `ultimo_t`. Es correcto y hay que dejarlo explícito: la
recuperación no asume nada del buffer.

### Proceso largo, no re-corrida completa

Decisión central. Dos opciones:

| | por ciclo | riesgo |
|---|---|---|
| (a) proceso largo, motor en memoria | incremental | estado en RAM |
| (b) re-correr todo cada ciclo | 402 s hoy, creciendo | supera la cadencia |

Medido en el ensayo a escala: una corrida completa son 345 s y un reinicio 402 s.
La opción (b) ya consume casi la mitad de un ciclo de 15 minutos y crece con la
cohorte hasta superarlo. **Se elige (a)**: daemon largo que replica la historia
una vez al arrancar (~7 min) y después procesa solo lotes nuevos.

El riesgo de (a) —que el estado en RAM derive del que produciría un arranque en
frío— se controla con la §8.

## 6. Instancia única

Lock exclusivo (`flock`) sobre un archivo en el directorio de estado, tomado
antes de abrir el libro y liberado solo al terminar. Dos observadores sobre el
mismo estado producirían dos historias bajo una identidad de cohorte: es el
mismo daño que `estado_dir` compartido, y se rechaza igual.

## 7. Fail-closed

| Situación | Respuesta |
|---|---|
| Lag > `LAG_MAX` | detener el ciclo, no procesar lotes, alertar |
| Error de red / HTTP | reintento con backoff; agotado, detener |
| Hueco local | `declarar_hueco_local` cuando el watermark se cumpla |
| Silencio de un mercado | `watermark_exchange` (CF-29), degradación |
| `vela_revisada` | se registra; **no** se reescribe lo sellado |
| Snapshot canónico alterado | fallo cerrado (ya vigente) |
| Árbol de `modules/bot3/v9` sucio | fallo cerrado (ya vigente) |
| Identidad de cohorte distinta | fallo cerrado (ya vigente) |

Ninguna de estas situaciones se resuelve con un reintento silencioso que
cambie el libro.

## 8. Verificación de determinismo

Es la prueba que pidió la auditoría y la que justifica elegir (a).

Periódicamente, y siempre antes de cualquier reporte de resultados:

1. copiar estado y libro a un directorio scratch;
2. correr un arranque **en frío** sobre esa copia;
3. comparar la firma del libro **byte a byte** con el del proceso vivo.

Divergencia = incidente, cohorte marcada, sin excepción. Esto convierte la
determinación de replay en algo medido y no supuesto.

Además, el gate de aceptación de la implementación:

> ejecución continua sobre N+1 velas vs. ejecución sobre N + reinicio +
> incorporación de la vela N+1 → misma firma de ledger.

Hoy ese gate **no es construible** porque no existe la ruta de push; con el
observador, sí.

## 9. Parámetros a congelar en el protocolo

`CADENCIA`, `MARGEN_CIERRE`, `RESOLAPE`, `LAG_MAX`, `BACKOFF_*`, `TF_OBSERVADAS`,
`UNIVERSO`, rutas de estado y libro. Ninguno se elige en operación.

`bootstrap_hasta` **no** es parámetro del observador: es la identidad de la
cohorte y se congela en el acta de activación.

## 10. Secuencia de activación

1. diseño (este documento) → auditoría → aprobación;
2. protocolo del observador pre-registrado con hash;
3. implementación **solo en scratch**, con datos sintéticos o copias;
4. gate continuo vs. reinicio + vela nueva;
5. auditoría de la implementación;
6. recién entonces, actualizar los snapshots canónicos hasta el último M15
   cerrado común;
7. congelar snapshot, commit, hashes y `bootstrap_hasta`;
8. desplegar el observador e iniciar la cohorte desde la vela siguiente.

Los snapshots canónicos **no** se actualizan antes del paso 6: volverían a
quedar atrasados mientras se diseña e implementa.

## 11. Registro de anomalía conocida

Hueco 2023-03-24 12:45 → 13:45 (5 velas M15) presente en los siete mercados.

Clasificación: **`common_upstream_gap` / causa no demostrada.** La
simultaneidad es compatible con una caída del exchange y también con una falla
de nuestra ingesta; sin evidencia externa no se afirma cuál. Corresponde
corregir aquí una afirmación previa que lo daba por «caída del exchange».

---

## Fuera de alcance

Gráfico del Command Center: siguiente pendiente prioritario, después de
estabilizar el gate 7. No se integra hasta entonces.
