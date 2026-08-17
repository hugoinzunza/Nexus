# Revisión científica independiente — Estudio "BOOTCAMP MAYO 2025" (Bitcoin Traders)

**Fecha:** 2026-08-17
**Revisor:** Claude (revisión adversarial independiente, encargada por Hugo)
**Objeto revisado:** los 8 documentos del estudio de Codex en
`nexux/research/bitcoin_traders_course_2026-08-17/` (protocolo, manifiesto,
11 fichas de sesión, glosario, playbook, comparación NexUX, backlog de
hipótesis y revisión final).
**Mandato:** no aceptar conclusiones por autoridad; intentar refutarlas contra
la evidencia original (transcripciones JSON + videos vía Classroom autorizado).
**Restricciones cumplidas:** no se modificó ningún documento existente, no se
tocó NexUX ni Bot/Testnet/Live/Railway/VPS, no se implementaron indicadores ni
backtests ni señales, sin commit y sin push. Este archivo es lo único creado.

---

## 1. Veredicto

**APROBADO CON CORRECCIONES.**

El estudio es honesto, trazable y metodológicamente serio: separa evidencia de
inferencia con la taxonomía E0/E1/E2/I1/H1/U0, conserva el conocimiento
negativo, no infla edge y excluye correctamente el material peligroso (fórmula
de futuros). Sometido a verificación adversarial —13+ contrastes de
transcripción y 6 verificaciones visuales dirigidas contra los videos
originales— **ninguna conclusión central quedó refutada**. Las correcciones
requeridas son de precisión documental (una cita errada, dos matices omitidos,
una regla fusionada), no de fondo. Ninguna invalida el veredicto de Codex
("CONCEPTUAL PASS COMPLETE / VISUAL GATE PENDING"); de hecho, esta revisión
**cierra el gate visual principal** que la revisión final dejó pendiente.

---

## 2. Método de esta revisión

1. **Lectura completa** de los 8 documentos en el orden indicado.
2. **Contraste adversarial de transcripciones:** re-extracción de ventanas
   desde los JSON de `.course-cache/bitcoin-traders-bootcamp-2025/transcripts/`
   (segmentos con `start/end/text`) para cada regla estructural, buscando
   afirmaciones del estudio sin soporte o soporte que el estudio omitiera.
3. **Verificación visual dirigida:** acceso a los videos vía Google Classroom
   (sesión autorizada de Hugo), posicionamiento por línea de tiempo en el
   reproductor de Drive y captura de fotograma en los 6 fragmentos del gate
   recomendado por `FINAL_REVIEW.md`. Los videos usados y fotogramas quedan
   citados por sesión y timestamp del reproductor; no se descargó ni
   redistribuyó material.
4. **Verificación aritmética** de la fórmula de futuros de S11.
5. Intento explícito de refutación de cada conclusión mayor; donde mi propia
   sospecha inicial resultó infundada, lo dejo registrado (§5, hallazgo M-4).

Nota de reproducibilidad: los timestamps de transcripción tienen la deriva
usual de ASR (±5-10 s) respecto del reproductor; las garblings de Whisper
("y vos" = iBOS, "su hija" = swing high, "su enlo" = swing low, "wit high" =
weak high, "indusme"/"induccion" = inducement, "orden blog" = order block,
"estoblos" = stop loss) fueron verificadas y el estudio las normalizó
correctamente.

---

## 3. Resultado del gate visual (cerrado en esta revisión)

Los 6 fragmentos del gate recomendado en `FINAL_REVIEW.md` fueron posicionados
y verificados contra pantalla:

| # | Ítem del gate | Video / posición | Qué se ve | Resultado |
|---|---|---|---|---|
| 1 | Fractal válido y criterio cuerpo/mecha | Sesión 02, 28:06 | Lámina "SESIÓN 02: FRACTALIDAD": velas japonesas, panel MOVIMIENTOS con Fibonacci 0 / 0,5 / 1 anclado en los extremos del impulso (esquema i→r), panel SWING HIGH | **CONFIRMADO** |
| 2 | Inicio/finalización del rango y weak target | Sesión 03, 1:07:46 | Esquema BTC 1D con "FRACTALES SW Y SL", "T.R = TRADING RANGE", **Strong Low** rotulado como inicio y **Bos HTF** marcado; tramos ALCISTA/BAJISTA/ALCISTA; "D, H4 Y M15" | **CONFIRMADO** |
| 3 | Liquidez exterior y bloque trampa | Sesión 05, 31:42 | El profesor marca con plumón dos "Discount POI" apilados con liquidez entre ambos: el primero queda como trampa y la zona válida es la que está más allá de la liquidez (transcripción 00:30:52–00:33:02: "sea cual sea la temporalidad") | **CONFIRMADO** |
| 4 | iBOS válido izquierda/derecha | Sesión 08, 39:42 | Esquema de confirmación: reacción en BUY ZONE → iBos interno → "ESTRUCTURA PRINCIPAL M5, M3 O M1" → zona derivada → continuación; a la izquierda SELL ZONE con INDUCEMENT dibujado delante (geometría del bloque trampa) | **CONFIRMADO** |
| 5 | Primer uso / zona no mitigada (decisional vs extremo) | Sesión 04, 1:05:51 | Rótulo "DECISIONAL EXTREMO"; el profesor marca sobre BTC 1D cuál zona sigue sin mitigar y pasa a ser el nuevo extremo; zonas premium/discount POI rotuladas | **CONFIRMADO** (con corrección de cita, ver M-1) |
| 6 | Fórmula visual de futuros (para documentar exclusión) | Sesión 11, 1:48:01 | Lámina "Cómo saber el apalancamiento correcto": `% SL × APALANCAMIENTO = X%`, "XX = nunca debe ser mayor al 80% (lo ideal es cerca del 70%)", ejemplo SL 0,76% → 105x → 79,8% "+ comisión", "para evitar ser liquidado antes de tiempo" | **CONFIRMADO** (exclusión validada, §9) |

El pipeline (Classroom → Drive → seek por fracción de duración del manifiesto)
funcionó de forma reproducible; no hubo bloqueo de acceso. Con esto, el
requisito previo que `FINAL_REVIEW.md` fija para congelar `playbook.v1` queda
**satisfecho en sus 6 puntos**, quedando solo ítems secundarios de ficha (§13).

---

## 4. Hallazgos por severidad — resumen

**Crítico (invalida conclusiones): ninguno.**

**Mayor (requiere corrección antes de congelar `playbook.v1`):**

- **M-1. Cita errada de "frescura/primer uso" en el playbook.** El §9 del
  playbook ("una zona refinada se prefiere en su primer uso") cita
  S08 00:50:40–00:53:53, pero esa ventana trata bloque trampa y dos entradas;
  no menciona refinamiento ni primer uso. El concepto real está en
  **S04 01:04:22–01:10:01** ("lo ideal es que el precio no lo haya mitigado…
  ese va a ser su nuevo extremo") y su persistencia al refinar en
  S05 00:32:12–00:33:02. Confirmado visualmente (gate #5). Corregir la cita.

- **M-2. "Dos entradas" está subrepresentada como regla docente.** La
  transcripción de S08 00:52:30–00:53:53 es categórica: "siempre nosotros
  vamos a gestionar dos entradas **siempre siempre siempre** hagan eso… si
  quieren invertirle el 1 % dividan 0.5 y 0.5 y se acabó… y si en las dos les
  sale el stop loss, listo, se acabó su operativa ese día". El curso la enuncia
  como regla universal con reparto de riesgo explícito, mientras
  `FINAL_REVIEW.md` la lista como "contextual, sin disparador universal" y el
  playbook la condiciona ("cuando se usan dos entradas"). La parte del riesgo
  repartido sí está bien capturada (S11 02:28:11–02:29:52 confirma 0,25+0,25).
  Corrección: documentar que el docente la enuncia como universal; mantenerla
  en amarillo operacional es defendible (faltan definición de zonas admisibles
  y correlación), pero el registro de lo enseñado debe ser fiel.

- **M-3. Ficha S11: detalles literales de la fórmula de futuros omitidos.**
  La ficha registra `stop_pct × leverage = 80%` pero omite tres elementos
  presentes en transcripción y en la lámina (verificados): (a) el ideal
  declarado es ~70 % ("lo ideal sería escoger el 70… por efectos prácticos el
  80"); (b) el ejemplo numérico completo (SL 0,76 % → 80/0,76 ≈ 105x →
  79,8 % del margen "+ comisión"); (c) la justificación de la lámina es
  "evitar ser liquidado **antes de tiempo**" (buffer anti-liquidación),
  mientras que oralmente el 20 % restante se atribuyó a "comisiones del
  exchange" — explicación financieramente incorrecta que merece registro
  explícito como parte de la exclusión. La decisión de excluir es correcta
  (§9); la documentación de por qué debe quedar completa.

**Menor (precisión de redacción):**

- **m-4. Fusión de dos reglas distintas de Fibonacci en ficha S02/glosario.**
  El texto funde el **anclaje** de la medición ("¿Medimos desde las mechas?
  Sí… mayormente son desde las mechas; si tiene cuerpo, tocará cogerlo desde
  el cuerpo", S02 00:27:06–00:27:21) con la **tolerancia del toque** del 50 %
  ("al llegar al 50 %… puede llegar con mecha o puede llegar con cuerpo",
  S02 00:29:08–00:29:17). Ambas reglas existen y tienen soporte E0 —mi
  sospecha inicial de que la tolerancia del toque carecía de soporte quedó
  **refutada** al ampliar la ventana—, pero son reglas distintas (anclaje con
  preferencia por mecha vs toque indistinto) y deben registrarse separadas:
  cualquier operacionalización futura las parametriza distinto.

- **m-5. Regla de diez velas: matices omitidos.** S06 00:52:16–00:55:47
  añade tres precisiones que la ficha no recoge: (a) "si esas 10 velas las da
  **por dentro** tengan cuidado, puede que no llegue a romper el alto";
  (b) las velas se cuentan en la temporalidad de la zona de reacción (H4 →
  10 velas H4, M15 → 10 de M15, M5 → 10 de M5); (c) el propio profesor la
  rebaja: "es un dato no más". El punto (c) de hecho refuerza la
  clasificación amarilla del estudio; conviene citarlo.

**Verificaciones positivas relevantes (intentos de refutación fallidos):**

- La resolución de la inconsistencia oral de S04 sobre "al menos dos de los
  cuatro requisitos" (marcada U0 y resuelta con S05) es correcta.
- El relato de acierto BTC "75 %–82 %" (S11 02:12:02–02:13:20) está
  correctamente clasificado U0: no hay dataset, periodo ni costos.
- La normalización de garblings ASR es consistente en las 11 fichas.
- La reserva sobre S09 (metodología de rangos en revisión, no congelable) está
  soportada por transcripción.
- La secuencia núcleo del playbook (10 pasos) es reconstruible desde las
  ventanas citadas; no encontré pasos inventados ni SMC externo infiltrado.

---

## 5. Tabla de reglas núcleo

Estados: **CONFIRMADA** (soporte E0 + reproducible desde transcripción, y
visual donde correspondía), **CONFIRMADA CON MATIZ** (soportada, requiere la
corrección indicada), **AMBIGUA** (soportada pero sin cierre operacional),
**EXCLUIDA** (registrada y correctamente no incorporada), **SIN EVIDENCIA**.

| Regla | Evidencia | Sesión / timestamp | Reproducibilidad | Dependencia visual | Estado |
|---|---|---|---|---|---|
| Jerarquía temporal (semanal>D>H4>M15>micro) | E0 | S01 01:44:15–01:46:39; S09 00:22:58–00:24:22 | Alta | Baja | CONFIRMADA |
| Fractal válido: impulso + retroceso ≥50 % + continuación | E0 | S02 00:16:33–00:41:11 | Alta | Media (resuelta: S02 28:06) | CONFIRMADA |
| Anclaje Fib: mayormente mechas, fallback cuerpo | E0 | S02 00:27:06–00:27:21 | Alta | Resuelta (gate #1) | CONFIRMADA CON MATIZ (separar de la siguiente, m-4) |
| Toque del 50 %: vale cuerpo o mecha | E0 | S02 00:29:08–00:29:17 | Alta | Baja | CONFIRMADA CON MATIZ (m-4) |
| Rango: toma de liquidez → strong extreme → finalización iBOS → weak target → 50 % | E0 | S03 01:05:15–01:24:54 | Alta | Resuelta (gate #2) | CONFIRMADA |
| Weak high/low como objetivo principal | E0 | S03; S07 00:55:44–00:57:58 | Alta | Baja | CONFIRMADA |
| Premium/discount por dirección | E0 | S04 00:38:28–00:44:42; S07 00:14:30–00:19:18 | Alta | Baja (zonas rotuladas visibles en gate #5) | CONFIRMADA |
| Tres familias de zona (OB, imbalance, toma de liquidez) | E0 | S06 00:31:54–00:32:37 | Alta | Baja | CONFIRMADA |
| Taxonomía OB (decisional/extremo/breaker/alta prob.) | E0 | S04 00:21:46–00:24:50 | Media | Resuelta parcial (gate #5 muestra decisional/extremo) | CONFIRMADA (etiqueta "alta probabilidad" sigue sin frecuencia) |
| Frescura / no mitigado; OB HTF con zonas LTF | E0 | **S04 01:04:22–01:10:01** (no S08) | Media | Resuelta (gate #5) | CONFIRMADA CON MATIZ (M-1: corregir cita) |
| Liquidez delante (inducement) fortalece contexto | E0 | S05 00:14:18–00:23:08; S08 (INDUCEMENT en lámina) | Media | Resuelta (gate #4) | CONFIRMADA |
| Liquidez exterior detrás ⇒ bloque trampa; refinar no la elimina | E0 | S05 00:29:40–00:33:02; S08 00:50:40–00:51:46 | Alta | Resuelta (gate #3) | CONFIRMADA |
| iBOS válido: toma liquidez izquierda + crea liquidez derecha | E0 | S08 00:36:05–00:41:50 | Media | Resuelta (gate #4) | CONFIRMADA (operacionalización pendiente por diseño) |
| Tabla zona→confirmación (D→H1, H4→M15, H1→M5, M15→micro) | E0 | S06 00:43:13–00:50:50; S11 00:31:14–00:32:35 | Alta | Baja | CONFIRMADA |
| Regla de diez velas (en TF de la zona; "por dentro" = cuidado) | E0 | S06 00:52:16–00:55:47 | Media | Baja | AMBIGUA (m-5; el docente mismo la relativiza) |
| Dos entradas con riesgo dividido (0,5+0,5 / 0,25+0,25) | E0 | S08 00:52:30–00:53:53; S11 02:28:11–02:29:52 | Alta | Parcial (S11 02:28 sin captura) | CONFIRMADA CON MATIZ (M-2: docente la enuncia universal; operacionalmente amarilla) |
| Riesgo 0,5 %–1 %, 2 stops diarios, meta semanal 3–5 % | E0 (plantilla personal) | S11 00:36:06–00:45:55 | Alta | Pendiente secundaria | CONFIRMADA como ejemplo personal, no como parámetro óptimo |
| Fórmula futuros `stop_pct × leverage = 80 %` (ideal 70 %) | E0 literal | S11 01:45:17–01:55:01 | Alta | Resuelta (gate #6) | **EXCLUIDA — exclusión correcta y ahora visualmente documentada** |
| Acierto BTC 75 %–82 % | U0 | S11 02:12:02–02:13:20 | N/A | N/A | SIN EVIDENCIA (correctamente tratada) |
| Revisión futura de rangos (S09) | E0 de su existencia; contenido no cerrado | S09 01:25:12–01:34:47 | N/A | N/A | EXCLUIDA (correcta) |

---

## 6. Reglas confirmadas vs ambiguas

**Confirmadas para congelar en `playbook.v1`** (tras aplicar M-1/M-2/m-4):
jerarquía temporal; fractal ≥50 % (con anclaje y toque como reglas separadas);
construcción del rango y weak target; premium/discount; tres familias de zona;
mapa de liquidez delante/detrás con bloque trampa; iBOS válido como definición
descriptiva; tabla zona→confirmación; gestión base (riesgo bajo, límite
diario, aceptación previa de pérdida, bitácora).

**Ambiguas — permanecen amarillas, correctamente:** selección del swing
rector; tamaños mínimos de OB/FVG; buffer de stop; regla de diez velas;
break-even y parciales; dos entradas (universal en el discurso, incompleta en
especificación); "alta probabilidad" como etiqueta.

---

## 7. Contradicciones (verificadas contra transcripción)

Las cuatro contradicciones que el estudio reporta son reales y quedan
verificadas: (1) riesgo bajo predicado vs fórmula de futuros que consume ~80 %
del margen por posición; (2) límite diario 1 % → 1–2 % → techo 5 %;
(3) win rate relatado sin dataset; (4) el profesor admite error propio de
mapeo y una metodología de rangos aún en evaluación. Añado una quinta, menor:
la lámina de S11 justifica el buffer del 20–30 % como anti-liquidación
mientras el discurso oral lo atribuye a comisiones — inconsistencia interna
del curso que refuerza la exclusión (§9).

---

## 8. Evaluación especial: fórmula de futuros de S11

**Aritmética:** internamente consistente. Con SL 0,76 %: 80/0,76 ≈ 105,26 →
el docente usa 105x → 0,76 % × 105 = 79,8 % del margen. Verificado en
transcripción y en la lámina (gate #6).

**Por qué la exclusión es correcta (y debe permanecer):**

1. **Margen de seguridad casi nulo frente a liquidación.** A 105x, la
   distancia aproximada a liquidación es ~1/105 ≈ 0,95 % menos el margen de
   mantenimiento y ajustes de mark price; el stop está a 0,76 %. Cualquier
   mecha, slippage o fee empuja el precio de liquidación por delante del stop:
   la posición puede liquidarse **antes** de que el stop trabaje, exactamente
   lo que la lámina dice querer evitar, sin modelar por qué el 20 % bastaría.
2. **El docente acepta la liquidación como salida** ("si me liquido pues que
   me liquide, ya está gestionado", S11 01:49:40–01:50:19). Eso convierte la
   liquidación —el peor mecanismo de salida en costos— en parte del plan.
3. **Confusión conceptual:** mezcla riesgo de cuenta, margen asignado,
   apalancamiento y liquidación sin modelo de exchange (MMR, mark price,
   fees, funding). La atribución del buffer a "comisiones" es incorrecta.
4. No existe dataset ni argumento estadístico que justifique 70/80 frente a
   cualquier otro número.

**Conclusión:** mantener `NO OPERACIONALIZAR`. Ninguna variante de esta
fórmula debe entrar a NexUX ni siquiera como hipótesis de laboratorio; el
sizing del Bot (riesgo fijo en USD con stop estructural) es categóricamente
superior en control de riesgo. La ficha debe completarse con los literales
omitidos (M-3) para que la exclusión quede blindada ante relecturas futuras.

---

## 9. Evaluación del playbook y de la comparación con NexUX

**Playbook:** la secuencia de 10 pasos es una reconstrucción fiel; el semáforo
verde/amarillo/rojo está bien calibrado (nada en verde carece de soporte E0;
nada en rojo merece rescate). Correcciones antes de congelar `playbook.v1`:
M-1 (cita de frescura), M-2 (fidelidad de "dos entradas"), m-4 (separar
anclaje/toque), m-5 (matices de diez velas), M-3 (completar exclusión de
futuros).

**BITCOIN_TRADERS_VS_NEXUX:** la matriz de equivalencias es correcta y su
hallazgo central está bien identificado: lo nuevo no es detectar más OB/FVG
sino (a) la relación topológica "liquidez detrás de la zona" (ausente en
NexUX), (b) el iBOS válido izquierda/derecha (más exigente que el CDC micro),
(c) frescura por zona efectiva y (d) la separación estructura rectora /
interna. Coincido en que el fractal docente **no** es el pivote de NexUX y en
que el rango causal no debe reemplazar al rango actual sin hipótesis
congelada. También valida indirectamente el diagnóstico previo de la auditoría
SMC vs LuxAlgo: la calibración por temporalidad del dealing range de NexUX es
una diferencia real con lo enseñado. Ninguna diferencia autoriza cambios al
Bot — de acuerdo.

---

## 10. Revisión por hipótesis del backlog

- **HYP-BT-LIQ-EXT-001 (liquidez exterior / bloque trampa):** soporte E0
  sólido y ahora visual (gates #3 y #4). Prioridad 1 justificada — es el
  concepto de mayor valor incremental. Definiciones pendientes bien
  identificadas (distancia, tipos, disponibilidad causal).
- **HYP-BT-IBOS-001 (toma izquierda / crea derecha):** soportada; el bloqueo
  declarado (definir "crea liquidez" sin velas futuras) es exactamente el
  punto duro; el control adversarial con niveles aleatorios es apropiado.
- **HYP-BT-FRESH-001 (primer uso):** concepto confirmado, pero **debe
  re-citarse a S04 01:04:22–01:10:01** (M-1) antes de cualquier prerregistro.
- **HYP-BT-FRACTAL-001:** al diseñarla, separar anclaje (mecha/cuerpo) y
  tolerancia de toque como parámetros distintos (m-4).
- **HYP-BT-RANGE-001:** la condición de no arrancar hasta resolver
  cuerpo/mecha visual quedó satisfecha en lo principal; la prohibición de
  reconstruir la revisión de S09 sigue vigente.
- **HYP-BT-TWOENTRY-001:** sube de interés dado M-2 (el docente la enuncia
  como regla universal); el diseño de tres brazos (1 entrada / 2 con riesgo
  constante / 2 con riesgo duplicado como control) es correcto.
- **CONFLUENCE / ENTRY / SCALE / OBTF:** sin objeciones; los bloqueos
  declarados son los correctos.
- Los requisitos de prerregistro del backlog (dataset congelado, causalidad,
  costos, regla de parada, análisis único) son consistentes con la disciplina
  del laboratorio. Mantener el límite de **máximo dos hipótesis** propuesto
  por `FINAL_REVIEW.md` (LIQ-EXT-001 e IBOS-001).

---

## 11. Cambios recomendados al estudio (no ejecutados por restricción)

1. Corregir la cita de frescura/primer uso del playbook §9 → S04
   01:04:22–01:10:01 (+S05 00:32:12–00:33:02 para persistencia al refinar).
2. Reescribir la entrada de "dos entradas": regla enunciada como universal por
   el docente (S08 00:52:30–00:53:53, "siempre siempre siempre", 0,5+0,5;
   stop doble = fin del día), manteniendo su estado amarillo operacional.
3. Completar ficha S11 con los literales omitidos de la fórmula: ideal 70 %,
   ejemplo 105x/79,8 %, "+ comisión", justificación anti-liquidación de la
   lámina vs atribución oral a comisiones, y la aceptación de liquidación.
4. Separar en ficha S02/glosario el anclaje Fibonacci de la tolerancia del
   toque, con sus dos ventanas de evidencia.
5. Añadir a la regla de diez velas: conteo en la TF de la zona, matiz
   "por dentro", y el descargo del propio docente ("es un dato no más").
6. Actualizar `FINAL_REVIEW.md`: gate visual principal cerrado (6/6) con las
   posiciones de §3 de este documento.

Tras aplicar 1–5 se puede congelar `playbook.v1` conforme a la recomendación
de la revisión final.

---

## 12. Gate visual pendiente (lista exacta restante)

El gate principal de 6 ítems está **cerrado** (§3). Quedan pendientes solo los
ítems secundarios listados en las fichas, ninguno bloqueante para
`playbook.v1` pero sí previos a operacionalizar la regla correspondiente:

- **S01:** 00:39:37–00:43:05 (multi-timeframe); 01:07:03–01:10:27 (mapa de
  variables); 01:22:02–01:25:24 (config. Fibonacci).
- **S02:** 00:35:41–00:40:04 (fractal interno); 00:45:15–00:59:01 (ejemplos
  diarios); 01:33:43–01:46:00 (correcciones a alumnos).
- **S03:** 00:18:33–00:21:54 (válido vs fuerte); 01:13:14–01:15:46 (dos
  variantes de finalización); 01:22:56–01:24:54 (cuerpo vs mecha);
  01:34:55–01:42:46 (mapeo práctico).
- **S04:** 00:02:49–00:10:29 (cuatro requisitos); 00:10:42–00:18:23
  (construcción FVG/POI); 00:21:46–00:24:50 (cuatro tipos de OB);
  00:30:51–00:44:42 (integración con rango).
- **S05:** 00:03:57–00:08:11 (grupos de liquidez); 00:14:18–00:23:08
  (trendlines/EQH-EQL); 00:38:10–00:44:18 (multi-TF); 00:47:47–01:05:27
  (mapa completo).
- **S06:** 00:17:57–00:21:12 (tabla de temporalidades); 00:31:54–00:43:06
  (geometría stop/target); 00:43:13–00:50:50 (confirmación multi-TF);
  00:52:30–00:56:56 (diez velas); 00:59:17–01:16:29 (ejemplo D→H1);
  01:20:07–02:00:00 (replay).
- **S07:** 00:03:46–00:18:16 (rango H4/M15 y 50 %); 00:42:00–00:58:00
  (replay); 00:57:08–01:01:04 (zonas consumidas).
- **S08:** 00:04:34–00:35:40 (los seis patrones completos; solo se verificó
  la geometría central); 00:42:02–01:10:00 (ejemplos reales).
- **S09:** las cuatro ventanas de la ficha (estructuras alternativas,
  transición H4/M15, conflicto D/H4/M15, rangos anidados no congelados).
- **S10:** 00:16:43–00:55:00 (replay); 01:31:40–01:41:28 (columnas de la
  plantilla); 01:41:28–01:44:00 (iBOS/swing por mecha).
- **S11:** 00:31:14–00:35:00 (plantilla activo/TF); 00:36:06–00:45:55 (tabla
  de riesgo); 02:00:00–02:13:20 (matriz de consistencia); 02:28:11–02:31:00
  (división 0,25+0,25).

El pipeline de acceso quedó demostrado; cualquiera de estos ítems es
capturable con el mismo método cuando la regla asociada pase a prerregistro.

---

## 13. Recomendación final

1. **Aceptar el estudio** con las correcciones documentales 1–5 de §11
   (responsabilidad de Codex, que es quien mantiene esos archivos).
2. **Congelar `playbook.v1`** después de esas correcciones — el gate visual
   principal ya no es impedimento.
3. **Prerregistrar como máximo dos hipótesis** (HYP-BT-LIQ-EXT-001 y
   HYP-BT-IBOS-001), cada una con protocolo congelado según los requisitos del
   backlog, como estudios de laboratorio (forward/append-only), sin tocar Bot
   ni cohortes vigentes.
4. **Mantener la fórmula de futuros excluida permanentemente** (`NO
   OPERACIONALIZAR`), ahora con confirmación visual y aritmética de por qué.
5. Nada de este material constituye señal, edge demostrado ni autorización
   para Bot/Testnet/Live; ECON-COHORT-001 sigue intocada y NO LIVE vigente.

---

*Fin de la revisión. Este archivo es el único artefacto creado; no se modificó
ningún documento del estudio ni componente de NexUX.*
