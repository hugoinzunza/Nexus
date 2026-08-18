# Bot3.v7 — Protocolo pre-registrado CANDIDATO (submodelo single-entry H4→M15)

**Fecha:** 2026-08-17
**Estado:** `CANDIDATO / NO IMPLEMENTADO / PENDIENTE CONFORMIDAD CODEX`
**Antecedentes incorporados por referencia (prevalece este texto):**
- Diseño rev.3: `5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`
- Protocolo v2: `ef267f23583d4a36eca46bacb4f51fabdaaecf81955ebb5d079f0aee083998ea`
- Protocolo v3: `5688f4cf4b073c26533810baa0d45658fe5eddf008907dc50977173057c9be70`
- Protocolo v4: `6210e5bb578e2af2569b1041538f53acbccee9eb1b0dae388fdd9f832b79cf67`
- Protocolo v5: `d5504d5029139f6a2c99e1de6a89c96a02afd69bb360e2e57113938f57465979`
- Protocolo v6: `a342cd100d94482326fff31f5160e99e7131ae919f4681eff47339bbcd1cd393`
- Informe NO CONFORME v6: `12fc534c7fc0cb0ca49d4133edc86426a0fdaa11165499c860f87a39e8ce7828`

Vigencia: CF-8/9/11/13/14/15/16/18/20/23/24/25/26/27 permanecen con las
COMPLETACIONES de abajo; de CF-22 permanece todo salvo el ancla M15
(reemplazada por CF-28) y el marcador (ampliado por CF-31); se agregan
CF-28..CF-33. El `contrato_hash` será el SHA-256 de este archivo al
declararse CONFORME.

---

## CF-28. Nacimiento M15 desde snapshot versionado (reemplaza el ancla de CF-22; cierra B-1)

- El bootstrap de un mercado está PROHIBIDO hasta cargar y verificar el
  **snapshot versionado canónico**: el archivo `data/klines_<MERCADO>_15m.json`
  del repositorio en el **commit git registrado en el evento de despliegue**
  (el commit queda en la provenance del evento `nacimiento`).
- **Ancla M15** = menor `t` de ese snapshot. El almacén M15 nace ahí,
  ingiriendo primero el snapshot completo (con watermark CF-22) y después las
  demás fuentes.
- Snapshot no disponible, ilegible o sin cobertura del ancla →
  `historia_insuficiente`. **Prohibido nacer desde el push VPS.** Dos
  instalaciones con el mismo commit ancla idéntico por construcción.
- Evento `nacimiento` (por mercado/TF): registra ancla, commit del snapshot,
  SHA-256 del archivo snapshot y `hash_acum` inicial.

## CF-29. Silencio total: watermark global de exchange (cierra B-2)

- **Conjunto de referencia** del mercado X = los otros 6 mercados del
  universo. Si el mercado X (con época habilitada) no tiene vela ni marcador
  para el lote `T`, y **≥Q = 4** `[U0]` mercados de referencia tienen
  appendeadas velas con `close_time ≥ T + 3×900000` (tres cierres M15
  posteriores sincronizados, timestamps de mercado), se declara
  **hueco por silencio** para X: marcador CF-31 con `motivo = "exchange"`,
  `desde = T`, `hasta` = el último cierre faltante consecutivo bajo la misma
  evidencia. El mercado X pasa a estado `degradado`: sin candidatos ni
  órdenes nuevas; su reingreso exige época M15 nueva (≥200 velas, CF-13).
- **Exchange completo sin datos** (ningún mercado alcanza evidencia): el
  motor ESPERA — se declara expresamente que en ese estado ni los lotes ni el
  corte progresan con timestamps de mercado.
- **Corte sin lote posterior:** única excepción de reloj de pared, declarada:
  si el reloj del sistema en un ciclo de ingestión supera
  `T_corte + 86_400_000 ms` (24 h) y no existe ninguna vela con
  `close_time > T_corte`, el experimento se cierra administrativamente
  (evento `corte_administrativo`, con el reloj del pull como evidencia
  explícita) registrando `abierta_al_corte`/`orden_al_corte` con el último
  estado elegible.

## CF-30. `event_id` universal y dedupe contra el ledger (cierra B-3)

- TODO evento del ledger tiene `event_id` = SHA-256 hex minúscula de su
  **preimagen normativa** (JSON canónico CF-9). Eventos con jerarquía CF-9
  usan `{"contrato","id_jerarquia","tipo"}` (id = candidate/order/trade según
  la etapa). Eventos sin jerarquía:
  - `lote_finalizado`: `{"contrato":"…","t":<T>,"tipo":"lote_finalizado"}`
  - `frontera`: `{"contrato":"…","t":<T_frontera>,"tipo":"frontera"}`
  - `estado_inicial`: `{"contrato":"…","mercado":"…","t":<T_frontera>,"tipo":"estado_inicial"}`
  - `epoca_m15`: `{"contrato":"…","mercado":"…","t":<t_inicio>,"tipo":"epoca_m15"}`
  - `nacimiento`: `{"contrato":"…","mercado":"…","t":<ancla>,"tf":"…","tipo":"nacimiento"}`
  - `corte_administrativo`: `{"contrato":"…","t":<T_corte>,"tipo":"corte_administrativo"}`
  - descartes/abstenciones sin candidato: `{"contrato":"…","mercado":"…",`
    `"motivo":"…","t":<lote>,"tipo":"descarte","zona_avail":<ms>,`
    `"zona_hi":"<%.6f>","zona_lo":"<%.6f>"}`
- **Dedupe contra el ledger ya ESCRITO**: antes de appendear, el motor
  verifica el `event_id` releyendo el ledger (nunca solo memoria o índices
  auxiliares). Tras un crash en cualquier punto (incluido entre el último
  evento de mercado y la barrera), el reproceso re-deriva los mismos
  `event_id` y el dedupe hace la escritura idempotente.
- **Vectores dorados** (con `contrato = "0"×64` de prueba):
  - `lote_finalizado(t=1646095500000)` → `bfed95caa6bfad87697f8cc4cca1580c62f1b6fc3061b6abeebef27b07bd5c6b`
  - `frontera(t=1646092800000)` → `84bb23de88c477538fce49333da5a2ae02ae52084056e7541f4fcba10aff991e`
  - `estado_inicial(BTCUSDT, t=1646092800000)` → `c1692c949f95513f360605929de6f8058cc850c94d348aceaa5d128a7d002f6e`
  - `epoca_m15(BTCUSDT, t=1646092800000)` → `b63500ccf34c2889b4c88121daaa0248324473163862da78a88adb06051a13de`
- **Gate:** matriz de crash con un punto de caída entre cada par de eventos
  consecutivos de un lote (incluida la barrera) → el ledger final es idéntico
  byte a byte en todos los casos.

## CF-31. Marcador de hueco con evidencia probatoria (amplía CF-22; cierra M-1)

- El marcador canónico pasa a:
  `{"desde":<ms>,"gap":true,"hasta":<ms>,"motivo":"local"|"exchange",`
  `"prueba":[t1,t2,t3]}` con `prueba` = los `close_time` de mercado
  ordenados que completaron el watermark (del propio mercado si `local`; del
  conjunto de referencia si `exchange`). `detected_at ≡ max(prueba)`, ahora
  derivable del almacén y cubierto por `hash_acum`.
- **Vectores dorados actualizados** (mismas velas c1/c2/c3 de CF-17; falta
  `t=1646094600000`; `prueba=[1646096400000,1646097300000,1646098200000]`):
  - `ser(gap) = {"desde":1646094600000,"gap":true,"hasta":1646094600000,"motivo":"local","prueba":[1646096400000,1646097300000,1646098200000]}`
  - `h1 = 7bceed811ed9f3d848f5139114b9c8b04ea50b46347f6de61d11291bec1271e7`
  - `h2 = 5d84537de5783432781eeadecdf86759d26abc93bbbdff158b7a9832161df6cf`
  - `hg = 2d649fd44e2e7e77905473a29b6edc93082865829c90f6ec904614ee48ea9317`
  - `h3 = 157837865ad4abb014e2c3c3ec3ca133965c4ac3ebccf8840813a8827b0d95d9`

## CF-32. Head causal por prefijo en catch-up (completa CF-25; cierra M-2)

- El head que porta un evento con `ahora = T` es el `hash_acum` del ÚLTIMO
  registro del almacén **consumible en T**: velas con `t + dur ≤ T`;
  marcadores con `max(prueba) ≤ T`. NUNCA el head físico del archivo (que en
  catch-up ya contiene velas de lotes posteriores).
- **Gate:** vector con un hueco y cuatro lotes liberados en catch-up → cada
  evento porta un head distinto y causal; ninguno porta el head físico final.

## CF-33. `processed_at` y latencia declarada (cierra M-3)

- Todo evento de dominio lleva además `processed_at` = `close_time` del lote
  en curso cuando el motor lo emite. Al día, `processed_at = effective_at`;
  en catch-up, `processed_at > effective_at`.
- La evaluación REPORTA la distribución de `processed_at − effective_at`
  (latencia de liberación). La cohorte se rotula como estudio DESCRIPTIVO del
  submodelo: no acredita ejecutabilidad en tiempo real sin evidencia
  adicional, y esa limitación queda pre-registrada aquí.

---

## Parámetros congelados (consolidado; `[U0]` salvo nota)

| Parámetro | Valor |
|---|---|
| Universo (orden canónico) | ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT |
| GENESIS_H4 | 2022-03-01T00:00:00Z (`1646092800000`), época única continua |
| Ancla M15 | menor `t` del snapshot versionado del commit de despliegue (CF-28) |
| Épocas M15 | segmentos maximales; habilitación ≥200 velas |
| Watermark local | N = 3 cierres de mercado posteriores distintos |
| Watermark exchange | Q = 4 mercados de referencia con 3 cierres sincronizados |
| Cierre administrativo | reloj de pull > `T_corte` + 24 h sin velas posteriores |
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
| Q | `round(x, 6)` float64 half-even (vectores CF-15) |
| Almacén | shortest-repr + cadena con marcador probatorio (vectores CF-31) |

## Reglas de vigencia

1. CANDIDATO: se congela como v7 definitivo solo con conformidad de Codex; su
   SHA-256 pasa a ser `contrato_hash`. Cambio posterior = v8 + cohorte nueva.
2. Gates de implementación: los de v6 más — nacimiento desde snapshot con
   commit fijado (dos instalaciones, mismo ancla), silencio total con
   watermark de exchange (mercado degradado y reingreso por época nueva),
   matriz de crash por punto de caída (CF-30), heads de prefijo en catch-up
   (CF-32) y `processed_at` con latencia reportada (CF-33). Vectores CF-15,
   CF-30 y CF-31 exactos.
3. Frontera forward según CF-21/CF-24. Bot3.v1 SUSPENDIDO; nada de v1..v6 se
   reutiliza como evidencia. Resultado positivo NO autoriza Bot/Testnet/Live.
4. Evaluación ÚNICA al corte; octubre es checkpoint informativo. La cohorte
   es descriptiva (CF-33): no acredita ejecutabilidad en tiempo real.

## Secuencia restante

Conformidad Codex → congelamiento v7 (hash = contrato_hash) → implementación
(paso 5) → re-auditoría completa (paso 6) → despliegue verificado (paso 7) →
cohorte desde cero (paso 8).
