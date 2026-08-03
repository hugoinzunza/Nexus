# HYP-COST-003 - Preregistro de telemetria forward

**Research only - No signal - No bot**

## Pregunta

¿Los escenarios declarados de spread, comision y slippage usados por
HYP-COST-001/002 representan razonablemente la ejecucion observada?

## Cohorte

Comienza en `1785634006230` ms UTC. Solo incorpora operaciones `mode=live`
abiertas desde ese instante. El ledger principal es la cohorte primaria;
Testnet se conserva como diagnostico separado y nunca satisface los minimos.

## Evidencia disponible

- Fill de entrada: `entry_price` del ledger.
- Referencia causal preferida: `activation_price`; `setup_entry` se informa por
  separado y no lo reemplaza.
- Spread: primer `bookTicker` publico observado al detectar un nuevo fill. Solo
  se considera oportuno con lag de deteccion menor o igual a 3 segundos.
- Comision: solo es observada cuando `pnl_confirmed=true`.
- Slippage de salida: queda nulo mientras el ledger no conserve la referencia
  de salida pretendida. No se infiere por cercania al SL o TP.

## Umbral previo a recalibrar escenarios

Se requieren simultaneamente, en live principal:

- 30 operaciones cerradas con comisiones confirmadas;
- 30 entradas con referencia de activacion;
- 30 entradas con spread detectado oportunamente;
- 4 semanas calendario.

Al alcanzar esos minimos solo se autoriza una revision manual de los escenarios
de research. No existe recalibracion automatica ni cambio de estrategia.

## Aislamiento

El observador lee ambos ledgers, utiliza exclusivamente GET publicos de Binance
y escribe un snapshot atomico gitignored. No importa el bot, no modifica el
Diario, no envia ordenes y no cambia Testnet, Live, Railway o VPS.
