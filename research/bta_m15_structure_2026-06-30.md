# Estudio BTC M15 estilo BTA/SMC vs Nexux

Fecha del estudio: 2026-06-30. Datos locales: 2022-06-12 17:45 UTC a 2026-06-11 19:30 UTC, 140,163 velas de 15m.

Nota de alcance: la auditoría visual detallada del chart del profe quedó separada en `research/tradingview_bta_visual_audit_2026-06-30.md`, con capturas guardadas en `research/tradingview_bta_screenshots_2026-06-30/`.

## Lectura ejecutiva

- Observación directa en TradingView del layout "Bitcoin Traders Academy" en BTCUSDT.P M15: el gráfico está en modo sólo lectura, con marcas naranjas de `Máximo`/`Mínimo`, niveles horizontales/alertas en precios redondos, zonas celestes tipo bloque/imbalance y alertas de cruce. No se ve el código propietario del indicador; el estudio visual se basa en lo que el chart dibuja.
- En M15 hay muchísima estructura operable visualmente, pero el edge mecánico no viene de “tocar cualquier OB”: aparece cuando el POI tiene salida hacia liquidez opuesta con R:R suficiente y el CDC no llega tarde.
- La variante simple de toque a POI con TP fijo 2R dio 1488 trades, expectativa -0.129R, PF 0.83 y total -191.44R.
- La variante que apunta a la siguiente liquidez weak sin barrer y exige R:R >= 2.0 dio 605 trades, expectativa -0.129R, PF 0.86 y total -78.07R.
- M15 sirve mejor como microscopio de ejecución: barrido, mitigación y CDC. Para dirección y selección de POI, los resultados siguen favoreciendo que la idea venga de 1h/4h/1d y no de ruido M15 aislado.

## Observación directa del TradingView del profe

Esta sección corrige la primera pasada visual: al hacer zoom-out correcto en TradingView aparecen muchas más zonas y anotaciones del layout del profe. Todo lo siguiente fue observado directamente en el chart `Bitcoin Traders Academy`, `BTCUSDT.P`, `15m`, Binance.

- Elementos visibles de la plantilla:
  - Zonas grises horizontales como áreas de decisión.
  - Etiquetas explícitas: `Premium POI`, `Premium POI X Confirmación`, `Discount POI`, `Discount POI x confirmación`, `counter POI`, `Alto Referencial (Resistencia)`.
  - Líneas `CDC` rojas/rosadas que funcionan como nivel de cambio de carácter o confirmación.
  - Franjas verticales azules que resaltan ventanas de reacción / desplazamiento.
  - Marcas verdes de check sobre zonas donde la reacción fue validada.
  - Círculos/ojos y marcas celestes en máximos/mínimos relevantes.
  - Niveles de precio azules/rojos apilados en el eje derecho, probablemente soportes/resistencias o alertas guardadas.
  - En tramos anteriores aparece estructura dibujada con zigzag morado, puntos celestes en swings, flechas de dirección y mediciones tipo Fibonacci/rango.
- Alertas activas vistas en el panel: cruce descendente `56.500`, cruce descendente `57.000`, cruce ascendente `65.000`, cruce descendente `59.500`; una alerta `60.500` aparece interrumpida por error de cálculo.
- Alertas históricas visibles: zonas `75.000/75.500`, `78.900/79.200/79.500/80.000`, `82.200/82.445/82.803`, además de `Divergencia Bajista detectada` y `Divergencia Alcista detectada` en BTCUSDT.P 4h.

Tramos revisados en zoom-out:

- 2026-06-24: aparece una zona gris `Discount POI x confirmación` alrededor de `60.6k-61.3k`, con `Alto Referencial (Resistencia)` arriba y niveles apilados `62.8k`, `62.2k`, `61.7k`, `61.0k`, `60.6k`, `59.8k`, `59.0k`. El precio viene cayendo hacia el discount POI, rebota y después vuelve a testear; aquí el profe está mirando reacción en zona, no una vela aislada.
- 2026-06-17: aparece un bloque azul amplio sobre el tramo de `63.6k-66.4k`, con máximo `66.419`, varias mechas violentas y caída posterior a mínimo `63.881`. Se ve una lectura de rango premium/discount y reacción en zonas internas.
- 2026-06-11: aparece un bloque gris superior alrededor de `63.6k`, un bloque gris inferior alrededor de `62.2k-62.6k`, una línea diagonal naranja y un check verde. Esto sugiere validación por desplazamiento desde discount hacia zona premium, no simplemente por cruce.
- 2026-05-27: se ve una caída desde zona alta `76k` hacia una caja naranja de rango/objetivo entre `72.66k-74.25k`, con mínimo marcado `72.667`. El movimiento respeta la idea de tomar liquidez alta, desplazar y buscar liquidez baja.
- 2026-05-15: se observan zonas celestes horizontales alrededor de `79.2k`, `78.85k`, `78.25k`, `77.6k`, una línea `CDC` cerca de `78.75k`, una zona `Discount POI`, y una etiqueta `INF`. El precio pierde el CDC, cae y luego reacciona en zonas inferiores.
- 2026-01-15: no se ven tantas etiquetas de POI, pero sí muchos niveles apilados en el eje derecho alrededor de `94k-96k`; parece una zona de referencia/niveles de trabajo más que una plantilla vacía.
- 2025-11-05: aparece la estructura morada/celeste más explícita: zigzags sobre swings, círculos celestes en puntos de giro, flechas de dirección, línea roja horizontal y mediciones tipo `0/1`. Esto sí parece lectura estructural/manual de acumulación/distribución o secuencia de swings.

Lectura inferida desde lo visible:

- El profe trabaja en capas: primero rango/referencia, luego POI premium/discount, luego CDC/confirmación, y recién después reacción/objetivo.
- Las zonas grises/celestes son más importantes que el precio exacto de la alerta. El nivel redondo sirve como imán o referencia, pero la decisión ocurre por interacción con POI + CDC + liquidez.
- `Máximo`/`Mínimo` no son simples high/low decorativos: parecen extremos operativos del rango actual, usados para definir premium/discount y posibles objetivos.
- Hay dos familias de lectura en el layout: una de zonas POI/CDC y otra de estructura swing/zigzag con puntos de giro. Nexux hoy modela bastante bien la primera, pero todavía no replica prolijamente la parte visual de zigzag/legibilidad del profe.

## POI / OB por año

| año | toques | CDC<=16 | RRliq>=2 | fixed expR | fixed PF | liq expR | liq PF |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2022 | 212 | 45.8% | 28.8% | 0.002 | 1.0 | 0.004 | 1.01 |
| 2023 | 581 | 54.9% | 29.9% | -0.255 | 0.67 | -0.072 | 0.92 |
| 2024 | 608 | 51.3% | 39.1% | -0.003 | 1.0 | -0.307 | 0.68 |
| 2025 | 718 | 53.2% | 39.6% | -0.204 | 0.74 | -0.058 | 0.94 |
| 2026 | 284 | 47.9% | 41.2% | -0.08 | 0.89 | -0.054 | 0.94 |

## Fuente del POI

| fuente | toques | invalid pre | CDC<=16 | RRliq>=2 |
| --- | --- | --- | --- | --- |
| 15m | 1876 | 406 | 53.1% | 39.3% |
| 1d | 17 | 1 | 52.9% | 0.0% |
| 1h | 386 | 35 | 49.2% | 28.2% |
| 4h | 124 | 4 | 40.3% | 21.8% |

## Estructura PIV10 M15

Weak = nivel todavía no barrido al cierre de la historia. Strong = nivel que ya fue barrido después de confirmarse.

| año | SH | SL | weak H fin | weak L fin | sweep H | sweep L | med h sweep H | med h sweep L |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2022 | 656 | 666 | 0 | 7 | 656 | 659 | 11.75 | 10.5 |
| 2023 | 1177 | 1199 | 0 | 83 | 1177 | 1116 | 12.0 | 10.25 |
| 2024 | 1174 | 1136 | 0 | 42 | 1174 | 1094 | 9.25 | 12.25 |
| 2025 | 1125 | 1121 | 21 | 0 | 1104 | 1121 | 10.0 | 11.5 |
| 2026 | 492 | 529 | 47 | 7 | 445 | 522 | 10.25 | 10.0 |

## FVG M15

| año | FVGs | bull | bear | fill | med fill velas |
| --- | --- | --- | --- | --- | --- |
| 2022 | 3242 | 1588 | 1654 | 99.9% | 2.0 |
| 2023 | 7641 | 4043 | 3598 | 99.2% | 2.0 |
| 2024 | 7699 | 4080 | 3619 | 99.5% | 2 |
| 2025 | 8239 | 4172 | 4067 | 99.7% | 2.0 |
| 2026 | 3524 | 1709 | 1815 | 98.6% | 2 |

## Casos destacados

Mejores trades con TP a liquidez:

```json
[
  {
    "time": "2025-11-05 01:15",
    "source_tf": "15m",
    "dir": "long",
    "session": "Asia",
    "rr_liq": 12.08,
    "cdc_delay_bars": 8,
    "fixed_R": 1.8182,
    "liq_R": 11.8962,
    "outcome_liq": "win"
  },
  {
    "time": "2025-04-16 17:45",
    "source_tf": "15m",
    "dir": "long",
    "session": "NY",
    "rr_liq": 17.677,
    "cdc_delay_bars": 10,
    "fixed_R": 1.8165,
    "liq_R": 10.5422,
    "outcome_liq": "time"
  },
  {
    "time": "2025-09-15 05:45",
    "source_tf": "15m",
    "dir": "short",
    "session": "Asia",
    "rr_liq": 8.271,
    "cdc_delay_bars": 7,
    "fixed_R": 1.7729,
    "liq_R": 8.0451,
    "outcome_liq": "win"
  },
  {
    "time": "2025-08-01 14:15",
    "source_tf": "15m",
    "dir": "short",
    "session": "NY",
    "rr_liq": 8.003,
    "cdc_delay_bars": 11,
    "fixed_R": 1.8605,
    "liq_R": 7.8647,
    "outcome_liq": "win"
  },
  {
    "time": "2024-06-12 14:15",
    "source_tf": "1h",
    "dir": "short",
    "session": "NY",
    "rr_liq": 5.925,
    "cdc_delay_bars": 8,
    "fixed_R": 1.9234,
    "liq_R": 5.8492,
    "outcome_liq": "win"
  },
  {
    "time": "2025-04-30 13:45",
    "source_tf": "15m",
    "dir": "long",
    "session": "NY",
    "rr_liq": 5.89,
    "cdc_delay_bars": 15,
    "fixed_R": 1.8641,
    "liq_R": 5.7533,
    "outcome_liq": "win"
  },
  {
    "time": "2025-11-24 02:00",
    "source_tf": "1h",
    "dir": "short",
    "session": "Asia",
    "rr_liq": 5.846,
    "cdc_delay_bars": 9,
    "fixed_R": 1.8645,
    "liq_R": 5.7113,
    "outcome_liq": "win"
  },
  {
    "time": "2024-10-10 18:00",
    "source_tf": "15m",
    "dir": "long",
    "session": "NY",
    "rr_liq": 5.682,
    "cdc_delay_bars": 15,
    "fixed_R": 1.9273,
    "liq_R": 5.6086,
    "outcome_liq": "win"
  }
]
```

Fallos representativos de TP fijo:

```json
[
  {
    "time": "2025-10-04 21:15",
    "source_tf": "15m",
    "dir": "short",
    "session": "Fuera",
    "rr_liq": 4.444,
    "cdc_delay_bars": null,
    "fixed_R": -1.5994,
    "liq_R": -1.5994,
    "outcome_liq": "loss"
  },
  {
    "time": "2024-07-18 12:00",
    "source_tf": "15m",
    "dir": "short",
    "session": "Londres",
    "rr_liq": 4.258,
    "cdc_delay_bars": 6,
    "fixed_R": -1.5988,
    "liq_R": -1.5988,
    "outcome_liq": "loss"
  },
  {
    "time": "2023-09-26 07:30",
    "source_tf": "15m",
    "dir": "long",
    "session": "Londres",
    "rr_liq": 2.231,
    "cdc_delay_bars": 8,
    "fixed_R": -1.5954,
    "liq_R": -1.5954,
    "outcome_liq": "loss"
  },
  {
    "time": "2023-12-01 16:15",
    "source_tf": "1h",
    "dir": "short",
    "session": "NY",
    "rr_liq": 9.76,
    "cdc_delay_bars": 12,
    "fixed_R": -1.5939,
    "liq_R": -1.5939,
    "outcome_liq": "loss"
  },
  {
    "time": "2023-07-07 07:15",
    "source_tf": "15m",
    "dir": "long",
    "session": "Londres",
    "rr_liq": 4.625,
    "cdc_delay_bars": null,
    "fixed_R": -1.59,
    "liq_R": -1.59,
    "outcome_liq": "loss"
  },
  {
    "time": "2025-05-20 19:15",
    "source_tf": "15m",
    "dir": "short",
    "session": "NY",
    "rr_liq": 11.219,
    "cdc_delay_bars": 8,
    "fixed_R": -1.5883,
    "liq_R": -1.5883,
    "outcome_liq": "loss"
  },
  {
    "time": "2023-07-09 09:30",
    "source_tf": "15m",
    "dir": "long",
    "session": "Londres",
    "rr_liq": 0.977,
    "cdc_delay_bars": 12,
    "fixed_R": -1.5861,
    "liq_R": null,
    "outcome_liq": null
  },
  {
    "time": "2026-05-12 10:00",
    "source_tf": "15m",
    "dir": "long",
    "session": "Londres",
    "rr_liq": 1.281,
    "cdc_delay_bars": null,
    "fixed_R": -1.584,
    "liq_R": null,
    "outcome_liq": null
  }
]
```

## Conclusión para Nexux

La lectura del profe tiene sentido como secuencia: liquidez tomada -> desplazamiento/FVG -> OB/POI -> mitigación -> CDC -> objetivo en weak liquidity. La parte crítica para automatizar no es detectar más dibujos, sino filtrar cuáles toques tienen liquidez cercana al otro lado, riesgo estructural acotado y confirmación CDC dentro de una ventana corta. En esta muestra, M15 por sí solo genera demasiada frecuencia; conviene tratarlo como gatillo de entrada y dejar el sesgo/POI principal en timeframes superiores.
