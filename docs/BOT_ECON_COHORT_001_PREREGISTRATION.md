# ECON-COHORT-001 — Pre-registro

**Estado:** congelada; recoleccion dry desde `2026-08-15 04:30 UTC`.

**Decision vigente:** `NO LIVE`. Ningun resultado activa live automaticamente.

## Pregunta

¿La politica congelada del bot conserva evidencia economica neta suficiente en una
cohorte forward homogenea como para habilitar una nueva revision humana?

## Regla de parada

La cohorte se cierra al alcanzar exactamente 50 operaciones elegibles cerradas o el
`2026-10-10 04:30 UTC`, lo que ocurra primero. Se evalua una sola vez. Durante la
recoleccion solo se publican conteos operativos; mirar o publicar metricas acumuladas
de resultado antes del cierre esta prohibido.

Si llega la fecha con menos de 50 cierres, el dictamen es `evidencia insuficiente / NO
LIVE`. No se extiende la fecha ni se espera una racha favorable.

## Politica congelada

El snapshot completo esta en `config/bot_econ_cohort_001.policy.json`. Su SHA-256
canonico es `6d1b2d7a045e98f6e95bb4a0b8a5faca5efa038b78bf26ce50733ea7ff30820a`.
Incluye filtros, pares, guardas, leverage, limites, watchdog y riesgo objetivo fijo de
`9,00 USD`. Toda modificacion, no solo el riesgo, invalida la cohorte y exige un ID
nuevo. El ejecutor falla cerrado para aperturas si el snapshot deja de coincidir.

Cada apertura registra `economic_cohort_id`, `economic_protocol_sha256` y
`economic_policy_sha256`. No existe inclusion retrospectiva.

## Costos

El R neto dry se define como `pnl_usd / risk_usd_est`; `pnl_usd` ya resta las
comisiones estimadas de entrada, parciales y salida con el `fee_rate` congelado.

Se reutiliza la unica telemetria causal existente, HYP-COST-003, identificada por
SHA-256 `fe632337e675b36256741a65ec5820f4bb1d08f0bce5d9346a712a1629ba2148`.
No se crea un colector paralelo. Su contrato excluye operaciones dry: por tanto sus
campos `entries_with_timely_spread` y `closed_with_confirmed_fees` sirven como
calibracion externa solo cuando existan observaciones elegibles, nunca se mezclan con
esta cohorte ni se presentan como costos confirmados de ella. La ausencia permanece
visible.

## Gate pre-registrado

Una revision de promocion requiere simultaneamente:

- exactamente 50 cierres elegibles;
- avgR neto puntual mayor a `+0,20R`;
- limite inferior IC95 del avgR neto mayor a `0`;
- win rate puntual al menos `55%`;
- limite inferior Wilson IC95 del win rate al menos `55%`;
- Profit Factor neto mayor a `1,0`;
- cero incidentes criticos de ejecucion;
- revision humana explicita de la cobertura y limitaciones de costos.

Cumplir habilita solamente revision humana. No cumplir cualquiera conserva `NO LIVE`.

## Watchdog — escenario 6

Queda registrado como ensayo opcional y no bloqueante para esta cohorte: en Binance
Demo, abrir una posicion protegida, cancelar deliberadamente el stop nativo, dejar que
el precio cruce el SL y verificar que `nexus-watchdog` cierre la cantidad real, por
simbolo y lado, con orden idempotente y rastro auditable. No se ejecuta como parte de
este inicio y no cuenta dentro de los cinco escenarios ya aprobados.
