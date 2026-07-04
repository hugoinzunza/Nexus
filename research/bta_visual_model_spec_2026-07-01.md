# Especificación inicial `bta_visual_model`

Objetivo: modelar en Nexux la lectura visual observada en el TradingView `Bitcoin Traders Academy` sin copiar código propietario. Se traduce sólo lo visible: zonas, estados, pivotes, CDC y outcomes.

## Modelo de objetos

### `RangeMap`

Representa el rango operativo visible.

Campos:

- `t_start`, `t_end`
- `high`, `high_t`, `high_kind`: `maximo`, `alto_referencial`, `strong_high`
- `low`, `low_t`, `low_kind`: `minimo`, `weak_low`, `target_low`
- `eq`
- `premium_lo`, `premium_hi`
- `discount_lo`, `discount_hi`
- `bias`: `bullish`, `bearish`, `range`

Regla:

- Si el precio está sobre `eq`, sólo POIs de venta tienen prioridad salvo CDC alcista limpio.
- Si el precio está bajo `eq`, sólo POIs de compra tienen prioridad salvo continuación bajista ya confirmada.

### `Zone`

Representa una zona gris/celeste/naranja del chart.

Campos:

- `kind`: `premium_poi`, `discount_poi`, `counter_poi`, `reference`, `target`, `intermediate_liquidity`
- `lo`, `hi`, `mid`
- `created_t`, `source_tf`
- `state`: `pending`, `tapped`, `confirmed`, `failed`, `retest_continuation`, `target_hit`
- `requires_cdc`: boolean
- `cdc_level_id`
- `validation_mark`: `none`, `check`, `eyes`, `manual`

Estados:

- `pending`: precio no toca.
- `tapped`: precio toca zona.
- `confirmed`: toca y desplaza a favor o rompe CDC correcto.
- `failed`: atraviesa la zona/stop estructural.
- `retest_continuation`: zona perdida que luego actúa como resistencia/soporte.
- `target_hit`: precio llega a liquidez objetivo.

### `CharacterLevel`

Representa el `CDC` rojo/rosado.

Campos:

- `price`
- `direction`: `bullish_break`, `bearish_break`
- `created_t`
- `broken_t`
- `reclaimed_t`
- `state`: `pending`, `broken`, `respected`, `reclaimed`, `invalidated`

Regla:

- Un POI con `requires_cdc=True` no dispara entrada sólo por toque.
- Si CDC se pierde y luego se retestea desde el otro lado, la zona cambia a continuación.

### `SwingLeg`

Representa la capa de zigzag morado/pivotes celestes.

Campos:

- `pivot_a`, `pivot_b`
- `direction`
- `leg_high`, `leg_low`
- `fib0`, `fib1`, `eq`
- `state`: `forming`, `completed`, `swept`, `invalidated`

Regla:

- La entrada sólo vale si la zona está alineada con la leg activa o con reversa confirmada por CDC.

### `SetupCandidate`

Compone los objetos anteriores.

Campos:

- `zone_id`
- `range_id`
- `cdc_id`
- `swing_leg_id`
- `entry`
- `sl`
- `tp`
- `tp_kind`: `weak_high`, `weak_low`, `alto_referencial`, `range_low`, `range_high`
- `rr`
- `score`
- `decision`: `watch`, `valid`, `skip`, `invalidated`

## Score inicial

Propuesta de score 0-10:

- +2 zona correcta para premium/discount.
- +2 CDC confirmado o respetado.
- +1 reacción visible: rechazo, wick, displacement.
- +1 alineado con leg/zigzag.
- +1 target claro de liquidez.
- +1 R:R >= 2.
- +1 sesión Londres/NY si el backtest lo valida.
- +1 zona no mitigada previamente.
- -2 si entra contra `Alto Referencial`/`Strong High` cercano.
- -2 si el target ya fue barrido.
- -3 si CDC fue perdido contra la idea.

## Hipótesis a testear

1. POI plano pierde; POI con `state=confirmed` mejora.
2. `Discount POI x confirmación` exige CDC posterior; sin CDC es sólo vigilancia.
3. `Premium POI` que falla y se pierde pasa a `retest_continuation`.
4. `Alto Referencial` y `Strong High` deben ser objetivos/invalidaciones, no simples pivotes.
5. La capa `SwingLeg` reduce trades M15 ruidosos.

## Implementación sugerida

Archivos nuevos:

- `modules/trading/bta_visual.py`
- `research/bta_visual_backtest.py`
- `tests/test_bta_visual.py`

Estado 2026-07-01:

- Prototipo creado en `research/bta_visual_model.py`.
- Checks básicos creados en `research/test_bta_visual_model.py`.
- Se mantiene en research; no toca producción ni el bot vivo.
- El test detectó y corrigió una transición inválida: una zona no puede pasar de `failed` a `retest_continuation` en la misma vela que falla.

Funciones:

- `build_range_map(candles, piv=10, window=800)`
- `detect_character_levels(candles, piv=2)`
- `detect_visual_zones(candles, pois, range_map, cdc_levels)`
- `update_zone_states(candles, zones)`
- `build_setup_candidates(candles, zones, swing_legs)`
- `simulate_visual_candidates(candles, candidates)`

## Criterio de éxito

No basta con subir win rate. El modelo tiene que:

- Reducir frecuencia respecto a POI plano.
- Mejorar PF y expectativa fuera de muestra.
- Reproducir visualmente los casos del chart del profe: junio 2026, mayo 2026 y zigzag noviembre 2025.
- Generar explicaciones legibles: “zona perdida -> retest -> continuación” o “discount POI + CDC confirmado -> target weak high/low”.
