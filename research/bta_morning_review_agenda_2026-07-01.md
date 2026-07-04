# Agenda revisión mañana - BTA TradingView

Fecha: 2026-07-01.

Objetivo de la reunión: decidir si limpiamos/re-navegamos TradingView y qué parte del modelo BTA pasa a siguiente fase en Nexux.

## Orden recomendado

1. Abrir el HTML:
   - `/Users/hugh/crisol/nexux/research/bta_morning_review_2026-07-01.html`
2. Revisar la corrección importante:
   - Las capturas `2025-04-16`, `2025-08-01`, `2025-11-05` quedaron repetidas o casi iguales.
3. Revisar el hallazgo cuantitativo:
   - POI + liquidez RR>=2: `605` trades, `26.8%` WR, `-0.129R`, PF `0.86`.
   - POI + CDC + liquidez: `272` trades, `44.9%` WR, `+0.700R`, PF `1.99`.
4. Decidir si se recarga/limpia TradingView.
5. Si se autoriza, ejecutar protocolo de re-navegación.

## Decisiones que necesito de Hugo

### 1. Chart TradingView

Pregunta:

```text
¿Autorizas recargar el chart de TradingView aunque descarte cambios no guardados?
```

Opciones:

- Sí: recargar y empezar re-navegación limpia.
- No: borrar manualmente el texto accidental y confirmar que el layout quedó estable.
- Esperar: no tocar TradingView y seguir sólo con research offline.

### 2. Prioridad de captura

Pregunta:

```text
¿Partimos por reemplazar 2025 o por ampliar 2026?
```

Recomendación: empezar por 2025 porque es la brecha más grave.

Orden sugerido:

1. `2025-04-16`
2. `2025-08-01`
3. `2025-11-05`
4. `2026-01-15`
5. `2024` si el layout conserva anotaciones

### 3. Nexux

Pregunta:

```text
¿El siguiente trabajo en Nexux debe ser sólo research o empezamos integración controlada?
```

Recomendación: mantenerlo en research hasta tener capturas limpias 2025/2024.

Pieza técnica lista:

- `research/bta_visual_model.py`
- `research/test_bta_visual_model.py`

No llevar aún a producción:

- alertas;
- ejecución;
- señales reales;
- cambios en bot vivo.

## Lo que considero probado

- El profe no opera cualquier OB/FVG.
- La lectura visible usa rango, premium/discount, POI, CDC, reacción, liquidez y estado de zona.
- `CDC + liquidez` es el filtro cuantitativo que más conversa con lo visual.
- Nexux necesita `Zone.state`, `CharacterLevel`, `SwingLeg`, `ReferenceLevel` y `TargetZone`.

## Lo que no considero probado

- Recorrido histórico amplio en TradingView.
- Evidencia visual independiente de 2025.
- Evidencia visual confiable de 2024.
- Que la capa zigzag reduzca ruido en backtest fuera de muestra.
- Que el rango mecánico de 7 días represente bien el rango manual del profe.

## Checklist si se autoriza navegar

Abrir:

- `/Users/hugh/crisol/nexux/research/bta_tradingview_renavigation_protocol_2026-07-01.md`
- `/Users/hugh/crisol/nexux/research/bta_clean_capture_checklist_2026-07-01.md`

Guardar capturas en:

```text
/Users/hugh/crisol/nexux/research/tradingview_bta_screenshots_clean_2026-07-01/
```

Después correr:

```bash
python3 /Users/hugh/crisol/nexux/research/bta_clean_capture_ingest.py
python3 /Users/hugh/crisol/nexux/research/bta_package_manifest.py
python3 /Users/hugh/crisol/nexux/research/bta_verify_package.py
```

## Cierre esperado de la reunión

Al final deberíamos tener una de estas tres decisiones:

1. `Navegar ahora`: limpiar chart y capturar 2025/2024.
2. `Research offline`: seguir mejorando backtest/modelo sin tocar TradingView.
3. `Pausar`: revisar primero con el profe o con más contexto antes de tocar nada.
