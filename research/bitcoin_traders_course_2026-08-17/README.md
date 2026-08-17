# Bitcoin Traders SMC Course Study

Estudio reproducible del curso privado `BOOTCAMP MAYO 2025` de Bitcoin Traders,
disponible en el Google Classroom del usuario.

## Estado

- Classroom accesible y autenticado.
- 11 sesiones inventariadas (22 h 15 min).
- 11 audios autorizados descargados y verificados localmente.
- Transcripcion de Drive no disponible; se usa transcripcion local.
- Primera pasada: `mlx-community/whisper-small-mlx` para el corpus completo.
- Verificacion: fuente audiovisual y modelo mayor para reglas criticas o ambiguas.
- 11 transcripciones locales completas y enlazadas por hash.
- 11 fichas de evidencia con timestamps.
- Glosario, playbook, comparacion y backlog de hipotesis: primera version
  completada.
- Gate visual principal: cerrado 6/6 por revision independiente.
- Items visuales secundarios por ficha: pendientes y no bloqueantes para el
  baseline descriptivo.
- Integracion con NexUX, Bot o produccion: prohibida en esta etapa.

## Objetivo

Reconstruir la estrategia SMC ensenada por el profesor con trazabilidad suficiente
para distinguir:

1. reglas expresadas literalmente;
2. reglas repetidas de forma consistente en ejemplos;
3. interpretaciones del analista;
4. hipotesis que requieren prueba cuantitativa;
5. diferencias frente al playbook BTA/SMC ya documentado en NexUX.

El resultado esperado no es una senal ni una estrategia operativa. Es un playbook
auditable que pueda estudiarse y, posteriormente, convertirse en hipotesis
pre-registradas.

## Fuente

- Curso: `BOOTCAMP MAYO 2025`
- Classroom: `https://classroom.google.com/c/Nzg1MDExNzI3MTM5`
- Profesor/publicador: `Bitcoin Traders`
- Acceso: cuenta privada del usuario

Los videos y audios permanecen fuera del repositorio en:

`/Users/hugh/crisol/.course-cache/bitcoin-traders-bootcamp-2025`

No se redistribuyen materiales del curso.

## Entregables previstos

- `STUDY_PROTOCOL.md`: metodo congelado antes del analisis.
- `COURSE_MANIFEST.json`: inventario, duraciones y hashes de artefactos locales.
- `sessions/SESSION_XX.md`: notas por clase con timestamps.
- `BITCOIN_TRADERS_SMC_GLOSSARY.md`: vocabulario operativo del profesor.
- `BITCOIN_TRADERS_SMC_PLAYBOOK.md`: secuencia de decision completa.
- `BITCOIN_TRADERS_VS_NEXUX.md`: coincidencias, diferencias y huecos.
- `HYPOTHESIS_BACKLOG.md`: preguntas comprobables, sin promocion automatica.
- `FINAL_REVIEW.md`: hallazgos, limites y recomendacion de siguiente gate.

## Resultado actual

El curso queda reconstruido conceptualmente como una secuencia de fractal, rango,
zona, liquidez, confirmacion y gestion. Tras las correcciones documentales y el
gate visual independiente, el baseline descriptivo queda congelado como
`playbook.v1`. Esto no lo convierte en estrategia operativa ni autoriza pruebas.

Estado: `PLAYBOOK.V1 FROZEN / PRIMARY VISUAL GATE CLOSED / NO PROMOTION`.

## Herramientas

- `download_audio.py`: descarga local por rangos desde URLs efimeras autorizadas.
- `transcribe_course.py`: transcripcion local con timestamps mediante MLX Whisper.

Estas herramientas solo leen el material autorizado y escriben en el cache local.
