# Indicador de riesgo desde CoinGlass — resultado y pre-registro

Fecha: 2026-07-24 · **Research only · No señal · No bot · NO usar para activar live.**

Script: `research/coinglass_risk_indicator.py` · Datos: `coinglass_risk_indicator_results.json`

## Por qué riesgo y no dirección

El estudio previo (`coinglass_hobbyist_study`) probó reglas **direccionales** sobre
estas mismas series y ninguna sobrevivió OOS. No es sorpresa: predecir el signo del
retorno con 6 meses de barras 4h y features de posicionamiento es lo más difícil
que se puede intentar.

Este apunta a **expansión de volatilidad**. Tiene mejor fundamento (la volatilidad
se agrupa; el posicionamiento extremo es el combustible de las cascadas) y, sobre
todo, es **seguro de usar en un bot**: un indicador de riesgo modula tamaño o pausa
entradas — no elige lado. Si se equivoca, el costo es dejar de operar, no operar mal.

## Método

- 1.079 barras 4h (2026-01-25 → 2026-07-24), origen backfill.
- **Objetivo**: movimiento absoluto máximo de las próximas H barras (4h/8h/12h).
- **Baseline adversarial**: la volatilidad de las H barras **previas**. Si el
  indicador no le gana a "lo que se movió recién", no aporta nada.
- **Normalización causal**: z-score con ventana expansiva — el score de la barra t
  usa solo barras anteriores. Normalizar con la media de toda la muestra habría
  metido futuro en cada punto.
- **Ventanas no solapadas** por horizonte (una obs cada H barras), IC bootstrap 95%,
  split IS/OOS 70/30, pesos iguales pre-registrados sin ajuste.
- **Control negativo**: correlación con el retorno **con signo**, que debe dar ~0.

## Resultado del compuesto: DESCARTADO

| Horizonte | ρ OOS score | IC 95% | ρ baseline | ρ parcial (sobre baseline) | Control dirección |
|---|---|---|---|---|---|
| 4h | +0.055 | [−0.05, +0.17] | **+0.180** | −0.014 | −0.05 |
| 8h | +0.030 | [−0.14, +0.21] | +0.024 | +0.021 | −0.03 |
| 12h | −0.002 | [−0.20, +0.20] | +0.038 | −0.013 | +0.04 |

Cumple el criterio de descarte pre-registrado por partida doble: **el IC incluye
cero en los tres horizontes**, y la **correlación parcial es ~0**, o sea que no
aporta nada que la volatilidad reciente no tenga ya. A 4h el baseline tonto
(+0.180) le gana limpiamente al indicador (+0.055).

Los quintiles OOS lo confirman: el movimiento medio es plano (Q1 0.68% … Q5 0.62%
a 4h). No hay calibración monótona.

El control negativo funciona: correlación con dirección ≈ 0. El pipeline está sano.

## El hallazgo importante: la trampa que casi pasa

La ablación por variable mostró `crowd_extremity` con **+0.215 / +0.222 / +0.308**
OOS, con IC que **excluye cero**. Es exactamente el número que uno querría publicar.

Pero su signo en in-sample es **negativo**: −0.063 / −0.071 / −0.103.

Una variable que correlaciona negativo en un período y positivo en el siguiente no
tiene una relación estable con el objetivo: se alineó con lo que pasó en la segunda
mitad de la muestra. Elegirla ahora, **después** de ver su OOS, sería el
cherry-picking clásico. Queda **rechazada** pese al IC favorable.

Por eso el script reporta IS y OOS juntos y marca `signo_estable`: mirar solo el
OOS habría producido un "indicador validado" que es un artefacto de régimen.

## Ablación completa

| Feature | ρ IS (4h/8h/12h) | ρ OOS (4h/8h/12h) | Veredicto |
|---|---|---|---|
| `liq_intensity` | +0.07 / +0.16 / +0.16 | +0.17 / +0.13 / +0.17 | **Signo estable, sin significancia** |
| `oi_buildup` | +0.09 / +0.11 / +0.07 | +0.06 / +0.06 / +0.02 | Signo estable, muy débil |
| `crowd_extremity` | −0.06 / −0.07 / −0.10 | +0.22 / +0.22 / +0.31 | Artefacto de régimen |
| `funding_extremity` | −0.10 / −0.12 / −0.08 | −0.03 / +0.04 / +0.09 | Artefacto de régimen |
| `book_imbalance` | +0.01 / +0.01 / +0.06 | −0.04 / −0.14 / −0.13 | Artefacto de régimen |

**`liq_intensity` (intensidad de liquidaciones recientes) es la única variable con
signo positivo consistente en los seis cortes.** Su correlación parcial sobre el
baseline es positiva en los tres horizontes (+0.09 / +0.13 / +0.13) pero su IC 95%
roza el cero por abajo ([−0.015, +0.208] a 4h; [−0.015, +0.282] a 8h). No alcanza
el listón — pero es lo único que no está refutado.

## Pre-registro para validación forward

Se fija **ahora**, antes de mirar datos nuevos:

- **Hipótesis única**: `liq_intensity` (suma de liquidaciones long+short de la barra,
  z-score causal) correlaciona positivamente con el movimiento absoluto de las
  siguientes 8h, **por encima** de la volatilidad de las 8h previas.
- **Métrica**: correlación parcial de Spearman controlando por `vol_previa`.
- **Muestra mínima**: 120 observaciones no solapadas de 8h ≈ **40 días** de
  recolección forward. Antes de eso no se evalúa.
- **Criterio de promoción**: IC 95% bootstrap de la parcial **completamente sobre
  cero**. Cualquier otra cosa = descartar y cerrar la línea.
- **Prohibido**: cambiar la variable, el horizonte o el umbral después de ver el
  resultado. Si falla, falla.
- **Qué NO se hace aunque pase**: no se convierte en señal direccional. El uso
  contemplado es modular tamaño o pausar, y eso requiere su propia validación.

## Qué NO llevar al bot hoy

Nada de esto. El compuesto está descartado, `crowd_extremity` está rechazada por
inestabilidad de signo, y `liq_intensity` es una hipótesis pre-registrada sin
validar. El único uso legítimo hoy es **observar**.

## Nota de método

Los datos siguen acumulándose por el colector, así que este estudio se puede
re-correr tal cual dentro de 40 días para resolver el pre-registro. El script es
determinista (semilla fija) y no requiere red.
