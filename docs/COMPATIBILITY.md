# NEXUX Command Center - Compatibility Policy

Estado: **FROZEN**

Fecha de freeze: `2026-07-30`

Contrato: `nexux.command-center` Wire ABI v1

Fingerprint:

```text
b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46
```

## Fuente normativa

El JSON Schema
`modules/command_center/schemas/v1.json` es la unica fuente normativa del
Wire ABI v1. El fingerprint es el SHA-256 de su JSON canonico, con claves
ordenadas, separadores compactos y caracteres ASCII escapados.

La implementacion, los ejemplos y este documento explican el contrato, pero
no pueden contradecir el schema.

## Regla de inmutabilidad

El Wire ABI v1 es inmutable desde su freeze. Dentro de v1 nunca se puede:

- eliminar, renombrar o reutilizar un campo publicado;
- cambiar el tipo, significado, unidad o obligatoriedad de un campo;
- cambiar enums, limites, convenciones canonicas o reglas temporales;
- cambiar la semantica de secuencia, snapshot, patch o replay;
- cambiar el binding entre topic, source, subject e identidad;
- cambiar el algoritmo de fingerprint.

Todo cambio de semantica Wire exige un nuevo contrato mayor. No se modifica
v1 para acomodar una implementacion nueva.

Los campos Wire desconocidos deben ignorarse de forma segura y se consideran
no normativos. Su presencia no concede capacidades ni modifica el significado
de campos conocidos.

## Evolucion permitida en v1

El dominio puede evolucionar de forma aditiva dentro de:

- `payload.data`;
- payloads de eventos;
- `error.details`.

Un evento de dominio conserva su `event_type`. Todo cambio incompatible de su
payload exige incrementar `event_version` y mantener la version anterior
durante la migracion de consumidores.

Un campo se depreca antes de dejar de emitirse. Su eliminacion del Wire ABI
solo puede ocurrir en una nueva version contractual.

## Obligaciones del consumidor

- Validar `v` y `contract_fingerprint` antes de reconstruir una sesion.
- Fallar cerrado o solicitar un snapshot compatible ante una version o
  fingerprint desconocidos.
- Solicitar un nuevo snapshot cuando exista un hueco de secuencia.
- Ignorar de forma segura eventos de dominio desconocidos sin mutar estado.
- Interpretar errores y degradaciones mediante sus codigos estables.
- Aplicar primero el snapshot y despues unicamente eventos posteriores.

## Obligaciones del productor

- Emitir el fingerprint congelado junto al snapshot v1.
- Validar todo documento contra el contrato antes de publicarlo.
- No presentar campos experimentales como parte normativa de v1.
- Autorizar providers antes de ejecutarlos y entregarles contexto minimo.
- Mantener identidad, permisos y alcance bajo control exclusivo del servidor.

## Procedimiento de cambio

1. Clasificar el cambio como dominio aditivo o Wire ABI.
2. Para dominio aditivo, versionar el evento cuando corresponda y probar
   consumidores anteriores.
3. Para Wire ABI, crear un schema de nueva version sin modificar v1.
4. Ejecutar una Contract Freeze Review independiente.
5. Publicar un fingerprint nuevo y conservar los artefactos congelados.
6. Documentar ventana de compatibilidad, migracion y retiro.

El EventBus, WebSocket y futuros adaptadores deben depender de este contrato.
El contrato no se adapta a esos componentes.
