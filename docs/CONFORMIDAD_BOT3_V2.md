# Conformidad pre-implementacion - Bot3.v2

**Fecha:** 2026-08-17
**Protocolo revisado:** `docs/BOT3_V2_PROTOCOLO.md`
**Commit:** `242047c`
**SHA-256 verificado:** `ef267f23583d4a36eca46bacb4f51fabdaaecf81955ebb5d079f0aee083998ea`
**Diseno rev.3:** SHA-256 `5dc40f0bcf2f0349b294575307de4596c836372c3b22aa3b34e388f8adb6cfe8`

## Veredicto

`NO CONFORME - CORRECCIONES CONTRACTUALES REQUERIDAS`

CF-1..CF-5 cierran la intencion de las cinco observaciones previas, pero el
protocolo todavia permite que dos implementaciones honestas produzcan libros,
identidades o costos diferentes. No se autoriza implementacion ni apertura de
cohorte.

## Hallazgos bloqueantes

### B-1 - La profundidad historica todavia puede cambiar el rango rector

CF-1 elimina correctamente el fallback explicito al inicio de la ventana, pero
define la ruptura opuesta previa "dentro de la serie disponible" sin congelar
el origen, cobertura minima o estado persistente de esa serie. Una
implementacion con mas historia puede encontrar una ruptura opuesta y construir
un rango mientras otra, con menos historia, se abstiene. Ambas cumplirian el
texto.

Debe congelarse una unica regla reproducible, por ejemplo: dataset y fecha de
inicio canonicos por mercado, o estado estructural append-only derivado desde
un genesis versionado. Si falta la cobertura exigida, la unica salida valida es
`historia_insuficiente`.

### B-2 - Falta una precedencia global para eventos disponibles en el mismo cierre

El protocolo fija recorridos e inclusividad, pero no el orden cuando en la
misma vela coinciden, entre otros:

- fill y cambio/expiracion de direccion H4;
- fill y vencimiento del deadline;
- salida de una posicion y aparicion de un candidato nuevo;
- invalidacion, iBOS y creacion de zona derivada;
- SL, TP y cierre del experimento.

CF-5 hace elegible la vela del deadline, pero el diseno tambien ordena cancelar
al vencerlo. Sin una maquina de estados y una tabla de precedencia, dos motores
pueden aceptar o cancelar la misma orden. Debe congelarse el orden de evaluacion
por vela y por estado. Los eventos conocidos solo al cierre no pueden cancelar
retroactivamente un fill intravela anterior sin una regla explicita.

## Hallazgos mayores

### M-1 - El precio de funding puede depender de informacion posterior

CF-4 usa el cierre de "la vela M15 que contiene" el timestamp de funding. Para
un devengo a las 08:00 UTC esto puede interpretarse como la vela que abre a las
08:00 y cierra a las 08:15, usando informacion posterior al devengo e incluso a
una salida dentro de esa vela. Tambien es ambiguo un fill o salida en la misma
vela del timestamp.

Debe identificarse la vela por desigualdades exactas. Una opcion causal es el
cierre M15 cuyo `close_time == k`. Asimismo debe congelarse la inclusion cuando
fill, salida y devengo comparten timestamp o vela.

### M-2 - Los hashes jerarquicos no tienen serializacion canonica

El contenido logico de `candidate_id`, `order_id` y `trade_id` esta definido,
pero no su representacion en bytes. JSON con espacios, orden de claves,
separadores decimales, casing del mercado o representacion de precios puede
producir hashes distintos.

Debe congelarse algoritmo y preimagen: UTF-8, JSON canonico, orden de claves,
separadores, nombres normalizados, timestamps enteros y precios como decimal de
seis posiciones. Tambien debe declararse SHA-256 hexadecimal minusculo.

### M-3 - Redondeo, SL y unidad R no cierran todos los calculos

El protocolo fija seis decimales para comparaciones, pero no establece si E, S,
T, fills, fees y PnL se calculan con valores crudos o cuantizados, ni en que
paso se redondean. El buffer del SL se expresa como `+/-0,1%`, sin formula
normativa para largo y corto. Esto afecta arbitraje, IDs, filtro RR y resultado.

Debe definirse, como minimo:

- `S_long = extremo * (1 - 0.001)` y `S_short = extremo * (1 + 0.001)`, o la
  formula elegida;
- precision interna y politica de redondeo;
- valores cuantizados que entran en IDs y comparaciones;
- ausencia de redondeo intermedio en fees/PnL, con redondeo solo de salida, si
  esa es la politica elegida.

### M-4 - El corte temporal no tiene un instante normativo

`2026-12-31` no define zona horaria, hora ni si el limite es inclusivo. Debe
convertirse en un timestamp UTC exacto y congelar el tratamiento de posiciones
abiertas y cierres ocurridos exactamente en el limite.

## Evaluacion de CF-1..CF-5

- **CF-1:** parcialmente conforme; abstiene sin ruptura opuesta, pero falta
  congelar cobertura/genesis historico.
- **CF-2:** conforme para precios de salida aislados; requiere la precedencia
  global de B-2 para simultaneidades.
- **CF-3:** conforme en la eleccion de riesgo planificado; requiere la politica
  numerica de M-3.
- **CF-4:** ecuaciones nominales conformes; devengo y precio de funding no son
  todavia univocos.
- **CF-5:** limites de recorrido conformes; el conflicto deadline/fill depende
  de la precedencia faltante.

## Hash y vigencia

SHA-256 del texto, commit Git y regla "cambio = v3 + cohorte nueva" son un
mecanismo suficiente de pre-registro una vez que el contrato sea conforme. El
archivo actual no debe editarse para cambiar su estado: la version corregida
debe publicarse como protocolo v3 candidato, con hash nuevo y una nueva pasada
de conformidad. Este informe vincula explicitamente el dictamen al hash v2
revisado.

## Estado

- Bot3.v1: `SUSPENDIDO`.
- Bot3.v2: `NO IMPLEMENTADO`.
- Cohorte v2: `NO INICIADA`.
- Protocolo v2 (`ef267f...`): `NO CONFORME`.
- Implementacion: `NO AUTORIZADA`.
