# Sesion 08 - Bloques Trampa, iBOS Valido y Liquidez

**Fuente:** `Bloques Trampa, iBOS Valido & Liquidez`<br>
**Audio SHA-256:** `c25648387c9b0fd005eaebf15a567fd183eec914cc0fe78990183e20d7e6685a`<br>
**Transcripcion:** primera pasada local; seis patrones y ejemplos pendientes de
cotejo visual.

## Proposito declarado

La clase intenta distinguir zonas que deben evitarse y separar una confirmacion
estructural valida de un iBOS que solo genera liquidez.

| Evidencia | Tiempo | Observacion |
|---|---:|---|
| E0 | 00:00:21-00:02:34 | No todo OB ni todo iBOS debe aceptarse como zona o confirmacion. |
| E0 | 00:03:36-00:04:34 | Se presentan seis patrones recurrentes del profesor. |
| E0 | 00:36:05-00:38:10 | `Confirmacion` es una capa compuesta; no equivale solo a un quiebre LTF. |

## Bloque trampa

- **E0, 00:07:52-00:14:51:** si una estructura llega a una zona HTF contraria,
  los ultimos extremos LTF pueden actuar como liquidez. Un OB ubicado en uno de
  esos extremos puede reaccionar levemente y luego ser atravesado.
- **E0, 00:09:45-00:14:51:** se debe revisar como se construyo el extremo que
  contiene el OB. Si el retroceso deja liquidez pendiente detras de la zona, el
  bloque se clasifica como trampa y se busca la siguiente zona mas alla de esa
  liquidez.
- **E0, 00:17:52-00:21:40:** un impulso sin retrocesos internos deja como primer
  objetivo de liquidez el propio bajo/alto que contiene el OB. La confirmacion se
  espera despues de neutralizarlo, no necesariamente dentro del primer bloque.
- **E0, 00:26:40-00:34:05:** antes de seleccionar demanda se inspecciona liquidez
  por debajo; antes de seleccionar oferta, liquidez por encima. Una zona con todos
  los requisitos convencionales puede seguir siendo trampa.
- **E0, 00:33:48-00:35:00:** la `liquidez de afuera` incluye trendlines, equal
  highs/lows y extremos que cubren parcialmente un imbalance.

## Liquidez previa frente a liquidez exterior

- **E0, 00:34:25-00:35:40:** liquidez previa es la que aparece antes de alcanzar
  el bloque que se pretende operar.
- **E0, 00:33:48-00:35:40:** liquidez exterior queda mas alla del bloque y puede
  convertirlo en inducement/trampa.
- **I1:** son relaciones espaciales respecto del POI, no categorias absolutas del
  mismo high/low.

## Confirmacion e iBOS valido

- **E0, 00:36:05-00:38:10:** el profesor enumera cinco capas de confirmacion:
  fractal, rango, tipo de OB, liquidez institucional y eleccion entre riesgo o
  confirmacion estructural.
- **E0, 00:38:48-00:39:15:** una estructura de confirmacion menor proyecta un
  recorrido mas corto; una estructura interna mayor permite aspirar a mas tramo.
- **E0, 00:39:27-00:41:44:** para considerar valido el iBOS del ejemplo, el
  movimiento debe tomar liquidez a la izquierda y crear liquidez a la derecha.
  Si no crea liquidez a la derecha, puede construir otro rango y la entrada se
  evita.
- **E0, 00:41:28-00:41:50:** la regla se aplica en el ejemplo M15 -> M5/M3/M1 y
  se presenta como extensible a otros pares de temporalidades.

## Gestion y limites de certeza

- **E0, 00:02:34-00:03:18:** el profesor recuerda que son probabilidades; ante
  falta de claridad, la respuesta puede ser no operar.
- **E0, 00:50:40-00:53:53:** aun con un bloque trampa posible, propone dividir el
  riesgo entre dos zonas del rango, por ejemplo 0.5% + 0.5% para un riesgo total
  de 1%.
- **U0:** `siempre gestionar dos entradas` es enfatico en esta clase, pero puede
  ser una regla de gestion y no una condicion estructural. Se contrasta con las
  sesiones 10 y 11 antes de congelarla.
- **U0:** expresiones como `siempre se neutraliza` o `aumenta probabilidad` no
  incluyen frecuencia, muestra ni excepciones; no se convierten en hechos
  estadisticos.

## Hipotesis futuras

- **H1:** OB con liquidez exterior frente a OB sin liquidez exterior.
- **H1:** iBOS que toma liquidez izquierda y crea liquidez derecha frente a iBOS
  que incumple una de las condiciones.
- **H1:** impulso con estructura interna frente a impulso de velas continuas.
- **H1:** primera zona aparente frente a siguiente zona tras barrido.
- **H1:** escala de confirmacion y MFE posterior.

## Verificacion visual pendiente

- 00:04:34-00:35:40: los seis patrones y ubicacion precisa de liquidez exterior.
- 00:38:48-00:41:50: geometria izquierda/derecha del iBOS valido.
- 00:42:02-01:10:00: ejemplos reales, decisional frente a extremo y bloques
  trampa.

## Estado

`TRANSCRIBED / TRAP-AND-CONFIRMATION DRAFT / VISUAL REVIEW PENDING`
