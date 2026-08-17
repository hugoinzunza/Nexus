# Bot3.v2 — Protocolo pre-registrado (submodelo causal single-entry H4→M15)

**Fecha de congelamiento:** 2026-08-17
**Estado:** `PRE-REGISTRADO / NO IMPLEMENTADO / PENDIENTE CONFORMIDAD CODEX`
**Base normativa incorporada por referencia:**
`docs/BOT3_V2_DISENO_CONTRACTUAL.md` revisión 3, SHA-256
`5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`
(verificado por Codex). Todo lo del diseño rev.3 es parte de este protocolo;
las cláusulas siguientes lo CIERRAN y, ante conflicto, prevalecen.

El `contrato_hash` usado en `candidate_id`/`order_id`/`trade_id` es el
SHA-256 de ESTE archivo tal como quede congelado.

---

## Cláusulas normativas finales

### CF-1. Rango rector sin ruptura opuesta previa → abstención

El tramo origen del rango rector se define EXCLUSIVAMENTE entre la última
ruptura H4 opuesta previa y la ruptura vigente. Si dentro de la serie
disponible no existe ruptura opuesta previa, **no hay rango** (abstención
registrada como `rango_sin_origen`). Queda prohibido el respaldo "inicio de
la ventana causal": la profundidad histórica cargada no puede alterar el
strong.

### CF-2. Precios de salida con gap (vela posterior al fill)

Sea la posición larga con stop `S` y target `T` (corto: espejo exacto), y
`x` la vela M15 evaluada:

- `o[x] ≤ S` (abre más allá del stop) → salida por STOP con precio base
  `o[x]` (nunca `S`: ese precio no se transitó).
- si no, `o[x] ≥ T` (abre más allá del target) → salida por TP con precio
  base `o[x]` (gap a favor del límite).
- si no, `l[x] ≤ S` → STOP con precio base `S`; si además `h[x] ≥ T` en la
  misma vela → STOP (vela ambigua, regla vigente).
- si no, `h[x] ≥ T` → TP con precio base `T`.

Precio de EJECUCIÓN: STOP → `base × (1 − 0,0005)` largo / `× (1 + 0,0005)`
corto (slippage 0,05%); TP → `base` (sin slippage, orden límite).

### CF-3. Unidad R = riesgo PLANIFICADO

El tamaño de la posición queda fijado al crear la orden con el riesgo
planificado `|E − S|` (E = nivel de la orden). El R realizado usa SIEMPRE ese
denominador:

```text
R = PnL_neto_en_precio / |E − S|
```

Un fill favorable al open mejora el numerador (mejor precio de entrada), pero
NO redefine la unidad de riesgo. `−1R` corresponde exactamente a la pérdida
planificada al colocar la orden, antes de costos.

### CF-4. Ecuaciones exactas de costos y devengo

Con `dir = +1` largo / `−1` corto, `P_in` = precio de fill, `P_out` = precio
de ejecución de salida (CF-2):

```text
PnL_bruto   = dir × (P_out − P_in)
fee_in      = 0,0002 × P_in                    (entrada, límite/maker)
fee_out_tp  = 0,0002 × P_out                   (salida TP, límite/maker)
fee_out_sl  = 0,0005 × P_out                   (salida STOP, mercado/taker)
funding_k   = 0,0001 × C_k                     (por devengo k)
PnL_neto    = PnL_bruto − fee_in − fee_out − Σ_k funding_k
R           = PnL_neto / |E − S|
```

- **Devengo de funding:** en cada timestamp estándar 00:00, 08:00 y 16:00 UTC
  estrictamente posterior al fill y anterior o igual a la salida. `C_k` = el
  CIERRE de la vela M15 que contiene el timestamp k. El signo es siempre un
  cargo (conservador), independiente del lado.
- El slippage del STOP ya está dentro de `P_out` (CF-2); no se descuenta dos
  veces. El spread queda subsumido en ese slippage.
- **Filtro RR ≥ 2 (a priori):**
  `RR_a_priori = (|T − E| − 0,0002×E − 0,0002×T) / |E − S|` — solo costos
  deterministas; el funding no entra al filtro.

### CF-5. Recorrido de velas de la orden (límites inclusivos)

`m` recorre cronológicamente TODAS las velas M15 con índice
`m ∈ [idx_alta + 1, idx_deadline]`, ambos inclusive, donde `idx_alta` es la
vela cuyo CIERRE disponibilizó la orden y `idx_deadline` es la última vela
cuyo cierre ocurre a más tardar 64 velas M15 después del cierre de la vela
del toque H4. La primera vela que satisfaga una condición de §4.5 resuelve;
si ninguna lo hace, `confirmada_sin_fill`. La resolución post-fill recorre
`x ∈ [m_fill + 1, ∞)` (la vela del fill solo puede producir STOP, §4.5),
sin límite de tiempo salvo cierre del experimento.

---

## Parámetros congelados (todos `[U0]` salvo nota)

| Parámetro | Valor |
|---|---|
| Universo | ADA, BNB, BTC, DOGE, ETH, SOL, XRP (USDT-PERP, klines Binance) |
| Fila del curso | zona H4 → confirmación M15 (única) |
| STRUCT_PIV / INT_PIV | 8 / 3 |
| Expiración dirección H4 | 180 velas H4 |
| TTL zona H4 | 180 velas H4 desde `available_at` |
| Deadline total toque→fill | 64 velas M15 |
| Ventana iBOS | ≤48 velas M15 desde el toque |
| Buffer SL | 0,1% |
| RR neto mínimo (a priori) | 2,0 (compatible S06, no demostrado) |
| Fees | maker 0,02% · taker 0,05% |
| Slippage STOP | 0,05% |
| Funding | 0,01% por devengo de 8 h, siempre cargo |
| Corte | 50 cierres totales o 2026-12-31, con cobertura ≥8 semanas ISO |
| Bootstrap | bloques = semanas ISO, 10.000 réplicas, semilla 20260817, IC 95% |
| Redondeo comparaciones | 6 decimales |

## Reglas de vigencia

1. Este texto se congela ANTES de implementar. Cambiar cualquier valor o
   cláusula = protocolo v3 y cohorte nueva desde cero.
2. La implementación se acepta solo si pasa los gates del diseño rev.3 §11
   (invariancia por prefijo en ventana real >300 zonas, tests discriminantes,
   determinismo de arbitraje, ledger sin duplicados) y la re-auditoría
   completa de Codex.
3. Frontera forward = primer pull exitoso del recolector posterior al
   despliegue verificado. Todo lo anterior es backtest y se reporta aparte.
4. Bot3.v1 permanece suspendido; ninguna métrica v1 se reutiliza como
   evidencia de v2.
5. Un resultado positivo NO autoriza Bot, Testnet ni Live: cualquier paso a
   dinero real exige protocolo propio y decisión explícita de Hugo.
6. Evaluación ÚNICA al corte; octubre es checkpoint informativo, sin valor
   decisional.

## Secuencia restante (orden aprobado por Hugo)

Conformidad de Codex sobre este protocolo → implementación (paso 5) →
re-auditoría completa (paso 6) → despliegue verificado (paso 7) → cohorte
desde cero (paso 8).
