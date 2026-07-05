# 2ª auditoría visual/estratégica del gráfico BTA vs Nexux

Fecha: 2026-07-05 · Auditor: Fable 5 · Alcance: solo análisis/research; sin operar,
sin tocar bot live, sin quitar kill-switch.

Fuentes: 9 capturas anotadadas (`tradingview_bta_screenshots_2026-06-30/`), 74 PNGs
campaña limpia (`..._clean_2026-07-01/`), docs previos (playbook 06-30, visual audit
06-30, model spec 07-01, deep backtest 07-01, dealing_range 06-12), código
(`smc_live.py`, `strategies.py`, `executor.py`), y el Diario (191 trades cerrados).

---

## 1. Resumen ejecutivo

La lectura jerárquica que ya teníamos (rango → premium/discount → POI → CDC →
reacción → liquidez) sigue siendo correcta como marco. Pero la auditoría encontró
**una inconsistencia P0 real entre nuestro propio research y el gate del bot**
(`quality_require_disc`), **dos debilidades graves de evidencia visual** (capturas
no independientes y anotaciones con sesgo retrospectivo), y **una lectura nueva
del CDC** (nivel redibujado por pierna, no único) que nuestro modelo simplifica.

## 2. Errores detectados (adversarial)

### E1 — P0 · El bot reintroduce el veto EQ-global que nuestro research eliminó
- `smc_live._tpsl` calcula `disc_ok` contra el **EQ del dealing range GLOBAL**
  (smc_live.py:630-637). El research `dealing_range_2026-06-12.md` demostró que ese
  veto **empeora OOS** (−0.096R → −0.130R) y que lo descartado era lo mejor
  (+0.045R); la acción aplicada fue quitarlo de la capa de plan.
- Pero `executor._quality` con `quality_require_disc: true` (config actual) **exige
  `disc_ok=True`** para grade A, y `_quality_allowed` bloquea todo lo que no sea A/A+.
- **Réplica en el Diario (3er dataset independiente)**: `disc_ok=False` → n=45,
  73% WR, **+0.460R** neto vs `disc_ok=True` → n=137, 58% WR, +0.094R.
- Consecuencia: tal como está, el dry-run de Fase 1 saltaría el subconjunto más
  rentable del forward-test. Es el mismo error conceptual que el profe evita al medir
  el fib 0/0.5/1 **por pierna** (visible en la recaptura zigzag 2025-12-04: fib local
  0=87.97, 0.5=89.73, 1=91.489), no contra un rango de semanas.
- Propuesta: `quality_require_disc: false` en config ANTES de iniciar Fase 1
  (decisión de Hugo; es cambio de filtro, no de código). El EQ local ya viene
  validado dentro de `detect_pois`.

### E2 — P0 (metodológico) · Las capturas anotadas NO son evidencia independiente
- Similarity report 07-01: `2025-04-16_liquidity_case.jpg` y
  `2025-11-05_zigzag_structure.jpg` son **el mismo archivo** (sha256 idéntico);
  un tercer par casi idéntico (hamming 2). De 9 anotadas quedan ~6 efectivas.
- Las 6 útiles cubren **solo may–jun 2026 (un único régimen bajista)** — mismo
  sesgo de régimen que ya nos quemó con el "sesgo short" del diario.
- Campaña de recaptura histórica limpia: de 32 objetivos priorizados,
  **0 confirmados** (29 pending, 2 not_matching, 1 needs_review). Los 74 PNGs son
  mayormente paneos solapados, no casos independientes.
- Conclusión: cualquier regla "aprendida" de estas capturas está **in-sample de un
  régimen** y con n≈6. Sirven para vocabulario visual, NO para validar reglas.

### E3 — P0 (metodológico) · Sesgo retrospectivo en las anotaciones del profe
- Los ✅/❌/💀 del layout se ven en su estado FINAL: no sabemos **cuándo** se dibujó
  cada zona ni si hubo zonas borradas. Un chart estático de TradingView no permite
  distinguir "zona anticipada que funcionó" de "zona anotada después del movimiento".
- Por lo tanto: "las zonas del profe aciertan X%" **no es medible** desde capturas.
  Solo el forward (Diario) o backtests anti-repaint propios pueden validar reglas.

### E4 — P1 · "Reacción" vs "confirmación": el diario entra por TOQUE
- El diario activa cuando "el precio entró a la zona" (module.py:495); el CDC se
  registra (`cdc_status_init`) pero no gatea.
- El deep backtest 07-01 (M15 BTC, 4 años) mostró: toque+liquidez sin CDC =
  **−0.129R neto** (PF 0.86) vs POI→toque→CDC→liquidez = **+0.700R** (PF 1.99,
  OOS +1.05). El lenguaje del profe lo dice literal: "POI **X Confirmación**".
- PERO el Diario da un matiz que frena promover esto a gate ya: por
  `cdc_status_init`, los setups nacidos "sin_toque" (zona fresca) son los mejores
  (+0.707R, n=17) y los nacidos "confirmado" rinden peor (+0.095R, n=92) — señal
  de que **CDC confirmado ANTES de crear el plan = entrada tardía**. La secuencia
  correcta a testear es: plan en zona fresca → toque → CDC DESPUÉS del toque →
  entrada. El diario aún no separa ese caso del resto (muestras chicas).

### E5 — P1 · Nuestro CDC es un objeto único; el del profe es una escalera por pierna
- En las capturas 2026-05-15 y 2026-06-11 hay **múltiples líneas CDC simultáneas**,
  redibujadas en cada quiebre estructural, con roles distintos (frontera de
  continuación tras perderse; confirmación tras recuperarse).
- Nexux tiene 2 capas (estructural RANGE_PIV=10 para dibujar; micro CDC_PIV=2 para
  confirmar) pero ningún objeto "nivel CDC con estado" (pending/broken/reclaimed/
  retest). El prototipo `CharacterLevel` del model spec 07-01 es el camino correcto
  — sigue en research.

### E6 — P2 · Zonas perdidas → continuación (retest) no está modelado en vivo
- 2026-05-27: Premium POI ❌ atravesado en tendencia fuerte; el retest posterior
  actuó de continuación short. 2026-06-24: Discount POI con reacción inicial y 💀
  después (reacción ≠ confirmación, y zona perdida cambió de rol).
- Nexux marca `mitigated/invalid` y descarta; no re-usa la zona como continuación.
  `retest_continuation` existe solo en el prototipo research. Mantener ahí hasta
  tener conteo OOS.

### E7 — P2 · El "mapa" del profe tiene objetos que Nexux no expone
- `Alto Referencial` / `Strong High` como techo-objetivo explícito, `Máximo/Mínimo`
  del rango visible, repisas celestes de liquidez intermedia (targets parciales).
  Nexux los aproxima con `_levels`/`_range` pero no como objetos con rol
  (objetivo/invalidación). Es capa de PRESENTACIÓN/contexto más que de edge:
  útil para el panel SMC, no urge para el bot.

## 3. Qué está BIEN y no hay que tocar
- Anti-repaint (pivotes con `confirm_idx`, velas cerradas) — mejor que el chart.
- TP a liquidez opuesta (validado: +0.371R vs −0.096R con RR fijo).
- SL estructural ajustado + tope 1.5%.
- POI = sweep + displacement + FVG + OB con EQ **local** en la formación.
- rr≥5 global + pares ampliados (2ª auditoría estratégica, commit 87df51b).
- No operar 15m; 1h/4h/1D.

## 4. Mejoras propuestas (disciplina anti-overfitting)

| # | Propuesta | Evidencia visual | Evidencia cuantitativa | Qué la invalidaría | Cómo testear sin operar | ¿Research? |
|---|---|---|---|---|---|---|
| P0-1 | `quality_require_disc: false` antes de Fase 1 | fib 0/0.5/1 por pierna en zigzag del profe | dealing_range OOS + Diario (+0.46 vs +0.09) — 3 datasets | que en dry-run disc_ok=False rinda peor sostenido | ya testeado (backtest+forward); medir en dry-run | config, decisión Hugo |
| P0-2 | Congelar "aprendizaje" desde capturas hasta tener casos independientes | duplicado sha256 + 0/32 recapturas confirmadas | — | conseguir ≥10 capturas fechadas multi-régimen | protocolo de recaptura con fecha objetivo verificada | sí |
| P1-1 | Secuencia toque→CDC(post-toque)→entrada como variante del Diario (columna paralela, no gate) | "X Confirmación" en zonas del profe | cdc_liq +0.70R/PF 1.99 OOS M15-BTC; matiz diario E4 | que en 1h/4h multi-par no replique | registrar en el diario ambas variantes (toque vs confirmación) y comparar netR | sí, paper |
| P1-2 | `CharacterLevel` con estados (broken/reclaimed/retest) | escalera CDC en capturas 05-15/06-11 | parcial (cdc en contexto +0.066R OOS 1h) | conteo OOS sin mejora | extender prototipo research + replay histórico | sí |
| P2-1 | Zona perdida → `retest_continuation` | ❌/💀 y retests en 05-27/06-24 | ninguna aún | OOS negativo | contar casos en 4 años con smc propio | sí |
| P2-2 | Freshness del POI (primer toque de zona virgen) como score | zonas nuevas con ✅ al primer toque | Diario: sin_toque +0.707R (n=17, chico) | n grande sin efecto | re-split del backtest 4a por nº de toque | sí |
| P3 | Score visual 0-10 como gate | — | visual_score7 mediocre (+0.087R neto) | ya casi invalidada | — | descartar como gate; solo ranking UI |
| P3 | Réplica cosmética del layout (colores, arcos, bandas) | — | — | — | — | descartar: cero edge |

## 5. Checklist para futuras capturas (protocolo)
1. Verificar FECHA objetivo visible en el eje antes de guardar (no confiar en el paneo).
2. sha256 inmediato contra las previas (nada de duplicados silenciosos).
3. Guardar SIEMPRE el par (anotada + limpia mismo encuadre) y anotar hora UTC de captura.
4. Cubrir regímenes distintos: mínimo 1 tramo alcista, 1 bajista, 1 lateral por lote.
5. Registrar qué objetos hay: rango, POIs, CDC(s), targets, marcas (✅/👀/❌/💀).
6. NO usar las marcas del profe como ground truth de outcome (sesgo retrospectivo);
   el outcome se mide con nuestras velas.
7. Toda regla inferida entra como HIPÓTESIS en research con split IS/OOS propio.

## 6. Qué NO llevar al bot todavía
- CDC como gate de entrada (P1-1): prometedor en backtest, matiz contradictorio en
  el forward; primero columna paralela en el Diario.
- retest_continuation, freshness, CharacterLevel, SwingLeg: prototipos research.
- Cualquier regla derivada de las capturas 06-30/07-01 (E2/E3).
- El score visual como decisión.
- BTA/paper_only sigue fuera del bot real (guard vigente en executor).

## 7. Estado operativo al cierre
Sin cambios: kill-switch ACTIVO en VPS, servicio sin restart, sin órdenes reales,
sin tocar credenciales. Este documento es research puro. La única acción de config
propuesta (P0-1) queda pendiente de decisión explícita de Hugo antes de Fase 1.
