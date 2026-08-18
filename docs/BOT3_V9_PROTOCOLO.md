# Bot3.v9 — Protocolo pre-registrado CANDIDATO (submodelo single-entry H4→M15)

**Fecha:** 2026-08-17
**Estado:** `CANDIDATO / NO IMPLEMENTADO / PENDIENTE CONFORMIDAD FINAL CODEX (pasada acotada al cierre registral)`
**Antecedentes incorporados por referencia (prevalece este texto):**
- Diseño rev.3: `5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`
- Protocolo v2: `ef267f23583d4a36eca46bacb4f51fabdaaecf81955ebb5d079f0aee083998ea`
- Protocolo v3: `5688f4cf4b073c26533810baa0d45658fe5eddf008907dc50977173057c9be70`
- Protocolo v4: `6210e5bb578e2af2569b1041538f53acbccee9eb1b0dae388fdd9f832b79cf67`
- Protocolo v5: `d5504d5029139f6a2c99e1de6a89c96a02afd69bb360e2e57113938f57465979`
- Protocolo v6: `a342cd100d94482326fff31f5160e99e7131ae919f4681eff47339bbcd1cd393`
- Protocolo v7: `c9ea96be4d0b2041b4e26edbd8eb7e4b9964c6e0735853213f451320c67c5921`
- Informe NO CONFORME v7 (con criterio de cierre): `3dc07432e332368d8ae65c10a64b454a802c3a1e1887ef4ab3cc61d37c9f8dd4`
- Protocolo v8: `6ba91d3051c953edb1043299518e38e4833561f0e793a5d76fad100e46aec4a2`
- Informe NO CONFORME v8 (único cierre registral): `bffe94293b4c04fde4a3653414bf389a90def90c888100d135de359209a17abc`

**Único cambio respecto de v8:** el registro CF-37 incorpora los tres tipos
exigidos por CF-11/CF-35 que faltaban (`abierta_al_corte`, `orden_al_corte`,
`degradacion_de_cobertura`), con sus preimágenes y vectores. Nada más cambia.

Vigencia: permanecen CF-8/9/11/13/14/15/16/18/20/22..28/30/31 con las
completaciones de abajo; CF-33 queda REEMPLAZADA por CF-34; el corte
administrativo de CF-29 queda REEMPLAZADO por CF-35; se agregan CF-36 y
CF-37. El `contrato_hash` será el SHA-256 de este archivo al declararse
CONFORME.

---

## CF-34. Temporalidad triple y heads duales (reemplaza CF-33; completa CF-32; cierra B-1)

Todo evento de dominio lleva TRES timestamps con semántica congelada:

- `effective_at` = `T` del evento/modelo (tiempo de mercado del lote).
- `finalized_at` = timestamp de MERCADO que hizo finalizable el lote:
  `T` si el lote estaba completo; el `detected_at` del marcador (máximo de la
  prueba, CF-36) si esperó watermark. **La latencia científica determinista es
  `finalized_at − effective_at`** y su distribución se reporta en la
  evaluación.
- `processed_at` = timestamp OBSERVADO (reloj del ciclo/pull) en que el motor
  materializó el evento. Solo telemetría operacional: **no participa en IDs,
  decisiones, ni en ningún cálculo del modelo**, y se reporta aparte.

Heads duales en cada evento (completa CF-32):

- `input_head_asof_T` = último head consumible por el MODELO en
  `ahora = T` (velas con `t + dur ≤ T`; marcadores con `detected_at ≤ T`).
  Jamás contiene datos posteriores a `T`.
- `provenance_head_at_finality` = head del prefijo que INCLUYE el
  marcador/prueba que liberó el lote (el último registro con
  `detected_at ≤ finalized_at`). Demuestra por qué el lote se procesó, sin
  contaminar los inputs.

## CF-35. Corte administrativo total (reemplaza el corte administrativo de CF-29; cierra B-2)

Si el reloj de un ciclo de ingestión supera `T_corte + 86_400_000 ms` y **no
existe ningún lote global FINALIZADO con `T > T_corte`** — haya o no velas
parciales posteriores — se ejecuta el cierre administrativo:

- NO se procesan retroactivamente lotes incompletos;
- el estado congelado es el del último lote global finalizado `≤ T_corte`;
- `abierta_al_corte`/`orden_al_corte` se registran respecto de ESE estado;
- las velas parciales posteriores quedan FUERA de la cohorte y se reportan
  como `degradacion_de_cobertura` (mercados y rangos faltantes detallados);
- el evento `corte_administrativo` conserva la evidencia: reloj del pull,
  último lote finalizado, y la lista de mercados sin datos suficientes.

Esto hace TOTAL la regla de parada: cubre silencio completo y parcial (1–3
mercados activos sin quorum) sin cambiar Q=4 y sin inventar datos.

## CF-36. Prueba probatoria unívoca (completa CF-29/CF-31; clarificación M-1)

- **Prueba local:** los TRES PRIMEROS `close_time` cronológicos del propio
  mercado que satisfacen el watermark. `detected_at = max(prueba)`.
- **Prueba exchange:** objeto con los **Q = 4 mercados calificantes en orden
  alfabético** (si califican más de 4, los 4 primeros alfabéticos), cada uno
  con sus TRES `close_time` exactos requeridos:
  `"prueba":{"MERCADO":[t1,t2,t3],…}`. `detected_at` = máximo de toda la
  estructura. El marcador y su `hash_acum` cubren la estructura completa.
- **Vector dorado del marcador exchange** (mismo hueco de CF-31, tras `h2`):
  - `ser(gap_exchange) = {"desde":1646094600000,"gap":true,"hasta":1646094600000,"motivo":"exchange","prueba":{"ADAUSDT":[1646095500000,1646096400000,1646097300000],"BNBUSDT":[1646095500000,1646096400000,1646097300000],"ETHUSDT":[1646095500000,1646096400000,1646097300000],"SOLUSDT":[1646095500000,1646096400000,1646097300000]}}`
  - `hg_ex = 96da3e96173407b2baf6a2880feb0926eff25a34c6865c09263f11daee6c74c8`
- Los vectores del marcador local (CF-31) permanecen vigentes sin cambio.

## CF-37. Registro cerrado de tipos de evento (clarificación M-2)

El ledger admite EXCLUSIVAMENTE los tipos de este registro versionado.
Agregar/modificar un tipo = protocolo v9. `event_id` = SHA-256 de la preimagen
canónica CF-9 de su familia:

| Familia | Tipos | Preimagen |
|---|---|---|
| Jerarquía de trade | `candidato`, `orden_creada`, `orden_cancelada`, `fill`, `cerrado`, `trayectoria_indeterminada`, `gap_ambiguo`, `confirmada_sin_fill`, `descartada_por_arbitraje`, `abierta_al_corte` (id = trade), `orden_al_corte` (id = order) | `{"contrato","id"(candidate/order/trade según etapa),"tipo"}` |
| Descarte con zona | `descarte` | `{"contrato","mercado","motivo","t","tipo","zona_avail","zona_hi","zona_lo"}` |
| Abstención sin zona | `abstencion` (motivos: `rango_sin_origen`, `historia_insuficiente`, `sin_weak_cerrado`, `direccion_expirada`, `direccion_desconocida`, `epoca_no_habilitada`) | `{"contrato","mercado","motivo","t","tipo"}` |
| Global de barrera | `lote_finalizado`, `frontera`, `corte_administrativo` | `{"contrato","t","tipo"}` |
| Estructural por mercado | `estado_inicial`, `epoca_m15`, `mercado_degradado`, `mercado_reingresado` | `{"contrato","mercado","t","tipo"}` |
| Nacimiento | `nacimiento` | `{"contrato","mercado","t","tf","tipo"}` |
| Hueco (reflejo en ledger) | `hueco_detectado` | `{"contrato","desde","hasta","mercado","tf","tipo"}` |
| Cobertura al corte | `degradacion_de_cobertura` | `{"contrato","desde","hasta","mercado","tipo"}` |
| Incidencia de ingestión | `vela_revisada`, `vela_no_incorporada` | CF-26 |

- **Vectores dorados adicionales** (contrato de prueba `"0"×64`):
  - `abstencion(BTCUSDT, rango_sin_origen, t=1646095500000)` → `6b2e5a76e2885234507e9e5cef10afbfadd648a0ebdd2b997fd453b5d7b2dedc`
  - `mercado_degradado(BTCUSDT, t=1646095500000)` → `d47fcb9946fb0a1ca935f7b5cb2692d95223aad144194f166d7976911d586193`
  - `abierta_al_corte(trade_id="1"×64)` → `58eb9ddb2112318a25eeb6bd8b1b04ed91567c5bac47032c5d97a223e2b1a663`
  - `orden_al_corte(order_id="2"×64)` → `563f3df291d78971685c0e81c81fe1de8060074e51634157398436e83b059256`
  - `degradacion_de_cobertura(BTCUSDT, desde=1798761600000, hasta=1798848000000)` → `34e0260c4a798204be97656d876f347967e3de0cf3bd9ddf8566d81771afdde9`
- **Gate:** la matriz de crash (CF-30) debe recorrer al menos un ejemplar de
  CADA familia de este registro.

---

## Parámetros congelados (consolidado; `[U0]` salvo nota)

| Parámetro | Valor |
|---|---|
| Universo (orden canónico) | ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT |
| GENESIS_H4 | 2022-03-01T00:00:00Z (`1646092800000`), época única continua |
| Ancla M15 | menor `t` del snapshot versionado del commit de despliegue (CF-28) |
| Épocas M15 | segmentos maximales; habilitación ≥200 velas |
| Watermark local | N = 3 cierres propios posteriores (prueba CF-36) |
| Watermark exchange | Q = 4 mercados de referencia × 3 cierres (prueba CF-36) |
| Cierre administrativo | sin lote global finalizado > `T_corte` a reloj `T_corte`+24 h (CF-35) |
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
| Corte | 50 cierres totales (≥8 semanas ISO) o `1798761599999` ms |
| Bootstrap estadístico | semanas ISO, 10.000 réplicas, semilla 20260817, IC 95% |
| Q numérico | `round(x, 6)` float64 half-even (vectores CF-15) |
| Almacén | shortest-repr + cadena con marcadores probatorios (vectores CF-31/CF-36) |
| Temporalidad | `effective_at`/`finalized_at`/`processed_at` (CF-34) |

## Reglas de vigencia

1. CANDIDATO: se congela como v9 definitivo con la conformidad de Codex; su
   SHA-256 pasa a ser `contrato_hash`. Cambio posterior = v10 + cohorte nueva.
2. Gates de implementación: los de v7 más — latencia `finalized_at −
   effective_at` con vector de lote retrasado 45 min; heads duales por evento
   (input as-of vs provenance de finalidad) con vector de catch-up; corte
   administrativo con 1–3 mercados activos (vector de caída parcial); prueba
   exchange con mercados de referencia con gaps propios (selección alfabética
   determinista); matriz de crash cubriendo cada familia de CF-37.
3. Frontera forward según CF-21/CF-24. Bot3.v1 SUSPENDIDO; nada de v1..v7 se
   reutiliza como evidencia. Resultado positivo NO autoriza Bot/Testnet/Live.
4. Evaluación ÚNICA al corte; octubre es checkpoint informativo. La cohorte es
   descriptiva: la latencia determinista reportada (CF-34) acota — no
   acredita — ejecutabilidad en tiempo real.

## Secuencia restante

Conformidad final de Codex (pasada acotada: los tres tipos, sus vectores y
los cuatro gates operacionales documentados) → congelamiento v9
(hash = contrato_hash) → implementación (paso 5) →
re-auditoría completa (paso 6) → despliegue verificado (paso 7) → cohorte
desde cero (paso 8).
