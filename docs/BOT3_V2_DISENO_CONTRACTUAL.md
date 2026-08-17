# Bot3.v2 — diseño contractual (revisión 2, clarificaciones incorporadas)

**Fecha:** 2026-08-17 · **Estado:** `BORRADOR PARA FREEZE (rev. 2 tras
APPROVED WITH REQUIRED CLARIFICATIONS)` · **Copia canónica:** este archivo en
la rama `codex/command-center-contract-v1`; la copia de `main` es solo una
referencia y no debe editarse.

**Insumos:** `AUDITORIA_CURSO_BOT3_2026-08-17.md`, re-auditoría C-1 (PASS con
fix requerido), revisión del diseño (8 clarificaciones), playbook
`course-study.v1`, `CLAUDE_INDEPENDENT_REVIEW.md`.

Nada de aquí se implementa hasta el protocolo v2 pre-registrado con hash.
Ninguna métrica de v1 se reutiliza.

---

## 1. Objeto científico

**Submodelo causal single-entry H4→M15 del curso** (clarificación 7): zona de
interés del rector H4, confirmación completa en M15, UNA entrada por
oportunidad. NO es "la estrategia completa del curso": excluye deliberadamente
la regla docente universal de dos entradas (S08 00:52:30–00:53:53, amarilla en
el playbook por falta de especificación), break-even y parciales. Los
resultados se rotulan siempre como submodelo.

## 2. Contexto rector (H4) — fail closed

- **Rango causal**: strong SOLO con sweep verificable en su origen; weak
  cerrado SOLO tras finalización por swing + iBOS (S03). Sin ambos →
  abstención.
- **Dirección**: última ruptura H4 con cuerpo. `None`, conflicto o expiración
  → abstención.
- **Expiración de dirección**: 180 velas H4 sin BOS de continuación, o
  invalidación del rango origen por cierre H4. `[U0 — decisión operacional,
  no enseñada]`

## 3. Selección de zona (H4)

OB o FVG del rector H4 con: disponibilidad causal, frescura contractual (cero
toques entre `available_at` y el toque de entrada), lado correcto vs EQ del
rango rector, y gate de fractal H4 ≥50%. `liq_delante`/`trampa` se registran
sin vetar (alimentan HYP-BT-LIQ-EXT-001).

- **TTL de zona**: 180 velas H4 desde `available_at` `[U0]`. Justificación
  operacional (clarificación sobre el 500 original): una zona más antigua que
  la vigencia máxima de la dirección que la haría operable no puede producir
  entrada; TTL y expiración de dirección quedan alineados en 30 días.

## 4. Confirmación M15 y entrada (iBOS válido, S08)

**Deadline total: 64 velas M15 (16 h) desde el CIERRE de la vela del toque
H4** (clarificación 6). Todo lo siguiente debe completarse dentro de él:

1. **Toma de liquidez a la izquierda**: la pierna M15 que entra a la zona
   barrió con mecha ≥1 swing interno M15 previo (INT_PIV M15).
2. **iBOS M15 con cuerpo** en la dirección del trade, a más tardar 48 velas
   M15 tras el toque `[U0 — máximo inicial]`.
3. **Zona derivada** creada por el desplazamiento del iBOS.
4. **Orden límite** en el borde PROXIMAL de la zona derivada (el más cercano
   al precio), disponible desde el cierre de la vela que completa la zona
   derivada.
5. **Fill** (clarificación 1 — el midpoint queda eliminado): la orden se
   considera ejecutada solo si una vela M15 posterior CRUZA el nivel
   (largo: `low ≤ nivel`; corto: `high ≥ nivel`).
   - Precio de fill = nivel de la orden.
   - **Gap**: si la vela ABRE más allá del nivel a favor del fill, el fill es
     al OPEN de esa vela (nunca a un precio no transitado).
   - **Vela ambigua en la entrada** (cruza el nivel Y el SL en la misma vela
     M15): se asume fill + STOP en esa vela (conservador).
   - Sin cruce dentro del deadline → `confirmada_sin_fill` (registrada).

Invalidación (cierre M15 a través de la invalidación de la zona H4 antes del
iBOS) → descarte registrado con motivo.

## 5. Arbitraje determinista (clarificación 2)

Con candidatos simultáneos, gana exactamente uno y el resto se registra como
`descartada_por_arbitraje` con referencia al ganador:

- **Zonas H4 elegibles tocadas en la misma vela M15**: gana la de
  `available_at` más antiguo; empate → OB sobre FVG; empate → la de borde
  proximal más cercano al precio de cierre del toque; empate → la de menor
  precio `lo` (determinista final).
- **iBOS M15**: el PRIMERO (por índice de vela) que cumpla toma-izquierda.
- **Zona derivada**: el OB del desplazamiento; si no existe OB, el FVG más
  cercano al origen del desplazamiento; si hay varios FVG, el de
  `available_at` más antiguo.
- **Retest/fill**: el primer cruce (por índice de vela).
- **Posición única por mercado**: mientras hay posición u orden límite viva,
  ningún candidato nuevo entra a arbitraje (se registra
  `posición_u_orden_viva`).
- La orden límite viva se CANCELA si: vence el deadline total, la dirección
  rectora expira/cambia, o el SL implícito queda cruzado antes del fill.

## 6. Tabla de disponibilidad por evento (clarificación 3)

| Evento | `available_at` |
|---|---|
| Sweep del origen (H4) | cierre de la vela H4 cuya mecha barre |
| Strong del rango | cierre de la vela H4 del BOS con cuerpo que lo consagra |
| Weak cerrado | cierre de la vela H4 del iBOS de finalización |
| Dirección / BOS H4 | cierre de su vela H4 |
| Fractal ≥50% (gate) | cierre de la vela H4 cuya mecha/cuerpo alcanza el 50% |
| Zona H4 (OB/FVG) | cierre de la 3ª vela del FVG (H4) |
| Toque de zona H4 | cierre de la vela M15 del toque (las decisiones parten ahí) |
| Toma de liquidez izquierda | cierre de la vela M15 que barre |
| iBOS M15 | cierre de su vela M15 |
| Zona derivada | cierre de la vela M15 que la completa |
| Orden límite de entrada | = `available_at` de la zona derivada |
| Fill | intra-vela M15 posterior al alta de la orden (regla §4.5) |
| SL/TP | intra-vela; vela ambigua = STOP |
| Expiraciones (dirección, TTL, deadline) | contadas en CIERRES de su TF |

Regla general: **ningún evento es consumible antes de su `available_at`; nada
puede seleccionarse usando el final de la serie** (sin `[-N:]`: el
`MAX_ZONES_SIM` de v1 queda eliminado; los límites de cómputo son solo TTL y
deadlines causales).

## 7. Riesgo, objetivo y gestión

- **SL**: extremo de la reacción que originó el iBOS ± buffer 0,1% `[U0]`.
- **TP**: weak cerrado del rango rector H4. Sin weak cerrado → abstención.
- **Filtro**: RR neto ≥ 2 (compatible con S06, no umbral demostrado) con
  costos por mercado versionados (base 0,12% ida y vuelta `[U0]`; tabla por
  par en el protocolo).
- Salida completa en SL o TP; vela ambigua = STOP.

## 8. Cohorte forward: ledger append-only

- Recolector launchd en el Mac mini (`com.hugo.nexux-bot3-forward`), pull de
  `nexux.cl/m/bot3/api/book` cada 15 min, append a
  `crisol/nexux/data/bot3_forward/ledger.jsonl`:
  `trade_id` = hash(mercado, dir, `available_at` zona H4, vela de fill,
  contrato_hash); eventos `descubierto`/`cerrado`/`gap_detectado` inmutables;
  provenance (hash contrato, commit, fuente y `as_of` de velas, ts del pull).
- El simulador es VISTA reproducible; **la cohorte evaluable es el ledger**.
- **Frontera forward** = primer pull exitoso posterior al despliegue
  verificado de v2.

## 9. Evaluación (clarificación 4)

- **Primario (único):** el AGREGADO de los 7 mercados — se detiene en
  **50 cierres totales en el ledger o 2026-12-31**, lo primero. Una sola
  evaluación al detenerse; sin lecturas intermedias con valor decisional
  (octubre = checkpoint informativo del ecosistema, no corte).
- **Dependencia:** intervalos del agregado por bloques temporales (block
  bootstrap semanal) — operaciones simultáneas en pares correlacionados no se
  tratan como independientes.
- **Secundarios:** métricas por mercado, corregidas por multiplicidad (Holm),
  solo descriptivas.
- n bajo al corte → reporte con intervalos, sin promoción ni descarte;
  decidir extender o cerrar `insuficiente`.
- Resultado positivo NO autoriza Bot/Testnet/Live.

## 10. Parámetros a congelar (todos `[U0]` salvo indicación — clarificación 5)

Ninguno de estos valores fue enseñado en el curso; son decisiones
operacionales pre-registradas de este submodelo (baseline). El resultado
valida ESTA parametrización, no "el método docente abstracto".

| Parámetro | Propuesta rev.2 | Etiqueta |
|---|---|---|
| Expiración dirección H4 | 180 velas H4 (30 días) | U0 |
| TTL zona H4 | 180 velas H4 (alineado a la dirección) | U0 |
| Deadline total toque→fill | 64 velas M15 (16 h) | U0 |
| Ventana iBOS dentro del deadline | ≤48 velas M15 | U0 (máximo inicial) |
| Buffer SL | 0,1% | U0 |
| RR neto mínimo | 2,0 | compatible S06, no demostrado |
| Costos | 0,12% base + tabla por par | U0, versionados |
| Corte | 50 cierres TOTALES o 2026-12-31 | U0 |
| Universo | 7 pares USDT (pre-datos) | U0 |

## 11. Gates de aceptación de la implementación

1. Invariancia por prefijo sobre ventana real (≥2000 velas M15 BTC, >300
   zonas — la reproducción de la re-auditoría) + sintético con expulsión
   forzada: un trade cerrado que cambie = implementación rechazada.
2. Tests DISCRIMINANTES: la disponibilidad por apertura (bug C-1) debe hacer
   FALLAR el test correspondiente; `avail_t` con delta EXACTO por TF.
3. Determinismo de arbitraje: dos corridas y un reordenamiento de detección
   producen el mismo libro.
4. Ledger: reinicio del recolector sin duplicar `trade_id` ni reescribir.
5. Re-auditoría completa de Codex (paso 6) antes del despliegue.

---

**Pendiente para el freeze (decisión de Hugo):** aprobar la tabla del §10 y
las reglas de fill (§4.5) y arbitraje (§5). Con eso se escribe el protocolo
v2 pre-registrado (hash SHA-256 sobre el texto congelado) y recién entonces
se implementa.
