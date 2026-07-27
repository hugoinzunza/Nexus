# Bot2 de acción del precio — implementación inicial

Fecha: 2026-07-27  
Estado: `research_only`; no crea señales ni órdenes.

## Contrato v1

- Mercados: BTCUSDT y ETHUSDT.
- Temporalidades principales: 1h, 4h y 1d.
- Pivotes causales: 5 velas a la izquierda, extremo y 5 a la derecha.
- Fase I: impulso entre pivotes opuestos confirmados.
- Fase II: corrección entre 38,2% y 61,8%, sin perder el origen.
- Fase III: solo se confirma al aparecer el evento de la variante.
- Entrada: apertura de la vela siguiente con 0,03% de deslizamiento adverso.
- SL: extremo estructural de la corrección más 0,10 ATR.
- TP: primera proyección de fase alcanzable entre 1,25 / 1,50 / 1,618 / 2,00.
- Gate: RR neto mayor o igual a 2.
- Resolución intrabar conservadora: si SL y TP ocurren en la misma vela, cuenta SL.
- Gestión: salida completa. No se optimizaron parciales ni break-even.

El panorama superior veta únicamente cuando todas las tendencias conocidas son
contrarias. Los contextos mixtos o indefinidos se guardan como etiqueta para poder
compararlos; el curso no define una resolución objetiva para ese caso.

## Primera lectura histórica

Agregado BTC+ETH, 1h/4h/1d, usando todo el histórico disponible:

| Variante | n cerrados | WR | avgR | total R |
|---|---:|---:|---:|---:|
| Profesor, dos cierres | 11 | 18,2% | -0,431 | -4,744 |
| Primer cierre | 17 | 29,4% | -0,102 | -1,727 |
| Quiebre estructural | 20 | 30,0% | +0,042 | +0,850 |

En 1d ninguna variante superó simultáneamente contexto, evento y RR. El único
resultado positivo agregado es prácticamente plano y tiene `n=20`; no constituye
evidencia de edge.

## Veredicto actual

La traducción exacta de dos cierres llega tarde y produce muy pocas operaciones.
El quiebre temprano merece seguir como comparador, pero no debe promoverse: el
resultado es in-sample, no tiene walk-forward, mezcla mercados y su intervalo de
incertidumbre sería enorme.

La siguiente prueba honesta es un estudio walk-forward con parámetros congelados,
costos por mercado y reporte separado por año, par y temporalidad. Hasta entonces,
Bot2 es un visor y libro virtual de investigación.

## Vigilancia

La pantalla mantiene una lista causal de fases vigentes dentro de las 120 velas
posteriores a la confirmación de la corrección. Expone el estado previo a la
entrada, gatillo, distancia, SL, TP, RR estimado y panorama superior. “Lista para
próxima apertura” significa que la última vela cerrada completó la condición; la
apertura siguiente todavía no se conoce y no se inventa. La vigilancia desaparece
si el origen se invalida o vence la ventana.

## Aislamiento

`modules/bot2/` no importa el ejecutor, el cliente privado de Binance, credenciales
ni funciones de órdenes. Lee OHLCV versionado y completa la cola con el snapshot
público del VPS cuando está disponible. La API solo expone `GET state` y
`GET analysis`.
