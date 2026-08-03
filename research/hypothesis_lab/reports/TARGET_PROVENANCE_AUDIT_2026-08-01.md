# Auditoría de procedencia del target original — 2026-08-01

> Research only - No señal - No bot

## Objetivo

Verificar que el target estructural usado como baseline por `HYP-EXIT-001/002`
existía y estaba confirmado en el momento de cada decisión histórica.

## Método

- El backtest entrega a `smc_live.analyze()` únicamente velas hasta la decisión.
- El export v3 conserva precio, tipo, timestamp de origen y timestamp de confirmación.
- El cargador del Lab falla si el origen o la confirmación son posteriores a la decisión.
- También falla si el precio del target no coincide con el precio de su fuente.

## Evidencia

- Setups del universo BTC/ETH/SOL/ADA/XRP, 1h/4h: **8.640**.
- Targets desde swing confirmado: **5.712**.
- Targets desde dealing range causal: **2.928**.
- Fuentes o confirmaciones futuras: **0**.
- Precios sin correspondencia con su fuente: **0**.
- Export validado: `setup-backtest-research-v3`.

## Veredicto

La procedencia temporal del target original queda **APROBADA** para continuar
research histórico. Esto no convierte los datos en holdout virgen ni resuelve
solapamiento, correlación entre pares o account heat.

## HYP-EXIT-002

La protección a break-even después de alcanzar 3R es el único candidato que no
reduce la expectativa observada frente al target original: `+0,0144R`, con CI95
`[-0,0450; +0,0701]`. Mejora 7 de 10 combinaciones par/TF y 4 de 5 años, pero la
diferencia no es concluyente después de Holm (`p=0,6287`). Queda como candidato
para medición forward paralela, no como cambio del bot.
