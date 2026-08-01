# NexUX Hypothesis Lab v0.1

Fundación reproducible y estrictamente research-only para experimentos pre-registrados. `HYP-EXIT-001` compara targets sobre exactamente los mismos setups, entrada y SL. El motor no importa módulos de ejecución y no expone endpoints ni promoción.

`HYP-EXIT-002` compara salidas híbridas que conservan el target original: parciales pequeños en 2R/3R, runner estructural y protección a break-even después de 3R. El export v3 conserva la fuente causal del target original y el Lab rechaza un pivote o rango que no estuviera confirmado en la vela de decisión.

## Flujo

```bash
python3 -m research.hypothesis_lab.cli validate
python3 -m research.hypothesis_lab.cli preregister
python3 -m modules.trading.run_setup_backtest  # genera export enriquecido gitignored
python3 -m research.hypothesis_lab.cli run
python3 -m research.hypothesis_lab.cli run \
  --spec research/hypothesis_lab/specs/v1/HYP-EXIT-002.frozen.json
```

El preregistro queda inmutable por `hypothesis_id + spec SHA-256` en SQLite antes de cualquier ensayo. Cada ejecución guarda commit, hashes de spec/datasets/código, semilla, timestamp y conteo de ensayos. Los 210 ensayos y todos sus candidatos —incluidos descartados— quedan en `data/hypothesis_lab/lab.sqlite3`.

La inferencia usa bootstrap de meses completos y una corrección Holm sobre las seis comparaciones target-vs-original únicas. Como el mismo costo por setup se resta a ambos lados, los escenarios base/duro/extremo se usan para sensibilidad económica y no se cuentan tres veces como evidencia. La suficiencia se expresa mediante CI y mínimo efecto detectable. DSR/PBO y Monte Carlo de secuencias quedan bloqueados explícitamente; no se fabrican resultados ni se permutan trades IID.

**Research only - No señal - No bot**
