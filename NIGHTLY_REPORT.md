# NEXUX Command Center — Nightly Report

**Fecha:** 2026-07-31  
**Rama:** `codex/command-center-contract-v1`  
**Alcance:** trabajo autorizado de Línea B, sin producción

## Resumen ejecutivo

La sesión consolidó B4 sin abrir un nuevo sprint visual. El Market Ribbon ahora
expone telemetría operacional read-only, conserva su degradación por proveedor y
usa enlaces nativos para los mercados que deben abrirse en TradingView.

El smoke autenticado confirmó que SPX abre el símbolo exacto en una pestaña
nueva y no sustituye el gráfico BTC integrado. Durante esa validación se detectó
y corrigió una referencia residual que podía dejar la banda congelada al
renderizar.

VAL-0019 y VAL-0020 permanecen perceptualmente pendientes. No existe evidencia
suficiente para cerrarlos sin una nueva observación de Hugo desde la posición
real de trabajo. B5 no se inició porque no cuenta con autorización formal.

## Objetivos

### Cumplidos

- Consolidar técnicamente B4.
- Mejorar observabilidad sin modificar el Wire ABI.
- Robustecer la navegación hacia TradingView.
- Aumentar cobertura de regresión.
- Verificar la experiencia con datos reales y sesión autenticada.
- Mantener la arquitectura y los entornos operacionales intactos.

### Pendientes

- Validación perceptual de VAL-0019 sobre el ARZOPA.
- Validación perceptual de VAL-0020 sobre el ARZOPA.
- Decisión explícita sobre el alcance de B5.

## Commits

1. `8bbad4b` — `command-center: harden B4 market ribbon`
2. Commit de cierre — incorpora únicamente este informe.

## Archivos modificados

- `modules/command_center/market_ribbon.py`: métricas de refresco, caché,
  proveedores disponibles y degradación, sin incluir datos de mercado.
- `modules/command_center/module.py`: incorpora la telemetría del Ribbon en
  `/health`.
- `modules/command_center/public/command-center.js`: convierte SPX, VIX, DXY y
  TOTAL en enlaces nativos seguros; limita el bloqueo temporal a los botones de
  gráficos integrados.
- `modules/command_center/public/command-center.css`: mantiene idéntica la
  presentación de enlaces y botones.
- `tests/test_command_center_b4_market_ribbon.py`: fija telemetría, privacidad,
  navegación externa y el guard contra referencias residuales.
- `docs/VALIDATION_LOG.md`: agrega la evidencia técnica sin cerrar gates
  perceptuales.
- `NIGHTLY_REPORT.md`: informe único de la sesión.

## Decisiones tomadas

- **No cerrar VAL-0019 ni VAL-0020.** La aprobación técnica no reemplaza la
  evaluación perceptual a 80–90 cm.
- **No iniciar B5.** El roadmap no constituye autorización de sprint.
- **Usar enlaces HTML nativos.** Son más resistentes a bloqueadores de popups,
  accesibles y conservan el layout autenticado de TradingView.
- **Mantener la telemetría fuera del Wire ABI.** `/health` es la superficie
  operacional existente y no altera el contrato congelado.
- **No versionar manualmente JS/CSS.** La ruta ya exige revalidación; se evitó
  introducir una obligación de mantenimiento sin evidencia.

## Riesgos encontrados

### P1

- VAL-0019 y VAL-0020 todavía no prueban la regla de los dos segundos desde la
  posición física real.
- Los precios externos provienen de Yahoo Finance y CoinGecko, mientras que el
  análisis abre TradingView. Diferencias pequeñas entre proveedores son
  esperables y deben seguir comunicándose mediante fuente y frescura.

### P2

- Yahoo Finance y CoinGecko son dependencias externas sin SLA para NexUX. La
  caché conserva el último valor bueno y `/health` ahora permite observar la
  degradación, pero no elimina la dependencia.

### P3

- El ejecutable `.venv/bin/pytest` conserva un shebang antiguo hacia
  `/Users/hugh/Nexux`. La suite funciona correctamente mediante
  `.venv/bin/python -m pytest`; no se modificó el entorno compartido.

## Trabajo bloqueado

- **VAL-0019:** requiere confirmación perceptual de Hugo.
- **VAL-0020:** requiere confirmación perceptual de Hugo.
- **B5:** requiere autorización explícita y definición de una sola pregunta
  operacional.
- **Producción:** bloqueada por gobernanza; no se intentó desplegar.

## Cobertura

- Suite completa: **770 pruebas aprobadas**.
- Advertencia existente: `urllib3` sobre LibreSSL 2.8.3.
- Smoke autenticado:
  - ocho activos renderizados con datos reales;
  - cuatro mercados externos como enlaces seguros;
  - cuatro perpetuos como botones de gráfico integrado;
  - SPX abrió
    `https://www.tradingview.com/chart/5qSvm5Yx/?symbol=SP%3ASPX`;
  - el gráfico integrado permaneció en BTC.
- `/health`: Market Ribbon `ready`, tres proveedores cacheados y sin errores
  activos durante la comprobación.

## Arquitectura

- Wire ABI v1: **intacto**.
- Fingerprint:
  `b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46`.
- EventBus: **sin cambios**.
- Gateway: **sin cambios**.
- Registro estático: **sin cambios**.
- Factories productivas: **0**.
- `origin/main`: sin cambios,
  `7eeb3b40733f484bb72ce7ae6462bd3c00e307d2`.
- Railway: sin acciones.
- Producción: sin acciones.
- VPS: sin acciones.

## Recomendaciones

1. Ejecutar VAL-0019 y VAL-0020 en una sola sesión física sobre el ARZOPA.
2. Mantener B4 sin nuevas capas hasta conocer ese resultado.
3. Autorizar B5 únicamente después de formular su única pregunta operacional.
4. Corregir el shebang del virtualenv en una tarea de mantenimiento separada.
5. Usar la nueva telemetría para distinguir fallos reales de proveedor de
   lecturas servidas desde caché.

