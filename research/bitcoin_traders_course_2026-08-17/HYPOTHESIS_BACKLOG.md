# Backlog de hipotesis - Bitcoin Traders SMC

`research_only` | `not_preregistered` | `no_bot` | `no_shadow`

Este archivo convierte afirmaciones del curso en preguntas. No declara edge y no
autoriza pruebas hasta que cada hipotesis tenga protocolo propio.

## Prioridad 1 - valor incremental sobre NexUX

### HYP-BT-LIQ-EXT-001 - Liquidez exterior y bloque trampa

**Afirmacion docente:** un OB con liquidez pendiente detras tiene mayor riesgo de
ser atravesado; refinarlo no elimina la trampa.

**Comparacion candidata:** POI NexUX base frente a POI base estratificado por
liquidez exterior causal.

**Definiciones pendientes:** distancia maxima, tipos admitidos (trendline,
EQH/EQL, partial-FVG high/low), timeframe y momento de disponibilidad.

**Metricas:** activacion, stop-before-target, AvgR, PF, MFE/MAE y tiempo a barrido.

### HYP-BT-IBOS-001 - iBOS toma izquierda y crea derecha

**Afirmacion docente:** una confirmacion valida toma liquidez a la izquierda y
crea liquidez a la derecha.

**Comparacion candidata:** CDC actual frente a CDC + toma izquierda, CDC +
creacion derecha y CDC + ambas.

**Control adversarial:** niveles aleatorios conservando densidad y distancia.

**Bloqueo:** definir `crea liquidez` sin utilizar velas posteriores no disponibles
en el instante de entrada.

### HYP-BT-FRESH-001 - Primer uso efectivo de la zona

**Afirmacion docente:** una zona se prefiere una sola vez; un OB HTF puede contener
varias zonas LTF independientes.

**Evidencia:** S04 01:04:22-01:10:01 para zona no mitigada/nuevo extremo; S05
00:32:12-00:33:02 para persistencia del bloque trampa al refinar.

**Comparacion candidata:** primer toque LTF, segundo toque de la misma zona LTF y
toques a zonas LTF diferentes dentro del mismo OB HTF.

**Bloqueo:** identidad estable de zona y regla de solapamiento.

## Prioridad 2 - representacion estructural

### HYP-BT-FRACTAL-001 - Retroceso minimo de 50%

Comparar swings confirmados actuales con fractales que ademas alcanzan 50% antes
de continuacion. Separar activacion, calidad y target; evitar condicionar con el
movimiento que se intenta predecir.

### HYP-BT-RANGE-001 - Rango causal del curso

Construir una representacion append-only de:

```text
toma de liquidez -> strong extreme -> finalizacion -> weak target -> BOS/update
```

No iniciar hasta resolver visualmente cuerpo/mecha y congelar si se estudia la
version enseñada o la revision futura mencionada en S09. La revision futura no
esta disponible y no debe reconstruirse.

### HYP-BT-CONFLUENCE-001 - Fractal y rango alineados

Estratificar setup por acuerdo, desacuerdo y desconocido. La hipotesis docente es
que el desacuerdo puede representar manipulacion; no usar esa palabra como label.

## Prioridad 3 - geometria y ejecucion

### HYP-BT-ENTRY-001 - Riesgo frente a confirmacion

Comparar mismo POI y mismo target bajo:

- primer toque a riesgo;
- confirmacion LTF;
- no fill por confirmacion tardia.

Incluir costos reales, fill, slippage, MAE/MFE y oportunidad perdida.

### HYP-BT-SCALE-001 - Tamaño de estructura confirmante

Medir si confirmacion micro frente a interna mayor cambia MFE, duracion y target
alcanzado. No usar target posterior para escoger la escala.

### HYP-BT-OBTF-001 - OB M15 frente a M30/H1

Comparar zona estrecha con su agregacion superior. Requiere una regla de nesting
predefinida; no seleccionar el timeframe que mejor contiene el giro a posteriori.

### HYP-BT-TWOENTRY-001 - Dos zonas y riesgo dividido

Comparar una entrada, dos entradas con riesgo total constante y dos entradas con
riesgo duplicado. Solo la segunda representa de forma defendible la sugerencia
del curso; la tercera es un control de sobreexposicion.

## Conocimiento negativo a preservar

- Una etiqueta `alta probabilidad` no es un label.
- Que el precio reaccione no demuestra que el bloque fuera valido.
- Un stop no invalida retrospectivamente el analisis.
- Una zona con cuatro requisitos puede seguir fallando.
- El profesor corrige mapas; sus anotaciones no son labels infalibles.
- La muestra propuesta en clase no reemplaza costos, holdout ni intervalos.

## Requisitos para cualquier pre-registro

Antes de ejecutar una hipotesis se debe congelar:

- dataset y fingerprint;
- unidad de observacion;
- disponibilidad causal de cada feature;
- algoritmo exacto y parametros;
- baseline y controles;
- costos;
- split, purging y embargo;
- metrica primaria y criterios de promocion/descarte;
- regla de parada;
- analisis unico al cierre.

## Estado

`BACKLOG ONLY / NO EXPERIMENT AUTHORIZED`
