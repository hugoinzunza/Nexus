# NEXUX Command Center - TradingView Adapter Spike

- **Estado:** APROBADO Y CERRADO
- **Fecha de cierre:** 2026-07-30
- **Implementacion validada:** `b0e8d6d`
- **Producto probado:** Advanced Real-Time Chart Widget
- **Factory productiva:** NO AUTORIZADA EN ESTE DOCUMENTO
- **Linea B visual:** BLOQUEADA

## Objetivo

El spike verifico que un proveedor externo real puede implementar
`ChartProvider` sin modificar el Wire ABI v1, EventBus, Gateway WebSocket,
registro estatico ni interfaces headless.

Este cierre documenta la frontera tecnica comprobada. No autoriza despliegue,
composicion visual ni activacion en el catalogo productivo.

## Producto integrado

La implementacion usa el widget publico alojado por TradingView mediante el
script oficial:

```text
https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js
```

El resultado es un iframe cross-origin administrado por TradingView. NexUX
controla su configuracion inicial y su ciclo de vida exterior, pero no su DOM,
estado interno ni APIs privadas.

Este producto no debe confundirse con la biblioteca licenciada y self-hosted
**Advanced Charts**.

## Capacidades comprobadas

El adaptador proporciona:

- montaje y destruccion deterministas;
- configuracion inicial de simbolo, intervalo y tema;
- mapa estatico de BTC, ETH, SOL, ADA y XRP contra Binance perpetual;
- intervalos 15m, 1h, 4h, 1D y 1W;
- health y estados `detached`, `mounting`, `ready`, `degraded`, `failed` y
  `destroyed`;
- timeout, codigos de error estables y observabilidad de montaje;
- idempotencia al repetir un montaje identico;
- atribucion visible a TradingView.

El fixture real monto `BINANCE:BTCUSDT.P` en 1h y alcanzo `ready`. Una carga
transitoria que excedio el timeout produjo `degraded` sin bloquear la pagina ni
declarar un exito falso.

## Capacidades deliberadamente no expuestas

`capabilities()` devuelve un conjunto vacio. El adaptador no anuncia:

- `set_symbol`;
- `set_interval`;
- `set_theme`;
- `fullscreen`;
- lectura de velas, dibujos, indicadores o layout;
- sincronizacion de cuenta o sesion de TradingView;
- control de favoritos, alertas o plantillas;
- acceso al DOM interno del grafico.

Los cambios de configuracion requieren destruir y montar de nuevo el widget.
La opcion de cambio de simbolo dentro del propio iframe pertenece a TradingView;
no constituye una capacidad programatica de NexUX.

## Widget publico frente a Advanced Charts

| Aspecto | Widget publico validado | Advanced Charts |
|---|---|---|
| Alojamiento | TradingView | Aplicacion integradora |
| Integracion | Script + iframe | Biblioteca JavaScript |
| Datafeed | TradingView | Debe proporcionarlo NexUX |
| Control en runtime | Limitado a la UI del iframe | API programatica amplia |
| DOM y estado interno | Opacos para NexUX | Integrables segun licencia/API |
| Licencia/acceso | Widget publico con atribucion | Acceso y condiciones especificas |
| Estado en NexUX | Spike aprobado | No integrado |

Las APIs documentadas para Advanced Charts no se pueden atribuir al widget
publico. El adaptador no simulara paridad entre ambos productos.

## Limitaciones operacionales

- TradingView es una dependencia de red y disponibilidad externa.
- El iframe cross-origin impide verificar o reconstruir su estado interno.
- El evento `load` confirma la carga del iframe, no la exactitud de cada dato
  mostrado por el proveedor.
- La tabla de simbolos es explicita y falla cerrado ante pares o intervalos no
  mapeados.
- La configuracion no cambia en caliente.
- El widget puede cambiar su implementacion sin que NexUX controle su version.
- Login, indicadores privados y persistencia de layouts no fueron validados.
- El spike no constituye una validacion de UX, densidad, legibilidad ni
  ergonomia.

## Criterios para autorizar una factory productiva

La factory solo podra proponerse en un cambio separado que demuestre:

1. manifiesto estatico con exactamente las capacidades reales;
2. autorizacion previa a construccion y cero ejecucion para roles excluidos;
3. CSP y conectividad compatibles con los dominios oficiales requeridos;
4. timeout, degradacion y recuperacion observables en el runtime;
5. pruebas de montaje, destruccion y shutdown dentro del registro;
6. ausencia de cambios en el Wire ABI v1 y su fingerprint;
7. revision vigente de condiciones de uso, atribucion y privacidad;
8. rollback que retire la factory sin afectar snapshot, EventBus o Gateway.

La factory no autoriza por si misma una superficie visual definitiva. Esa
decision sigue perteneciendo a Linea B.

## Criterios para evaluar una migracion a Advanced Charts

La migracion solo se justificara si existe una necesidad aprobada que el widget
no puede satisfacer, por ejemplo:

- sincronizacion programatica de simbolo, intervalo o tema sin remontaje;
- indicadores, dibujos o layouts controlados por NexUX;
- persistencia y restauracion de estado del grafico;
- integracion con un datafeed propio;
- eventos internos necesarios para coordinacion entre modulos;
- requisitos de observabilidad o accesibilidad imposibles dentro del iframe.

Ademas deberan existir acceso/licencia compatibles, revision legal, datafeed
operativo, adaptador independiente y conformidad con el mismo
`ChartProvider`. Una migracion no modificara el Wire ABI para acomodar al
proveedor.

## Evidencia

- Commit del spike: `b0e8d6d`.
- Suite al cierre: 699 pruebas aprobadas.
- Harness contractual: aprobado.
- Wire ABI v1:
  `b0a8a7efa623a1aae4b681c3cfc42790d36a6a14fbc689688026c523f2e49b46`.
- Catalogo productivo: sin factory activa.
- `main`: sin modificaciones por el spike.

Fuentes oficiales:

- [Formatos de widgets](https://www.tradingview.com/widget-docs/widget-formats/)
- [Advanced Real-Time Chart Widget](https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/)
- [Advanced Charts](https://www.tradingview.com/charting-library-docs/latest/)

## Resolucion

El TradingView Adapter Spike queda **APROBADO Y CERRADO**.

La arquitectura de Linea A queda validada frente a un servicio real. La factory
productiva queda habilitada para una futura propuesta tecnica separada, pero
permanece inactiva. Linea B visual continua bloqueada.
