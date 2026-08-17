# Sesion 11 - Gestion de Riesgo y Plan de Trading Profesional

**Fuente:** `Gestion de Riesgo y Plan de Trading Profesional`<br>
**Duracion:** 02:58:43<br>
**Audio SHA-256:** `9f62517c084a378a388873808ec8af42c9c21ee4fc43ddef83a73848d10dfaa5`<br>
**Transcripcion:** primera pasada local; formula de futuros confirmada visualmente
en S11 01:48:01; ejemplos visuales secundarios pendientes.

## Proposito declarado

La clase presenta el plan y la gestion como condiciones previas a la estrategia.
El profesor insiste en definir por adelantado activo, temporalidades, riesgo,
limites y proceso de revision, y luego dedica un bloque separado a futuros.

## Plan operativo

- **E0, 00:27:49-00:31:07:** comenzar con un solo activo y especializarse antes
  de ampliar el universo.
- **E0, 00:31:14-00:32:35:** para cripto utiliza diario, H4, H1 y M15; a veces
  M5/M3 para refinar. El recorrido descrito es diario -> direccion H4 ->
  confirmacion M15 -> refinamiento inferior.
- **E0, 00:46:35-00:49:32:** no operar si el estado mental impide analizar con
  claridad; resolver primero el conflicto externo.
- **E0, 00:49:41-00:51:16:** revisar el mapa dos o tres veces antes de ejecutar,
  porque una lectura apresurada puede omitir detalles estructurales.
- **E1:** el activo, horizonte y temporalidades deben quedar fijados antes de
  interpretar el setup; no deben elegirse despues para justificar una entrada.

## Riesgo por operacion

- **E0, 00:36:06-00:36:53:** clasifica `0,5%-1%` como riesgo bajo, `3%-5%` como
  medio y `>=5%` como alto.
- **E0, 00:38:13-00:39:21:** su politica personal usa `0,5%` contra tendencia y
  `1%` a favor. El mismo profesor aclara que es una decision propia.
- **E0, 00:42:05-00:43:43:** fija para si mismo un maximo de dos stops diarios
  para cortar revancha y sobreoperacion.
- **E0, 00:43:44-00:44:06:** muestra `1%` como perdida diaria y admite un rango
  variable de `1%-2%`, con advertencia de no superar `5%`.
- **U0:** esas cifras aparecen como plantilla personal y ejemplos didacticos; el
  curso no ofrece una optimizacion estadistica que las convierta en umbrales
  universales.
- **E0, 00:44:58-00:45:55:** usa una meta semanal personal de `3%-5%` y deja de
  operar si la alcanza antes del viernes.
- **I1:** una meta de beneficio no debe convertirse en obligacion de producir
  operaciones. En NexUX solo podria estudiarse como regla de exposicion, no como
  evidencia de edge.

## Condiciones previas a la entrada

- **E0, 00:25:05-00:25:31:** aceptar de antemano la perdida completa asignada a
  la operacion.
- **E0, 00:46:35-00:53:00:** comprobar claridad mental, mapa, criterio de entrada,
  stop y disposicion a aceptar el resultado.
- **E1:** si el riesgo a primer toque no cabe en el plan, esperar confirmacion o
  abstenerse; la confirmacion no autoriza a aumentar el riesgo total.
- **E2, 02:28:11-02:29:52:** en un short contra tendencia el profesor conserva
  `0,5%` total y plantea dividirlo `0,25% + 0,25%` entre dos zonas. No duplica la
  exposicion.

## Bitacora y consistencia

- **E0, 00:57:00-01:00:30:** registrar operaciones para revisiones semanales,
  mensuales y anuales; modificar el plan solo despues de encontrar patrones en
  el historial.
- **E0, 02:00:00-02:09:30:** usa una matriz win rate/RR para explicar que un
  sistema puede ser rentable con menor acierto si el payoff compensa las
  perdidas.
- **U0:** la matriz es aritmetica bruta. No incorpora comisiones, spread,
  slippage, break-even, distribucion variable de R ni intervalos de confianza.
- **E0, 02:12:02-02:13:20:** el profesor relata un acierto personal de
  aproximadamente `75%-82%` en BTC usando diario/H4/M15.
- **U0:** no se muestra dataset enlazable, periodo, costos ni protocolo; el dato
  es una afirmacion docente y no evidencia de eficacia.

## Reserva critica sobre futuros

- **E0, 01:40:22-01:43:12:** recomienda riesgo bajo y argumenta que `1%` conserva
  cien oportunidades teoricas.
- **E0, 01:45:17-01:51:20:** propone calcular apalancamiento con
  `stop_pct * leverage = 80%` para que el movimiento al stop consuma cerca del
  80% del margen asignado.
- **E0, 01:46:25-01:48:01:** declara que lo ideal seria utilizar cerca del `70%`
  y que adopta `80%` por efectos practicos.
- **E2 visual, 01:48:01:** la lamina muestra el ejemplo completo:
  `SL 0,76% -> 80 / 0,76 ~= 105x -> 79,8% del margen + comision`.
- **U0, 01:46:25-01:48:01:** la lamina justifica el buffer como forma de `evitar
  ser liquidado antes de tiempo`, mientras la explicacion oral atribuye el 20%
  restante a comisiones del exchange. Esa atribucion es financieramente
  incorrecta y constituye una inconsistencia interna del material.
- **E0, 01:49:40-01:50:19:** llega a aceptar que una posicion pueda liquidarse
  si ese margen estaba contemplado.
- **E0, 01:52:03-01:55:01:** calcula el margen de entrada suponiendo que el 80%
  equivale al riesgo monetario elegido.
- **U0 / NO OPERACIONALIZAR:** esta formulacion mezcla sizing de cuenta, margen,
  apalancamiento, stop y liquidacion. No modela de forma auditable mantenimiento,
  mark price, fees, slippage ni reglas del exchange. La contradiccion entre la
  lamina y la explicacion oral refuerza la exclusion. Se conserva como contenido
  literal del curso, pero queda excluida permanentemente del playbook NexUX.

## Preferencias operativas y afirmaciones no demostradas

- **E0, 02:15:32-02:18:47:** recomienda a principiantes operar a favor de la
  estructura y describe el paso del primer al segundo rango como de alta
  probabilidad.
- **H1:** la aparente ventaja del primer rango requiere definicion causal y
  prueba; no hay frecuencia publicada.
- **E0, 02:20:00-02:25:00:** las sesiones horarias se presentan como menos
  determinantes en BTC que en forex, oro e indices.
- **U0:** no se aporta comparacion cuantitativa por sesion.

## Contradicciones y limites

- La clase privilegia riesgo bajo, pero tambien enseña una formula de futuros
  orientada a consumir gran parte del margen de cada posicion.
- El limite diario aparece como `1%`, luego `1%-2%`, y finalmente con un techo de
  `5%`; debe leerse como plantilla personal, no como una unica regla cerrada.
- El alto win rate relatado no puede verificarse desde el material disponible.
- La relacion entre porcentaje de recorrido en cripto y resultado en R queda sin
  contrato uniforme.

## Verificacion visual

- 00:31:14-00:35:00: plantilla de activo y temporalidades.
- 00:36:06-00:45:55: tabla de riesgo, stops diarios y meta semanal.
- **Confirmado, 01:48:01:** formula, ideal 70%, limite practico 80% y ejemplo
  `0,76% -> 105x -> 79,8% + comision`.
- 02:00:00-02:13:20: matriz de consistencia y afirmacion de acierto BTC.
- 02:28:11-02:31:00: division de riesgo entre dos zonas.

## Estado

`TRANSCRIBED / FUTURES FORMULA VISUALLY CONFIRMED AND EXCLUDED / SECONDARY VISUAL REVIEW PENDING`
