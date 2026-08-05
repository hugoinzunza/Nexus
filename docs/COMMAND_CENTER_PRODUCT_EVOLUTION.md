# Command Center Product Evolution

Estado: Sprints D, E, F e I implementados en rama, sin merge ni despliegue.

## Sprint D — Operational Timeline

Implementado como historia causal y efímera de la sesión. Registra únicamente
transiciones observadas del Pulso, estado operacional, conteo de posiciones y
señales nuevas del Bot con timestamp válido.

La primera lectura es baseline, no evento. No hay reconstrucción retrospectiva,
persistencia nueva ni narrativa. La especificación detallada vive en
`COMMAND_CENTER_OPERATIONAL_TIMELINE.md`.

## Sprint E — Explainability Layer

Las superficies existentes exponen evidencia determinista:

- Pulso: amplitud y mediana que produjeron la lectura.
- Atención inmediata: fuentes y alertas activas que originaron el estado.
- Salud operacional: servicio, estado y evidencia concreta.
- Estado degradado: causa publicada por la lectura correspondiente.

Las explicaciones se incorporan mediante texto accesible y tooltips sobre los
elementos actuales. No se agregaron botones, tarjetas ni paneles.

## Sprint F — Operational Health Engine

Estados públicos:

- `Estable`
- `Degradado`
- `Crítico`
- `Desconocido`

No existe score. La precedencia es explícita:

1. Cualquier servicio esencial fallido produce `Crítico`.
2. Sin fallos, cualquier servicio degradado produce `Degradado`.
3. Sin fallos ni degradaciones, una lectura desconocida o ausente produce
   `Desconocido`.
4. Solo los cinco servicios esenciales verificados producen `Estable`.

Los servicios esenciales permanecen congelados como Gateway, EventBus,
Snapshot, Internet y Trading. Los módulos opcionales no degradan la salud global.

## Sprint G — Context Evolution

**BLOQUEADO POR EVIDENCIA.**

Las ventanas de 6 horas, 24 horas y 7 días requieren snapshots realmente
almacenados durante esas ventanas. Context Collection continúa inactiva, por lo
que hoy no existe historia admisible. No se reconstruyó ni rellenó ningún dato.

## Sprint H — Replay

**BLOQUEADO POR EVIDENCIA.**

La timeline actual dura una sesión y no es una fuente persistente apta para
Replay. Implementarlo ahora obligaría a interpolar o reconstruir eventos. Replay
solo podrá comenzar cuando exista una historia real con brechas explícitas.

## Sprint I — Dashboard Adaptativo

La superficie existente de Atención adopta tres modos:

- `calm`: sin alertas; muestra como máximo dos eventos recientes.
- `elevated`: advertencia; muestra una entrada temporal secundaria.
- `focused`: estado crítico; oculta actividad secundaria y concentra la atención
  exclusivamente en la alerta.

Los eventos de timeline dejan de ocupar la superficie tras 15 minutos. Esto evita
que actividad antigua mantenga color o densidad innecesarios.

No existen animaciones decorativas. Las transiciones de color duran 160 ms y se
limitan a cambios de estado.

## Validación

- 333 pruebas del Command Center aprobadas.
- Suite global: 961 aprobadas y 4 incidencias de research preexistentes:
  - supuesto histórico del Diario V1 ya no se cumple en la muestra local;
  - tres pruebas requieren `research/vacio_disponible_trades.json`, ausente.
- Health Engine sin score y con precedencia cubierta.
- Evidencia visible cubierta por pruebas estáticas.
- Timeline causal, deduplicada, ordenada y acotada.
- Modo adaptativo cubierto para calma, advertencia, crítico y desconocido.
- Validación visual en 1280 × 720, más restrictiva que el Arzopa:
  - cero overflow horizontal;
  - cero overflow vertical;
  - panel de Atención conservado en 190 px;
  - modo `elevated` visible ante evento macro a 42 minutos;
  - salud global `Estable` con explicación verificable.

## Arquitectura preservada

- layout 67/33 intacto;
- shell nativa intacta;
- TradingView intacto;
- Wire ABI, EventBus, Gateway y Runtime intactos;
- cero nuevas tarjetas o paneles;
- cero cambios en Recorder, Vault, Recovery o Storage;
- cero cambios en Bot, Trading Intelligence o Aurora;
- producción, Railway y VPS intactos.
