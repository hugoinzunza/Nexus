# Bot3.v2 — diseño contractual (PROPUESTA, no congelada)

**Fecha:** 2026-08-17 · **Estado:** `BORRADOR PARA APROBACIÓN (Hugo + re-auditoría Codex)`
**Insumos:** `AUDITORIA_CURSO_BOT3_2026-08-17.md` (rechazo v1), re-auditoría C-1
(PASS con fix requerido: selección retrospectiva de zonas), playbook
`course-study.v1`, `CLAUDE_INDEPENDENT_REVIEW.md`.

Este documento es el paso 3 de la secuencia aprobada. Nada de aquí se
implementa hasta que exista el protocolo v2 pre-registrado (paso 4) firmado
sobre esta base. Ninguna métrica de v1 se reutiliza.

---

## 1. Objeto científico (elección única)

**La fila H4→M15 de la tabla docente** (S06 00:43:13–00:50:50; S11
00:31:14–00:32:35): zona de interés del rector **H4**, confirmación completa
en **M15**. Es la porción del curso medible con los datos disponibles (no hay
velas <15m). Todo lo que no sea esta fila queda fuera del objeto y no se
menciona como "estrategia del curso" en los resultados.

## 2. Contexto rector (H4) — fail closed

- **Rango operativo causal**: strong SOLO si su origen barrió liquidez
  (sweep verificable); weak cerrado SOLO tras finalización por swing + iBOS
  (S03 01:05:15–01:24:54). Sin sweep → no hay rango → **abstención**.
- **Dirección**: última ruptura H4 con cuerpo, disponible a su cierre
  (`available_at`). `None`, conflicto o rango sin dirección → **abstención**
  (nunca fail open — corrige M-5).
- **Antigüedad máxima del rector** (a congelar en el protocolo, no durante el
  desarrollo): la dirección expira si su BOS tiene más de **180 velas H4
  (30 días)** sin un BOS de continuación, o si el rango que la originó fue
  invalidado por cierre H4. Valor propuesto; Hugo decide el número final.

## 3. Selección de zona (H4)

Zona admitida: OB o FVG **del rector H4**, con:
- disponibilidad causal (`avail_t` = cierre de la vela que la completa);
- **frescura contractual**: cero toques entre `avail_t` y el toque de entrada;
- **lado correcto**: discount para largos / premium para cortos vs el EQ del
  rango rector (corrige M-2);
- **gate de fractal**: el fractal H4 vigente alcanzó retroceso ≥50%
  (cuerpo o mecha) en la dirección del trade (S02);
- registro descriptivo de `liq_delante` y `trampa` (no vetan en v2; quedan
  medidos para HYP-BT-LIQ-EXT-001).

## 4. Confirmación M15 completa (iBOS válido, S08 00:36:05–00:41:50)

Tras el toque de la zona H4, en M15 y dentro de una ventana congelada
(propuesta: **48 velas M15 = 12 h**):
1. **Toma de liquidez a la izquierda**: la pierna M15 que entra a la zona
   barrió (mecha) al menos un swing low/high interno M15 previo;
2. **iBOS M15 con cuerpo** en la dirección del trade (disponible a su cierre);
3. **Zona derivada**: el desplazamiento del iBOS deja OB/FVG M15 propio;
4. **Entrada = retest de la zona derivada** (primer toque posterior, ventana
   propuesta: **32 velas M15 = 8 h**). Sin retest → no hay trade (se registra
   `confirmada_sin_retest`: los rechazos también son resultado).

Invalidación previa (cierre M15 a través de la invalidación de la zona H4
antes del iBOS) → descarte registrado.

## 5. Riesgo, objetivo y gestión

- **Entrada**: precio del retest (mid de la zona derivada tocada).
- **SL**: extremo de la reacción que originó el iBOS (el swing barrido) ±
  buffer congelado (propuesta: **0,1%**).
- **TP**: **weak cerrado del rango rector H4** (corrige M-2). Sin weak
  cerrado → abstención.
- **Filtro**: RR neto ≥ 2 con costos por mercado versionados (propuesta base
  0,12% ida y vuelta; tabla por par en el protocolo).
- Una posición virtual por mercado; salida completa; vela ambigua = STOP.
- Exclusiones declaradas (m-2 de la auditoría): la regla docente universal de
  dos entradas queda FUERA del objeto v2 (sigue amarilla en el playbook);
  BE/parciales fuera (sin disparador universal enseñado).

## 6. Causalidad total (cierra C-1 y el hallazgo de la re-auditoría)

- `available_at` en TODO evento multi-TF (ya implementado y auditado).
- **PROHIBIDO cualquier operador relativo al final de la serie**: nada de
  `[-N:]` sobre zonas, trades ni eventos (el `MAX_ZONES_SIM` de v1 queda
  eliminado). Los límites de cómputo solo pueden ser causales por evento:
  TTL de zona desde `avail_t` (propuesta: **500 velas H4** para zonas H4) y
  ventanas de confirmación/retest desde el toque.
- **Gate de aceptación**: test de invariancia por prefijo sobre ventana real
  (≥2000 velas M15 de BTC, >300 zonas) — exactamente la reproducción de la
  re-auditoría — más un test sintético con expulsión forzada. Si el prefijo
  cambia un trade cerrado, la implementación no se acepta.
- Tests discriminantes (corrigen las debilidades que señaló Codex): el
  escenario de toque prematuro debe FALLAR contra una versión con
  disponibilidad por apertura (se prueba parametrizando la disponibilidad),
  y la aserción de `avail_t` exige el delta EXACTO de la TF.

## 7. Cohorte forward: ledger append-only (corrige M-6)

- **Recolector en el Mac mini** (máquina canónica), servicio launchd propio
  (`com.hugo.nexux-bot3-forward`), que cada 15 min consulta
  `nexux.cl/m/bot3/api/book` por mercado y **appendea** a
  `crisol/nexux/data/bot3_forward/ledger.jsonl`:
  - `trade_id` estable = hash de (mercado, tf, dir, zona H4 `avail_t`,
    `t_entrada`, contrato_hash);
  - eventos append-only: `descubierto`, `cerrado` (nunca se reescribe);
  - provenance por evento: hash del contrato v2, commit de código, fuente y
    `as_of` de las velas, timestamp local del pull;
  - gaps del recolector registrados explícitamente (`gap_detectado`).
- El simulador sigue existiendo como VISTA reproducible; **la cohorte
  evaluable es el ledger**, no la recomputación.
- **Frontera forward** = timestamp del primer pull exitoso posterior al
  despliegue verificado de v2 (nunca una fecha anterior al deploy — corrige
  la frontera inválida de v1).

## 8. Evaluación (única)

- Corte: **≥50 trades cerrados en el ledger por mercado, o 2026-12-31**
  (lo primero). Nota: con el embudo completo (retest incluido) la frecuencia
  bajará vs v1; octubre es el checkpoint del ecosistema, no el corte de Bot3.v2
  — en la ventana de octubre solo se reporta avance del ledger, sin decidir.
- Multiplicidad declarada: 7 mercados × 1 fila (H4→M15). Métricas por mercado
  y agregado; cualquier lectura por mercado lleva corrección por multiplicidad
  (Holm), como en el laboratorio.
- Si el corte llega con n bajo: se reporta con intervalos y NO se promueve ni
  descarta; se decide extender o cerrar como `insuficiente`.
- Resultado positivo NO autoriza Bot/Testnet/Live: exige protocolo propio.

## 9. Parámetros que Hugo debe congelar en el protocolo v2

| Parámetro | Propuesta | Nota |
|---|---|---|
| Antigüedad máxima dirección H4 | 180 velas H4 (30 días) | pedido explícito de Hugo |
| Ventana confirmación M15 | 48 velas (12 h) | reemplaza el 30 arbitrario de v1 |
| Ventana retest zona derivada | 32 velas (8 h) | nueva (entrada del curso) |
| TTL zona H4 | 500 velas H4 | causal desde avail_t |
| Buffer SL | 0,1% | U0 del curso, default declarado |
| Costos por par | 0,12% base + tabla | versionados por mercado |
| Umbral evaluación | 50 cierres/mercado o 2026-12-31 | única |
| Universo | 7 pares USDT actuales | igual a v1, pre-datos |

Con estos valores aprobados (o corregidos por Hugo), el paso 4 es escribir el
protocolo v2 pre-registrado con hash, y recién entonces implementar (paso 5),
re-auditar (paso 6), desplegar verificado (paso 7) y abrir la cohorte desde
cero (paso 8).
