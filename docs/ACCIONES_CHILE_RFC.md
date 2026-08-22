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
- Fase inicial: exportación personal de cartera y movimientos, normalizada al
  contrato `{ticker, company_rut, quantity, average_cost, currency}`.
- La ingesta está deshabilitada por defecto y exige un token separado.
- No se automatiza el login, no se guardan claves y no se interceptan endpoints
  privados. Antes de crear un adaptador web se requiere autorización/confirmación
  escrita de Renta 4 sobre acceso automatizado y uso de los datos.
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
- El dataset exploratorio queda marcado `forbidden_until_availability_join`; los
  candidatos causales se construyen únicamente tras unir sociedad, período,
  alcance y evento Telegram con `available_at`.

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
  `scripts/install_acciones_chile_universe.py`; el módulo lo prefiere sobre el
  snapshot público parcial y reporta `storage=local_licensed`.
- Los anuncios públicos registran cambios temporales desde marzo de 2024: sin
  cambios en 2024, incorporación de ILC en marzo de 2025 y sin cambios en marzo
  de 2026. Sin un baseline completo autorizado, estos deltas no bastan para
  declarar historia libre de sesgo de supervivencia.
- El cache CMF conserva una observación por emisor–período–scope para todos los
  cierres trimestrales expuestos por la fuente, además de la vista compacta del
  último período por emisor. El join causal usa las observaciones históricas.
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

## Fases

1. **Cartera y CMF:** importación read-only, catálogo ticker↔RUT y métricas.
2. **Biblioteca de tesis:** índice del canal y contraste CMF.
3. **Modelos research-only:** preregistro, splits temporales, benchmark simple,
   costos y evidencia fuera de muestra.
4. **Command Center:** alertas explicables y revisión humana. Sin ejecución.

## Criterios de salida del MVP

- Cero imports desde módulos cripto o ejecutores.
- Parser CMF probado con fixture representativo.
- Cartera rechaza payloads inválidos y permanece read-only.
- Auditor visible con modelo, disponibilidad y autoridad.
- Predicciones rotuladas como investigación y sin camino a órdenes.

El diseño causal del modelo se congela por separado en
`docs/ACCIONES_CHILE_PREDICTOR_PROTOCOL.md`.
