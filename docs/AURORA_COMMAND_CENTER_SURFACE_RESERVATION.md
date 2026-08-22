# Aurora Command Center Surface Reservation

## Estado

**RESERVA VISUAL APROBADA. INTEGRACION DIFERIDA. SUPERFICIE INACTIVA.**

Fecha de validacion: 2026-08-10.

Esta decision registra donde y como podra aparecer Aurora en el Command Center
cuando exista una autorizacion de integracion. No activa Aurora, no conecta una
fuente real y no agrega una superficie permanente al producto actual.

## Evidencia fisica

- Monitor: ARZOPA 16 pulgadas QHD.
- Resolucion nativa observada: 3840 x 2400.
- Viewport efectivo validado: 1920 x 1200 @ 60 Hz.
- Evidencia: `docs/evidence/command-center-aurora-reservation-arzopa-16.png`.
- Estado visual validado: `responding`.
- Dimension aproximada del prototipo activo: 611 x 156 px.

## Contrato visual reservado

- Aurora no sera una cuarta tarjeta permanente.
- Mientras Aurora este dormida o inactiva, su superficie permanecera colapsada
  por completo y no reservara espacio visible.
- Durante una interaccion, aparecera como una banda transitoria en el rail
  derecho, entre Atencion inmediata y Musica.
- La composicion principal 67/33, el grafico y Posiciones abiertas se conservan.
- La superficie transitoria tomara espacio principalmente de Musica y del margen
  disponible del rail derecho.
- Una alerta critica de NexUX tiene precedencia visual sobre Aurora.
- La interfaz solo mostrara estados operacionales que Aurora pueda demostrar.
  Los estados candidatos provienen de su maquina de conversacion: listening,
  thinking/hypothesis, responding y waiting.
- No se persistira una transcripcion del usuario en esta superficie sin un Gate
  posterior y una politica explicita de privacidad.

## Limites actuales

- No existe enlace entre el Command Center y el runtime de Aurora.
- No existen endpoints, providers, factories ni suscripciones productivas para
  esta reserva.
- No se expone informacion del Bot, posiciones, balances ni Trading Intelligence
  a Aurora.
- El parametro local `aurora_preview` es exclusivamente un mecanismo de prueba
  visual y permanece ausente de la ejecucion normal.

## Gate de activacion futuro

La superficie solo podra activarse despues de una autorizacion explicita que
defina, como minimo:

1. Fuente contractual y autenticada del estado de conversacion.
2. Semantica de frescura, degradacion y desconexion.
3. Politica de privacidad y retencion.
4. Prioridad frente a Atencion inmediata.
5. Pruebas de ciclo de vida y recuperacion.
6. Nueva validacion perceptual sobre el hardware vigente.

Hasta completar ese Gate, el comportamiento normativo es: **Aurora no aparece**.

