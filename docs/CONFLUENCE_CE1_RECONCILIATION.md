# NexUX Confluence Engine — CE-1 Reconciliation

Estado: **A. CE-1 REVISED AND READY FOR AUTHORIZATION REVIEW**

Fecha: 2026-08-08

Alcance: reconciliacion semantica entre `CONFLUENCE_ENGINE_DISCOVERY.md` y la
restriccion cientifica establecida por
`../nexux-trading-intelligence-lab/docs/CONFLUENCE_SCIENTIFIC_REVIEW.md`.

Este documento revisa el diseno conceptual del Gate CE-1. No autoriza ni
implementa CE-1. No crea contratos, schemas, fixtures, conexiones, cohortes ni
integraciones.

---

## 1. Proposito de la reconciliacion

El Discovery identifico correctamente la necesidad de normalizar observaciones
heterogeneas, conservar provenance y freshness, resolver linaje, representar
contradicciones y abstenerse cuando la evidencia descriptiva sea insuficiente.

La Scientific Review acepto esa finalidad descriptiva, pero establecio una
restriccion cientifica decisiva: un contrato puede introducir doble conteo y
supuestos invalidos incluso sin contener scores, probabilidades o acciones. La
mera separacion por modulo, proveedor o familia no demuestra independencia.

Esta reconciliacion incorpora esa restriccion al alcance de CE-1. El Gate queda
redefinido para demostrar correccion representacional, no valor predictivo.

La pregunta de CE-1 pasa a ser:

> ¿Puede NexUX representar observaciones descriptivas preservando su linaje,
> dependencia, disponibilidad causal, comparabilidad temporal, faltantes y
> contradicciones sin convertir multiplicidad en confirmacion?

CE-1 no responde:

> ¿La coincidencia de observaciones aumenta la probabilidad de un resultado?

Esa segunda pregunta requeriria un protocolo cientifico posterior, separado y
expresamente autorizado.

## 2. Dictamen reconciliado

**Estado final: `A. CE-1 REVISED AND READY FOR AUTHORIZATION REVIEW`.**

Este estado significa exclusivamente que:

- las modificaciones cientificas requeridas ya estan incorporadas al diseno del
  Gate;
- CE-1 puede volver a presentarse para una autorizacion formal de implementacion;
- todavia no existe autorizacion para implementarlo;
- no se ha demostrado independencia estadistica, causal o informacional;
- no se ha demostrado utilidad predictiva ni operativa.

## 3. Redefinicion de CE-1

CE-1 queda definido como un **Gate de representacion descriptiva, lineage,
dependencia y causal availability**.

Su responsabilidad futura, si se autoriza, sera validar que una representacion
normalizada pueda:

1. identificar cada observacion y su provenance;
2. conservar sus entradas y transformaciones conocidas;
3. expresar relaciones estructurales entre observaciones;
4. distinguir multiplicidad de independencia;
5. conservar los tiempos relevantes sin leakage;
6. determinar si dos observaciones son temporalmente comparables;
7. representar faltantes, staleness, dependencia desconocida y abstencion;
8. describir alineacion, coexistencia, divergencia o contradiccion sin atribuir
   efecto sobre resultados futuros.

CE-1 no es un mecanismo para acumular "confirmaciones". Tampoco cuenta familias,
fuentes, modulos u observaciones como votos.

## 4. Principio cientifico rector

La Scientific Review distingue una propiedad descriptiva de una propiedad
predictiva:

- **co-ocurrencia:** varias observaciones satisfacen predicados predefinidos
  dentro de una regla temporal explicita;
- **incremento predictivo:** la combinacion cambia la probabilidad de un outcome
  respecto de baselines adecuados.

CE-1 solo puede representar la primera. La segunda no puede inferirse del
contrato, del vocabulario, del numero de observaciones ni de su clasificacion.

En consecuencia:

> Multiplicidad de observaciones no equivale a multiplicidad de evidencia
> independiente.

Y tambien:

> Co-ocurrencia no equivale a aumento de probabilidad.

## 5. Independencia: definicion permitida

Dentro de CE-1, `independent` significa exclusivamente:

> `no known structural dependency within represented lineage`

Esta etiqueta declara el limite del conocimiento representado por el contrato.
Nunca significa:

- independencia estadistica demostrada;
- independencia causal demostrada;
- independencia informacional demostrada;
- baja correlacion;
- informacion incremental;
- mayor fuerza descriptiva;
- mayor confianza;
- mayor probabilidad de un outcome.

Dos observaciones no son `independent` por pertenecer a familias diferentes,
venir de proveedores diferentes o ser producidas por modulos diferentes. La
ausencia de una dependencia conocida solo permite usar `independent` cuando el
linaje representado es suficientemente completo para sostener exactamente esa
afirmacion limitada. En cualquier otro caso corresponde `unknown`.

## 6. Relaciones estructurales obligatorias

El modelo revisado debe poder expresar como minimo estas relaciones:

| Relacion | Significado descriptivo |
|---|---|
| `derived` | Una observacion es transformacion o descendiente conocido de otra entrada u observacion. |
| `shared_source` | Las observaciones comparten una fuente, entrada o familia de datos materialmente comun. |
| `partially_dependent` | Existe solapamiento de entradas, mecanismo, ventana o driver conocido, sin dependencia total representada. |
| `independent` | No existe dependencia estructural conocida dentro del linaje efectivamente representado. |
| `unknown` | La informacion disponible no permite clasificar la dependencia. |

Estas relaciones no forman una escala de calidad. No asignan pesos y no ordenan
observaciones de mejor a peor.

La relacion debe conservar, cuando corresponda:

- observaciones relacionadas;
- raw inputs o clases de raw input compartidas;
- parent/child lineage;
- transformacion y version;
- lookback o ventana solapada;
- fundamento descriptivo de la clasificacion;
- alcance y limite de lo conocido.

Una observacion puede mantener relaciones distintas con diferentes
observaciones. El contrato no debe forzar una unica etiqueta global cuando la
dependencia es relacional.

## 7. `unknown` como estado de primera clase

`unknown` es un resultado valido y necesario, no un error que deba completarse.
Debe poder aparecer, al menos, en:

- dependencia;
- provenance incompleta;
- disponibilidad causal;
- freshness;
- cobertura;
- comparabilidad temporal;
- estado descriptivo;
- precision de timestamps;
- relacion entre fuentes o transformaciones.

No debe existir fallback que convierta `unknown` en una categoria mas comoda.
Su presencia debe sobrevivir normalizacion, agrupacion y proyeccion.

## 8. Semantica temporal causal

El Discovery separaba `effective_at_ms`, `observed_at_ms`, `valid_from_ms`,
`stale_at_ms` y `expires_at_ms`. La Scientific Review exige hacer explicita la
disponibilidad causal. La reconciliacion adopta los siguientes relojes o
semanticas equivalentes:

| Campo conceptual | Pregunta que responde |
|---|---|
| `effective_at_ms` / event time | ¿Cuando ocurrio o se hizo efectivo el hecho segun la fuente? |
| `source_timestamp_ms` | ¿Que timestamp declaro la fuente? |
| `observed_at_ms` | ¿Cuando NexUX recibio u observo el dato? |
| `available_at_ms` | ¿Desde que instante podia conocerlo causalmente el sistema? |
| `computed_at_ms` | ¿Cuando se produjo la transformacion? |
| `valid_from_ms` | ¿Desde cuando satisface el estado descriptivo declarado? |
| `stale_at_ms` | ¿Desde cuando deja de considerarse vigente bajo su politica de freshness? |
| `expires_at_ms` | ¿Desde cuando deja de ser utilizable en una comparacion vigente? |

`available_at_ms` es obligatorio cuando event time y knowledge time pueden
diferir. Es especialmente relevante para pivotes confirmados, velas cerradas,
feeds visuales, publicaciones macro, revisiones y transformaciones con retraso.

Reglas:

1. Nunca sustituir un timestamp ausente por `now`.
2. Nunca usar event time como availability time sin justificacion contractual.
3. Nunca presentar un dato revisado como si hubiera estado disponible en su
   version final desde el evento original.
4. Nunca usar una observacion antes de `available_at_ms`.
5. Nunca ocultar precision inferida o granularidad limitada del timestamp.
6. Nunca mezclar freshness y availability: un dato puede haber estado disponible
   y encontrarse stale, o ser reciente segun la fuente pero todavia no haber sido
   causalmente disponible para NexUX.

## 9. Comparabilidad temporal

La co-ocurrencia solo puede declararse bajo una ventana o regla de comparabilidad
explicita y versionada. CE-1 no puede usar una nocion implicita de "al mismo
tiempo".

La regla debe declarar, como minimo:

- referencia temporal utilizada;
- ventana permitida o criterio de solapamiento;
- granularidad y precision de cada fuente;
- intervalos de validez;
- freshness y expiry aplicables;
- tratamiento de fuentes lentas frente a fuentes rapidas;
- tratamiento de cambios de venue, provider o data vintage;
- resultado cuando falta informacion suficiente.

Dos observaciones solo pueden marcarse `aligned` o `co-occurring` cuando sus
intervalos comparables satisfacen la regla congelada. Si no existe solapamiento,
si una observacion esta stale, si su availability es posterior a la comparacion
o si la precision no alcanza, el resultado debe ser `unavailable`, `stale` o
`unknown`, segun corresponda.

CE-1 no fijara en este documento una tolerancia universal. El futuro contrato
debera hacerla explicita por clase de fenomeno o fixture y evitar que una
tolerancia arbitraria adquiera significado predictivo.

## 10. Taxonomia revisada

Las familias del Discovery se conservan como organizacion descriptiva, no como
clases de independencia:

- `price_structure`;
- `derivatives_positioning`;
- `liquidity_microstructure`;
- `volume_flow`;
- `macro_context`;
- `cross_market_context`.

Cada familia puede contener observaciones redundantes, derivadas o parcialmente
dependientes. Pertenecer a familias distintas no autoriza `independent`.

### `temporal_context`

`temporal_context` deja de ser una evidence family primaria. Pasa a ser una
dimension contextual o de condicionamiento.

Incluye, segun corresponda:

- sesion;
- hora y dia;
- apertura semanal o anual como contexto temporal;
- proximidad a eventos;
- ventanas de funding o expiracion;
- edad y horizonte de una observacion.

No puede contarse como una observacion adicional que "confirma" otra familia.

## 11. Vocabulario canonico revisado

CE-1 debe favorecer vocabulario estrictamente descriptivo:

- `observed`;
- `aligned`;
- `co-occurring`;
- `divergent`;
- `contradictory`;
- `missing`;
- `unavailable`;
- `stale`;
- `unknown`;
- `derived`;
- `shared_source`;
- `partially_dependent`.

Cada termino debe definirse mediante predicados observables, no mediante su
relacion esperada con un outcome.

### Vocabulario retirado o restringido

`confirmation` se retira de la semantica canonica. En trading implica validacion
o aumento de confianza y puede introducir una afirmacion predictiva implicita.

`supportive` y `adverse` se retiran. Ambos califican una observacion respecto de
una tesis o resultado y sugieren peso evidencial.

`invalidation` queda restringido, si fuera imprescindible fuera del vocabulario
canonico, a una regla logica predefinida: el predicado descriptivo dejo de
satisfacerse. Nunca significa que una tesis o trade fue invalidado. Se prefieren
`predicate_no_longer_satisfied`, `state_changed` o `state_expired`.

`convergence` solo podria utilizarse con una definicion contractual puramente
descriptiva de compatibilidad o co-ocurrencia y con una advertencia explicita de
que no implica independencia, fuerza, confianza, probabilidad ni valor
predictivo. Para CE-1 se prefieren `aligned` y `co-occurring`.

## 12. Abstencion como resultado de primera clase

La abstencion no es una excepcion ni una degradacion cosmetica. Es el resultado
correcto cuando el sistema no puede sostener una descripcion dentro de sus
contratos.

Debe abstenerse, entre otros casos, cuando:

- provenance o lineage son insuficientes;
- la dependencia es desconocida y la salida solicitada exige clasificarla;
- falta `available_at_ms` donde es causalmente necesario;
- no existe comparabilidad temporal;
- una fuente esta stale o expired;
- existe un cambio no reconciliado de venue, provider, metodo o vintage;
- la cobertura es parcial y no permite el predicado;
- los timestamps son contradictorios;
- el fixture no contiene evidencia suficiente.

La abstencion debe conservar su motivo y los datos que impidieron la
clasificacion. No debe sustituirse por neutralidad, ausencia de contradiccion ni
independencia.

## 13. Invariantes que CE-1 debe preservar

Un futuro contrato y sus fixtures deberan hacer verificables estas prohibiciones:

- nunca inferir `unknown` -> `independent`;
- nunca inferir `missing` -> `neutral`;
- nunca inferir `stale` -> `current`;
- nunca inferir `different family` -> `independent`;
- nunca inferir `different source` -> `independent`;
- nunca inferir `co-occurrence` -> `increased probability`.

Ademas:

- observaciones del mismo linaje pueden conservarse por trazabilidad, pero su
  numero no representa evidencia independiente;
- una relacion `partially_dependent` no puede redondearse a `independent`;
- una contradiccion no puede resolverse por mayoria;
- la ausencia de contradiccion no equivale a alineacion;
- la presencia de mas familias no equivale a mayor confianza;
- un dato disponible pero stale no participa como observacion vigente;
- una observacion no disponible causalmente no puede entrar en una comparacion;
- ningun nombre de campo puede introducir semantica de outcome por otra via.

## 14. Modelo conceptual revisado

Este ejemplo ilustra la semantica minima reconciliada. No es un schema ni una
autorizacion para crearlo.

```json
{
  "observation_id": "opaque-id",
  "schema_version": "candidate-only",
  "subject": {
    "symbol": "BTCUSDT",
    "venue": "Binance",
    "market": "futures"
  },
  "family": "price_structure",
  "subfamily": "confirmed_pivot",
  "phenomenon": "resistance_zone_observed",
  "measurement_type": "derived",
  "value": {
    "kind": "price_zone",
    "low": 65320.0,
    "high": 65450.0
  },
  "effective_at_ms": 0,
  "source_timestamp_ms": 0,
  "observed_at_ms": 0,
  "available_at_ms": 0,
  "computed_at_ms": 0,
  "valid_from_ms": 0,
  "stale_at_ms": 0,
  "expires_at_ms": 0,
  "source": {
    "provider": "nexux.inteligencia",
    "origin": "binance_futures_vps",
    "method": "confirmed_pivot",
    "source_ref": "opaque-reference"
  },
  "lineage": {
    "lineage_group_id": "binance:BTCUSDT:futures:ohlcv:4h",
    "raw_input_class": "ohlcv",
    "raw_input_ids": ["opaque-input"],
    "transformation_id": "confirmed_pivot",
    "transformation_version": "opaque-version",
    "parent_observation_ids": ["opaque-parent"],
    "lookback_window": "opaque-window"
  },
  "quality": {
    "freshness": "current",
    "coverage": "complete",
    "causal_availability": "known"
  },
  "evidence_status": "descriptive_unvalidated"
}
```

Las relaciones de dependencia deben modelarse como relaciones entre
observaciones o grupos de linaje, no como una afirmacion global de calidad.

Campos o semanticas prohibidos incluyen:

- `buy` / `sell`;
- `entry` / `exit`;
- `position_size`;
- `risk_multiplier`;
- `win_probability`;
- `confidence_score`;
- `evidence_weight`;
- `confirmation_count`;
- ranking o direccion operativa equivalente.

## 15. Cambios respecto del Discovery

### 15.1 Independencia

**Antes:** el Discovery proponia `primary|derived|shared_source` y permitia
considerar independientes observaciones que difirieran materialmente en fuente o
mecanismo.

**Ahora:** la relacion es explicita y relacional:
`derived|shared_source|partially_dependent|independent|unknown`.
`independent` queda limitada a ausencia de dependencia estructural conocida
dentro del linaje representado. No se presume por taxonomia, fuente o modulo.

**Por que:** la Scientific Review demostro conceptualmente que source
independence no es necesaria ni suficiente para independencia estadistica,
causal o informacional.

### 15.2 Multiplicidad y confluencia

**Antes:** el Discovery agrupaba `convergences` y hablaba de condiciones futuras
de confirmacion o invalidacion.

**Ahora:** CE-1 representa `aligned` o `co-occurring`, preserva redundancia y
dependencia, y no acumula confirmaciones. `confirmation` se retira e
`invalidation` se restringe a cambios de predicado o estado.

**Por que:** contar descriptores compatibles puede insinuar fuerza o informacion
incremental sin haberla demostrado.

### 15.3 Stance

**Antes:** el modelo conceptual contenia
`supportive|adverse|mixed|neutral|unknown`.

**Ahora:** se eliminan `supportive` y `adverse`. Los estados deben describir
alineacion, divergencia, contradiccion, ausencia, disponibilidad o desconocimiento
mediante predicados definidos.

**Por que:** `supportive` y `adverse` relacionan el dato con una tesis u outcome e
introducen weighting predictivo implicito.

### 15.4 Tiempo

**Antes:** `valid_from_ms` cubria parcialmente el momento causal de conocimiento.

**Ahora:** se incorpora `available_at_ms` y se mantienen separados event/effective
time, source time, observed time, computed time, validity, freshness y expiry.

**Por que:** un evento puede existir antes de que NexUX pueda conocerlo. Ignorar
esa diferencia permite leakage aun en un sistema descriptivo.

### 15.5 Comparabilidad

**Antes:** se exigia solapamiento de intervalos, sin formalizar completamente la
regla que define simultaneidad entre fuentes heterogeneas.

**Ahora:** toda alineacion o co-ocurrencia requiere una ventana/regla explicita,
versionada y consciente de availability, precision, freshness y horizonte.

**Por que:** sincronizar retrospectivamente fuentes con frecuencias y latencias
distintas puede fabricar simultaneidad.

### 15.6 Taxonomia temporal

**Antes:** `temporal_context` era una familia raiz junto con familias de
observacion.

**Ahora:** es una dimension contextual o de condicionamiento.

**Por que:** sesion, calendario y edad condicionan observaciones; no constituyen
por si mismos evidencia independiente que deba sumarse.

### 15.7 Missingness y abstencion

**Antes:** el Discovery ya defendia `missing`, freshness y abstencion.

**Ahora:** `unknown` y abstencion pasan a ser invariantes transversales con
motivos preservados, y se prohiben explicitamente conversiones a neutralidad,
actualidad o independencia.

**Por que:** missingness y dependencia desconocida pueden ser informativas y no
deben borrarse para obtener una sintesis completa.

### 15.8 Alcance del Gate

**Antes:** CE-1 se proponia como `Observation Contract & Lineage Fixtures`.

**Ahora:** sigue limitado a contratos y fixtures en una futura implementacion,
pero su criterio central es correccion representacional de descripcion, linaje,
dependencia, disponibilidad causal y comparabilidad temporal.

**Por que:** lineage sin semantica de dependencia no evita que una arquitectura
confunda varias representaciones del mismo dato con evidencia adicional.

## 16. Alcance de una futura autorizacion CE-1

Si CE-1 recibe autorizacion formal posterior, podra abarcar exclusivamente:

1. vocabulario descriptivo congelado;
2. contrato candidato fuera del Wire ABI;
3. fixtures sinteticos o congelados, sin fuentes reales;
4. representacion de raw inputs, transformaciones y relaciones de dependencia;
5. semantica temporal con `available_at_ms`;
6. reglas explicitas de comparabilidad;
7. casos redundant, derived, shared-source, partially-dependent, independent y
   unknown;
8. casos missing, unavailable, stale, expired, contradictory y no comparables;
9. abstencion y motivos;
10. invariantes contra doble conteo y semantica predictiva.

El Gate debera validar correccion determinista de representacion. No validara el
mercado ni una estrategia.

## 17. Fuera de alcance

Permanecen expresamente prohibidos en CE-1:

- scores;
- probabilidades;
- weighting predictivo;
- senales;
- recomendaciones;
- ranking;
- decisiones;
- ejecucion;
- Bot;
- fuentes reales;
- endpoints productivos;
- escrituras en productores;
- Aurora;
- integracion real con Trading Intelligence;
- cohortes, backtests o protocolos predictivos;
- EventBus o Wire ABI;
- Railway, VPS o produccion;
- CE-2.

No se autoriza inferir utilidad futura a partir de la aprobacion representacional
de CE-1.

## 18. Criterios revisados para una futura implementacion

Una futura implementacion de CE-1 solo podria aprobarse si demuestra, mediante
fixtures congelados y pruebas deterministas, que:

- toda observacion conserva provenance y lineage suficientes;
- toda observacion causalmente sensible conserva `available_at_ms`;
- los relojes no se colapsan en un unico timestamp;
- la comparabilidad temporal es explicita y reproducible;
- las cinco relaciones estructurales son representables;
- `unknown` nunca se promociona a `independent`;
- derivados y shared-source permanecen identificables despues de normalizar;
- una observacion puede ser preservada sin contarse como evidencia adicional;
- stale, missing y unavailable no se reinterpretan;
- contradicciones conservan todas sus ramas;
- la abstencion es determinista y explicable;
- no existe vocabulario, campo ni salida predictiva;
- no existe score, peso, probabilidad, ranking o accion;
- no existen imports, endpoints ni conexiones con sistemas prohibidos.

Estos criterios verifican semantica e integridad. No constituyen evidencia de
edge.

## 19. Preguntas que permanecen abiertas

La reconciliacion no resuelve anticipadamente:

1. cual es la unidad atomica adecuada: medicion, observacion, concepto o estado
   de familia;
2. como representar inputs parcialmente solapados sin perder trazabilidad;
3. que tolerancia temporal corresponde a cada fenomeno;
4. como comparar observaciones de horizontes diferentes;
5. cuando una medida de liquidez es directa, proxy o derivada;
6. como representar drivers comunes hipoteticos sin declararlos como hechos;
7. como conservar vintages y revisiones macro;
8. que sujeto canonico usar entre activo, instrumento, venue y mercado;
9. quien sera owner del contrato descriptivo;
10. si alguna combinacion aporta informacion incremental sobre outcomes futuros.

La pregunta 10 queda completamente fuera de CE-1.

## 20. Resolucion

**Estado: `A. CE-1 REVISED AND READY FOR AUTHORIZATION REVIEW`.**

El Discovery sigue siendo valido como inventario y direccion arquitectonica
read-only. La Scientific Review actua como restriccion cientifica sobre su
semantica: ninguna multiplicidad, taxonomia o diferencia de fuente puede
convertirse implicitamente en independencia, confirmacion o valor predictivo.

CE-1 queda reconciliado como Gate de representacion descriptiva, lineage,
dependencia y disponibilidad causal. Esta listo para que una autoridad humana
decida si autoriza su implementacion limitada a contratos y fixtures.

Hasta esa autorizacion:

- CE-1 no se implementa;
- no se crean schemas ni fixtures;
- no se conectan fuentes;
- no se inicia CE-2;
- NexUX, Trading Intelligence, Aurora, Bot y produccion permanecen intactos.
