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

---

## Bitácora — contrato v2 (2026-08-15)

**Cambio:** `piv` pasa de 5 a 3 (configurable en `config.bot2.piv`; el código
conserva 5 como default). `min_net_rr` se mantiene en 2,0.

**Motivo mecánico, medido antes de mirar resultados de la grilla:** con `piv=5`
la cadena de confirmaciones (3 pivotes para el ciclo + 2 para el evento, 5 velas
de espera cada uno) consume la fase. Embudo medido sobre 4 años, BTC+ETH, 1h/4h/1d:
1.789 ciclos → 12-23 aceptados (0,7-1,3%): **54% de los ciclos se invalida antes
de que el evento sea observable** y otro 27-29% agota la ventana de 120 velas.
Un trade cada ~2,5 meses en todo el universo — el "no abre nunca" reportado el
2026-08-15 era la tasa base, no una falla.

**Grilla pre-declarada completa** (BTC+ETH agregado, 1h+4h; IS = pre-2025,
OOS = 2025+; corte fijado antes de correr):

| piv | RR≥ | variante | IS n / totR | OOS n / totR |
|---|---|---|---|---|
| 3 | 1,5 | teacher_2close | 18 / −0,27 | 9 / +6,04 |
| 3 | 1,5 | first_close | 35 / +1,31 | 22 / +12,46 |
| 3 | 1,5 | structure_break | 37 / +3,98 | 23 / +9,44 |
| 3 | 2,0 | teacher_2close | 11 / −1,34 | 4 / +2,65 |
| 3 | 2,0 | first_close | 20 / +7,29 | 13 / +6,06 |
| 3 | 2,0 | structure_break | 24 / +10,54 | 15 / +4,55 |
| 5 | 1,5 | teacher_2close | 8 / −5,74 | 13 / +1,93 |
| 5 | 1,5 | first_close | 22 / −15,66 | 19 / +4,79 |
| 5 | 1,5 | structure_break | 23 / −12,74 | 19 / +6,56 |
| 5 | 2,0 | teacher_2close | 6 / −6,58 | 5 / +1,84 |
| 5 | 2,0 | first_close | 6 / −6,56 | 11 / +4,83 |
| 5 | 2,0 | structure_break | 8 / −4,72 | 12 / +5,56 |

**Advertencias que esta tabla no permite olvidar:**

1. **Multiplicidad:** 12 celdas exploradas; ninguna corrección aplicada. Las 4
   celdas positivas en ambas mitades (todas con piv=3, variantes first_close y
   structure_break) NO son evidencia de edge — son la región que un estudio
   walk-forward tendría que confirmar o refutar.
2. **Régimen:** con piv=5 TODAS las variantes son negativas en IS y positivas en
   OOS. Eso huele a dependencia de régimen 2025-2026, no a robustez.
3. **Muestras chicas:** la mejor celda OOS tiene n=23. Cualquier IC honesto cruza
   ampliamente el cero.
4. La expectativa declarada del v1 no cambia: Bot2 sigue siendo un visor y libro
   virtual de investigación. **Nada de esto alimenta a BOT1, al Diario ni a
   ECON-COHORT-001.**

El v1 (piv=5) queda reproducible poniendo `piv: 5` en la config; los resultados
v1 de esta misma página no se editan.
