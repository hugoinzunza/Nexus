# Auditoría del gráfico SMC de NexUX vs LuxAlgo — 2026-08-17

Origen: capturas de Hugo (LuxAlgo SMC en BTCUSDT.P, 15m/1h/4h/1D) que no
concuerdan con NexUX en Strong/Weak, OB y FVG. Comparación hecha contra el
endpoint vivo `/m/trading/api/smc` con el mismo dato (Binance Futuros).

## 1. Comparación numérica del dealing range

| TF | NexUX Strong High | NexUX Weak Low | NexUX EQ | LuxAlgo (leído de las capturas) |
|---|---|---|---|---|
| 15m | 65.483 (09-ago) | 62.484 (14-ago) | 63.983 | high ~63.7-63.8 · low ~62.7 · EQ ~63.240 |
| 1h | 66.924 (21-jul) | 62.229 (01-ago) | 64.577 | EQ ~64.000 · Strong LOW ~62.4 |
| 4h | **82.829 (06-may)** | 57.759 (01-jul) | **70.294** | high ~67.0 · EQ ~64.500 |
| 1D | **126.209 (oct-2025)** | 48.888 (ago-2025) | **87.548** | Weak High ~83.5 · Strong Low ~56.9 · EQ ~70.4 |

La divergencia crece con la temporalidad hasta volverse absurda: el equilibrio
diario de NexUX está en **87.5k con el precio en 63.7k** — todo el mercado
visible queda clasificado "discount".

## 2. Hallazgo principal — BUG de calibración de alcance

`DEALING_RANGE_WINDOW = 800` velas y `RANGE_PIV = 10` fueron **calibrados contra
el 15m** (los comentarios del código lo dicen textual: "800 (~8 días en 15m)…
alineado con el indicador de Hugo (BTA)", "_range… Calibrado contra BTCUSDT.P
15m") — pero se aplican a TODAS las temporalidades:

- 800 velas de 1h = 33 días · de 4h = **133 días** · de 1D = **2,2 años**.
- Por eso el 4h ancla su Strong High en mayo y el 1D en el máximo histórico de
  octubre-2025.

### Impacto real (no es solo cosmético)

El diario planifica en `setup_tfs = [1h, 4h]` y **el TP de los planes puede ser
literalmente el Strong High / Weak Low del rango** (`tp_label` en el código y en
los setups reales). Con la ventana mal escalada en 4h, los TP apuntan a extremos
de hace meses → **RR inflados** (los rr 19,2 / 50,5 / 14 observados en el
diario) → esos planes pasan el gate `rr≥5` con ventaja → **sesgo de selección**.
Conecta directo con el diagnóstico de julio del bot ("el gap es selección, no
ejecución") y con la fricción: RR nominal alto con targets lejanos que rara vez
se alcanzan.

## 3. Diferencias por definición (NO son bugs; jamás van a coincidir con LuxAlgo)

1. **Semántica Strong/Weak**: NexUX etiqueta FIJO (el alto del rango = "Strong
   High", el bajo = "Weak Low"), herencia de la calibración BTA. LuxAlgo asigna
   fuerte/débil **según la tendencia** — por eso tu 1D muestra *Weak* High y
   *Strong* Low (estructura alcista de fondo): contradicción esperable, no error
   de cálculo. Los % de LuxAlgo (59/41, 37/63…) son fuerza relativa entre ambos
   lados; el % de NexUX en `levels` es posición dentro del rango (0–100%).
2. **Order Blocks**: NexUX = última vela opuesta (rango completo con mechas)
   dentro de las 5 previas a un FVG con displacement ≥1,0 ATR, del lado correcto
   del EQ local (pivote 2). LuxAlgo selecciona por swing/volumen con mitigación
   configurable. Construcciones distintas → cajas distintas, por diseño.
3. **FVG**: NexUX no filtra por tamaño mínimo y marca mitigado con CUALQUIER
   toque (los deep-FVG 1D/4h solo muestran los no llenados). LuxAlgo aplica
   umbral automático y otra regla de mitigación → conjuntos distintos.
4. **NexUX no detecta POIs en 15m** (`POI_TFS = 1D/4h/1h`): las cajas 15m de tu
   captura nunca tendrán equivalente. Decisión de diseño.
5. Los TP1/TP2/SL1/SL2 punteados y las etiquetas de volumen (4.622K 4%,
   141.631K 21%, 4,11M 38%) de tus capturas **no son del SMC de LuxAlgo** — son
   otro overlay (señales/liquidaciones). NexUX no modela eso.

## 4. Propuesta

1. **Fix del bug (rama, sin desplegar):** ventana y pivote del dealing range
   **por TF**, configurables, con la calibración 15m intacta. Los valores de
   1h/4h/1D requieren calibración visual contra el indicador de referencia de
   Hugo, igual que se hizo con el 15m — no los invento yo.
2. **Despliegue en la ventana de octubre** junto al resto: cambia la SELECCIÓN
   de setups, así que ni el VPS (ECON-COHORT-001 congelada) ni el Mac (fuente de
   las cohortes del laboratorio) deben recibirlo a mitad de cohorte.
3. **Documentar en el panel** que NexUX ≠ LuxAlgo por definición en OB/FVG y
   semántica Strong/Weak, para que la próxima comparación visual no parta de la
   expectativa de igualdad.

## Veredicto

- **1 bug real y material**: ventana del rango sin escalar por TF, con efecto en
  los TP y el RR de los planes de 1h/4h del diario.
- **El resto de las discrepancias es definicional**: dos indicadores distintos
  midiendo conceptos emparentados con reglas diferentes. NexUX es internamente
  consistente y causal (anti-repintado, velas cerradas, confirmación de
  pivotes); simplemente no es un clon de LuxAlgo ni pretendía serlo — fue
  calibrado contra BTA en 15m.
