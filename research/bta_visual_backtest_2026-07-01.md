# Backtest prototipo BTA visual

Fecha: 2026-07-01. Datos: 2022-06-12 17:45 UTC a 2026-06-11 19:30 UTC, 140,163 velas BTCUSDT M15.

Este prototipo no replica el indicador del profe. Traduce lo observado en TradingView a filtros auditables:

- premium/discount de un rango operativo reciente;
- CDC dentro de 16 velas;
- liquidez objetivo con R:R >= 2.0;
- riesgo máximo 1.2%;
- preferencia por POI HTF y sesiones líquidas;
- score visual 0-10.

## Resultados

| variante | seleccionados | trades | WR | expR | PF | totalR | DD | med risk% | med RRliq |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| liq_rr2 | 874 | 605 | 26.8% | -0.129 | 0.86 | -78.07 | 100.57 | 0.324 | 3.199 |
| cdc_liq | 390 | 272 | 44.9% | 0.7 | 1.99 | 190.38 | 13.49 | 0.291 | 3.177 |
| range_cdc_liq | 245 | 176 | 44.3% | 0.626 | 1.88 | 110.22 | 11.69 | 0.305 | 3.282 |
| visual_score6 | 730 | 504 | 29.2% | -0.007 | 0.99 | -3.6 | 60.01 | 0.33 | 3.186 |
| visual_score7 | 587 | 410 | 30.7% | 0.087 | 1.1 | 35.69 | 38.46 | 0.349 | 3.198 |

## Lectura

- El filtro `liq_rr2` aísla la parte "target de liquidez" que Nexux ya tenía.
- `cdc_liq` exige que el toque tenga confirmación de carácter; baja frecuencia.
- `range_cdc_liq` agrega la idea visual del profe: long en discount o short en premium de un rango reciente.
- `visual_score6` suma contexto completo. Si mejora PF/expectativa, es la línea de trabajo para `bta_visual_model`; si no mejora, la interpretación visual todavía está incompleta.

## Ejemplos score alto

```json
[
  {
    "time": "2023-12-01 16:15",
    "dir": "short",
    "source_tf": "1h",
    "session": "NY",
    "score": 10,
    "rr_liq": 9.76,
    "risk_pct": 0.152,
    "range": [
      36707.0,
      37770.0,
      38833.0
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2025-03-03 19:45",
    "dir": "long",
    "source_tf": "1h",
    "session": "NY",
    "score": 10,
    "rr_liq": 9.021,
    "risk_pct": 0.698,
    "range": [
      78258.52,
      86629.26,
      95000.0
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2025-05-15 16:30",
    "dir": "short",
    "source_tf": "1h",
    "session": "NY",
    "score": 10,
    "rr_liq": 6.867,
    "risk_pct": 0.311,
    "range": [
      100718.37,
      103268.91,
      105819.45
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2025-03-12 14:30",
    "dir": "long",
    "source_tf": "1h",
    "session": "NY",
    "score": 10,
    "rr_liq": 6.553,
    "risk_pct": 0.532,
    "range": [
      76606.0,
      84708.32,
      92810.64
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2026-05-15 13:30",
    "dir": "long",
    "source_tf": "4h",
    "session": "NY",
    "score": 10,
    "rr_liq": 6.086,
    "risk_pct": 0.338,
    "range": [
      78754.65,
      80616.99,
      82479.32
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2024-06-12 14:15",
    "dir": "short",
    "source_tf": "1h",
    "session": "NY",
    "score": 10,
    "rr_liq": 5.925,
    "risk_pct": 0.52,
    "range": [
      66051.0,
      69024.01,
      71997.02
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2025-12-29 10:45",
    "dir": "long",
    "source_tf": "1h",
    "session": "Londres",
    "score": 10,
    "rr_liq": 5.425,
    "risk_pct": 0.429,
    "range": [
      86420.0,
      88504.11,
      90588.23
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2025-02-19 10:00",
    "dir": "short",
    "source_tf": "1h",
    "session": "Londres",
    "score": 10,
    "rr_liq": 4.721,
    "risk_pct": 0.166,
    "range": [
      93388.09,
      96107.04,
      98826.0
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2025-02-02 18:30",
    "dir": "long",
    "source_tf": "1h",
    "session": "NY",
    "score": 10,
    "rr_liq": 4.131,
    "risk_pct": 0.589,
    "range": [
      96862.02,
      101659.73,
      106457.44
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2023-08-14 18:00",
    "dir": "long",
    "source_tf": "1h",
    "session": "NY",
    "score": 10,
    "rr_liq": 4.067,
    "risk_pct": 0.31,
    "range": [
      28973.03,
      29608.51,
      30244.0
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2026-02-18 15:30",
    "dir": "short",
    "source_tf": "1h",
    "session": "NY",
    "score": 10,
    "rr_liq": 3.473,
    "risk_pct": 0.589,
    "range": [
      65118.0,
      68050.5,
      70983.0
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  },
  {
    "time": "2024-11-15 12:00",
    "dir": "short",
    "source_tf": "1h",
    "session": "Londres",
    "score": 10,
    "rr_liq": 3.157,
    "risk_pct": 1.151,
    "range": [
      75630.76,
      84448.2,
      93265.64
    ],
    "reasons": [
      "premium/discount global correcto",
      "CDC confirmado",
      "liquidez con RR>=2",
      "riesgo acotado",
      "POI HTF",
      "sesion liquida",
      "rango reciente suficiente"
    ]
  }
]
```

## Próximo paso

Validar estos candidatos contra capturas del chart del profe. El modelo sólo queda aceptado si reproduce los casos visuales de junio 2026, mayo 2026 y noviembre 2025 sin sobreajustar.
