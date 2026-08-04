# Command Center Context Recorder

Estado: Sprint B aprobado; implementado en rama, sin merge, activacion ni
despliegue.

## Objetivo

Crear historia causal propia para futuras explicaciones temporales del Command
Center. Este sprint registra observaciones; no compara, interpreta ni recomienda.

## Fuente y cadencia

- fuente: snapshot vigente de `MarketRibbonService`;
- captura headless cada 30 segundos mientras el modulo esta iniciado;
- independencia de la pagina y de una sesion de navegador abierta;
- persistencia por defecto en
  `data/command_center/context_market_v1.jsonl`;
- ruta configurable mediante `NEXUX_CONTEXT_RECORDER_PATH`.

El colector empieza con la primera observacion recibida. No importa archivos
anteriores, no consulta velas historicas y no rellena periodos sin cobertura.

## Contrato persistido

Cada linea JSON usa el schema `nexux.context.market.v1` y conserva:

- secuencia monotona;
- hora de captura y hora publicada por la fuente;
- activos, precio, variacion, frescura, fuente y timestamp observado;
- errores de proveedor y contadores de calidad;
- provenance forward;
- fingerprint canonico del snapshot;
- hash del evento y hash del evento anterior.

La cadena SHA-256 permite detectar alteraciones, truncamientos logicos y regresion
de secuencia al reiniciar.

## Garantias

- append-only con `fsync` antes de confirmar la escritura;
- bloqueo de archivo para serializar escritores concurrentes;
- permisos `0600` al crear el archivo;
- duplicados exactos no generan un evento adicional;
- snapshots con mas de dos minutos de atraso son rechazados;
- timestamps futuros fuera de la tolerancia de reloj son rechazados;
- valores no numericos, infinitos o `NaN` son rechazados;
- un log corrupto bloquea nuevas escrituras, pero no derriba el Command Center;
- fallos del observador no impiden entregar el Market Ribbon.

## Observabilidad

El health del modulo expone solamente metadatos operacionales:

- estado;
- schema;
- secuencia;
- ultima captura;
- escrituras, duplicados y rechazos;
- ultimo tipo de error;
- estado del colector y frecuencia.

No expone el historial ni agrega una API de consulta en este sprint.

## Limite semantico

Todavia no estan autorizadas afirmaciones sobre continuidad, cambios o comparacion
con periodos anteriores. El siguiente paso solo podra definir ventanas y reglas de
comparacion cuando exista cobertura forward suficiente y medible.

Una brecha permanece como brecha. La falta de registros nunca se interpreta como
estabilidad del mercado.

## Condicion antes de cualquier despliegue

La ruta debe apuntar a almacenamiento persistente y su retencion debe quedar
definida. Desplegar sobre un filesystem efimero destruiria precisamente la
evidencia que este componente busca construir.

La activacion exige tres confirmaciones independientes: solicitud explicita,
persistencia confirmada y respaldo confirmado. Sin las tres, el observador no se
conecta al Market Ribbon y el hilo headless no arranca.

## Integridad arquitectonica

- Wire ABI, EventBus, Gateway y registro intactos;
- sin cambios visuales ni nuevas superficies;
- sin IA, LLM, modelos o decisiones;
- sin acceso al Bot, Trading Intelligence, credenciales u ordenes;
- sin cambios en Railway, VPS o produccion.
