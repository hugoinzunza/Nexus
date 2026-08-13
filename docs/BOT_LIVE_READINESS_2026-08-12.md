# Bot — estado de preparacion para live

**Corte:** 2026-08-12
**Decision:** `LIVE NO AUTORIZADO`
**Metodo:** lecturas locales y remotas; cero ordenes; cero cambios en VPS.

## Provenance de esta revision

- Fuente canonica del libro: `/home/hugo/Nexus/data/bot_trades.json` en `nexux-de`.
- La copia local de `data/bot_trades.json` no es fuente auditable: puede ser un espejo
  incompleto o congelado y no debe utilizarse para evaluar cohortes.
- Entorno de pruebas: `Mac-mini-de-Hugo.local`.
- Worktree: `/Users/hugh/crisol/nexux-command-center`.
- Commit local: `3e9f034bff7058c72a978e943e4c15d11527ef87`.
- Commit observado en VPS: `55d9b6dd36a47fa1bd40d38b510fba609811d71f`.

Resultados reproducidos localmente:

| Alcance | Comando | Resultado |
|---|---|---|
| Bot principal | `python3 -m pytest -q tests/test_bot.py` | 66 passed |
| Suite contractual `tests/` | `python3 -m pytest -q tests` | 759 passed, 2 warnings |
| Foco Bot + Testnet | `python3 -m pytest -q tests/test_bot.py tests/test_bot_testnet_worker.py tests/test_bot_testnet_regressions.py` | 84 passed |
| Descubrimiento desde raiz | `python3 -m pytest -q` | 1032 passed, 4 failed, 2 warnings |

La ejecucion desde raiz incluye `research/test_*.py`; sus cuatro fallos fueron uno por
semantica de dataset V1/V2 y tres por ausencia de
`research/vacio_disponible_trades.json`. No pertenecen a `tests/` ni a este cambio.
Por tanto, no se deben comparar cifras de suites sin conservar comando, worktree,
commit y maquina.

## Seguridad observada

- Configuracion del VPS: `modules.bot.live = false`.
- Kill-switch productivo: presente.
- Posiciones reales productivas segun watchdog: 0.
- `nexus-watchdog.service`: enabled y active desde 2026-07-31 06:01:57 UTC.
- Watchdog systemd: `WatchdogSec=120s`, 0 reinicios reportados y heartbeat vigente.
- Ultimo ciclo observado: 2026-08-13 02:45:21 UTC.
- El estado conserva cinco fallas de lectura historicas (rate limit, DNS, reloj y
  timeouts). Son fail-closed: en esos ciclos no actuo.

La afirmacion previa "el watchdog no esta desplegado" queda refutada para el VPS. No
existe LaunchAgent en el Mac, pero el watchdog productivo corresponde al VPS y alli si
esta desplegado. Esto no acredita todavia su cierre real de emergencia.

## Cohorte dry

La reconciliacion completa esta en
`docs/BOT_PHASE1_V2_CANONICAL_RECONCILIATION.md`.

- Libro canonico: 20 V2 cerradas, `+91,8131 USD`.
- `13 / +44,30 USD` es el corte de las primeras 13 filas del mismo libro.
- El riesgo ejecutado vario entre `6,69` y `17,95 USD`.
- El trade 20 uso `17,95 USD` y tuvo cierre manual de fin de fase.

La discrepancia contable queda cerrada. La heterogeneidad de riesgo y la insuficiencia
estadistica permanecen abiertas; esta cohorte no prueba edge.

## Estado de Binance Demo/Testnet

Lectura causal efectuada contra `https://demo-fapi.binance.com`:

- cuenta HEDGE confirmada;
- balance virtual: `4.900,69381525 USDT`;
- 25 operaciones en el libro: 24 cerradas y 1 abierta;
- P&L cerrado registrado: `-75,7099 USD`;
- 24 cierres con P&L reconciliado;
- una posicion BTC SHORT abierta por `0,0001 BTC`;
- stop nativo `NEW`, algo ID `1000000164885625`, por `0,0001 BTC` a `64.476,44`;
- el libro registra un parcial previo de `0,0405 BTC`, dejando `0,0001 BTC`.

## Gate de escenarios

| Escenario | Estado | Evidencia |
|---|---|---|
| Apertura y stop nativo confirmado | Observado | Posicion BTC SHORT `0,0001`; stop Binance `NEW` por la misma cantidad. |
| Parcial y stop reajustado | Observado | Parcial `0,0405`; remanente y stop coinciden en `0,0001`. |
| Stop nativo disparado realmente | Pendiente | No existe artefacto que vincule trigger, cierre y libro. |
| Reinicio y reconciliacion | Pendiente | No existe ensayo dirigido con estado antes/despues. |
| Timeout ambiguo resuelto en HEDGE | Pendiente | No existe ensayo dirigido trazable en Demo. |

`Observado` no equivale aun a `passed` en el marker operacional: falta preservar un
artefacto de ejecucion versionado para cada escenario. El gate permanece `2/5` en
terminos de evidencia disponible y `0/5` en el marker formal actual.

## Bloqueo de despliegue

El VPS permanece en `55d9b6dd36a47fa1bd40d38b510fba609811d71f`. La copia local
contiene fixes posteriores y esta en `3e9f034bff7058c72a978e943e4c15d11527ef87`,
ademas de cambios no relacionados del Command Center. No se debe ejecutar el smoke
dirigido ni actualizar el VPS mezclando ese arbol.

Antes de los tres escenarios pendientes se requiere un commit aislado y revisado de
los fixes del bot, seguido de despliegue controlado solo al worker Demo. La instancia
real debe conservar `live:false` y el kill-switch.

## Economia

La evidencia forward comunicada para el filtro operativo `RR >= 5` permanece:

- `n=59`;
- avgR bruto `-0,025R`;
- PF `0,95`;
- IC95 `[-0,306; +0,267]`;
- friccion medida aproximada `0,22R` por operacion a riesgo de `9 USD`.

El gate mecanico de Testnet no resuelve este bloqueo economico. Incluso con los cinco
escenarios aprobados, live seguira bloqueado hasta una nueva revision de evidencia.

## Decision

`NO LIVE`.

Siguiente accion segura: aislar y revisar el commit del bot, desplegar exclusivamente
en Demo y ejecutar los tres escenarios pendientes con artefactos trazables. La cohorte
economica futura debe mantener riesgo objetivo fijo de `9 USD`; cambiarlo inicia una
cohorte nueva.

## Runner dirigido de escenarios

El runner `deploy/binance_testnet_scenarios.py` no forma parte del worker automatico.
Cada invocacion exige explicitamente `NEXUS_TESTNET=1`, el endpoint exacto
`https://demo-fapi.binance.com`, una cuenta HEDGE y un `--data-dir` terminado en
`/testnet`. No carga `trade.env`, no acepta el endpoint productivo y se niega a tocar
un simbolo que ya tenga posicion u orden algo.

Los tres comandos pendientes son:

```text
native-stop-triggered
restart-reconciled
hedge-ambiguous-resolved
```

`observe-current` es un cuarto comando estrictamente read-only: acredita los dos
escenarios ya observados solo cuando posicion, libro, parcial y stop nativo coinciden.
No cambia leverage ni envia ordenes.

`baseline-current-incidents` congela de forma explicita los incidentes anteriores al
inicio de la cohorte. Conserva sus IDs y fechas en el marker y se niega a incorporar
un incidente posterior a `started_at`; por tanto, cualquier fallo nuevo mantiene el
gate en estado `failed`.

Cada resultado se materializa en `scenario_evidence/` como JSON canonico inmutable.
`live_readiness.json` conserva solo ruta y SHA-256; `BotSync` vuelve a leer y verificar
ambos antes de contar el escenario. Texto libre, archivos adulterados o referencias
fuera de ese directorio no acreditan el gate.

El escenario de stop disparado exige simultaneamente estado `TRIGGERED` o `FINISHED`,
`actualOrderId` no vacio, posicion en cero y un fill de cierre del mismo order ID y
`positionSide`. Un stop `CANCELED` seguido de un cierre manual no puede acreditarlo.
