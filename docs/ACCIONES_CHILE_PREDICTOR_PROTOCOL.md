# Protocolo del predictor — Acciones Chile

**Estado:** preregistro de diseño; entrenamiento no autorizado  
**Fecha:** 2026-08-22

## Pregunta

¿La información disponible al publicarse un estado financiero ayuda a anticipar
retornos ajustados por mercado en acciones chilenas, después de costos, mejor que
un benchmark simple?

## Unidad y tiempo causal

- Una observación es una sociedad–publicación trimestral.
- `available_at` es la hora del mensaje de HechosEsencialesChile.
- Si ocurre con el mercado abierto, la primera decisión simulable usa el siguiente
  precio ejecutable después de `available_at`; fuera de horario, la apertura siguiente.
- Ninguna fecha interna del PDF puede adelantar `available_at`.

## Etiquetas futuras

- Retorno total ajustado a 1, 5 y 20 ruedas bursátiles.
- Exceso de retorno frente al IPSA en el mismo intervalo.
- Costos y slippage definidos antes del experimento.
- Dividendos, splits, aumentos de capital y símbolos deslistados deben ajustarse.

## Features permitidas

- Ventas, crecimiento interanual, utilidades y márgenes CMF conocidos al evento.
- Para bancos, sólo métricas de CMF Bancos con cuenta contable validada y
  disponibilidad unida al evento; nunca aplicar las métricas IFRS societarias.
- Cambio respecto del mismo trimestre del año anterior.
- Hora/día de publicación, retraso desde cierre trimestral y tipo de balance.
- Cantidad de hechos esenciales conocidos en los 30 días previos.
- Sector y tamaño, si provienen de una fuente trazable.
- Flujo operativo, capex, flujo de caja libre, caja, inventarios, activos,
  pasivos, patrimonio y cobertura corriente CMF.
- EPS básico anual para mostrar un P/E observado sólo cuando precio y moneda son
  compatibles. Precio justo y margen de seguridad permanecen nulos hasta
  calibrar el múltiplo sectorial.

## Features prohibidas en la primera cohorte

- Videos de @inversorchileno: sirven para interpretación y contraste, pero suelen
  publicarse después del resultado y producirían contaminación post-evento.
- Composición de la cartera personal: introduce sesgo de selección.
- Precios, titulares, revisiones o documentos conocidos después de `available_at`.
- Variables de módulos cripto.

## Capa de decisión humana

El score fundamental no se convierte directamente en comprar/vender. Primero
debe existir precio y valorización autorizados, múltiplo apropiado al sector,
margen de seguridad, costo de la posición y plan personal. Una alerta de venta
requiere un gatillante crítico o acumulación de deterioros, no un trimestre malo.
El sistema puede sugerir `mantener`, `observar` o `revisar posible reducción`,
pero jamás enviar una orden.

## Gate mínimo

- Ocho trimestres completos como mínimo.
- Fuente de precios ajustados y benchmark IPSA con licencia/uso compatible.
- Mapeo ticker–RUT versionado y manejo de cambios de símbolo/deslistes.
- Split temporal walk-forward; nunca división aleatoria.
- Baseline ingenuo y modelo interpretable antes de modelos complejos.
- Evaluación OOS congelada, intervalos de confianza y resultados negativos preservados.

El backfill completo contiene 809 publicaciones financieras y 564 observaciones
empresa–trimestre de 97 sociedades entre marzo de 2025 y agosto de 2026. Cubre
siete períodos; la mediana por empresa es seis y ninguna puede aportar ocho
trimestres desde este canal todavía. También falta la fuente autorizada de
precios. El join histórico CMF↔Telegram entrega 428 candidatos causales y deja
tres AFP explícitamente sin matching. Por lo tanto no existe predictor ni señal
autorizada.
