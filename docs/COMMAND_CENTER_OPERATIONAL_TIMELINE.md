# Command Center Operational Timeline

Estado: Sprint D implementado en rama, sin merge ni despliegue.

## Pregunta operacional

La timeline responde:

> ¿Qué cambió realmente durante esta sesión?

No intenta explicar por qué ocurrió ni completar eventos que NexUX no observó.

## Fuentes permitidas

La primera versión consume exclusivamente estados que la interfaz ya recibe:

- Pulso de mercado derivado del Market Ribbon vigente.
- Estado operacional global calculado por NexUX.
- Cantidad consolidada de posiciones observadas.
- Última señal del Bot cuando incluye un timestamp causal posterior al inicio de
  la sesión.

No se agregaron endpoints, providers, almacenamiento ni llamadas externas.

## Semántica

La lectura inicial establece un baseline y no genera un evento. Solo una
transición posterior produce una entrada.

Ejemplos permitidos:

- `Pulso: Mixto → Bajista`.
- `Sistema: Estable → Degradado`.
- `Posiciones observadas: 1 → 2`.
- `SOL · LONG`, con estado y timestamp publicados por el Bot.

La expresión `Posiciones observadas` es intencional: una variación entre dos
lecturas no demuestra por sí sola la hora exacta de apertura o cierre.

## Abstenciones

La timeline no publica:

- rupturas de soporte o resistencia;
- causas de movimientos;
- continuidad o tendencia;
- aperturas o cierres inferidos desde un cambio de conteo;
- señales anteriores al inicio de la sesión;
- timestamps futuros;
- eventos reconstruidos retrospectivamente.

## Orden y ruido

- Orden descendente por timestamp de ocurrencia.
- Deduplicación de señales externas mediante identidad estable.
- Transiciones repetidas no generan entradas.
- Memoria acotada a 24 eventos.
- La UI muestra como máximo dos eventos en calma y uno cuando existen alertas.

## Superficie

La timeline reutiliza `Atención inmediata`. No incorpora tarjetas ni paneles.
Las alertas activas conservan prioridad visual; la actividad reciente aparece
como contexto secundario.

La historia es efímera y dura únicamente la sesión actual. No se usa
`localStorage`, Context Recorder, Context Storage ni Context Vault.

## Validación

- Baseline silencioso.
- Transiciones causales.
- Deduplicación.
- Rechazo de señales antiguas y futuras.
- Orden temporal.
- Límite de retención.
- Regresión visual y contractual del Command Center.
- Suite Command Center: 327 pruebas aprobadas.
- Sin overflow en viewport 1280 × 720; panel de atención conservado en 190 px.

## Frontera futura

Sprint H Replay permanece bloqueado. Una timeline de sesión no puede reconstruir
historia tras un reinicio. Replay requerirá eventos persistidos realmente y
brechas explícitas; no se autoriza reconstruirlos desde snapshots actuales.

## Integridad arquitectónica

- layout 67/33 intacto;
- shell nativa intacta;
- TradingView intacto;
- Wire ABI, EventBus y Gateway intactos;
- cero cambios en Bot, Trading Intelligence, Aurora, Railway, VPS o producción;
- Context Recorder, Collection, Interpreter operativo y automatizaciones
  permanecen inactivos.
