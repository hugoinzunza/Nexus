# Bitcoin Traders SMC frente a NexUX

**Corte:** 2026-08-17<br>
**Proposito:** mapa de equivalencias para investigacion. No autoriza cambios al
Bot, Trading Intelligence ni produccion.

## Resumen

NexUX ya representa buena parte del lenguaje visible del curso, pero no replica
la estrategia completa. La diferencia mayor no esta en detectar FVG u OB: esta en
como el profesor selecciona la estructura rectora, construye rangos desde
liquidez y descarta zonas por liquidez exterior.

| Capa | Curso Bitcoin Traders | NexUX actual | Estado |
|---|---|---|---|
| Swing/fractal | Impulso + retroceso >=50%; escala elegida por objetivo | Pivotes confirmados por lookback | Diferente |
| Estructura | Principal/interna segun horizonte | Swing points y estructura derivada | Parcial |
| Strong/weak | Strong nace de liquidez + rompimiento; weak es target | Niveles strong/weak derivados del rango/pivotes | Parcial |
| Rango | Inicio strong + finalizacion iBOS + continuaciones | Rango reciente y EQ persistente | Diferente |
| Premium/discount | 50% del rango/fractal operativo | EQ local del swing y contexto global | Cercano |
| FVG | Gap de tres velas por no solape de mechas | Deteccion causal de tres velas | Equivalente base |
| OB | Vela opuesta + tipo + liquidez + imbalance | Ultima vela opuesta antes de displacement/FVG | Parcial |
| Liquidez previa | Trendline, EQH/EQL o high/low antes del bloque | Sweep de swing/weak level | Parcial |
| Liquidez exterior | Detras del OB; posible bloque trampa | No modelada como relacion de zona | Ausente |
| Frescura | Preferencia por primer uso efectivo | Mitigated/valid/in-zone | Parcial |
| Confirmacion | HTF->LTF; iBOS toma izquierda y crea derecha | CDC micro tras toque dentro de ventana | Parcial |
| Target | Weak high/low de la estructura elegida | Liquidez opuesta; fallback a rango | Cercano |
| Stop | Invalidez estructural sin buffer formal | Stop estructural + buffer fijo | Diferente |
| Gestion | Riesgo/confirmacion, dos zonas, discrecion | Plan y ejecucion mecanizados | No equivalente |

## Coincidencias fuertes

### POI no equivale a entrada

Ambos sistemas separan deteccion de zona y confirmacion posterior. NexUX conserva
POIs mitigados durante una ventana CDC en `modules/trading/smc_live.py`; el curso
lo enseña en S04 y S06.

### Premium/discount local

NexUX valida el lado local al nacer el POI en
`modules/trading/strategies.py`. Esto se aproxima mejor al uso del 50% del curso
que imponer un veto global fijo.

### FVG y order block base

`modules/trading/smc.py` implementa FVG causal y ultima vela opuesta. Coincide con
la base de S04, aunque no representa toda su taxonomia ni el mapa de liquidez.

### Target de liquidez

NexUX busca weak high/low opuesto en `modules/trading/smc_live.py`. Es coherente
con el objetivo principal observado en rangos de S03 y S07.

## Diferencias materiales

### 1. Fractal del curso no es el pivot de NexUX

El pivote de NexUX usa confirmacion por velas a ambos lados. El fractal del curso
usa impulso, retroceso >=50% y continuacion relativa al objetivo. Uno puede servir
para construir el otro, pero no son intercambiables.

**Riesgo:** etiquetar como `fractal valido del profesor` cualquier swing point
produciria falsos equivalentes.

### 2. El rango del curso contiene causalidad estructural adicional

El curso exige toma de liquidez, strong extreme, finalizacion e iBOS. NexUX
resume el contexto con extremos recientes/pivotes. El resultado visual puede
parecer similar sin compartir el mismo proceso de construccion.

**Bloqueo:** S09 declara ademas que la version de rangos estaba siendo revisada.
No conviene reemplazar el rango de NexUX hasta congelar una hipotesis precisa.

### 3. Falta liquidez exterior relativa al POI

El curso distingue:

- liquidez que aparece antes de alcanzar el bloque;
- liquidez que queda detras y puede volverlo trampa.

NexUX modela sweeps y niveles, pero no la relacion topologica `liquidez detras de
esta zona`. Este es el candidato conceptual mas nuevo del curso.

### 4. CDC de NexUX no equivale al iBOS valido de S08

El CDC micro actual exige rompimiento tras el toque. S08 agrega dos condiciones:
toma de liquidez a la izquierda y creacion de liquidez a la derecha. Esa capa no
debe incorporarse por analogia; necesita definicion causal y ablation.

### 5. La seleccion del timeframe es mas discrecional en el curso

El profesor adapta estructura y objetivo al horizonte, admite coberturas y baja a
distintas temporalidades. NexUX requiere decisiones deterministas. La
discrecionalidad no debe trasladarse como multiples reglas alternativas sin un
protocolo de seleccion.

## Conocimiento ya compatible con evidencia NexUX

- tocar cualquier OB/FVG no basta;
- confirmar despues del toque puede mejorar seleccion en 1h;
- la liquidez opuesta es un target mas fiel que un R fijo aislado;
- premium/discount local es mas defendible que una prohibicion global;
- contexto visual y regla operativa deben permanecer separados.

Estos puntos ya aparecen en los estudios BTA anteriores y en componentes research.
El curso nuevo refina su explicacion, pero no constituye validacion cuantitativa
adicional.

## Candidatos nuevos, no implementados

1. fractal de retroceso >=50% como capa distinta del pivot;
2. liquidez exterior relativa al OB;
3. bloque trampa persistente al refinar timeframe;
4. iBOS valido: toma izquierda + creacion derecha;
5. frescura por zona efectiva y no solo por contenedor HTF;
6. escala de confirmacion frente a MFE/tiempo de salida;
7. conflicto entre rango y fractal como categoria descriptiva.

Todos pertenecen a `HYPOTHESIS_BACKLOG.md`. Ninguno queda autorizado para el Bot.

## Elementos que no deben copiarse

- entradas de replay basadas en experiencia del profesor;
- cobertura long/short sin politica pre-registrada;
- “dos entradas siempre” sin definir exposicion y correlacion;
- revision futura del rango mencionada en S09;
- causalidad noticiosa o rechazo de noticias como regla estadistica;
- nombres `alta probabilidad` sin frecuencia medida;
- metas de win rate o RR relatadas por alumnos.

## Recomendacion

Conservar el curso como especificacion cualitativa. La primera comparacion
cuantitativa razonable no es reescribir NexUX, sino medir incrementalmente:

```text
baseline NexUX
vs baseline + liquidez exterior
vs baseline + iBOS izquierda/derecha
vs baseline + ambas
```

con dataset, costos, disponibilidad causal y protocolo congelados antes de ver
resultados.

## Estado

`COMPARISON COMPLETE / NO IMPLEMENTATION AUTHORIZED`
