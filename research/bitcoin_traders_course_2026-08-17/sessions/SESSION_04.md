# Sesion 04 - Oferta y Demanda (OB + Imbalance)

**Fuente:** `Oferta y Demanda (OB + Imbalance)`<br>
**Duracion:** 02:10:27<br>
**Audio SHA-256:** `235858aab9c0d1ecc164b86ffa0f7327a92c4b28e45a2451942fee996d3b8fb7`<br>
**Transcripcion:** primera pasada local; zonas exactas pendientes de cotejo visual.

## Proposito declarado

Definir el uso particular de order blocks e imbalance dentro de esta estrategia.
El profesor advierte que no pretende cubrir todas las taxonomias SMC externas.

## Order block base

- **E0, 00:02:49-00:03:40:** para un movimiento alcista fuerte, el OB se busca en
  la vela bajista anterior; para uno bajista, en la vela alcista anterior.
- **E0, 00:04:03-00:04:29:** clasifica cuatro tipos: decisional, extremo, breaker
  y OB de alta probabilidad.

## Cuatro requisitos y excepcion practica

La clase enumera:

1. **Tradicional:** rompimiento estructural (BOS, CDC o iBOS) con volumen
   (E0, 00:05:27-00:06:17).
2. **Liquidez de la vela anterior:** la vela OB barre el high o low de la vela
   precedente (E0, 00:06:18-00:06:59).
3. **Movimiento que genera liquidez:** el desplazamiento originado por el OB deja
   liquidez posterior/preexistente segun la explicacion que se completa en la
   sesion 5 (E0, 00:06:48-00:07:21).
4. **Imbalance:** dentro o junto al OB (E0, 00:07:22-00:07:58).

**Tension documentada:** entre 00:07:50 y 00:10:29 el profesor aclara que en la
practica no siempre aparecen los cuatro. Exige al menos dos, pero su enumeracion
oral cambia de "primero y segundo" a una prioridad donde `tradicional` y
`movimiento que genera liquidez` son los dos mas importantes. Esto queda **U0**
hasta contrastarlo con los ejemplos y la sesion de liquidez.

## Imbalance / FVG

- **E0, 00:10:42-00:12:37:** se detecta con tres velas; existe vacio cuando las
  mechas de la primera y tercera no se solapan.
- **E0, 00:12:10-00:12:37:** imbalance, ineficiencia, gap, vacio de liquidez y FVG
  se usan como nombres equivalentes en la clase.
- **E0, 00:13:42-00:14:15:** suele aparecer alrededor de velas de cuerpo grande.
- **E0, 00:17:53-00:18:23:** OB + imbalance se interpreta como POI susceptible de
  ofrecer una entrada, no como entrada automatica.
- **E0, 00:20:20-00:20:45:** el profesor exige confirmacion antes de proyectar que
  un imbalance lejano sera cubierto.

## Tipos de OB

- **Decisional, E0 00:21:46-00:23:02:** origina el rompimiento tras reaccionar a
  una zona opuesta.
- **Extremo, E0 00:23:02-00:23:40:** origen del movimiento que causa rompimiento.
- **Breaker, E0 00:23:40-00:24:01:** OB no respetado en el pasado que actua luego
  como OB contrario; el profesor lo describe como infrecuente en su muestra.
- **Alta probabilidad, E0 00:24:01-00:24:50:** OB + imbalance situado en descuento
  para rango alcista o premium para rango bajista.

El nombre `alta probabilidad` pertenece al vocabulario del curso; no constituye
evidencia estadistica.

## Integracion con rango

- **E0, 00:30:51-00:34:28:** orden de lectura practico: tendencia amplia, rango,
  fractal y luego OB.
- **E0, 00:32:44-00:34:28:** primero debe existir finalizacion del rango; antes de
  ella el profesor evita seleccionar las ordenes de compra/venta.
- **E0, 00:34:15-00:36:34:** inicio y finalizacion suelen contener OB decisional y
  extremo.
- **E0, 00:38:28-00:41:54:** demanda se ubica bajo 50%/inicio y oferta sobre
  50%/finalizacion en el rango explicado.
- **E0, 00:43:10-00:44:42:** en rango alcista se prioriza demanda; operar oferta
  es contracorriente y requiere asumir/gestionar mayor riesgo. Caso bajista
  pendiente de verificar por simetria explicita.

## Restricciones observadas

- **E0, 00:28:31-00:29:01:** recomienda OB de M15 o superiores y reconoce que una
  zona H4 puede reaccionar antes de alcanzar un OB menor incrustado.
- El tamano del FVG no recibe umbral minimo en la clase (E0,
  00:20:11-00:20:36). Esto impide mecanizar un filtro de magnitud sin una
  hipotesis nueva.
- Las expresiones `volumen` y `momentum` parecen basarse en cuerpo/desplazamiento,
  pero la regla exacta no esta formalizada aun.

## Hipotesis futuras

- **H1:** tradicional + generacion de liquidez frente a OB tradicional aislado.
- **H1:** aporte incremental de imbalance al OB.
- **H1:** decisional/extremo frente a OB de alta probabilidad por premium/discount.
- **H1:** calidad por timeframe del OB.

## Verificacion visual pendiente

- 00:02:49-00:10:29: cuatro requisitos y prioridad practica.
- 00:10:42-00:18:23: construccion exacta del FVG y POI.
- 00:21:46-00:24:50: cuatro tipos de OB.
- 00:30:51-00:44:42: integracion con rango operativo.
- 00:45:09-01:10: ejemplos decisional/extremo.

## Estado

`TRANSCRIBED / CONCEPT MAP DRAFT / VISUAL REVIEW PENDING`
