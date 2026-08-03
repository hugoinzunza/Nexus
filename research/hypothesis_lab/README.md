# NexUX Hypothesis Lab v0.1

Fundación reproducible y estrictamente research-only para experimentos pre-registrados. `HYP-EXIT-001` compara targets sobre exactamente los mismos setups, entrada y SL. El motor no importa módulos de ejecución y no expone endpoints ni promoción.

`HYP-EXIT-002` compara salidas híbridas que conservan el target original: parciales pequeños en 2R/3R, runner estructural y protección a break-even después de 3R. El export v3 conserva la fuente causal del target original y el Lab rechaza un pivote o rango que no estuviera confirmado en la vela de decisión.

`HYP-EXIT-003-SHADOW` observa hacia adelante `protect_3r_runner_original` sin
intervenir ninguna operación. La cohorte comienza después del preregistro y
registra todas las operaciones activadas, no solo las que posteriormente llegan
a 3R. El proceso local lee `data/setups.json`, usa GET públicos de Binance y
escribe exclusivamente en
`data/hypothesis_lab/shadow/protect_3r_runner_original.json`.

`HYP-COST-001` compara stops de 1,00x, 0,75x, 0,50x y 0,35x manteniendo fija la
entrada, la activación y el precio del target original. Como el export v3 no
contiene spread ni slippage observados, la primera ejecución usa escenarios
pre-registrados y los identifica como tales; no los presenta como costos reales
medidos.

`HYP-COST-002` audita la viabilidad operacional de esas mismas variantes sin
buscar una ganadora. Separa el retorno por nocional de la amplificación mecánica
de la unidad R y simula capacidad con riesgo fijo, account heat y límites de
nocional. Reutiliza la muestra histórica, por lo que todo resultado sigue siendo
exploratorio y no puede promover cambios.

`HYP-COST-003-TELEMETRY` inicia una cohorte forward para medir fills, spread
detectado y comisiones confirmadas sin completar datos ausentes con supuestos.
Live principal y Testnet permanecen separados. El observador lee los ledgers y
escribe exclusivamente en `data/hypothesis_lab/telemetry/`.

## Vista web y separacion de runtime

La vista autenticada de solo lectura vive en `/m/hypothesis-lab/`. Presenta por
separado los estudios historicos cerrados y los observadores forward, incluyendo
la frescura de cada salida y de sus fuentes. No expone endpoints `POST`, no
importa el bot y no permite promover una hipotesis.

El codigo y los datos persistentes pueden vivir en arboles distintos. El shadow
observer recibe `--setups` y `--output` explicitos; la telemetria recibe
`--input-root` y `--output`. La web resuelve sus diagnosticos desde
`NEXUX_RESEARCH_RUNTIME_ROOT`. Esta separacion evita que un cambio de rama deje
procesos vivos leyendo rutas inexistentes.

## Flujo

```bash
python3 -m research.hypothesis_lab.cli validate
python3 -m research.hypothesis_lab.cli preregister
python3 -m modules.trading.run_setup_backtest  # genera export enriquecido gitignored
python3 -m research.hypothesis_lab.cli run
python3 -m research.hypothesis_lab.cli run \
  --spec research/hypothesis_lab/specs/v1/HYP-EXIT-002.frozen.json
python3 -m research.hypothesis_lab.shadow_exit
./tools/start_exit_shadow.command
python3 -m research.hypothesis_lab.cost_study
python3 -m research.hypothesis_lab.cost_viability
python3 -m research.hypothesis_lab.cost_telemetry
./tools/start_cost_telemetry.command
```

El preregistro queda inmutable por `hypothesis_id + spec SHA-256` en SQLite antes de cualquier ensayo. Cada ejecución guarda commit, hashes de spec/datasets/código, semilla, timestamp y conteo de ensayos. Los 210 ensayos y todos sus candidatos —incluidos descartados— quedan en `data/hypothesis_lab/lab.sqlite3`.

La inferencia usa bootstrap de meses completos y una corrección Holm sobre las seis comparaciones target-vs-original únicas. Como el mismo costo por setup se resta a ambos lados, los escenarios base/duro/extremo se usan para sensibilidad económica y no se cuentan tres veces como evidencia. La suficiencia se expresa mediante CI y mínimo efecto detectable. DSR/PBO y Monte Carlo de secuencias quedan bloqueados explícitamente; no se fabrican resultados ni se permutan trades IID.

**Research only - No señal - No bot**
