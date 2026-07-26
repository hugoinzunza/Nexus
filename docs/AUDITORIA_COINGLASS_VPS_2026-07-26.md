# Segunda auditoría CoinGlass + orden del VPS — 2026-07-26

Pedida después de encontrar cuatro defectos de la misma familia en un día. Alcance:
buscar lo que se nos pasó en el módulo, y revisar el orden del VPS y todo lo que
recolecta y entrega. Verificado contra producción, no razonado.

---

## A. VPS — lo que está sano (para no re-auditarlo)

| | |
|---|---|
| `nexus.service` | **active running** |
| `nexus-coinglass-visual.timer` | activo · **79 capturas en 6 h** (esperadas ~72) |
| `nexus-collector.timer` | activo · klines frescos |
| `nexus-coinsignals.timer` | activo · corre cada minuto |
| cron del estudio pareado | instalado (`7 19 * * *`) |
| disco | 17% de 38 G · `data/` 157 M · repo 537 M |

Frescura medida: dashboard 0,9 min · visual 4,5 min · coinsignals 4,8 min · archivo
del libro 4,5 min y creciendo. Nada rancio.

## B. VPS — hallazgos

### V1 · P1 — El precio de referencia depende de una API que nos limita

`visual_collector.public_btc_price()` llama a la API pública de futuros de Binance
**en cada captura**: 288 veces al día. Binance responde **429 Too Many Requests**, y
en las últimas 6 horas pasó **5 veces** (~7% de los ciclos, ~20 al día).

Dos cosas lo hacen peor que un error transitorio:

1. **Se llama al final**, después de todo el scraping (mapa, heatmap, delta, muros).
   Un 429 ahí tira a la basura trabajo que ya salió bien.
2. **El reintento cuesta un navegador completo**: `collect_with_retry` reinicia
   Chrome, con pico de 1,3 GB y ~60 s de CPU. Unos 20 reinicios diarios evitables.

Por qué existe esa llamada: es el precio **independiente** con el que
`_assert_chart_matches_symbol` verifica que el perfil de Chrome no haya cambiado de
símbolo. Es una protección legítima —fallar cerrado si el gráfico no es BTC— y no
hay que quitarla.

**Fix propuesto**: mantener Binance como primera opción y **caer a los klines
locales** (`data/klines_BTCUSDT_1h.json`, que el propio `nexus-collector.timer`
refresca) cuando responda 429. Sigue siendo una referencia independiente de
CoinGlass, así que conserva la propiedad de seguridad; no se puede limitar por tasa;
y para un chequeo de ±25% un cierre de hasta una hora sobra.

**No lo apliqué**: toca el colector en producción, y un guard mío ya le costó un
ciclo de captura antes. Queda propuesto para que lo autorices.

### V2 · P2 — Timeouts de página, absorbidos por el reintento

2 veces en 6 h: `Page.wait_for_selector: Timeout 90000ms exceeded`. Es CoinGlass
lento o el canvas que no aparece. El reintento lo cubre y por eso las 79 capturas
salieron. No amerita cambio, sí amerita no confundirlo con el 429: son causas
distintas y el journal los mezcla.

### V3 · P3 — 13 archivos de respaldo acumulados en `data/`

`*.bak`, `*.pre_*`, `*pre-*` de intervenciones de los últimos días. No molestan
(157 M en total, disco al 17%) pero ensucian el directorio y confunden al buscar el
archivo vigente. Conviene una limpieza puntual, no automática: algunos son respaldos
deliberados.

## C. Módulo — hallazgos nuevos

### M1 · P3 latente — `tanh(delta / 20_000_000)`: el 20% del score en una constante

`visual.py:431` normaliza el componente de delta del libro con una constante
**absoluta** de 20 M. Es exactamente la familia de defectos de hoy, así que lo medí
antes de opinar:

| | |
|---|---|
| mediana de \|delta\| | **8,10 M** |
| puntos sobre la constante (20 M) | 1 de 44 |
| puntos que saturan el `tanh` (>40 M) | **0 de 44** |
| aporte al score del último dato | +5,70 de 100 puntos |

**No está mordiendo**: el `tanh` trabaja en su zona casi lineal y el componente varía
suave. Pero es escala-dependiente por construcción: si la liquidez de BTC se
duplicara, todos los deltas se duplicarían, el componente empujaría a saturación y la
composición del score cambiaría **en silencio**, sin que nada lo avise.

**Recomendación**: no cambiarlo ahora —está calibrado y tocarlo movería el score sin
evidencia— pero **medirlo**. Un chequeo barato: publicar en `coverage` qué fracción
de la serie supera la constante, y avisar en la UI si pasa de, digamos, un tercio.
Eso convierte un riesgo silencioso en uno visible, que es la política del módulo.

### M2 · P3 — `log1p(amount / 1_000_000)` en `_weighted_side`

Mismo tipo (unidad de escala fija en millones) pero el logaritmo amortigua mucho el
efecto. Se deja anotado por completitud, sin acción.

## D. Lo que se corrigió hoy, para que el registro quede en un solo lugar

Cuatro defectos, **todos de la misma familia** —umbral absoluto sobre un dato de
escala variable, o encuadre dominado por valores extremos— y **todos invisibles en
fixtures y visibles en producción**:

1. Marcadores de flujo cortados en `maxUsd * 0.55`: con el bid persistente de 78,7 M
   fijando el máximo, se dibujaban **0 de 14 eventos**.
2. Encuadre del gráfico de bandas estirado por los muros a ±5%: se leían **6 de 10**
   bandas. Ya había pasado en el gráfico del libro.
3. Umbral de US$1 M de CoinGlass: el **48%** de los eventos de flujo eran muros
   cruzando el umbral de ida y vuelta, no comportamiento del mercado.
4. `minimum_usd=5_000_000` en `_nearest`: reportaba el imán de abajo **35% más
   lejos**, y la tasa de alcance a 4 h pasó de ~10% a 16% al corregirlo.

## E. Conclusión y orden propuesto

El VPS está **ordenado y sano**. Lo único con impacto real es **V1**, y no es de
datos sino de eficiencia y fragilidad: ~20 reinicios de navegador diarios por una
dependencia externa que se puede evitar sin perder la protección que justifica su
existencia.

Orden que propongo:

1. **V1** — fallback a klines locales (1 función, con test). Necesita tu OK porque
   toca el colector en producción.
2. **M1** — publicar la fracción de la serie que supera la constante de escala, y
   avisar en la UI. Sin cambiar el score.
3. **V3** — limpieza puntual de los 13 respaldos, revisando uno por uno.

Y una observación de método, porque explica por qué aparecieron cuatro defectos
juntos: **los fixtures del proyecto son demasiado benignos**. No tienen una ballena
de 78 M ni un umbral de plataforma ni niveles redondeados a cero. Cada vez que hoy
probé con el snapshot real del VPS apareció algo. Vale la pena que el fixture de
tests incorpore esos casos patológicos, y eso sí se puede hacer sin tocar producción.
