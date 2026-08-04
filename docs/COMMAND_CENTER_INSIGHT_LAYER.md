# Command Center Insight Layer

Estado: Sprint A implementado en rama, sin merge ni despliegue.

## Objetivo

Transformar lecturas existentes en contexto operacional breve sin agregar modulos,
IA, modelos ni capacidad de decision.

## Primera regla: amplitud cripto

La superficie reutilizada es el encabezado de `Pulso de mercado`.

Entradas permitidas:

- variacion publicada de BTC, ETH, SOL y XRP;
- frescura `live` o `current`;
- snapshot actual del Market Ribbon.

La regla exige al menos tres de los cuatro activos con variacion finita y frescura
vigente. Con menor cobertura se abstiene y muestra `Contexto insuficiente`.

## Umbrales congelados

Con tres o cuatro activos elegibles:

- tres o mas positivos y mediana >= +2%: `Cripto avanza con fuerza`;
- tres o mas positivos y mediana >= +0,5%: `Cripto mantiene tono alcista`;
- tres o mas positivos con mediana menor: `Cripto avanza con cautela`;
- tres o mas negativos y mediana <= -2%: `Cripto retrocede con fuerza`;
- tres o mas negativos y mediana <= -0,5%: `Cripto mantiene tono bajista`;
- tres o mas negativos con mediana mayor: `Cripto retrocede con cautela`;
- cualquier otra distribucion: `Cripto opera sin direccion comun`.

La evidencia reconstruible conserva conteo de activos positivos y negativos, junto
con la mediana utilizada.

## Limites semanticos

Esta regla describe amplitud del snapshot. No afirma:

- duracion del movimiento;
- tendencia tecnica;
- causalidad;
- probabilidad futura;
- conveniencia de operar;
- relacion con el Bot o Trading Intelligence.

Las frases `desde hace varias horas`, `rompio`, `mantiene tendencia` o equivalentes
requieren historia temporal causal que este sprint no posee.

## Integridad arquitectonica

- estructura 67/33 intacta;
- TradingView intacto;
- shell nativa intacta;
- Wire ABI, EventBus, Gateway y Runtime intactos;
- cero nuevas tarjetas;
- cero llamadas externas adicionales;
- cero cambios en Bot, Trading Intelligence, Railway, VPS o produccion.

## Validacion

- escenarios alcista fuerte, alcista cauteloso, bajista, mixto y abstencion;
- datos stale y unknown excluidos;
- viewport 1920 x 1080 sin overflow;
- altura de Market Ribbon preservada en 74 px.

## Frontera del siguiente sprint

Sprint C agrega un interprete headless capaz de comparar snapshots temporales
causales. La coleccion permanece bloqueada hasta aprobar persistencia y respaldo;
por ello la interfaz no consume todavia sus resultados. Ninguna comparacion puede
aparecer sin una ventana forward completa y verificable.
