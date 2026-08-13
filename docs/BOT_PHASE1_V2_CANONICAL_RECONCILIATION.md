# Reconciliacion canonica — Bot Fase 1 V2

**Fecha de lectura:** 2026-08-12
**Fuente:** `/home/hugo/Nexus/data/bot_trades.json` en `nexux-de`
**Commit desplegado durante la lectura:** `55d9b6dd36a47fa1bd40d38b510fba609811d71f`
**SHA-256 del libro:** `ff389904de6bbe74527ec6d9bad5e68c88ca6cc9997fe0a0a81fb41d16e19986`
**Phase ID:** `phase1_v2_2026-07-18`

Este documento registra una lectura reproducible del libro existente. No modifica,
completa ni reinterpreta operaciones. El archivo vivo del VPS sigue siendo la fuente
primaria; este documento fija el corte utilizado para la decision.

La copia local del libro quedo congelada despues de la operacion 13. No es una replica
autoritativa y no debe utilizarse para auditorias futuras. Toda medicion del libro debe
registrar maquina, ruta, timestamp, commit y SHA-256 de la fuente leida.

## Resultado reconciliado

- 20 operaciones V2 cerradas.
- 15 ganadoras y 5 perdedoras: 75% de win rate descriptivo.
- P&L neto registrado: `+91,8131 USD`.
- AvgR neto: `+0,385089R`, usando `pnl_usd / risk_usd_est` por operacion.
- Primera operacion cerrada: 2026-07-20 08:37:16 UTC.
- Ultima operacion cerrada: 2026-07-29 03:18:10 UTC.

La discrepancia `13 operaciones / +44,30 USD` queda explicada: corresponde
exactamente a las primeras 13 operaciones cerradas de este mismo libro (`+44,3049
USD`). Es un corte temporal anterior, no otra cohorte. El corte de 15 operaciones
arroja `+48,5600 USD`; el cierre final autorizado es el de 20 operaciones.

## Tabla canonica

| # | Cierre UTC | Setup ID | P&L USD | Riesgo ejecutado USD | R neto |
|---:|---|---|---:|---:|---:|
| 1 | 2026-07-20 08:37:16 | `BTC_USDT:1h:long:63833.0:1784431394` | +1,3185 | 8,83 | +0,149320 |
| 2 | 2026-07-21 00:42:54 | `ADA_USDT:1h:short:0.17:1784348450` | +6,4525 | 13,30 | +0,485150 |
| 3 | 2026-07-21 12:36:33 | `BTC_USDT:1h:short:65755.0:1784348442` | -11,2627 | 10,07 | -1,118441 |
| 4 | 2026-07-22 10:01:01 | `ADA_USDT:1h:short:0.17:1784651595` | -14,7918 | 13,53 | -1,093259 |
| 5 | 2026-07-23 14:02:42 | `ADA_USDT:1h:long:0.17:1784733687` | +3,4028 | 9,00 | +0,378089 |
| 6 | 2026-07-24 07:12:47 | `ADA_USDT:1h:short:0.17:1784762083` | +18,5173 | 14,88 | +1,244442 |
| 7 | 2026-07-24 07:33:43 | `XRP_USDT:1h:long:1.1:1784840482` | +13,2800 | 9,00 | +1,475556 |
| 8 | 2026-07-25 19:30:20 | `XRP_USDT:1h:long:1.09:1784617960` | +9,8864 | 9,75 | +1,013990 |
| 9 | 2026-07-26 13:45:16 | `BTC_USDT:1h:short:64485.25:1785047629` | -0,1362 | 9,00 | -0,015133 |
| 10 | 2026-07-26 23:30:50 | `XRP_USDT:1h:long:1.1:1785057506` | +8,4525 | 9,00 | +0,939167 |
| 11 | 2026-07-27 00:38:06 | `BTC_USDT:1h:long:63858.1:1784636555` | +12,0956 | 9,21 | +1,313312 |
| 12 | 2026-07-27 12:44:54 | `SOL_USDT:1h:short:76.47:1785114100` | +7,7214 | 9,00 | +0,857933 |
| 13 | 2026-07-27 14:50:53 | `BTC_USDT:1h:short:64485.25:1785163100` | -10,6314 | 6,69 | -1,589148 |
| 14 | 2026-07-27 20:45:17 | `XRP_USDT:1h:long:1.09:1785171608` | +2,0242 | 9,00 | +0,224911 |
| 15 | 2026-07-27 22:02:12 | `SOL_USDT:1h:long:75.03:1785171982` | +2,2309 | 9,00 | +0,247878 |
| 16 | 2026-07-27 22:40:53 | `SOL_USDT:1h:long:75.08:1785189773` | -10,4297 | 9,00 | -1,158856 |
| 17 | 2026-07-28 17:49:08 | `ETH_USDT:1h:short:1922.11:1785222823` | +11,8858 | 8,99 | +1,322113 |
| 18 | 2026-07-28 23:38:56 | `SOL_USDT:1h:short:74.0:1785261667` | +10,7777 | 9,00 | +1,197522 |
| 19 | 2026-07-28 23:48:36 | `ETH_USDT:1h:short:1913.38:1785261665` | +1,7856 | 8,99 | +0,198621 |
| 20 | 2026-07-29 03:18:10 | `ADA_USDT:1h:short:0.17:1785162701` | +29,2337 | 17,95 | +1,628618 |

## Limites de interpretacion

1. El trade 20 fue cerrado manualmente para congelar la fase, como ya declara el
   runbook. No se presenta como salida automatica.
2. La cohorte no fue homogenea en riesgo ejecutado: `risk_usd_est` varia entre
   `6,69` y `17,95 USD`. En particular, el trade 20 uso `17,95 USD`, no `9 USD`.
3. El resultado satisface el registro administrativo de 20 operaciones, pero no
   demuestra edge. Los intervalos de confianza y la evidencia forward siguen siendo
   obligatorios para cualquier decision posterior.
4. Ningun resultado de esta cohorte autoriza `live:true`.

## Regla para cohortes futuras

La cohorte economica siguiente debe congelar antes de comenzar:

- politica y version de codigo;
- riesgo objetivo por operacion;
- definicion neta de R y costos;
- fecha de inicio y criterio de inclusion;
- hash o snapshot inmutable del libro evaluado.

Cambiar el riesgo objetivo inicia una cohorte nueva.
