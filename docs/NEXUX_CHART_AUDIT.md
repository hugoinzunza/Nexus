# NexUX Chart - Auditoria de estabilizacion

**Fecha:** 2026-08-22
**Estado:** `AUDITADO / ESTABILIZACION EN CURSO / GATE BOT3 ABIERTO`
**Superficie canonica:** `modules/trading/` (NexUX Trading)
**Consumidor secundario:** Command Center, layout 67/33, Arzopa QHD 16 pulgadas

## Precedencia

El grafico que debe auditarse y corregirse es el grafico de NexUX Trading. Command
Center consume esa superficie y no puede mantener un segundo motor de velas,
temporalidades o SMC con semantica propia.

La precedencia queda congelada para esta estabilizacion:

1. fuente, temporalidades y capas del grafico NexUX;
2. adaptador de Command Center;
3. validacion perceptual en el Arzopa.

Esta auditoria no certifica Bot3.v13 ni autoriza despliegue, cohorte, Testnet o
Live.

## Hallazgos

### 1. Velas y overlays usan autoridades distintas

NexUX obtiene historia profunda de Binance y el tramo reciente desde el push de
Binance cuando esta vigente. En 1m y 5m declara el fallback a Crypto.com. El
navegador solo conecta el WebSocket de Binance cuando las velas visibles tambien
son de Binance.

Sin embargo, CDC, FVG, OB, dealing range y TP/SL proceden de
`/m/trading/api/smc`. Ese endpoint conserva deliberadamente el analizador y feed
legados para no alterar una cohorte historica. No publica contrato, event IDs,
`available_at`, ledger ni provenance Bot3.v13.

Por lo tanto, las capas SMC heredadas no pueden presentarse como Bot3 ni quedar
activas por defecto. El feed cientifico legado tampoco debe modificarse para
resolver un problema visual.

### 2. Carrera ABA al cambiar temporalidad

Las respuestas se descartaban solo si la temporalidad actual era distinta. Una
secuencia H4 -> 1D -> H4 permitia que la primera respuesta H4, mas antigua,
sobrescribiera la segunda. El mismo defecto existia en velas, SMC y Curso.

Ademas, el grafico conservaba las velas anteriores debajo de la etiqueta de la
nueva temporalidad hasta terminar el fetch. Eso explica la percepcion de que el
selector vuelve o mezcla H1, H4 y 1D.

### 3. WebSocket reemplazado sin identidad de generacion

Cerrar un socket anulaba `onclose`, pero un mensaje ya encolado podia seguir
actualizando la tarjeta despues de cambiar temporalidad o instrumento. Una tarjeta
oculta tambien podia completar un fetch tardio y tomar el socket global.

### 4. Frescura incompleta

El sello distingue Binance, Crypto.com, conectando, en vivo y stream mudo, y
publica el atraso del push. Todavia falta un contrato completo de salud con ultima
vela cerrada, continuidad y brechas para cerrar el gate Bot3.

### 5. Refresco normal mayormente incremental

La actualizacion WebSocket usa `series.update`; el refresco REST solo reconstruye
cuando cambia la cardinalidad y el back-load conserva el rango logico. El
parpadeo reportado no nace del ciclo normal, sino de respuestas/socket obsoletos y
del cambio de temporalidad sin limpiar la vista anterior.

### 6. Densidad y semantica visual

En QHD, el TP/SL heredado, strong/weak, POIs y cajas compiten con las velas. La
vista por defecto debe conservar solo indicadores descriptivos calculados sobre
las mismas velas visibles. Las capas heredadas deben requerir activacion manual y
mostrar su estado no certificado.

### 7. Command Center aun no es un consumidor puro

El adaptador provisional de Command Center consulta Binance directamente y
mantiene calculos visuales propios. Aunque reutiliza `/m/trading/api/smc`, todavia
no hereda de punta a punta el contrato del grafico NexUX. Esta divergencia no se
amplia en esta pasada: queda como gate de integracion prioritario.

## Contrato provisional de estabilizacion

1. NexUX Trading es la fuente visual canonica; Command Center no recalcula SMC.
2. Cada carga de velas, SMC y Curso lleva una revision monotona por tarjeta.
3. Cada WebSocket lleva generacion, temporalidad, tarjeta e instrumento capturados.
4. Cambiar temporalidad invalida solicitudes, cierra el socket anterior y limpia
   inmediatamente la vista antigua.
5. Una tarjeta oculta no puede aplicar respuestas ni reclamar el socket global.
6. Volumen, EMA 21/55, RSI 14 y ADX 14 siguen siendo descriptivos sobre las velas
   visibles.
7. El endpoint SMC declara expresamente que su contrato es legado, no validado y
   no compatible con Bot3.
8. TP/SL, niveles y otras capas SMC legadas quedan apagadas por defecto.

## Pendientes para cerrar el gate

- endpoint visual canonico derivado del ledger Bot3.v13;
- paridad evento por evento y pruebas de prefijo;
- salud completa de velas: cierre, edad, continuidad y brechas;
- prueba prolongada sin parpadeo;
- validacion de todas las temporalidades en NexUX;
- validacion posterior del adaptador de Command Center;
- eliminacion de la obtencion y semantica duplicadas en ese adaptador;
- capturas antes/despues en el Arzopa fisico;
- re-auditoria independiente de `BOT3_V9_GRAPH_VALIDATION_GATE.md`.

Hasta completar esos puntos, NexUX Chart es una superficie descriptiva de
mercado. No es una fuente cientifica o decisional y no acredita Bot3.
