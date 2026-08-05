# Command Center Context Interpreter

Estado: Sprint C implementado en rama, sin merge, activacion ni despliegue.

## Objetivo

Convertir historia causal registrada por NexUX en descripciones temporales
reconstruibles. El componente no pronostica, recomienda, califica tendencia ni
completa informacion ausente.

## Primera capacidad congelada

El interprete puede responder una sola pregunta:

> ¿Como cambio el precio de este activo entre dos observaciones registradas con
> una hora de separacion?

La salida puede describir que el precio subio, bajo o no vario. Esa direccion es
el resultado aritmetico de dos precios almacenados, no una inferencia de tendencia.

No estan autorizadas expresiones de continuidad, persistencia, causalidad,
probabilidad futura o conveniencia de operar.

## Evidencia exigida

Antes de emitir una descripcion, el interprete exige:

- cadena completa del archivo valida;
- fingerprint de cada snapshot valido;
- secuencia y reloj de captura sin regresiones;
- observacion actual con antiguedad maxima de dos minutos;
- baseline a una hora con tolerancia maxima de un minuto;
- muestras del mismo activo con brechas maximas de 90 segundos;
- una unica fuente durante toda la ventana;
- precios positivos y finitos;
- timestamps observados validos y monotonos;
- frescura `live` o `current`.

Si alguna condicion falla, devuelve `insufficient_evidence`, una razon estable y
ninguna frase.

## Razones de abstencion

- `no_history`;
- `asset_unobserved`;
- `insufficient_history`;
- `coverage_gap`;
- `source_changed`;
- `stale_history`;
- `future_capture` o `future_observation`;
- `capture_time_regressed` u `observation_time_regressed`;
- `integrity_failure`;
- `history_unavailable`;
- `unsupported_horizon`.

Una abstencion es el resultado correcto cuando la evidencia no alcanza.

## Trazabilidad de una descripcion

Cada resultado aceptado incluye:

- secuencia y hash del evento baseline;
- secuencia y hash del evento actual;
- precios y timestamps de ambos extremos;
- fuente;
- cantidad de muestras;
- duracion realmente observada;
- mayor brecha de la ventana;
- delta absoluto y porcentual.

La base se declara siempre como `stored_snapshots_only`.

## Activacion de la coleccion

La coleccion permanece bloqueada. Para que el modulo pueda escribir deben estar
presentes simultaneamente:

- `NEXUX_CONTEXT_RECORDER_ENABLED=1`;
- `NEXUX_CONTEXT_RECORDER_PERSISTENCE_CONFIRMED=1`;
- `NEXUX_CONTEXT_RECORDER_BACKUP_CONFIRMED=1`.

Ademas, `NEXUX_CONTEXT_STORAGE_ROOT` debera apuntar al almacenamiento persistente
aprobado y `NEXUX_CONTEXT_BACKUP_ROOT` al Vault externo. Existe un release gate
compilado en `False`, por lo que estas variables no pueden activar la coleccion por
si solas.

El backup exige ademas `NEXUX_CONTEXT_VAULT_PUBLIC_FILE` con una clave publica
dedicada a este historial.

## Superficie

Sprint C no agrega endpoint, texto visual ni consumo automatico del interprete.
El componente existe como capacidad headless y expone solo contadores de salud.
Esto permite validar la semantica antes de convertirla en experiencia de producto.

## Limites actuales

- solo una ventana de una hora;
- solo comparacion de precio;
- sin combinacion entre activos;
- sin estado general de mercado;
- sin comparacion mientras la coleccion siga bloqueada;
- sin IA, LLM, modelos o acceso al Bot.

## Integridad arquitectonica

- Wire ABI, EventBus, Gateway y registro intactos;
- estructura visual, TradingView y shell intactos;
- sin cambios en Bot, Trading Intelligence o Aurora;
- sin Railway, VPS, produccion, merge o activacion.
