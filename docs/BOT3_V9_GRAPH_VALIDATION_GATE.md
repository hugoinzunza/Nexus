# Bot3.v9 - Gate de validacion del grafico NexUX

**Fecha de registro:** 2026-08-17
**Estado:** `PENDIENTE / OBLIGATORIO ANTES DE ACEPTAR LA IMPLEMENTACION VISUAL`
**Contrato relacionado:** Bot3.v9
**contrato_hash:** `9d24166a33aa74af7f2b2dd7d0bdf4e2d16866e13eec7c48e7b1480512001530`

## Motivo

La conformidad pre-implementacion de Bot3.v9 fue exclusivamente contractual y
cientifica. No audito el grafico de NexUX ni certifico que sus velas, capas SMC,
marcas o controles representen correctamente el futuro motor Bot3.v9.

El usuario ha observado errores recurrentes en el grafico actual:

- la temporalidad seleccionada puede revertirse a la anterior;
- el grafico puede romperse al cambiar de temporalidad;
- existen recargas periodicas, parpadeo y perdida de continuidad visual;
- las capas de indicadores y estructura requieren revision;
- CDC, FVG, OB y demas marcas pueden no coincidir con el estado causal que las
  origina.

Estos defectos no quedan cubiertos por la conformidad del protocolo y deben
tratarse como un gate independiente.

## Alcance obligatorio

### 1. Paridad con el ledger

Cada marca visible debe poder vincularse a un evento real y versionado mediante
su identidad estable. Para una muestra auditada, timestamp, mercado,
temporalidad, precio, direccion, zona y estado deben coincidir exactamente con
el ledger canonico.

No se permite crear una marca solo a partir de un recalculo visual si el evento
correspondiente no existe en el ledger.

### 2. Causalidad visual

Una marca solo puede aparecer cuando su `available_at` ya es elegible para la
vela mostrada. Deben existir pruebas de prefijo que demuestren que agregar velas
futuras no crea, mueve ni elimina marcas historicas ya publicadas.

Se debe reproducir expresamente el antiguo defecto C-1 y confirmar que ninguna
vela M15 observa BOS, zona H4 u otra estructura antes del cierre que la hace
disponible.

### 3. Temporalidades

Validar todas las temporalidades expuestas por el selector, no solo 1H, 4H y
1D. Al cambiar entre ellas:

- la seleccion debe permanecer estable;
- no debe regresar automaticamente a la temporalidad anterior;
- velas, viewport y capas deben corresponder a la misma temporalidad;
- no deben mezclarse datos o marcas de una vista anterior;
- una respuesta tardia no puede sobrescribir la seleccion mas reciente.

### 4. Estabilidad de render

El refresco de datos no debe reconstruir innecesariamente el grafico completo.
Se debe verificar ausencia de parpadeo, pantalla vacia, salto de viewport,
duplicacion de capas y perdida de zoom o seleccion durante actualizaciones
normales.

Las transiciones de carga y degradacion deben fallar cerrado y conservar el
ultimo estado valido claramente identificado como no actualizado.

### 5. Capas SMC

Auditar por separado, cuando existan:

- CDC/BOS/iBOS;
- FVG;
- OB;
- zonas rectoras y derivadas;
- strong/weak;
- liquidez y sweeps;
- entrada, stop, target, fill y cierre.

Cada capa debe declarar su fuente, algoritmo, disponibilidad causal y
temporalidad. No mezclar heuristicas visuales heredadas con eventos Bot3.v9 sin
una etiqueta explicita.

### 6. Consistencia de precios y velas

OHLC, timestamps, sesiones y precios mostrados deben provenir del mismo almacen
sellado que consume el motor o demostrar una reconciliacion exacta con el. Una
divergencia entre grafico y motor debe producir estado degradado, no una
representacion silenciosamente aproximada.

### 7. Validacion visual en hardware real

Validar en el Arzopa QHD de 16 pulgadas con el viewport operativo real:

- legibilidad de velas y etiquetas;
- solapamientos entre marcas;
- contraste y saturacion;
- densidad de capas;
- estabilidad durante cambios de temporalidad;
- actualizaciones prolongadas sin parpadeo.

Incluir capturas y evidencia automatizada antes/despues. La inspeccion
perceptual complementa, pero no reemplaza, la paridad con el ledger.

## Criterios de aceptacion

El gate solo puede cerrarse cuando:

1. todas las temporalidades disponibles superan pruebas de cambio rapido y
   respuestas fuera de orden;
2. la muestra de eventos visuales coincide exactamente con el ledger;
3. las pruebas de prefijo no muestran retroactividad;
4. no hay reconstrucciones periodicas visibles ni parpadeo en una prueba
   prolongada;
5. cada capa SMC tiene provenance y semantica documentadas;
6. los estados de datos ausentes, stale o corruptos fallan cerrado;
7. la validacion perceptual en el Arzopa QHD queda registrada;
8. una re-auditoria independiente aprueba codigo, evidencia y capturas.

## Restricciones

- Este documento no modifica Bot3.v9 ni su `contrato_hash`.
- No autoriza despliegue, cohorte, Testnet, Live ni cambios al Bot.
- No autoriza reinterpretar el curso ni agregar indicadores no contratados.
- No permite usar el grafico como fuente cientifica primaria.
- La implementacion visual no se considera aceptada solo porque el motor pase
  sus pruebas.

## Estado registral

- Protocolo Bot3.v9: `CONFORME PARA IMPLEMENTACION`.
- Motor Bot3.v9: `NO IMPLEMENTADO`.
- Grafico NexUX frente a Bot3.v9: `NO AUDITADO`.
- Gate visual: `ABIERTO / OBLIGATORIO`.
