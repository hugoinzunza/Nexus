# Revision final - Bitcoin Traders SMC

**Corte:** 2026-08-17<br>
**Curso:** `BOOTCAMP MAYO 2025`<br>
**Corpus:** 11 sesiones, 22 h 15 min<br>
**Estado:** `PLAYBOOK.V1 FROZEN / PRIMARY VISUAL GATE CLOSED`

## Veredicto

El curso contiene una estrategia SMC coherente y enseñable, pero no un algoritmo
cerrado listo para automatizar. Su nucleo estable puede reconstruirse asi:

```text
horizonte y timeframe rector
-> fractal con retroceso >=50%
-> rango operativo y weak target
-> premium/discount
-> OB, FVG o toma de liquidez
-> liquidez delante y detras de la zona
-> entrada a riesgo o confirmacion iBOS
-> invalidacion, objetivo y riesgo predefinidos
```

La principal contribucion frente al lenguaje ya presente en NexUX no es detectar
mas OB o FVG. Es describir relaciones que NexUX aun no representa completamente:

1. liquidez exterior detras de un POI como posible bloque trampa;
2. confirmacion iBOS que toma liquidez a la izquierda y crea liquidez a la
   derecha;
3. frescura de cada zona LTF dentro de un contenedor HTF;
4. separacion explicita entre estructura rectora y estructuras internas.

## Lo que el curso realmente enseña

### Contexto antes que patron

Un OB o un FVG no es una entrada por si solo. Primero se define horizonte,
estructura, rango, direccion y target. Luego se evalua la zona y su liquidez.

### Fractal y rango no son sinonimos de pivot

El fractal docente exige impulso, retroceso de al menos 50% y continuacion. El
rango incorpora toma de liquidez, strong extreme, finalizacion e iBOS. Esto no
equivale automaticamente a los pivotes actuales de NexUX.

### Liquidez relativa a la zona

El hallazgo conceptual mas interesante es topologico: la liquidez puede estar
delante de la zona o detras de su invalidacion. En el segundo caso, el primer
bloque puede actuar como trampa y refinarlo no elimina ese problema.

### Confirmacion compuesta

La confirmacion no es cualquier ruptura micro. La version mas completa de la
clase 8 exige reaccion en zona, ruptura estructural, toma de liquidez a la
izquierda y creacion de liquidez a la derecha.

### Gestion antes que ejecucion

La clase final exige riesgo bajo, limite diario, aceptacion previa de la perdida,
revision del mapa y bitacora. Los numeros personales del profesor se conservan
como ejemplos, no como parametros optimos.

## Ambiguedades que impiden operacionalizar la estrategia

- La eleccion de estructura principal o interna depende del objetivo del trader.
- El profesor reconoce un error propio de mapeo y que la metodologia de rangos
  estaba todavia en evaluacion.
- No existen umbrales cerrados para tamaño de OB, FVG, buffer de stop o regla de
  diez velas.
- Break-even y parciales no tienen disparador universal. El docente si enuncia
  dos entradas como regla universal con riesgo total repartido, pero no cierra
  zonas admisibles, correlacion ni secuencia para mecanizarla.
- Las etiquetas `alta probabilidad` y el acierto BTC de `75%-82%` carecen de un
  dataset auditable.
- La formula de futuros que busca consumir cerca del 80% del margen de la
  posicion queda excluida por no separar adecuadamente riesgo de cuenta, margen,
  stop y liquidacion.

## Comparacion con NexUX

NexUX ya contiene equivalentes parciales para FVG, OB base, premium/discount,
target de liquidez y CDC posterior al toque. No contiene equivalentes completos
para el fractal docente, el rango causal, la liquidez exterior relativa al POI ni
el iBOS izquierda/derecha.

La comparacion completa esta en `BITCOIN_TRADERS_VS_NEXUX.md`. Ninguna diferencia
autoriza cambios al Bot.

## Estado de la evidencia

- 11/11 sesiones inventariadas.
- 11/11 audios descargados en cache privado.
- 11/11 hashes SHA-256 registrados.
- 11/11 transcripciones locales completadas.
- 11/11 fichas con timestamps.
- Corpus audiovisual fuera del repositorio.
- Gate visual principal: 6/6 fragmentos confirmados por revision independiente.
- Items visuales secundarios: pendientes y no bloqueantes para `playbook.v1`.

La transcripcion y la revision visual independiente permiten congelar el
playbook descriptivo. El freeze no convierte las reglas amarillas en reglas
mecanicas ni demuestra rentabilidad.

## Gate visual principal cerrado

La revision independiente verifico contra pantalla:

1. fractal valido: S02 00:28:06;
2. inicio/finalizacion del rango y weak target: S03 01:07:46;
3. liquidez exterior y bloque trampa: S05 00:31:42;
4. iBOS izquierda/derecha: S08 00:39:42;
5. decisional/extremo no mitigado: S04 01:05:51;
6. formula de futuros, solo para documentar su exclusion: S11 01:48:01.

Los items visuales secundarios por ficha permanecen enumerados de forma canonica
en §12 de `CLAUDE_INDEPENDENT_REVIEW.md`. No bloquean este freeze y si bloquean
cualquier operacionalizacion de la regla asociada hasta ser revisados.

`playbook.v1` queda congelado. Un paso futuro y separado podra pre-registrar como
maximo `HYP-BT-LIQ-EXT-001` y `HYP-BT-IBOS-001`; este freeze no las autoriza.

## Restricciones permanentes de esta entrega

- no es señal;
- no demuestra rentabilidad;
- no autoriza Bot, Testnet, Live ni shadow mode;
- no modifica NexUX productivo;
- no completa reglas ausentes con SMC externo;
- no redistribuye contenido privado del curso.

## Conclusion

El material ya puede estudiarse como un sistema y no como once videos aislados.
La estrategia del profesor queda conceptualmente aprendida, trazable y congelada
como baseline descriptivo `playbook.v1`. Los items visuales secundarios y las
reglas amarillas permanecen visibles; no existe autorizacion para convertirlas en
señal, backtest o comportamiento del Bot.
