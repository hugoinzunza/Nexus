# Estudio de la estrategia SMC del curso — 4 años (2022–2026)

**Fecha:** 2026-06-13 (sesión nocturna)
**Qué se evaluó:** el MISMO criterio del indicador en vivo (`smc_live.analyze`):
POI multi-TF (1D/4h/1h) en descuento/premium → entrada en la zona → SL estructural
con techo 1.5% → TP a la siguiente liquidez sin barrer → filtro R:R ≥ 2.
**Cómo:** `run_setup_backtest.py` reusando `smc_live.analyze` barra a barra,
anti-repaint (solo velas cerradas; HTF cerradas; resolución con barras posteriores;
SL antes que TP si una barra toca ambos). Datos: klines de Binance BTC/ETH 1h+4h.
Split IS/OOS 70/30 por fecha. **1.794 trades cerrados, 2022-05 → 2026-06.**

> Antes este backtest cubría ~1 año (cap `BARS=4000/2000`). Con la historia profunda
> ya versionada, ahora cubre 4 años → permite testear regímenes, no solo el último.

---

## Veredicto honesto

**El criterio tiene un edge estadístico POSITIVO y ROBUSTO entre regímenes en
backtest — PERO todo el edge depende de dejar correr los winners a la liquidez
lejana, y es un perfil de win rate bajo (16–22%) brutal de ejecutar.**

Esto es **muy distinto** del veredicto viejo ("ninguna estrategia mecánica tiene
edge OOS"): aquel era de 12 estrategias de indicadores genéricos. Este criterio
—el del curso, con POI + liquidez— sí muestra edge consistente.

---

## 1) Robustez por régimen (lo más importante)

| Año | Régimen | Trades | Win % | R prom | PF | R acum |
|----:|---------|------:|------:|------:|----:|------:|
| 2022 | bear | 219 | 17.4 | 0.53 | 1.64 | +117 |
| 2023 | recuperación | 427 | 20.6 | 0.51 | 1.64 | +218 |
| 2024 | bull | 457 | 16.2 | 0.45 | 1.53 | +204 |
| 2025 | — | 499 | 19.2 | 0.83 | 2.03 | +413 |
| 2026 | parcial | 192 | 22.4 | 1.41 | 2.81 | +270 |

**Positivo TODOS los años, en bear / recuperación / bull (PF 1.5–2.8).** No es un
artefacto de un solo régimen — esa es la señal fuerte. (El R prom mejora con los
años; misma lógica aplicada a todos, así que refleja comportamiento de mercado, no
sobreajuste a un período.)

## 2) La dependencia crítica: dejar correr los winners

Sensibilidad a capar el R de los ganadores (4 años):

| Cap del winner | R prom | Lectura |
|---------------|------:|---------|
| sin tope (TP a liquidez) | **+0.68** | el setup tal cual |
| 15R | +0.57 | |
| 10R | +0.45 | |
| 5R | +0.05 | apenas break-even |
| **3R** | **−0.25** | **NEGATIVO** |

**Todo el edge vive en los winners grandes (mediana ~8.5R).** Si tomas profit en
3R —lo que hace la mayoría— la estrategia **pierde**. Esto es lo más accionable del
estudio: el criterio no es "entra al POI y saca 3R"; es "entra al POI y aguanta
hasta la liquidez opuesta", lo que exige soltar la mano por movimientos enormes.

## 3) Dureza real de ejecución

- **Win rate 16–22%**: ~4 perdedoras por cada ganadora.
- **Racha perdedora más larga: 32 trades seguidos** (en R: −42R de drawdown máximo).
  A 1.5% de riesgo por trade, una racha así es un drawdown de cuenta fuerte.
- **45% de las señales son "anuladas"**: el precio llega al TP sin llenar la
  entrada → ves la mitad de los setups arrancarse sin ti.
- Psicológicamente: hay que ejecutar mecánicamente ~80% de trades perdedores
  esperando los pocos que pagan 8–34R. Sin esa disciplina, el edge no se captura.

## 4) Concentración

| Corte | R prom | Nota |
|-------|------:|------|
| BTC | 0.47 | positivo |
| ETH | 0.90 | ~2× BTC |
| sel 1h | 0.54 | |
| sel 4h | 0.84 | mejor |
| POI 1h | (bulk del edge) | |
| POI 4h | flojo | |

Ambos símbolos positivos a 4 años, pero ETH y las TF de 4h cargan más del edge.

---

## Sesgos / limitaciones (para no engañarnos)

1. **Sin costos** en `_simulate` (perdida = −1R exacto, ganada = +rr exacto). El
   edge por trade es grande, así que aguanta: a 0.2R/trade de costo seguía en
   +1.18R (en el tramo reciente). No es fatal, pero el R real será algo menor.
2. **El winner = rr completo del plan, asumido alcanzado** dentro de la ventana
   forward (240 barras 1h / 180 barras 4h). Es la mayor optimización: supone que
   aguantas cada winner hasta el TP lejano y que el TP se llena.
3. **Muestras no independientes**: BTC/ETH correlacionados, 1h/4h solapados → el N
   efectivo es menor que 1.794; los intervalos de confianza son más anchos.
4. **"Anuladas" y "abierto" excluidas** del win/loss (impacto chico: solo 8
   "abierto" en el tramo reciente).
5. No modela slippage en el SL ni gaps; el SL real puede ser peor que −1R.

---

## Recomendación para "aplicar"

- **Es lo bastante sólido para forward-test en serio** (papel o tamaño mínimo), no
  para asumirlo como caja registradora. La robustez entre regímenes es genuina.
- **La regla de ejecución no es negociable**: TP a la liquidez opuesta, no a 3R.
  Si tu plan real es tomar 3R, este criterio NO es tu edge (es negativo ahí).
- **Disciplina sobre la racha**: dimensiona el riesgo para sobrevivir 32 perdidas
  seguidas (p.ej. 0.5–1% por trade, no 2–3%).
- **Foco**: ETH y planificación en 4h con POIs de 1h fueron los más fuertes.
- **Siguiente paso de validación**: registrar los planes que el indicador genera en
  vivo (ya hay `_record_setups`) y comparar el forward real contra estos números en
  unos meses. Es la única prueba que no tiene sesgo de backtest.

Datos crudos: `setup_backtest_results.json` (ahora con `by_year`, `cap_sensitivity`,
`risk`). Reproducible: `python3 -m modules.trading.run_setup_backtest`.
