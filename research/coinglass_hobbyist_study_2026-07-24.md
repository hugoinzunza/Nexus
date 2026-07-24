# CoinGlass Hobbyist — estudio histórico 4h

## Método

- 1079 barras consecutivas 4h; 2026-01-25T20:00:00+00:00 → 2026-07-24T12:00:00+00:00.
- Split temporal 70/30: 755 IS y 324 OOS desde 2026-05-31T16:00:00+00:00.
- Retornos a 4h/8h/12h; operaciones no solapadas por horizonte.
- Costo conservador: 0.10% por operación.
- Reglas primarias con umbrales fijos; variantes inversas marcadas como post-hoc; IC bootstrap 95%.

## Resultados OOS

| Regla | 4h | 8h | 12h |
|---|---:|---:|---:|
| Long cada ventana | n=323, avg=-13.8 bps, WR=41.2%, DD=-44.8% | n=161, avg=-16.9 bps, WR=46.6%, DD=-31.2% | n=107, avg=-19.7 bps, WR=48.6%, DD=-27.6% |
| Radar parcial | n=69, avg=-1.4 bps, WR=50.7%, DD=-8.8% | n=52, avg=+8.9 bps, WR=50.0%, DD=-5.8% | n=40, avg=+12.3 bps, WR=50.0%, DD=-9.7% |
| Order book | n=157, avg=-8.0 bps, WR=45.9%, DD=-13.8% | n=101, avg=-9.1 bps, WR=47.5%, DD=-12.1% | n=78, avg=+1.0 bps, WR=50.0%, DD=-9.7% |
| Order book inverso* | n=157, avg=-12.0 bps, WR=42.7%, DD=-24.1% | n=101, avg=-10.9 bps, WR=40.6%, DD=-17.2% | n=78, avg=-21.0 bps, WR=43.6%, DD=-19.9% |
| Taker continuación | n=171, avg=-9.6 bps, WR=40.4%, DD=-24.1% | n=119, avg=-5.0 bps, WR=47.1%, DD=-19.5% | n=84, avg=-0.5 bps, WR=41.7%, DD=-15.4% |
| Taker inverso* | n=171, avg=-10.4 bps, WR=44.4%, DD=-17.9% | n=119, avg=-15.0 bps, WR=42.9%, DD=-22.1% | n=84, avg=-19.5 bps, WR=48.8%, DD=-16.4% |
| Crowding contrarian | n=188, avg=-3.9 bps, WR=48.9%, DD=-24.7% | n=96, avg=+1.7 bps, WR=47.9%, DD=-17.3% | n=65, avg=+5.4 bps, WR=41.5%, DD=-13.1% |
| Funding contrarian | n=29, avg=+3.6 bps, WR=41.4%, DD=-3.1% | n=19, avg=+32.4 bps, WR=57.9%, DD=-1.1% | n=16, avg=-16.9 bps, WR=43.8%, DD=-7.1% |
| Liquidaciones continuación | n=248, avg=-13.2 bps, WR=43.1%, DD=-43.9% | n=136, avg=-0.7 bps, WR=48.5%, DD=-16.2% | n=96, avg=+3.6 bps, WR=41.7%, DD=-11.6% |
| Liquidaciones inversas* | n=248, avg=-6.8 bps, WR=45.2%, DD=-19.6% | n=136, avg=-19.3 bps, WR=39.7%, DD=-28.5% | n=96, avg=-23.6 bps, WR=42.7%, DD=-24.7% |
| Precio+OI continuación | n=142, avg=-22.1 bps, WR=33.8%, DD=-38.1% | n=100, avg=-34.5 bps, WR=40.0%, DD=-37.3% | n=73, avg=-20.9 bps, WR=43.8%, DD=-18.7% |
| Precio+OI inverso* | n=142, avg=+2.1 bps, WR=52.1%, DD=-9.9% | n=100, avg=+14.6 bps, WR=53.0%, DD=-8.1% | n=73, avg=+0.9 bps, WR=47.9%, DD=-12.0% |
| Voto compuesto ≥2 | n=177, avg=-11.5 bps, WR=43.5%, DD=-35.9% | n=109, avg=-7.3 bps, WR=45.9%, DD=-19.8% | n=85, avg=-4.7 bps, WR=43.5%, DD=-20.1% |

## Hallazgos adversariales

1. **No aparece un edge robusto.** Ninguna regla positiva mantiene su IC 95% completamente sobre cero.
2. **Radar parcial: candidato no validado.** Mejora a 8h/12h en IS y OOS, pero alterna meses positivos y negativos y tiene muestras OOS de 52/40.
3. **Precio+OI como continuación queda refutado.** Pierde OOS a 4h y 8h con IC 95% completamente bajo cero. Su inversa es post-hoc y no fue positiva en IS.
4. **Liquidaciones como continuación inmediata queda refutada a 4h.** El resultado OOS es negativo con IC 95% bajo cero.
5. **Order book, taker y crowding son contexto, no gatillos.** Ninguno supera costos de forma estable.
6. **Funding a 8h no es accionable:** el resultado positivo usa sólo 19 operaciones OOS y se invierte a 12h.
7. **Hay desplazamiento de régimen.** El quintil IS bajo de crowding no aparece ni una vez OOS y el de funding sólo aparece tres veces.

### Incertidumbre de los candidatos positivos

| Candidato | Horizonte | Media neta | IC 95% |
|---|---:|---:|---:|
| Radar parcial | 8h | +8.9 bps | [-20.9, +39.2] |
| Radar parcial | 12h | +12.3 bps | [-34.7, +61.2] |
| Precio+OI inverso* | 8h | +14.6 bps | [-9.6, +39.4] |

## Sensibilidad de costos OOS a 8h

| Regla | 0,05% | 0,10% | 0,15% |
|---|---:|---:|---:|
| Radar parcial | +13.9 bps | +8.9 bps | +3.9 bps |
| Precio+OI inverso* | +19.6 bps | +14.6 bps | +9.6 bps |
| Liquidaciones inversas* | -14.3 bps | -19.3 bps | -24.3 bps |
| Taker inverso* | -10.0 bps | -15.0 bps | -20.0 bps |

## Extremos aprendidos en IS → resultado OOS a 4h

| Variable | N bajo/alto | Bajo | Alto | Alto−bajo |
|---|---:|---:|---:|---:|
| `oi_change` | 67/67 | -0.5 bps | -12.7 bps | -12.2 bps |
| `funding` | 3/179 | -41.1 bps | -9.6 bps | +31.5 bps |
| `crowd_long` | 0/73 | +0.0 bps | -12.7 bps | -12.7 bps |
| `taker_buy` | 87/59 | -10.1 bps | -1.0 bps | +9.1 bps |
| `book_ratio` | 62/76 | -5.8 bps | +1.4 bps | +7.2 bps |
| `liq_imbalance` | 81/83 | -4.9 bps | +0.1 bps | +5.0 bps |
| `partial_radar` | 92/37 | -3.7 bps | +10.1 bps | +13.8 bps |

## Criterio de lectura

- Una media positiva sin IC 95% sobre cero no se considera edge.
- Consistencia mensual pesa más que el mejor agregado.
- El histórico cubre un solo semestre de 2026: no prueba estabilidad de régimen.
- Ninguna regla modifica el bot; todos los resultados son research-only.
- `*` Las variantes inversas son exploratorias y tienen penalización por haber sido revisadas junto a su opuesto.

## Recomendación

- No usar CoinGlass como señal de entrada ni modificar el bot con estas reglas.
- Mantenerlo como contexto visual y registrar sus variables junto a cada trade forward del Diario.
- Revaluar sólo cuando existan al menos 100 decisiones forward alineadas con setups reales; el histórico genérico de BTC no sustituye esa prueba.
- No promover el Radar parcial: queda visible como research e incompleto.
