# Árbol de decisión de octubre — congelado antes de ver datos

**Fecha:** 2026-08-15. Se escribe con ECON-COHORT-001 en 0/50 y HYP-EXIT-003 en
semana 2 de 12, sin ningún resultado a la vista. Ese es el punto: decidir las
ramas ahora, cuando ningún número puede sesgarlas. Es el mismo principio del
pre-registro, aplicado a las decisiones humanas.

Este documento no ejecuta nada. Cada rama termina en una decisión de Hugo.

---

## Evento 1 — Cierre de ECON-COHORT-001 (50 cierres o 10-oct 04:30 UTC)

Evaluación ÚNICA al cierre, como manda el protocolo (`a46d073e…`). Métricas
netas con IC95 por bloques, publicadas junto al estimador puntual.

### Rama A — n = 50 y la evidencia económica es positiva
*(avgR neto con IC95 sobre cero — el listón de "positiva" es el del protocolo
congelado, no este doc)*

1. NO pasar a live de inmediato. La cohorte prueba **selección y expectativa
   con fees estimadas**; la fricción real sigue sin medirse (el propio
   protocolo lo declara: HYP-COST-003 excluye dry).
2. Siguiente paso autorizable: **fase live acotada** tipo ECON-COHORT-002-LIVE,
   pre-registrada: mismo riesgo 9 USD, n pequeño definido de antemano, con el
   único objetivo de alimentar HYP-COST-003 (fees confirmadas, spread causal) y
   comparar fricción real vs estimada. Esto además desbloquea el único
   observador del laboratorio aún en `blocked`.
3. El paso 2 exige antes: desplegar el gate nuevo al VPS (el deploy quedó
   bloqueado durante la cohorte) y decidir el destino de la rama
   `claude/bot-protect3r-flag` según el Evento 2.

### Rama B — n = 50 y la evidencia es negativa o indistinguible de cero

1. NO live. Sin excepciones ni "casi".
2. La pregunta pasa a ser estructural: la fricción (~0,22R medidos a 9 USD) es
   mayor que cualquier edge plausible de la señal. Las tres palancas, en orden
   de menor a mayor costo de implementación:
   - **entradas maker** (limit post-only): reduce la comisión a la mitad o
     menos; exige estudio propio de fill-rate (¿cuántas señales se pierden
     esperando el fill?) — pre-registrable como estudio dry sin tocar nada;
   - **menos operaciones de mayor RR realizado** (no más filtros post-hoc:
     rediseño pre-registrado);
   - **tier de fees / BNB discount** según lo que el exchange ofrezca.
3. El bot NO se archiva por una cohorte negativa: se archiva la *pretensión de
   live con esta configuración*. Diario, laboratorio y Bot2 siguen su curso.

### Rama C — 10-oct con n < 50

1. La regla dura ya existe y se respeta: **"seguir midiendo, nunca evaluar con
   lo que haya."** Se extiende la cohorte SIN tocar la config (la extensión de
   plazo con política idéntica no es un cambio de política; se registra en el
   acta con fecha).
2. Si el ritmo proyecta n=50 más allá de fin de año, ahí sí hay una decisión de
   diseño (¿universo del VPS más amplio en una COHORT-002?) — nunca un parche a
   la cohorte viva.

---

## Evento 2 — Veredicto HYP-EXIT-003 (24-oct, protocolo congelado `138c49a8…`)

La decisión es AUTOMÁTICA por protocolo; lo único humano es ejecutarla.

### Si `decision.status` = promoción (los 6 criterios, IC95 incluido)

1. Merge de `claude/bot-protect3r-flag` (código listo, probado, con identidad
   verificada a bandera apagada) al release del VPS **después** del deploy
   post-cohorte del Evento 1.
2. `exit_protect_3r: true` SOLO si para entonces no hay otra cohorte económica
   viva cuya política lo congele. Si la hay: la bandera espera a su cierre.
   Cambiar la política de salidas a mitad de una cohorte la invalida — regla ya
   escrita, aquí solo se recuerda.

### Si no cumple todos los criterios

1. **Descarte.** El protocolo dice `rule_changes_after_start: forbidden` y su
   regla terminal es descarte a las 200 pareadas o 26 semanas; a las 12 semanas
   sin promoción la cohorte puede seguir hasta su término natural, pero la
   bandera NO se enciende con evidencia parcial.
2. La rama `claude/bot-protect3r-flag` se conserva sin mergear (es la
   implementación de referencia si una cohorte futura reabre la pregunta), y se
   anota el resultado en el registro del laboratorio.
3. Atención especial al criterio de drawdown (−10% relativo): el histórico dio
   −9,0% con costos base. Si el forward falla por ese criterio, la respuesta
   correcta ya quedó decidida en la auditoría de agosto: **es descarte**, no
   "nueve es casi diez". Este doc existe para que esa frase no se pronuncie.

---

## Evento 3 — Bot2 v2 alcanza ~30–50 cerrados virtuales (estimado: fin de año)

1. Ejecutar el walk-forward que el contrato v1 dejó definido, con los
   parámetros v2 congelados el 15-ago (piv=3, RR≥2, projection).
2. Sin resultado positivo ahí, Bot2 sigue siendo visor. Con resultado positivo,
   lo único que se habilita es *discutir* una fase dry — nunca un salto a live.

---

## Reglas transversales de este árbol

- Ninguna rama se decide antes de su evento. Este doc se congela hoy;
  enmendarlo después de ver resultados lo anula como pre-compromiso.
- Las métricas intermedias de ECON-COHORT-001 siguen prohibidas hasta el cierre;
  el conteo (X/50) es lo único visible.
- Cualquier acción de dinero real la ejecuta Hugo, nunca un agente. Los agentes
  preparan ramas, actas y evidencia.
- `NO LIVE` es el estado por defecto en todo camino no cubierto explícitamente
  por una rama de este árbol.
