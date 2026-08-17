# Sesion 06 - Criterios de Entrada

**Fuente:** `Criterios de Entrada`<br>
**Duracion:** 02:25:47<br>
**Audio SHA-256:** `4e8eeb6da4404b97bd9d6298db1a49880e76f043aadc51d1654a6568edea001c`<br>
**Transcripcion:** primera pasada local; operaciones de replay pendientes de cotejo.

## Proposito declarado

Elegir entre los dos modelos de entrada del curso: `a riesgo` o `por
confirmacion`. El profesor declara que la eleccion depende del plan y gestion de
riesgo, no de preferencia subjetiva.

| Evidencia | Tiempo | Observacion |
|---|---:|---|
| E0 | 00:00:39-00:01:58 | Solo se presentan dos modelos: riesgo y confirmacion. |
| E0 | 00:03:39-00:05:00 | El objetivo y horizonte de la operacion deben definirse antes de buscar una entrada perfecta. |
| E0 | 00:17:57-00:19:12 | HTF define direccion; LTF define entrada. |

## Zonas admitidas

- **E0, 00:31:54-00:32:37:** ambos criterios pueden aplicarse unicamente sobre
  tres clases de POI: OB, imbalance o toma de liquidez.
- **I1:** la zona es una precondicion; la decision riesgo/confirmacion es una capa
  posterior y no una propiedad intrinseca del OB.

## Entrada a riesgo

- **E0, 00:32:38-00:34:19:** orden programada directamente en la zona, antes de
  confirmacion posterior.
- **E0, 00:33:54-00:37:28:** ventaja: mayor probabilidad de recibir fill;
  desventaja: stop estructural mas amplio y posibilidad de invalidacion inmediata.
- **E0, 00:34:48-00:36:08:** el ejemplo exige al menos 2R hacia el high/low objetivo
  para compensar una unidad de riesgo.
- **E0, 00:36:20-00:36:50:** si la zona amplia no entrega RR suficiente, se
  descarta la entrada a riesgo y se considera confirmacion.
- **E0, 00:42:39-00:43:06:** ante toma de liquidez, el profesor normalmente espera
  confirmacion por la amplitud incierta del barrido.

## Entrada por confirmacion

- **E0, 00:43:13-00:44:13:** la confirmacion no es garantia; se necesita distinguir
  iBOS valido de iBOS de liquidez/bloque trampa.
- **E0, 00:44:13-00:45:00:** tabla observada de pares:
  - zona diaria -> confirmacion H1;
  - zona H4 -> confirmacion M15;
  - zona H1 -> confirmacion M5;
  - scalping -> confirmacion en temporalidad de entrada inferior, aun por precisar.
- **E0, 00:45:24-00:47:56:** tras reaccionar la zona HTF se espera iBOS en LTF;
  las nuevas zonas creadas por ese desplazamiento ofrecen la entrada posterior.
- **E0, 00:47:48-00:50:21:** bajar otra temporalidad puede refinar el stop, a costa
  de complejidad y posible perdida del movimiento.

## Reglas candidatas adicionales

- **E0, 00:52:16-00:55:47:** el profesor pide al menos diez velas despues de la
  reaccion para considerar un impulso/reaccion suficientemente desarrollado. Las
  velas pueden ser mixtas.
- **E0, 00:52:16-00:55:47:** se cuentan en la temporalidad de la zona de
  reaccion: una zona H4 usa diez velas H4; una M15, diez velas M15; una M5, diez
  velas M5.
- **E0, 00:52:16-00:55:47:** si las diez velas se desarrollan por dentro de la
  zona/estructura, el profesor pide cautela porque puede no romper el alto.
- **E0, 00:52:16-00:55:47:** el propio docente relativiza la regla como `un dato
  no mas`.
- **U0:** no queda claro si diez velas es condicion de entrada, evaluacion posterior
  de la reaccion o heuristica didactica. La relativizacion docente refuerza su
  estado amarillo y bloquea su uso como condicion mecanica.
- **E0, 01:04:58-01:05:10:** los rompimientos usados para confirmacion se exigen
  con cuerpo; la mecha sola no sirve en el ejemplo.

## Gestion observada, no congelada

- Durante el replay el profesor combina posiciones long y short, multiples
  entradas, break-even y parciales. Son decisiones de demostracion, no reglas
  estables hasta revisar las sesiones 9-11.
- La frase `dos entradas por estructura` aparece en la practica, pero no esta
  definida aun como limite universal.
- Los costos, slippage y sizing no se formalizan en esta clase.

## Hipotesis futuras

- **H1:** entrada a riesgo frente a confirmacion condicionada por RR disponible.
- **H1:** matriz HTF/LTF del curso frente a confirmacion en la misma temporalidad.
- **H1:** iBOS valido y zona derivada frente a primer toque del POI.
- **H1:** regla de diez velas como descriptor de reaccion.

## Verificacion visual pendiente

- 00:17:57-00:21:12: tabla de temporalidades.
- 00:31:54-00:43:06: riesgo y su geometria de stop/target.
- 00:43:13-00:50:50: confirmacion multi-timeframe.
- 00:52:30-00:56:56: regla de diez velas.
- 00:59:17-01:16:29: ejemplo diario -> H1.
- 01:20:07-02:00:00: replay, bloques trampa, riesgo, confirmacion y gestion.

## Estado

`TRANSCRIBED / ENTRY MODEL DRAFT / VISUAL REVIEW PENDING`
