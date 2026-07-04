# Catálogo operativo de zonas BTA

Fecha: 2026-07-01. Fuente: capturas locales del TradingView `Bitcoin Traders Academy`, `BTCUSDT.P`, `15m`.

Este catálogo no pretende reconstruir el indicador completo. Su función es convertir cada captura en una ficha útil para comparar contra Nexux.

## Escala de confianza

- Alta: etiquetas/zonas visibles y datos posteriores consistentes.
- Media: etiquetas visibles, pero falta re-navegación para confirmar precio exacto o secuencia.
- Baja: captura no concluyente o repetida por estado del chart.

## Fichas

### 1. `2026-06-17_blue_range_premium_discount.jpg`

Confianza: alta.

Etiquetas/objetos visibles:

- `Premium POI X Confirmación`
- `counter POI`
- `Discount POI`
- `Discount POI x confirmación`
- franjas azules verticales
- check verde
- máximo/mínimo operativo

Lectura BTA:

Mapa completo de distribución/rango. La zona premium no se evalúa aislada: tiene contraparte discount, POI intermedio y confirmación por CDC/reacción. El precio responde con desplazamiento bajista hacia liquidez inferior.

Datos:

- rango medido: `67.255 -> 60.193` (`11.73%`);
- desde centro: `+0.92% / -5.44%` en 24h.

Traducción Nexux:

- `RangeMap` requerido;
- `Zone.kind=premium_poi`, `counter_poi`, `discount_poi`;
- `Zone.state=confirmed` para la zona que recibe check/reacción;
- target a weak low/range low.

Brecha:

Nexux no tiene todavía estado simultáneo de varias zonas dentro del mismo rango.

### 2. `2026-06-24_discount_poi_confirmacion.jpg`

Confianza: alta.

Etiquetas/objetos visibles:

- `Discount POI x confirmación`
- `Alto Referencial (Resistencia)`
- `Strong High (Nivel De Resistencia)`
- zonas grises
- mínimo operativo
- niveles horizontales apilados

Lectura BTA:

La zona discount funciona como punto de reacción/confirmación dentro de una secuencia ya bajista. El `Strong High` y el `Alto Referencial` ordenan invalidación o resistencia; el mínimo inferior funciona como liquidez.

Datos:

- rango medido: `66.419 -> 57.758` (`14.99%`);
- desde centro: `+2.38% / -4.07%` en 24h.

Traducción Nexux:

- `CharacterLevel` debe persistir después del toque;
- una entrada debería esperar CDC/reacción, no sólo mitigación de POI;
- `Strong High` debería ser objeto explícito de invalidación.

Brecha:

Falta diferenciar `Discount POI` normal vs `Discount POI x confirmación`.

### 3. `2026-06-11_premium_discount_check.jpg`

Confianza: alta.

Etiquetas/objetos visibles:

- `Premium POI`
- `Discount POI`
- checks verdes
- líneas `CDC`
- diagonal/leg naranja
- franjas azules
- pivotes celestes

Lectura BTA:

Secuencia didáctica de transición: swing -> CDC -> POI -> desplazamiento -> check. El check parece representar que la zona ya reaccionó y cambió de estado.

Datos:

- rango medido: `67.255 -> 60.363` (`11.42%`);
- desde centro: `+2.49% / -0.77%` en 24h;
- desde centro: `+3.09% / -0.77%` en 72h.

Traducción Nexux:

- `Zone.state=confirmed`;
- `validation_mark=check`;
- `CharacterLevel.state=broken/respected`;
- `SwingLeg` para la diagonal/impulso.

Brecha:

Nexux calcula CDC, pero no conserva una marca visible de validación de zona.

### 4. `2026-05-27_drop_to_orange_target.jpg`

Confianza: media-alta.

Etiquetas/objetos visibles:

- caja naranja de objetivo/rango
- zona celeste superior
- zona de continuación
- `Premium POI` / `Discount` en contexto de franja azul
- mínimos/máximos operativos

Lectura BTA:

Continuación bajista después de perder estructura. La caja naranja parece representar una zona de llegada o toma de liquidez, no una entrada.

Datos:

- rango medido: `78.180 -> 65.359` (`19.62%`);
- desde centro: `+0.17% / -3.60%` en 24h;
- desde centro: `+0.17% / -3.76%` en 72h.

Traducción Nexux:

- `Zone.kind=target`;
- `Zone.state=target_hit`;
- estados de zona perdida y retesteada.

Brecha:

Nexux no tiene objeto de caja objetivo manual/visual comparable.

### 5. `2026-05-15_discount_cdc_zones.jpg`

Confianza: media-alta.

Etiquetas/objetos visibles:

- `Discount POI`
- `CDC`
- zonas celestes horizontales
- máximo/mínimo operativo
- caída tras pérdida de zona

Lectura BTA:

Caso clave para no simplificar: aunque aparece `Discount POI`, la lectura visible termina siendo bajista cuando el CDC se pierde y las zonas celestes pasan a funcionar como retest/continuación.

Datos:

- rango medido: `82.460 -> 76.014` (`8.48%`);
- desde centro: `+0.47% / -1.97%` en 24h;
- desde centro: `+0.47% / -3.97%` en 72h.

Traducción Nexux:

- `CharacterLevel.state=broken`;
- `Zone.state=failed` y luego `retest_continuation`;
- prioridad de contexto por encima del tipo original `Discount`.

Brecha:

El prototipo automático encontró un long HTF cercano, lo que muestra conflicto de jerarquía. Este caso debe revisarse manualmente antes de entrenar una regla.

### 6. `2025-11-05_zigzag_structure.jpg`

Confianza: media.

Etiquetas/objetos visibles:

- zigzag morado
- pivotes/círculos celestes
- flechas de leg
- líneas rojas de medición
- etiquetas `0/1`

Lectura BTA:

No es un caso típico de POI. Es lectura de estructura: legs, pivotes, mediciones y posible secuencia de liquidez. Sirve para decidir qué zonas están alineadas con el swing dominante.

Datos:

- rango medido: `111.250 -> 98.944` (`12.44%`);
- desde centro: `+2.60% / -0.69%` en 24h;
- desde centro: `+2.60% / -2.57%` en 72h.

Traducción Nexux:

- `SwingLeg`;
- `pivot_a`, `pivot_b`;
- `leg_direction`;
- `leg_state`;
- target/invalidación por pivote.

Brecha:

Los pivotes weak/strong de Nexux no son suficientes si no se conectan como leg activa.

Advertencia:

La lámina de revisión muestra que `2025-04-16_liquidity_case.jpg`, `2025-08-01_structure_context.jpg` y `2025-11-05_zigzag_structure.jpg` son visualmente la misma escena o quedaron capturadas en el mismo estado del chart. Por lo tanto, esta captura sirve como evidencia de la capa zigzag/leg, pero no como prueba fuerte de que el chart fue navegado correctamente a tres fechas distintas.

### 7. `2026-01-15_level_cluster.jpg`

Confianza: baja-media.

Etiquetas/objetos visibles:

- cluster de niveles horizontales;
- referencias apiladas en eje de precio.

Lectura BTA:

Parece más una zona de referencias/alertas que una secuencia POI completa. Requiere re-navegación para confirmar si los niveles eran liquidez, alertas o soportes/resistencias manuales.

Traducción Nexux:

- posible `intermediate_liquidity`;
- posible `reference_level`.

Brecha:

No usar como evidencia fuerte todavía.

### 8. `2025-08-01_structure_context.jpg`

Confianza: baja.

Lectura:

Captura no concluyente por estado del chart/zoom. En la lámina se ve igual o prácticamente igual a las capturas `2025-04-16` y `2025-11-05`, por lo que no debe contarse como evidencia independiente. Debe re-navegarse desde el chart limpio.

### 9. `2025-04-16_liquidity_case.jpg`

Confianza: baja.

Lectura:

Captura no concluyente por estado del chart/zoom. En la lámina se ve igual o prácticamente igual a las capturas `2025-08-01` y `2025-11-05`. El backtest base sí tiene un trade destacado el `2025-04-16 17:45`, pero esta captura no basta para afirmar que coincide con la lectura visual del profe.

## Taxonomía resultante

Objetos mínimos para Nexux:

- `RangeMap`: rango operativo, EQ, premium, discount.
- `Zone`: tipo, precio, estado, origen y validación.
- `CharacterLevel`: CDC persistente con estado.
- `SwingLeg`: pivotes conectados, dirección e invalidación.
- `ReferenceLevel`: `Alto Referencial`, `Strong High`, niveles intermedios.
- `TargetZone`: caja naranja/celeste de llegada.

Estados mínimos de zona:

- `pending`
- `tapped`
- `confirmed`
- `failed`
- `retest_continuation`
- `target_hit`

## Conclusión del catálogo

Las capturas fuertes de mayo/junio 2026 apoyan una tesis clara: BTA no premia más detección de zonas, sino mejor gestión del estado de cada zona. La capa zigzag/leg está visualmente presente, pero las capturas antiguas repetidas obligan a re-navegar el chart limpio antes de usar 2025 como evidencia histórica independiente. La regla cuantitativa `CDC + liquidez` es el primer proxy medible; la siguiente capa debe ser `Zone.state + SwingLeg`.
