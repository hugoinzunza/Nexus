# Bot3.v13 - Gate de validacion del grafico NexUX

**Fecha de registro:** 2026-08-17
**Estado:** `PENDIENTE PRIORITARIO / BLOQUEA SU INCORPORACION DEFINITIVA AL COMMAND CENTER`
**Contrato vigente relacionado:** Bot3.v13
**contrato_hash vigente:** `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d`
**Origen registral:** este gate se abrio durante Bot3.v9 y permanece vigente
tras la congelacion e implementacion de Bot3.v13.

## Motivo

La conformidad e implementacion de Bot3.v13 fueron exclusivamente contractuales,
cientificas y de motor. No auditaron el grafico de NexUX ni certificaron que sus
velas, capas SMC, marcas o controles representen correctamente el motor Bot3.v13.

El usuario utiliza actualmente un grafico NexUX dentro del Command Center y ha
reportado que aparenta no estar actualizado. Esa percepcion se registra como una
incidencia pendiente de diagnostico, no como una conclusion sobre la fuente. La
primera tarea del gate es medir y mostrar explicitamente la frescura real del
feed, la ultima vela cerrada y la edad de la vela en formacion.

El usuario ha observado errores recurrentes en el grafico actual:

- la temporalidad seleccionada puede revertirse a la anterior;
- el grafico puede romperse al cambiar de temporalidad;
- existen recargas periodicas, parpadeo y perdida de continuidad visual;
- las capas de indicadores y estructura requieren revision;
- CDC, FVG, OB y demas marcas pueden no coincidir con el estado causal que las
  origina.

Estos defectos no quedan cubiertos por la conformidad del protocolo y deben
tratarse como un gate independiente. El grafico actual es provisional: no se
considera la superficie visual certificada de Bot3.v13 y no debe adquirir esa
condicion por despliegue implicito.

## Pendiente prioritario para Command Center

La incorporacion definitiva del grafico NexUX al Command Center requiere cerrar,
en este orden, los siguientes bloques:

1. **Frescura del feed:** medir ultima vela recibida, ultima vela cerrada, edad,
   fuente y continuidad; comparar contra Binance y fallar cerrado si divergen.
2. **Temporalidades y concurrencia:** impedir regresiones de seleccion y que una
   respuesta tardia sobrescriba la temporalidad vigente.
3. **Refresco incremental:** eliminar reconstrucciones periodicas, parpadeo,
   pantallas vacias y perdida de viewport.
4. **Paridad causal:** reconciliar OHLC y cada marca SMC con el almacen y ledger
   canonicos de Bot3.v13, incluyendo pruebas de prefijo.
5. **Validacion perceptual:** ejecutar una prueba prolongada y registrar capturas
   en el Arzopa QHD de 16 pulgadas con el viewport operativo real.

Hasta cerrar los cinco bloques, el grafico no reemplaza una fuente visual ya
validada ni se usa como evidencia cientifica o decisional.

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
temporalidad. No mezclar heuristicas visuales heredadas con eventos Bot3.v13 sin
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

- Este documento no modifica Bot3.v13 ni su `contrato_hash`.
- No autoriza despliegue, cohorte, Testnet, Live ni cambios al Bot.
- No autoriza reinterpretar el curso ni agregar indicadores no contratados.
- No permite usar el grafico como fuente cientifica primaria.
- La implementacion visual no se considera aceptada solo porque el motor pase
  sus pruebas.

## Estado registral

- Protocolo Bot3.v13: `CONGELADO`.
- Motor Bot3.v13: `IMPLEMENTADO / NO DESPLEGADO / COHORTE NO INICIADA`.
- Grafico NexUX frente a Bot3.v13: `NO AUDITADO / PROVISIONAL`.
- Integracion definitiva en Command Center: `BLOQUEADA POR ESTE GATE`.
- Gate visual: `ABIERTO / PENDIENTE PRIORITARIO`.
