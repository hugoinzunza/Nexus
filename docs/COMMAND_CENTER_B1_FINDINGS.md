# Command Center — Sprint B1 Findings

- **Estado:** aprobado técnica y perceptualmente
- **Fecha:** 2026-07-30
- **Rama:** `codex/command-center-contract-v1`

## Resultado

La shell experimental funciona sobre el Arzopa real usando el snapshot y Gateway
existentes. El viewport útil observado en Chrome fue `1920 × 992`, DPR `1.00`.
La composición no presenta scroll horizontal, solapamientos ni texto truncado.

TradingView ocupa aproximadamente siete doceavos del ancho de contenido. Conserva
un área útil de más de 1000 px de ancho en el viewport completo sin desplazar el
estado operacional. El montaje observado estuvo entre 609 y 2621 ms en cargas
reales; la variación deberá medirse durante una sesión prolongada antes de fijar
un SLO visual.

## Hallazgo bloqueante resuelto

Las proyecciones `system.session` y `system.modules` caducan, pero hoy no existe un
publisher periódico que avance esos topics. El Gateway seguía conectado mientras
su checkpoint envejecía, por lo que una shell abierta terminaba correctamente en
`expired` y no podía recuperar frescura mediante resync.

Se resolvió en la frontera cliente sin modificar Línea A:

1. La renovación programada usa el endpoint HTTP antes de `stale_at`.
2. La reconciliación conserva la mayor secuencia.
3. A igual secuencia conserva el envelope con `observed_at` más reciente.
4. Un gap real sigue solicitando resync al Gateway.

La verificación sostenida mostró un snapshot nuevo después de 32 segundos y la
shell permaneció en `ready`.

## Evidencia visual

- `docs/evidence/command-center-b1-arzopa-physical.png`: Chrome ejecutándose en
  el monitor ARZOPA real con datos locales reales y TradingView.
- `docs/evidence/command-center-b1-ready-1920x1080.png`: harness exacto
  `1920 × 1080`, estado ready y gráfico montado.
- `docs/evidence/command-center-b1-expired-1920x1080.png`: fixture contractual
  expired sin red externa.

Los fixtures siempre muestran la marca `Fixture contractual`; no pueden
confundirse con datos reales.

## Observaciones

- macOS ubica lógicamente el Arzopa a la izquierda, aunque físicamente está bajo
  el monitor principal. Debe corregirse antes de evaluar trayectorias del cursor.
- Las barras de Chrome reducen el alto útil de 1080 a 992 px. El modo pantalla
  completa puede recuperar espacio, pero todavía no se adopta como requisito.
- Ocho módulos caben sin scroll en dos columnas. Eso no demuestra que ocho sean
  cognitivamente apropiados.
- Los estados warning y expired son visualmente inequívocos en captura; su
  reconocimiento físico aún debe medirse.

## Validación perceptual

Hugo evaluó la shell a 80–90 cm, de noche y únicamente con iluminación de barra
Quntis:

- legibilidad cómoda;
- brillo suficiente para operar, aunque mejorable por diseño;
- jerarquía clara;
- densidad adecuada;
- regla de los dos segundos cumplida.

La validación estuvo limitada a TradingView y contexto de sistema. Debe repetirse
cuando B2 incorpore varias fuentes simultáneas.

## Validaciones posteriores

- ángulo e inclinación;
- brillo y reflejos diurnos;
- regla de los dos segundos con composición multimódulo.

## Recomendación B2

Incorporar una sola proyección read-only por vez y repetir la prueba de dos
segundos antes de aumentar densidad. El widget público de TradingView no puede
mostrar LuxAlgo privado; B2 debe conservarlo como contexto general o abrir el
layout autenticado como superficie externa.
