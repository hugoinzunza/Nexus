# Auditoría NEXUX — 2026-08-06

Auditoría de estado en el Mac mini (`Mac-mini-de-Hugo.local`), hecha leyendo procesos vivos,
launchd, logs, ficheros de datos y los endpoints del servidor que está corriendo.
Todo lo que sigue es observación; no se cambió ni una línea.

---

## 0. Semáforo

| Área | Estado | Una línea |
|---|---|---|
| Diario (motor de setups) | 🟢 vivo | Última actualización hoy 10:06 UTC; ~5 setups resueltos/día |
| Inteligencia | 🟢 vivo | Vela 1h de las 11:00 UTC, fuente Binance pública válida |
| BOT | 🔴 **inerte** | Sin llaves de subcuenta → no ejecuta *ni siquiera en papel* desde el 27-jul |
| Watchdog del bot | 🔴 apagado | Ningún proceso; último ciclo 05-ago 01:16 |
| Laboratorio · shadow_exit | 🟠 **congelado** | 15 registros, sin moverse desde el 03-ago 22:15 |
| Laboratorio · candle_reversal | 🔴 **cero** | Arrancó el 04-ago y lleva 0 registros en 2 días |
| Laboratorio · cost_telemetry | 🔴 bloqueado | 0 registros; necesita ejecuciones live que no existen |
| Journal / CoinSignals / CoinGlass | ⚪ sin datos | `has_data: false`, `waiting: true` |
| Git | 🟠 | 12 commits sin pushear en la rama que está en producción |

---

## 1. Lo que realmente está corriendo

**Vivos** (launchd, `KeepAlive`):

| Servicio | Qué es | Directorio de trabajo |
|---|---|---|
| `com.hugo.nexux-command-center` | **El NexUX que está en el aire** (uvicorn `core.app:app` :8812) | `crisol/nexux-command-center` |
| `com.hugo.nexux-shadow-exit` | Observador HYP-EXIT-003 | lee `crisol/nexux/data` |
| `com.hugo.nexux-candle-shadow` | Observador HYP-CANDLE-002 | lee `crisol/nexux/data` |
| `com.hugo.nexux-cost-telemetry` | Observador HYP-COST-003 | lee `crisol/nexux` |
| `cl.nexux.trading-intelligence-prospective` | Colector del lab de trading | lee `crisol/nexux/data/setups.json` |

**Caídos o inexistentes:**

- `com.hugo.nexus` — el servidor "oficial" **no está cargado**, y su plist apunta a
  `/Users/hugh/Nexux`, **una carpeta que no existe**. Aunque se cargara, no arrancaría.
- `com.hugo.nexus-collector` y `com.hugo.nexus-klines` — plists presentes, no cargados.
- Watchdog del bot — ningún proceso.
- Colector de CoinSignals y de CoinGlass — ningún proceso, ningún dato.

### 1.1 El problema de fondo: el sistema está partido en dos

Esto explica casi todo lo demás.

```
ESCRIBE (vivo)      crisol/nexux-command-center/data/setups.json   → 06-ago 10:06  ✅
LEEN   (lab)        crisol/nexux/data/setups.json                  → 03-ago 18:15  ❌ 2,5 días muerto
```

El servidor migró a `nexux-command-center` pero **los tres observadores del laboratorio y
el colector prospectivo siguen apuntando al repo viejo**, por argumento explícito en sus
plists (`--setups /Users/hugh/crisol/nexux/data/setups.json`) y por la variable
`NEXUX_RESEARCH_RUNTIME_ROOT=/Users/hugh/crisol/nexux/data`.

Llevan 2,5 días releyendo el mismo archivo muerto cada 60 segundos y reescribiendo el
mismo resultado. El log del colector prospectivo lo dice literal en cada ciclo:

```
{"types": {}, "written": 0}
```

Además, el fork que está en producción va **4 commits atrás** del `main` de `nexux`: le
faltan `HYP-CANDLE-001`, `HYP-SEASON-001`, `HYP-TREND-001` y el observador de velas.
Por eso el panel del laboratorio muestra **6 estudios en vez de 8**.

---

## 2. El BOT

### 2.1 Estado actual: inerte

El log del servidor lo repite en cada arranque:

```
[21:22:38] bot: ejecutor espejo inerte (sin llaves de subcuenta) · modo dry-run
```

En `modules/bot/executor.py:273`:

```python
@property
def active(self) -> bool:
    return bool(self.cfg.get("enabled")) and self.client() is not None
```

Y `on_transitions()` corta en seco si `not self.active`. O sea: **sin llaves
`BINANCE_TRADE_*`, el bot no registra ni las operaciones de papel.** No es que esté en
dry-run: está apagado del todo.

Confirmado:
- No existe `deploy/trade.env` en ninguno de los dos repos.
- El plist del servidor no define `BINANCE_TRADE_*`.
- `NEXUS_TESTNET_WORKER` no está seteado → el ejecutor de Binance Demo tampoco corre.
- **No existe `data/bot_trades.json` en la instancia que está corriendo.** Cero operaciones.

`config.bot.live` sigue en `false`, así que **no hay capital real expuesto**. Eso está bien.
Lo que no está bien es que tampoco hay forward-test.

### 2.2 El libro histórico (`crisol/nexux/data/bot_trades.json`, último 27-jul)

60 operaciones, 58 cerradas, 2 abiertas.

| Fase | Ventana | n | Σ R | avg R | Aciertos | PF (R) | P&L USD | Comisiones |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **live** | 23-jun → 01-jul | 27 | −3,05 | −0,12 | 12/25 | 0,745 | **−129,03** | 48,93 |
| **dry** | 06-jul → 27-jul | 31 | +6,20 | +0,20 | 17/31 | 1,564 | +25,03 | 64,74 |

Dos cosas que vale decir con todas sus letras:

1. **La única fase con dinero real terminó en −129 USD con PF 0,745.** Nueve días, 27
   operaciones. Es muestra chica, pero es el único dato real que existe.
2. **Las comisiones se comen el resultado.** En dry, 31 operaciones dejaron +25 USD de P&L
   contra 64,74 USD de comisiones. En live, 48,93 USD de comisiones sobre 27 operaciones.
   Este es exactamente el número que `HYP-COST-003` debería estar midiendo — y no mide nada.

**Dos posiciones siguen abiertas desde el 27-jul** (10 días), ambas en modo `dry`, sin
riesgo real: XRP long (sin parciales) y SOL long (TP1 tomado a 0,5R, media posición viva).
Están congeladas porque el ejecutor que las manejaba ya no existe.

### 2.3 Watchdog

No corre. El estado (`bot_watchdog.json`, 66 ciclos) marca último ciclo el **05-ago 01:16**,
hace 33 horas. De sus 54 eventos, **12 son `lectura_fallida`**, incluyendo
`{"code":-2015,"msg":"Invalid API-key"}`.

Ahora bien — ese archivo está **contaminado por los tests**: contiene precios sintéticos
(BTC a 103,5; ADA a 0,185). `tests/test_bot.py:714` carga `deploy/bot_watchdog.py` por
`spec_from_file_location`, y el módulo escribe en `<ROOT>/data/bot_watchdog.json`, que es
la ruta de producción. Los tests están pisando el estado real.

---

## 3. El Diario (motor de setups)

🟢 **Es lo único del stack operativo que funciona bien.** Actualizado hoy a las 10:06 UTC.

Ventana viva (03-ago 23:09 → 06-ago 09:41), 27 setups:

| Estado | n |
|---|---:|
| perdida | 7 |
| ganada | 6 |
| anulada | 6 |
| pendiente | 7 |
| activo | 1 |

13 resueltos: **Σ −2,39R · avg −0,18R · 6/13 aciertos · PF 0,66**. RR medio de los
resueltos: 6,6. 16 de 27 cumplen `rr >= 5`.

| Día | n | Σ R |
|---|---:|---:|
| 03-ago | 4 | −0,16 |
| 04-ago | 5 | −2,00 |
| 05-ago | 3 | +0,77 |
| 06-ago | 1 | −1,00 |

Por par: ETH +0,84 · ADA +0,27 · XRP −0,50 · SOL −1,00 · BTC −2,00.

Tres días y medio no dicen nada estadísticamente. Lo dejo anotado como observación, no
como veredicto.

---

## 4. Inteligencia

🟢 **Funcionando correctamente.** Verificado contra el endpoint vivo:

- Precio BTC 64.494,9 · vela 1h cerrada de las 11:00 UTC de hoy.
- `fuente_meta: {fuente: "binance_publico", valida: true}` — solo klines públicas, sin firma.
- `research_only: true`, `execution_enabled: false`. Coherente con la config.
- Estructura 1h y 1D calculadas (pivotes, fractales, tendencia), rejilla anual,
  pivotes clásicos diarios, análisis de vacío arriba/abajo, rejilla placebo como control.

Dos observaciones, ninguna es un fallo:

1. El módulo se declara honestamente sin validar:
   > *"Research sin validar. Del curso completo, cero conceptos tienen evidencia
   > cuantitativa propia."*
   Eso es correcto y es lo que dice el principio del producto. Pero significa que
   Inteligencia hoy **no alimenta ninguna hipótesis del laboratorio**. Es un visor.
2. `refugios_promovidos: []` — ningún nivel ha sido promovido.

---

## 5. Research / Laboratorio

### 5.1 Evidencia histórica (cerrada)

`data/hypothesis_lab/lab.sqlite3` (93 MB): 1 pre-registro (`HYP-EXIT-002`), 1 corrida del
01-ago, 180 ensayos, **155.520 candidatos** — 72.126 descartados, 64.923 SL, 16.395 TP,
2.076 cerrados por timeout.

Ocho estudios en `research/hypothesis_lab/reports/` (el panel solo enseña 6, ver §1.1):

| ID | Familia | Estado | Veredicto |
|---|---|---|---|
| HYP-EXIT-001 | Salidas | cerrado | Parciales 2R/3R reducen expectativa; 5R no supera al original |
| **HYP-EXIT-002** | Salidas | **candidato** | Único que no empeora; IC95 incluye cero |
| HYP-EXIT-003 | Salidas | recolectando | Cohorte forward del anterior |
| HYP-COST-001 | Costos | cerrado | Exploratorio; no autoriza recalibrar |
| HYP-COST-002 | Costos | cerrado | Ninguna comparación sobrevive Holm |
| HYP-COST-003 | Costos | recolectando | Bloqueado (ver §5.2) |
| HYP-SEASON-001 | Estacionalidad | exploratorio | Julio tras mayo/junio rojos: p=0,44, IC95 cruza cero |
| HYP-TREND-001 | Estructura | exploratorio | Solo la ruptura bajista + retest a 10d sobrevive: −2,78 pp, IC95 [−4,35; −1,13] |
| **HYP-CANDLE-001** | Velas | **candidato** | Patrón informativo (+1,39R de exceso); esperar la confirmación destruye −2,80R |

El rigor metodológico es genuinamente bueno: pre-registro con SHA-256, corrección de Holm,
bootstrap por bloques de calendario, bloqueos explícitos (DSR/PBO no simulados, sin
permutación IID), y estudios que se auto-declaran limitados. No hay inflado de edge.

### 5.2 Recolección forward — **aquí está el problema**

Esto es lo que pediste mirar con lupa, y es donde está el daño.

#### `HYP-EXIT-003-SHADOW` — 🟠 congelado

```
15 registros · 14 pareados cerrados · 6 alcanzaron 3R
Último registro: 2026-08-03 22:15:53Z    (hace 2,5 días)
```

Cohorte abierta el **01-ago 14:07**. Recolectó bien durante ~1,84 días (02-ago → 03-ago) y
después se detuvo en seco: es el observador que lee el `setups.json` muerto.

Requisitos del protocolo (congelado, `rule_changes_after_start: forbidden`):

| Criterio | Mínimo | Hoy | Falta |
|---|---:|---:|---|
| Operaciones pareadas cerradas | 100 | 14 | 86 |
| Operaciones que alcanzan 3R | 25 | 6 | 19 |
| Semanas de calendario | 12 | 0,7 | 11,3 |

Al ritmo que llevaba vivo (**7,6 pareadas/día, 3,3 con 3R/día**), la muestra se
completaría en ~13 días. **El cuello de botella real son las 12 semanas de calendario:
24-oct-2026.** Regla terminal: a las 200 pareadas o 26 semanas (30-ene-2027), si no cumple
todos los criterios, se descarta.

Resultados provisionales (n=14, sin valor decisorio):

| Métrica | original | protect_3r | Requisito |
|---|---:|---:|---|
| avg net R | 0,535 | 0,607 | Δ > 0 ✅ (+0,071) |
| Profit factor | 1,609 | 1,751 | +0,10 abs ✅ · +5% rel ✅ (+8,8%) |
| Max drawdown (R) | 6,258 | 6,258 | **−10% rel ❌ (0,0%)** |
| IC95 del Δ | — | `null` | límite inferior > 0 ❌ |

⚠️ **Ojo con esto:** el criterio de drawdown es el que va a decidir. En el estudio
histórico con costos base, el DD bajó de 77,8R a 70,8R = **−9,0%**, es decir **falla el
umbral del 10% por un punto**. Solo lo cumple bajo costos `hard` (−13,3%) y `extreme`
(−21,7%). Esto hay que mirarlo de frente ahora, no cuando lleguen los datos (§7.1).

#### `HYP-CANDLE-002-SHADOW` — 🔴 cero registros

```
Cohorte abierta: 2026-08-04 00:56:09Z
eligible_records: 0 · patterns: 0 · closed_with_pattern: 0
```

**Este es el hallazgo más grave del laboratorio.** La cohorte se abrió el 04-ago a las
00:56 — es decir, **después** de que la fuente se congelara el 03-ago a las 18:15. Lleva
dos días completos corriendo cada 5 minutos y **no ha capturado un solo registro en toda su
vida**. Su archivo de salida se reescribe puntualmente, así que el panel lo marca `fresh`.

Y hay un segundo problema, independiente del anterior: **la aritmética no cierra.**

- El protocolo exige **30 patrones cerrados** + 100 controles pareados + 12 semanas.
- La frecuencia histórica del patrón es **2,12%** (98 patrones en 4.633 setups).
- El diario resuelve ~5 setups/día (~10 si se cuentan todos los generados).

| Ritmo | Patrones/día | 30 patrones en |
|---|---:|---|
| 5 setups resueltos/día | 0,106 | **283 días (~9,3 meses)** |
| 10,4 setups/día | 0,220 | **136 días (~4,5 meses)** |

O sea: aunque se arregle el cableado hoy, **el mínimo de 12 semanas no es el que manda —
manda el de 30 patrones, que está entre 4,5 y 9 meses.** Tal como está planteado, este
estudio no da veredicto en 2026.

#### `HYP-COST-003-TELEMETRY` — 🔴 bloqueado estructuralmente

```
n_records: 0 · closed_with_confirmed_fees: 0 · entries_with_activation_reference: 0
status: collecting_insufficient_coverage · weeks_elapsed: 0,63
```

Necesita **comisiones confirmadas de operaciones reales**. El bot está inerte y `live:false`,
y el propio módulo ya deja constancia de que *"Testnet es diagnóstico y no satisface el
mínimo"*. **No es que vaya lento: no puede avanzar nunca en la configuración actual.**
Está reportado como `collecting` cuando en rigor es `blocked`.

#### Colector prospectivo del lab de trading — 🟠 congelado

`nexux-trading-intelligence-lab/datasets/prospective/events.jsonl`: 145 eventos, todos del
backfill del 04-ago 18:05. Desde entonces, `written: 0` en cada ciclo. Misma causa raíz.

### 5.3 El monitoreo miente

`modules/hypothesis_lab/module.py:245`:

```python
def health(self):
    statuses = {item["status"] for item in state["observers"].values()}
    return {"status": "ok" if statuses == {"fresh"} else "degraded", ...}
```

`_freshness()` mide **la antigüedad del archivo de salida**, no si entró algún dato. Los
tres observadores reescriben su JSON puntualmente sin capturar nada → los tres salen
`fresh` → el módulo reporta `ok`. Por eso `/health` devuelve `"status": "ok"` para el
laboratorio mientras dos de sus tres cohortes están en cero.

Justo es decir que el `state` **sí** expone la verdad, si uno la va a buscar:

```json
"sources": {
  "setups":       {"status": "stale", "age_seconds": 219160},
  "main_ledger":  {"status": "stale", "age_seconds": 834393},
  "testnet_ledger": {"status": "stale", "age_seconds": 719186}
}
```

Pero eso no llega a `health()` ni dispara nada.

---

## 6. Hallazgos por severidad

| # | Sev | Hallazgo |
|---|---|---|
| 1 | 🔴 P0 | Los 3 observadores y el colector prospectivo leen `nexux/data`, muerto hace 2,5 días. La recolección forward está detenida. |
| 2 | 🔴 P0 | `HYP-CANDLE-002` lleva 0 registros desde que nació. Y su mínimo de 30 patrones necesita 4,5–9 meses al ritmo actual. |
| 3 | 🔴 P0 | El BOT está inerte por falta de llaves: no ejecuta ni en papel. No hay forward-test desde el 27-jul. |
| 4 | 🟠 P1 | `health()` del laboratorio reporta `ok` con cohortes en cero: mide frescura del archivo, no progreso de la muestra. |
| 5 | 🟠 P1 | `HYP-COST-003` está bloqueado estructuralmente, pero se reporta como `collecting`. |
| 6 | 🟠 P1 | El fork en producción va 4 commits atrás: el panel muestra 6 estudios de 8. |
| 7 | 🟠 P1 | 12 commits sin pushear en la rama que está en producción → viola la REGLA #1 del CLAUDE.md. |
| 8 | 🟡 P2 | El watchdog del bot no corre; su último ciclo fue hace 33 h. |
| 9 | 🟡 P2 | `tests/test_bot.py` escribe en `data/bot_watchdog.json` de producción. |
| 10 | 🟡 P2 | `~/Library/LaunchAgents/com.hugo.nexus.plist` apunta a `/Users/hugh/Nexux`, que no existe. |
| 11 | 🟡 P2 | Dos posiciones `dry` abiertas desde el 27-jul, huérfanas. |
| 12 | ⚪ P3 | Journal, CoinSignals y CoinGlass sin datos ni colector. |

---

## 7. Propuesta: cómo implementar los candidatos

Dos estudios están en estado `candidate`: **HYP-EXIT-002** y **HYP-CANDLE-001**. Ninguno
de los dos tiene hoy evidencia suficiente para promoverse, y la propuesta no es forzarlos:
es **construir el camino para que puedan promoverse**, y tener el código listo y probado
para el día en que la evidencia llegue o no llegue.

### Paso 0 — Destapar la cañería (sin esto, nada de lo demás sirve)

Antes de tocar cualquier hipótesis: **un solo directorio de datos canónico.**

Los cuatro procesos apuntan a `crisol/nexux/data`; el servidor escribe en
`crisol/nexux-command-center/data`. Hay que unificarlo — o repuntando los plists, o dejando
`nexux/data` como symlink al directorio vivo. Prefiero **repuntar los plists**: un symlink
esconde el problema y el próximo cambio de repo lo vuelve a romper en silencio.

Junto con eso:
- Mergear los 4 commits de research de `nexux/main` en la rama del command-center, para que
  el panel muestre los 8 estudios.
- Pushear los 12 commits pendientes (REGLA #1).

**Decisión que te toca a ti:** el apagón del 03 al 06-ago deja tres días sin datos dentro
de una cohorte cuyo protocolo dice `rule_changes_after_start: forbidden`.

- **Recomiendo: conservar la cohorte y registrar el hueco** en el manifiesto como
  *coverage gap* documentado. El protocolo cuenta **semanas de calendario**, no días con
  datos, y el bootstrap por bloques semanales tolera semanas vacías. Costo: honestidad
  explícita en el reporte.
- La alternativa —reiniciar limpio— empuja la fecha de veredicto de **24-oct a fines de
  enero 2027**. Tres meses por tres días de hueco me parece un precio malo.

### 7.1 HYP-EXIT-002 — protección del runner a 3R

**Qué dice la evidencia hoy.** Histórico (n=4.633, costos base): avg R 0,7277 → 0,7421
(**Δ +0,0144**, IC95 [−0,045; +0,070], p=0,63, p_holm=0,63) · PF 1,768 → **2,019** ·
DD 77,8R → 70,8R · WR 20,8% → 18,5%. Forward (n=14, sin valor): Δ +0,071R, PF +8,8%,
DD sin cambio.

Es el **único** de las cinco variantes de salida que no empeora la expectativa: las otras
cuatro tienen Δ negativo y tres sobreviven a Holm con signo malo. Pero su propio IC95
incluye cero, así que "no empeora" es literalmente todo lo que se puede afirmar.

**Propuesta en tres movimientos:**

**(a) Escribir el código ahora, apagado.** — *deploy dark*

Añadir a `modules/bot/executor.py` un modo de salida `protect_3r` detrás de una bandera de
config `bot.exit_protect_3r`, **por defecto `false`**. Cuando una posición alcanza 3R, mueve
el SL a break-even neto (entrada + costos). Requisitos:

- **Reutilizar la misma fórmula** que ya calcula `stop_protected_price` en
  `research/hypothesis_lab/shadow_exit.py`. Si la sombra y la producción calculan el stop
  por separado, van a divergir y la evidencia deja de aplicar al código real.
- Un test que verifique que **con la bandera apagada el comportamiento es idéntico** al
  actual, byte a byte en el libro.
- Un test de la transición a 3R con el SL movido, sobre un fixture del propio cohorte.

Por qué ahora: cuando llegue el 24-oct no quieres estar escribiendo un ejecutor nuevo
contra la presión de un resultado positivo. Quieres apretar una bandera que lleva tres
meses probada.

**(b) Cerrar antes el flanco del drawdown.**

El criterio de promoción exige **−10% de drawdown relativo**. El estudio histórico con
costos base entrega **−9,0%**: falla por un punto. Solo pasa con costos `hard` (−13,3%) y
`extreme` (−21,7%). El forward hoy va en **0,0%**.

Esto es una trampa esperando: si dentro de tres meses el DD queda en −9%, va a ser muy
tentable decir "bueno, nueve es prácticamente diez". **Hay que decidir ahora, antes de ver
más datos**, una de dos:

1. El umbral del 10% se mantiene tal cual, y −9% es descarte. Limpio, y consistente con
   `rule_changes_after_start: forbidden`.
2. Se registra explícitamente —y **hoy**, con timestamp y hash— que el criterio de DD se
   evalúa bajo el escenario de costos `hard`, que es el más cercano a la fricción real que
   mostró el libro (48,93 USD de comisiones en 27 operaciones).

Yo iría por la **(1)**. La (2) es defendible pero huele a mover el arco, y el principio del
producto es honestidad sobre todo.

**(c) La promoción es automática o no es.**

Que la bandera solo se pueda encender cuando `decision.status == "promote"`, es decir
cuando los seis criterios se cumplen **y** el límite inferior del IC95 supera cero. Nada de
promoción a ojo. Si el 30-ene-2027 no cumple, se descarta y se escribe por qué.

**Fecha realista de veredicto: 24-oct-2026** (si la cañería se destapa esta semana).

### 7.2 HYP-CANDLE-001 — impulso, absorción y reclaim

**Qué dice la evidencia hoy.** Con patrón: **+2,93R**, PF 5,26, WR 40,8% (n=98). Sin patrón:
+0,68R, PF 1,71, WR 20,3% (n=4.535). Contra controles del mismo par/TF/dirección/mes, el
exceso es **+1,39R, IC95 [+0,13; +2,70]** — no cruza cero. Y no se explica por targets más
grandes (RR medio 13,94 vs 14,03).

Pero: **esperar la confirmación para entrar cuesta −2,80R por operación pareada**, IC95
[−3,95; −1,86], p≈0,001. El WR no cambia; lo que se destruye es el payoff.

**La lectura correcta es la que ya hizo el estudio: el patrón es información, no gatillo.**

**Propuesta en cuatro movimientos:**

**(a) Arreglar la factibilidad, que hoy no existe.**

Como está, el estudio no da veredicto hasta 2027 (§5.2). Tres opciones, y una es mala:

| Opción | Efecto | Veredicto |
|---|---|---|
| Ampliar universo: sumar DOGE y BNB al motor de setups | ~+40% de throughput | 3–6,5 meses |
| Sumar 15m a los TF elegibles | Mucho más volumen | ❌ **rompe el protocolo congelado** — exigiría un `HYP-CANDLE-003` nuevo |
| Bajar el mínimo de 30 patrones | Veredicto rápido | ❌ **no** — es exactamente lo que el protocolo prohíbe |

**Recomiendo la primera, y aceptar el horizonte.** Inteligencia ya sigue DOGE; el motor de
setups ya cubre 6 instrumentos. Es el único aumento de muestra que no toca la definición
congelada. Y con eso, asumir que este estudio cierra en el **primer trimestre de 2027**, no
antes. Escribirlo así en el ROADMAP es mejor que fingir que llega en 12 semanas.

**(b) Implementar lo que el estudio ya autoriza: una columna informativa.**

El propio reporte define la siguiente etapa: *"columna shadow forward que registre
presencia, hora de confirmación y resultado original, sin modificar órdenes ni P&L
oficial"*. El observador ya existe (`candle_reversal_shadow.py`) — lo que falta es que se
vea. Propongo:

- Un badge en la ficha del setup del diario: **patrón presente / ausente**, con la hora de
  confirmación, etiquetado **"informativo · no es señal"**.
- Que no toque `setups.json` ni el libro. El propio protocolo del observador lo restringe:
  `writes_allowed` es un único archivo, `setups_store_mutation: false`.

Esto sirve dos propósitos: te deja mirar el patrón en vivo durante meses (que es la mejor
forma de saber si la definición congelada realmente captura lo que viste en las capturas),
y no compromete nada.

**(c) Pre-registrar HOY la hipótesis de aborto — antes de mirar los datos.**

El reporte dice, textual, que evaluar el patrón como regla de aborto *"requiere una
hipótesis y un protocolo separados antes de mirar resultados"*. Ese momento es **ahora**,
mientras la cohorte forward está en cero y nadie puede acusarse de haber espiado.

Propongo pre-registrar **`HYP-CANDLE-004 — no abortar con patrón presente`**: cuando el
patrón alineado aparece dentro de las 3 velas posteriores al toque, ¿la operación original
sobrevive mejor que su control pareado? Con su propio SHA-256, su propio mínimo de muestra
y su propio criterio de descarte, registrado antes de que exista un solo dato.

Si no se hace ahora, en seis meses este análisis va a ser post-hoc y no va a valer nada.

**(d) Nunca como gatillo de entrada.** Eso ya está resuelto: −2,80R, p≈0,001, y peor
(−3,09R) justo en el régimen `rr >= 5` que es el que usa el bot. Cerrado.

### 7.3 Lo transversal: un watchdog de recolección

Nada de lo anterior sobrevive si la cañería se vuelve a romper en silencio durante 2,5 días.

Cambiar `health()` del laboratorio para que un observador sea `degraded` cuando **su conteo
de registros no se mueve en N horas**, no solo cuando su archivo envejece. Y subir el
`sources.stale` que ya se calcula al health, que hoy se queda encerrado en el `state`.

Es el arreglo más barato de todo este informe y es el que hubiera evitado el hallazgo #1.

---

## Cierre

El rigor científico del laboratorio es real y poco común: pre-registro, Holm, bootstrap por
bloques, bloqueos declarados, estudios que se auto-limitan. Eso está bien construido.

El problema no es metodológico, es de **plomería**: el sistema se mudó de repositorio y la
mitad de las tuberías quedaron conectadas a la casa vieja. Dos de las tres cohortes forward
llevan días o su vida entera en cero, y el panel dice `ok` porque mide la fecha del archivo
en vez del contenido.

Y hay una verdad incómoda de fondo: **la única fase con dinero real (23-jun → 01-jul) cerró
en −129 USD con PF 0,745**, y `HYP-COST-003` —el estudio que debería explicar cuánto de eso
fue fricción de ejecución— no puede avanzar mientras el bot esté inerte. Eso no es un bug
que se arregle repuntando un plist: es una decisión tuya sobre si el bot vuelve a operar y
bajo qué condiciones.
