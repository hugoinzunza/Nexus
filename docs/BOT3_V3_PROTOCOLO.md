# Bot3.v3 — Protocolo pre-registrado CANDIDATO (submodelo single-entry H4→M15)

**Fecha:** 2026-08-17
**Estado:** `CANDIDATO / NO IMPLEMENTADO / PENDIENTE CONFORMIDAD CODEX`
**Antecedentes incorporados por referencia (prevalece este texto):**
- Diseño rev.3: SHA-256 `5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`
- Protocolo v2 (CF-1..CF-5): SHA-256 `ef267f23583d4a36eca46bacb4f51fabdaaecf81955ebb5d079f0aee083998ea`
- Informe de conformidad NO CONFORME: SHA-256 `fd6c05b7d255684d423552e2e0e70433d41a3d67a4654a2f4cbb2813a5764788`

El protocolo v2 no se edita (regla del informe): este v3 candidato lo
reemplaza íntegro. El `contrato_hash` de las identidades será el SHA-256 de
ESTE archivo una vez declarado CONFORME.

---

## Cláusulas nuevas (resuelven B-1, B-2, M-1..M-4)

### CF-6. Génesis canónico e historia normativa (cierra B-1)

- **Dataset canónico por mercado:** klines Binance versionadas del repositorio
  + push del VPS (fuentes ya definidas), fusionadas por `t` (el push
  prevalece en empate).
- **GENESIS_H4 = 2022-03-01T00:00:00Z (`1646092800000` ms)** para los 7
  mercados. El estado estructural H4 (pivotes, BOS, rangos, zonas) se computa
  NORMATIVAMENTE desde GENESIS_H4, independiente de cuánta historia cargue el
  proceso: dos implementaciones ven exactamente las mismas velas.
- La "ruptura opuesta previa" de CF-1 se busca en `[GENESIS_H4, ahora]`. Si
  no existe → `rango_sin_origen` (abstención). Prohibido cualquier otro
  origen dependiente de la profundidad cargada.
- **Cobertura mínima para procesar la vela `m` de un mercado:** continuidad
  sin huecos de las últimas **1000 velas H4** y **200 velas M15** (por
  diferencia exacta de `t` = duración de la TF). Si falla →
  `historia_insuficiente`: sin candidatos nuevos ni órdenes nuevas en ese
  mercado hasta recuperar continuidad (posiciones/órdenes vivas se gestionan
  solo con SL/TP/deadline; el episodio se registra en el ledger).

### CF-7. Máquina de estados y precedencia global por vela (cierra B-2)

Estados por mercado: `flat` → `orden_viva` → `posicion` → `flat`. Todo el
motor procesa las velas M15 en orden cronológico; dentro de la vela `m` el
orden normativo es EXACTAMENTE:

1. **Resolución intravela de `posicion`** (CF-2; orden interno: gap-SL →
   gap-TP → SL → TP; SL y TP en la misma vela = STOP).
2. **Resolución intravela de `orden_viva`** (fill §4.5; `gap_ambiguo` se
   evalúa primero).
3. **Al cierre — devengos de funding** pendientes con `k ≤ close_time(m)`
   (CF-8).
4. **Al cierre — expiraciones y cancelaciones:** deadline vencido sin fill →
   `orden_cancelada(deadline)`; cambio o expiración de dirección H4
   disponible a este cierre → `orden_cancelada(direccion)`. **Regla de no
   retroactividad:** ningún evento conocido al cierre cancela ni revierte un
   fill o salida ya ocurridos intravela en esta vela o antes. Una `posicion`
   NUNCA se cierra por cambio de dirección: solo por SL, TP o corte.
5. **Al cierre — actualización estructural** (BOS/iBOS, zonas, rango,
   fractal, dirección) con los eventos cuyo `available_at ≤ close_time(m)`.
6. **Al cierre — detección de toques, arbitraje y creación de orden** (solo
   en estado `flat`; la orden creada tiene `idx_alta = m` y es elegible desde
   `m+1`). Si la posición salió en el paso 1 de esta misma vela, el mercado
   ya está `flat` y este paso aplica normalmente.
7. **Al cierre — chequeo de corte del experimento** (CF-11). El corte por
   50 cierres se evalúa DESPUÉS de registrar los cierres de esta vela.

Conflictos resueltos explícitamente: la vela del deadline es elegible
completa para fill (paso 2) y la cancelación por deadline solo ocurre en su
cierre si no hubo fill (paso 4); fill y cambio de dirección en la misma vela
→ el fill queda firme (paso 2 precede al 4); salida y candidato nuevo en la
misma vela → permitido (pasos 1 y 6).

### CF-8. Funding causal por desigualdades (cierra M-1)

- La vela de referencia del devengo `k` es la vela M15 con
  `close_time == k` (es decir `t == k − 900000`). `C_k` = su CIERRE. El
  devengo se procesa en el paso 3 del cierre `k` — nunca usa una vela que
  abra en `k`.
- Se devenga todo `k` tal que
  `close_time(m_fill) < k ≤ close_time(x_salida)`, con `m_fill` la vela del
  fill y `x_salida` la vela de la salida (desigualdades sobre enteros ms).
  Fill y devengo en la misma vela → NO se devenga ese `k`; salida y devengo
  en la misma vela → SÍ se devenga (conservador, es un cargo).

### CF-9. Serialización canónica de identidades (cierra M-2)

- Preimagen = JSON canónico: UTF-8 sin BOM, claves ordenadas
  lexicográficamente, separadores `(",", ":")` sin espacios, sin float JSON:
  **los precios van como cadenas con exactamente 6 decimales** (formato
  `%.6f` del valor cuantizado Q, CF-10), timestamps como enteros ms UTC,
  mercado en mayúsculas (`BTCUSDT`), `dir` ∈ {`"long"`,`"short"`}.
- Hash = SHA-256 en hexadecimal minúsculo de los bytes UTF-8 de la preimagen.
- Preimágenes exactas (campos completos, nada más ni menos):
  - `candidate_id`: `{"contrato":"<sha>","dir":"…","mercado":"…",`
    `"tipo":"candidate","toque_t":<ms>,"zona_avail":<ms>,`
    `"zona_hi":"<%.6f>","zona_lo":"<%.6f>"}`
  - `order_id`: `{"candidate":"<candidate_id>","derivada_avail":<ms>,`
    `"derivada_hi":"<%.6f>","derivada_lo":"<%.6f>","tipo":"order"}`
  - `trade_id`: `{"fill_precio":"<%.6f>","fill_t":<ms>,`
    `"order":"<order_id>","tipo":"trade"}`

### CF-10. Política numérica y fórmulas del SL (cierra M-3)

- Cálculo interno en float64 IEEE-754 **sin redondeo intermedio**.
- Cuantización `Q(p)` = redondeo half-even a 6 decimales.
- Se cuantizan al crearse (y gobiernan fills, salidas, arbitraje, IDs y
  filtro RR): `E = Q(borde proximal)`, `T = Q(weak rector)`,
  `S_long = Q(extremo × (1 − 0.001))`, `S_short = Q(extremo × (1 + 0.001))`
  con `extremo` = el precio crudo del swing de la reacción.
- Fees, funding, PnL y R se calculan sobre valores crudos/cuantizados según
  las fórmulas de CF-4 **sin redondeo intermedio**; solo el REPORTE de R se
  redondea a 4 decimales (half-even). Las comparaciones de arbitraje y
  desempate usan valores `Q`.

### CF-11. Corte temporal normativo (cierra M-4)

- Límite duro: `T_corte = 2026-12-31T23:59:59.999Z = 1798761599999 ms`.
  Un cierre de trade cuenta para el experimento sii
  `close_time(x_salida) ≤ T_corte` (inclusivo).
- Corte por muestra: en el paso 7 del primer cierre M15 donde el ledger
  alcanza 50 cierres totales Y la cobertura es ≥8 semanas ISO con ≥1 cierre.
- Al corte (por muestra o por tiempo): posiciones abiertas →
  `abierta_al_corte`; órdenes vivas → `orden_al_corte`. Ambas se EXCLUYEN
  del estadístico primario y se reportan aparte (conteo y detalle). Después
  del corte no se procesan más velas.

---

## Parámetros congelados (consolidado; todos `[U0]` salvo nota)

| Parámetro | Valor |
|---|---|
| Universo | ADA, BNB, BTC, DOGE, ETH, SOL, XRP (USDT-PERP, klines Binance) |
| GENESIS_H4 | 2022-03-01T00:00:00Z (`1646092800000`) |
| Cobertura mínima | 1000 velas H4 y 200 velas M15 continuas |
| Fila del curso | zona H4 → confirmación M15 (única) |
| STRUCT_PIV / INT_PIV | 8 / 3 |
| Expiración dirección H4 | 180 velas H4 |
| TTL zona H4 | 180 velas H4 desde `available_at` |
| Deadline total toque→fill | 64 velas M15 |
| Ventana iBOS | ≤48 velas M15 desde el toque |
| Buffer SL | 0,1% (fórmulas CF-10) |
| RR neto mínimo (a priori) | 2,0 (compatible S06, no demostrado) |
| Fees | maker 0,02% · taker 0,05% |
| Slippage STOP | 0,05% |
| Funding | 0,01% por devengo (CF-8) |
| Corte | 50 cierres totales (≥8 semanas ISO) o `1798761599999` ms |
| Bootstrap | semanas ISO, 10.000 réplicas, semilla 20260817, IC 95% |
| Cuantización | Q = half-even a 6 decimales (CF-10) |

## Reglas de vigencia

1. Este texto es CANDIDATO: se congela como v3 definitivo solo con la
   conformidad de Codex; su SHA-256 en ese momento pasa a ser el
   `contrato_hash`. Cualquier cambio posterior = protocolo v4 + cohorte nueva.
2. Implementación aceptable solo pasando los gates del diseño rev.3 §11 más:
   determinismo del génesis (dos profundidades de carga distintas → mismo
   libro) y vectores dorados de las preimágenes de CF-9.
3. Frontera forward = primer pull exitoso del recolector posterior al
   despliegue verificado. Todo lo anterior es backtest, reportado aparte.
4. Bot3.v1 permanece suspendido; ninguna métrica v1/v2 se reutiliza.
5. Resultado positivo NO autoriza Bot/Testnet/Live.
6. Evaluación ÚNICA al corte; octubre es checkpoint informativo.

## Secuencia restante

Conformidad de Codex sobre este candidato → congelamiento v3 (hash) →
implementación (paso 5) → re-auditoría completa (paso 6) → despliegue
verificado (paso 7) → cohorte desde cero (paso 8).
