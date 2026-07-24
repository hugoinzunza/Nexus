# CoinGlass visual: estudio general e indicador Research

Fecha: 2026-07-24. Activo: BTCUSDT. Acceso autorizado por el titular de la
cuenta. Este trabajo no modifica el bot ni habilita órdenes.

## Instrumentos revisados

| Instrumento | Fuente preferida | Uso útil | No usar como |
|---|---|---|---|
| OI histórico/agregado | API Hobbyist | régimen de apalancamiento y divergencias precio/OI | entrada aislada |
| Funding por exchange | API Hobbyist | costo y crowding; dispersión entre exchanges | dirección automática |
| Ratios long/short | API Hobbyist | posicionamiento retail/top traders | contrarian mecánico |
| Taker buy/sell | API Hobbyist | agresión ejecutada y confirmación de flujo | predicción sin precio |
| Bid/ask ±1% | API Hobbyist | profundidad y divergencia entre exchanges | muro permanente |
| Mapa de liquidaciones | Navegador autorizado | objetivos probables y zonas de aceleración | certeza direccional |
| Heatmap Model 2 | Navegador autorizado | concentración y proximidad de bandas | gatillo por sí solo |
| Delta del order book | Navegador autorizado | presión y desaceleración del libro | orden ejecutable |

La API se usa siempre que el plan la ofrece. El navegador se reserva para las
capas visuales que Hobbyist marca como no disponibles por API.

## Lectura real observada

Precio de referencia durante la captura: 64,238 USDT.

Heatmap 24h, columna más reciente:

- Arriba: 64,482.8 (US$8.85M), 64,703.8 (US$13.36M),
  64,924.8 (US$13.85M) y 66,029.8 (US$15.51M).
- Abajo: 63,598.8 (US$15.97M), 63,377.8 (US$20.38M),
  63,156.8 (US$12.73M) y 62,935.8 (US$9.90M).
- El nivel significativo más cercano estaba arriba, a aproximadamente +0.38%,
  pero la banda inferior cercana era más intensa.

Mapa acumulado:

- Concentraciones superiores relevantes en 64,746-64,791 y
  65,601-65,691.
- Concentraciones inferiores relevantes en 63,486-63,666 y 62,856.

Delta agregado del libro ±1%:

- Subió desde US$454K a un máximo cercano a US$27.56M.
- Después bajó a US$20.37M, US$13.85M y US$12.47M.
- Lectura: bids todavía dominantes, pero con presión desacelerando.

## Resultado adversarial

El mapa sí aporta información que no estaba disponible en la API Hobbyist:
distancia a liquidez, intensidad relativa y bandas de aceleración. No resuelve
por sí solo la dirección. Una concentración puede atraer el precio, actuar como
target o desaparecer antes de ser alcanzada.

El estudio Hobbyist previo sobre 1,079 barras 4h no encontró edge standalone
robusto en OI, funding, libro, taker, liquidaciones ni reglas compuestas. Por
eso el nuevo índice se llama `CoinGlass Visual Context v0`, queda
`validated:false` y no sustituye la decisión de la estrategia.

## Indicador implementado

Componentes fijos:

- 50% asimetría ponderada del Heatmap Model 2 dentro de ±5%.
- 30% asimetría ponderada del mapa acumulado dentro de ±5%.
- 20% delta del order book, saturado para que un extremo no domine.

La intensidad se pondera por distancia al precio. Además se publican sin
ocultar:

- nivel significativo más cercano arriba y abajo;
- nivel más fuerte arriba y abajo;
- distancia porcentual e intensidad en USD;
- delta actual, pendiente y desaceleración;
- cobertura, antigüedad y URLs de procedencia.

El índice describe `atracción superior`, `atracción inferior` o
`liquidez equilibrada`. Es contexto, no señal.

## Validación y bot virtual

Fase A: recolectar snapshots cada cinco minutos sin cambiar la fórmula.

Fase B: asociar cada snapshot con retorno BTC a 15m, 1h, 4h y 12h, MFE/MAE y
eventos de toque de nivel. Exigir al menos 100 decisiones forward y separar
por régimen.

Fase C: ejecutar un bot virtual sin credenciales de trading. Comparar:

1. estrategia NexUX base;
2. base + CoinGlass solo para targets/invalidation;
3. base + filtro contextual;
4. CoinGlass aislado como control negativo.

Solo una mejora OOS/forward estable en expectativa y drawdown justificaría
proponer un cambio al dry-run. El bot real queda fuera de esta implementación.

El shadow `visual_context_v0` ya quedó instrumentado: abre una observación
virtual solo cuando el índice cruza ±25 y existen target/stop opuestos con
geometría mínima. Sale por target, stop, señal opuesta o cuatro horas; descuenta
0.08% por round trip. La simulación usa precios de snapshots cada cinco minutos,
por lo que declara explícitamente que no conoce el recorrido intrabar.

## Archivos

- `modules/coinglass/visual.py`: validación e indicador.
- `modules/coinglass/visual_collector.py`: navegador dedicado y tooltips.
- `modules/coinglass/shadow.py`: bot virtual y métricas forward.
- `modules/coinglass/module.py`: ingesta separada.
- `modules/coinglass/public/`: vista Mapa visual.
- `deploy/COINGLASS_VISUAL_VPS.md`: instalación y rollback.
