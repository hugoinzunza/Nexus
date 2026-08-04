# NexUX Experience Audit

**Fecha:** 2026-08-04  
**Estado:** Auditoria completada; implementacion bloqueada hasta revision formal  
**Superficie evaluada:** Command Center en ARZOPA 14", 1920 x 1080, DPR 1  
**Alcance:** Experience Layer exclusivamente

## 1. Veredicto ejecutivo

El Command Center ya posee una composicion estable y una identidad reconocible, pero
todavia se comporta visualmente como un dashboard muy bien construido. El problema no
es falta de informacion ni falta de color. Es que demasiadas superficies permanecen
activas al mismo tiempo y varias responden la misma pregunta.

La base no debe redisenarse desde cero. Debe evolucionar desde **modulos siempre
visibles** hacia **estados de calma, contexto y excepcion**.

La mejora de mayor valor es esta:

> En estado normal, NexUX debe callar. Cuando algo cambia, debe explicar una sola vez
> que ocurrio, que significa y si requiere accion.

## 2. Evidencia revisada

- Implementacion actual en `modules/command_center/public/`.
- Viewport real de 1920 x 1080 sin overflow ni scroll.
- Estado `ready` con datos reales y TradingView montado.
- Estado degradado con proveedor y fuentes incompletas.
- Evidencia aprobada `docs/evidence/command-center-val-0029-arzopa.png`.
- `VALIDATION_LOG.md`, `DESIGN_REVIEW_NEXT_PHASE.md`,
  `DESIGN_SYSTEM_FOUNDATIONS.md` y `VIEWPORT_SPECIFICATION.md`.
- Mediciones DOM de dimensiones, tipografia y superficies.
- Contraste WCAG calculado sobre los tokens actuales.

La lectura a 80-90 cm ya fue validada perceptualmente. La lectura a dos metros no ha
sido validada fisicamente; en esta auditoria solo se evalua su viabilidad tipografica y
periferica.

## 3. Lo que funciona

### Composicion principal

- El reparto aproximado 67/33 mantiene al grafico como superficie dominante.
- El viewport se utiliza completo y la shell nativa elimina la apariencia de navegador.
- TradingView puede ser reemplazado en el futuro sin cambiar el espacio principal.
- El rail derecho contiene las tres preguntas secundarias correctas: atencion,
  reproduccion y posiciones.

### Identidad

- La base oscura funciona bien para uso prolongado.
- Cian, verde, ambar, rojo y magenta ya forman un vocabulario reconocible.
- El logo, la marca y la densidad general se sienten propios de NexUX.
- Radios, bordes y controles son contenidos y coherentes con una aplicacion de escritorio.

### Comprension operacional

- `Atencion inmediata` ya consolida Sistema, Binance, Macro y Bot.
- Los estados no dependen exclusivamente del color.
- Posiciones separa correctamente la cuenta principal de la cuenta Bot.
- Musica tiene controles claros, caratula estable y metadatos suficientes.

## 4. Problemas encontrados

### P0 - La disponibilidad se repite y compite consigo misma

En estado normal aparecen simultaneamente:

- `Conectado` en la barra superior;
- `Sin alertas` en Atencion inmediata;
- `Sistema listo` dentro de Atencion;
- cinco estados `Ready` en el footer;
- un estado global `READY` en el footer;
- el punto verde del proveedor.

Todas comunican casi lo mismo. La repeticion no aumenta confianza: aumenta ruido y
reduce la capacidad de una alerta real para destacar.

**Recomendacion:** conservar una unica confirmacion global en estado normal. Los
detalles de infraestructura deben aparecer solo cuando existe degradacion o mediante
una inspeccion voluntaria.

### P0 - El estado normal de Atencion inmediata no esta realmente en calma

Aunque dice `Sin intervencion inmediata`, conserva cuatro filas de estado, el conteo de
posiciones, el modo del Bot, el contexto macro y la hora de evaluacion. Binance y Macro
se repiten en otras superficies.

**Recomendacion:** en estado normal mostrar solo una frase breve y discreta. Las cuatro
fuentes deben expandirse automaticamente ante una excepcion o mediante accion del
usuario.

### P0 - La degradacion conserva la geometria, pero pierde el significado

Cuando TradingView o las fuentes no estan disponibles, el grafico se transforma en una
gran superficie negra, Market Ribbon queda casi vacio y el rail mantiene paneles con
`Esperando` o `Unknown`. El usuario ve que algo falta, pero no obtiene una narrativa
unica de recuperacion.

**Recomendacion:** el estado degradado debe sustituir el contenido inutil por un unico
mensaje operacional: que fuente fallo, que informacion sigue siendo confiable y si se
puede continuar trabajando.

### P1 - La jerarquia tipografica es demasiado plana

El titulo del grafico y los tres titulos del rail usan 16 px. Atencion, Posiciones y
Mercado reciben casi el mismo tratamiento nominal pese a tener prioridades diferentes.
Los items de Atencion usan 10-11 px y macOS usa 8-11 px.

La pantalla mide aproximadamente 310 mm de ancho para 1920 px. A dos metros, 10-16 px
no son una lectura operacional comoda. Desde esa distancia solo pueden reconocerse
formas, color y titulares grandes.

**Recomendacion:** definir dos distancias:

- **80-90 cm:** lectura completa de detalle.
- **2 m:** solo estado global, alerta principal y direccion general del mercado.

No debe intentarse hacer legible todo a dos metros. Debe hacerse legible lo esencial.

### P1 - Market Ribbon entrega datos, pero no contexto

Ocho activos tienen exactamente el mismo peso visual. El usuario debe leer precio y
porcentaje, comparar signos y construir mentalmente una conclusion.

**Recomendacion:** mantener los datos disponibles, pero permitir que una lectura
determinista los resuma. El resumen debe sustituir texto existente, no crear otro panel.

Una regla no debe afirmar `impulso alcista` usando solo variacion diaria. Cuando la
evidencia sea limitada, el lenguaje debe ser factual: `BTC sube hoy` o `VIX cae con
fuerza`. Toda regla debe abstenerse si la fuente esta stale.

### P1 - El PnL domina mas que el riesgo operacional

Las cifras rojas de Posiciones son uno de los elementos mas intensos del rail. Pueden
capturar la mirada incluso cuando no existe una condicion accionable. Esto contradice
la decision previa de no convertir PnL o ROE en mecanismo de atencion.

**Recomendacion:** conservar PnL disponible, pero bajar su intensidad en estado normal.
Solo una condicion de riesgo predefinida deberia elevarlo a Atencion inmediata.

### P1 - Las tres superficies del rail no comparten el mismo eje interno

Atencion usa 16 px de padding, Musica 18 px y Posiciones 12 px. Sus encabezados comienzan
en coordenadas distintas. En una captura completa la diferencia es pequena, pero evita
que el rail se sienta como una sola columna del sistema.

**Recomendacion:** adoptar un inset comun y una linea base unica para titulos, badges y
contenido.

### P1 - El color asigna protagonismo permanente

Musica conserva borde magenta, fondo tintado y glow aunque no requiera atencion.
Atencion conserva una superficie coloreada incluso en estado normal. Al mismo tiempo,
el activo seleccionado usa cian y el footer mantiene varios verdes.

El resultado es elegante, pero existen demasiados focos permanentes.

**Recomendacion:** reservar glow y saturacion alta para cambio, seleccion o alerta.
Una superficie estable debe volver gradualmente a un estado mas silencioso.

### P1 - El idioma operacional no esta unificado

La interfaz mezcla `Listo`, `Conectado`, `Ready`, `Degraded`, `Unknown`, `Live` y
`Dry-run`. La mezcla hace visible la arquitectura interna.

**Recomendacion:** usar espanol en la experiencia y conservar los terminos tecnicos solo
en diagnostico: `Listo`, `Degradado`, `Sin datos`, `En vivo`, `Simulacion`.

### P2 - El contraste es correcto, salvo metadatos pequenos

`--text-1` y `--text-2` superan ampliamente AA. `--text-3` obtiene 4.69:1 sobre
`--surface-1`, pero cae a 4.36:1 sobre `--surface-2`. Se utiliza ademas en textos de
8-12 px.

**Recomendacion:** aclarar ligeramente `--text-3` o limitarlo a texto verdaderamente
prescindible de al menos 12 px. No debe contener estado operacional.

### P2 - El sistema casi no comunica actualizaciones

La unica transicion relevante es el progreso de reproduccion. Refrescos, cambios de
frescura y aparicion de alertas se sienten instantaneos o invisibles.

**Recomendacion:** Motion debe indicar causalidad, no decorar: dato actualizado, alerta
nueva, fuente recuperada y cambio de estado.

## 5. Jerarquia de informacion recomendada

### Nivel 0 - Interrupcion

Solo aparece cuando existe una condicion accionable.

- alerta critica;
- fuente esencial fallida;
- posicion no confirmada;
- evento macro dentro de la ventana definida;
- estado critico del Bot.

Debe responder: **Que paso, que significa y debo actuar ahora?**

### Nivel 1 - Conciencia principal

- grafico seleccionado;
- estado global de NexUX;
- una frase de contexto de mercado.

Debe poder reconocerse perifericamente y desde dos metros.

### Nivel 2 - Contexto operativo

- posiciones abiertas;
- siguiente evento relevante;
- estado real del Bot cuando corresponda.

Se lee desde la posicion habitual, no a distancia.

### Nivel 3 - Contexto personal

- reproduccion musical;
- seleccion de proveedor;
- controles.

Debe sentirse premium sin simular urgencia.

### Nivel 4 - Diagnostico

- Gateway;
- EventBus;
- Snapshot;
- latencia;
- macOS;
- timestamps tecnicos.

Debe permanecer oculto mientras todo funciona.

## 6. Quick wins recomendados

Estos cambios son pequenos, pero requieren aprobacion antes de implementarse.

1. Unificar todo el idioma operacional en espanol.
2. Unificar el inset izquierdo de los tres paneles del rail.
3. Ocultar el detalle duplicado del footer cuando el estado global sea normal.
4. Reducir Atencion inmediata normal a una sola linea.
5. Reservar las cuatro fuentes de Atencion para warning/critical o expansion voluntaria.
6. Subir el titular de una alerta a 20-24 px sin agrandar el resto del panel.
7. Bajar la saturacion persistente del PnL y del glow de Musica en estado estable.
8. Aclarar `--text-3` o eliminar su uso en textos inferiores a 12 px.
9. Reemplazar `Market Ribbon` por una etiqueta mas natural en espanol.
10. Cuando el grafico no monte, sustituir el vacio por una explicacion y la ultima
    lectura confiable disponible.

## 7. Roadmap propuesto

### Sprint 2 - Information Hierarchy

- Construir tres composiciones estaticas usando exactamente los modulos actuales.
- Definir estados `calma`, `atencion` y `degradado`.
- Medir reconocimiento a 80-90 cm y a 2 m.
- Elegir una composicion antes de tocar comportamiento productivo.

**Gate:** la informacion esencial debe reconocerse en cinco segundos y la condicion
accionable en dos segundos.

### Sprint 3 - Insight Layer determinista

- Definir un diccionario pequeno de frases permitidas.
- Documentar inputs, umbrales, frescura, abstencion y precedencia.
- Sustituir lecturas existentes; no agregar superficies.
- Probar contradicciones como BTC positivo con mercado global negativo.

**Gate:** toda frase debe reconstruirse desde datos visibles y nunca sonar mas segura
que su evidencia.

### Sprint 4 - Visual Language

- Congelar tokens de color, tipografia, inset, borde, radio y elevacion.
- Definir intensidad por estado: estable, seleccionado, actualizado, warning y critical.
- Unificar iconografia y lenguaje operacional.
- Validar contraste sobre el Arzopa real.

**Gate:** una captura monocroma debe conservar la jerarquia; el color no puede ser la
unica razon por la que algo destaque.

### Sprint 5 - Motion

- Transicion breve al cambiar estado.
- Aparicion contenida de alertas.
- Confirmacion visual de refresco y recuperacion.
- Respeto estricto de `prefers-reduced-motion`.

**Gate:** cada animacion debe explicar un cambio. Si solo decora, se elimina.

## 8. Elementos que no deberian cambiar

- TradingView como proveedor principal temporal.
- La proporcion general 67/33 entre grafico y contexto.
- La shell nativa sin navegador y sin scroll.
- El logo y la marca NexUX.
- La separacion entre cuenta principal y cuenta Bot.
- El caracter read-only del Command Center.
- El acceso `Analisis completo` a TradingView autenticado.
- El selector y los controles reales de Musica.
- La base oscura y el limite de 8 px para radios.
- Los estados contractuales y sus significados.
- Wire ABI, Gateway, EventBus, Runtime y arquitectura principal.

## 9. Elementos que deberian desaparecer hasta ser necesarios

- detalle permanente de Gateway/EventBus/Snapshot/Internet/Trading cuando todos estan
  listos;
- filas normales dentro de Atencion inmediata;
- timestamps tecnicos repetidos;
- estados `Unknown` de capacidades opcionales que no afectan el trabajo;
- superficies vacias cuando una fuente no esta disponible;
- glows permanentes que no representan cambio ni seleccion.

## 10. Criterios de exito de Experience Layer

Una iteracion solo debe aprobarse si:

1. reduce informacion que debe leerse para entender el estado;
2. mantiene o mejora la deteccion de riesgo;
3. conserva el grafico como ancla principal;
4. funciona en calma, alerta y degradacion;
5. distingue lectura cercana de lectura a dos metros;
6. no introduce datos, modulos, IA ni reglas operacionales nuevas;
7. mantiene el viewport sin overflow;
8. mejora la sensacion de producto integrado, no de tarjetas independientes.

## 11. Resolucion recomendada

**Experience Audit: APROBADA el 4 de agosto de 2026.**

La arquitectura visual principal queda congelada. Se autorizan exclusivamente los
quick wins de reduccion de carga cognitiva, jerarquia, modo calma, contexto,
legibilidad y consistencia documentados en esta auditoria.

## 12. Implementacion autorizada

### Bloque 1 - Modo calma y lenguaje

- lenguaje operacional visible unificado en espanol;
- `Market Ribbon` renombrado como `Pulso de mercado`;
- filas normales retiradas de `Atencion inmediata`;
- detalle duplicado del footer oculto cuando todo esta listo;
- alertas warning y critical con titular de mayor jerarquia.

### Bloque 2 - Consistencia visual

- inset comun de 16 px en el riel derecho;
- texto secundario elevado a contraste AA sobre ambas superficies;
- PnL y acentos musicales persistentes con menor saturacion;
- color intenso reservado para seleccion, cambio o atencion.

### Bloque 3 - Degradacion util

- el grafico indisponible explica la causa;
- conserva simbolo, ultimo precio fiable, variacion, frescura y hora cuando existen;
- nunca inventa una lectura ausente;
- mantiene disponible el salto a `Analisis completo`.

### Evidencia tecnica

- viewport 1920 x 1080 sin overflow horizontal ni vertical;
- proporcion 67/33, TradingView, shell y modulos preservados;
- 270/270 pruebas del Command Center aprobadas;
- 898 pruebas globales aprobadas y cuatro fallos preexistentes de datos de research:
  tres por `research/vacio_disponible_trades.json` ausente y uno por cambio de cohorte
  V1 en `data/setups.json`.

### Validacion pendiente

La aprobacion perceptual debe realizarse en el Arzopa a 80-90 cm, primero en estado
normal y luego con una alerta o degradacion real. No habilita nuevos modulos ni un
rediseño posterior.
