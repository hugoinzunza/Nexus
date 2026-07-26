# Auditoría del módulo CoinGlass — 2026-07-26

Alcance: `modules/coinglass/` completo (module.py, visual.py, shadow.py,
visual_collector.py, public/app.js·html·css) tras el rework de esta semana.
Foco pedido por Hugo: errores, mejoras, y sobre todo **que el entregable gráfico
aporte a la toma de decisiones**. Research only; nada de esto toca el bot.

Método: lectura línea a línea + verificación de los hallazgos contra los datos
reales de producción (archivo del VPS), no contra fixtures.

---

## A. Errores encontrados

### A1 · P1 — El flujo de muros es invisible en producción (verificado con datos reales)

`drawOrderbook` filtra los marcadores de flujo con `corte = maxUsd * 0.55`.
Contra la captura real de producción: el muro mayor es **78,7M** (el bid de 61.300
que lleva días), así que el corte queda en **43,3M** — y la **mediana de muro es
1,8M**. Resultado: **un solo muro de 41 puede producir marcadores**. La
funcionalidad que Hugo pidió (ver qué muros nacen, se consumen o se retiran)
funciona en el fixture de prueba y **casi nunca en producción**, porque una sola
ballena persistente fija la vara para todos los demás.

El pie del gráfico sí cuenta todos los eventos (se calcula antes del filtro), lo
que agrava la confusión: el texto dice "3 retirados" y el gráfico no muestra
ninguno.

**Fix propuesto**: cortar por percentil de la distribución de muros (p.ej. top-N
eventos por monto, o `corte = percentil 80`), no por fracción del máximo.

### A2 · P1 — Semántica de color invertida entre pestañas

En el **Mapa visual** un clúster ARRIBA del precio se pinta **rojo** (es
resistencia/asks) y abajo **verde** (soporte/bids) — igual que el libro. En la
**brújula** del Radar es al revés: la aguja ARRIBA es **verde** y la de ABAJO
**roja** (`drawCompass`, líneas ~879-880). Mismo dato, colores opuestos según la
pestaña. Para tomar decisiones esto es peor que no tener color.

**Fix**: unificar. Propuesta: arriba=rojo, abajo=verde en todo el módulo (la
convención del libro), y que la brújula distinga sus agujas por posición y
etiqueta, no por color direccional.

### A3 · P2 — La salud del archivo histórico se publica pero no se muestra

Ayer dejamos `visual_book_archive` (bytes, última escritura, lleno) en la
respuesta de `/api/state` justamente para que "si deja de crecer, alguien se
entere". **app.js no lo renderiza en ninguna parte.** El dato existe y nadie lo
ve: el modo de falla exacto que se quería evitar.

**Fix**: una línea en el pie de la pestaña del libro ("archivo histórico: X MB ·
última escritura hace N min", en rojo si >30 min).

### A4 · P2 — `flujoDeMuros` pierde muros que comparten bucket

Los mapas `antes`/`ahora` usan `Map.set` con la clave del bucket: si dos muros
distintos caen en el mismo bucket de 0,05% **el segundo pisa al primero** (su
monto desaparece del diff), y si uno de los dos se retira no se genera evento
(el bucket sigue ocupado). Subcuenta eventos y subrepresenta montos.

**Fix**: acumular por bucket (`usd += ...`) y comparar montos entre capturas
además de presencia (un bucket cuyo monto cae >50% también es un retiro parcial).

### A5 · P2 — Deduplicación O(n²) sobre ~11.500 muros por redraw

En `drawOrderbook`, el etiquetado de muros grandes hace
`filter((m,i,arr) => arr.findIndex(...) === i)` sobre todos los muros en rango:
con 288 capturas × ~40 muros son ~11.500 elementos → ~130M comparaciones **en
cada redraw** (cada cambio de zoom, cada resize). En desktop se siente; en móvil
—donde Hugo mira esto— congela.

**Fix**: dedup con `Set` por clave `lado:precio_redondeado` (O(n)).

### A6 · P3 — "cada 5 min" está cableado en el pie del libro

`drawOrderbook` escribe "capturas · cada 5 min" fijo. Es el mismo defecto que ya
corregimos en la pestaña Flujo (el "4h" cableado que resultó ser 1h): si el timer
cambia o hay huecos, miente. El intervalo real es medible con la mediana de los
`captured_at` que ya están en memoria.

### A7 · P3 — `probabilidad_de_alcance` reporta el `n` del último horizonte

`salida["n"] = bloque.get("n")` va dentro del loop de horizontes: el `n` que se
muestra en la UI ("n=X barras") corresponde al último horizonte iterado, no
necesariamente al de la celda que el usuario mira. Menor (los n son parecidos),
pero es el tipo de detalle que en este proyecto preferimos exacto.

### A8 · P3 — Código muerto de validación en `api_post`

`module.py:179-181`: el chequeo de `execution_enabled`/`mode` solo retorna 400
para `ingest`; para `visual-ingest` el caso lo cubre `normalize_visual_snapshot`
aguas abajo. No hay agujero de seguridad (verificado), pero el condicional
sugiere una protección que no está haciendo nada por esa rama. Simplificar o
comentar.

### Lo que se revisó y está BIEN (para no re-auditarlo)

- XSS: todo lo que viene del payload pasa por `escapeHtml` (incluido `reason()`).
- El token de ingesta usa `hmac.compare_digest`; los GET exigen sesión.
- Escrituras atómicas (`.tmp` + `os.replace`, chmod 600).
- El recorte del historial público es por tiempo, no por conteo (los huecos se ven).
- La leyenda del libro ya no afirma "spoofing"; declara las tres explicaciones.
- El Radar no publica dirección probable (las reglas direccionales quedaron
  refutadas OOS) y lo dice.
- `stale`/`age` distinguen edad del archivo vs edad del dato.
- El colector degrada con gracia (checkbox, archivo local) y reporta en el log.

---

## B. Mejoras de valor para decisión (más allá de los bugs)

### B1 — Una "lectura del momento" única, arriba de todas las pestañas

Hoy, para armarse la película, hay que visitar 4 pestañas: el imán más cercano
está en Radar, el flujo de muros en Libro, las liquidaciones en Resumen, la
frescura en Mapa visual. Propuesta: una franja compacta y **siempre visible**
con los 4 datos que cambian decisiones:

> `imán más cercano: ABAJO a 0,8% (alcanzado 62% en 4h) · muro dominante: 78,7M
> bid en 61.300 (lleva 2 días) · flujo 1h: 3 nuevos / 1 consumido / 2 retirados ·
> captura hace 4 min`

Todo eso ya se calcula; es solo composición. Es la mejora con mejor razón
valor/esfuerzo del módulo.

### B2 — Fusionar las pestañas "Mapa visual" y "Radar"

Ambas muestran los componentes del mismo indicador (`visual-components` y
`model-components` son casi la misma lista) y el score aparece dos veces. Son
las dos pestañas más nuevas y quedaron solapadas. Una sola pestaña "Radar" con:
brújula + mapa de niveles + componentes + alcance, y muere la duplicación que el
propio Hugo marcó como "mucha información".

### B3 — El muro dominante merece su propia historia

El bid de 78,7M en 61.300 lleva **días** en las capturas. Esa persistencia es
información (un muro que sobrevive semanas es más creíble que uno de 10 min) y
hoy no se muestra en ninguna parte: cada captura lo pinta como si fuera nuevo.
Con el archivo append-only ya se puede calcular "edad del muro" (cuántas
capturas seguidas lleva un bucket ocupado con monto similar) y etiquetarla.

### B4 — Los umbrales del gráfico deberían ser relativos al régimen

`drawVisualLevels` filtra clústers con `>= 5M` fijo y el libro marca "grandes"
por USD absoluto. La lección del video del ex-Goldman (tamaño/volumen habitual,
no tamaño absoluto) aplica acá: 5M en un día muerto es mucho, en un día de
volatilidad es ruido. Mientras el estudio de normalización no esté hecho, al
menos declarar el umbral en la leyenda.

---

## C. Vincular CoinGlass al bot — el mapa honesto

Lo que la evidencia permite y no permite HOY:

| Uso posible | Estado de la evidencia |
|---|---|
| **Contexto visual** (Radar) | Ya existe. Único uso justificado hoy. |
| **TP en el muro/imán** | **Refutado** con proxies de estructura (capar el TP empeora monótonamente). Con muros reales: sin datos aún. |
| **SL tras el muro/imán** | **Refutado** como regla (es régimen, no gestión; resta en 1h). |
| **Detonante de entrada** | Lo intenta `shadow_plan` v0 (score ≥25). Muestra forward diminuta; las reglas direccionales de CoinGlass quedaron **refutadas OOS**. Lo más lejano. |
| **Veto/anulación de entrada** | **Sin evidencia aún, pero es el candidato más prometedor** — ver abajo. |

Por qué el veto es el candidato: (1) un filtro que solo REMUEVE trades no puede
inflar el edge por look-ahead de ejecución, solo reduce muestra — es la clase de
regla más barata de validar y la menos peligrosa de desplegar; (2) su premisa
("un muro real en el camino frena el precio") es exactamente lo que el estudio
pareado `muros_vs_niveles_vacios` empieza a medir **mañana** con ~11.000
observaciones/día; (3) encaja con el hallazgo de que el plan actual muere por
trades que no llegan ni a 1R — si los muros opuestos cercanos predicen esos
fracasos, el veto ataca la herida real.

**Compuertas (gates) antes de que NADA toque al bot:**

1. **Gate 1 — mecanismo**: el estudio pareado muestra que los muros frenan
   (alcance menor) o rebotan (reacción mayor) vs niveles vacíos, con CI que no
   cruza cero. Semanas. Si falla, todo el resto muere acá y nos ahorramos meses.
2. **Gate 2 — relevancia para NUESTROS trades**: las columnas contrafactuales de
   BOT2 (abajo) muestran mejora pareada sobre los mismos setups del Diario, IS/OOS,
   sin depender del top 1%. Meses.
3. **Gate 3 — implementación**: recién ahí, un flag en config, **apagado por
   defecto**, sin tocar el criterio pre-registrado de Fase 2, con su propio
   período de dry-run.

## D. BOT2 — qué recomiendo (y qué no)

**No recomiendo un segundo bot con su propia estrategia y su propio universo.**
Dos resultados independientes no se pueden comparar limpio: cualquier diferencia
puede ser régimen, universo o suerte, y ya medimos que el forward produce ~1,3
días independientes por semana — dos bots dividirían esa evidencia escasa en dos
pozos incomparables.

**Recomiendo BOT2 como "Diario B": un evaluador contrafactual sobre los MISMOS
setups del bot real.** Para cada setup que el Diario crea (partiendo por BTC, que
es lo que CoinGlass captura):

- registra el contexto CoinGlass en el momento del setup (el unidor
  `coinglass_imanes_forward.py` ya hace la mitad de esto);
- evalúa en paralelo un set de reglas **predefinidas y congeladas** — R1: vetar
  si hay muro opuesto a menos de X% del camino al TP1; R2: TP recortado al muro;
  R3: SL tras el muro — y simula qué habría pasado con cada una;
- guarda el resultado como columnas junto al trade real, igual que la columna
  CDC-8 que ya existe (patrón probado, tarea #19);
- compara BOT1 vs BOT2 **pareado**: mismos trades, misma ventana, la única
  diferencia es la regla. Eso convierte cada trade real en evidencia doble.

Propiedades: paper-only por construcción (no hay ruta de ejecución), no importa
CoinGlass desde `modules/` de trading (join offline por `captured_at`), no toca
el Diario oficial ni su P&L, y el día que una regla pase el Gate 2, la migración
al bot real es un flag — porque la regla ya corrió meses sobre los trades reales.

Costo estimado: el recolector de contexto ya existe; el evaluador contrafactual
es un script de research + un cron como el del estudio pareado; la vista web
comparativa puede esperar a que haya algo que mirar.

**Advertencia de expectativa**: con ~15 setups BTC/43 días, BOT2 acumula lento.
Por eso los gates están en este orden — el estudio pareado (11k obs/día) decide
rápido si la premisa vive; BOT2 decide despacio si sirve para NUESTROS trades.

## E. Orden propuesto de ejecución

1. Fixes A1-A5 (los dos P1 y los tres P2) + mejora B1 (lectura del momento) — un
   solo cambio de UI coherente.
2. B2 (fusionar pestañas) en el mismo pase si no infla el diff.
3. BOT2 v0: congelar las reglas R1-R3 por escrito ANTES de mirar resultados,
   y dejar el evaluador corriendo en cron junto al estudio pareado.
4. Esperar Gate 1 (~semanas) antes de invertir nada más en la vía "muros".
