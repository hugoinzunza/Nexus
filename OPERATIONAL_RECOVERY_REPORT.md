# Operational Recovery Report — 2026-08-06

**Sprint:** Operational Recovery (Crisol) · **Host:** Mac mini de Hugo
**Alcance:** restaurar la captura de datos del laboratorio. Sin ciencia nueva.

**Lo que NO se tocó:** hipótesis, protocolos congelados, umbrales, métricas, criterios de
evaluación, resultados históricos, fechas de cohorte, el bot, Aurora, Gate A2. Ninguna
cohorte se reinició. El hueco operacional no se rellenó retrospectivamente.

---

## 1. Causa raíz

El servidor de NexUX se mudó de repositorio: dejó de correr desde `crisol/nexux` y pasó a
correr desde `crisol/nexux-command-center` (launchd `com.hugo.nexux-command-center`, :8812).
El motor de setups siguió funcionando con normalidad — pero escribiendo en el `data/` del
repo nuevo.

Los cuatro consumidores del laboratorio se quedaron apuntando al repo viejo:

```
ESCRIBE (vivo)   crisol/nexux-command-center/data/setups.json   ← el servidor se mudó acá
LEEN   (los 4)   crisol/nexux/data/setups.json                  ← última escritura 2026-08-03 18:15
```

Nadie se dio cuenta durante 2,5 días porque **ningún proceso falló**. Los observadores
seguían vivos, releyendo un archivo muerto cada 60 segundos y reescribiendo puntualmente su
JSON de salida. El colector prospectivo dejó constancia en cada ciclo —`{"types": {},
"written": 0}`— pero nadie leía ese log.

### Por qué la falla fue invisible: el segundo defecto

`modules/hypothesis_lab/module.py` derivaba la salud de `_freshness()`, que medía **la
antigüedad del archivo de salida**. Un observador girando en vacío reescribe su archivo con
la misma puntualidad que uno capturando evidencia, así que los tres salían `fresh` y el
módulo reportaba `"status": "ok"` con dos cohortes en cero.

Las dos causas son independientes y las dos había que corregirlas: la primera rompió la
captura, la segunda impidió verlo.

### Un tercer hallazgo, encontrado durante el sprint

La corrección obvia —repuntar los observadores al `setups.json` vivo— **habría destruido la
cohorte de HYP-EXIT-003**. `shadow_exit.py` reconstruye sus registros iterando los setups
**presentes en el archivo fuente**; `previous_records` es solo una caché para no recalcular
los ya cerrados. El store vivo empezó de cero el 2026-08-03, así que ninguno de los 15
registros existentes estaba en él.

Se verificó antes de tocar nada:

```
elegibles en store VIEJO: 15   cubren 15 de 15 registros
elegibles en store VIVO : 14   cubren  0 de 15 registros
=> repuntar solo al vivo dejaria 0 de 15  <-- COHORTE DESTRUIDA
```

Eso habría sido un reinicio de cohorte encubierto, prohibido por el sprint.

---

## 2. Correcciones realizadas

### 2.1 Fuente canónica única — `research/hypothesis_lab/canonical_setups.py`

Un servicio que une **append-only** todos los stores de setups conocidos y publica un solo
archivo que leen los cuatro consumidores.

- **No es un symlink.** Es un artefacto explícito, con metadatos y versionado en el repo.
- **No rellena el hueco.** Solo deja de tirar lo que cada store ya había registrado por su
  cuenta. Lo que ningún store capturó no aparece y no se inventa.
- **Nunca escribe en los orígenes** (con test que lo verifica por mtime y bytes).
- **Append-only de verdad:** un setup canonizado sobrevive a que su origen desaparezca. Eso
  es lo que protege a las cohortes de la próxima mudanza de repositorio.
- Identidad por `(key, ts_created)`; cuando un setup evoluciona se conserva la versión más
  nueva por `ts_updated`, sin perder nunca la fila ni retroceder a una versión anterior.
- La lista plana solo se reescribe cuando el contenido cambia: evita el falso positivo de
  frescura y evita abortar la pasada de `candle_reversal_shadow`, que rechaza el snapshot si
  el archivo se mueve mientras observa.

Con la unión, la cobertura queda casi continua: el store histórico llega hasta el 2026-08-03
15:20 y el vivo arranca el 2026-08-03 23:09. **El hueco real es de ~7,8 h**, no de 2,5 días.

### 2.2 Salud por movimiento real de registros — `modules/hypothesis_lab/module.py`

Cada observador cruza ahora dos señales independientes:

1. **Intrínseca** — la fecha del registro más nuevo dentro del propio payload. Es stateless
   y correcta desde el primer arranque, sin historia previa.
2. **Persistida** — cuándo cambió por última vez el conteo de registros
   (`data/hypothesis_lab/telemetry/observer_progress.json`). Atrapa el caso en que hay
   registros con fecha reciente pero la cohorte dejó de crecer.

Basta con que **cualquiera** se haya movido; si ninguna lo hizo, el observador sale
`stalled` aunque acabe de reescribir su archivo, y eso arrastra el `health()` del módulo.

**Umbral de silencio: 24 h**, calibrado con los huecos reales entre llegadas de HYP-EXIT-003
(n=28): mediana 1,4 h · p90 12,2 h · **máximo observado 17,4 h**. No es un número a ojo, y
no es un umbral científico: es plomería.

**Detector rápido, en minutos:** la salud de la fuente canónica se mide aparte, sobre el
latido del merger (900 s) y sobre si cada origen se pudo leer. Ese es el que **habría
detectado el apagón del 2026-08-03 en quince minutos** en vez de en dos días y medio.

Un detalle que casi vuelve a esconder la falla: sembrar el ledger de conteo con "ahora" en el
primer arranque simulaba un movimiento que nunca ocurrió. Se siembra con la señal intrínseca.
Hay un test dedicado a eso.

### 2.3 Cinco servicios recableados

| Servicio | Cambio |
|---|---|
| `com.hugo.nexux-lab-canonical` | **nuevo** — publica la fuente canónica cada 30 s |
| `com.hugo.nexux-shadow-exit` | `--setups` → canónica · `WorkingDirectory` → `crisol/nexux` |
| `com.hugo.nexux-candle-shadow` | `--setups` → canónica |
| `com.hugo.nexux-cost-telemetry` | `--input-root` → instancia viva · `WorkingDirectory` → `crisol/nexux` |
| `cl.nexux.trading-intelligence-prospective` | `--source` → canónica |

Los plists quedan versionados en `deploy/`, con el porqué escrito adentro. El código de los
observadores era **byte a byte idéntico** entre los dos repos, y las specs congeladas
comparten SHA-256, así que unificar el `WorkingDirectory` en `crisol/nexux` (superconjunto:
tiene el observador de velas y los 4 estudios más nuevos) no altera qué se ejecuta.

### 2.4 Cobertura de regresión

`tests/test_canonical_setups.py` (8) y `tests/test_hypothesis_lab_module.py` (+5), incluida
la que reproduce exactamente el fallo: *archivo fresco + cohorte detenida ya no puede
reportarse sano*. **371 → 384 pruebas, todas verdes.**

---

## 3. Rutas finales

| Rol | Ruta | Quién escribe |
|---|---|---|
| Setups en vivo (producción) | `crisol/nexux-command-center/data/setups.json` | el servidor NexUX |
| Store histórico (congelado) | `crisol/nexux/data/setups.json` | nadie desde 2026-08-03 |
| **Fuente canónica (única que leen los observadores)** | `crisol/nexux/data/hypothesis_lab/canonical/setups.json` | `com.hugo.nexux-lab-canonical` |
| Canónica con metadatos / latido | `…/canonical/setups_canonical.json` | ídem |
| Salidas de cohortes | `crisol/nexux/data/hypothesis_lab/{shadow,telemetry}/` | cada observador |
| Ledger de progreso | `…/telemetry/observer_progress.json` | el módulo del laboratorio |
| Libros del bot (para costos) | `crisol/nexux-command-center/data/bot_trades.json` | el bot — **hoy no existe** |
| Código y specs del laboratorio | `crisol/nexux` | — |

`NEXUX_RESEARCH_RUNTIME_ROOT=/Users/hugh/crisol/nexux/data` se mantiene sin cambios: es donde
ya viven las cohortes y moverlas habría sido un riesgo innecesario.

---

## 4. Estado de los observadores

Verificado contra el servidor vivo (`/m/hypothesis-lab/api/state`) después del reinicio:

| Observador | Estado | Registros | Capturando | Silencio | Fuente |
|---|---|---:|---|---|---|
| `shadow_exit` | `fresh` | 30 | ✅ sí | 0,0 h / 24 h | `fresh` |
| `candle_reversal` | `fresh` | 14 | ✅ sí | 0,0 h / 24 h | `fresh` |
| `cost_telemetry` | `degraded` | 0 | ❌ no | 108,9 h | `ledger_missing` ×2 |

Fuente canónica: `fresh`, 171 setups, ambos orígenes legibles (144 + 27), latido de 18 s.

## 5. Estado de health()

Activo en producción. El servidor se reinició con autorización explícita
(`launchctl kickstart -k`, ~5 s; el bot está inerte, así que no había órdenes en riesgo).

```json
{"slug": "hypothesis-lab", "status": "degraded",
 "observers": {"shadow_exit": "fresh", "cost_telemetry": "degraded"},
 "stalled": [], "degraded_observers": ["cost_telemetry"], "capturing": ["shadow_exit"]}
```

`degraded` es **el resultado correcto**: `cost_telemetry` está genuinamente bloqueado. Antes
este mismo módulo decía `ok` con dos cohortes en cero.

> El panel del servidor vivo muestra 2 observadores y 6 estudios, no 3 y 8: el fork en
> producción va 4 commits de research atrás de `main`. Mergearlo es un cambio de contenido
> científico y queda **fuera de este sprint**. Los tres observadores corren y capturan por
> igual; es solo la vista la que muestra de menos.

## 6. Estado de las cohortes

| | HYP-EXIT-003 | HYP-CANDLE-002 | HYP-COST-003 |
|---|---|---|---|
| Registros | 15 → **30** | 0 → **14** | 0 → 0 |
| Pareados cerrados | 14 → **27** (mín. 100) | — | — |
| Alcanzan 3R | 6 → **7** (mín. 25) | — | — |
| Cerrados con patrón | — | 0 → **1** (mín. 30) | — |
| Último registro | 03-ago 22:15Z → **06-ago 13:06Z** | — | — |
| `cohort_start_ms` | **sin cambios** | **sin cambios** | **sin cambios** |
| `protocol_sha256` | **sin cambios** | **sin cambios** | **sin cambios** |
| Registros preservados | **15 de 15, 0 perdidos** | n/a (recalcula) | n/a |

Los 27 registros ya cerrados de HYP-EXIT-003 se conservaron **bit a bit** (comparación
JSON completa, 0 alterados).

## 7. Confirmación de captura nuevamente activa

No basta con que los procesos estén arriba. Se dejó un vigía observando el encadenado
completo hasta capturar una propagación real de punta a punta:

```
13:07:39Z  ESCRITURA EN EL SERVIDOR VIVO detectada
13:09:39Z  PROPAGADO -> canonica(total=171) | shadow_exit 29->30 | candle 13->14
```

Un dato nuevo nacido en el servidor de producción atravesó la fuente canónica y llegó a
**las dos cohortes activas** en menos de dos minutos. Eso es la confirmación pedida.

El vigía también registró propagaciones de actualización (`updated: 1`, sin registros
nuevos) a las 13:04:54Z, 13:10:24Z y 13:31:10Z: setups que evolucionan sin activar nada
nuevo. Comportamiento correcto.

## 8. Brecha operacional registrada

Se deja constancia explícita, **sin rellenarla**:

| | |
|---|---|
| Inicio | **2026-08-03 15:20Z** — último `ts_created` del store histórico |
| Fin | **2026-08-03 23:09Z** — primer `ts_created` del store vivo |
| Duración sin cobertura de setups | **~7,8 horas** |
| Detención de la captura | 2026-08-03 22:15Z → 2026-08-06 13:06Z (**2 días 14,9 h**) |
| Registros perdidos definitivamente | los setups creados dentro de la ventana de 7,8 h |
| Registros recuperados | todos los del store vivo desde 23:09Z, que ningún observador había leído |

La distinción importa: la captura estuvo detenida 2,5 días, pero **el dato solo se perdió
durante 7,8 h**. El resto estaba registrado por el store vivo y simplemente nadie lo leía.
Recuperarlo no es rellenar el hueco — es dejar de descartar evidencia ya registrada.

Para HYP-EXIT-003 el hueco cae en la semana 1 de una cohorte de 12 semanas mínimas, y el
bootstrap es por bloques de semana calendario. Para HYP-CANDLE-002 la cohorte abrió el
2026-08-04 00:56Z, es decir **después** del hueco: no lo cruza.

---

## 9. Riesgos pendientes

| # | Sev | Riesgo |
|---|---|---|
| 1 | 🔴 | **`HYP-COST-003` sigue estructuralmente bloqueado.** Necesita comisiones confirmadas de operaciones reales; el bot está inerte (`live:false`, sin llaves `BINANCE_TRADE_*`) y tocarlo está fuera de este sprint. El observador ahora reporta `ledger_missing` en vez de un silencioso `0`, que es lo correcto — pero **no puede avanzar hasta que se decida si el bot vuelve a operar.** Se reporta como `collecting` cuando en rigor está `blocked`; cambiar esa etiqueta toca el protocolo congelado y no se hizo. |
| 2 | 🟠 | **`candle_reversal_shadow` no arrastra estado**: recalcula su cohorte entera en cada pasada. Hoy depende por completo de que la canónica siga siendo append-only. Si la canónica se pierde o se trunca, esa cohorte se pierde con ella. Un respaldo periódico del directorio `canonical/` cerraría el flanco. |
| 3 | 🟠 | **El fork en producción va 4 commits de research atrás de `main`**: el panel muestra 6 estudios de 8 y 2 observadores de 3. No afecta la captura; afecta la visibilidad. |
| 4 | 🟠 | La aritmética de `HYP-CANDLE-002` sigue sin cerrar: 1 patrón cerrado de 30 en la primera pasada, con frecuencia histórica de 2,12%. Al ritmo actual son **4,5 a 9 meses**. Es un problema de diseño del estudio, no de infraestructura, y su discusión pertenece al sprint de investigación. |
| 5 | 🟡 | Cuatro repos del ecosistema **no tienen remoto**: `nexux-trading-intelligence-lab`, `nexux-aurora`, `nexux-ecosystem-governance`, `nexux-aurora-identity-lab`. Solo existen en este disco, lo que contradice la REGLA #1. No se tocaron (Aurora está fuera de alcance). |
| 6 | 🟡 | `~/Library/LaunchAgents/com.hugo.nexus.plist` sigue apuntando a `/Users/hugh/Nexux`, que no existe. No está cargado, así que es inerte — pero es una trampa para el próximo que intente arrancarlo. |
| 7 | 🟡 | `tests/test_bot.py` sigue escribiendo en `data/bot_watchdog.json` de producción (contaminación de estado real con precios sintéticos). Fuera de alcance de este sprint. |
| 8 | 🟡 | El watchdog del bot no corre desde el 2026-08-05 01:16. Fuera de alcance. |

---

## 10. Estado de Git

Ecosistema consistente y todo lo que tenía remoto está subido.

| Repo | Rama | Sin subir | Sucio |
|---|---|---:|---:|
| `nexux` | `main` | **0** | 0 |
| `nexux-command-center` | `codex/command-center-contract-v1` | **0** (eran 12) | 0 |

- Los **12 commits pendientes** del command-center se subieron sin modificarlos:
  `9210eaf..73eb39d`.
- `nexux` subió el sprint: `361a7f8..7a78c3c`.
- Ramas locales sueltas (`claude/intelligent-cohen-163ab4`, `codex/testnet-stop-confirmation`):
  **0 commits exclusivos**, íntegramente contenidas en `origin/main`. Nada en riesgo; se
  dejan como están.
- No se mergeó nada entre ramas: la relación entre `main` y la rama viva queda documentada,
  no alterada.

---

## 11. Respaldo

Estado previo íntegro en `data/hypothesis_lab/_recovery_backup_20260806/`: las tres salidas
de observadores, los dos `setups.json` de origen y los cuatro plists originales. Es lo que
permitió comparar registro por registro y afirmar que no se perdió ninguno.

---

## Cierre

Las dos cohortes que podían recuperarse están capturando, con sus 15 registros previos
intactos y sus protocolos congelados sin tocar. El fallo que las detuvo ahora se detecta en
minutos en vez de días, y hay una prueba que falla si alguien vuelve a confundir "archivo
reciente" con "cohorte viva".

Queda una sola cohorte detenida, `HYP-COST-003`, y no es un problema de plomería: no puede
avanzar mientras el bot no opere. Esa decisión es tuya y está fuera de este sprint.

No se avanzó hacia ningún experimento nuevo. HYP-EXIT y HYP-CANDLE quedan como estaban,
esperando su propio sprint.
