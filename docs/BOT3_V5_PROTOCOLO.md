# Bot3.v5 — Protocolo pre-registrado CANDIDATO (submodelo single-entry H4→M15)

**Fecha:** 2026-08-17
**Estado:** `CANDIDATO / NO IMPLEMENTADO / PENDIENTE CONFORMIDAD CODEX`
**Antecedentes incorporados por referencia (prevalece este texto):**
- Diseño rev.3: `5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`
- Protocolo v2 (CF-1..CF-5): `ef267f23583d4a36eca46bacb4f51fabdaaecf81955ebb5d079f0aee083998ea`
- Protocolo v3 (CF-8, CF-9, CF-11 vigentes): `5688f4cf4b073c26533810baa0d45658fe5eddf008907dc50977173057c9be70`
- Protocolo v4 (CF-13..CF-16 vigentes con las modificaciones de abajo): `6210e5bb578e2af2569b1041538f53acbccee9eb1b0dae388fdd9f832b79cf67`
- Informe NO CONFORME v4: `7260c166a6264ec94923fef45ea05a958078700fd54c558e39f7bf34cce16c49`

Vigencia de cláusulas: CF-8, CF-9, CF-11, CF-14, CF-15 y CF-16 permanecen;
CF-12 queda REEMPLAZADA por CF-17; CF-13 queda MODIFICADA por CF-18 (se
elimina `funding_en_hueco`); CF-11/CF-14 quedan integradas por CF-19 y
CF-20; se agrega CF-21. El `contrato_hash` será el SHA-256 de este archivo al
declararse CONFORME.

---

## CF-17. Almacén canónico: bytes, ingestión y fuentes unívocos (reemplaza CF-12; cierra B-1)

- **Serialización exacta de vela** (NO usa la regla Q de CF-9 — el hash cubre
  los CRUDOS que consume el motor): JSON canónico UTF-8, claves ordenadas,
  separadores `(",", ":")`, con `t` como entero ms y `o,h,l,c,v` como la
  **representación decimal más corta que hace round-trip al mismo float64**
  (algoritmo shortest-repr/Ryū; semántica de `repr` de Python 3):
  `{"c":"…","h":"…","l":"…","o":"…","t":<int>,"v":"…"}`.
- **Cadena:** `hash_acum(i) = SHA-256_hex( hash_acum(i−1) ‖ ser(vela_i) )`,
  donde `hash_acum(i−1)` se concatena como sus **64 caracteres ASCII hex
  minúscula** (no bytes crudos). Semilla del primer registro de cada
  mercado/TF: `hash_acum(0) = "0"×64`.
- **Orden de append:** estrictamente creciente por `t`. Una vela cuyo `t` sea
  ≤ al último appendeado NO se incorpora jamás (se registra
  `vela_no_incorporada`); los huecos resultantes se manejan por épocas
  (CF-18). No existe backfill dentro del segmento: sin reescritura, sin
  inserción.
- **Prioridad de fuentes (dedupe pre-append):** en cada ciclo de ingestión se
  toman todas las velas cerradas disponibles en orden de `t`; para un mismo
  `t`, prevalece SIEMPRE la fuente **versionada del repositorio** sobre el
  push VPS (la versionada es auditable por git). `first-write-wins` aplica
  después contra el almacén.
- **Revisiones:** contenido distinto para un `t` ya escrito → `vela_revisada`
  registrada, contenido ignorado, cadena intacta.
- **Vectores dorados de la cadena** (gate; semilla `"0"×64`):
  - `ser(c1) = {"c":"1.00000049","h":"2.5","l":"0.5","o":"1.0","t":1646092800000,"v":"123.456"}`
  - `ser(c2) = {"c":"1.0000004","h":"1.2","l":"0.9","o":"1.00000049","t":1646093700000,"v":"0.0"}`
    (nótese: `1.00000040` serializa `"1.0000004"` — los crudos son
    distinguibles; la incompatibilidad con Q queda eliminada)
  - `h1 = 7bceed811ed9f3d848f5139114b9c8b04ea50b46347f6de61d11291bec1271e7`
  - `h2 = 5d84537de5783432781eeadecdf86759d26abc93bbbdff158b7a9832161df6cf`
  - hueco (falta `t=1646094600000`) y luego
    `c3 = {t:1646095500000, o:1.1, h:1.3, l:1.05, c:1.25, v:10.0}` →
    `h3 = 982abd23a998eb0a628a23e6caf2b5a1732722277233694a798589f26dd38408`
  - revisión de `c2` con `c=1.00000041` → ignorada; la cadena permanece en
    `h3`.

## CF-18. Hueco M15 que intersecta una posición → `trayectoria_indeterminada` (modifica CF-13; cierra B-2)

- Si un hueco M15 comienza mientras existe una `posicion` (o una
  `salida_detectada` no consolidada), el trade termina **fail-closed** como
  `trayectoria_indeterminada`, con timestamp = `close_time` de la última vela
  sellada antes del hueco. Sin precio de salida imputado, sin funding del
  hueco, sin R. Se EXCLUYE del estadístico primario y se conserva íntegro en
  el ledger.
- `funding_en_hueco` queda ELIMINADO: ningún devengo usa un `C_k` de una vela
  distinta a la definida por CF-8. Los devengos cuyo `k` cae en el hueco no
  existen (el trade ya terminó como indeterminado).
- Órdenes vivas al empezar un hueco: `orden_cancelada(hueco_m15)` (vigente).
- Resolución posterior solo mediante una fuente causal externa congelada por
  un protocolo futuro; este protocolo NO la define ni la permite implícita.

## CF-19. Motor global por lotes de `close_time` y pre-gate de corte (integra CF-11/CF-14; cierra B-3)

- **Lotes:** el motor procesa los 7 mercados sincronizados por `close_time`
  M15 creciente. Para cada lote `T`: se ejecutan las Fases 1–7 de CF-14 de
  cada mercado en **orden alfabético de mercado** (ADAUSDT, BNBUSDT, BTCUSDT,
  DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT) — el orden solo afecta la secuencia de
  registros del ledger, nunca la inclusión — y al final del lote se ejecuta
  UNA sola Fase 8 global.
- **Cierres simultáneos:** TODOS los cierres del lote entran al ledger y al
  conteo aunque el total supere 50 (`n` final puede ser >50; se preserva la
  simultaneidad, sin truncado por orden de recorrido).
- **Pre-gate temporal:** si `T > T_corte (1798761599999)`, el lote NO ejecuta
  Fases 1–7 en ningún mercado. En ese instante se registran
  `abierta_al_corte` / `orden_al_corte` con el último estado elegible
  (lote anterior). El chequeo de Fase 8 evalúa el corte por muestra
  (50 cierres + ≥8 semanas ISO) al final de cada lote.

## CF-20. Transición explícita fill+STOP (cierra M-1)

En la Fase 1b, una `orden_viva` cuya vela de fill cumple además la condición
de STOP (§4.5 v2) transita DIRECTAMENTE `orden_viva → salida_detectada`
(fill y salida en la misma vela), sin pasar por `posicion` entre lotes. Por
CF-8 (`close_time(fill) < k` es falso) ese trade NO devenga funding en ese
cierre. Se consolida en la Fase 4 del mismo lote con su único evento
`cerrado`. Prohibido diferir el STOP a la vela siguiente.

## CF-21. Bootstrap sin emisión y primer `m` elegible (cierra M-2)

- **Fase de bootstrap (normativa):** al desplegar, el motor reconstruye el
  estado estructural (almacén, épocas, rangos, zonas, dirección, fractal)
  procesando la historia COMPLETA con las mismas reglas, pero en modo
  `bootstrap`: NO emite candidatos, órdenes, fills ni cierres al ledger
  evaluable, y termina con TODOS los mercados en estado `flat` (ninguna
  posición u orden "heredada" del pasado se materializa).
- **Frontera:** `T_frontera` = timestamp del primer pull exitoso posterior al
  despliegue verificado (registrado en el ledger como evento `frontera` con
  provenance completa).
- **Primer `m` elegible:** la primera vela M15 con
  `close_time > T_frontera`. Las velas del primer pull con
  `close_time ≤ T_frontera` solo alimentan estado (bootstrap).
- **Ledger evaluable:** solo admite eventos cuyo disparador (toque del
  candidato, creación de orden, fill, cierre) tenga
  `close_time > T_frontera`. Todo lo anterior es backtest y se reporta en un
  artefacto separado, nunca mezclado con la cohorte.

---

## Parámetros congelados (consolidado; `[U0]` salvo nota)

| Parámetro | Valor |
|---|---|
| Universo (orden canónico) | ADAUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, SOLUSDT, XRPUSDT |
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
| Slippage STOP | 0,05% (CF-15) |
| Funding | 0,01% por devengo (CF-8; sin imputaciones, CF-18) |
| Corte | 50 cierres totales (≥8 semanas ISO) o `1798761599999` ms, por lotes (CF-19) |
| Bootstrap estadístico | semanas ISO, 10.000 réplicas, semilla 20260817, IC 95% |
| Q | `round(x, 6)` float64 half-even (vectores CF-15) |
| Serialización almacén | shortest-repr float64 + cadena CF-17 (vectores CF-17) |

## Reglas de vigencia

1. CANDIDATO: se congela como v5 definitivo solo con conformidad de Codex; su
   SHA-256 pasa a ser `contrato_hash`. Cambio posterior = v6 + cohorte nueva.
2. Gates de implementación: diseño rev.3 §11 + determinismo génesis/épocas +
   vectores CF-15 y CF-17 + identidad replay≡vivo (CF-16) + almacén sin
   reescrituras (CF-17) + lotes globales deterministas (CF-19: permutar el
   orden de detección no cambia inclusión ni conteo) + bootstrap sin emisión
   (CF-21).
3. Frontera forward según CF-21. Bot3.v1 SUSPENDIDO; nada de v1..v4 se
   reutiliza como evidencia. Resultado positivo NO autoriza Bot/Testnet/Live.
4. Evaluación ÚNICA al corte; octubre es checkpoint informativo.

## Secuencia restante

Conformidad Codex → congelamiento v5 (hash = contrato_hash) → implementación
(paso 5) → re-auditoría completa (paso 6) → despliegue verificado (paso 7) →
cohorte desde cero (paso 8).
