# NEXUX Command Center — Viewport Specification

- **Estado:** Fase -1B nocturna aprobada; calibración diurna pendiente
- **Versión:** 0.2
- **Fecha:** 2026-07-30
- **Propósito:** definir y validar el entorno físico donde vivirá el Command Center

## 1. Responsabilidad

Este documento gobierna las restricciones físicas, ergonómicas y perceptuales del
Command Center. No define su identidad, arquitectura ni lenguaje visual.

| Documento | Responsabilidad |
|---|---|
| `PRODUCT_CHARTER.md` | Identidad y principios permanentes del producto |
| `RFC_COMMAND_CENTER.md` | Arquitectura, contratos, despliegue, pruebas y riesgos |
| `VIEWPORT_SPECIFICATION.md` | Entorno físico y límites perceptuales |
| `DESIGN_SYSTEM.md` | Lenguaje visual, después de completar la Fase -1B |
| `UX_MANIFESTO.md` | Principios permanentes de interacción; documento futuro |

Toda decisión de UX debe respetar esta especificación. Un componente no puede
compensar una limitación física ocultando información crítica o reduciendo su
legibilidad.

## 2. Estados de evidencia

- **Verificado:** medido directamente en el equipo.
- **Objetivo:** condición deseada del producto.
- **Hipótesis:** valor inicial que debe probarse en la Fase -1B.
- **Pendiente:** no existe evidencia suficiente.

Estos estados evitan convertir una intención de diseño en una propiedad del
hardware.

## 3. Hardware

| Elemento | Estado | Especificación |
|---|---|---|
| Equipo | Verificado | Mac mini con Apple M4 |
| Monitor principal | Verificado | TCL 34R83Q |
| Resolución principal | Verificado | 3440 × 1440 |
| Frecuencia principal | Verificado | 170 Hz |
| Monitor secundario | Verificado | ARZOPA, panel horizontal de aproximadamente 14 pulgadas |
| Identificación EDID | Verificado | Vendor `1ee4`, producto `0140`, serie `89610209`, fabricación semana 17 de 2025 |
| Área física informada | Verificado | 310 × 170 mm; diagonal calculada de 13,92 pulgadas |
| Resolución secundaria | Verificado | 1920 × 1080 nativa y efectiva |
| Densidad calculada | Verificado | Aproximadamente 158 PPI |
| Posición física secundaria | Verificado | Bajo el monitor principal como superficie de monitoreo |
| Disposición macOS | Verificado | A la izquierda del principal: origen lógico `(-1920, 0)` |
| Inclinación secundaria | Hipótesis | Aproximadamente 30° hacia el usuario |
| Escalado efectivo | Verificado | 1:1; bounds y pixels coinciden en 1920 × 1080 |
| Frecuencia secundaria | Verificado | 60 Hz |
| Rotación | Verificado | 0°, horizontal |
| Conexión | Verificado | USB-C al Mac mini |
| Brillo relativo | Observación | Menor luminancia percibida que el TCL MiniLED |

La resolución nativa no equivale al viewport útil. El producto se diseñará contra
el viewport CSS medido con el shell, navegador y escala reales.

La posición lógica de macOS no coincide todavía con la posición física descrita.
No bloquea el prototipo, pero debe corregirse o justificarse antes de validar
movimiento del cursor entre pantallas.

## 4. Ergonomía objetivo

El monitor secundario debe permitir consultas breves sin inclinar sostenidamente el
cuello ni desplazar el torso.

- Distancia inicial a probar: **55–75 cm** desde los ojos a la superficie.
- Centro del monitor: objetivo de **15–20° bajo la línea horizontal de visión**.
- Pantalla: aproximadamente perpendicular a la línea de visión; la inclinación
  inicial de 30° se ajustará si genera reflejos o distorsión.
- Alineación horizontal: centro de la pantalla alineado con el usuario y el monitor
  principal.
- Relación funcional: el monitor principal conserva el trabajo detallado; el
  secundario ofrece conciencia situacional persistente.
- Postura de validación: espalda apoyada, cabeza alineada con el torso y sin
  adelantarse para leer.

OSHA sitúa la distancia general preferida entre 50 y 100 cm, el centro del monitor
entre 15 y 20° bajo la mirada horizontal y recomienda que la superficie quede
aproximadamente perpendicular a la línea de visión. Los valores más estrechos de
esta especificación son hipótesis específicas del escritorio, no reglas
universales.

### Mediciones requeridas

La Fase -1B registrará:

- distancia ojo–centro de pantalla;
- diferencia vertical entre ojos y centro de pantalla;
- ángulo de mirada calculado;
- inclinación real del panel;
- separación física entre ambos monitores;
- presencia de reflejos en condiciones diurnas y nocturnas.

El ángulo de mirada se calculará como:

```text
ángulo = atan(diferencia_vertical / distancia_horizontal)
```

## 5. Zonas de visión

Estas zonas describen atención, no un layout definitivo.

### Primaria

Región central reconocible con una mirada. Solo contiene estado crítico, modo del
bot, riesgo inmediato y cambio principal del mercado.

### Secundaria

Contexto que confirma o explica el estado principal: salud de dominios, tendencia,
frescura y excepciones no críticas.

### Periférica

Señales estables de presencia y cambio. No puede contener texto indispensable ni
usar solo color para comunicar severidad.

La atención crítica no puede repartirse entre varias zonas ni depender de recorrer
la pantalla.

## 6. Restricciones UX provisionales

Todos los valores de esta sección son hipótesis hasta completar la Fase -1B.

### Tipografía

- Metadatos no críticos: mínimo inicial de **12 px CSS**.
- Información operacional: mínimo inicial de **14 px CSS**.
- Valores y estados principales: **16–20 px CSS**.
- Números: variantes tabulares cuando se comparen columnas o métricas.
- Texto: debe poder ampliarse al 200% sin pérdida de contenido o funcionalidad.

El tamaño final no se aprobará por captura. Se aprobará leyendo el monitor desde la
postura y distancia reales.

### Espaciado y controles

- Unidad base: 4 px.
- Separación mínima entre grupos distintos: 8 px.
- Objetivo inicial para controles de escritorio: 32 px de alto.
- Ninguna interacción crítica dependerá de un objetivo pequeño o exclusivamente
  gestual.

### Contraste y color

- Texto normal: mínimo **4.5:1**.
- Texto grande y elementos visuales esenciales: mínimo **3:1**.
- Información crítica persistente: objetivo **7:1** cuando la paleta lo permita.
- La severidad se expresa mediante texto, forma, posición o icono además del color.

### Brillo y reflejos

No se fija un valor universal de brillo. Se ajustará al entorno para evitar que la
pantalla parezca una fuente luminosa aislada o pierda contraste por reflejos. Se
validarán por separado condiciones diurnas y nocturnas.

### Densidad

- Una sola alerta puede dominar la vista.
- La pantalla principal debe responder como máximo tres preguntas inmediatas.
- El detalle histórico, la configuración y la explicación extensa quedan fuera de
  la vista persistente.
- El movimiento visual se reserva para cambios relevantes y debe respetar
  `prefers-reduced-motion`.

La densidad no se aprobará contando widgets, sino midiendo reconocimiento, errores
y necesidad de búsqueda visual.

## 7. Fase -1B — Protocolo de validación física

La Fase -1B comienza cuando el monitor secundario esté conectado en su posición de
uso definitiva.

### 7.1 Inventario técnico

Registrar:

- fabricante y modelo;
- tamaño físico;
- resolución nativa;
- resolución y escalado efectivos de macOS;
- frecuencia;
- profundidad de color, si es observable;
- `window.innerWidth`, `window.innerHeight` y `devicePixelRatio`;
- viewport útil después del shell y de las barras del navegador.

La densidad física se calculará como:

```text
PPI = sqrt(ancho_px² + alto_px²) / diagonal_pulgadas
```

### 7.2 Calibración neutral

Antes de diseñar el producto se usará una pantalla de calibración neutral, sin
widgets NexUX, para probar:

- lectura de textos de 12, 14, 16 y 20 px;
- reconocimiento de números tabulares;
- separación visual de 4, 8, 12 y 16 px;
- contraste en estados normal, warning, critical y unknown;
- reflejos, brillo y comodidad durante uso sostenido breve.

La calibración puede invalidar cualquier valor provisional de la sección 6.

### 7.3 Regla de los dos segundos

La calibración comprobará que un estado, un modo y una anomalía puedan reconocerse
en menos de dos segundos sin inclinarse ni recorrer toda la pantalla. No se
evaluará estética ni preferencia.

La shell experimental B1 repetirá la prueba con contenido realista. Esa prueba de
producto es un gate de experiencia, no parte del cierre ergonómico, y no aprueba
por sí sola el diseño.

### 7.4 Criterios de aprobación

No se aprueba ni promueve la shell experimental hasta que:

- el viewport útil real esté registrado;
- la geometría física y el ángulo de mirada estén registrados;
- el usuario lea el tamaño operacional sin cambiar de postura;
- los umbrales de contraste estén verificados;
- brillo y reflejos sean aceptables de día y de noche;
- exista un límite provisional de densidad;
- la prueba neutral de dos segundos no presente errores;
- toda desviación respecto del objetivo quede documentada.

## 8. Registro de validación

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Monitor secundario | ARZOPA, EDID 2025-W17, aproximadamente 14 pulgadas |
| Resolución nativa | 1920 × 1080 |
| Escalado macOS | 1:1; 1920 × 1080 puntos sobre 1920 × 1080 píxeles |
| Viewport CSS útil | 1920 × 992 en Chrome sobre el Arzopa; 1920 × 1080 en harness sin chrome |
| `devicePixelRatio` | 1.00, medido por la shell |
| Frecuencia | 60 Hz |
| Distancia de observación | 80–90 cm |
| Ángulo de mirada | Pendiente |
| Inclinación del panel | Pendiente |
| Tamaño mínimo legible | 12 px visible en metadatos actuales; no aprobado para información crítica |
| Tamaño operacional aprobado | 14–16 px en la shell B1 |
| Contraste | Aprobado en condición nocturna |
| Brillo diurno/nocturno | Noche suficiente con barra Quntis; día pendiente |
| Densidad máxima provisional | B1 actual, TradingView + contexto del sistema |
| Regla neutral de dos segundos | Aprobada para B1; repetir con composición multimódulo |

El inventario se obtuvo mediante `system_profiler` y CoreGraphics. Las mediciones
ergonómicas y perceptuales permanecen pendientes porque requieren observación
física; no se infieren desde EDID ni desde capturas.

## 9. Fuentes normativas

- [OSHA — Computer Workstations: Monitors](https://www.osha.gov/etools/computer-workstations/components/monitors)
- [OSHA — Workstation Environment](https://www.osha.gov/etools/computer-workstations/workstation-environment)
- [W3C WCAG 2.2 — Contrast (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum)
- [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)

Estas fuentes entregan límites generales. La aprobación del producto depende además
de la medición física del escritorio y de la validación directa del usuario.
