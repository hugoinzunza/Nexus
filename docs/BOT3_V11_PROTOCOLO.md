# Bot3.v11 — Protocolo pre-registrado CANDIDATO (ciclo del candidato, cerrado)

**Fecha:** 2026-08-17
**Estado:** `CANDIDATO / NO IMPLEMENTADO / PENDIENTE CONFORMIDAD ACOTADA`
**Base:** v9 CONFORME (`9d24166a33aa74af7f2b2dd7d0bdf4e2d16866e13eec7c48e7b1480512001530`).
**Antecedentes:** v10 candidato
(`8849dec79bd36fab1bb0f48d580ed6d12618de3ae559ea665e93cfeff35d03bd`,
NO CONFORME) y su informe de conformidad.

v11 reemplaza íntegramente a v10 (que no se edita). Alcance idéntico:
solo lo que el contrato debe cambiar para B-2 y el head causal. Todo v9
(CF-1..CF-37) permanece vigente salvo lo aquí indicado. B-3..B-6 siguen
siendo defectos de implementación, sin contrato nuevo.

---

## CF-38. Estados y FRONTERA candidato/orden (cierra hallazgo 1)

```text
flat → candidato_vivo → orden_viva → posicion → (salida_detectada) → flat
```

- **Frontera exacta:** el candidato TERMINA en el instante en que se crea la
  orden (CF-40, paso b). Desde ese cierre el mercado está en `orden_viva`.
- **Partición estricta de eventos** (ningún evento puede emitirse fuera de
  su estado):
  - en `candidato_vivo`: `candidato`, `candidato_invalidado`,
    `candidato_expirado`;
  - en `orden_viva`: `orden_creada`, `orden_cancelada`,
    `confirmada_sin_fill`, `gap_ambiguo`, `fill`;
  - en `posicion`/`salida_detectada`: `cerrado`,
    `trayectoria_indeterminada`, `abierta_al_corte`.
  Una orden creada NUNCA produce `candidato_expirado`; un candidato sin
  orden NUNCA produce `orden_cancelada`.
- La FRESCURA de la zona se consume en el TOQUE: un candidato muerto no
  devuelve la zona a fresca.
- Mientras el mercado no esté `flat`, no admite candidatos nuevos.

## CF-39. Cronología POST-TOQUE determinista (cierra hallazgos 2 y 3)

Sea `j_toque` la vela del toque. Todo ocurre **estrictamente después** de
`j_toque` y dentro del deadline total (64 velas M15 desde el cierre del
toque, inclusive). Definiciones únicas, sin cuantificadores existenciales:

1. **`j_toma` (toma de liquidez a la izquierda)** = la PRIMERA vela
   `k > j_toque` (orden cronológico) que BARRE (§6-bis) algún swing INT M15
   del lado correspondiente con `confirm_idx < k` (disponibilidad causal,
   M-3). Una vez fijado, `j_toma` no se recalcula.
2. **Par ganador (iBOS, zona derivada)** = el PRIMER par cronológicamente
   válido, recorriendo los eventos iBOS `e` con `j_e > j_toma` y
   `j_e ≤ j_toque + 48` en orden creciente de `j_e`, y quedándose con el
   primero que TENGA zona derivada (CF-39.3). Un iBOS sin zona derivada se
   descarta y el recorrido continúa con el siguiente; el candidato sigue
   vivo mientras queden velas dentro del deadline.
3. **Zona derivada** (regla del diseño rev.3, ahora normativa):
   - **Desplazamiento** = velas `[j_origen, j_ibos]`, donde `j_origen` es el
     `idx` del ÚLTIMO swing INT M15 del lado OPUESTO al trade con
     `confirm_idx ≤ j_ibos` e `idx < j_ibos`. Si no existe, no hay zona
     derivada para ese iBOS.
   - **OB del desplazamiento** = la ÚLTIMA vela de `[j_origen, j_ibos]` con
     cuerpo OPUESTO al trade (largo: `c < o`; corto: `c > o`); su caja es
     `[l, h]`. Si existe, ESA es la zona derivada.
   - **Fallback FVG**: si no hay vela de cuerpo opuesto, la zona derivada es
     el FVG de la dirección del trade con vela de formación en
     `(j_origen, j_ibos]` cuyo `idx` sea MÍNIMO (el más cercano al origen);
     empate → `available_at` más antiguo; empate → menor `lo`.
   - Si no hay OB ni FVG en el desplazamiento, ese iBOS no tiene zona
     derivada.
4. **Orden límite** en el borde proximal de la zona derivada, disponible
   desde el cierre de la vela que la completa.
5. **Fill** según §4.5 v2, dentro del deadline total.

SL y TP no cambian: SL = extremo de la reacción que originó el iBOS ±
buffer; TP = weak rector CERRADO.

## CF-40. Fase 7 desdoblada y su precedencia interna (cierra hallazgo 5)

La Fase 7 de CF-14 se desdobla. **Fase 7a** (solo si el estado es
`candidato_vivo`) se evalúa en ESTE orden normativo único:

- **a) Invalidación:** si el cierre M15 de esta vela atraviesa la
  invalidación de la zona H4 → `candidato_invalidado`; estado `flat`. FIN.
- **b) Orden:** si con las velas cerradas en `T` existe par ganador
  (CF-39.2) y su zona derivada se completó en `T` o antes → crear
  `orden_creada`; estado `orden_viva`. **El candidato terminó**: los pasos
  (c) y (d) NO se evalúan en esta vela. Una orden creada exactamente en la
  vela del deadline es válida; su fill solo puede ocurrir desde la vela
  siguiente, que ya excede el deadline → `confirmada_sin_fill`.
- **c) Deadline:** si `T ≥ close(j_toque) + 64·15m` → `candidato_expirado`
  (motivo `deadline`); estado `flat`.
- **d) Dirección/hueco:** si la dirección rectora vigente difiere de la del
  toque o expiró, o un hueco M15 intersecta al candidato →
  `candidato_expirado` (motivos `direccion` / `hueco_m15`); estado `flat`.

**Fase 7b** (solo si el mercado quedó `flat` tras 7a y no está degradado):
detectar toques, arbitrar y crear `candidato_vivo`. Nunca se crea una orden
en la misma vela del toque.

El resto de CF-14 (cálculo puro antes de aplicar, no retroactividad del
fill, funding antes del cierre único, lotes globales) no cambia.

## CF-41. Compromiso de contenido separado del head de conocimiento (cierra hallazgo 4)

Se REVIERTE el backdating propuesto en v10: un marcador de hueco solo se
conoce en `detected_at`, y adelantarlo sería conocimiento futuro. Cada
evento de dominio lleva TRES campos de almacén, con roles disjuntos:

| Campo | Definición | Rol |
|---|---|---|
| `input_head_asof_T` | último registro con velas `t+dur ≤ T` y marcadores `detected_at ≤ T` (regla v9, sin cambio) | qué estaba CONOCIDO en `T` |
| `input_commit_asof_T` | `hash_acum` del último registro de tipo VELA con `t+dur ≤ T` | qué bytes se CONSUMIERON (la cadena hasta esa vela incluye los marcadores intermedios) |
| `provenance_head_at_finality` | último registro con `detected_at ≤ finalized_at` (regla v9) | por qué el lote se LIBERÓ |

`input_commit_asof_T` identifica exactamente el conjunto de velas
consumidas —incluidas las posteriores a un hueco— sin afirmar que el hueco
fuera conocido antes de tiempo: es provenance, no conocimiento del modelo.
Con esto queda cerrada la sub-identificación declarada como hallazgo, sin
introducir look-ahead.

## CF-42. Ganador del arbitraje (M-3)

Todo evento `descartada_por_arbitraje` DEBE llevar `ganador` = el
`candidate_id` del candidato elegido en ese mismo lote. Sin ese campo el
evento es inválido.

## CF-43. Ampliación del registro CF-37

Dos tipos nuevos en la familia "jerarquía de trade"
(preimagen `{"contrato","id","tipo"}`, `id` = `candidate_id`):

| Tipo | Cuándo |
|---|---|
| `candidato_expirado` | deadline, dirección o hueco matan al candidato vivo |
| `candidato_invalidado` | cierre M15 a través de la invalidación de la zona H4 |

**Vectores dorados** (contrato `"0"×64`, `candidate_id = "3"×64`):

- `candidato_expirado` → `7cc8eda9b1b9f43a99634abd927ea881c2edb37197b6478a56600ec0945e59b8`
- `candidato_invalidado` → `8131681cbb2c46aab6489aadabb2b03e1ecd32c7cc52c7b3a3e140682da34c71`

---

## Gates adicionales de implementación (sobre los de v9)

1. **Cronología estricta:** un iBOS anterior o igual al toque NO produce
   orden; el primero posterior con zona derivada SÍ.
2. **Candidato multi-lote:** candidato nacido en `T` produce orden en
   `T + n·15m` (n ≥ 1); libro idéntico procesando lote a lote.
3. **iBOS sin zona derivada:** se descarta y el recorrido continúa con el
   siguiente iBOS dentro del deadline (vector con dos iBOS, el primero sin
   zona).
4. **Zona derivada:** el OB del desplazamiento gana sobre cualquier FVG; una
   zona anterior a `j_origen` nunca es derivada; fallback FVG por `idx`
   mínimo.
5. **Precedencia 7a:** vector donde la zona derivada se completa en la MISMA
   vela del deadline → se crea la orden (b) y NO se emite
   `candidato_expirado`; y su fill posterior da `confirmada_sin_fill`.
6. **Partición de eventos:** ningún `candidato_*` tras crear la orden;
   ningún `orden_*` sin orden.
7. **CF-41:** `input_commit_asof_T` identifica las velas post-hueco
   consumidas; `input_head_asof_T` NO adelanta el marcador.
8. **Sweep causal:** un swing con `confirm_idx ≥ k` no sirve como liquidez
   tomada por la vela `k`.
9. **Arbitraje:** todo `descartada_por_arbitraje` trae `ganador` válido.
10. Todos los gates de v9 siguen vigentes, incluidos los dos de B-1.

## Reglas de vigencia

1. CANDIDATO: se congela como v11 con la conformidad acotada; su SHA-256
   pasa a ser el nuevo `contrato_hash`. Cambio posterior = v12.
2. Cambiar `contrato_hash` cambia TODAS las identidades del ledger: v11 debe
   congelarse ANTES de implementar B-2; ningún libro previo se reutiliza.
3. B-3..B-6 se corrigen en implementación contra cláusulas v9 vigentes.
4. Bot3.v1 SUSPENDIDO. Resultado positivo NO autoriza Bot/Testnet/Live.
5. Evaluación ÚNICA al corte; cohorte descriptiva.

## Secuencia restante

Conformidad acotada → congelamiento v11 → implementar B-2 → implementar
B-3/B-4/B-5/B-6 → re-auditoría integrada completa → despliegue verificado →
cohorte desde cero.
