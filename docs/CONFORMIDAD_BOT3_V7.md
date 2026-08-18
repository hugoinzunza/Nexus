# Conformidad pre-implementacion - Bot3.v7 candidato

**Fecha:** 2026-08-17
**Protocolo revisado:** `docs/BOT3_V7_PROTOCOLO.md`
**Commit:** `0f5f363`
**SHA-256 verificado:** `c9ea96be4d0b2041b4e26edbd8eb7e4b9964c6e0735853213f451320c67c5921`
**Informe v6:** SHA-256 `12fc534c7fc0cb0ca49d4133edc86426a0fdaa11165499c860f87a39e8ce7828`

## Criterio de cierre aplicado

Esta pasada adopta expresamente el criterio propuesto: solo bloquean una nueva
version los defectos que pueden cambiar el libro, romper causalidad, impedir la
regla pre-registrada de parada o hacer imposible la reconstruccion cientifica.
Los riesgos puramente operacionales con semantica ya congelada pasan a gates de
implementacion y re-auditoria.

## Veredicto

`NO CONFORME - DOS CIERRES CAUSALES/DE PARADA REQUERIDOS`

La v7 cierra correctamente los tres bloqueantes y los tres mayores de v6. El
snapshot fija el ancla M15, la identidad universal cubre la barrera, el marcador
incluye prueba causal y los heads se seleccionan por prefijo. Todos los vectores
CF-30 y CF-31 fueron recalculados y coinciden exactamente.

Persisten dos contradicciones que cumplen el umbral de bloqueo acordado: el
tiempo de procesamiento de catch-up no puede tomar el valor que declara CF-33,
y una caida parcial del exchange puede impedir para siempre tanto la finalidad
de lotes como el corte administrativo. No se autoriza aun implementacion ni
cohorte.

## Hallazgos bloqueantes

### B-1 - `processed_at` no representa el procesamiento de catch-up

CF-33 define `processed_at = close_time` del lote en curso. En catch-up, el lote
atrasado conserva su timestamp original `T`; por definicion, asignar
`processed_at = T` produce `processed_at = effective_at`, no
`processed_at > effective_at` como afirma la linea siguiente.

Ejemplo normativo:

1. falta BTC en el lote `T`;
2. el hueco se vuelve observable con prueba hasta `T+45m`;
3. el motor procesa entonces el lote atrasado `T`;
4. la regla actual escribe `processed_at=T`, ocultando los 45 minutos de
   retraso.

Esto no es solo telemetria: la v7 rotula la cohorte como descriptiva
precisamente porque necesita distinguir efectividad de disponibilidad real.
La temporalidad actual haria parecer causalmente emitida en `T` una decision
reconstruida despues de observar el watermark.

Debe congelarse al menos:

- `effective_at = T` del evento/modelo;
- `finalized_at` o `available_at` = timestamp de mercado que hizo finalizable
  el lote (`T` si estaba completo; maximo de las pruebas de hueco si espero);
- `processed_at` = timestamp observado del ciclo/pull que materializo el
  evento, solo para latencia operacional.

La latencia cientifica determinista debe usar `finalized_at - effective_at`.
`processed_at` puede reportarse aparte y no debe participar en IDs ni decisiones.

CF-32 tambien necesita dos referencias explicitas durante catch-up:

- `input_head_asof_T`: ultimo head consumible por el modelo en `T`, sin datos
  futuros;
- `provenance_head_at_finality`: head que contiene el marcador/prueba que
  libero el lote.

Un unico head causal que excluye el marcador no puede demostrar por que el lote
se proceso; incluir el marcador en el head de inputs introduciria evidencia
posterior. Separarlos preserva ambas propiedades.

### B-2 - La regla de parada queda bloqueada en una caida parcial amplia

CF-29 resuelve el silencio de un mercado cuando al menos cuatro de los otros
seis entregan evidencia. Pero existe un estado no cubierto:

- solo uno, dos o tres mercados siguen publicando despues de `T`;
- los restantes mercados habilitados callan;
- para cada mercado silencioso no existe quorum Q=4, por lo que no se declara
  marcador;
- existen velas posteriores a `T_corte`, por lo que la condicion administrativa
  "no existe ninguna vela posterior" es falsa;
- ningun lote global puede finalizar y el experimento nunca cierra.

La politica de parada pre-registrada deja de ser total. Debe corregirse la
excepcion administrativa para actuar cuando, a `T_corte + 24h`, **no existe un
lote global finalizado posterior a `T_corte`**, independientemente de que haya
velas parciales. En ese caso:

- no se procesan retroactivamente lotes incompletos;
- se congela el ultimo lote global finalizado `<= T_corte`;
- abiertas/ordenes se registran respecto de ese estado;
- las velas parciales posteriores quedan fuera de la cohorte y se reportan como
  degradacion de cobertura;
- `corte_administrativo` conserva la evidencia de reloj y mercados faltantes.

Esto cubre silencio completo y parcial sin cambiar Q=4 ni inventar datos.

## Clarificaciones mayores requeridas

Estas clarificaciones no justifican por si solas otra iteracion, pero deben
incorporarse junto con B-1/B-2 y convertirse en vectores/gates.

### M-1 - La prueba exchange debe identificar quorum y timestamps exactos

CF-29 exige cuatro mercados de referencia, mientras CF-31 guarda solo tres
timestamps. Ante gaps en los mercados de referencia, dos implementaciones
pueden escoger distintos mercados/timestamps probatorios y producir marcadores
con el mismo significado pero distinta provenance.

Congelar que la prueba exchange contiene los Q mercados calificantes (orden
alfabetico; si hay mas, los cuatro primeros) y, para cada uno, los tres
`close_time` exactos requeridos. `detected_at` es el maximo de esa estructura.
El marcador y su hash deben cubrirla. Para prueba local, usar siempre los tres
primeros timestamps cronologicos que satisfacen el watermark.

### M-2 - Completar el registro cerrado de tipos para `event_id`

CF-30 cierra correctamente los eventos nombrados, pero "TODO evento" requiere
un registro exhaustivo. Abstenciones como `rango_sin_origen` pueden no tener
zona, y eventos operacionales como marcador/mercado_degradado no encajan
necesariamente en la preimagen de descarte con `zona_*` obligatoria.

La implementacion debe partir de un enum/versionado de todos los tipos y una
preimagen exacta por familia. Ningun evento puede caer en una serializacion ad
hoc. El gate de crash debe recorrer al menos un ejemplar de cada familia.

## Cierres confirmados respecto de v6

- **B-1 anterior (ancla M15):** cerrado por snapshot versionado, commit y hash.
- **B-2 anterior (silencio):** cerrado para silencio individual con quorum;
  falta hacer total la parada ante caida parcial amplia.
- **B-3 anterior (barrera):** cerrado para los tipos definidos y sus vectores.
- **M-1 anterior (prueba de hueco):** el marcador ya cubre la evidencia; falta
  hacer univoca la prueba exchange.
- **M-2 anterior (head catch-up):** cerrado para inputs as-of; requiere separar
  provenance de finalidad.
- **M-3 anterior (latencia):** la intencion esta cerrada, pero la ecuacion de
  `processed_at` no puede producir el resultado declarado.

## Vectores y hashes verificados

- Protocolo v7: SHA-256 exacto `c9ea96be4d0b2041b4e26edbd8eb7e4b9964c6e0735853213f451320c67c5921`.
- CF-30: los cuatro `event_id` publicados coinciden byte por byte.
- CF-31: `h1`, `h2`, `hg` y `h3` coinciden byte por byte.
- `git diff --check` del commit candidato: limpio.

## Hash y vigencia

El mecanismo de vigencia es suficiente. Las correcciones requieren protocolo
v8, SHA-256 nuevo, commit nuevo y una pasada final bajo este mismo criterio de
cierre. No editar v7 para convertirlo en conforme.

## Estado

- Bot3.v1: `SUSPENDIDO`.
- Protocolo v7 candidato (`c9ea96be...`): `NO CONFORME`.
- Bot3.v7: `NO IMPLEMENTADO`.
- Cohorte: `NO INICIADA`.
- Implementacion: `NO AUTORIZADA`.
