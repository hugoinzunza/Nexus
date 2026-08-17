# Bot3.v6 — Protocolo pre-registrado CANDIDATO (submodelo single-entry H4→M15)

**Fecha:** 2026-08-17
**Estado:** `CANDIDATO / NO IMPLEMENTADO / PENDIENTE CONFORMIDAD CODEX`
**Antecedentes incorporados por referencia (prevalece este texto):**
- Diseño rev.3: `5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`
- Protocolo v2 (CF-1..CF-5): `ef267f23583d4a36eca46bacb4f51fabdaaecf81955ebb5d079f0aee083998ea`
- Protocolo v3 (CF-8, CF-9, CF-11): `5688f4cf4b073c26533810baa0d45658fe5eddf008907dc50977173057c9be70`
- Protocolo v4 (CF-13..CF-16): `6210e5bb578e2af2569b1041538f53acbccee9eb1b0dae388fdd9f832b79cf67`
- Protocolo v5 (CF-17..CF-21): `d5504d5029139f6a2c99e1de6a89c96a02afd69bb360e2e57113938f57465979`
- Informe NO CONFORME v5: `8bb8ffe34923ccb559d6d1c3dc89800e5bb2e54c58dac062252eaf31a5354ab1`

Vigencia: CF-8/9/11/13/14/15/16/18/20 permanecen; de CF-17 permanecen la
serialización, la cadena y la prioridad de fuentes (su regla de ingestión
queda REEMPLAZADA por CF-22); CF-19 queda COMPLETADA por CF-23; CF-21 queda
COMPLETADA por CF-24; se agregan CF-25..CF-27. El `contrato_hash` será el
SHA-256 de este archivo al declararse CONFORME.

---

## CF-22. Watermark causal de ingestión (reemplaza la ingestión de CF-17; cierra B-1)

- Por mercado/TF el almacén mantiene `ultimo_t` (t de la última línea de vela
  o marcador). **Buffer:** toda vela recibida con `t > ultimo_t` entra a un
  buffer donde la prioridad de fuentes (versionado > push) aplica durante
  TODA su permanencia (una copia versionada que llega después reemplaza a la
  del push EN EL BUFFER; nunca en el almacén).
- **Append por prefijo continuo:** mientras el buffer contenga la vela con
  `t == ultimo_t + dur`, se appendea y `ultimo_t` avanza. Ninguna vela se
  appendea con su predecesora faltante.
- **Declaración de hueco (solo timestamps de mercado, jamás pulls):** si la
  vela `ultimo_t + dur` falta y el buffer contiene velas de **N = 3** `[U0]`
  cierres de mercado posteriores distintos (`t ≥ ultimo_t + 2·dur`, contando
  t distintos), se declara hueco: se appendea a la cadena el **marcador
  canónico** `{"desde":<ultimo_t+dur>,"gap":true,"hasta":<t_min_buffer −
  dur>}` (serialización canónica, mismo encadenado `hash_acum`), `ultimo_t`
  pasa a `t_min_buffer − dur` y el append continúa desde `t_min_buffer`.
- Una vela que llegue con `t ≤ ultimo_t` tras la declaración →
  `vela_no_incorporada` (el hueco es permanente; nada se reabre).
- **Anclas iniciales:** H4: `ultimo_t` inicial = `GENESIS_H4 − 4h` (la
  primera vela esperada es GENESIS_H4; velas anteriores se ignoran). M15:
  la primera vela del almacén es la de menor `t` presente en el primer ciclo
  de ingestión con buffer no vacío (tras prioridad de fuentes); queda
  registrada en el evento de nacimiento del almacén con provenance.
- **Vectores dorados de cadena con hueco** (reemplazan a los de CF-17;
  semilla `"0"×64`, velas c1/c2/c3 de CF-17, falta `t=1646094600000`):
  - `ser(gap) = {"desde":1646094600000,"gap":true,"hasta":1646094600000}`
  - `h1 = 7bceed811ed9f3d848f5139114b9c8b04ea50b46347f6de61d11291bec1271e7`
  - `h2 = 5d84537de5783432781eeadecdf86759d26abc93bbbdff158b7a9832161df6cf`
  - `hg = 43e36536c274715b2eb7a41c53a88196fe4376a34a8896b3f49787b78cfbef9f`
  - `h3 = 56ba4db1a4f037c4534407d7b093087184c654ee5cc60fe73bd4836efed7aa49`
  - Gate adicional: el escenario A/B del informe v5 (t2 llega antes que t1)
    debe producir el MISMO almacén en ambas implementaciones (t1 y t2
    appendeadas en orden si t1 llega antes de declararse el hueco).

## CF-23. Finalidad de lote y recuperación (completa CF-19; cierra B-2)

- El lote `T` queda **FINALIZABLE** cuando para CADA mercado se cumple una:
  (a) su vela M15 con `close_time = T` está appendeada; (b) un marcador de
  hueco appendeado cubre `T`; (c) el mercado no tiene época M15 habilitada.
  El motor procesa el lote solo cuando es finalizable; el watermark de CF-22
  garantiza que la espera termina (la declaración depende de cierres de
  mercado observados, no de pulls).
- Composición inmutable: al procesarse, el conjunto de mercados del lote
  queda fijo. Un mercado en caso (b)/(c) no ejecuta fases en `T`. Una vela
  tardía JAMÁS reabre un lote (CF-22 la rechaza).
- Los eventos derivados de un hueco (cancelación de orden,
  `trayectoria_indeterminada`) se emiten en el primer lote finalizable que
  hizo observable el hueco, con la temporalidad dual de CF-27.
- **Atomicidad y crash:** el lote emite sus eventos por mercado en orden
  canónico y termina con el evento `lote_finalizado(T)`. Tras un crash, el
  motor reprocesa desde el último `lote_finalizado` previo; el determinismo
  (almacén sellado + reglas) reproduce exactamente los mismos eventos y la
  identidad estable de eventos (CF-26) hace la re-emisión idempotente (sin
  duplicar ni omitir).

## CF-24. Bootstrap con transiciones completas (completa CF-21; cierra B-3)

- El bootstrap ejecuta **TODAS las transiciones** del motor — candidatos,
  arbitraje, órdenes, fills, salidas — con efecto COMPLETO sobre estado
  estructural, **frescura, mitigación, TTL, invalidación** y arbitraje. Lo
  ÚNICO suprimido es la escritura de eventos evaluables al ledger forward.
- Al cruzar `T_frontera`: `orden_viva`/`posicion`/`salida_detectada` → `flat`
  (registrado como evento no evaluable `estado_inicial` con detalle). Las
  zonas NO se resucitan; la historia de toques y frescura persiste íntegra.
- **Gate obligatorio:** vector donde una zona H4 se toca antes de la frontera
  y se vuelve a tocar después — NO puede crear candidato forward (frescura ya
  consumida). Implementación que lo permita = rechazada.

## CF-25. Heads del almacén en cada evento (cierra M-1)

Todo evento de dominio del ledger (candidato, orden_*, fill, cerrado,
trayectoria_indeterminada, estado_inicial, frontera, lote_finalizado) incluye:
`h4_hash_acum` y `m15_hash_acum` vigentes a su `ahora`, `epoca_m15` (t inicial
de la época), `contrato_hash` y commit de implementación. La afirmación
replay ≡ vivo se verifica EVENTO POR EVENTO comparando estos campos.

## CF-26. Identidad estable de incidencias y eventos (cierra M-2)

- Incidencias de ingestión (`vela_revisada`, `vela_no_incorporada`):
  `incidencia_id` = SHA-256 hex minúscula de la serialización canónica CF-9 de
  `{"contenido":"<sha256 de ser(vela observada)>","mercado":"…","t":<ms>,`
  `"tf":"…","tipo":"…"}`. Cada `incidencia_id` se registra UNA sola vez;
  reapariciones en ciclos posteriores no generan nuevos eventos.
- Eventos de dominio: su identidad es la jerarquía CF-9
  (`candidate_id`/`order_id`/`trade_id`) más el tipo de evento; la re-emisión
  tras crash (CF-23) dedupe por esa identidad.

## CF-27. Temporalidad dual de huecos (cierra M-3)

Todo evento derivado de un hueco lleva DOS timestamps:
- `effective_at` = `close_time` de la última vela sellada verificable antes
  del hueco (convención congelada);
- `detected_at` = `close_time` del lote en que el watermark hizo observable
  el hueco (primer lote finalizable que lo incluye).
Nada se backdatea con un único timestamp; ambos son obligatorios y quedan en
el ledger.

---

## Parámetros congelados (consolidado; `[U0]` salvo nota)

| Parámetro | Valor |
|---|---|
| Universo (orden canónico) | ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT |
| GENESIS_H4 | 2022-03-01T00:00:00Z (`1646092800000`), época única continua |
| Épocas M15 | segmentos maximales; habilitación ≥200 velas |
| Watermark de hueco | N = 3 cierres de mercado posteriores distintos |
| Fila del curso | zona H4 → confirmación M15 (única) |
| STRUCT_PIV / INT_PIV | 8 / 3 |
| Expiración dirección H4 | 180 velas H4 |
| TTL zona H4 | 180 velas H4 desde `available_at` |
| Deadline total toque→fill | 64 velas M15 |
| Ventana iBOS | ≤48 velas M15 desde el toque |
| Buffer SL | `S_long=Q(extremo×0.999)` / `S_short=Q(extremo×1.001)` |
| RR neto mínimo (a priori) | 2,0 |
| Fees | maker 0,02% · taker 0,05% |
| Slippage STOP | 0,05% (CF-15) |
| Funding | 0,01% por devengo (CF-8; sin imputaciones, CF-18) |
| Corte | 50 cierres totales (≥8 semanas ISO) o `1798761599999` ms, lotes CF-19/23 |
| Bootstrap estadístico | semanas ISO, 10.000 réplicas, semilla 20260817, IC 95% |
| Q | `round(x, 6)` float64 half-even (vectores CF-15) |
| Serialización almacén | shortest-repr float64 + cadena con marcador de hueco (vectores CF-22) |

## Reglas de vigencia

1. CANDIDATO: se congela como v6 definitivo solo con conformidad de Codex; su
   SHA-256 pasa a ser `contrato_hash`. Cambio posterior = v7 + cohorte nueva.
2. Gates de implementación: diseño rev.3 §11 + vectores CF-15/CF-22 +
   determinismo génesis/épocas + escenario A/B de llegada tardía (CF-22) +
   lote con mercado ausente y recuperación de crash idempotente (CF-23) +
   vector de frescura pre/post frontera (CF-24) + heads por evento (CF-25) +
   identidad replay≡vivo (CF-16) + dedupe de incidencias (CF-26).
3. Frontera forward según CF-21/CF-24. Bot3.v1 SUSPENDIDO; nada de v1..v5 se
   reutiliza como evidencia. Resultado positivo NO autoriza Bot/Testnet/Live.
4. Evaluación ÚNICA al corte; octubre es checkpoint informativo.

## Secuencia restante

Conformidad Codex → congelamiento v6 (hash = contrato_hash) → implementación
(paso 5) → re-auditoría completa (paso 6) → despliegue verificado (paso 7) →
cohorte desde cero (paso 8).
