# ZONAS-001 — Grados de zona objetivos (pre-registro)

**Fecha de congelamiento:** 2026-08-15, ANTES de calcular ningún resultado.
`research_only` · sin señal · sin bot · sin promoción automática.

## Por qué existe

La clase 06 enseña zonas "de primer y segundo grado" sin geometría reproducible
(sin fórmula de centro, ancho, contactos, fusión ni prioridad — los apuntes lo
declaran). El gate V de Bot2 demostró con números que sin este catálogo el plan
T+Z+V del curso no es implementable: tratando cada pivote como obstáculo, 0
trades en 4 años. Este estudio fija UNA definición causal de zona y mide si
carga información — o la descarta.

## Definición congelada (no se edita; cambios van en bitácora)

Sobre pivotes confirmados **5+1+5** (el canon de la clase 03; Bot2 v2 usa 3 pero
las zonas del curso son estructura mayor), por timeframe separado (1h, 4h, 1d),
BTC y ETH, con el histórico versionado del repo.

1. **Clúster:** un pivote se une a una zona existente si su precio dista del
   borde más cercano ≤ **0,50 × ATR(14)** del TF en la vela de confirmación del
   pivote. Si no, crea zona nueva. Primario k=0,50; k=0,25 se publica como
   secundario (mini-grilla pre-declarada, las dos celdas se publican).
2. **Bordes:** mínimo y máximo de los precios de los pivotes miembros. Los
   bordes solo se expanden cuando se une un miembro nuevo; toda evaluación usa
   los bordes vigentes en ese `as_of` (causal).
3. **Nacimiento:** una zona existe desde la confirmación de su **segundo**
   miembro. Un pivote solo = **referente puntual** (brazo de comparación).
4. **Grados:** grado 1 = ≥3 miembros; grado 2 = exactamente 2 miembros. El grado
   puede subir al confirmarse miembros nuevos; nunca baja.
5. **Ruptura:** cierre más allá del borde lejano por ≥ **0,25 × ATR** (el mismo
   umbral causal de HYP-TREND-001). Una zona rota deja de contar toques hasta
   ser reclamada (cierre de vuelta dentro). Estados: activa → rota → reclamada.
6. **Sin expiración**; la edad se registra.

## Evento y métrica congelados

- **Toque:** primera vela cuyo rango solapa la zona viniendo desde fuera (el
  cierre previo estaba más allá del borde cercano). Solo zonas activas.
- **Reacción:** dentro de las **12 velas** siguientes, el precio se aleja del
  borde cercano en dirección contraria a la aproximación ≥ **1,0 × ATR** ANTES
  de que un cierre rompa el borde lejano por ≥0,25 ATR. Si no ocurre ninguna de
  las dos en 12 velas: no-reacción.
- **Métrica primaria:** Δ tasa de reacción = P(reacción | toque de zona grado 1)
  − P(reacción | toque de placebo), con IC95 bootstrap por bloques mensuales
  (5.000 iteraciones, semilla 7, determinista).
- **Placebo:** bandas del mismo ancho que las reales, centradas en el punto
  medio entre zonas reales consecutivas (determinista, sin RNG), excluyendo
  solapes con zonas reales. Mismo criterio de toque y reacción.
- **Brazos publicados:** grado 1, grado 2, referente puntual, placebo — por TF y
  por par. Corte IS (pre-2025) / OOS (2025+), fijado ahora.

## Criterio de lectura, congelado

- **La definición "carga información"** solo si el Δ primario (grado 1 vs
  placebo) tiene IC95 con borde inferior > 0 **en OOS**, en al menos 2 de los 3
  TF, para ambos pares o el agregado con bloques mensuales.
- Si falla: la definición se descarta y el gate Z sigue no implementable — ese
  resultado también se publica y también es un éxito del estudio.
- Grado 1 debe superar además al referente puntual (si una banda no informa más
  que su pivote suelto, el concepto de "zona" no aporta).
- **Ninguna celda se elige a posteriori**: primario es k=0,50 / grado 1 /
  reacción 1,0 ATR / H=12. Todo lo demás es secundario y se publica completo.
- Nada se promueve a Bot2, Inteligencia ni al Diario desde este estudio; una
  eventual integración exigiría su propio pre-registro (ZONAS-002+).

## Predicciones registradas ahora

| Pregunta | Predicción |
|---|---|
| ¿Grado 1 > placebo? | Incierta; si el efecto existe, esperable pequeño (los estudios previos de niveles — refugios, rejilla — no superaron controles) |
| ¿Grado 1 > puntual? | Escéptica: el ancho puede ser ruido más que información |
| ¿1d > 1h? | Sí, si algo funciona: menos ruido y menos toques triviales |

La casa ya aprendió que "varios descriptores coinciden" no es evidencia; este
estudio existe para medir, no para confirmar.

---

## Resultados (2026-08-15, posteriores al freeze — harness `zonas_crecetrader.py`)

Primario (k=0,50, grado 1 vs placebo, OOS 2025+, IC95 por bloques mensuales):

| TF | grado1 n / tasa | placebo n / tasa | Δ | IC95 | ¿Borde inferior > 0? |
|---|---|---|---|---|---|
| 1h | 4.184 / 0,733 | 226 / 0,686 | +0,047 | [−0,011; +0,109] | no |
| 4h | 861 / 0,714 | 41 / 0,634 | +0,080 | [−0,129; +0,274] | no |
| 1d | 117 / 0,650 | 18 / 0,500 | +0,150 | [−0,069; +0,373] | no |

Secundario (k=0,25): única celda con borde en cero exacto (4h, [+0,000; +0,183]),
1 de 3 TF, en el brazo secundario. Grado 1 tampoco supera al referente puntual de
forma consistente (positivo solo en 1h primario; negativo en 4h secundario).

### Veredicto según el criterio congelado

**La definición se descarta.** Exigía borde inferior > 0 en ≥2 de 3 TF en el brazo
primario; obtuvo 0 de 3. El gate Z sigue no implementable — ahora con evidencia
propia, no solo por ausencia de definición.

Observación estructural honesta: la tasa base de "reacción" es ~70% en TODOS los
brazos, placebo incluido. Con cripto revirtiendo ≥1 ATR en 12 velas la mayoría de
las veces, casi cualquier banda "reacciona". El Δ verdadero de una zona, si
existe, es pequeño frente a esa base — consistente con la predicción escéptica
registrada y con los estudios previos de niveles (refugios, rejilla) que tampoco
superaron sus controles.

### Consecuencias

1. Tercera línea independiente de evidencia contra "niveles con información
   propia" en este stack (refugios 2026, rejilla anual, zonas CreceTrader).
2. El gate V verdadero de Bot2 queda **bloqueado con honestidad**: sin catálogo Z
   con información demostrada, recortar targets a "obstáculos" no tiene base.
3. Una definición distinta de zona (volumen, tiempo de permanencia, confluencia
   multi-TF) exigiría ZONAS-002 con nuevo pre-registro. Este no se edita.
