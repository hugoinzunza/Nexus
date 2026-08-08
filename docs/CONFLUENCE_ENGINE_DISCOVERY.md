# NexUX Confluence Engine Discovery

Estado: **DISCOVERY COMPLETE / IMPLEMENTATION NOT AUTHORIZED**

Fecha: 2026-08-07

Alcance: arquitectura descriptiva, read-only, sin senales ni cambios operativos.

## 1. Necesidad observada

NexUX ya observa estructura de precio, niveles calculados, derivados,
liquidaciones, profundidad, order book y contexto macro. El problema no es la
ausencia de datos: es que cada modulo publica su lectura con una semantica
distinta y el usuario debe reconstruir manualmente cuando varias lecturas se
refieren a la misma zona o fenomeno.

La oportunidad es una capa que responda, de manera demostrable:

- que observo cada productor;
- que evidencia converge y cual solo repite el mismo origen;
- que evidencia contradice la lectura;
- donde se concentra espacial y temporalmente;
- que dato falta o esta vencido;
- que observacion futura confirmaria o invalidaria la descripcion.

Esta capa no debe decidir comprar, vender, entrar, salir, asignar capital ni
estimar probabilidades. Mas coincidencias tampoco significan mas edge.

## 2. Inventario de modulos relevantes

### Trading (`modules/trading`)

Produce tres superficies distintas:

1. `state`: ticker, libro, velas y derivados simples (`range_pos`, spread,
   momentum y book imbalance). El poller obtiene esta superficie desde
   Crypto.com.
2. `candles`: historia de grafico. Puede combinar historia local con tramo
   reciente de Binance empujado desde VPS; declara `fuente`, metadata del push y
   stream vivo.
3. `smc`: dealing range, FVG, POI, CDC, objetivos estructurales, plan descriptivo
   y gate de regimen. Son transformaciones de velas; no constituyen nuevas
   fuentes independientes.

Fortalezas:

- POI y estructura contienen timestamps causales internos;
- la vista declara que las zonas son contexto y no recomendacion;
- el grafico distingue el venue del tramo reciente.

Brechas:

- `state` no publica freshness por instrumento ni timestamps propios para book,
  ticker y velas;
- `smc` no expone una provenance global estable del feed usado;
- grafico, estado y SMC pueden describir venues distintos;
- `signals` repite informacion de ticker, velas y book del mismo snapshot.

### Accion del precio (`modules/inteligencia`)

Produce:

- pivotes confirmados y tendencia por timeframe;
- piernas causales, retrocesos y extensiones;
- apertura anual y semanal;
- Pivot Points diarios;
- referencias estructurales y capas calculadas;
- alineacion multi-timeframe y espacio estructural disponible.

Es hoy la salida mas explicita en causalidad. Publica `as_of`, fuente por
timeframe, `pivot_t`, `confirmed_at`, razon de seleccion y `evidence_status`.
Tambien distingue correctamente:

- estructura observada;
- aritmetica no predictiva;
- rejilla anual refutada como predictor;
- liquidez todavia no implementada.

Todo este modulo pertenece a la familia `price_structure`: muchas lineas no son
muchas confirmaciones independientes.

### CoinGlass (`modules/coinglass`)

Tiene dos vias de captura:

1. API normalizada: precio, OI, funding, ratios long/short, taker flow,
   liquidaciones, order book y capacidades disponibles.
2. Navegador autorizado: mapa y heatmap de liquidaciones, depth delta y ordenes
   ballena, con validacion de edad, simbolo y cobertura.

Fortalezas:

- `captured_at`, `bar_time`, origen forward/backfill y capabilities;
- visual snapshot con fuente declarada, edad maxima y cobertura;
- historia de book conserva huecos por tiempo y hace visible perdida de capturas;
- ausencia de endpoint se representa como dato faltante, no como cero.

Brechas:

- API, visual map y heatmap pueden ser transformaciones del mismo universo de
  liquidaciones;
- book ratio, depth delta, heatmap y whale walls pueden compartir el mismo libro;
- varias series agregan exchanges y otras son solo Binance;
- timestamps de tooltips visuales no tienen la misma precision que timestamps de
  API;
- `experimental_pressure`, `visual_indicator` y `visual_shadow` son artefactos de
  research y no deben alimentar una sintesis descriptiva.

### Market Ribbon y Context Recorder (`modules/command_center`)

Market Ribbon normaliza:

- SPX, VIX y DXY desde Yahoo Finance;
- TOTAL desde CoinGecko;
- BTC, ETH, SOL y XRP perpetuos desde Binance Futures.

Cada activo incluye precio, variacion, `observed_at_ms`, fuente, tipo y freshness.
El Context Recorder agrega captura append-only, hash chain, calidad y provenance.
El Interpreter solo compara snapshots almacenados y se abstiene ante cambios de
fuente, datos viejos, brechas o historia insuficiente.

Estos contratos son un buen precedente para tiempo, abstencion e integridad. No
son aun un contrato de observacion de mercado completo y la coleccion permanece
sujeta a su activacion separada.

### Macro (`modules/trading/news.py`, `dashboard.py`, `regime.py`)

Existe:

- calendario de alto impacto desde el feed semanal de Forex Factory;
- ventanas para FOMC, tasas, CPI, NFP, PCE y GDP;
- VIX diario desde Yahoo, anti-repaint y cacheado;
- DXY y VIX en Market Ribbon;
- un termometro macro descriptivo del Home.

No existe aun una familia macro completa y homogenea. Yields no estan
incorporados, el calendario no equivale a sorpresa macro y VIX aparece por dos
caminos que comparten Yahoo como origen.

### Modulos que no son evidencia de mercado

- Bot, posiciones, PnL y estados de ejecucion son contexto operacional, no
  confirmaciones de mercado.
- Hypothesis Lab presenta estudios y cohortes; no produce observaciones para la
  sintesis.
- Operational Timeline y Health Engine describen NexUX, no el mercado.
- Claude grader, briefs y cualquier texto de IA quedan fuera.

## 3. Mapa de fuentes de datos

| Fuente primaria | Productores actuales | Datos | Familia raiz |
|---|---|---|---|
| Binance Futures | Trading chart/push, Inteligencia, Market Ribbon, precio de control CoinGlass | OHLCV, precio, cambio 24 h | `price_structure` |
| Crypto.com | Trading `state` y fallback SMC | ticker, book, OHLCV | `price_structure` / `liquidity_microstructure` |
| CoinGlass API | CoinGlass basic/advanced | OI, funding, positioning, taker, liquidaciones, books | `derivatives_positioning` / `liquidity_microstructure` |
| CoinGlass web autorizado | CoinGlass visual | mapas, heatmaps, depth, walls | `liquidity_microstructure` |
| Yahoo Finance | Market Ribbon y regime | SPX, VIX, DXY | `macro_context` |
| CoinGecko | Market Ribbon | capitalizacion cripto total | `cross_market_context` |
| Forex Factory feed | News/fundamental guard | calendario y ventanas macro | `macro_context` |
| Archivos locales versionados | Trading/Inteligencia fallback | historia OHLCV | misma familia del venue original, con otra freshness |

El `source` debe identificar origen, venue, instrumento, mercado y metodo de
captura. `CoinGlass` o `Binance` por si solos no son provenance suficiente.

## 4. Independencia y dependencia entre senales

### Taxonomia preliminar

1. `price_structure`
   - precio, OHLCV, pivotes, tendencia, FVG, POI, CDC, rangos, retrocesos,
     extensiones, medias, momentum y volatilidad derivada.
2. `derivatives_positioning`
   - OI, funding, long/short accounts, top traders y posicionamiento.
3. `liquidity_microstructure`
   - order book, depth, walls, taker flow, mapas y heatmaps de liquidacion.
4. `volume_flow`
   - volumen negociado, taker buy/sell y futuras medidas de flujo con origen
     verificable.
5. `macro_context`
   - calendario, VIX, DXY, yields y releases macro.
6. `cross_market_context`
   - SPX, TOTAL, fuerza relativa y relaciones entre activos.
7. `temporal_context`
   - sesion, apertura semanal/anual y distancia temporal a eventos.

La taxonomia describe linaje, no pesos ni importancia.

### Casos que no deben contarse dos veces

- precio, momentum, pivotes, tendencia, FVG y POI derivados de la misma serie de
  velas son una familia, no seis votos;
- tendencia 1h, 4h y 1d puede aportar escalas distintas, pero sigue compartiendo
  el mismo origen de precio;
- mapa, heatmap y liquidaciones agregadas de CoinGlass pueden repetir el mismo
  fenomeno de liquidacion;
- book imbalance, depth delta y whale walls pueden provenir del mismo libro;
- top traders, top accounts y global accounts son segmentos relacionados, no
  observadores totalmente independientes;
- VIX de `regime.py` y VIX del Market Ribbon comparten Yahoo;
- precio Binance usado para validar un canvas CoinGlass no agrega evidencia a la
  lectura CoinGlass;
- un nivel calculado que coincide con un pivote no es dos observaciones si ambos
  nacen del mismo OHLCV.

### Independencia util

La sintesis debe trabajar con `lineage_key`, no solo con `module_id`. Dos modulos
son independientes solo si difieren materialmente en fuente o mecanismo de
observacion. Puede existir independencia parcial, que debe declararse como
`shared_source`, nunca redondearse a independiente.

## 5. Arquitectura actual relevante

NexUX tiene dos contratos aprovechables pero insuficientes por separado:

1. El contrato modular (`NexusModule`) ofrece APIs GET, health y aislamiento de
   ciclo de vida, pero no define schemas de dominio entre modulos.
2. El Wire ABI v1 del Command Center define envelope, source, timestamps,
   freshness, degradacion y limites. Su `data` es intencionalmente abierto y el
   ABI esta congelado.

No existe hoy un bus semantico comun para observaciones de mercado. Tampoco hay
un registro donde Trading, Inteligencia y CoinGlass publiquen observaciones
normalizadas. Una implementacion que lea directamente sus diccionarios internos
quedaria acoplada a detalles no contractuales.

## 6. Alternativas de diseno

### A. View-model en Command Center

Ventaja: integracion visual rapida.

Desventajas: mezcla semantica con presentacion, dificulta reutilizacion por
Aurora y Trading Intelligence, y puede ocultar dependencia de fuentes. No
recomendada.

### B. Extension del EventBus o Wire ABI v1

Ventaja: transporte ya probado.

Desventajas: reabre infraestructura congelada y confunde contrato de transporte
con schema de dominio. Rechazada para v1.

### C. Servicio externo

Ventaja: aislamiento fuerte.

Desventajas: otra operacion, autenticacion y despliegue antes de demostrar la
semantica. Prematura.

### D. Nuevo modulo NexUX con nucleo puro y adapters

Ventajas:

- frontera read-only visible;
- no modifica productores;
- modelo de dominio testeable con fixtures;
- proyecciones separadas para Command Center, Aurora y futura captura cientifica;
- puede abstenerse si un adapter no satisface provenance o freshness.

Riesgo: si los adapters consumen diccionarios internos sin contratos, el
acoplamiento reaparece.

### E. Libreria compartida sin modulo

Ventaja: nucleo puro simple.

Desventaja: no define ownership, autorizacion ni superficie publica. Util como
implementacion interna de D, no como arquitectura completa.

## 7. Propuesta recomendada

Adoptar conceptualmente la alternativa D:

```text
Productores read-only
  -> Observation Adapters
  -> MarketObservation v1 (contrato de dominio nuevo, no Wire ABI)
  -> Lineage Resolver
  -> Spatial/Temporal Grouper
  -> Descriptive Synthesis
  -> Proyecciones read-only
       - Command Center
       - Aurora (futura, allowlisted)
       - export cientifico prospectivo (futuro protocolo separado)
```

El componente deberia ser un **aggregator descriptivo** alojado como nuevo modulo
NexUX. Su nucleo debe ser una funcion pura: recibe observaciones ya normalizadas y
devuelve una sintesis o una abstencion. El modulo aporta adapters, autorizacion,
health y API read-only.

No debe importar Bot, ejecutores, credenciales, stores de trades ni politicas de
riesgo. Tampoco debe escribir en los modulos fuente.

Antes de cualquier integracion real se necesitan contratos read-only estables por
productor. Durante un prototipo, los adapters deben operar solo sobre fixtures
congelados; no sobre endpoints productivos.

## 8. Modelo conceptual de observacion

No es un schema autorizado. Es la minima semantica que el siguiente gate deberia
formalizar:

```json
{
  "observation_id": "opaque-id",
  "schema_version": "1.0.0-candidate",
  "subject": {"symbol": "BTCUSDT", "venue": "Binance", "market": "futures"},
  "family": "price_structure",
  "phenomenon": "confirmed_resistance",
  "stance": "supportive|adverse|mixed|neutral|unknown",
  "value": {"kind": "price_zone", "low": 65320.0, "high": 65450.0},
  "effective_at_ms": 0,
  "observed_at_ms": 0,
  "valid_from_ms": 0,
  "stale_at_ms": 0,
  "expires_at_ms": 0,
  "source": {
    "provider": "nexux.inteligencia",
    "origin": "binance_futures_vps",
    "method": "confirmed_pivot",
    "source_ref": "opaque-reference"
  },
  "lineage": {
    "lineage_key": "binance:BTCUSDT:futures:ohlcv:4h",
    "derived_from": ["opaque-source-observation"],
    "independence": "primary|derived|shared_source"
  },
  "quality": {
    "freshness": "live|current|stale|expired|unknown",
    "coverage": "complete|partial|unknown",
    "causal": true
  },
  "evidence_status": "descriptive_unvalidated"
}
```

Campos prohibidos en este contrato: `buy`, `sell`, `entry`, `exit`,
`position_size`, `risk_multiplier`, `win_probability`, `confidence_score` y
cualquier instruccion equivalente.

## 9. Provenance y freshness

Cada observacion debe conservar cuatro relojes distintos:

- `effective_at_ms`: cuando ocurrio el hecho segun la fuente;
- `observed_at_ms`: cuando NexUX lo recibio;
- `valid_from_ms`: cuando causalmente pudo conocerse, importante para pivotes;
- `stale_at_ms` / `expires_at_ms`: limites de uso descriptivo.

Reglas propuestas:

1. Nunca reemplazar un timestamp faltante por `now`.
2. Nunca presentar fallback local como live.
3. No agrupar observaciones cuyos intervalos de validez no se superponen.
4. Una observacion stale puede mostrarse como antecedente, pero no como
   confluencia vigente.
5. Un cambio de venue o proveedor rompe continuidad salvo contrato explicito.
6. La provenance debe sobrevivir completa en la salida sintetizada.
7. Si una fuente visual usa timestamps inferidos, debe declarar precision e
   inferencia.

## 10. Tratamiento de contradicciones

La contradiccion es informacion de primera clase, no ruido a promediar.

La sintesis deberia producir cuatro colecciones separadas:

- `observations`: evidencia valida disponible;
- `convergences`: fenomenos compatibles agrupados por zona/tiempo y deduplicados
  por linaje;
- `contradictions`: evidencia incompatible, conservando ambas ramas;
- `missing_evidence`: familias ausentes, vencidas o no comparables.

No se debe resolver una contradiccion mediante mayoria ni ponderacion oculta.
Ejemplo: estructura alcista entrando en resistencia no es una lectura que deba
reducirse a neutral; son dos hechos simultaneos que deben permanecer visibles.

`confirmation` e `invalidation` deben ser condiciones observables y tipadas, no
pronosticos. Si un productor no puede expresar una condicion causal, ambos campos
deben quedar `unknown`.

## 11. Frontera NexUX / Trading Intelligence / Trading Bot

### NexUX

- normaliza observaciones;
- resuelve linaje;
- agrupa por zona y tiempo;
- expone convergencias, contradicciones, faltantes y condiciones observables;
- se abstiene ante evidencia insuficiente.

### Trading Intelligence Lab

- determina si una sintesis agrega informacion predictiva;
- mide redundancia, tasas base, falsos positivos, EV y robustez OOS;
- conserva cohortes y protocolos independientes.

La cohorte prospectiva actual del TIL observa lifecycle de setups y esta
congelada. No debe recibir eventos de confluencia. Una investigacion futura exige
nuevo protocolo, schema, baseline inicial y collector separado, sin backfill.

### Trading Bot

- no consume observaciones ni sintesis durante esta etapa;
- no cambia filtros, sizing, stops, targets ni gates;
- no debe importar el modulo de confluencia;
- cualquier conexion futura requiere evidencia cientifica y autorizacion propia.

## 12. Posible integracion futura con Aurora

Aurora ya define una frontera NexUX read-only por HTTP loopback y allowlist. Una
integracion futura coherente seria una consulta explicita, por ejemplo "que
observa NexUX sobre BTC", con resultado validado contra un contrato dedicado.

Condiciones:

- Aurora consume una proyeccion, no importa codigo ni lee stores de NexUX;
- la respuesta conserva provenance, freshness, contradicciones y abstenciones;
- Aurora puede explicar o leer la sintesis, pero no convertirla en accion;
- no se escribe memoria permanente automaticamente;
- la ausencia de datos produce `unknown`, nunca una interpretacion fabricada;
- el endpoint no se agrega a la allowlist hasta un gate propio de Aurora.

Aurora no debe ser el lugar donde se calcula la confluencia. Eso haria depender la
verdad operacional de una capa conversacional y duplicaria reglas.

## 13. Riesgos

### P0 conceptuales

- **Doble conteo:** tratar derivados del mismo OHLCV o libro como votos
  independientes.
- **Deriva hacia signal engine:** agregar score, direccion o probabilidad sin
  evidencia cientifica.
- **Falsa actualidad:** sintetizar datos con distinta freshness como si fueran
  simultaneos.
- **Venue mismatch:** combinar Binance, Crypto.com y agregados sin declararlo.

### P1 arquitectonicos

- acoplar adapters a diccionarios internos no versionados;
- reabrir Wire ABI/EventBus para resolver un problema de dominio;
- usar outputs experimentales de CoinGlass como hechos;
- confundir ausencia de datos con neutralidad;
- ocultar contradicciones en una frase demasiado resumida;
- contaminar la cohorte prospectiva del TIL.

### P2 operacionales

- crecimiento de latencia al consultar todos los modulos en serie;
- fallos parciales que degraden toda la sintesis;
- zonas agrupadas con tolerancias arbitrarias;
- explosion visual de observaciones redundantes;
- depender de scraping visual fragil sin declarar cobertura.

## 14. Preguntas abiertas

1. Cual sera el sujeto canonico: simbolo, venue y mercado, o activo economico
   independiente del venue?
2. Que tolerancia espacial agrupa dos zonas sin inventar una regla universal?
3. Como se representa independencia parcial entre agregado CoinGlass y Binance?
4. Que freshness corresponde a cada fenomeno y timeframe?
5. Que contratos read-only aceptaran Trading, Inteligencia y CoinGlass?
6. Debe una condicion de confirmacion pertenecer al productor o al sintetizador?
7. Como se versionan cambios de taxonomia sin reabrir Wire ABI v1?
8. Que campos visuales de CoinGlass tienen timestamp efectivo suficientemente
   preciso?
9. Que significa `macro_context` cuando solo existe calendario, sin actual ni
   sorpresa del release?
10. Que superficie minima necesita Command Center sin agregar una tarjeta?

## 15. Propuesta de siguiente Gate

### Gate CE-1: Observation Contract & Lineage Fixtures

Objetivo: demostrar que observaciones heterogeneas pueden normalizarse,
deduplicarse y contradecirse sin producir una senal.

Autorizaria exclusivamente:

1. congelar taxonomia candidata y vocabulario permitido;
2. definir JSON Schema `MarketObservation v1-candidate` y
   `DescriptiveSynthesis v1-candidate` fuera del Wire ABI;
3. crear adapters puros solo para fixtures congelados de Trading, Inteligencia,
   CoinGlass y Macro;
4. construir matriz explicita de lineage y fuentes compartidas;
5. probar freshness, abstencion, cambio de venue, contradiccion y deduplicacion;
6. revisar adversarialmente que no existan campos de decision o score;
7. documentar latencia y tamano con fixtures, sin conectar produccion.

Criterios de aprobacion:

- 100% de observaciones con provenance y reloj causal suficiente;
- ningun dato stale contado como vigente;
- derivados con mismo `lineage_key` no aumentan el numero de familias
  independientes;
- contradicciones preservadas sin resolver por score;
- ausencia de una familia produce `missing`, no `neutral`;
- cero imports de Bot, cero ordenes, cero credenciales y cero escrituras;
- TIL, Aurora, EventBus, Wire ABI, Railway, VPS y produccion intactos.

Fuera del Gate CE-1:

- endpoints reales;
- UI;
- recorder prospectivo;
- integracion Aurora;
- integracion Trading Intelligence;
- integracion Bot;
- scores, probabilidades y decisiones.

Solo tras aprobar CE-1 corresponderia decidir si existe merito para un prototipo
read-only conectado a fuentes reales.

---

## Resolucion

**Confluence Engine: DISCOVERY COMPLETE / IMPLEMENTATION NOT AUTHORIZED**

La arquitectura actual permite construir una capa descriptiva, pero todavia no
existe un contrato de observacion comun ni una garantia suficiente de
independencia entre lecturas. El siguiente paso correcto no es sintetizar en
produccion: es congelar semantica, linaje y abstencion sobre fixtures.
