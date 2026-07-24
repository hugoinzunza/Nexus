# Busqueda de configuraciones BTC - CoinSignals

Fecha: 2026-07-22
Estado: `research_only`
Universo: BTC, 2024-07-22 a 2026-07-22, cohorte reconstruible

## Objetivo

Buscar mejoras de gestion sin modificar las entradas, SL o targets publicados. La
busqueda se hizo temporalmente para reducir sobreajuste:

- Entrenamiento/seleccion: antes de 2026 (69 operaciones resueltas).
- OOS: 2026 (57 operaciones resueltas).
- Metrica de seleccion: mayor avgR de entrenamiento; PF como desempate.
- 21 repartos de TP x 5 politicas de stop = 105 configuraciones.

Politicas: SL original, BE tras TP1, BE tras TP2, proteccion escalonada
(BE -> TP1 -> TP2) y mover SL a TP1 despues de TP2.

## Resultado principal

La configuracion elegida usando solamente entrenamiento fue:

- TP1 `0%`, TP2/TP3/TP4 `33,3%` cada uno.
- Despues de TP2, mover SL a TP1.

| Periodo | n | avgR | PF | Total R |
|---|---:|---:|---:|---:|
| Entrenamiento | 69 | +0,053 | 1,12 | +3,64 |
| OOS 2026 | 57 | +0,054 | 1,12 | +3,10 |
| Total | 126 | +0,054 | 1,12 | +6,75 |

Agregado parece estable, pero no lo es por subperiodos:

| Subperiodo | avgR | PF |
|---|---:|---:|
| 2024-H2 | -0,118 | 0,75 |
| 2025-H1 | -0,081 | 0,84 |
| 2025-H2 | +0,191 | 1,48 |
| 2026-Q1 | +0,413 | 2,14 |
| 2026-Q2 | -0,326 | 0,44 |
| 2026-Q3 parcial | -0,511 | 0,15 |

No se recomienda para live: no toma beneficio en TP1, tiene mayor varianza y su ganancia
agregada depende de dos tramos muy favorables.

## Comparacion con TP1 25% + BE

| Configuracion | Train avgR/PF | OOS avgR/PF | Total avgR/PF |
|---|---:|---:|---:|
| 25% cada TP, SL original | -0,033 / 0,92 | +0,079 / 1,19 | +0,018 / 1,04 |
| **TP1 25% + BE** | +0,006 / 1,02 | **+0,080 / 1,22** | +0,040 / 1,12 |
| Ganadora de train | +0,053 / 1,12 | +0,054 / 1,12 | +0,054 / 1,12 |

La ganadora de entrenamiento no supera a TP1 25% + BE en el periodo OOS. La regla
simple BE tiene menos grados de libertad, asegura una realizacion en TP1 y es la opcion
mas razonable para forward-test.

## Prueba de sobreajuste

- Correlacion de ranking train vs OOS: `-0,499`. Las configuraciones que mas ganaron en
  entrenamiento tendieron a rankear peor en 2026.
- 104/105 configuraciones fueron positivas en el OOS agregado porque 2026-Q1 fue muy
  favorable; eso no significa 104 edges distintos.
- Las 105 configuraciones fueron negativas en 2024-H2.
- Las 105 fueron negativas en 2026-Q2.
- Las 105 fueron negativas en 2026-Q3 parcial.
- Ninguna fue positiva simultaneamente en 2026-Q1 y Q2.

La configuracion que mas gana mirando retrospectivamente el OOS fue 10/18/27/45% con
BE despues de TP2: OOS `+0,127R`, PF `1,29`. No es seleccionable honestamente porque
fue descubierta mirando el examen; ademas pierde en Q2 y Q3.

## Walk-forward

Cada fold eligio de nuevo usando solo el pasado:

| Test | Config elegida | n | avgR | PF |
|---|---|---:|---:|---:|
| 2026-Q1 | 0/33/33/33 + lock TP1 tras TP2 | 31 | +0,413 | 2,14 |
| 2026-Q2 | 0/33/33/33 + BE tras TP2 | 19 | -0,305 | 0,47 |
| 2026-Q3 parcial | misma | 7 | -0,558 | 0,07 |

El optimizador persigue el regimen anterior y no se adapta cuando cambia. La ganancia
del walk-forward proviene enteramente de Q1 y luego se devuelve en gran parte.

## Lectura por politica

Promedio OOS entre todos los repartos:

| Politica | avgR OOS promedio | Configuraciones positivas |
|---|---:|---:|
| SL original | +0,071 | 21/21 |
| BE tras TP1 | +0,071 | 21/21 |
| BE tras TP2 | +0,082 | 21/21 |
| Escalonada | +0,007 | 20/21 |
| Lock TP1 tras TP2 | +0,040 | 21/21 |

BE tras TP2 gana como familia en OOS, pero no fue mejor en entrenamiento y tampoco
resiste Q2/Q3. Es candidato research, no reemplazo validado.

## Recomendacion

1. Mantener `TP1 25% + BE` como configuracion principal del shadow book: es simple,
   interpretable y mejoro frente al baseline en el OOS.
2. Registrar en paralelo dos challengers, sin dinero real:
   - 25/25/25/25 con BE despues de TP2.
   - 0/33/33/33 con SL a TP1 despues de TP2.
3. No seguir optimizando sobre estos mismos 126 trades; cada nueva prueba aumenta el
   riesgo de encontrar ruido.
4. Elegir solamente con una muestra forward nueva y pre-registrada. Requerir al menos
   50 operaciones, PF >1,20 y avgR >+0,10 neto.
5. Investigar por que todos los esquemas fallan juntos en los periodos malos. El proximo
   avance probablemente esta en seleccion/regimen, no en microajustar porcentajes de TP.

## Artefactos

- Busqueda: `research/coinsignals_btc_exit_search.py`
- Resultados: `data/telegram/coinsignals_btc_exit_search.json`
- Motor: `research/coinsignals_btc_swing.py`
- Tests: `research/test_coinsignals_btc_exit_search.py`

No se modificaron NexUX, dry-run, VPS, credenciales, Binance ni posiciones reales.

Continuacion: `research/coinsignals_btc_filter_search_2026-07-22.md` prueba filtros
de senal/regimen y una validacion externa con datos anteriores a julio de 2024.
