# Auditoría técnica integral y adversarial — NexUX

Fecha: 2026-07-24 · Commit auditado: `1a02d00` (+ correcciones en `0b8ee01`)
Alcance: ingeniería de software, estadística retrospectiva, calidad de datos,
seguridad y observabilidad. **No contiene decisiones financieras ni
recomendaciones de operar.**

Método: verificación directa contra código, tests, datos y configuración. Cinco
auditorías paralelas por componente + verificación propia de cada hallazgo grave
citando archivo:línea. Nada se da por bueno porque un resumen previo lo diga.

---

## 1. Resumen ejecutivo

El proyecto está **notablemente mejor aislado de lo habitual** en su capa de
riesgo: no existe un solo camino de código entre la investigación (CoinSignals,
CoinGlass, BTA) y la ejecución. Lo verifiqué a nivel de imports, no de
documentación: `grep` de `modules.bot|market_order|BinanceFutures|_trade_creds`
sobre `modules/coinglass/` y `modules/coinsignals/` devuelve **cero**, y a la
inversa también. Las llaves de trading (`BINANCE_TRADE_*`, `deploy/trade.env`)
están separadas de las del colector por diseño explícito
(`modules/bot/executor.py:108-111`).

Los problemas reales no están en "el bot va a operar solo". Están en tres
familias:

1. **Medición**: el componente de mayor peso del Radar visual se muestrea de una
   columna del gráfico que probablemente no es la vigente, y hasta hoy nada lo
   medía.
2. **Potencia estadística**: el criterio de decisión de la Fase 2 no puede
   distinguir éxito de fracaso con la muestra que él mismo exige.
3. **Superficie de exposición**: un token de ingesta compartido y las llaves de
   la cuenta principal conviven con un Chrome que navega un sitio de terceros.

Ninguno pone en peligro fondos hoy (kill-switch y `live:false` verificados en el
VPS), pero los tres bloquearían cualquier integración futura seria.

---

## 2. Estado real verificado

| Componente | Estado verificado | Evidencia |
|---|---|---|
| Bot / ejecución | `live:false`, kill ausente (dry-run corriendo), 0 órdenes reales | endpoint `/m/bot/api/state` en VPS: `live: False, kill: False` |
| Config vigente | rr≥5 global, 5 pares, `require_disc:false`, slippage 0.3 | `config/nexus.json` |
| Ejecución tocada desde 07-05 | **No**: solo metadata (`phase_id`, `entry_model`, `activation_price`) | `git diff 8734cf9..HEAD -- modules/bot/executor.py` = +2 líneas |
| Aislamiento research↔ejecución | **Cero imports cruzados**, en ambos sentidos | grep verificado; test `test_coinglass_visual.py:351-361` |
| Llaves de trading | Separadas; el ejecutor queda inerte sin `BINANCE_TRADE_*` | `modules/bot/executor.py:108-111` |
| Secretos en git/HTML/JS | Ninguno literal; keys por env | grep sobre diff, `modules/*/public/`, `core/*.html` |
| CI | pytest en Python 3.12 y 3.14 | `.github/workflows/ci.yml` |
| Suite | **177/177 verde** | ejecución local en `0b8ee01` |
| Fase 1 V2 | n=7 cerrados, 71% WR, +0.344R; 2 abiertos; día 6 de 21 | `data/bot_trades.json` del VPS |
| Fase 1 V1 | archivada con justificación documentada | `docs/BOT_RELANZAMIENTO.md` (rollover 07-18) |

---

## 3. Hallazgos

### P0-1 · El 50% del score del Radar se muestrea de una columna del pasado

`modules/coinglass/visual_collector.py:366` toma el heatmap con
`x_ratio=0.75`. El heatmap de CoinGlass es tiempo(x) × precio(y): el 75% del
ancho en una vista de 24 h es **varias horas atrás**, no la columna vigente. Ese
barrido produce `heatmap_attraction`, que pesa **0.50** del puntaje
(`visual.py:307-311`), y sus distancias se comparan contra un precio **live** de
Binance pedido después de cerrar el browser (`visual_collector.py:373-382`).

Dos agravantes verificados:
- El commit que lo introdujo (`7e0d191`) se titula *"scan **current** chart
  layers"* y su diff es exactamente `-x_ratio=0.975` → `+x_ratio=0.75`: movió el
  muestreo **lejos** de la columna reciente.
- El fixture de test construido desde una captura real trae tooltips del heatmap
  marcados `14:50` con `captured_at` a las `18:00` UTC
  (`tests/test_coinglass_visual.py:32,53-60`).

**Corregido en parte (`0b8ee01`)**: ahora se mide. `coverage.heatmap_lag_seconds`
y `stale_heatmap` comparan el reloj del tooltip con la captura; en ese fixture da
**11.400 s (3h10m)**. El dato ya venía en cada nivel y se descartaba.

- **Qué lo refutaría**: que el 25% derecho del canvas sea margen de eje/proyección
  y 0.75 sea efectivamente la columna vigente. Ahora es comprobable con datos
  reales, no con opinión: basta leer el nuevo campo en producción.
- **Riesgo**: alto para cualquier validación. Todo estudio del Radar hecho antes
  de resolver esto mide una mezcla de presente y pasado.
- **Esfuerzo**: bajo (una línea + verificación empírica del canvas).
- **Criterio de promoción/descarte**: si el lag mediano > 15 min, el componente
  no puede usarse para horizontes de 1h sin recalcular contra el precio de su
  propio timestamp.
- **Naturaleza**: research/UI.

### P0-2 · El criterio de la Fase 2 no puede distinguir éxito de fracaso

El criterio pre-registrado es "≥20 trades dry **o** 3 semanas (lo primero), con
avgR neto > +0.2R **y** WR ≥ 55%". Calculado sobre la muestra real:

| Muestra | WR observado | IC 95% (Wilson) | ¿separa del 55%? |
|---|---|---|---|
| n=7 (hoy) | 71% | **[36%, 92%]** | No |
| n=20 (el umbral) con 70% | 70% | [48%, ...] | **No** |
| n=30 con 70% | 70% | [52%, ...] | No |
| n=50 con 70% | 70% | [56%, ...] | Sí |

Y para el avgR: con n=7, `avgR=+0.344`, sd=1.01 → **IC 95% [−0.41, +1.09]**,
que contiene el cero y el umbral.

Es decir: **aun aprobando el criterio en n=20, la aprobación no sería
estadísticamente distinguible del azar.** Peor, la cláusula "o 3 semanas"
permite decidir con n≈10 si el flujo de setups es lento.

- **Evidencia**: cálculo reproducible sobre `data/bot_trades.json` del VPS.
- **Riesgo**: es el hallazgo con mayor consecuencia práctica de toda la auditoría.
- **Propuesta (NO aplicada — cambiar el criterio es decisión de Hugo)**: no mover
  el umbral (sería mover el arco), sino **agregar** dos condiciones: (a) n mínimo
  duro de 20 aunque se cumplan las 3 semanas — si no hay muestra, la respuesta es
  "seguir midiendo", no "evaluar"; (b) exigir que el IC 95% inferior del WR supere
  55% y el del avgR supere 0, no el estimador puntual.
- **Naturaleza**: potencialmente operativa (gobierna el paso a live).

### P1-3 · Token de ingesta compartido + llaves de la cuenta principal en el proceso que lanza Chrome

`deploy/nexus-coinglass-visual.service:10` carga
`EnvironmentFile=/home/hugo/Nexus/deploy/collector.env`, que contiene
`BINANCE_API_KEY/SECRET` y `NEXUS_INGEST_TOKEN`
(`deploy/collector.env.example:14-15,21`), en el entorno del proceso que hace
`launch_persistent_context` — es decir, **Chrome hereda ese entorno** mientras
navega un sitio de terceros con anuncios, como `User=hugo`
(`service:8`), el mismo usuario del bot y del diario.

Atenuantes verificados: las llaves de **trading** NO están ahí
(`BINANCE_TRADE_*` viven en `deploy/trade.env`, `executor.py:108-111`), y
`collector.env` está en `.gitignore` y no trackeado.

- **Riesgo**: medio-alto. `BINANCE_API_*` es la cuenta principal según el propio
  docstring del ejecutor; no puedo verificar sus permisos desde el código.
- **Propuesta**: usuario propio sin acceso a `collector.env`, token por colector
  (hoy uno solo abre `bot/ingest`, `journal/ingest`, `coinglass/*`,
  `coinsignals/ingest`), y `LoadCredential=` en vez de EnvironmentFile.
- **Prueba necesaria**: verificar en Binance que `BINANCE_API_*` sea read-only.
- **Naturaleza**: operativa (infra), no toca la lógica del bot.

### P1-4 · XSS almacenado en el panel CoinGlass vía el token de ingesta

`core/app.py:391-393` (commit `5d7bd04`) agrega `coinglass/ingest`,
`coinglass/visual-ingest` y `coinsignals/ingest` a `_TOKEN_AUTH_POSTS`, que
saltan `_gate` completo. La validación del cuerpo existe y es correcta en lo
importante (token con `hmac.compare_digest`, `research_only`,
`execution_enabled`, `mode`, tamaño máximo — `modules/coinglass/module.py:70-85`),
pero **no valida el contenido de los campos**, y el front los inyecta sin
escapar: `reason()` devuelve el string tal cual
(`modules/coinglass/public/app.js:91-96`) y se interpola en `innerHTML`
(`:106-108`). Quien tenga el token planta HTML en el dashboard; la víctima es un
usuario logueado del mismo origen, que sí puede llamar `/m/bot/api/command`
(`kill|resume|close`, `modules/bot/module.py:102-110`).

- **No es bypass de autenticación**: el token se sigue exigiendo y falla cerrado
  con 503 si no está configurado. Es escalada *si el token se filtra* — lo que
  conecta con P1-3.
- **Propuesta**: escapar en `reason()` y en los `innerHTML` del panel; validar
  el payload de `ingest` con esquema.
- **Esfuerzo**: bajo. **Naturaleza**: web/seguridad.

### P1-5 · El colector visual no verifica sesión ni símbolo, y la doc afirma lo contrario

- **Sesión**: no hay ninguna comprobación de estado de login en `collect()`
  (`visual_collector.py:342-373`). El único guardián es "≥4 niveles"
  (`:375-381`). `deploy/COINGLASS_VISUAL_VPS.md:59` promete *"El servicio falla
  cerrado si la sesión vence"* — **no está implementado**.
- **Símbolo**: las cuatro URLs no llevan símbolo (`:21-24`); el activo depende del
  `localStorage` del perfil. `symbol: "BTCUSDT"` se escribe a mano (`:390`) y el
  validador solo comprueba que el string diga BTCUSDT (`visual.py:78-79`).
- **Propuesta**: `wait_for_selector` de un elemento solo-autenticado y un assert
  de que el precio del chart cuadra ±2% con el ticker público.
- **Naturaleza**: research (calidad de datos).

### P1-6 · Signo invertido en el tile "Consenso" — **corregido**

`Math.abs(h + m) / 2` pintaba un consenso **bajista** (ambos componentes
negativos) como **`+55` en verde**. Corregido en `0b8ee01` conservando el signo,
con test que impide la regresión.

### P1-7 · El Radar no mostraba frescura y cambiaba de modelo en silencio — **corregido**

`renderModel()` no leía `age_seconds`; al vencer la ventana de 30 min el
indicador visual desaparece y la vista **mutaba al modelo API** (otra fórmula,
otros pesos, otra barra de calibración) sin avisar. Corregido en `0b8ee01`:
ahora declara edad de captura, heatmap atrasado y el cambio de modelo.

### P1-8 · Muestra dependiente presentada como independiente — **corregido**

La UI ofrecía "2.016 capturas forward" como meta de calibración para 1h/4h/12h.
Con muestreo cada 5 min, las ventanas **no solapadas** por semana son ~168 (1h),
**~42** (4h) y **~14** (12h). El estudio Hobbyist previo sí hacía esto bien
("operaciones no solapadas", IC bootstrap); el estudio visual bajó el estándar.
Corregido el texto en `0b8ee01`; el estudio sigue pendiente de corregir.

### P2-9 · Sin candado sobre la fórmula del score — **corregido**

Ningún test fijaba los pesos ni la exclusión de los muros ballena: agregar
`whale_pressure` al cálculo pasaba la suite en verde. `0b8ee01` agrega el
candado (fórmula exacta + un desbalance extremo de muros que no puede mover el
puntaje ni una décima).

### P2-10 · Retención "7 días / 24 h" es por conteo, no por tiempo

`MAX_VISUAL_BOOK_HISTORY = 2_016` y `PUBLIC_VISUAL_BOOK_HISTORY = 288`
(`modules/coinglass/module.py:28-29`) equivalen a 7 d y 24 h **solo si el timer
nunca falla**. Con el colector caído medio día, las últimas 288 entradas abarcan
2-3 días y el chart las dibuja contiguas: los huecos desaparecen.
**Propuesta**: recortar por `captured_at >= now - 24h` y eje temporal real.

### P2-11 · Heurísticas de relleno en el parser de tooltips

`parse_tooltip` no distingue "tooltip incompleto" de "tooltip válido": si falta
el precio toma cualquier monto entre 1e3 y 1e6 como precio; si falta la
intensidad toma el último monto > 1e5 de la caja. Un tooltip a medio pintar
produce una fila plausible en vez de un descarte.
**Propuesta**: exigir claves obligatorias y descartar la fila si falta alguna.

### P2-12 · Fail-closed de órdenes canceladas apunta a un checkbox anónimo

`page.locator("input[type=checkbox]").first` (`visual_collector.py:283`) asume
que el primer checkbox del DOM es el de canceladas. Si CoinGlass agrega otro
filtro antes, se desmarca el control equivocado, no se lanza nada, y se publica
`active_only: True` — bandera **autoafirmada** que el servidor acepta como
evidencia (`visual.py:119-120`).
**Propuesta**: locator por texto/label.

### P2-13 · Filas virtualizadas y dedup que colapsa venues

`rows.count()` sobre `.large-order-item` sin scroll (`:291-296`): con lista
virtualizada se captura solo lo renderizado y se presenta como el libro de muros.
La clave de dedup omite `market`, así que un muro idéntico en spot y futuros
colapsa en uno (`:305-311`).

### P1-15 · Regresión del estándar estadístico entre estudios (hallazgo transversal)

El repo contiene **dos estándares distintos de rigor**, y el más nuevo es el peor.

`research/coinsignals_backtest_2026-07-22.md` es, verificado línea por línea, un
trabajo ejemplar:
- entrada solo en velas **posteriores** a la publicación; la vela de publicación
  nunca llena; en la vela de fill el stop cuenta y el TP no; ante ambigüedad
  TP/SL gana el stop; costo conservador 0,14% ida y vuelta; sin leverage.
- **Cuantifica el look-ahead de las ediciones** con un gradiente monótono
  (nunca editado −0,132R → editado >1 día +0,254R) y **excluye** todo mensaje
  editado de la métrica primaria, declarando que incluirlas inflaría el resultado
  de +0,021R a +0,117R.
- **Cuantifica el sesgo de selección del propio canal**: publicó desenlace para
  el 88,4% de los ganadores y solo el 29,5% de los perdedores.
- **Bootstrap por bloques mensuales** (61 meses) porque las señales no son
  independientes: TP1 IC 95% `[−0,190R, −0,076R]`; BE hipotético
  `[−0,067R, +0,110R]` — contiene cero.
- Marca sus propios cortes favorables (2026, longs) como **post-hoc** y prohíbe
  convertirlos en filtro.
- Veredicto: **no conectar al bot**. Negativo y publicado como negativo.

El estudio de CoinGlass API (`coinglass_hobbyist_study_2026-07-24.md`) mantiene
ese mismo estándar: split temporal 70/30, **operaciones no solapadas por
horizonte**, costo 0,10%, umbrales fijos con variantes inversas etiquetadas como
post-hoc, IC bootstrap 95%, y un veredicto igual de duro — *"No aparece un edge
robusto. Ninguna regla positiva mantiene su IC 95% completamente sobre cero"*,
refutando explícitamente sus propias hipótesis (Precio+OI y liquidaciones como
continuación) y señalando que el funding a 8 h usa solo 19 operaciones OOS.

Por lo tanto **no hay una degradación cronológica del estándar**: hay un único
**outlier**. El estudio visual del Radar
(`coinglass_visual_study_2026-07-24.md`), del mismo día que el anterior, **no
menciona** solapamiento, autocorrelación, bootstrap por bloques ni tamaño
efectivo, y propone "al menos 100 decisiones forward" para horizontes de hasta
12 h. La casa sabe hacerlo bien y lo hace bien dos de cada tres veces; el Radar
visual es la excepción.

- **Propuesta**: adoptar el estudio de CoinSignals como **plantilla obligatoria**
  para toda validación futura (submuestreo no solapado o bloques, IC, sesgos
  cuantificados, cortes post-hoc etiquetados, veredicto de descarte explícito).
- **Naturaleza**: proceso/research. Es la mejora con mayor relación
  evidencia/riesgo de toda la auditoría: no toca código y evita promover ruido.

### P1-16 · El crecimiento del Diario es reproducible, pero optimista y con el drawdown subestimado

Respuesta directa a "¿el crecimiento mostrado es reproducible o contiene errores
contables?". Verificado ejecutando `paper_account` sobre los setups reales del
VPS (294 cerrados, 272 contados tras dedup): **equity $142.840, +275,9%,
DD −17,6%, WR 64%**, con capital base $38.000 y 2% de riesgo por trade.

**Lo que está bien hecho** (`modules/trading/setups_store.py`):
- Solo `ganada`/`perdida` entran al desempeño; las `anuladas` se informan aparte.
- **Colapso de la misma idea**: replica sobre el histórico las guardias vivas —
  re-entradas de la misma `key` dentro del cooldown y zonas solapadas
  concurrentes del mismo par+dirección se descartan. Esto elimina el doble conteo
  que originó el "spam DOGE" y el "doble ETH". De 294 cerrados, 272 cuentan.
- Costos **maker-aware** por trade (`cost_R = cost_frac / SL%`), que con SL
  ajustado pesan mucho: $30.943 de comisiones sobre $104.840 de P&L.
- El compounding está declarado en el docstring, no escondido.

**Los dos problemas reales**:

1. **Sizing al cierre en vez de a la apertura.** La curva ordena por `ts_closed`
   y dimensiona cada trade con el equity vigente *en ese momento*
   (`pnl = net_r × risk_pct × eq`). Como el 99% de los trades se solapó, un trade
   que **abrió** temprano pero **cerró** tarde se dimensiona con capital que ya
   incluye las ganancias de operaciones que seguían abiertas cuando él se abrió.
   Recalculado dimensionando con el equity al **abrir**: **+259,1% en vez de
   +275,9%** → la cifra publicada está inflada en **16,8 puntos porcentuales**
   (~6% relativo). Real, medido, y no catastrófico.
2. **El drawdown está estructuralmente subestimado.** El modelo aplica los trades
   de a uno. En los datos reales hubo hasta **13 posiciones simultáneas, todas en
   la misma dirección**, es decir **26% del capital en riesgo a la vez y
   correlacionado** (son pares cripto). Una curva secuencial nunca puede mostrar
   ese golpe: el −17,6% reportado no es el drawdown que habría producido esa
   concentración.

- **Veredicto**: el crecimiento **es reproducible** (lo reproduje) y la mecánica
  es honesta y cuidadosa; pero el titular es optimista y el DD no es el riesgo
  real. Para una integración futura, el número que importa no es +275,9% sino la
  exposición concurrente correlacionada.
- **Propuesta**: dimensionar por equity a la apertura y reportar, junto al DD,
  el **máximo riesgo simultáneo** (posiciones concurrentes × riesgo, y cuántas
  comparten dirección). Es cambio en capa de reporte, no en ejecución.
- **Esfuerzo**: bajo. **Naturaleza**: research/UI (afecta cómo se lee, no cómo se
  opera). **Riesgo**: bajo.
- **Criterio**: si el máximo riesgo simultáneo correlacionado supera el tope
  diario configurado (15%), el sizing del Diario no representa la política real.

### P3-14 · Deriva de versión y umbrales inconsistentes

`visual_context_v0` (shadow) vs `Visual Context v1` (indicador) vs `RADAR VISUAL
V1` (UI) vs `v0` (estudio). Y tres umbrales para el mismo score: ±18 (etiqueta),
±25 (entrada del shadow), ±15 (modelo API), ninguno pre-registrado.

---

## 4. Qué funciona realmente

1. **El aislamiento research↔ejecución es genuino y está defendido con tests**,
   no solo con convenciones: `execution_enabled:false` se valida en la ingesta y
   se re-emite en cada objeto, y hay un test que prohíbe `modules.bot` y
   `place_order` en las fuentes del colector, el modelo y el shadow.
2. **La exclusión de los muros ballena del score** está bien ejecutada y bien
   comunicada — se calculan, se publican, se muestran, y no entran al puntaje.
   Es la decisión honesta correcta mientras no haya forward.
3. **El replay del shadow es pesimista donde podía hacer trampa**: sale al precio
   observado y no al de target/stop, prioriza el stop ante ambigüedad y declara
   que no ve el intrabar.
4. **La separación de llaves** (trading vs colector) con el ejecutor inerte si
   faltan las de la subcuenta.
5. **El estudio de CoinSignals** (ver P1-15): metodología causal estricta, sesgos
   cuantificados en vez de mencionados, bootstrap por bloques, y un veredicto
   negativo publicado como negativo ("no conviene conectar estas señales al
   bot"). Es el mejor trabajo cuantitativo del repo y debería ser la plantilla.
6. **El rollover Fase 1 V1→V2 está justificado**: el V1 activaba al tocar
   cualquier borde del POI pero atribuía el fill al midpoint, y la auditoría de
   velas confirmó ganadores donde ese midpoint nunca se negoció. El criterio no
   se movió; solo se reinició el contador. Es corrección de medición, no cambio
   de arco — y en dirección conservadora (el V1 medía **mejor** que la realidad y
   aun así fallaba).

## 5. Prometedor pero NO validado

- Radar visual completo (score y componentes): sin forward, con P0-1 abierto.
- Muros ballena como señal: bien excluidos; falta medir persistencia/cancelación.
- Todo lo derivado de CoinGlass: contexto, no predicción.

## 6. Qué debe descartarse

- Presentar cualquier métrica del bot virtual (WR, retorno, DD) sin `n` ni IC.
- La meta de "2.016 observaciones" como base de calibración por horizonte.
- Cualquier promoción al bot basada en el criterio actual de Fase 2 sin la
  corrección de potencia de P0-2.

---

## 7. Plan de validación forward (propuesto, no implementado)

Pre-registrar **antes** de mirar resultados, y reservar un bloque OOS temporal:

**Registro por captura** (ya casi todo existe): timestamp causal de la captura y
**el del propio dato** (`heatmap_lag_seconds`, nuevo), precio BTC, score y cada
componente, niveles fuertes arriba/abajo, muros y su persistencia, cambios de
OI/funding/taker, y luego retornos a 1h/4h/12h, MAE/MFE, y régimen (volatilidad
realizada y tendencia).

**Evaluación**:
- Submuestreo **no solapado** por horizonte (1 obs cada 12/48/144 capturas) o
  bootstrap por bloques; reportar siempre `n` efectivo, no capturas.
- Correlación OOS, calibración por deciles, precisión direccional, retorno neto
  con costos conservadores y drawdown.
- **Ablación** de cada componente y valor **incremental sobre el filtro RR≥5**
  (si no aporta sobre lo que ya hay, no sirve).
- Walk-forward por mes, IC bootstrap, sensibilidad a umbrales, y comparación
  contra baselines tontos (siempre-largo, momentum simple, aleatorio).
- Corrección por múltiples comparaciones: 3 horizontes × k reglas.
- **Criterio de descarte explícito**: si el IC 95% del edge incremental contiene
  cero, se descarta; no se "sigue observando" indefinidamente.

---

## 8. Roadmap priorizado

| # | Acción | Riesgo | Esfuerzo | Naturaleza |
|---|---|---|---|---|
| 0 | Adoptar la plantilla de CoinSignals para toda validación (P1-15) | Nulo | Bajo | Proceso |
| 1 | Resolver P0-1 (columna del heatmap) con el lag ya medido | Bajo | Bajo | Research |
| 2 | Reforzar el criterio de Fase 2 con n mínimo + IC (decisión de Hugo) | Bajo | Bajo | Operativa |
| 3 | Escapar HTML en el panel + esquema en `ingest` (P1-4) | Bajo | Bajo | Seguridad |
| 4 | Aislar el colector: usuario propio, token por colector (P1-3) | Medio | Medio | Infra |
| 5 | Verificar sesión y símbolo en el colector (P1-5) | Bajo | Bajo | Research |
| 6 | Retención por tiempo + eje temporal con huecos (P2-10) | Bajo | Bajo | UI/datos |
| 7 | Parser estricto de tooltips y dedup por venue (P2-11/13) | Bajo | Medio | Research |
| 8 | Sizing a la apertura + reportar riesgo simultáneo (P1-16) | Bajo | Bajo | Research/UI |

---

## 9. Limitaciones de esta auditoría

- No verifiqué los permisos reales de `BINANCE_API_*` en Binance (no es
  observable desde el código y no toco credenciales).
- No ejecuté el colector visual contra CoinGlass: la validación de P0-1 con datos
  reales requiere una corrida en el VPS, que no hice por la restricción de no
  escribir/desplegar sin autorización.
- La muestra V2 (n=7) es demasiado pequeña para cualquier conclusión sobre
  desempeño; solo la usé para demostrar la falta de potencia del criterio.
- Los estudios de CoinSignals y CoinGlass API fueron verificados directamente
  (ver P1-15); la contabilidad del Diario se reprodujo ejecutando
  `paper_account` sobre datos reales del VPS (ver P1-16).
- No audité en profundidad el parsing de Telegram de CoinSignals ni la capa de
  caché/rate-limit del proveedor CoinGlass; ambos quedan como brecha conocida.

## 10. Confirmación operativa

Bot, dry-run, credenciales y servicios **intactos**. No se crearon ni
modificaron órdenes, no se activó live, no se retiró ningún kill-switch, no se
tocaron secretos ni permisos, no se reinició ningún servicio y no se escribió en
el VPS. Los cambios de `0b8ee01` son tests, observabilidad y texto de UI.
