# Busqueda de filtros BTC - CoinSignals

Fecha: 2026-07-22
Estado: `research_only`

## Pregunta

Despues de comprobar que 105 esquemas de salida fallaban juntos en los periodos
malos, se buscaron filtros causales de seleccion y regimen. La ejecucion usada fue
la variante simple: entrada confirmada por el canal, 25% en cada TP y BE despues de
TP1.

## Metodo

- Cohorte principal: 126 operaciones resueltas entre 2024-07-22 y 2026-07-22.
- Seleccion: 69 operaciones anteriores a 2026.
- OOS: 57 operaciones de 2026.
- Archivo externo no usado para elegir reglas: 47 operaciones comparables anteriores
  a 2024-07-22. Solo se incluyeron senales reconstruibles con cuatro targets.
- 40 reglas: direccion, RR publicado a TP1/TP4, riesgo, leverage, momentum de 1-30
  dias, expansion de volatilidad y salud shadow de las ultimas 5/10/20 operaciones.
- Los datos de mercado usan exclusivamente velas cerradas antes de confirmar la
  entrada. Una operacion shadow solo entra en la salud del proveedor despues de
  haberse resuelto.
- El RR del plan usa igual capital USDT por entrada: promedio armonico de los precios,
  no promedio aritmetico. Si el canal publica `Average Entry Price`, la ejecucion usa
  directamente ese promedio oficial.
- El selector exige n>=20, al menos cinco casos por bloque de entrenamiento y
  resultado positivo en dos de tres bloques.

## Resultado del selector

El ganador mirando solo entrenamiento fue `TP1 >= 1.4R`:

| Periodo | n | avgR | PF |
|---|---:|---:|---:|
| Train | 32 | +0.352 | 3.21 |
| OOS 2026 | 21 | +0.588 | 3.88 |
| Archivo externo | 20 | **-0.026** | 0.93 |
| 2026-Q2 | 5 | **-0.375** | 0.12 |
| 2026-Q3 parcial | 2 | **-0.384** | 0.30 |

La validacion externa refuta al ganador. La unica regla positiva en archivo, train y
OOS agregados fue `TP4 >= 4R`, pero queda apenas en +0.013R en el archivo, mientras
3.75R y 4.25R vuelven a negativo. Es un corte sensible, no una frontera robusta.

## TP1/R

La distancia a TP1 fue la senal estructural mas fuerte dentro de los dos anos, pero
no sobrevivio completa al archivo:

| Regla | Archivo avgR | Train avgR | OOS avgR | Desde abril-26 |
|---|---:|---:|---:|---:|
| Sin filtro | -0.042 | +0.006 | +0.080 | **-0.343** |
| TP1 >= 1.3R | +0.024 | +0.178 | +0.286 | **-0.415** |
| TP1 >= 1.4R | -0.026 | +0.352 | +0.588 | **-0.375** |

El vecindario 1.2-1.4 mejora train/OOS agregado, pero la ventaja proviene en gran
parte de 2026-Q1. No es suficiente para operar ahora.

## Direccion

`long` fue el filtro mas interesante fuera del optimizador: archivo +0.046R (n=11),
train +0.165R (n=22) y OOS +0.514R (n=16). Sin embargo:

- La muestra historica externa es muy pequena y su intervalo incluye perdidas amplias.
- Perdio -0.264R en 2025-H2.
- Solo hubo tres longs desde abril de 2026 y ninguno en julio.

Sirve como hipotesis forward, no como permiso para live. Los shorts fueron negativos
en archivo, train y OOS, pero descartarlos ahora estaria condicionado por el regimen
alcista de la muestra.

## Gate por salud shadow

Pausar cuando la media de las ultimas 5/10/20 operaciones resueltas era negativa no
funciono. El gate de 10 operaciones dio -0.073R en train, -0.048R en archivo y
-0.628R desde abril. Reacciona despues del cambio de regimen y persigue el tramo
anterior, igual que el optimizador de salidas.

## Incertidumbre

Bootstrap simple de medias, 95% (no corrige dependencia temporal):

| Regla/periodo | avgR | IC 95% |
|---|---:|---:|
| Base desde abril-26, n=26 | -0.343 | **[-0.607, -0.088]** |
| TP1>=1.4, archivo n=20 | -0.026 | [-0.424, +0.410] |
| TP4>=4, archivo n=24 | +0.013 | [-0.357, +0.416] |
| Long, archivo n=11 | +0.046 | [-0.486, +0.604] |

La unica evidencia relativamente clara es negativa: el regimen reciente ha sido malo.
Los supuestos filtros positivos siguen siendo inciertos.

## Conclusion operativa

1. No promover ningun filtro ni configuracion a dinero real.
2. Mantener `25% TP1 + BE` solo como baseline shadow.
3. Pre-registrar tres libros paralelos para las proximas 50 operaciones BTC:
   baseline, long-only y TP1>=1.4R. No volver a mover umbrales durante la muestra.
4. Exigir para una promocion PF>1.20, avgR>+0.10, al menos 50 operaciones y resultado
   positivo en dos bloques temporales. Comparar tambien contra el baseline pareado.
5. El problema actual no se arreglo con salidas, filtros de mercado ni gates de racha.
   La conclusion honesta es esperar evidencia forward nueva.

## Artefactos

- Estudio: `research/coinsignals_btc_filter_search.py`
- Resultado crudo: `data/telegram/coinsignals_btc_filter_search.json`
- Tests: `research/test_coinsignals_btc_filter_search.py`

No se modificaron NexUX, el bot, VPS, Binance, credenciales ni operaciones reales.
