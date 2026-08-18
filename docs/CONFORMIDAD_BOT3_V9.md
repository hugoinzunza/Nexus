# Conformidad pre-implementacion - Bot3.v9

**Fecha:** 2026-08-17
**Protocolo revisado:** `docs/BOT3_V9_PROTOCOLO.md`
**Commit:** `b1f93f5`
**SHA-256 verificado / contrato_hash:** `9d24166a33aa74af7f2b2dd7d0bdf4e2d16866e13eec7c48e7b1480512001530`
**Informe v8:** SHA-256 `bffe94293b4c04fde4a3653414bf389a90def90c888100d135de359209a17abc`

## Criterio de cierre aplicado

Se mantiene el umbral acordado: solo bloquean divergencia del libro,
contaminacion causal, regla de parada incompleta o reconstruccion cientifica
imposible. Los bordes operacionales reproducibles quedan como gates
obligatorios para aceptar la implementacion.

## Veredicto

`CONFORME PARA IMPLEMENTACION`

La v9 cierra la unica contradiccion normativa pendiente en v8. Los tres eventos
que CF-11 y CF-35 obligan a emitir al corte ahora pertenecen al registro cerrado
CF-37, poseen preimagenes deterministas y cuentan con vectores dorados
reproducibles.

No se detectaron cambios adicionales en causalidad, temporalidad, finalidad,
regla de parada ni prueba exchange. El diff v8 -> v9 queda acotado al cierre
registral declarado y a las referencias de version correspondientes.

## Cierre del hallazgo v8

### B-1 - Registro cerrado y eventos obligatorios del corte

`CERRADO`.

- `abierta_al_corte` pertenece a la familia de jerarquia de trade y utiliza
  `trade_id`.
- `orden_al_corte` pertenece a la familia de jerarquia de trade y utiliza
  `order_id`.
- `degradacion_de_cobertura` posee una familia propia con mercado y rango
  temporal explicitos.
- La matriz de crash debe recorrer al menos un ejemplar de cada familia de
  CF-37, incluida la nueva familia de cobertura al corte.

Las identidades son univocas dentro de una cohorte: cada trade y orden tiene
una identidad estable; una degradacion queda identificada por contrato,
mercado y rango. Un cambio contractual exige nueva version y nueva cohorte.

## Vectores recalculados

Los tres vectores fueron recalculados desde sus JSON canonicos UTF-8, con claves
ordenadas y separadores compactos:

- `abierta_al_corte`:
  `58eb9ddb2112318a25eeb6bd8b1b04ed91567c5bac47032c5d97a223e2b1a663`.
- `orden_al_corte`:
  `563f3df291d78971685c0e81c81fe1de8060074e51634157398436e83b059256`.
- `degradacion_de_cobertura`:
  `34e0260c4a798204be97656d876f347967e3de0cf3bd9ddf8566d81771afdde9`.

Los tres coinciden exactamente con CF-37.

## Preservacion del contrato v8

- CF-34 permanece sin cambios sustantivos.
- CF-35 permanece sin cambios sustantivos.
- CF-36 permanece sin cambios sustantivos.
- No se agregaron productores, senales, decisiones operativas ni integraciones.
- `git diff --check` del candidato es limpio.

## Gates obligatorios para aceptar la implementacion

Estos puntos no bloquean el congelamiento del protocolo. Deben demostrarse con
tests y artefactos antes de aceptar la implementacion o iniciar una cohorte:

1. **Recovery y `processed_at`:** persistir el valor del lote para reutilizarlo
   tras crash, o comparar una proyeccion cientifica canonica que excluya esa
   telemetria. La matriz de crash no puede depender del reloj de reproceso.
2. **Finalidad multiple:** cuando un lote necesita varios marcadores,
   `finalized_at` debe ser el maximo de todos los `detected_at` que lo hicieron
   finalizable. El vector debe incluir marcadores con finales distintos.
3. **Heads globales:** los eventos globales deben portar el mapa canonico y
   ordenado de heads duales de los siete mercados, nunca el head arbitrario de
   uno solo.
4. **Prueba exchange:** los cuatro mercados calificantes deben seleccionarse
   alfabeticamente entre los que poseen tres cierres elegibles; un marcador de
   hueco no cuenta como vela probatoria.
5. **Gates ya congelados:** lote retrasado 45 minutos, catch-up con heads duales,
   caida parcial con 1-3 mercados, invariancia por permutacion, replay igual a
   vivo, bootstrap sin emision y matriz de crash sobre todas las familias de
   CF-37.

Un fallo en cualquiera de estos gates rechaza la implementacion sin reabrir ni
reinterpretar el protocolo.

## Hash y vigencia

Se congela como `contrato_hash`:

`9d24166a33aa74af7f2b2dd7d0bdf4e2d16866e13eec7c48e7b1480512001530`

Cualquier cambio posterior al texto normativo, registro de eventos,
preimagenes, parametros o reglas exige `Bot3.v10`, contrato_hash nuevo y
cohorte nueva. La conformidad autoriza implementar el contrato congelado; no
autoriza desplegarlo ni iniciar evidencia forward.

## Estado

- Protocolo Bot3.v9: `CONFORME / CONGELADO PARA IMPLEMENTACION`.
- Implementacion Bot3.v9: `AUTORIZADA, TODAVIA NO REALIZADA`.
- Re-auditoria de implementacion: `OBLIGATORIA`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte: `NO INICIADA`.
- Bot3.v1: `SUSPENDIDO`.
- Bot/Testnet/Live: `SIN AUTORIZACION`.
