# Capa "Curso" del gráfico — estrategia Bitcoin Traders (playbook.v1)

**Fecha:** 2026-08-17 · **Estado:** desplegada como capa PARALELA (toggle "Curso")

## Qué es

La lectura del profe (curso BOOTCAMP MAYO 2025, congelada en
`nexux/research/bitcoin_traders_course_2026-08-17/` como `playbook.v1` y
validada en `CLAUDE_INDEPENDENT_REVIEW.md`) dibujada sobre el gráfico de
NexUX: rango operativo causal, fractal ≥50%, zonas OB/FVG con frescura,
liquidez delante/detrás (bloque trampa) y checklist semáforo.

## Por qué es una capa paralela y NO un reemplazo (todavía)

`smc_live.analyze` alimenta los TP del diario vía `tpsl`, y el diario es la
fuente de señales que espeja el bot de **ECON-COHORT-001** (congelada hasta su
cierre: cualquier cambio la invalida). Por eso:

- `smc_course.py` **no produce `tpsl` ni plan alguno** (test lo garantiza);
- tiene **cache propio** (`_smc_course_cache`) y solo lo consume el endpoint
  del gráfico con `strategy=course`;
- `_record_setups`, el diario y el bot siguen colgados de `_smc_analysis`
  **intacto**.

**Promoción a default:** decidirla en la ventana de octubre (ver
`docs/BOT_OCTOBER_DECISION_TREE.md`), junto con el fix del dealing range.

## Mapeo playbook → implementación

| Playbook (§) | Implementación |
|---|---|
| §2 Fractal ≥50% | `_fractal`: última pierna estructural; fib50; toque con cuerpo O mecha (regla verificada) |
| §3 Rango causal | `_rango`: ruptura CON CUERPO (BOS) → strong = origen de la pierna (⚡ si tomó liquidez) → weak = LIQUIDEZ PENDIENTE más cercana más allá del extremo post-BOS (el Weak Low del profe) → 50% |
| §1 Jerarquía (rector) | El rango sale de la estructura RECTORA (`RECTOR_TF`: H4 para ≤1h, 1D para ≥2h) — el mapa del profe en M15 es el rango H4/D. La TF vista aporta estructura interna, fractal, zonas y entradas |
| §7 Entrada por confirmación | `_entradas`: zona (propia o del rector) tocada + iBOS de la TF vista en su dirección → ✓ entrada; cierre a través de la invalidación antes → ✗. Marcas descriptivas, sin entry/SL/TP |
| §4 Premium/discount | bandas del rango del curso, direccionales |
| §5 Zonas admitidas | `_zones`: OB (última vela opuesta antes del FVG) + FVG abiertos; frescura = primer uso sin tocar; se detectan en la TF vista Y en la rectora (las cajas Premium/Discount POI grandes del profe); etiqueta por lado vs EQ rector |
| §5 Taxonomía OB | `tipo`: extremo (toca el strong) / decisional (lado del origen) / interna — descriptivo |
| §6 Liquidez delante/detrás | `_pools` (EQH/EQL + swings sin barrer) + banderas `liq_delante` / `trampa` (pool detrás de la invalidación a <35% del alto del rango) |
| §8 Target | weak del rango + distancia % en el checklist |
| Checklist | pill "CURSO · dirección · liq · 50% · zona · trampa · target" |

## Defaults visuales (semáforo AMARILLO del playbook — el curso no fija umbrales)

`STRUCT_PIV=8`, `INT_PIV=3`, `WINDOW=500` barras **de la TF vista** (cada
temporalidad lee su propia escala — corrección del bug de calibración única de
la auditoría vs LuxAlgo), `EQ_TOL_PCT=0.12%`, `TRAP_MAX_FRAC=35%` del alto del
rango, `FVG_LOOKBACK=140`. **No validados estadísticamente; no migrar al bot
sin laboratorio.** Las candidatas cuantitativas ya están pre-encoladas como
`HYP-BT-LIQ-EXT-001` / `HYP-BT-IBOS-001` (máx. dos, protocolo congelado).

## Uso

Gráfico de trading → toggles de capas → **Curso**. Al activarlo la lectura
NexUX (bandas, POIs, niveles, CDC, plan TP/SL) se oculta y se dibuja la del
curso; las cajas de trades activos del forward-test permanecen. El estado del
toggle persiste (localStorage) y la capa se recalcula por TF.
