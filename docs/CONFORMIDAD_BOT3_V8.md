# Conformidad pre-implementacion - Bot3.v8 candidato

**Fecha:** 2026-08-17
**Protocolo revisado:** `docs/BOT3_V8_PROTOCOLO.md`
**Commit:** `721dc8a`
**SHA-256 verificado:** `6ba91d3051c953edb1043299518e38e4833561f0e793a5d76fad100e46aec4a2`
**Informe v7:** SHA-256 `3dc07432e332368d8ae65c10a64b454a802c3a1e1887ef4ab3cc61d37c9f8dd4`

## Criterio de cierre aplicado

Se mantiene el umbral acordado: solo bloquean divergencia del libro,
contaminacion causal, regla de parada incompleta o reconstruccion cientifica
imposible. Los detalles operacionales verificables pasan a gates.

## Veredicto

`NO CONFORME - UN CIERRE REGISTRAL OBLIGATORIO`

La v8 cierra correctamente los dos bloqueos causales y las dos clarificaciones
de v7. La temporalidad triple ya distingue efectividad, finalidad y telemetria;
el corte administrativo cubre silencio parcial; la prueba exchange es canonica;
y el registro de eventos esta casi completo. Todos los hashes y vectores
publicados fueron reproducidos exactamente.

Persiste una unica contradiccion normativa que cruza el umbral de bloqueo: la
regla de parada exige emitir tres tipos que el registro cerrado prohibe. No se
puede implementar simultaneamente CF-35/CF-11 y CF-37. El resto de las
observaciones queda clasificado como gate de implementacion, no como motivo
independiente para rechazar el modelo cientifico.

## Hallazgo bloqueante

### B-1 - El registro cerrado omite eventos obligatorios del corte

CF-37 declara que el ledger admite EXCLUSIVAMENTE los tipos enumerados y que
agregar uno requiere v9. Sin embargo:

- CF-11 exige `abierta_al_corte` y `orden_al_corte`;
- CF-35 vuelve a exigir ambos tipos durante el cierre administrativo;
- CF-35 exige reportar `degradacion_de_cobertura` para las velas parciales y
  mercados faltantes.

Ninguno de esos tres tipos aparece en las ocho familias de CF-37. Por tanto,
una implementacion debe violar el registro cerrado o incumplir la regla de
parada. Esto afecta directamente la completitud del libro final y no puede
deferirse como detalle operativo.

La correccion minima para v9 es agregar una familia cerrada de corte con
preimagenes univocas. Recomendacion:

- `abierta_al_corte`: jerarquia de trade + contrato + `T_corte` + tipo;
- `orden_al_corte`: jerarquia de order + contrato + `T_corte` + tipo;
- `degradacion_de_cobertura`: si es por mercado, contrato + mercado + rango
  faltante + `T_corte` + tipo; si es un unico evento global, contrato +
  `T_corte` + hash canonico del detalle + tipo.

Debe congelarse una sola granularidad, agregar al menos un vector dorado por
tipo e incluir los tres en la matriz de crash. El mismo registro debe indicar
si estos eventos aplican tanto al corte por muestra como al temporal o solo a
los estados que correspondan.

## Gates de implementacion obligatorios, no bloqueantes del contrato cientifico

### G-1 - `processed_at` y la igualdad byte a byte tras crash

`processed_at` es reloj observado y puede cambiar si el evento se materializa
despues de un reinicio. Por ello, el gate de crash no puede prometer ledger
identico byte a byte sin una regla adicional. La implementacion debe elegir y
probar una:

- persistir una vez el `processed_at` del lote antes de emitir sus eventos y
  reutilizarlo durante recovery; o
- comparar una proyeccion cientifica canonica que excluya telemetria, dejando
  `processed_at` en un log operacional separado.

Esta decision no altera IDs, decisiones ni resultados, por lo que queda como
gate operacional bajo el criterio acordado.

### G-2 - `finalized_at` con multiples marcadores

Si un lote espera mas de un mercado, `finalized_at` debe ser el maximo de los
`detected_at` de TODOS los marcadores necesarios para hacerlo finalizable, no
el de un marcador elegido. El vector de catch-up debe incluir dos mercados con
pruebas que terminan en timestamps distintos.

### G-3 - Heads de eventos globales

Los eventos por mercado pueden portar un par de heads H4/M15. Para
`lote_finalizado`, `frontera` y `corte_administrativo`, la implementacion debe
portar un mapa canonico ordenado de heads duales por los siete mercados, no
elegir arbitrariamente un mercado. Esto permite reconstruir la barrera global.

### G-4 - Prueba exchange ante gaps propios

El gate ya exigido debe confirmar que los cuatro calificantes son los primeros
alfabeticos entre quienes poseen los tres cierres requeridos. Los timestamps de
cada mercado deben ser los tres primeros cierres cronologicos elegibles; un
marcador de gap del mercado de referencia no cuenta como vela probatoria.

## Cierres confirmados respecto de v7

- **B-1 anterior (temporalidad):** cerrado por
  `effective_at/finalized_at/processed_at` y heads duales.
- **B-2 anterior (parada parcial):** cerrado por la condicion "sin lote global
  finalizado", independiente de velas parciales.
- **M-1 anterior (prueba exchange):** cerrado; el vector `hg_ex` coincide.
- **M-2 anterior (registro):** las familias y abstenciones sin zona quedaron
  cerradas salvo los tres eventos de corte omitidos en B-1.

## Vectores y hashes verificados

- Protocolo v8: SHA-256 exacto
  `6ba91d3051c953edb1043299518e38e4833561f0e793a5d76fad100e46aec4a2`.
- CF-36: `hg_ex` coincide byte por byte.
- CF-37: vectores `abstencion` y `mercado_degradado` coinciden byte por byte.
- Vectores heredados CF-30/CF-31 permanecen reproducibles.
- `git diff --check` del candidato: limpio.

## Hash y vigencia

El mecanismo de vigencia es suficiente. CF-37 dispone expresamente que agregar
un tipo exige v9; por tanto, el cierre registral debe publicarse como protocolo
v9 con SHA-256 y commit nuevos. La siguiente pasada debe verificar solo:

1. los tres tipos de corte y sus preimagenes/vectores;
2. ausencia de otras referencias a tipos fuera del registro;
3. preservacion textual de CF-34..CF-36;
4. gates G-1..G-4 incorporados como criterios de implementacion.

Si esos cuatro puntos cumplen y no aparece una divergencia causal nueva, el
protocolo puede declararse `CONFORME PARA IMPLEMENTACION` bajo el criterio de
cierre acordado.

## Estado

- Bot3.v1: `SUSPENDIDO`.
- Protocolo v8 candidato (`6ba91d30...`): `NO CONFORME`.
- Bot3.v8: `NO IMPLEMENTADO`.
- Cohorte: `NO INICIADA`.
- Implementacion: `NO AUTORIZADA`.
