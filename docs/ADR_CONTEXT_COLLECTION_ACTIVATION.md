# ADR — Activacion de Context Collection

Estado: `PENDIENTE / NO AUTORIZADA`

## Decision vigente

La coleccion historica del Command Center permanece desactivada. El release gate
compilado conserva el valor `False`; ninguna variable de entorno puede activarla.

## Evidencia requerida para cambiar esta decision

- storage persistente inicializado fuera del repositorio;
- audit completo en estado `ready`;
- prueba de reinicio y cierre inesperado;
- rotacion y manifest verificados;
- Vault externo cifrado con clave dedicada;
- cobertura de backup completa;
- restauracion en destino vacio;
- comparacion de manifests origen/restauracion;
- ensayo preactivacion aislado, sin eventos canario en el storage primario;
- prueba de cola incompleta;
- prueba de espacio bajo y `ENOSPC`;
- estimacion de crecimiento y espacio disponible;
- destino externo y responsable operacional definidos.

## Acto futuro de activacion

Requiere una nueva revision formal y un commit dedicado que cambie el release
gate. Ese commit no podra incluir cambios de schema, interpretacion ni interfaz.

Hasta entonces:

- historia operacional no iniciada;
- Context Interpreter sin afirmaciones reales;
- merge y despliegue bloqueados.
