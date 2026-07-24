# Backtest detallado BTC swing - Vip CoinSignals

Fecha: 2026-07-22
Ventana: 2024-07-22 a 2026-07-22
Estado: `research_only`

## Veredicto revisado

Las entradas BTC de CoinSignals quedan aproximadamente en equilibrio, no en una perdida
grande: la muestra causalmente reconstruible produjo `+0,018R` por operacion, PF `1,04`
y `+2,22R` total (n=126). El intervalo bootstrap mensual cruza ampliamente cero
(`-0,220R` a `+0,248R`), por lo que no demuestra edge, pero tampoco justifica descartar
el canal.

La experiencia positiva del usuario con shorts es compatible con los datos. Los shorts
fueron ligeramente positivos en 2025 (`+0,022R`, PF `1,06`) y el conjunto short tiene
alta incertidumbre. En los dos anos completos/parciales suma `-0,097R`, PF `0,79`, pero
su IC mensual `[-0,360R, +0,160R]` incluye resultados positivos.

## Correccion metodologica importante

La primera lectura excluyo todos los mensajes editados y concluyo que los shorts eran
claramente negativos. Ese corte era sesgado: 14 operaciones ganadoras fueron editadas
para anadir `/HOLD` al Target 4 cuando avanzaron. Excluirlas eliminaba sistematicamente
TP4 reales, aunque las entradas y los targets ya habian sido publicados y luego
confirmados en vivo.

La metrica principal revisada incluye:

- Mensajes nunca editados.
- Ediciones cuyo texto final contiene la anotacion identificable `/HOLD`.

Las otras 17 ediciones permanecen separadas porque el export no conserva su version
anterior. La sensibilidad queda asi:

| Cohorte | n resueltas | avgR | PF | Total R |
|---|---:|---:|---:|---:|
| Reconstruible (principal) | 126 | +0,018 | 1,04 | +2,22 |
| Todas, incluyendo ediciones ambiguas | 143 | -0,010 | 0,98 | -1,45 |
| Nunca editadas solamente | 112 | -0,162 | 0,65 | -18,15 |
| Edicion `/HOLD` identificable | 14 | +1,454 | sin perdedores | +20,36 |
| Otras ediciones | 17 | -0,217 | 0,53 | -3,68 |

La diferencia no prueba que toda edicion `/HOLD` haya cambiado solo esa etiqueta, pero
los timestamps de TP y el replay de precios corroboran esos recorridos. Por eso se
reporta como cohorte propia y no se mezcla silenciosamente.

## Reconstruccion swing

- 149 senales BTC: 23 en 2024, 57 en 2025 y 69 en 2026.
- Sin caducidad de entrada y sin limite artificial de 30 dias.
- Entrada desde mensajes live `Entry 1` y `All entries achieved`, usando sus precios
  promedio publicados.
- Cuando se reconstruyen dos entradas sin promedio oficial, `50/50` significa igual
  capital USDT en cada nivel. El promedio es armonico (cantidad = capital/precio), no
  la media aritmetica de los dos precios.
- Cuatro parciales iguales; se mantiene hasta TP4, SL o instruccion posterior.
- Costos de 0,14% ida y vuelta, convertidos a R.
- Stop primero en ambiguedad intrabar; no hubo salidas TP/SL ambiguas en esta muestra.

Tambien se incorporaron mensajes generales que el primer replay habia omitido, por
ejemplo `Close all shorts`, `BTC close near entry` y `Shorts closed`. En la cohorte
principal se usaron 29 instrucciones unicas:

- 14 cierres a mercado.
- 10 cierres a entrada/cerca de entrada.
- 3 actualizaciones numericas de SL.
- 2 reglas de SL confirmado por cierre 4h/diario.

Los cierres generales se vinculan a posiciones BTC compatibles abiertas durante los
120 dias anteriores. Es una heuristica auditable; una captura live futura sera exacta.

## Targets observados

| Maximo alcanzado | n |
|---|---:|
| Ningun TP | 45 |
| TP1 | 23 |
| TP2 | 21 |
| TP3 | 10 |
| TP4 | 27 |

Ochenta y una de 126 operaciones (64,3%) alcanzaron al menos TP1 y 27 (21,4%) llegaron
a TP4. Por tanto, la percepcion de que alcanzan TP4 frecuentemente es correcta.

El maximo TP reconstruido coincide exactamente con los mensajes del canal en 102/112
operaciones no editadas. En ocho casos el mercado llego mas lejos de lo anunciado y en
dos el canal anuncio un TP mayor. El detector de targets no esta recortando
sistematicamente ganadores.

## Resultado por ano y direccion

| Corte | n | avgR | PF | Total R |
|---|---:|---:|---:|---:|
| 2024 parcial | 22 | -0,192 | 0,54 | -4,21 |
| 2025 | 47 | +0,041 | 1,10 | +1,91 |
| 2026 parcial | 57 | +0,079 | 1,19 | +4,52 |
| Long | 38 | +0,281 | 2,00 | +10,69 |
| Short | 88 | -0,096 | 0,79 | -8,44 |

Short por periodo:

| Periodo | n | avgR | PF |
|---|---:|---:|---:|
| 2024 parcial | 13 | -0,471 | 0,06 |
| 2025 | 34 | +0,022 | 1,06 |
| 2026 parcial | 41 | -0,078 | 0,85 |

Long sigue siendo el corte mas prometedor, pero fue descubierto despues de mirar la
muestra y su IC mensual `[-0,122R, +0,714R]` todavia cruza cero.

## Sensibilidad de salidas

| Gestion sobre entradas confirmadas | avgR principal | PF principal |
|---|---:|---:|
| 40/30/20/10% en TP1-TP4 | +0,016 | 1,04 |
| 25/25/25/25% | +0,018 | 1,04 |
| 10/20/30/40% | +0,019 | 1,04 |
| Salir completo en TP1 | -0,002 | 1,00 |

El resultado cercano a cero no depende de favorecer TP1 o TP4. El leverage tampoco
cambia el edge en R; solo multiplica margen, retorno porcentual y riesgo de liquidacion.

## Variante TP1 25% + break-even

Se probo la regla solicitada: al tocar TP1 se cierra 25% y el SL del 75% restante se
mueve al precio promedio de entrada. TP2, TP3 y TP4 cierran 25% inicial cada uno. El BE
se activa desde la vela siguiente para no inventar el orden dentro de una vela de 15m.

| Gestion | n | WR economico | avgR | PF | Total R |
|---|---:|---:|---:|---:|---:|
| 25% por TP, SL original | 126 | 42,1% | +0,018 | 1,04 | +2,22 |
| TP1 25% + BE desde vela siguiente | 126 | 64,3% | +0,040 | 1,12 | +4,99 |
| TP1 25% + BE intrabar conservador | 126 | 64,3% | +0,038 | 1,11 | +4,74 |

La mejora sobre las mismas operaciones es `+2,78R`: 32 trades mejoran, 17 empeoran y
77 no cambian. Hubo 55 salidas por BE. Diez de esos trades habrian llegado despues a
TP4, por lo que la proteccion reduce TP4 de 27 a 17, pero evita suficientes retornos al
SL para compensarlo.

Por direccion, long mejora de `+0,281R` a `+0,312R`; short mejora de `-0,097R` a
`-0,078R`. Por periodo: 2024 `-0,096R`, 2025 `+0,054R` y 2026 `+0,080R`.

El IC bootstrap mensual sigue cruzando cero (`-0,176R` a `+0,264R`). Es la mejor
gestion probada hasta ahora, pero la evidencia sigue siendo debil y no convierte por si
sola los shorts en una estrategia positiva estable.

## Cuenta teorica de 1.000 USDT

Con la gestion original y riesgo de 0,5% del equity al SL, la cohorte principal termina
aproximadamente en `1.009 USDT`, con drawdown maximo de 4,3%. Con TP1 25% + BE termina
en `1.023 USDT`, con drawdown de 4,4%. A riesgo de 1%, la variante BE termina cerca de
`1.043 USDT`, con drawdown de 8,7%.

Esto confirma que la estrategia reconstruida esta cerca de break-even despues de costos:
un pequeno cambio de fills, comisiones o gestion puede moverla a ganancia o perdida.

## Recomendacion

1. No descartar CoinSignals ni afirmar que sus shorts no funcionan.
2. No usar el backtest anterior de mensajes `no editados` como veredicto; estaba sesgado
   por las anotaciones `/HOLD` y por cierres generales no enlazados.
3. Construir el lector shadow live para registrar la version original, cada edicion y
   cada instruccion global en tiempo real. Eso elimina la ambiguedad historica.
4. Pre-registrar dos libros BTC, `todos` y `solo long`, usando TP1 25% + BE y riesgo fijo.
5. Considerar live con 1.000 USDT solo despues de una muestra forward que supere PF 1,20
   y `+0,10R` neto sin cambiar reglas durante la prueba.

La busqueda posterior de 105 configuraciones confirma que `TP1 25% + BE` sigue siendo
la opcion principal mas defendible para forward, aunque no fue la de mayor retorno
in-sample. Ver `research/coinsignals_btc_exit_search_2026-07-22.md`.

## Artefactos

- Motor: `research/coinsignals_btc_swing.py`
- Tests: `research/test_coinsignals_btc_swing.py`
- Resultados: `data/telegram/coinsignals_btc_swing_2y.json`

No se modificaron NexUX, el dry-run, el VPS, Binance, credenciales ni posiciones reales.
