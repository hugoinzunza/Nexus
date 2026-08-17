# Bot3.v4 — Protocolo pre-registrado CANDIDATO (submodelo single-entry H4→M15)

**Fecha:** 2026-08-17
**Estado:** `CANDIDATO / NO IMPLEMENTADO / PENDIENTE CONFORMIDAD CODEX`
**Antecedentes incorporados por referencia (prevalece este texto):**
- Diseño rev.3: SHA-256 `5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`
- Protocolo v2 (CF-1..CF-5): SHA-256 `ef267f23583d4a36eca46bacb4f51fabdaaecf81955ebb5d079f0aee083998ea`
- Protocolo v3 candidato (CF-6..CF-11): SHA-256 `5688f4cf4b073c26533810baa0d45658fe5eddf008907dc50977173057c9be70`
- Informe NO CONFORME v3: SHA-256 `a60b3a708c5b7eec2eb5bfb46de4fceaa7c89b06cfbcc1c6941dac39c10020ec`

De v3 permanecen vigentes CF-8 (funding causal), CF-9 (serialización de
identidades) y CF-11 (corte temporal), declaradas conformes. CF-6, CF-7 y
CF-10 quedan REEMPLAZADAS por las cláusulas siguientes; se agregan CF-12 a
CF-14. El `contrato_hash` será el SHA-256 de este archivo al declararse
CONFORME.

---

## CF-12. Almacén canónico de velas: append-only, sellado y con hash encadenado (cierra M-1 y funda CF-13)

- **Almacén por mercado/TF** (`data/bot3_store/<MERCADO>_<TF>.jsonl`): cada
  línea = una vela cerrada `{t,o,h,l,c,v}` + `hash_acum` = SHA-256 hex
  minúscula de (`hash_acum` anterior ‖ serialización canónica CF-9 de la
  vela). Primera línea usa `hash_acum` previo = `contrato_hash`.
- **First-write-wins:** una vela con `t` ya escrito NUNCA se reescribe. Si la
  fuente (versionado o push VPS) entrega después un contenido distinto para
  un `t` existente, se registra `vela_revisada` en el ledger y el contenido
  nuevo se IGNORA para todo cálculo.
- **Sello:** al procesar la vela M15 `m`, el almacén queda sellado hasta
  `close_time(m)` en ese mercado (M15 y H4). Un backfill (vela faltante) solo
  es válido si su `t` es posterior al último sello; un hueco sellado queda
  permanente y se maneja por épocas (CF-13).
- **Provenance reconstruible:** todo evento del ledger incluye el `hash_acum`
  del último registro H4 y M15 consumido. El libro completo es reconstruible
  bit a bit desde el almacén + este protocolo.

## CF-13. Génesis, épocas y cobertura (reemplaza CF-6; cierra B-1)

- **H4:** el estado estructural H4 se computa sobre la ÉPOCA ÚNICA
  `[GENESIS_H4 = 2022-03-01T00:00:00Z (1646092800000), ahora]` del almacén,
  exigiendo continuidad TOTAL (diferencias de `t` exactamente = 4 h). La
  "ruptura opuesta previa" se busca en toda la época. Hueco H4 no
  backfilleable antes del sello → el mercado queda `historia_insuficiente`
  (sin candidatos nuevos) mientras el hueco exista dentro de la época — sin
  excepciones ni ventanas alternativas. El gate de 1000 velas H4 desaparece
  como sustituto: la cobertura ES desde génesis.
- **M15:** no hay génesis fijo; hay **ÉPOCAS**: segmentos maximales continuos
  del almacén M15. Todo estado M15 (pivotes, liquidez, iBOS, zonas derivadas,
  deadline) se computa EXCLUSIVAMENTE dentro de la época que contiene a `m`,
  desde su primera vela; ningún objeto M15 cruza un hueco. Una época habilita
  candidatos cuando acumula ≥200 velas (`epoca_m15` con su `t` inicial se
  registra en el ledger al habilitarse). Órdenes/posiciones vivas al empezar
  un hueco M15: la orden se cancela (`orden_cancelada(hueco_m15)`); la
  posición persiste y se gestiona desde la primera vela de la época
  siguiente (funding se devenga por CF-8 usando las velas existentes; los
  devengos cuyo `k` cae dentro del hueco se devengan con `C_k` = cierre de la
  última vela M15 sellada anterior a `k`, registrados como
  `funding_en_hueco`).
- Dos implementaciones que lean el mismo almacén obtienen por construcción
  las mismas épocas y el mismo estado: la dependencia de "cuánta historia se
  carga" queda eliminada de raíz.

## CF-14. Ciclo de vela: cálculo puro, luego aplicación (reemplaza CF-7; cierra B-2 y B-3)

Estados: `flat` → `orden_viva` → `posicion` (+ transitorio normativo
`salida_detectada`). Para cada vela M15 `m` (todo ejecutado a su cierre):

- **Fase 1 — intravela:**
  a) `posicion`: determinar precio/motivo de salida (CF-2; gap-SL → gap-TP →
     SL → TP; SL∧TP = STOP) → estado `salida_detectada` (NO se emite
     `cerrado` todavía).
  b) `orden_viva`: fill (§4.5 v2; `gap_ambiguo` primero). El fill es firme:
     nada posterior de esta vela lo revierte.
- **Fase 2 — cálculo puro de cierre (sin aplicar):** con el estado previo +
  velas del almacén con `close_time ≤ close_time(m)`: BOS/iBOS, zonas,
  rango, fractal, dirección_nueva, expiraciones (dirección, TTL, deadline).
- **Fase 3 — funding:** devengos con `k ≤ close_time(m)` (CF-8), incluidos
  los de una `salida_detectada` de esta vela.
- **Fase 4 — consolidación de cierres:** para cada `salida_detectada`,
  calcular PnL/R definitivo (CF-4 + CF-15) con TODOS los costos ya
  devengados y appendear el ÚNICO evento `cerrado`. Estado → `flat`.
- **Fase 5 — cancelaciones:** aplicar sobre `orden_viva` usando el estado de
  la Fase 2 (dirección_nueva incluida): deadline vencido sin fill,
  cambio/expiración de dirección, hueco M15 → `orden_cancelada(motivo)`.
  No retroactividad: jamás afecta fills (F1b) ni cierres (F4) de esta vela.
- **Fase 6 — aplicar estado estructural** calculado en Fase 2.
- **Fase 7 — toques, arbitraje y creación de orden** (solo `flat`;
  `idx_alta = m`, elegible desde `m+1`).
- **Fase 8 — chequeo de corte** (CF-11), después de registrar los cierres de
  esta vela.

## CF-15. Raw vs Q campo por campo + vectores dorados (reemplaza CF-10; cierra M-2)

`Q(x) ≡ round(x, 6)` de IEEE-754 float64 (semántica de Python 3: half-even
sobre el valor binario real). Es el ÚNICO operador de cuantización.

| Campo | Regla |
|---|---|
| OHLC del almacén | crudos en desigualdades intravela |
| Niveles al crearse (`E`, `T`, `S`, `lo/hi` de zonas, fib50, EQ, pools) | `Q` en su creación; gobiernan comparaciones, arbitraje, filtro RR e IDs |
| `P_in` con fill a `E` | `= E` (ya Q) |
| `P_in` con fill al open | `= Q(o[m])` |
| Base de salida (S, T, u open con gap) | `base_Q = Q(base)` |
| `P_out` STOP | `= Q(base_Q × (1 − 0.0005))` largo / `Q(base_Q × (1 + 0.0005))` corto |
| `P_out` TP | `= base_Q` |
| `C_k` | `= Q(cierre de la vela del devengo)` |
| fees y funding | float64 sobre los valores Q anteriores, SIN redondeo |
| PnL, R | float64 sin redondeo intermedio; reporte final `round(R, 4)` |
| `fill_precio` en `trade_id` | `%.6f` de `P_in` |

**Vectores dorados congelados** (gate de aceptación; cualquier desviación =
implementación rechazada):

- Cuantización: `Q(1.0000005)=1.000001` · `Q(1.0000015)=1.000001` ·
  `Q(99.0009)=99.000900` · `Q(2.3456785)=2.345678` (float64 real, no
  intuición decimal).
- **Vector A** (largo; fill favorable al open; TP con gap; 1 devengo):
  extremo=99.10 → `S=99.000900`; `E=100.000000`; `T=105.000000`;
  `o_fill=99.95` → `P_in=99.950000`; open de salida 105.40 →
  `P_out=105.400000`; `C_k=101.230000` → funding=0.010123;
  fee_in=0.019990; fee_out=0.021080; PnL_neto=5.398807;
  `|E−S|=0.999100` → **R reportado = 5.4037**.
- **Vector B** (largo; fill a E; gap-SL; sin funding): `E=100.000000`,
  extremo=99.00 → `S=98.901000`; open de salida 98.70 → base_Q=98.700000 →
  `P_out=98.650650`; fee_out=0.049325325; PnL_neto=−1.418675325;
  `|E−S|=1.099000` → **R reportado = −1.2909**.
- **Vector C** (corto; fill al open; STOP normal): `E=200.000000`,
  extremo=202.00 → `S=202.202000`; `o[m]=200.5 ≥ E` → `P_in=200.500000`;
  `P_out=Q(202.202×1.0005)=202.303101`; PnL_neto=−1.94435255…;
  `|E−S|=2.202000` → **R reportado = −0.8830**.

## CF-16. Reloj normativo `ahora` (cierra M-3)

- **Replay/backtest:** `ahora ≡ close_time(m)` de la vela M15 en proceso.
  Solo son elegibles velas H4 con `close_time_H4 ≤ ahora`. Prohibido usar
  reloj de pared o "todas las velas cargadas".
- **Vivo:** el motor procesa, en orden, cada vela M15 del almacén con
  `close_time ≤ reloj_sistema del pull`; para cada una rige el mismo
  `ahora ≡ close_time(m)`.
- **Gate:** replay sobre el almacén sellado y ejecución en vivo deben
  producir libros idénticos (mismo `hash_acum` consumido → mismos eventos).

---

## Parámetros congelados (consolidado; `[U0]` salvo nota)

| Parámetro | Valor |
|---|---|
| Universo | ADA, BNB, BTC, DOGE, ETH, SOL, XRP (USDT-PERP, Binance) |
| GENESIS_H4 | 2022-03-01T00:00:00Z (`1646092800000`), época única continua |
| Épocas M15 | segmentos maximales del almacén; habilitación ≥200 velas |
| Fila del curso | zona H4 → confirmación M15 (única) |
| STRUCT_PIV / INT_PIV | 8 / 3 |
| Expiración dirección H4 | 180 velas H4 |
| TTL zona H4 | 180 velas H4 desde `available_at` |
| Deadline total toque→fill | 64 velas M15 |
| Ventana iBOS | ≤48 velas M15 desde el toque |
| Buffer SL | `S_long=Q(extremo×0.999)` / `S_short=Q(extremo×1.001)` |
| RR neto mínimo (a priori) | 2,0 |
| Fees | maker 0,02% · taker 0,05% |
| Slippage STOP | 0,05% (aplicado según CF-15) |
| Funding | 0,01% por devengo (CF-8; huecos según CF-13) |
| Corte | 50 cierres totales (≥8 semanas ISO) o `1798761599999` ms incl. |
| Bootstrap | semanas ISO, 10.000 réplicas, semilla 20260817, IC 95% |
| Q | `round(x, 6)` float64 half-even (vectores CF-15) |

## Reglas de vigencia

1. CANDIDATO: se congela como v4 definitivo solo con conformidad de Codex;
   su SHA-256 pasa a ser `contrato_hash`. Cambio posterior = v5 + cohorte
   nueva.
2. Gates de implementación: diseño rev.3 §11 + determinismo de génesis/épocas
   (dos profundidades de carga → mismo libro) + vectores dorados CF-15 +
   identidad replay≡vivo (CF-16) + almacén sellado sin reescrituras (CF-12).
3. Frontera forward = primer pull exitoso post-despliegue verificado.
4. Bot3.v1 SUSPENDIDO; nada de v1/v2/v3 se reutiliza como evidencia.
5. Resultado positivo NO autoriza Bot/Testnet/Live.
6. Evaluación ÚNICA al corte; octubre es checkpoint informativo.

## Secuencia restante

Conformidad Codex → congelamiento v4 (hash = contrato_hash) → implementación
(paso 5) → re-auditoría completa (paso 6) → despliegue verificado (paso 7) →
cohorte desde cero (paso 8).
