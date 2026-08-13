# Bot — reporte de escenarios Binance Demo

**Fecha:** 2026-08-13

**Resultado mecanico:** `5/5`, pendiente de revision humana

**Decision operativa:** `NO LIVE`

## Alcance y aislamiento

- Checkout dirigido en VPS: `/home/hugo/Nexus-demo-readiness`.
- Commit ejecutado al cierre: `54f5194243b4fe14504d2fa6e6d78ee26ceba5ee`.
- Endpoint exigido: `https://demo-fapi.binance.com`.
- Datos: `/home/hugo/Nexus/data/testnet`.
- Produccion permanecio en `55d9b6dd36a47fa1bd40d38b510fba609811d71f`.
- `nexus.service` no fue reiniciado y conservo el mismo PID.
- Configuracion productiva: `live=false`; kill-switch productivo presente.
- El kill-switch Testnet se uso solo durante los ensayos y fue retirado al terminar.

El runner no cargo `trade.env`, no acepto el endpoint productivo y se nego a operar
simbolos con exposicion preexistente. ADA, SOL y XRP quedaron planos y sin algo orders.
La posicion BTC SHORT `0,0001` es anterior a los ensayos y no fue modificada.

## Evidencia aprobada

| Escenario | Resultado | Artefacto | SHA-256 |
|---|---|---|---|
| Stop nativo confirmado | passed | `1786650293301-native_stop_confirmed-0ef491641e70.json` | `0ef491641e701eaabf17e89972fe50433c3b2c92758da61af9d3897e497515d1` |
| Parcial y stop reajustado | passed | `1786650293306-partial_stop_resized-c538ae96e01d.json` | `c538ae96e01d2e88bf4be5c8f6c7626e4d9ff6f9cf841e72105d65e03a229804` |
| Timeout ambiguo resuelto HEDGE | passed | `1786650446474-hedge_ambiguous_resolved-06bb3f8a14e8.json` | `06bb3f8a14e8830291e9fc515180272f6989e2ba9ef17441cfd40a2e1d21968b` |
| Reinicio y reconciliacion | passed | `1786650503310-restart_reconciled-42d708a31255.json` | `42d708a3125565252cc90e8a79d3e2e9c3a1d495fde8d28f14ecc968e02022cc` |
| Stop nativo disparado | passed | `1786651277462-native_stop_triggered-d807af4b07b2.json` | `d807af4b07b29fe8653d309f113c8517ebd282265cb661370c5466b5d1ac8dc0` |

El stop real de XRP termino `FINISHED`, con `actualOrderId=3478303757`. `userTrades`
confirmo el mismo order ID como fill `SELL/LONG` por `14,9 XRP`; la posicion final fue
cero.

## Evidencia negativa preservada

No se eliminaron los intentos fallidos:

- `23b6e5e...`: un `CANCELED` se interpreto inicialmente como terminal. Fue invalidado
  inmediatamente mediante `3f21e002...`; el contrato ahora exige `TRIGGERED` o
  `FINISHED`, `actualOrderId` y fill del mismo ID.
- `934cd836...`: timeout honesto de 300 segundos con stop `NEW`; el runner limpio su
  propia posicion y dejo el escenario en `failed`.
- Un intento adicional fallo cerrado por lectura `None` inmediatamente despues del
  POST. Se agrego espera de consistencia solo al GET; el POST nunca se reenvia.

## Baseline de incidentes

El incidente ETH `native_stop_unconfirmed_fail_closed` es anterior a esta cohorte y
permanece visible. Su ID y fecha quedaron congelados como baseline. El gate permite
ese unico incidente historico y falla ante cualquier incidente adicional.

Estado final del validador:

```text
scenarios_passed=5
scenarios_failed=0
execution_ok=true
status=review
automatic_live=false
critical_execution_errors=1 (baseline historico)
```

## Interpretacion

Los cinco escenarios acreditan la maquinaria Demo que se queria ejercitar. No prueban
edge economico, rentabilidad neta ni suficiencia estadistica. El filtro operativo
`RR >= 5` conserva evidencia forward insuficiente y el costo medido sigue siendo una
barrera independiente. Por tanto, completar este gate no autoriza live.

Antes de reconsiderar live se mantiene la exigencia de una cohorte homogenea cercana
a 50 operaciones, riesgo objetivo fijo de `9 USD`, metricas netas e intervalos de
confianza predefinidos. Cambiar el riesgo inicia una cohorte nueva.
