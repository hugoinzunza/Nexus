# Veredicto final — estrategia SMC del curso (estudio nocturno 2026-06-13)

Consolida todo el análisis de la noche: edge, TP, SL, temporalidad, apalancamiento
y sizing, aplicado al capital real de Hugo ($38.000). Todo con costos (comisión
0,05%/lado + slippage 0,02%/fill) y anti-repaint, reusando `smc_live.analyze`
(el mismo criterio del indicador en vivo). **Es backtest, no una promesa.**

---

## 1. ¿Tiene edge? Sí, y robusto entre regímenes.

4 años (2022–2026), BTC+ETH 1h+4h, 1.794 trades cerrados:

| Año | Régimen | win% | R prom | PF |
|----:|---------|-----:|-------:|----:|
| 2022 | bear | 17,4 | 0,53 | 1,64 |
| 2023 | recuperación | 20,6 | 0,51 | 1,64 |
| 2024 | bull | 16,2 | 0,45 | 1,53 |
| 2025 | — | 19,2 | 0,83 | 2,03 |
| 2026 | parcial | 22,4 | 1,41 | 2,81 |

**Positivo todos los años, en bear/recuperación/bull (PF 1,5–2,8).** Es la señal
fuerte: no es un artefacto de un solo régimen. Muy distinto del "sin edge" de las
12 estrategias mecánicas — ese era otro estudio.

## 2. El edge vive en POCAS ganadoras GRANDES

- Win rate **16–22%**: ~4 perdedoras por ganadora. Rachas perdedoras de hasta 32.
- Ganadora mediana ~8,5R; el edge NO depende de 1–2 outliers (top-5 = 17% del R+).
- **Capar los winners lo mata:** sin tope +0,68R · cap 5R +0,05R · **cap 3R −0,25R**.
  Si tomas profit cerca, pierdes el edge. Hay que dejar correr a la liquidez lejana.

## 3. TP: el estructural (tu idea) es el mejor ajustado por riesgo

4 años, sizing fijo:

| TP | win% | R prom | $ fijo | maxDD |
|----|-----:|-------:|-------:|------:|
| baseline (liquidez lejana) | 20,7 | 0,80 | +$134k | −$8,1k |
| **estructural (alto previo)** | 23,8 | 0,80 | +$130k | **−$5,6k** |
| 3R | 44,7 | 0,79 | +$67k | −$3,6k |
| 2R | 56,1 | 0,68 | +$47k | −$2,5k |

Estructural ≈ baseline en plata pero con **menos drawdown y más win rate** → mejor
ajustado por riesgo. 2R/3R suben el win rate pero cortan el R y ganan la mitad o menos.

## 4. SL: ajustado, NO ancho

Ensanchar el stop a 2% (vs el estructural ~0,7%):

| SL | win% | avgR | P&L 2026 |
|----|-----:|-----:|---------:|
| estructural ~0,7% | 24,6 | **1,34** | +$121k |
| fijo 2% | 36,2 | **0,24** | +$18k |

Sube el win rate (menos stop-outs) pero **hunde el avgR** (1,34→0,24): al alejar el
stop 3x, el R:R se reduce 3x. La ganancia cae ~7x. **El stop ajustado ES el edge.**

## 5. Temporalidad: 4h > 1h ≈ 15m

2026, R neto por TF de planeación: 4h **1,86** · 1h 0,77 · 15m 0,78. Lo largo rinde
más. Y lo corto NO da más apalancamiento: el stop sale de la estructura HTF
(~0,7% en las tres TF), no de la TF en que planeas.

## 6. Apalancamiento: el punto dulce es ~3x, no 10x ni 20x

Estructural, 2026, compuesto desde $38k:

| Sizing | ~riesgo/tr | final 2026 | maxDD |
|--------|-----------:|-----------:|------:|
| 1% (~1,5x) | 1% | $162k | −26% |
| **2–3% (~3x)** | 2–3% | **~$533k** | −46% |
| 10x all-in | ~7% | $436k | **−92%** |
| 20x all-in | ~14% | ruina/fantasía | −100% |

**A 10x ganas MENOS que a 2–3% Y con −92% de drawdown.** Es volatility drag (Kelly):
pasado el óptimo, más apalancamiento baja el crecimiento geométrico y dispara la
caída. El óptimo está en ~3x efectivo; de ahí para arriba es autodestructivo.

**Liquidación: con el SL ajustado (~0,7–2%) el stop se llena antes del nivel de
liquidación (4,6% a 20x).** En 2026 hubo CERO liquidaciones reales (las 3 "alertas"
eran el SL llenándose normal; la mecha posterior no toca una posición ya cerrada).
El problema del apalancamiento no es liquidación — es el drawdown por sobre-apuesta.

## 7. Las cifras astronómicas son fantasía

Compounding all-in (20x, o 2R/3R) da $billones/quadrillones. **No es resultado, es
el modelo rompiéndose**: asume reinvertir el 100% sin impacto de mercado, liquidez
infinita y que el edge dura intacto años. Ignóralas.

---

## VEREDICTO

**La estrategia del curso tiene un edge real y robusto entre regímenes — pero es un
perfil de win rate bajo (16–22%) y winners grandes, que solo rinde si se ejecuta
con disciplina de hierro y sizing modesto.**

**Config óptima medida:** 4h · TP estructural (o baseline) · SL estructural ajustado
(no ancho) · **~3x efectivo (≈2% de riesgo por trade), nunca 10x/20x.**

**Lo que decide entre ganar y perder NO es la estrategia — es:**
1. **Sizing:** ~3x. Más apalancamiento = menos plata + ruina (Kelly). Comprobado.
2. **Disciplina:** ejecutar ~80% de perdedoras esperando las pocas que pagan 8R+,
   y dejar correr los winners (no cortar en 3R).
3. **Aguantar el drawdown:** aun en la config sana, −26% a −46% de la cuenta.

**Caveats honestos:** backtest 2026 = muestra chica y quizá favorable; 4 años =
robusto pero asume ejecución perfecta, sin slippage extra al escalar tamaño, sin
decaimiento del edge. Los retornos de papel (+160% en 2026) recortan mucho en real.

**Recomendación (no es asesoría financiera):** NO arrancar con los $38k completos.
Forward-test con tamaño chico (el indicador ya registra los setups con `_record_setups`),
comparar fills reales vs backtest unos meses, y recién ahí escalar. El edge está
demostrado en papel; lo que falta validar es TU ejecución y el comportamiento real
de los fills.
