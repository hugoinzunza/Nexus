# Matriz de alineación BTA TradingView vs Nexux

Fecha: 2026-07-01. Objetivo: convertir la observación visual del chart del profe en requisitos concretos para Nexux.

## Lectura base

La plantilla BTA visible en TradingView trabaja como un sistema de estados:

1. define extremos de rango (`Máximo`, `Mínimo`, `Alto Referencial`, `Strong High`);
2. separa premium/discount;
3. marca POIs según ubicación y rol;
4. espera `CDC` o confirmación;
5. valida o invalida con reacción;
6. transforma zonas perdidas en retests de continuación;
7. usa liquidez visible como objetivo;
8. superpone una capa swing/zigzag para decidir si la zona tiene sentido.

Nexux ya detecta varias piezas, pero todavía las trata demasiado como señales independientes.

## Matriz caso por caso

| caso visual | lectura BTA observada | movimiento medido | qué cubre Nexux hoy | brecha |
| --- | --- | --- | --- | --- |
| `2026-06-17_blue_range_premium_discount` | Rango grande con `Premium POI X Confirmación`, `counter POI`, `Discount POI`, franjas azules y mínimo operativo. | Rango `67.255 -> 60.193` (`11.73%`). Desde el centro: `+0.92% / -5.44%` en 24h. | Detecta POI, FVG, liquidez y CDC posterior en M15/HTF. | Falta mapa de rango simultáneo y estado de cada zona. Nexux no distingue bien `counter POI` ni `x confirmación`. |
| `2026-06-24_discount_poi_confirmacion` | Secuencia premium -> strong high/intermedio -> discount POI x confirmación -> mínimo. | Rango `66.419 -> 57.758` (`14.99%`). Desde el centro: `+2.38% / -4.07%` en 24h. | Puede modelar target a weak low/high y CDC. | Falta convertir la zona baja en objeto de confirmación, no simple entrada al toque. |
| `2026-06-11_premium_discount_check` | POI con check verde, CDC, desplazamiento y transición de discount a premium. | Rango `67.255 -> 60.363` (`11.42%`). Desde el centro: `+2.49% / -0.77%` en 24h. | CDC + liquidez es el filtro que mejor rindió en el prototipo. | Falta registrar reacción/check como estado de zona y no como dato efímero. |
| `2026-05-27_drop_to_orange_target` | Continuación bajista hacia caja objetivo naranja después de perder estructura. | Rango `78.180 -> 65.359` (`19.62%`). Desde el centro: `+0.17% / -3.60%` en 24h. | Puede detectar continuidad si hay POI + CDC + target. | Falta objeto `target zone`/caja naranja y lógica de zona perdida -> retest -> continuación. |
| `2026-05-15_discount_cdc_zones` | `Discount POI`, CDC perdido, zonas celestes intermedias actuando como retests/targets. | Rango `82.460 -> 76.014` (`8.48%`). Desde el centro: `+0.47% / -3.97%` en 72h. | El prototipo detectó un ejemplo score 10 cercano a `2026-05-15 13:30`, pero con dirección long por POI 4h; esto obliga a revisar manualmente. | Posible conflicto entre POI HTF automático y lectura visual M15 bajista. Falta jerarquía de contexto para resolverlo. |
| `2025-11-05_zigzag_structure` | Zigzag morado, pivotes celestes, flechas, medición `0/1`; lectura explícita de legs. | Rango cuantitativo de referencia `111.250 -> 98.944` (`12.44%`), pero la captura debe tratarse con cautela porque las capturas antiguas quedaron repetidas visualmente. | Nexux tiene pivotes weak/strong, pero no una leg activa visual comparable. | Falta `SwingLeg`: pivotes conectados, dirección de leg, invalidación y target por estructura. Requiere re-navegación limpia para validar el caso histórico. |

## Hallazgo cuantitativo que sí conversa con el chart

El backtest plano confirma que la caja sola no basta:

- POI + liquidez RR>=2: `605` trades, `26.8%` WR, `-0.129R`, PF `0.86`.
- POI + CDC + liquidez: `272` trades, `44.9%` WR, `+0.700R`, PF `1.99`.
- rango + CDC + liquidez: `176` trades, `44.3%` WR, `+0.626R`, PF `1.88`.

Interpretación: la mejora real viene al exigir confirmación de carácter y target de liquidez. Esto calza con `Premium/Discount POI x Confirmación`: el texto `x confirmación` del profe no es adorno; es probablemente la diferencia entre vigilar una zona y operar una señal.

## Qué debe cambiar en Nexux

### 1. Separar observación de señal

Hoy una zona puede terminar actuando como señal demasiado pronto. BTA parece separar:

- zona pendiente;
- toque;
- CDC;
- reacción;
- entrada;
- fallo;
- retest de continuación;
- target.

Esto debe ir en `Zone.state`.

### 2. Agregar `CharacterLevel` persistente

El CDC no debe ser sólo un check posterior al toque. Debe tener vida propia:

- `pending`;
- `broken`;
- `respected`;
- `reclaimed`;
- `invalidated`.

El estado del CDC decide si una zona sigue siendo reversa, queda inválida o pasa a continuación.

### 3. Convertir el rango en objeto

El rango visible del profe no siempre coincide con una ventana fija. Por eso el filtro mecánico de rango ayudó, pero no fue el mejor. Hay que probar:

- rango por últimos pivotes PIV10/PIV20;
- rango por swing HTF;
- rango por último impulso-distribución;
- rango manual inferido desde máximos/mínimos operativos.

### 4. Modelar zonas de continuación

Mayo 2026 muestra que una zona perdida puede quedar como resistencia/soporte de retest. Nexux necesita un estado `retest_continuation`, no sólo invalidación.

### 5. Agregar `SwingLeg`

Noviembre 2025 no se explica bien con POI/FVG. Se necesita:

- pivote A/B;
- dirección de leg;
- leg actual;
- punto de invalidación;
- objetivo de liquidez;
- relación con premium/discount.

## Regla candidata para implementar primero

Prioridad 1:

```text
POI valido =
  zona en contexto premium/discount razonable
  AND target de liquidez opuesta con RR >= 2
  AND CDC confirmado dentro de N velas
  AND riesgo estructural acotado
```

Esta regla ya mejoró el control cuantitativo. Después se agregan `Zone.state` y `SwingLeg`.

## Riesgos de interpretación

- Las capturas de 2026 están mejor fundamentadas que las más antiguas.
- Junio 2026 usa datos recientes de futures (`BTCUSDT.P`), mientras el backtest histórico principal usa cache local BTCUSDT spot hasta `2026-06-11`.
- Los casos antiguos guardados no son concluyentes: `2025-04-16`, `2025-08-01` y `2025-11-05` quedaron visualmente iguales o muy parecidos en la lámina. Sirven como evidencia de que existe capa zigzag, no como tres muestras históricas independientes.
- La plantilla del profe puede tener elementos manuales; no hay código propietario visible.

## Conclusión operativa

Para comparar de verdad con la estrategia del profe, Nexux no necesita “más POIs”. Necesita una máquina de estados sobre zonas: rango, ubicación, CDC, reacción, retest y liquidez. El primer filtro implementable es `CDC + liquidez`; la siguiente mejora real es persistir estados de zona y leg estructural.
