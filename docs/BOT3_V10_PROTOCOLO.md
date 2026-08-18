# Bot3.v10 — Protocolo pre-registrado CANDIDATO (mínimo: ciclo del candidato)

**Fecha:** 2026-08-17
**Estado:** `CANDIDATO / NO IMPLEMENTADO / PENDIENTE CONFORMIDAD ACOTADA`
**Base:** protocolo v9 CONFORME, SHA-256
`9d24166a33aa74af7f2b2dd7d0bdf4e2d16866e13eec7c48e7b1480512001530`.
**Origen:** auditoría de implementación
`AUDITORIA_IMPLEMENTACION_BOT3_V9.md` (SHA-256
`c55362479d85efbe3b23c57c15ba0461ccdbe0d4ee706c7dd87e571728129fa6`),
hallazgos B-2 y M-3, más el defecto de head post-hueco declarado en
`tests/test_bot3_v9_gates.py`.

**Alcance deliberadamente MÍNIMO.** v10 solo toca lo que B-2 y el head
causal exigen; todo lo demás de v9 (CF-1..CF-37) permanece idéntico y
vigente. Los hallazgos B-3, B-4, B-5 y B-6 de la auditoría son defectos de
IMPLEMENTACIÓN contra cláusulas v9 ya conformes: se corrigen en código, NO
requieren contrato nuevo y no se tratan aquí.

Cláusulas modificadas: CF-14 (máquina de estados y ciclo), CF-32/CF-34
(head de inputs). Se agregan CF-38..CF-41 y dos tipos al registro CF-37.

---

## CF-38. Estado `candidato_vivo` (modifica la máquina de CF-14)

La máquina pasa a:

```text
flat → candidato_vivo → orden_viva → posicion → (salida_detectada) → flat
```

- `candidato_vivo` NACE en el cierre de la vela M15 del TOQUE de la zona H4
  ganadora del arbitraje (Fase 7), con su `candidate_id` ya definido.
- Mientras un mercado tiene `candidato_vivo`, `orden_viva`, `posicion` o
  `salida_detectada`, NO admite candidatos nuevos (posición única por
  mercado, ya vigente).
- La FRESCURA de la zona se consume en el TOQUE (regla v9 sin cambio): un
  candidato que expira no devuelve la zona a fresca.
- `candidato_vivo` MUERE por, en este orden de evaluación:
  1. **fill** → `posicion` (o `salida_detectada` si fill+STOP, CF-20);
  2. **invalidación**: cierre M15 a través de la invalidación de la zona H4
     → `candidato_invalidado`;
  3. **deadline total**: 64 velas M15 desde el cierre del toque, sin fill →
     `candidato_expirado`;
  4. **dirección rectora** expirada o cambiada respecto de la del toque →
     `candidato_expirado` (motivo `direccion`);
  5. **hueco M15** que lo intersecta → `candidato_expirado` (motivo
     `hueco_m15`).

## CF-39. Cronología POST-TOQUE (cierra B-2)

Dentro del deadline total y **estrictamente después** de la vela del toque
(`j_toque`), en este orden causal:

1. **Toma de liquidez a la izquierda**: existe una vela M15 `k > j_toque`
   que BARRE (definición de sweep, §6-bis) un swing INT M15 **confirmado y
   disponible antes de `k`** (`confirm_idx < k` — CF-41 M-3).
2. **iBOS**: el PRIMER evento BOS con cuerpo de `INT_PIV` en la dirección
   del candidato con `j_ibos > j_toma`, y `j_ibos ≤ j_toque + 48`.
   *(Prohibido usar un iBOS anterior o igual al toque: ese era el defecto
   B-2.)*
3. **Zona derivada** (creada POR el desplazamiento): entre las zonas M15
   con `available_at ≤ close(j_ibos)` y vela de formación
   `idx ∈ (j_toque, j_ibos]`. Arbitraje: OB antes que FVG; luego
   `available_at` más antiguo; luego menor `lo`. Si no existe ninguna →
   el candidato sigue vivo esperando (puede aparecer con un iBOS posterior
   dentro del deadline; el iBOS ya consumido no se reutiliza).
4. **Orden límite** en el borde proximal de la zona derivada, disponible
   desde el cierre de la vela que la completa (regla v9).
5. **Fill** según §4.5 v2 (sin cambios), dentro del deadline total.

El TP sigue siendo el weak rector CERRADO y el SL el extremo de la reacción
que originó el iBOS ± buffer (reglas v9).

## CF-40. Ciclo de vela extendido (modifica el orden de fases de CF-14)

Las fases de CF-14 se conservan; la Fase 7 se desdobla:

- **Fase 7a — candidato vivo:** si el mercado está en `candidato_vivo`,
  evaluar la cronología CF-39 sobre las velas cerradas en `T` (toma → iBOS
  → zona derivada → orden). Las muertes de CF-38 (2)–(5) se evalúan aquí,
  después del fill de Fase 1b y con el estado calculado en Fase 2.
- **Fase 7b — nuevo candidato:** solo si el mercado quedó `flat`, detectar
  toques, arbitrar y crear `candidato_vivo` (nunca orden en la misma vela
  del toque).

Todo lo demás (cálculo puro antes de aplicar, no retroactividad, funding
antes del cierre único, lotes globales) queda igual.

## CF-41. Head de inputs por contenido causal (corrige CF-32/CF-34)

`input_head_asof_T` = `hash_acum` del último registro cuyo CONTENIDO es
causalmente anterior o igual a `T`:

- vela: `t + dur ≤ T`;
- **marcador de hueco: `hasta + dur ≤ T`** (el intervalo ausente terminó en
  `T`), en reemplazo de la regla `detected_at ≤ T` de v9.

`provenance_head_at_finality` NO cambia: sigue usando `detected_at ≤
finalized_at`, y es lo que demuestra por qué el lote se liberó.

Motivo: con la regla v9, durante el catch-up el head de inputs se quedaba
en el prefijo pre-hueco aunque el modelo ya consumía velas posteriores al
hueco — sub-identificaba los bytes consumidos. La regla nueva mantiene la
prohibición de datos futuros (un marcador solo entra cuando su intervalo ya
pasó) y hace que el head identifique exactamente lo consumido.

## CF-42. Referencia al ganador del arbitraje (cierra M-3)

Todo evento `descartada_por_arbitraje` DEBE llevar el campo `ganador` con
el `candidate_id` del candidato elegido en ese mismo lote. Sin ese campo el
evento es inválido.

## CF-43. Ampliación del registro CF-37

Se agregan DOS tipos a la familia "jerarquía de trade"
(preimagen `{"contrato","id","tipo"}`, `id` = `candidate_id`):

| Tipo | Cuándo |
|---|---|
| `candidato_expirado` | deadline, dirección o hueco matan al candidato vivo |
| `candidato_invalidado` | cierre M15 a través de la invalidación de la zona H4 |

**Vectores dorados** (contrato de prueba `"0"×64`, `candidate_id = "3"×64`):

- `candidato_expirado` → `7cc8eda9b1b9f43a99634abd927ea881c2edb37197b6478a56600ec0945e59b8`
- `candidato_invalidado` → `8131681cbb2c46aab6489aadabb2b03e1ecd32c7cc52c7b3a3e140682da34c71`

Ningún otro tipo se agrega ni modifica.

---

## Gates adicionales de implementación (sobre los de v9)

1. **Cronología estricta:** un iBOS ANTERIOR al toque no puede producir
   orden; un iBOS posterior dentro de las 48 velas sí. Vector sintético con
   ambos casos.
2. **Candidato vivo multi-lote:** el candidato nacido en `T` produce orden
   en `T + n·15m` (n ≥ 1) y el libro es idéntico procesando lote a lote.
3. **Muertes:** un vector por cada causa de CF-38 (2)–(5), con su evento.
4. **Zona derivada acotada:** una zona anterior al toque NUNCA puede ser la
   derivada, aunque sea la más cercana.
5. **Head de inputs (CF-41):** en catch-up, el head identifica las velas
   post-hueco efectivamente consumidas y nunca contiene futuro.
6. **Sweep causal (M-3):** un swing cuyo `confirm_idx ≥ k` no sirve como
   liquidez tomada por la vela `k`.
7. **Arbitraje:** todo `descartada_por_arbitraje` trae `ganador` válido.
8. Los gates de v9 siguen vigentes en su totalidad, incluidos los dos de
   B-1 (habilitación por velas cerradas y continuidad H4 causal).

## Reglas de vigencia

1. CANDIDATO: se congela como v10 con la conformidad acotada de Codex; su
   SHA-256 pasa a ser el nuevo `contrato_hash`. Cambio posterior = v11 +
   cohorte nueva.
2. Un cambio de `contrato_hash` cambia TODAS las identidades del ledger; por
   eso v10 debe congelarse ANTES de implementar B-2, y cualquier libro
   producido bajo v9 no se reutiliza.
3. B-3, B-4, B-5, B-6 se corrigen en implementación contra cláusulas v9
   vigentes; no requieren contrato nuevo.
4. Bot3.v1 SUSPENDIDO. Nada de v1..v9 se reutiliza como evidencia.
   Resultado positivo NO autoriza Bot/Testnet/Live.
5. Evaluación ÚNICA al corte; la cohorte es descriptiva (CF-33/CF-34).

## Secuencia restante

Conformidad acotada de v10 → congelamiento (hash = `contrato_hash`) →
implementar B-2 → implementar B-3/B-4/B-5/B-6 → re-auditoría integrada
completa → despliegue verificado → cohorte desde cero.
