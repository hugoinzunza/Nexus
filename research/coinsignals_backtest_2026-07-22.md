# Auditoria causal de Vip CoinSignals

Fecha: 2026-07-22
Estado: `research_only`
Fuente: exportacion MTProto de 17.278 mensajes (2019-04-14 a 2026-07-21)

## Veredicto

No conviene conectar estas senales al bot ni copiarlas automaticamente a una cuenta real.
El canal acierta TP1 con una frecuencia visualmente atractiva, pero el pago tipico de TP1
es demasiado pequeno frente al stop. En las senales no editadas, la estrategia de salir
completo en TP1 pierde `-0,132R` por operacion y los parciales iguales pierden `-0,158R`.

Mover hipoteticamente el remanente a break-even despues de TP1 deja `+0,021R`, PF `1,05`,
pero su intervalo bootstrap mensual incluye ampliamente cero (`-0,067R` a `+0,110R`).
No es evidencia de edge. Tampoco es una instruccion observada del canal: es una gestion
alternativa creada para probar si sus entradas contienen informacion util.

La utilidad real del canal, por ahora, es servir como benchmark y flujo shadow para
investigacion forward, no como fuente de ordenes.

## Cobertura

- Se detectaron 2.004 mensajes candidatos; 1.995 pasaron la validacion estructural.
- 1.937 corresponden a cripto, 43 a oro y 15 a otros activos.
- El replay cubre los 20 pares mas frecuentes: 1.503 senales, 77,6% del universo cripto
  parseado.
- Resultado de entrada al primer precio: 1.370 resueltas, 98 abiertas al terminar el
  horizonte y 35 no llenadas.
- La metrica principal usa 1.121 operaciones resueltas provenientes de mensajes nunca
  editados.
- Las senales parseables empiezan en 2021. Los mensajes de 2019-2020 usan otros formatos
  o no contienen todos los niveles necesarios para un replay verificable.

Pares: BTC, ETH, SOL, BNB, LTC, ADA, XRP, DOGE, SUI, BCH, NEAR, APT, MATIC, WIF, ENA,
ARB, TON, S, 1000PEPE y UNI.

## Metodo causal

- Velas publicas Binance Futures de 15 minutos; no se usaron credenciales de trading.
- Entrada solo en velas posteriores a la publicacion. La vela de publicacion nunca llena.
- Orden limite en el primer precio publicado; caduca despues de 7 dias.
- Horizonte maximo de resolucion: 30 dias desde el fill.
- En la vela de fill, el stop cuenta y el TP no se acredita.
- En una ambiguedad posterior TP/SL dentro de la misma vela, gana el stop.
- Costo conservador fijo de 0,14% ida y vuelta, convertido a R segun el riesgo del setup.
- Resultados en R, sin aplicar el leverage anunciado. Usar leverage multiplicaria tanto
  retornos como drawdown y anadiria riesgo de liquidacion.

## Resultados principales

### Primer precio publicado

| Gestion | n no editadas | WR TP1 | avgR | Total R | PF | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| Salir completo en TP1 | 1.121 | 57,0% | -0,132 | -148,18 | 0,70 | 160,71R |
| Parciales iguales, stop original | 1.121 | 57,0% | -0,158 | -177,50 | 0,71 | 195,58R |
| Parciales, BE hipotetico tras TP1 | 1.121 | 57,0% | +0,021 | +24,00 | 1,05 | 36,10R |

El ganador TP1 promedio paga `+0,54R`; el perdedor promedio cuesta `-1,024R`. El win rate
de equilibrio es 65,5%, muy por encima del 57,0% observado.

### Sensibilidad: punto medio del rango

El 98% de las senales publica un rango. Darle al proveedor una entrada mas favorable en
el punto medio no rescata el sistema: reduce los fills y, en no editadas, produce
`-0,160R` en TP1, `-0,171R` con parciales y `-0,049R` con BE hipotetico. Por tanto, el
veredicto no depende de haber elegido el primer precio conservador.

### Estabilidad anual, no editadas

| Ano | n | WR TP1 | TP1 avgR | BE hipotetico avgR |
|---|---:|---:|---:|---:|
| 2021 | 42 | 61,9% | +0,049 | +0,147 |
| 2022 | 94 | 58,5% | -0,113 | +0,073 |
| 2023 | 121 | 50,4% | -0,214 | -0,016 |
| 2024 | 376 | 56,6% | -0,132 | +0,032 |
| 2025 | 368 | 56,0% | -0,169 | -0,072 |
| 2026 | 120 | 65,0% | -0,018 | +0,228 |

TP1 es negativo en cuatro de seis anos y el BE hipotetico cambia de signo. El resultado
positivo de 2026 no debe convertirse retrospectivamente en un filtro: fue observado
despues de mirar los datos y puede ser efecto de regimen.

Por direccion, los longs son menos debiles (`-0,074R` TP1; `+0,122R` BE hipotetico,
n=504) que los shorts (`-0,180R`; `-0,061R`, n=617). Este corte tambien es post-hoc.

## Sesgos detectados

### Ediciones con informacion futura

Telegram entrega el texto final, no el historial previo de una edicion. El rendimiento
crece casi monotonicamente con el tiempo transcurrido antes de editar:

| Estado del mensaje | n | WR TP1 | TP1 avgR | BE hipotetico avgR |
|---|---:|---:|---:|---:|
| Nunca editado | 1.121 | 57,0% | -0,132 | +0,021 |
| Editado en <=5 min | 40 | 65,0% | -0,018 | +0,294 |
| Editado entre 5 min y 1 dia | 68 | 82,4% | +0,242 | +0,515 |
| Editado despues de 1 dia | 141 | 80,9% | +0,254 | +0,634 |

No se puede saber que cambio, asi que ninguna senal editada es admisible en la metrica
primaria. Incluirlas transforma artificialmente el BE hipotetico de `+0,021R` a
`+0,117R`.

### Seleccion de resultados en las respuestas

Entre operaciones no editadas y resueltas, el canal publico una respuesta reconocible
para el 88,4% de nuestros ganadores de mercado, pero solo para el 29,5% de los perdedores.
Mirando exclusivamente las operaciones que recibieron un TP o stop en el chat, la tasa
de TP1 declarada parece ser 85,3%. Esa cifra no es un win rate del universo completo:
esta condicionada a que se haya publicado un desenlace.

El clasificador de respuestas puede omitir frases no estandarizadas, pero la asimetria
es demasiado grande para usar las respuestas del canal como verdad del backtest.

### Multiples senales correlacionadas

Las senales se agrupan por mes y mercado; no son observaciones independientes. Un
bootstrap por bloques mensuales sobre 61 meses da:

- TP1: IC 95% `[-0,190R, -0,076R]`.
- Parciales con stop original: IC 95% `[-0,253R, -0,060R]`.
- BE hipotetico: IC 95% `[-0,067R, +0,110R]`.

Solo 15/61 meses fueron positivos en TP1 y 30/61 con BE hipotetico.

## Recomendacion operativa

1. No tocar NexUX live, el dry-run ni sus filtros a partir de este estudio.
2. No autoejecutar CoinSignals y no usar el win rate publicado como expectativa.
3. Mantener un shadow book separado para nuevas senales: texto original inmutable,
   timestamp de recepcion, fill realista, costos y tres gestiones pre-registradas.
4. Reevaluar despues de al menos 100 senales nuevas no editadas o seis meses, lo que
   ocurra mas tarde. Exigir PF >1,20 y avgR >+0,10 en una gestion elegida antes de mirar.
5. Si sobrevive, probar CoinSignals solo como feature contextual contra el baseline de
   NexUX, nunca como reemplazo directo ni como gate sin test A/B forward.

## Artefactos locales

- Export: `data/telegram/coinsignals_history.json`
- Senales parseadas: `data/telegram/coinsignals_parsed.json`
- Replay principal: `data/telegram/coinsignals_backtest_top20.json`
- Sensibilidad midpoint: `data/telegram/coinsignals_backtest_top20_midpoint.json`
- Parser/replay: `research/coinsignals_backtest.py`
- Tests: `research/test_coinsignals_backtest.py`

Los datos de Telegram, klines, credenciales API y sesion permanecen locales, con permisos
restrictivos y fuera de Git. El codigo no importa `modules.bot`, no lee credenciales de
trading y no envia ordenes.
