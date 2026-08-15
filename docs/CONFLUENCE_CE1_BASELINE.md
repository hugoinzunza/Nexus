# CE-1 — Baseline congelado

**Fecha:** 2026-08-15
**Estado:** `CE-1 FROZEN BASELINE` · **CE-2 NOT AUTHORIZED**

Cierra las dos precondiciones administrativas que dejó la re-auditoría final
(`A. CE-1 FINAL RE-AUDIT — PASS`, 2026-08-08): P-1 (revisión científica
versionada en su repo dueño) y P-2 (declaración explícita del alcance del
contrato). No cambia código, schema, fixtures ni tests.

## Fingerprints del baseline

Commit del código: `3e9f034bff7058c72a978e943e4c15d11527ef87`
(`Fix CE-1 post-freeze validation invariants`, sobre `3ae6de4`).

```
tree modules/confluence : 83d004bd560e20fa4e314efe6c700bae526a9bc8
fixture ce1_cases.json  : 6d74904ab689038d383ef75496c6f56922178099db8751c00f6841e08bdad924
golden output           : 7413cb3962787f13d17bc4eb5eef5d8c306742926822d5ea748d664df06bdfda
schema ce1-v1-candidate : a4926c035913c17ef087136b75966e9cf54e819189b7f851141481c0cba5da82
contracts.py            : 2c23af5222bbe68c2770f36bd629b3bc76d1ae4a7082e95509f496c22c6db299
descriptive.py          : 62d0c1ef505741fe8445c660525e48bbe700836273592cc17ca88b73a3db08fd
```

El *golden output* es el SHA-256 del `descriptive_synthesis` serializado
(`sort_keys`) que produce `build_descriptive_synthesis` sobre el fixture
congelado. Ha permanecido idéntico a través de los tres pases de corrección: es
la prueba de que fueron aditivos en rechazo y neutros en aceptación.

`tests/test_confluence_ce1.py` **no** forma parte del baseline congelado: la
suite debe poder crecer sin romperlo. Suite al congelar: 60 passed.

## Documento científico canónico (P-1)

La restricción científica de segunda precedencia vive en su repo dueño:

- Ruta: `nexux-trading-intelligence-lab/docs/CONFLUENCE_SCIENTIFIC_REVIEW.md`
- Commit: `027bbf28af8762f4f553a17811764b2e77f65804`
- SHA-256 del archivo: `8b608d1e2d35e73e534b1fedce34fc87c054cd1e9b809b372ad08839c432fb38`

NexUX la referencia y no la duplica. Precedencia:
`RECONCILIATION > SCIENTIFIC REVIEW > DISCOVERY`.

## Alcance del contrato (P-2) — lo que "CE-1-valid" significa y lo que NO

1. **"CE-1-valid" significa corrección representacional**, no ausencia de
   semántica predictiva. El filtro de `value`/`temporal_context` es **nominal**:
   bloquea vocabulario prohibido (incluida morfología trivial y etiquetas
   direccionales), pero **no puede impedir** que una magnitud predictiva viaje
   bajo un nombre legítimo del dominio (p. ej. `{"levels": [0.7, 0.3]}`). Esa
   clase de evasión es estructuralmente incompletable con reglas léxicas; la
   auditoría final la clasificó como límite de diseño, aceptado porque CE-1 no
   interpreta ni computa sobre `value` (no existe aritmética de magnitudes en el
   módulo). Cerrarla exigiría un `value` discriminado por `kind` — pregunta
   abierta #19.1 de la reconciliación, materia de otra iteración de contrato.
2. **El JSON Schema por sí solo NO es un validador CE-1 suficiente.** No expresa
   las invariantes entre campos (orden causal, orden de validez, coherencia
   `basis`↔`relation`, auto-referencia, coherencia de `lineage.status`): 7
   mutaciones inválidas pasan el schema y las rechaza el runtime. El validador
   normativo es `validate_synthesis` / `validate_observation` de
   `modules/confluence`. El `$id` público del schema no cambia esto.
3. **La aprobación representacional no acredita nada científico.** Sin
   independencia estadística, información incremental, poder predictivo, EV,
   robustez ni edge. `provenance.environment` está fijado a `synthetic_fixture`:
   el contrato no puede representar una fuente real.
4. Reglas de compatibilidad recomendadas para cualquier CE-2 futuro: las diez de
   la auditoría post-freeze (versión §19), en particular *el validador es el
   contrato* y *la cardinalidad nunca se convierte en score*.

## Gobernanza

- Cambiar cualquier artefacto del baseline exige version bump de
  `CE1_SCHEMA_VERSION` y nueva acta; el sufijo `-candidate` se resuelve recién en
  esa próxima iteración.
- `CE-2 NOT AUTHORIZED`. Esta acta no habilita fuentes reales, UI, endpoints,
  EventBus, Bot, Aurora ni integración operativa con Trading Intelligence.
