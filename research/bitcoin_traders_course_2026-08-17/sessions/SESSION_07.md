# Sesion 07 - OB de Alta Reaccion

**Fuente:** `OB de Alta Reaccion`<br>
**Audio SHA-256:** `242797b2ae0ad13b571e78d33070676bcd0f7abf52039439cef2d072d86b16f1`<br>
**Transcripcion:** primera pasada local; replay pendiente de cotejo visual.

## Proposito observado

Aunque el titulo menciona OB de alta reaccion, el profesor presenta la sesion como
un repaso y mini-backtesting de fractales, rangos, zonas, liquidez y criterios de
entrada. Declara que esos cinco elementos forman el nucleo de la estrategia y que
bloques trampa, sistema y gestion son complementos posteriores.

| Evidencia | Tiempo | Observacion |
|---|---:|---|
| E0 | 00:00:09-00:02:35 | La clase integra los conceptos previos; el nucleo llega hasta criterios de entrada. |
| E2 | 00:03:46-00:58:00 | Replay bajista completo desde H4 hacia M15, zona, confirmacion y objetivo. |
| E0 | 00:57:46-00:58:06 | El objetivo principal se identifica con el `weak low` del rango rector. |

## Secuencia aplicada en el replay

1. **E0, 00:03:46-00:10:32:** definir primero la direccion H4 mediante rango y
   fractal.
2. **E0, 00:09:39-00:12:31:** bajar a M15 y exigir alineacion bajista para buscar
   ventas hacia el `weak low` H4.
3. **E0, 00:12:31-00:17:28:** esperar la finalizacion del rango M15 y su iBOS antes
   de seleccionar el retroceso.
4. **E0, 00:14:30-00:18:16:** operar desde el 50% del rango en adelante; si la zona
   o el stop son amplios, preferir confirmacion.
5. **E0, 00:18:20-00:19:18:** agregar lectura de liquidez y zonas de oferta sin
   asumir que el precio deba alcanzar todas.
6. **E2, 00:55:44-00:57:58:** el ejemplo llega al objetivo del rango despues de
   varias oportunidades internas en la direccion principal.

## Uso y frescura de zonas

- **E0, 00:57:08-00:57:47:** el profesor recomienda usar una zona de interes una
  sola vez. Tras dos o tres reacciones deja de considerarla, salvo una excepcion
  discrecional si conserva el stop y mantiene una proyeccion mas profunda.
- **E0, 01:00:00-01:01:04:** un OB H4 puede reaccionar varias veces si, al refinar,
  cada reaccion corresponde a un OB M15 interno diferente. No se interpreta como
  reutilizacion automatica de la misma zona refinada.
- **I1:** la frescura debe modelarse por zona efectiva y timeframe, no solo por el
  contenedor HTF.

## Gestion observada

- **E0, 00:19:24-00:19:37:** el profesor sugiere gestionar dos posiciones, como
  maximo tres, cuando existe mas de un punto de entrada.
- **E0, 00:57:47-00:59:12:** se observan long y short simultaneos, break-even y
  nuevas entradas internas. Son decisiones del replay, no reglas de entrada.
- **E0, 01:05:49-01:06:24:** en un ejemplo toma 10% parcial tras alcanzar varias
  unidades de riesgo.
- **U0:** la gestion no es estable ni completamente parametrizada en esta sesion;
  debe resolverse con las sesiones 9-11.

## Condiciones de abstencion

- **E0, 01:07:15-01:07:59:** no vender antes del 50% y no operar si no aparece una
  zona o estructura admisible; el profesor resume que no operar tambien es ganar.
- **E0, 01:03:48-01:04:00:** primero se prueba la estrategia y su adaptacion antes
  de aumentar riesgo.

## Hipotesis futuras

- **H1:** primer uso de una zona frente a segundo o tercer toque.
- **H1:** alineacion H4/M15 frente a estructura M15 aislada.
- **H1:** confirmacion por encima/debajo del 50% frente a primer toque del POI.
- **H1:** OB HTF con zonas LTF internas distintas frente a reutilizacion de una
  unica zona LTF.

## Verificacion visual pendiente

- 00:03:46-00:18:16: construccion exacta del rango H4/M15 y nivel 50%.
- 00:42:00-00:58:00: entradas internas, objetivos y cierres del replay.
- 00:57:08-01:01:04: zonas consumidas y OB HTF con refinamientos LTF.

## Estado

`TRANSCRIBED / INTEGRATION REPLAY DRAFT / VISUAL REVIEW PENDING`
