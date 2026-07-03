# Motor de análogos — Fase 2: ZOOM INTRADÍA (BTC/ETH/SOL/BNB, 15m y 1h)

**Fecha:** 2026-06-12 · **Worktree:** `research-smc-filtros`
**Idea:** el macro no tuvo edge (solo ~3 ciclos, ~30 casos efectivos). Bajamos a intradía,
donde hay **miles de casos** y un edge chico SÍ se podría medir. Reusa todo el andamiaje de
la fase 1 (mismas ventanas z-normalizadas, misma regla anti-look-ahead).

---

## 1. Resumen ejecutivo (para Hugo)

Probé el motor a fondo en intradía con disciplina anti-data-mining. **Veredicto: tampoco
hay edge predictivo real.** Con miles de casos por configuración, el acierto direccional de
los análogos queda **pegado a 0.50 (cara o cruz)** y es **indistinguible del azar**.

- **72 configuraciones probadas** (4 pares × 2 escalas × 3 largos × 3 horizontes). Los
  aciertos caen casi todos en **0.49–0.52**; la correlación entre lo predicho y lo realizado
  es **≈ 0**; el "skill" sobre un baseline tonto es **≈ 0** (a menudo negativo).
- **Multiplicidad (lo clave):** 5 de 72 dieron p<0.05 sin corregir, pero **por puro azar se
  esperaban 3.6**. O sea, no hay más "significativos" que los que daría el ruido. Tras
  **Bonferroni** sobrevive **1 solo** (BTC 1h, L=24, +12 barras), y ese tiene **efecto
  in-sample nulo** (0.501) → es casi seguro un **artefacto**, no un edge.
- **Por sesión/régimen:** condicionar por sesión no rescata nada (London sale peor, ~0.46;
  el resto ~0.50–0.51, sin señal explotable).
- **BTC ahora (1h):** los 12 análogos más parecidos dan una distribución forward **minúscula
  y mixta** (+1 barra −0.07%, +4 −0.26%, +12 +0.23%), con permutación **p 0.62 / 0.33 / 0.69**:
  no dice nada accionable.

**Conclusión honesta:** la semejanza de forma de ventanas de precio —ni macro ni intradía—
**no predice la dirección futura de BTC**. Confirmado ahora con muestra grande y control de
multiplicidad, así que ya no es "no alcanzó la muestra": es que **el edge no existe** a este
nivel. El valor del motor es como **lente de escenarios** (mostrar casos parecidos y su
dispersión), nunca como señal. Recomiendo cerrar esta vía de análogos puros y, si se quiere
seguir, combinarla con el contexto que SÍ mostró señal antes (régimen VIX/ADX del estudio de
filtros), no usar la forma sola.

---

## 2. Metodología

**Datos.** Binance, ~4 años (2022-06 → 2026-06): **BTC, ETH, SOL, BNB** en **1h** (~35.000
barras c/u) y **15m** (~140.000 barras c/u). Decenas de miles de casos por par/escala.

**Motor (reusado de fase 1).** Ventanas de log-precio de largo L, **z-normalizadas**;
distancia euclidiana z-norm; para cada t se buscan los **K=20** vecinos más parecidos entre
las ventanas que terminan en s con **s ≤ t−L** (no solape) y **s+Hmax ≤ t** (resultado ya
conocido): **cero look-ahead** en el match y en el "qué pasó después". KNN eficiente con
`argpartition` (no se ordena toda la historia). Horizontes forward **+1, +4, +12 barras**;
largos **L = 16, 24, 48**.

**Disciplina anti-data-mining (lo nuevo de esta fase):**
1. **Split temporal IS 60% / OOS 40%.** Se mide el efecto en ambos; un edge solo es creíble
   si aparece en **IS y OOS con el mismo signo** (columna `IScoh`).
2. **Permutación vs baseline aleatorio:** en cada t, además del análogo se evalúan 200
   "estrategias" que eligen K vecinos **al azar** del mismo pozo de candidatos, puntuadas
   contra los **mismos** retornos realizados. p = P(una selección aleatoria iguale o supere
   al análogo). Comparación justa (el solape de los retornos afecta a ambos por igual).
3. **Baseline tonto** ("deriva": predecir el signo de la media incondicional) como piso.
4. **Multiplicidad:** se prueban 72 hipótesis → se reportan **Bonferroni** (0.05/72) y
   **Benjamini-Hochberg (FDR 5%)**, y cuántos "significativos" se esperarían por azar.
5. **Tamaño efectivo ≈ barras_de_prueba / horizonte** (los forward solapan).

---

## 3. Resultados (72 configuraciones)

Distribución de los aciertos OOS de los análogos: prácticamente todos en **0.485–0.527**,
media ~0.50. Correlación predicho-vs-realizado entre **−0.034 y +0.043** (media ~0). El
"skill" sobre el baseline tonto es ~0 (mediana levemente **negativa**). Ejemplos del bloque
BTC (todos los 72 quedan en `research/analog_intraday.json`):

| par | tf | L | H | OOS n | effN | hitAn | hitBase | rnd | p | skill | corr | IScoh |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | 1h | 16 | 1 | 4671 | 14011 | 0.505 | 0.514 | 0.501 | 0.30 | −0.009 | −0.008 | sí |
| BTC | 1h | 24 | 4 | 4670 | 3502 | 0.488 | 0.503 | 0.501 | 0.96 | −0.015 | +0.003 | no |
| BTC | 1h | 24 | 12 | 4670 | 1168 | **0.527** | 0.509 | 0.502 | **0.00** | +0.018 | +0.043 | sí* |
| BTC | 15m | 24 | 1 | 4672 | 56053 | 0.511 | 0.508 | 0.500 | 0.075 | +0.003 | +0.008 | sí |
| ETH | 1h | 24 | 1 | 4670 | 14008 | 0.517 | 0.504 | 0.500 | 0.01 | +0.013 | −0.006 | sí |
| ETH | 1h | 48 | 12 | 4670 | 1168 | 0.485 | 0.512 | 0.500 | 0.985 | −0.026 | −0.004 | no |

\* coherencia "sí" sólo por el SIGNO; el efecto IS real es +0.0003 (nulo) — ver §4.

### Multiplicidad (anti-data-mining)

| | valor |
|---|---|
| Hipótesis OOS probadas | **72** |
| Significativos p<0.05 **sin corregir** | **5** |
| Esperados por puro azar (0.05×72) | **3.6** |
| Umbral **Bonferroni** (0.05/72) | 0.00069 |
| Significativos tras Bonferroni | **1** |
| Benjamini-Hochberg (FDR 5%) — rechazos | **1** |
| Sobreviven (Bonferroni **y** signo coherente IS↔OOS **y** skill>0) | **1** |

El único sobreviviente: **BTC 1h, L=24, H=12** (OOS hit 0.527, p≈0). Pero:
- su **acierto IS es 0.501** (vs aleatorio IS 0.5007) → **efecto in-sample ≈ +0.0003, nulo**:
  la "coherencia" es casualidad de signo, no un edge estable;
- su **p≈0 está inflado**: a H=12 las predicciones del análogo están **autocorrelacionadas**
  (ventanas vecinas → vecinos parecidos → predicciones parecidas), así que la distribución
  nula aleatoria (que refresca el azar en cada t) es **demasiado estrecha** y el p sale
  **anti-conservador**. El tamaño efectivo real es ~1.168, no 4.670.

En resumen: **0 hallazgos creíbles**. 5/72 ≈ tasa de falsos positivos del azar; el único que
cruza Bonferroni se cae al mirar su efecto in-sample y su autocorrelación. Es justo lo que
la disciplina anti-data-mining debe atrapar, y lo atrapó.

---

## 4. Condicionamiento por sesión (BTC, L=24, H=4, OOS)

Acierto direccional del análogo por sesión de la barra de decisión:

| escala | Asia | Londres | NY | Fuera |
|---|---|---|---|---|
| 1h | 0.514 (n1168) | **0.462** (n1168) | 0.512 (n1753) | 0.495 (n584) |
| 15m | 0.500 (n1168) | 0.509 (n1168) | 0.510 (n1752) | 0.500 (n584) |

London sale **peor** en 1h (0.46) —rima con el hallazgo del estudio de filtros SMC, donde
"Solo NY/excluir London" se comportaba raro— pero el resto ronda 0.50–0.51: **el
condicionamiento por sesión no concentra ningún edge de análogo explotable**. Es, a lo más,
un sesgo direccional de base por sesión, no producto de la selección por semejanza.

---

## 5. BTC ahora — análogos intradía más parecidos (1h, L=24)

Consulta **2026-06-11, $63.702** · 35.009 candidatos históricos. Las distancias (1.6–1.8)
son mucho menores que en macro (~3): a intradía las formas se repiten más, pero igual **no
informan**.

| análogo | dist | +1b | +4b | +12b |
|---|---|---|---|---|
| 2023-05-28 | 1.61 | +0.36% | +1.10% | +2.52% |
| 2022-10-26 | 1.62 | +0.36% | −0.20% | +0.70% |
| 2024-04-07 | 1.67 | −0.39% | −1.10% | −0.99% |
| 2022-09-02 | 1.71 | −0.03% | −2.12% | −2.10% |
| 2025-05-08 | 1.71 | +0.33% | +1.77% | +1.91% |
| 2024-10-28 | 1.72 | −0.13% | +0.49% | +1.76% |
| 2025-10-20 | 1.74 | +0.55% | +0.61% | +0.24% |
| 2025-08-03 | 1.76 | +0.10% | −0.09% | +0.30% |
| … (12 en total) | | | | |

**Distribución forward agregada + permutación:**

| horizonte | media | mediana | %+ | p (2 colas) |
|---|---|---|---|---|
| +1 barra | −0.07% | −0.03% | 42% | 0.62 |
| +4 barras | −0.26% | −0.47% | 33% | 0.33 |
| +12 barras | +0.23% | +0.27% | 58% | 0.69 |

Magnitudes minúsculas, signos mezclados y permutación no significativa: **hoy los análogos
intradía no dan ninguna inclinación accionable.**

---

## 6. Veredicto honesto y limitaciones

- **No hay edge.** Ni macro (fase 1, poca muestra) ni intradía (fase 2, muchísima muestra).
  La diferencia importa: ahora **no es excusa de muestra** — con decenas de miles de casos,
  si hubiera una señal direccional por semejanza de forma, aparecería. No aparece.
- **La disciplina funcionó:** 5/72 "significativos" = exactamente lo que da el azar; el único
  que cruza Bonferroni se desarma al exigir coherencia in-sample y al corregir la
  autocorrelación. Sin esa disciplina, habríamos "encontrado" un edge falso (BTC 1h H=12).
- **Caveat técnico (honesto):** la permutación por-t es anti-conservadora para horizontes
  largos porque las predicciones del análogo están autocorrelacionadas; el efecto verdadero
  se ve mejor en el **tamaño del efecto** (≈0 en todas) y en la **coherencia IS↔OOS**, no en
  el p crudo. Por eso no me apoyo en un p<0.05 aislado.
- **Qué sí haría con esto:** usar el motor como **explorador de escenarios/dispersión**
  (visual), y —si se quiere insistir en predicción— **combinar** la semejanza con las
  variables que SÍ tuvieron señal en el estudio de filtros (régimen **VIX<25 + ADX>25**),
  porque ahí el edge venía del **régimen**, no de la forma. La forma pura, sola, no sirve.

---

## 7. Archivos (worktree `research-smc-filtros`)

- `research/analog_intraday.py` — harness intradía: validación IS/OOS, permutación vs
  aleatorio, multiplicidad (Bonferroni + BH-FDR), sesión y aplicación a BTC actual.
  Reusa `analog_engine._zwindows` / `find_analogs` de la fase 1.
- `research/analog_intraday.json` — resultados completos de las 72 configuraciones + foto
  actual de BTC.
- `research/analogos_intradia_2026-06-12.md` — este informe.

**Cómo correrlo:** `/Users/hugh/crisol/nexux/.venv/bin/python research/analog_intraday.py` (~10 min).
