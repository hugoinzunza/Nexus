# TradingView BTA vs Nexux SMC - primera lectura

Fecha: 2026-06-30

## Objetivo

Estudiar la pagina abierta en TradingView ("Bitcoin Traders Academy") y compararla con la estrategia actual de Nexux usando historia de los ultimos anos.

## TradingView observado

Pagina abierta:

- URL: `https://es.tradingview.com/chart/c07zDMmj/`
- Layout: `Bitcoin Traders Academy`
- Simbolo: `BINANCE:BTCUSDT.P`
- Timeframe visible: `15m`
- Estado: `Modo solo lectura`
- Indicador visible en leyenda: `AG FX - Watermark`

Alertas visibles:

- Varias alertas manuales de cruce de nivel, por ejemplo:
  - `BTCUSDT.P Cruce descendente 59.500,0`
  - `BTCUSDT.P Cruce descendente 57.000,0`
  - `BTCUSDT.P Cruce ascendente 65.000,0`
  - `BTCUSDT.P Cruce descendente 56.500,0`
- Dos alertas de divergencia historicas:
  - `Divergencia Bajista detectada` en `BTCUSDT.P, 4h`
  - `Divergencia Alcista detectada` en `BTCUSDT.P, 4h`

Log de alertas:

- Predominan disparos repetidos de `BTCUSDT.P Cruce descendente 59.500,0` durante el 29 y 30 de junio.
- Esto parece monitoreo de niveles, no una estrategia completa de entrada/salida.

Conclusion preliminar sobre TradingView:

Con lo visible en el layout no hay reglas suficientes para backtestear una "estrategia BTA" completa. Faltan reglas objetivas de entrada, invalidacion, stop, take profit, gestion parcial, expiracion y filtro de temporalidad. Las alertas visibles son utiles como contexto discrecional, pero no equivalen a una estrategia comparable contra Nexux.

## Nexux observado

Nexux ya contiene dos lineas de investigacion:

1. Estrategias mecanicas traducidas/probadas:
   - RSI reversal
   - RSI MTF
   - SMA/EMA cross
   - EMA 53/200 + MACD + divergencia RSI
   - Liquidity grab
   - Donchian, Bollinger, squeeze, etc.

2. Estrategia SMC / curso:
   - POI multi-TF en `1D`, `4h`, `1h`
   - order block + barrido de liquidez
   - FVG con displacement
   - premium/descuento del dealing range
   - POI sin mitigar
   - plan en `1h` y `4h`
   - filtro R:R minimo
   - TP a liquidez lejana / estructural
   - SL estructural ajustado

Fuente principal:

- `modules/trading/smc_live.py`
- `modules/trading/run_setup_backtest.py`
- `modules/trading/setup_backtest_results.json`
- `research/veredicto_estrategia_2026-06-13.md`

## Resultados Nexux actuales

Backtest `setup_backtest_results.json`:

- Periodo: 2022-04-30 a 2026-06-11
- Universo: BTC, ETH, SOL, BNB, XRP, ADA, DOGE
- Timeframes de plan: `1h`, `4h`
- POI TFs: `1D`, `4h`, `1h`
- Trades cerrados: 6.254
- Win rate: 17,8%
- Avg R: +0,69R
- Total: +4.342,7R
- Profit factor: 1,84

BTC solamente:

- Trades: 920
- Win rate: 19,1%
- Avg R: +0,47R
- Total: +431,7R
- Profit factor: 1,58
- Max drawdown: -33,7R
- Max losing streak: 22

Por ano:

| Ano | Trades | Win rate | Avg R | Total R | PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2022 | 803 | 18,4% | +0,78 | +623,6 | 1,95 |
| 2023 | 1.441 | 17,9% | +0,50 | +720,3 | 1,61 |
| 2024 | 1.562 | 17,0% | +0,60 | +940,1 | 1,73 |
| 2025 | 1.680 | 18,2% | +0,91 | +1.525,6 | 2,11 |
| 2026 | 768 | 17,7% | +0,69 | +533,1 | 1,84 |

Sensibilidad de cortar ganadores:

| Tope | Avg R | Total R |
| --- | ---: | ---: |
| Sin tope | +0,69 | +4.342,7 |
| 15R | +0,56 | +3.473,9 |
| 10R | +0,40 | +2.514,8 |
| 5R | +0,00 | +0,6 |
| 3R | -0,29 | -1.825,8 |

Lectura:

El edge de Nexux depende de winners grandes. Si la estrategia TradingView/BTA usa targets fijos cortos o alertas de niveles sin dejar correr, probablemente no captura el mismo perfil de retorno.

## Comparacion preliminar

| Dimension | TradingView visible | Nexux SMC |
| --- | --- | --- |
| Tipo | Layout + alertas de niveles | Estrategia codificada/backtesteada |
| Simbolo observado | BTCUSDT.P 15m | BTCUSDT spot, multi-par |
| Reglas visibles | No suficientes | Definidas en codigo |
| Entrada | No visible | POI confirmado + toque/activacion |
| Stop | No visible | Estructural ajustado |
| TP | No visible | Liquidez lejana / estructural |
| Historia disponible | Log parcial de alertas | 2022-04-30 a 2026-06-11 |
| Testeabilidad | Baja sin Pine/reglas | Alta |

## Protocolo justo para comparar

Para comparar BTA vs Nexux se necesita transformar BTA a reglas mecanicas. Minimo:

1. Entrada long/short exacta.
2. Stop inicial.
3. Take profit o regla de salida.
4. Gestion parcial/break-even, si existe.
5. Timeframe base y timeframes superiores usados.
6. Si las senales repintan o se confirman al cierre.
7. Si una vela toca TP y SL, criterio conservador.

Despues:

1. Implementar `bta_*` como nueva estrategia en `modules/trading/strategies.py` o un script separado de research.
2. Probar en el mismo periodo y costos que Nexux.
3. Separar BTCUSDT.P/BTCUSDT de multi-par.
4. Reportar IS/OOS, PF, avg R, drawdown, rachas y sensibilidad a cap de winners.
5. Comparar contra `smc_live.analyze`, no contra estrategias mecanicas descartadas.

## Hipotesis inicial

La pagina TradingView actual parece mas un tablero discrecional de curso con niveles/alertas que una estrategia completa. Nexux, en cambio, ya codifica la parte estructural SMC y muestra edge historico positivo, especialmente cuando no corta ganadores.

La comparacion real depende de obtener el Pine Script o reglas BTA. Sin eso, la conclusion honesta es: no hay suficiente informacion visible para afirmar que BTA supera, iguala o contradice a Nexux.

