# Motor de análogos macro para BTC — analog forecasting honesto

**Fecha:** 2026-06-12 · **Worktree:** `research-smc-filtros`
**Objetivo:** dada la ventana de precio actual de BTC, buscar en toda la historia las
ventanas más parecidas y medir la distribución empírica de **qué pasó después** —
y, sobre todo, **validar con rigor si ese condicionamiento tiene edge real** o es ruido.
El objetivo NO es predecir; es medir honestamente.

---

## 1. Resumen ejecutivo (para Hugo)

Construí el motor completo y lo validé en serio. **Veredicto: a escala macro, los
análogos de BTC NO tienen edge predictivo demostrable.** La distribución de "qué vino
después" es estadísticamente **indistinguible de elegir fechas al azar**.

- En walk-forward (2018→2026), el acierto direccional de los análogos es **~0.47–0.53
  (cara o cruz)**. Un baseline tonto de "siempre sube" iguala o **supera** a los análogos
  en +4 y +12 semanas.
- El **p-valor frente a un baseline aleatorio nunca es significativo** (0.14 a 0.98). La
  correlación entre lo que el motor predice y lo que pasa es **nula o levemente negativa**.
- Los **mejores matches no aciertan más** (de hecho un poco menos): la calidad de la
  semejanza no compra poder predictivo.
- Para la foto de **hoy**, el test de permutación da p de dos colas **0.52 / 0.56 / 0.90**
  (1/4/12 semanas): la "señal" de los análogos actuales no se distingue del azar.

**Por qué (y esto es lo honesto):** BTC tiene ~11,7 años de historia (2014→2026), o sea
**~3 ciclos**. A escala macro, los casos verdaderamente independientes se cuentan con los
dedos (tamaño efectivo ~26–36 a 12 semanas). Con tan poca muestra, **aunque existiera un
edge macro, no podríamos demostrarlo** — y lo que medimos no muestra ni rastro de uno.

**Lo tangible que sí entrega** (con esa salvedad bien marcada): hoy las 8 ventanas más
parecidas a BTC están **partidas en dos** — la mitad precede a caídas (2022-05 → −30%,
2018-10 → −53%) y la otra mitad a subidas (2019-03 → +97%, 2020-03 → +48%). Mediana +12s
≈ +7% pero con un rango brutal (q10 −37% / q90 +62%). En cristiano: **los análogos no
inclinan la balanza**. El contexto macro sí es informativo como descripción: BTC $63.575,
**bajo su MA de 50 semanas ($91.751)**, RSI semanal ~35 (zona baja de ciclo), VIX 19, corr
BTC-SPX 0.5.

**Recomendación:** usar el motor como **herramienta de contexto/narrativa** (mostrar
"ciclos análogos" y su dispersión), **nunca como señal**. Sirve para encuadrar escenarios
y rangos, no para apostar dirección. El código queda reusable por si en la fase intradía
(más muestra) reaparece algo medible.

---

## 2. Metodología (innegociable)

**Datos.** BTC-USD diario desde Yahoo Finance (2014-09 → hoy, 4.287 días) forzando
resolución diaria con `period1/period2` (range=max devuelve mensual). Resampleo a
**semanal** (613 barras) y **quincenal** (307). SPX/VIX como contexto (`macro.py`).

**Representación.** Se compara la **forma** de la trayectoria: ventanas de log-precio de
largo L, **z-normalizadas** (resta media, divide desv. est.) → elimina nivel y escala,
quedando solo el patrón. Misma métrica que el matrix profile (STUMPY). Distancia:
euclidiana z-norm (principal) + DTW con banda de Sakoe-Chiba (opcional, tolera desfases).

**Anti-look-ahead (lo más crítico).** Para una consulta que termina en t, un vecino que
termina en s es válido solo si:
- **(a)** no se solapa con la consulta: `s ≤ t − L`, y
- **(b)** su resultado forward ya ocurrió antes de t: `s + max(horizonte) ≤ t`.

Con (a)+(b), tanto el *match* como el *"qué pasó después"* usan exclusivamente datos
anteriores a t. En el walk-forward, el retorno realizado en t+h se usa **solo para
puntuar** (evaluación OOS legítima), nunca para elegir el análogo.

**Horizontes:** +1, +4, +12 semanas. **L probados:** 13, 26, 52 barras. **k:** 8 vecinos,
con separación mínima L/2 para no contar 8 copias casi iguales del mismo tramo.

**Validación (3 capas):**
1. **Walk-forward direccional** (test desde 2018): acierto del signo predicho vs realizado,
   contra baseline de deriva y baseline **aleatorio** (k fechas al azar, 400 réplicas →
   p-valor que respeta la autocorrelación por solape).
2. **Edge de la media** vs distribución incondicional.
3. **Régimen:** BTC sobre/bajo su MA50s, y calidad del match (tercil de distancia).

**Honestidad de muestra.** Con horizonte H los t consecutivos comparten futuro (solape) →
no son independientes. Reporto **tamaño efectivo ≈ semanas/H** y uso el baseline aleatorio
(misma estructura de solape) para la significancia, no un binomial ingenuo.

---

## 3. Resultados de validación (walk-forward 2018→2026)

`hitAn` = acierto direccional del análogo · `hitBase` = baseline "deriva" · `rndMean` =
acierto medio de análogos aleatorios · `p_rnd` = P(azar ≥ análogo) · `skill` = hitAn−hitBase
· `corr` = correl(predicho, realizado). **Edge real ⇒ hitAn ≫ rndMean, p_rnd<0.05, corr>0.**

### Semanal

| L | H | n | effN | hitAn | hitBase | rndMean | p_rnd | skill | corr |
|---|---|---|---|---|---|---|---|---|---|
| 13 | 1 | 429 | 429 | 0.522 | 0.515 | 0.502 | 0.205 | +0.007 | −0.006 |
| 13 | 4 | 429 | 108 | 0.501 | 0.529 | 0.506 | 0.603 | −0.028 | −0.053 |
| 13 | 12 | 429 | 36 | 0.506 | 0.534 | 0.512 | 0.677 | −0.028 | −0.106 |
| 26 | 1 | 429 | 429 | 0.529 | 0.515 | 0.504 | 0.152 | +0.014 | −0.056 |
| 26 | 4 | 429 | 108 | 0.490 | 0.529 | 0.509 | 0.863 | −0.040 | −0.152 |
| 26 | 12 | 429 | 36 | 0.490 | 0.534 | 0.514 | 0.958 | −0.044 | −0.152 |
| 52 | 1 | 274 | 307 | 0.467 | 0.507 | 0.500 | 0.882 | −0.040 | −0.076 |
| 52 | 12 | 274 | 26 | 0.474 | 0.533 | 0.513 | 0.983 | −0.058 | −0.220 |

### Quincenal (resumen)

| L | H | n | effN | hitAn | hitBase | p_rnd | corr |
|---|---|---|---|---|---|---|---|
| 13 | 12 | 209 | 35 | 0.536 | 0.569 | 0.823 | −0.174 |
| 26 | 12 | 136 | 26 | 0.596 | 0.596 | 0.140 | −0.361 |

**Lectura:** en ninguna configuración el análogo supera al azar de forma significativa.
El acierto ronda 0.5; el baseline de deriva suele ser mejor; la correlación predicho-vs-
realizado es **negativa** casi siempre (a 4 y 12 semanas, lo que el motor "espera" tiende a
salir levemente al revés). El único hit alto (quincenal L=26 +12s, 0.596) **iguala** al
baseline (skill 0), tiene corr −0.36 y p=0.14: no es señal.

### Régimen (semanal, L=26) — acierto direccional

| grupo | +1s | +4s | +12s |
|---|---|---|---|
| todos | 0.529 | 0.490 | 0.490 |
| BTC alcista (>MA50s) | 0.521 | 0.500 | 0.507 |
| BTC bajista (<MA50s) | 0.545 | 0.469 | 0.455 |
| **buen match** (dist baja) | 0.549 | **0.396** | **0.403** |
| match pobre | 0.519 | 0.537 | 0.533 |

**Clave:** los **mejores matches aciertan menos** a 4–12 semanas (0.40). Que la historia
"se parezca mucho" no ayuda; si acaso, engaña. Es la prueba más dura contra la hipótesis.

---

## 4. Aplicación a BTC HOY (2026-06-12, $63.575)

### Las 8 ventanas históricas más parecidas (semanal, L=26 ≈ 6 meses)

| análogo | dist | +1s | +4s | +12s | qué era |
|---|---|---|---|---|---|
| 2022-05-15 | 2.92 | −3.2% | −15.7% | −30.1% | techo previo al desplome 2022 |
| 2015-05-03 | 3.07 | −0.0% | −4.3% | +19.7% | fin de bear, pre-recuperación |
| 2021-09-26 | 3.29 | +10.9% | +34.4% | +7.8% | rally a máximos de nov-2021 |
| 2019-03-31 | 3.35 | +23.6% | +25.3% | **+97.2%** | arranque rally 2019 |
| 2018-06-10 | 3.58 | −4.3% | −0.2% | +6.9% | bear 2018 lateral |
| 2018-10-07 | 3.77 | −4.8% | −3.5% | **−53.5%** | pre-capitulación nov-2018 |
| 2022-10-02 | 3.78 | +2.1% | +8.0% | −12.3% | rebote antes de FTX |
| 2020-03-22 | 4.34 | +1.6% | +21.0% | +47.6% | fondo COVID, pre-rally |

**Mitad alcista, mitad bajista.** Es el retrato perfecto de "no hay señal": ventanas de
forma parecida preceden tanto a +97% como a −53%.

### Distribución agregada + test de permutación

| H | media | mediana | %+ | q10 | q90 | baseline | percentil | **p (2 colas)** |
|---|---|---|---|---|---|---|---|---|
| +1s | +3.2% | +0.8% | 50% | −4.5% | +14.7% | +1.0% | 0.74 | **0.52** |
| +4s | +8.1% | +3.9% | 50% | −7.7% | +28.0% | +4.1% | 0.72 | **0.56** |
| +12s | +10.4% | +7.4% | 62% | −37.1% | +62.5% | +12.3% | 0.45 | **0.90** |

El p-valor de dos colas (¿la media de los análogos se distingue de 5.000 selecciones al
azar?) es **0.52 / 0.56 / 0.90**: **completamente no significativo**. A 12 semanas la media
de los análogos (+10.4%) es incluso **menor** que la incondicional (+12.3%). La dispersión
(q10 −37%, q90 +62%) es enorme.

*(Quincenal L=13 cuenta lo mismo, con sesgo levemente más bajista: media +12s −0.5% vs
baseline +24%, p=0.21 — tampoco significativo.)*

### Cross-check STUMPY (motifs macro, descriptivo)

Los pares de ventanas de 26 semanas más parecidos de toda la historia: 2019-01 ≈ 2020-09,
2016-08 ≈ 2020-09, 2015-08 ≈ 2023-07. Son tramos de **acumulación pre-markup** — coherentes
entre sí, pero es una vista descriptiva (el matrix profile mira toda la serie, no sirve de
pronóstico).

### Contexto top-down (descriptivo, NO predictivo)

BTC **$63.575, bajo su MA50s ($91.751)** (≈ −31% del promedio anual), **RSI semanal ~35**
(zona baja de ciclo), **VIX 19** (calma), **corr BTC-SPX 0.5** (acoplado risk-on). En el
mapa Wyckoff del analista que sigue Hugo, esto encaja con una fase de
**manipulación/spring o acumulación temprana** tras distribución — pero eso es *narrativa*:
los números de arriba dicen que los análogos no la confirman ni la niegan con poder real.

---

## 5. Veredicto honesto y limitaciones

- **No hay edge condicional macro demostrable.** Acierto ≈ azar, p no significativos, corr
  ≤ 0, y los mejores matches no ayudan. Es un **null result sólido**, no un "no encontré".
- **Causa estructural: muestra.** ~3 ciclos de BTC ⇒ tamaño efectivo ~26–36 a 12 semanas.
  Es físicamente imposible validar un edge macro con esto; lo honesto es decirlo y no
  vender una señal que no aguanta.
- **Sesgo de supervivencia/no estacionariedad:** BTC pasó de microcap a activo macro; un
  análogo de 2015 vive en otro régimen estructural. La z-normalización iguala forma, no
  contexto.
- **Qué sí vale:** el motor como **lente de escenarios** — mostrar los ciclos parecidos y su
  **dispersión** comunica incertidumbre mejor que una flecha. Y el andamiaje queda listo
  para la **fase intradía** (4h/1h), donde hay miles de casos y un edge pequeño *sí* podría
  ser medible. Ahí esta misma maquinaria (sin look-ahead, con baseline aleatorio y permutación)
  es la forma correcta de testearlo.

---

## 6. Archivos (worktree `research-smc-filtros`)

- `research/btc_history.py` — BTC diario máximo (Yahoo) + resampleo semanal/quincenal.
- `research/analog_engine.py` — **motor reusable**: `find_analogs(ts, closes, t_index, L,
  horizons, k, metric)` → `{análogos, distribución forward, baseline, stats}`, anti-look-ahead;
  `top_motifs()` (STUMPY) para motifs macro.
- `research/analog_validate.py` — walk-forward, baseline aleatorio + permutación, régimen,
  tamaño efectivo.
- `research/analog_current.py` — aplicación a BTC hoy + test de permutación + contexto →
  `research/analog_current.json`.
- `research/data_macro/btc_daily_full.json` — caché del histórico.

**Cómo correrlo:** `/Users/hugh/Nexus/.venv/bin/python research/analog_current.py`
(usa el venv con numpy/stumpy instalados).
