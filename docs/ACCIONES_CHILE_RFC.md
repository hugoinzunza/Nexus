# RFC — NexUX Acciones Chile

**Estado:** MVP read-only en construcción  
**Fecha:** 2026-08-22  
**Owner humano:** Hugo  

## Objetivo

Crear un módulo de NexUX separado del mundo cripto para observar una cartera de
acciones chilenas, analizar resultados financieros publicados por la CMF y
evaluar hipótesis de forma reproducible. Una señal o predicción nunca constituye
una orden.

## Fuentes y conectividad

### Renta 4 Chile

- No se encontró una API pública chilena documentada.
- La cartera se normaliza al contrato `{ticker, company_rut, quantity,
  average_cost, market_price, currency}`; NexUX recalcula inversión, valor,
  P/L, rentabilidad y pesos sin confiar en totales del navegador.
- La ingesta está deshabilitada por defecto y exige un token separado.
- Con autorización explícita del owner se permite capturar un snapshot desde su
  sesión web ya iniciada. No se automatiza el login, no se guardan claves y no
  se interceptan endpoints privados. La sincronización de fondo sigue bloqueada
  mientras Renta 4 no publique una API o autorice formalmente un adaptador.
- El módulo jamás incluye endpoints de compra, venta, modificación o cancelación.

### CMF

- Fuente primaria: TXT IFRS oficial publicado mensualmente en
  `https://www.cmfchile.cl/institucional/estadisticas/ver_archivo.php`.
- El cliente aplica allowlist exacta de esquema, host y path, límite de descarga,
  timeout, parser estricto y falla cerrada.
- Métricas iniciales: ventas, crecimiento interanual, utilidad operacional,
  utilidad neta, margen operacional y margen neto.
- Cada valor conserva período, RUT, sociedad, moneda, taxonomía y estado origen.
- Un colector diario descubre los dos cierres individuales más recientes y sus
  comparables interanuales, calcula SHA-256 de cada fuente y publica un cache
  compacto. Si el cierre nuevo aún es parcial, conserva el último período
  disponible por sociedad. Si la red falla, conserva el último cache válido.
- Endpoints read-only: `api/issuers?q=...`, `api/analysis?rut=...` y `api/videos`.
- Cada fuente registra URL parametrizada, hora de recuperación, estado HTTP,
  bytes, hash, completitud interanual y artefacto crudo comprimido.
- Como la CMF no informa `Content-Length`, cada período se descarga dos veces y
  ambos SHA-256 deben coincidir. Esto detecta truncamiento transitorio, no una
  alteración persistente del origen. El gzip determinista se relee y descomprime
  después de persistirlo para comprobar que reproduce exactamente la descarga.
- El dataset exploratorio queda marcado `forbidden_until_availability_join`; los
  candidatos causales se construyen únicamente tras unir sociedad, período,
  alcance y evento Telegram con `available_at`.

### Dónde corre cada colector

- Railway es la vista, no el colector. Un feed FIX 4.4 de la Bolsa es una sesión
  TCP persistente con heartbeats, números de secuencia y, normalmente, IP
  allowlisted; los contenedores de Railway se reinician y no dan IP de salida
  estable. Un puente con la sesión web de Renta 4 tampoco puede vivir ahí sin
  llevarse credenciales al servidor.
- Por eso el reparto es: el Mac mini recoge lo que exige sesión o conexión
  persistente y envía snapshots firmados; Railway guarda, normaliza y muestra.
  La CMF y el Banco Central son públicos y se consultan directo desde donde
  corra el módulo.

### Procedencia y frescura

- Toda fuente se describe con el mismo contrato: origen, modo, fecha del dato,
  fecha de recuperación, antigüedad y estado. Los modos son cerrados:
  `realtime`, `delayed`, `snapshot`, `official_publication` y `derived`.
- La fecha del dato y la de su descarga son distintas y se muestran las dos: un
  TXT de junio bajado hoy es reciente en recuperación y viejo en contenido.
- Si no se sabe cuándo se trajo un dato, el estado es `unknown`, nunca `fresh`.
  Cuando una fuente cae, la tarjeta queda degradada en vez de servir el último
  valor como si fuera de ahora. El estado agregado lo manda la peor fuente.
- Endpoints: `api/freshness` y la sección `freshness` de `api/status`.

### Cadencia del colector

- La CMF publica por período, no en flujo continuo. Sondear el listado cada
  hora es una petición; descargar los TXT completos son megabytes. Sólo se
  descarga cuando aparece un cierre que el cache no tiene, cuando no hay cache,
  o cuando el cache cumplió su edad máxima diaria.
- Si el listado no responde, se conserva el cache y se reintenta: una caída del
  regulador no gatilla descargas por las dudas.
- `cmf_probe_interval_seconds` (sondeo, por defecto 3600) y
  `cmf_refresh_interval_seconds` (edad máxima del cache, por defecto 86400).

### Precios de mercado: licencia antes que integración

- La vía correcta es el Market Data de la Bolsa de Santiago/nuam por FIX 4.4.
  No se convierten endpoints internos del sitio público en integración.
- Antes de cotizar hay que resolver **uso interno frente a redistribución**: que
  el owner vea sus precios y que cualquier visitante de nexux.cl los vea son
  dos tramos de licencia distintos. Cotizar sin esa definición da un número
  equivocado.
- Mientras no exista feed contratado, los precios provienen del snapshot manual
  y se rotulan como tales. `market_data` sigue exigiendo manifest con
  exportación adquirida o API autorizada.

### Qué desbloquea la valoración

- Tener precios no habilita recomendar. El gate del predictor pide cuatro cosas
  y los precios son una: ocho trimestres por empresa, precios ajustados con
  benchmark IPSA, universo sin sesgo de supervivencia y múltiplo sectorial
  calibrado. Hoy el mínimo por empresa es un trimestre y el universo cubre diez
  de treinta componentes.
- El cuello de botella es el gate, no la cañería. Ninguna mejora de transporte
  adelanta ese punto.

### CMF Bancos

- Los bancos listados usan un adaptador separado porque su catálogo contable no
  corresponde al TXT IFRS de sociedades: CHILE `001`, BCI `016`, BSANTANDER
  `037` e ITAUCL `039`.
- `scripts/refresh_acciones_chile_banks.py` consulta exclusivamente la API v3
  oficial por HTTPS y exige `CMF_BANKS_API_KEY`; la credencial nunca se guarda
  en URLs de procedencia, cache ni errores.
- El parser JSON valida esquema, institución, año, cuenta, mes y montos, limita
  el tamaño y rechaza redirecciones fuera del endpoint allowlisted.
- La primera métrica habilitada es la cuenta oficial `4100000`, ingresos por
  intereses y reajustes. ROE, provisiones, margen financiero y utilidad neta
  quedan pendientes de validar contra el catálogo contable vigente, sin inferir
  cuentas por nombre.
- El cache `acciones_chile_banks.json` conserva observaciones trimestrales y hash
  de cada descarga, pero permanece `forbidden_until_availability_join` hasta
  unir la publicación de Telegram. Endpoints read-only: `api/banks-status` y la
  sección `cmf_banks` de `api/status` y `api/predictor-status`.

### Dólar observado y unidades EPS

- `scripts/refresh_acciones_chile_fx.py` consulta únicamente la serie diaria
  oficial `F073.TCO.PRE.Z.D`. Prefiere la API BDE si existe `BCCH_API_TOKEN` y,
  sin credencial, usa la tabla HTML pública del mismo Banco Central mediante
  allowlist estricta, parser acotado y hash de la respuesta.
- El token se envía sólo al host `si3.bcentral.cl`; nunca se conserva en cache,
  URL de procedencia, error o snapshot de auditoría.
- El cache guarda todas las observaciones válidas, selecciona la última tasa
  disponible igual o anterior a la fecha del precio y conserva hash de la
  respuesta original.
- Una tasa oficial no autoriza por sí sola convertir EPS. Para estados rotulados
  USD, `scripts/install_acciones_chile_eps_units.py` exige evidencia auditada o
  disclosure del emisor, URL, SHA-256 y fecha, declarando explícitamente
  `USD_PER_SHARE` o `CLP_PER_SHARE`.
- La evidencia versionada también reconcilia el valor crudo del TXT CMF con el
  PDF auditado. MINERA 2025 confirma US$ 1,3495 por acción con factor 1. COPEC
  confirma US$ 0,674577; su TXT entrega 674,57, por lo que se registra y valida
  explícitamente el factor 0,001 antes de cualquier conversión.
- Sin ambas evidencias, P/E, valor justo, margen de seguridad y compra/venta
  permanecen bloqueados. Esto evita tratar los 674,57 de COPEC como USD por
  acción sólo porque la moneda de presentación general sea USD.
- `EPS 2 verificados` significa exclusivamente MINERA y COPEC; no declara lista
  la cobertura del universo. Cada emisor adicional continúa bloqueado hasta
  reconciliar su período, unidad, escala y PDF de origen.

### @inversorchileno

- El canal se usa como fuente secundaria de tesis, no como ground truth.
- Cada afirmación futura debe guardar video, fecha, timestamp, ticker/RUT, tipo
  (`hecho`, `tesis`, `opinión`) y evidencia CMF que la confirma, contradice o deja
  sin resolver.
- No se copiarán ni republicarán videos o transcripciones completas.
- El feed público ya permite indexar títulos, fechas, URL y capítulos. El primer
  lote Q2 2026 cubre, entre otras, CAP, CMPC, Cencosud, Cencomalls, SMSAAM,
  LATAM, Mall Plaza, CCU, Entel, Concha y Toro, los bancos, Enel, Colbún,
  Andina, Engie, Sonda y Pehuenche.
- Con autorización del owner se revisó además el contenido de miembros mediante
  su sesión de YouTube. Las transcripciones se usan sólo de forma transitoria
  para investigación personal: no se versionan, republican ni exponen por API.
- La rúbrica inicial referencia cuatro clases exclusivas: disciplina de venta,
  valoración/margen de seguridad, flujo de caja libre y lectura de balance.
- Principios codificados: no reaccionar a un trimestre aislado; confirmar
  deterioro repetido; revisar caja, deuda y composición del balance; contrastar
  utilidad contable con flujo libre; valorar con múltiplo propio del sector y
  tasas vigentes; exigir margen de seguridad; combinar tesis, riesgos y objetivo
  personal antes de reducir o salir.

### HechosEsencialesChile (Telegram)

- Fuente de eventos: `https://t.me/hechosesencialeschile`.
- El grupo declara uso personal y no masivo/lucrativo; NexUX conserva esa frontera.
- El colector no se une al grupo, exige una sesión que ya sea miembro, no descarga
  PDFs y descarta conversación humana.
- Solo persiste mensajes estructurados del bot: nuevo estado financiero o nuevo
  comunicado esencial.
- Para modelos, `available_at` es siempre la hora del mensaje Telegram. La hora
  declarada de emisión queda como metadata y nunca adelanta disponibilidad.
- Endpoint read-only: `api/events?type=financial_statement`.
- El monitor de cartera compara cada emisor por nombre CMF exacto con el último
  período detectado en el feed. Informa brechas de detección y hechos esenciales
  de 30 días, pero nunca predice una fecha ni interpreta ausencia como prueba de
  que el emisor no publicó.

### Universo y precios de mercado

- El catálogo temporal vive en
  `config/acciones_chile_universe_v0.1.json`; cada snapshot declara vigencia,
  cobertura, ticker, RUT con dígito verificador y fuentes.
- El primer snapshot versiona los 10 componentes principales visibles
  públicamente al 31-07-2026 y sus RUT CMF. La descarga de los 30 componentes
  prohíbe redistribución sin permiso, por lo que el universo completo debe vivir
  como dato local/licenciado. El código rechaza el top 10 para backtests.
- La Bolsa de Santiago comercializa por año sus resúmenes diarios de acciones y
  series IPSA/IGPA. NexUX no elude esa frontera ni scrapea el producto.
- `scripts/validate_acciones_chile_market_data.py` acepta un CSV normalizado sólo
  cuando el manifest declara exportación adquirida o API autorizada, método de
  ajuste y benchmark IPSA de retorno total.
- El CSV exige `session_date,ticker,open,high,low,close,volume,`
  `total_return_close,source_available_at`. Se validan duplicados, OHLC, orden
  temporal, disponibilidad con zona y cobertura del benchmark para cada rueda.
- Sólo se persiste el resumen/hash de la validación. El archivo licenciado no se
  copia al repositorio ni al cache de NexUX.
- Un universo completo autorizado se valida e instala fuera de Git con
  `scripts/install_acciones_chile_universe.py --as-of YYYY-MM-DD`; el módulo lo
  prefiere sobre el snapshot público parcial y reporta `storage=local_licensed`.
  Un snapshot marcado como completo se rechaza si no referencia una exportación
  autorizada/licenciada con SHA-256, fecha de verificación y conteo coincidente.
- Los anuncios públicos registran cambios temporales desde marzo de 2024: sin
  cambios en 2024, incorporación de ILC en marzo de 2025 y sin cambios en marzo
  de 2026. Sin un baseline completo autorizado, estos deltas no bastan para
  declarar historia libre de sesgo de supervivencia.
- El cache CMF conserva una observación por emisor–período–scope para todos los
  cierres trimestrales expuestos por la fuente, además de la vista compacta del
  último período por emisor. El join causal usa las observaciones históricas.
- El total del catálogo es la unión de RUT distintos en todos los períodos
  cargados; por eso puede superar el conteo de cualquier cierre individual. No
  representa una sección cruzada contemporánea ni un universo transable.
- Endpoints read-only: `api/universe-status` y `api/universe`.

## Auditoría OPUS/Claude

Claude Opus actúa como auditor adversarial independiente de los avances. Revisa
procedencia, look-ahead, privacidad, separación respecto de cripto, reproducibilidad,
afirmaciones predictivas y comportamiento fail-closed.

Su autoridad es exclusivamente consultiva:

- no genera órdenes ni señales operables;
- no modifica datos, políticas o modelos;
- no aprueba releases;
- no sustituye revisión humana;
- si falta credencial o la API falla, el estado es `pending`, nunca `approved`.

La ejecución es manual para controlar costo y evitar enviar cartera personal sin
una acción explícita.

El comando recibe un snapshot JSON acotado; no descubre ni lee la cartera por su
cuenta:

```bash
ANTHROPIC_API_KEY=... .venv/bin/python scripts/audit_acciones_chile.py snapshot.json
```

`scripts/refresh_acciones_chile.py` genera automáticamente un snapshot sin cartera
ni datos personales en `data/acciones_chile_audit_snapshot.json`.

La revisión Opus del 22-08-2026 confirmó el comportamiento fail-closed: sin ocho
trimestres, precios ajustados, benchmark, universo histórico, FX y unidades EPS
verificadas, `can_train=false`, `can_generate_signal=false` y compra/venta sigue
en `null`. Sus observaciones de integridad originaron la doble descarga CMF, la
verificación del gzip leído desde disco y una prueba del grafo transitivo propio.
También se hizo explícito por posición que CHILE, BCI, BSANTANDER e ITAUCL quedan
bloqueados mientras la fuente contable CMF Bancos separada no esté lista. Quedan
como límites declarados que ambas descargas CMF comparten el mismo origen y que
el análisis transitivo cubre código propio, no internals de dependencias externas.

## Fases

1. **Cartera y CMF:** importación read-only, catálogo ticker↔RUT y métricas.
2. **Biblioteca de tesis:** índice del canal y contraste CMF.
3. **Modelos research-only:** preregistro, splits temporales, benchmark simple,
   costos y evidencia fuera de muestra.
4. **Command Center:** alertas explicables y revisión humana. Sin ejecución.

La interfaz del Command Center ya permite guardar manualmente una cartera por
usuario, abrir fichas históricas y consultar un radar fundamental comparable.
También acepta precios provenientes de un snapshot web autenticado de Renta 4
y muestra valorización, P/L y asignación sin exponer credenciales del broker.
Las etiquetas `FUNDAMENTOS FUERTES`, `EN OBSERVACIÓN` y `REVISAR TESIS` son
lecturas de investigación. `comprar` o `vender` permanece nulo hasta incorporar
precio autorizado, valoración, margen de seguridad y reglas personales.

## Criterios de salida del MVP

- Cero imports desde módulos cripto o ejecutores.
- Parser CMF probado con fixture representativo.
- Cartera rechaza payloads inválidos y permanece read-only.
- Auditor visible con modelo, disponibilidad y autoridad.
- Predicciones rotuladas como investigación y sin camino a órdenes.

El diseño causal del modelo se congela por separado en
`docs/ACCIONES_CHILE_PREDICTOR_PROTOCOL.md`.
