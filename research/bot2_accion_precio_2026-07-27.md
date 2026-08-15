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

---

## Contrato v3 — gate V pre-registrado (2026-08-15, ANTES de computar resultados)

**Origen:** los apuntes de la clase 14 muestran que el plan del curso es **T+Z+V
conjuntivo** y Bot2 solo implementa la T (panorama). El vacío (V) se registra
(`obstacles_before_target`) pero no se exige, y el target usa la proyección más
cercana en vez del "anterior al primer obstáculo" que enseña el curso.

**Definición congelada de la política `first_obstacle`:**

1. Se calcula el target por proyección igual que v2.
2. Si existe un pivote confirmado del lado opuesto **estrictamente entre la
   entrada y ese target** (mismo criterio causal que ya usa
   `obstacles_before_target`), el target se mueve **justo antes** del primer
   obstáculo: `obstáculo × (1 − 0,0005)` en long, `× (1 + 0,0005)` en short —
   el mismo epsilon del doc de muros.
3. Si el target recortado no supera la entrada, la operación se rechaza por
   `vacío insuficiente`.
4. El gate `RR neto ≥ 2` se evalúa contra el target final. Ahí vive el veto V del
   curso: si el primer obstáculo está tan cerca que no caben 2R, no hay entrada.
5. Todo lo demás es idéntico al v2 (piv=3, mismas variantes de gatillo).

**Z queda explícitamente fuera:** la clase 06 define las zonas de forma narrativa
(sin ancho ni grado objetivos). Implementarla exigiría decisiones nuestras que el
curso no toma; sería otra hipótesis, con su propio pre-registro.

**Predicciones registradas ahora, con la evidencia previa en la mano:**

| Efecto | Predicción | Fundamento previo |
|---|---|---|
| n de trades | baja | el veto solo remueve |
| Win rate | sube | targets más cercanos se alcanzan más |
| avgR | **incierta, sesgo a peor** | el estudio del imán (2026-07-25) mostró que capar ganadoras empeora la expectativa de forma monótona; el gate V mezcla veto (que no puede inflar) con recorte (que históricamente resta) |

**Criterio de lectura, congelado:** la comparación es **pareada** (mismos ciclos,
misma señal, solo cambia la política de target). La corrida histórica se publica
completa como contexto exploratorio sobre datos reciclados. La evidencia que
cuenta es el libro forward: consideración de promoción a política por defecto del
visor recién con **n≥30 afectados** en forward y ΔavgR pareado con IC95 por
bloques que no cruce cero. `research_only` sigue; nada alimenta a BOT1 ni al
Diario.

### Resultados de la corrida histórica pareada (2026-08-15, posterior al pre-registro)

Datos reciclados (BTC+ETH, 1h+4h, piv=3, RR≥2, las tres variantes de gatillo):

| Política | n cerrados | WR | totR | avgR |
|---|---:|---:|---:|---:|
| `projection` (v2) | 87 | 39% | +29,75 | +0,342 |
| `first_obstacle` (v3) | **0** | — | — | — |

Embudo del v3: además de los rechazos compartidos con v2, **678 eventos mueren por
`vacío insuficiente`** (el primer obstáculo queda pegado a la entrada) y **611 por
`RR neto < 2` contra el target recortado**. El gate V literal cierra la estrategia
por completo.

**Lectura honesta:** la predicción registrada era "n baja"; la realidad fue n=0.
La causa es identificable: Bot2 trata **cada pivote confirmado** del lado opuesto
como obstáculo, y con piv=3 los pivotes son densos. El curso, en cambio, mide el
vacío contra su **catálogo de zonas de primer y segundo grado** (el gate Z) — no
contra cada micro-pivote. Es decir: **V sin Z no es el plan del curso, es una
caricatura más estricta**, y este resultado lo demuestra con números.

**Consecuencia:** `first_obstacle` queda disponible en el visor como evidencia
didáctica (muestra el embudo del veto), pero NO como candidata a política por
defecto. Implementar el V verdadero exige primero definir grados de zona de forma
objetiva — el mismo requisito que dejó a Z fuera de este contrato. Si se hace,
será un pre-registro nuevo; este no se edita.
