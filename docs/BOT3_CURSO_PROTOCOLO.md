# Bot3 · Curso BTA — protocolo congelado (v1)

**Fecha de congelamiento:** 2026-08-17 · **Estado:** `PAPER / RESEARCH_ONLY`
**Módulo:** `modules/bot3` · **Config:** bloque `bot3` de `config/nexus.json`

## Qué es

La estrategia del curso Bitcoin Traders (playbook `course-study.v1`, congelada
en `nexux/research/bitcoin_traders_course_2026-08-17/` y validada en
`CLAUDE_INDEPENDENT_REVIEW.md`) corriendo como **bot paper con diario virtual
propio y aislado**, con el mismo chasis causal de Bot2: la simulación
determinista sobre velas cerradas ES el diario (mismas velas → mismo libro),
sin estado mutable que corromper y sin look-ahead (swings por `confirm_idx`,
rupturas solo con CUERPO).

## Aislamiento (no negociable)

- Sin ejecutor, sin credenciales, sin órdenes: solo OHLCV público/versionado.
- No escribe en el diario real (`setups_store`), no toca el Bot ni el bot2.
- No alimenta ni roza ECON-COHORT-001 (VPS intacto) ni las cohortes del lab.
- Solo lectura vía `/m/bot3/api/{state,book}`.

## Regla congelada (contrato v1)

1. **Universo:** ADA, BNB, BTC, DOGE, ETH, SOL y XRP (USDT) — los 7 pares con
   klines versionadas · TFs 15m y 1h · rector: H4 (15m/1h), D (4h).
   *(Ampliado de BTC+ETH a los 7 el mismo día del congelamiento, ANTES de
   mirar ningún resultado: con 2 pares la regla producía ~3 cierres/83 días y
   la muestra de octubre iba a ser inservible.)*
2. **Zona:** OB (última vela opuesta antes del FVG) o FVG abierto, de la TF
   vista o del rector; caduca sin toque en 2000 velas de la TF vista.
3. **Entrada (modelo por confirmación del curso):** primer toque de la zona →
   iBOS con cuerpo de la TF vista dentro de ≤30 velas → entrada al cierre del
   iBOS. Si un cierre atraviesa la invalidación antes de confirmar → descartada.
4. **Dirección:** solo a favor del rector vigente (última ruptura con cuerpo
   de la estructura rectora as-of la entrada).
5. **SL:** invalidación de la zona ± 0,1% de buffer.
6. **TP:** liquidez opuesta estructural sin barrer más cercana **as-of** la
   entrada (sin velas futuras).
7. **Filtro:** RR neto ≥ 2 (costos 0,12% ida y vuelta, supuesto de Bot2).
8. **Gestión:** una posición virtual por mercado; salida completa en SL o TP;
   sin break-even ni parciales (el curso no fija disparador universal).
9. **Honestidad:** vela que toca SL y TP en la misma barra cuenta como **STOP**.

## Evaluación

- **Única, al cierre:** ≥50 trades cerrados por mercado o 2026-10-31, lo que
  llegue primero. El panel es visible (es laboratorio exploratorio, no cohorte
  ciega), pero la DECISIÓN no se toma con métricas intermedias.
- Métricas del corte: n, win rate, avg R neto, R acumulado, profit factor,
  y el desglose de descartes (los rechazos también son resultado).
- Cambiar cualquier parámetro del contrato reinicia el conteo y exige nueva
  versión de este protocolo.

## Advertencias pre-registradas

- Los parámetros estructurales (`STRUCT_PIV=8`, `INT_PIV=3`, ventana de
  confirmación 30, buffer 0,1%, TTL 2000) son **defaults visuales** del
  semáforo amarillo del playbook — el curso no fija umbrales. Este forward-test
  mide ESA concreción, no "la estrategia del profe" en abstracto.
- Resultado positivo aquí NO autoriza Bot/Testnet/Live: la promoción se decide
  en la ventana de octubre (`BOT_OCTOBER_DECISION_TREE.md`) con el corte en la
  mano, y cualquier paso a dinero real exige su propio protocolo.
- La ventana simulada (~8000 velas) incluye historia previa al congelamiento:
  el tramo pre-2026-08-17 es **backtest** (mismo código causal) y el tramo
  posterior es **forward**. El corte de evaluación reporta ambos por separado
  usando `t_entrada` ≥ 2026-08-17 00:00 UTC como frontera.
