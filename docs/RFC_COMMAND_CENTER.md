# RFC: NEXUX Command Center

- **Estado:** Aceptado; Línea A cerrada, Fase A.5 activa, B2 aprobado, B3
  técnicamente aprobado y B4 autorizado
- **Versión:** 1.2.2
- **Fecha:** 2026-07-30
- **Autoría:** Codex, a partir del Product Vision Document, el repositorio actual
  y la revisión de arquitectura posterior
- **Decisión:** autoriza el Sprint B1 visual sobre el Arzopa medido; factories,
  decisiones irreversibles y despliegue de producción permanecen bloqueados
- **Documento rector de producto:** `docs/PRODUCT_CHARTER.md`
- **Especificación física:** `docs/VIEWPORT_SPECIFICATION.md`

## Estado de implementación

Al 2026-07-30, Línea A completó y validó:

- Wire ABI v1 congelado;
- snapshot reconstruible;
- EventBus;
- Gateway WebSocket;
- interfaces y componentes headless;
- registro estático y harness de conformidad;
- primer adaptador real mediante el TradingView Adapter Spike.

Este estado no activa factories productivas. Los adaptadores adicionales
requieren autorización específica y deben conservar las mismas fronteras
contractuales.

### Línea B — Sprint B1

El monitor ARZOPA está conectado y medido en `1920 × 1080 @ 60 Hz`, escala 1:1.
Línea B queda abierta exclusivamente para foundations visuales, una shell
experimental y validación en ese hardware.

La shell consume el snapshot y Gateway existentes, representa `loading`, `ready`,
`degraded`, `stale`, `expired` y `disconnected`, y puede montar el spike público
de TradingView. No contiene lógica de dominio, comandos ni factories.

Las proyecciones estáticas actuales no avanzan secuencia en el EventBus. Para
evitar que una sesión conectada expire por falta de eventos, el cliente renueva
el snapshot HTTP antes de `stale_at` y reconcilia de forma monotónica: mayor
secuencia prevalece y, a igual secuencia, prevalece el `observed_at` más reciente.
Los huecos de secuencia continúan usando el resync contractual del Gateway.

La validación nocturna a 80–90 cm aprobó legibilidad, jerarquía, densidad y regla
de los dos segundos. El brillo es suficiente, aunque B2 debe estudiar mayor
contraste percibido sin usar grandes superficies claras. La validación deberá
repetirse cuando existan varias fuentes de contexto simultáneas.

### Línea B — Sprint B2

B2 queda autorizado para mejorar contraste percibido y validar composición
multimódulo. No puede inventar datos ni introducir lógica de dominio en la UI.

LuxAlgo no puede prometerse dentro del widget público actual: ese embed no usa la
sesión ni los indicadores privados del usuario. Advanced Charts tampoco soporta
Pine Script; sus indicadores personalizados se implementan en JavaScript:
<https://www.tradingview.com/charting-library-docs/latest/resources/Frequently-Asked-Questions/>.
Por ello B2 debe elegir explícitamente entre conservar el widget como contexto
general o abrir el layout autenticado de TradingView como superficie externa.
Reimplementar LuxAlgo dentro de NexUX no está autorizado.

La implementación candidata conserva el widget como contexto permanente y
ofrece un enlace externo a `https://www.tradingview.com/chart/`, donde la sesión
del navegador mantiene LuxAlgo y los indicadores privados. El primer y único
módulo adicional responde: **¿cuál es el próximo evento macro de alto impacto?**
Lee el calendario existente del Trading Dashboard, selecciona causalmente el
primer evento futuro marcado `High` por la fuente y no altera la severidad del
sistema ni inventa umbrales.

El dashboard publica hasta 24 eventos semanales porque el límite anterior de
ocho podía agotarse con eventos recientes y ocultar eventos futuros. El cambio
es aditivo y no afecta el Wire ABI, EventBus, Gateway ni factories. La lectura usa
`translate=0`: consultar el calendario no activa traducción con Claude ni
consume IA para titulares que la superficie no muestra.

VAL-0018 aprobó perceptualmente contraste, jerarquía, densidad, próximo evento y
regla de los dos segundos sobre el Arzopa a 80–90 cm. B2 queda cerrado.

### Línea B — Sprint B3

B3 queda autorizado bajo la estrategia incremental validada: un solo módulo
nuevo por iteración y una pregunta operacional explícita. No se rediseña el
layout general. Puede estudiarse un aumento ligero de saturación en estados y
mayor énfasis del contexto derecho, siempre sujeto a una nueva validación
perceptual.

El módulo y la pregunta concreta de B3 deben seleccionarse antes de implementar.
Continúan bloqueados los cambios al Wire ABI, EventBus, Gateway, factories y
producción.

La implementación candidata reemplaza el contenido del panel superior derecho,
sin crear una cuarta superficie. Responde **¿está el núcleo listo para
trabajar?** con cuatro estados: `Ready`, `Degraded`, `Failed` y `Unknown`.

Los servicios esenciales son Gateway, EventBus, Snapshot, Internet y Trading.
`Ready` exige evidencia positiva de los cinco. Trading se degrada después de
30 segundos sin actualización y falla después de 120 segundos. Internet usa
como evidencia conjunta la conectividad del navegador y un upstream de Trading
operativo; no se presenta como medidor de calidad de red.

Agente macOS, Apple Music e IA son integraciones opcionales en esta fase. No
bloquean el estado general, pero permanecen visibles como `Unknown` mientras no
exista telemetría productiva. Haber superado un harness o un smoke técnico no
equivale a estar conectado.

La lectura usa `GET /health` y el estado contractual existente. No agrega
endpoints, topics, envelopes, comandos ni factories. VAL-0019 debe validar
perceptualmente que ocho estados compactos no aumenten la carga cognitiva.

### Línea B — Sprint B4

B4 incorpora un único módulo: **Market Ribbon**. Reutiliza la banda superior de
58 px que antes duplicaba el estado operacional; no agrega filas, paneles ni
tracks y no modifica la composición principal del gráfico y el contexto derecho.

La banda responde cinco preguntas de contexto mediante ocho referentes en orden
fijo: SPX, VIX, DXY, CRYPTOCAP:TOTAL, BTCUSDT.P, ETHUSDT.P, SOLUSDT.P y XRPUSDT.P.
Cada referente muestra exclusivamente símbolo, precio, variación diaria y un
indicador de frescura. No publica volumen, señales, indicadores ni gráficos
pequeños.

Las fuentes son explícitas:

- Yahoo Finance para SPX, VIX y DXY;
- CoinGecko Global para capitalización total cripto;
- Binance USD-M Futures para los cuatro perpetuos.

Cada proveedor conserva de forma independiente su último valor bueno. Una caída
no borra el contexto anterior: conserva el timestamp y cambia la frescura. Los
índices distinguen una lectura `live` de un `close` todavía utilizable; una
lectura antigua nunca se presenta como live. La API es autenticada, read-only y
queda fuera del Wire ABI congelado.

El cliente renueva la banda cada 30 segundos con `cache: no-store`; el servicio
mantiene un TTL corto y vuelve a calcular la frescura en cada lectura. Esto es
polling observable, no un WebSocket disfrazado. Los fixtures solo se activan con
`fixture_mode=1`, por lo que una URL histórica con `fixture=ready` no puede
congelar accidentalmente el carrusel real.

La selección distingue dos destinos. BTC, ETH, SOL y XRP actualizan el gráfico
integrado con el perpetuo exacto de Binance disponible en TradingView. SPX, VIX,
DXY y TOTAL conservan precio y variación en la banda, pero nunca intentan montar
un gráfico público incompatible: el clic abre directamente el símbolo exacto en
una pestaña nueva del TradingView autenticado del usuario. No se usan CFDs proxy,
gráficos aproximados ni extracción de una sesión privada.

El enlace `Análisis completo` comparte la misma construcción de URL. La sesión
pertenece al navegador; NexUX no recibe cookies, layouts ni credenciales de
TradingView.

VAL-0020 debe comprobar en el Arzopa que ocho referentes se entiendan sin lectura
secuencial, que la banda no compita con el gráfico y que la frescura sea
reconocible. VAL-0019 permanece abierto y no se cierra por comenzar B4.

### Línea B — Sprint B5

B5 incorpora un único módulo: **Contexto de IA**. Responde únicamente si existe
una observación contractual que merezca atención. La proyección publica estado,
última evaluación, severidad, resumen breve, frescura y fuente.

El módulo no llama modelos, no importa Anthropic, no reutiliza el graduador y no
consulta el brief de Home. Cuando no existe evidencia, el resumen queda vacío y
la UI muestra de forma neutral que no hay observación vigente. `unknown` y
`disabled` nunca se presentan como recomendaciones.

La API es autenticada, read-only y externa al Wire ABI. Una observación futura
debe usar severidades y estados cerrados, incluir timestamp causal, fuente y un
resumen máximo de 180 caracteres. No existen controles ni acciones automáticas.

VAL-0021 debe comprobar en el Arzopa que el estado sin observación no compita con
el contexto macro y que una severidad de fixture pueda reconocerse sin leer el
resumen completo. Su aprobación técnica no cierra la validación perceptual.

### Línea B — Sprint B6

B6 incorpora un único módulo: **Atención del Bot**. Responde si la actividad más
reciente del Bot requiere atención y muestra exclusivamente estado operacional,
modo, última señal sanitizada, antigüedad, severidad y la marca permanente
`solo lectura`.

La proyección consume el endpoint GET existente del Bot y conserva su
autorización de administrador. Descarta cuenta, balance, posiciones, órdenes,
precios, stops, targets y P&L. El Command Center no importa el ejecutor, no
ejecuta comandos y no escribe en el store.

`dry-run` es un modo válido y no se presenta como fallo. `kill` se representa
como pausa; una fuente con más de 120 segundos se degrada. La última señal
incluye únicamente par, dirección, estado, modo y timestamp.

VAL-0022 debe comprobar en el Arzopa que modo y última señal se reconocen sin
confundir el panel con una consola de ejecución. Su aprobación técnica no
autoriza operar ni cierra la validación perceptual.

### Línea B — Sprint B7

B7 reemplaza la telemetría temporal de viewport por un único módulo:
**Reproducción**. Responde qué está sonando, en qué proveedor y si sus controles
están realmente disponibles.

La proyección consume exclusivamente `MediaController`. Título, artista y álbum
son metadatos opcionales externos al contrato; si el proveedor no los entrega,
la UI no los inventa. Apple Music usa AppleScript. Qobuz y TIDAL usan un puente
local explícito de Accesibilidad, ejecutado por el agente macOS.

La superficie local ofrece un selector explícito entre Apple Music, Qobuz y
TIDAL. Apple Music obtiene título, artista, álbum y, cuando existe, carátula
directamente de la aplicación macOS. La imagen se limita a 5 MB, se valida como
PNG o JPEG y se sirve desde una ruta autenticada sin caché persistente. Qobuz y
TIDAL Desktop entregan lectura y controles mediante su árbol accesible local. El
puente no es una API oficial: debe degradar si cambia la estructura, nunca usar
coordenadas y nunca enviar teclas multimedia globales sin identificar proceso.

Los comandos conservan `command_id`, idempotencia, ACK `applied`, `rejected` o
`unknown`, deadline y reconciliación por lectura. Producción permanece inactiva:
sin configuración, `commands_enabled` es falso y los botones quedan
deshabilitados. Para validación local existe un opt-in explícito mediante
`NEXUX_COMMAND_CENTER_MEDIA=local` (con compatibilidad para `apple-music`);
habilita `open_app`, lectura, play, pausa, anterior y siguiente en los tres
proveedores mediante un único endpoint autenticado. Qobuz recibe sus atajos
documentados directamente en su PID; TIDAL recibe `AXPress` sobre botones con
nombre estable. Play/pausa se reconcilian por lectura. No se añadió factory
productiva, LaunchAgent ni control remoto.

VAL-0023 debe comprobar en el Arzopa que pista, proveedor y controles se
reconocen sin competir con Atención del Bot. La aprobación técnica no autoriza
factories ni cierra la validación perceptual.

### Fase A.5 — Integraciones headless

Línea A arquitectónicamente completa permanece cerrada. A.5 incorpora
integraciones sobre esa base sin reabrir su infraestructura.

La Fase A.5 está autorizada para integrar adaptadores reales, agente macOS,
OAuth, tokens y APIs externas detrás de las interfaces congeladas. Incluye
pruebas de conformidad, observabilidad, degradación, recuperación y validación
técnica del proveedor.

En A.5 permanecen bloqueadas factories productivas y despliegues. Las decisiones
visuales experimentales pertenecen exclusivamente a Línea B y no modifican los
contratos headless.

El primer incremento seleccionado es Apple Music, conforme al orden del RFC. Su
adaptador debe funcionar headless, superar `MediaController` y mantener todos
los efectos reales desactivados durante la validación automática.

El discovery de Spotify queda diferido: no existe Client ID ni cuenta de
desarrollo configurada en NexUX, y Development Mode exige Premium, limita
usuarios/cuota y no debe asumirse como base de una integración comercial. Antes
de implementarlo se requiere una decisión explícita de producto y una app
Spotify verificable.

El núcleo headless del agente macOS ya está implementado como paquete Swift
desplegable por separado. Usa exclusivamente WSS saliente, token de dispositivo
en Keychain, allowlist cerrada, ACK idempotente y no expone shell remoto. El
pairing contractual también está implementado: valida código de un solo uso,
nonce, identidad, expiración y respuesta ligada a la solicitud antes de guardar
la credencial en Keychain. Solo existe un Gateway fake; el endpoint real, la
instalación persistente en macOS y cualquier factory productiva continúan
bloqueados.

El adaptador Qobuz conserva la limitación oficial de Qobuz Connect: NexUX no se
presenta como cliente de Connect ni consume endpoints privados. Una validación
posterior demostró, sin embargo, que Qobuz Desktop publica pista, artista, álbum,
progreso y controles en el árbol de Accesibilidad de macOS. El agente local usa
esa superficie como integración experimental y degradable.

El discovery de TIDAL separa dos integraciones que no son equivalentes:

- **TIDAL Desktop:** la aplicación macOS publica pista, artista, álbum, progreso
  y botones nominados de reproducción en Accesibilidad. El agente puede leerlos
  y ejecutar `AXPress` sin APIs privadas ni automatización por coordenadas.
- **TIDAL Developer Platform:** ofrece OAuth 2.1 con Authorization Code + PKCE y
  módulos oficiales de reproducción para construir una sesión propia dentro de
  una aplicación autorizada. No controla la sesión existente de TIDAL Desktop y
  requiere registrar una aplicación, gestionar consentimiento y tokens, aceptar
  las condiciones del proveedor y superar una revisión arquitectónica nueva.

TIDAL Connect continúa fuera de alcance. NexUX no usa `api.tidal.com`, endpoints
no oficiales, inspección del bundle ni automatización por coordenadas. La ruta
local implementa el `MediaController` existente y no activa una factory.

## 1. Resumen ejecutivo

Se propone construir **NEXUX Command Center como un módulo nativo de NexUX**, no
como una aplicación independiente ni como reemplazo de los módulos existentes.
Será una capa de composición orientada a escritorio que:

1. Obtiene proyecciones de solo lectura de Trading, Bot, CoinGlass, Diario,
   infraestructura e IA.
2. Normaliza salud, frescura, severidad y procedencia.
3. Entrega un snapshot inicial por HTTP y cambios incrementales por WebSocket.
4. Usa TradingView como superficie principal del mercado.
5. Integra datos y controles locales mediante un agente macOS opcional,
   autenticado y con capacidades explícitas.

La primera versión debe ser **read-only**. No debe abrir operaciones, cambiar
configuraciones del bot ni ejecutar comandos arbitrarios en el Mac. Las acciones
críticas conservarán sus endpoints, autorizaciones, confirmaciones y auditoría
actuales.

La recomendación es **avanzar**, pero no intentar simultáneamente el centro de
mercado, un sistema universal de plugins, cinco proveedores musicales y control
operativo del bot. Eso produciría una plataforma grande antes de validar la
experiencia de dos segundos que guía el producto.

## 2. Contexto y motivación

NexUX ya contiene buena parte de la información que el Command Center necesita,
pero distribuida en páginas y contratos distintos:

- Trading y SMC en vivo.
- Diario y datos personales por usuario.
- Bot de producción y Binance Demo.
- Acción del precio y Bot2 research.
- CoinGlass y CoinSignals.
- Calendario fundamental y alertas.
- Salud básica del servidor y módulos.
- Google OAuth, roles y shell compartido.

El problema actual no es ausencia de datos. Es que no existe una **vista operativa
normalizada**, con una jerarquía visual única y semántica común para responder:

> ¿Qué está normal, qué requiere atención y qué cambió?

## 3. Objetivos

### 3.1 Objetivos de producto

- Comprender el estado general en menos de dos segundos.
- Mantener el gráfico como centro visual, no como una tarjeta secundaria.
- Mostrar excepciones y cambios, no repetir toda la información disponible.
- Distinguir explícitamente real, virtual, dry-run, shadow y research.
- Distinguir dato actual, atrasado, caído y desconocido.
- Mantener navegación directa a las superficies detalladas existentes.
- Permitir layouts adecuados al viewport secundario validado y al ultrawide.
- Habilitar futuras integraciones sin acoplarlas al bot.

### 3.2 Objetivos técnicos

- Reutilizar FastAPI, autenticación, Postgres, módulo loader y despliegues actuales.
- Introducir contratos versionados para snapshots y eventos.
- Evitar que el frontend dependa de JSON internos o stores de cada módulo.
- Mantener Railway como superficie web y el VPS como motor/ejecutor.
- Soportar reconexión, deduplicación, frescura y degradación parcial.
- Mantener aislamiento multiusuario y por rol.

## 4. No objetivos iniciales

- Reemplazar TradingView.
- Convertir el Command Center en terminal de ejecución.
- Permitir plugins de terceros con código arbitrario.
- Instalar/eliminar módulos Python en caliente.
- Controlar el bot mediante un bus genérico.
- Guardar cada tick de mercado o telemetría local en Postgres.
- Prometer control universal de toda aplicación multimedia desde la primera fase.
- Rediseñar al mismo tiempo las páginas detalladas existentes.

## 5. Arquitectura actual verificada

### 5.1 Núcleo

NexUX usa FastAPI y Uvicorn. `core/app.py` concentra:

- ciclo de vida;
- enrutamiento modular;
- estáticos;
- APIs GET/POST;
- SSE;
- autenticación y roles;
- PWA y web push.

`core/module_loader.py` descubre los módulos declarados en
`config/nexus.json`. Cada módulo implementa `NexusModule`, con ciclo de vida,
API, SSE, estáticos y salud.

### 5.2 Frontend

El frontend actual es HTML, CSS y JavaScript sin framework. Existe un shell
compartido (`static/nexux-shell.*`), pero las superficies grandes mantienen
estado, temporizadores y contratos propios.

Tiempo real actual:

- Trading usa SSE para el estado agregado.
- Trading y Acción del precio abren WebSockets directos a Binance para precio.
- Bot consulta su snapshot cada 5 segundos.
- Diario consulta setups cada 20 segundos.
- Acción del precio actualiza estado cada 60 segundos.
- CoinGlass y CoinSignals cargan snapshots HTTP.

No existe un WebSocket del núcleo ni un bus de eventos común.

### 5.3 Persistencia y usuarios

Railway usa Postgres cuando existe `DATABASE_URL`; local/VPS puede usar stores
JSON. Ya existen:

- usuarios;
- roles e invitaciones;
- datos ingeridos por `user_id` y tipo;
- suscripciones push;
- conexiones de exchange cifradas.

Google OAuth y el rol admin están implementados. Bot es admin-only; Diario,
CoinGlass y CoinSignals requieren sesión.

### 5.4 Despliegue

La topología real es híbrida:

```text
Binance / proveedores
        |
        v
VPS Alemania: motor, colectores, ejecución, Testnet, systemd
        |
        | HTTPS POST autenticado, snapshots/comandos
        v
Railway: FastAPI, Postgres, web pública/autenticada
        |
        v
Navegador / PWA
```

El Mac mini ya no es el motor principal. Para música y sistema se necesitará un
componente local nuevo, pero no debe devolver responsabilidades de trading al Mac.

## 6. Hallazgos y brechas

### 6.1 Fortalezas reutilizables

- Loader modular y configuración por módulo.
- FastAPI/Starlette ya soporta WebSocket sin cambiar backend.
- Separación Railway/VPS y endpoints de ingesta autenticados.
- Postgres multiusuario y stores locales degradables.
- OAuth, roles y gates por superficie.
- Shell visual compartido.
- PWA y push.
- Frontera explícita entre research y ejecución.

### 6.2 Brechas

1. **No hay contrato común de estado.** Cada módulo representa `status`, edad,
   modo, errores y timestamps de manera diferente.
2. **`/health` es insuficiente.** Un módulo puede decir `ok` aunque su dato esté
   atrasado o su fuente externa haya fallado.
3. **Polling fragmentado.** Cada página decide su frecuencia y ciclo de vida.
4. **No hay broker de eventos.** SSE existe solo en Trading.
5. **No hay preferencias de layout por usuario/dispositivo.**
6. **El shell contiene navegación, no composición de widgets.**
7. **No existe agente macOS seguro.**
8. **No hay contabilidad completa de uso IA por componente.**
9. **TradingView no está integrado y tiene límites técnicos/licenciamiento que
   deben probarse antes de comprometer favoritos, layouts e indicadores.**

## 7. Decisiones arquitectónicas propuestas

### D1. Command Center como módulo nativo

Ruta propuesta: `/m/command-center/`.

El módulo no importará ejecutores ni credenciales. Consumirá interfaces de
proyección registradas por otros módulos o snapshots persistidos.

### D2. Read models, no acceso directo a stores internos

Cada dominio expone un adaptador de lectura con un contrato estable:

```text
TradingProjection
BotProjection
MarketProjection
AIProjection
InfrastructureProjection
MediaProjection
```

El adaptador traduce el formato interno actual al esquema del Command Center. Así,
un cambio en `bot_state.json`, CoinGlass o el Diario no rompe la pantalla principal.

### D3. HTTP para snapshot; WebSocket para cambios

Flujo del navegador:

1. `GET /m/command-center/api/snapshot`
2. Abrir `WSS /m/command-center/ws`
3. Suscribirse solo a los topics visibles.
4. Aplicar eventos incrementales.
5. Ante hueco de secuencia o reconexión larga, pedir snapshot nuevo.

WebSocket no reemplazará:

- ingestas VPS -> Railway;
- persistencia;
- descarga de historia;
- comandos críticos;
- APIs de configuración.

Esos flujos necesitan idempotencia, reintento y respuestas auditables. La frase
“todo por WebSocket” se interpreta como **la experiencia viva del Command Center**,
no como sustitución universal del transporte.

### D4. Broker en proceso primero; interfaz escalable

En la topología actual hay un proceso Uvicorn por despliegue. La primera versión
puede usar un broker en memoria con:

- topics;
- secuencia por topic;
- suscriptores;
- coalescing;
- límites por conexión;
- heartbeat.

La interfaz del broker debe permitir sustituirlo por Redis Pub/Sub o NATS cuando
Railway use múltiples réplicas/workers. No se agrega Redis antes de necesitarlo.

### D5. Protocolo versionado

Envelope propuesto:

```json
{
  "v": 1,
  "topic": "bot.production",
  "kind": "snapshot|patch|event",
  "subject": "account:123",
  "seq": 1842,
  "observed_at": 1785430000000,
  "received_at": 1785430000320,
  "expires_at": 1785430030000,
  "severity": "normal|info|warning|critical|unknown",
  "source": "vps:nexus",
  "payload": {}
}
```

Reglas:

- `observed_at` pertenece a la fuente; `received_at`, a NexUX.
- `expires_at` hace visible la obsolescencia.
- Nunca inferir “normal” desde ausencia de datos.
- Los patches solo se aceptan si la secuencia es continua.
- El cliente deduplica por `(topic, seq)`.

### D6. Semántica común de estado

Todo widget debe expresar:

- **health:** healthy, degraded, failed, unknown;
- **freshness:** live, current, stale, expired;
- **mode:** live, testnet, dry, shadow, research, disabled;
- **severity:** normal, info, warning, critical, unknown;
- **source:** proveedor/origen;
- **as_of:** timestamp real del dato.

Esto evita repetir errores conocidos, como comparar información histórica con
precios live o presentar una fuente vacía como ausencia real de riesgo.

### D7. Registro estático de módulos visuales antes de extensiones dinámicas

La terminología oficial será:

- **Módulo NexUX:** capacidad oficial del ecosistema.
- **Vista o widget:** representación visual concreta de un módulo.
- **Extensión externa:** integración de terceros, futura y no habilitada en V1.

Primera versión:

- widgets incluidos en el repositorio;
- manifiesto tipado;
- habilitar/ocultar;
- tamaño permitido;
- posición por layout;
- topics requeridos;
- roles requeridos;
- acciones permitidas.

No se ejecutará código descargado ni se instalarán paquetes desde la UI. “Instalar”
en V1 significa habilitar un módulo visual registrado. Un marketplace o runtime externo
queda fuera hasta definir sandbox, firma, permisos y actualizaciones.

### D8. Sistema de diseño en dos capas

La capa headless puede construirse antes de la validación física. Define semántica,
estados, eventos, roles, navegación por teclado, atributos de accesibilidad,
contratos de interacción, errores, carga y desconexión. No fija apariencia ni
dimensiones.

La capa visual debe esperar la Fase -1B. Define grid, espaciado, tipografía,
colores, iconografía, tamaños, densidad, contraste, jerarquía y composición. La
Component Library estilizada no se considera aprobada hasta validarse en el
monitor real y con contenido extremo.

Los estados normal, warning, critical, stale, offline y unknown sí pueden
formalizarse en la capa headless. Su representación visual queda diferida.

### D9. Frontend aislado, tipado y liviano

El Command Center justifica un frontend estructurado, pero no justifica reescribir
NexUX ni introducir React en todas las páginas.

Propuesta:

- TypeScript;
- Web Components;
- CSS Grid;
- build aislado con Vite;
- estado por topics;
- sin router SPA global;
- sin dependencia pesada de drag-and-drop en V1.

Los artefactos compilados se sirven desde el módulo como hoy. Las páginas existentes
siguen intactas.

### D10. Agente macOS con conexión saliente

No se recomienda que la página HTTPS de `nexux.cl` abra directamente
`ws://localhost` como arquitectura principal:

- crea problemas de mixed content/certificados;
- dificulta autenticación;
- aumenta la superficie local;
- no funciona igual desde otros dispositivos.

Un transporte local directo puede estudiarse como optimización cuando el Command
Center se sirva desde un origen local confiable o exista WSS local con identidad y
certificado válidos. No debe ser condición para que el sistema funcione.

Se propone un agente local, parte del repositorio pero desplegado aparte:

```text
Aplicaciones macOS
      |
      v
NexusAgent (Swift, LaunchAgent, permisos explícitos)
      |
      | WSS saliente autenticado
      v
Railway Command Center Gateway
      |
      v
Navegador autenticado
```

Características:

- token de dispositivo guardado en Keychain;
- emparejamiento mediante código de un solo uso;
- ninguna escucha pública;
- lista cerrada de capacidades;
- sin shell remoto;
- comandos idempotentes con ACK;
- revocación desde Cuenta/Admin;
- publicación mínima de metadatos.

Apple ofrece Scripting Bridge para aplicaciones scriptables, pero no existe una
abstracción pública universal que garantice idéntico control sobre Apple Music,
Qobuz, TIDAL, Spotify y navegadores. Se exige un spike por proveedor.

### D11. Acciones separadas por nivel de riesgo

| Nivel | Ejemplo | Política |
|---|---|---|
| R0 lectura | estado, precio, canción | WebSocket/snapshot |
| R1 reversible | play/pause, volumen | agente local, ACK, rate limit |
| R2 sensible | cambiar layout/config | HTTP, CSRF, auditoría |
| R3 financiero | cerrar/reanudar bot | endpoint actual, admin, confirmación |
| R4 prohibido | abrir trade desde Command Center V1 | no existe |

El Command Center no tendrá acceso directo a `BotExecutor`.

## 8. Arquitectura propuesta

```text
                               +----------------------+
                               | ChartProvider        |
                               | TradingView en V1    |
                               +----------+-----------+
                                          |
+----------------+    HTTPS/WSS   +-------v-------------------------+
| Navegador      |<-------------->| Railway / FastAPI               |
| Command Center |                |                                 |
| Web Components |                | CommandCenterModule             |
+----------------+                | - Snapshot Composer             |
                                  | - Event Gateway                 |
                                  | - Widget Registry               |
                                  | - Authorization                 |
                                  +---+--------------------+--------+
                                      |                    |
                               +------v------+      +------v------+
                               | Postgres    |      | EventBus    |
                               | prefs/state |      | in-process  |
                               +-------------+      +------+------+
                                                            |
                           HTTPS ingest                      |
+--------------------+  snapshots/events  +-----------------v------+
| VPS Alemania       |------------------->| Domain projections     |
| trading, bot, data |                    | adapters por módulo     |
+--------------------+                    +------------------------+

+--------------------+   outbound WSS
| NexusAgent macOS   |-------------------> Railway Gateway
| media/system       |
+--------------------+
```

## 9. Composición visual diferida

El RFC no fija layout, porcentajes, tamaños ni posiciones. Esas decisiones se
tomarán en `DESIGN_SYSTEM.md` después de validar
`VIEWPORT_SPECIFICATION.md`.

La Fase 0 podrá explorar los modos Focus, Operations, Ambient y Edit como
hipótesis. Ninguno queda aprobado antes de probar su legibilidad, densidad y Regla
de los Dos Segundos en el hardware físico.

## 10. TradingView

### 10.1 Recomendación inicial

Usar el **Advanced Real-Time Chart Widget** oficial en un spike de integración.
Permite mantener TradingView como proveedor del gráfico y reduce la duplicación.

El Command Center no conocerá directamente TradingView. Consumirá una interfaz
mínima `ChartProvider` con capacidades explícitas:

```text
ChartProvider
  mount(container, options)
  set_symbol(symbol)
  set_interval(interval)
  set_theme(theme)
  fullscreen()
  capabilities()
  health()
  destroy()
```

TradingView será el adaptador V1. Lightweight Charts u otro motor podrán implementar
la misma interfaz para un subconjunto de capacidades. La abstracción no fingirá
paridad: dibujos, indicadores o layouts solo aparecerán si el proveedor declara
soporte.

### 10.2 Límites que deben validarse

- El widget corre en un iframe externo; NexUX no puede asumir acceso a su DOM.
- La sincronización de símbolo/layout se limita a opciones y APIs públicas.
- Favoritos y presets de NexUX deben guardarse fuera del iframe.
- Debe validarse el comportamiento de indicadores, login de TradingView y layouts.
- Debe construirse una tabla explícita de símbolos NexUX -> TradingView.
- CSP, modo offline y caída del proveedor deben tener estado visible.

La librería self-hosted **Advanced Charts** requiere acceso privado, datafeed propio
y tiene condiciones de uso/no redistribución. La documentación vigente indica que
su uso gratuito exige atribución y entorno público, no privado o tras paywall. NexUX
autenticado no debe asumir que cumple esas condiciones sin confirmación contractual.

Fuentes:

- [TradingView Widgets](https://www.tradingview.com/widget-docs/widgets/charts/)
- [Advanced Charts: introducción y condiciones](https://www.tradingview.com/charting-library-docs/latest/introduction/)
- [Advanced Charts: acceso y no redistribución](https://www.tradingview.com/charting-library-docs/latest/quick-start/)

## 11. Música y sistema local

### 11.1 Estrategia por adaptadores

Contrato conceptual:

```text
MediaProvider
  capabilities()
  current_state()
  play()
  pause()
  next()
  previous()
  set_volume()
  open_app()
```

Cada proveedor declara capacidades reales. La UI oculta controles no soportados.
No se simula compatibilidad.

Orden recomendado:

1. Apple Music: Scripting Bridge/MediaPlayer, según capability spike.
2. Spotify: API oficial y OAuth; reproducción requiere Premium.
3. Navegador: evaluar Media Session/Accessibility con permiso explícito.
4. Qobuz y TIDAL: discovery técnico antes de prometer control.

Spotify introdujo límites relevantes en Development Mode en 2026 (Premium del
propietario y límite de usuarios). Si Command Center se comercializa, sus políticas
también deben revisarse.

Fuentes:

- [Apple Scripting Bridge](https://developer.apple.com/documentation/scriptingbridge)
- [Apple Media Player](https://developer.apple.com/documentation/mediaplayer/)
- [Spotify Playback State](https://developer.spotify.com/documentation/web-api/reference/get-information-about-the-users-current-playback)
- [Spotify Start/Resume Playback](https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback)

### 11.2 Métricas del sistema

V1 local:

- CPU;
- RAM;
- disco;
- red;
- uptime;
- estado del agente.

Temperatura en Apple Silicon no se promete hasta encontrar una API pública y estable
sin privilegios. Eero, NAS y UPS son adaptadores posteriores con credenciales
separadas y permisos read-only.

## 12. IA y costos

El panel no debe inferir gasto desde variables de entorno ni desde “modelo activo”.

Se propone instrumentar cada llamada de NexUX con:

- proveedor;
- componente;
- modelo;
- tokens entrada/salida/cache;
- latencia;
- coste estimado;
- resultado/error;
- timestamp;
- `user_id` cuando aplique.

Los datos del proveedor sirven para reconciliación diaria, no siempre para tiempo
real. Codex Desktop y otras herramientas pueden no exponer consumo por API; en ese
caso la UI debe mostrar `no disponible`, no cero.

## 13. Persistencia propuesta

Tablas nuevas posibles:

- `command_center_layouts`: usuario, dispositivo, preset, versión y widgets.
- `command_center_devices`: agente, clave pública, capacidades, estado, revocación.
- `ai_usage_events`: ledger normalizado de llamadas realizadas por NexUX.
- `command_center_audit`: acciones R1-R3 y resultado.

No persistir:

- cada cambio de progreso de una canción;
- cada tick de precio;
- cada lectura de CPU.

Mantener estado actual en memoria/broker y agregar solo resúmenes históricos cuando
exista un caso de uso.

## 14. Seguridad y privacidad

- Gate de sesión para toda la superficie.
- Filtro de topics por `user_id` y rol antes de suscribir.
- Nunca confiar en el `user_id` enviado por el cliente.
- Tokens de dispositivo hasheados/revocables; secretos en Keychain.
- Origin check obligatorio en WebSocket.
- Límite de conexiones, tamaño, topics y frecuencia.
- Heartbeat y cierre de conexiones zombis.
- CSP compatible con TradingView y sin `unsafe-eval` cuando sea posible.
- Sin secretos en eventos, logs ni payloads del browser.
- Sin comandos de shell, AppleScript arbitrario o rutas de archivo desde la nube.
- Acciones financieras fuera del protocolo genérico.
- Auditoría de cada comando local o sensible.
- Datos locales claramente opt-in.

## 15. Rendimiento y SLO

Los objetivos originales deben convertirse en métricas controlables:

| Métrica | Objetivo inicial |
|---|---|
| Snapshot cacheado | p95 < 300 ms |
| Evento fuente -> pintura | p95 < 500 ms para estado |
| Reconexión WebSocket | < 5 s con backoff y jitter |
| Animación/interacción | 60 FPS, respetando reduced-motion |
| Agente macOS en reposo | < 2% CPU, RSS < 100 MB |
| Backend CC sin carga | < 2% de un vCPU |
| Bundle propio inicial | < 250 KB gzip, excluyendo TradingView |
| Estado stale visible | dentro de 1 intervalo de expiración |

“RAM menor a 300 MB” no es un SLO controlable para la pestaña completa: el proceso
del navegador y el iframe de TradingView no pertenecen a NexUX. Debe medirse por
componente y en el hardware objetivo.

## 16. Observabilidad

Métricas mínimas:

- conexiones WebSocket activas;
- reconexiones y cierres por causa;
- eventos publicados/descartados/coalescidos;
- lag `received_at - observed_at`;
- topics stale/expired;
- tamaño de snapshot;
- latencia de render;
- estado del agente macOS;
- errores por adaptador;
- comandos y ACK pendientes.

La salud debe separar:

- proceso disponible;
- fuente disponible;
- dato fresco;
- funcionalidad operativa.

## 17. Dependencias

### 17.1 Reutilizadas

- FastAPI/Starlette/Uvicorn.
- SQLAlchemy/Postgres/Alembic.
- Google OAuth y roles.
- Módulos, ingestas y shell existentes.
- PWA/web push.

### 17.2 Nuevas propuestas

- Toolchain TypeScript + Vite solo para Command Center.
- Web Components sin framework de aplicación global.
- Swift/Xcode para NexusAgent.
- Redis opcional únicamente al escalar a múltiples procesos.
- TradingView Widget oficial, sujeto a spike y condiciones.

### 17.3 Dependencias externas/riesgosas

- TradingView.
- Spotify OAuth/API/políticas.
- Capacidades de scripting de cada reproductor.
- APIs de Eero/NAS/UPS.
- APIs de uso/facturación de proveedores IA.

## 18. Riesgos

| Riesgo | Prob. | Impacto | Mitigación |
|---|---:|---:|---|
| TradingView no permite la experiencia esperada tras login | M | Alto | Spike y revisión de condiciones antes de UI |
| Controles multimedia inconsistentes | Alta | Medio | Capability matrix; Apple Music primero |
| Command Center se vuelve otra página llena de widgets | Alta | Alto | Presets, límites y pruebas de dos segundos |
| Eventos stale parecen actuales | M | Alto | `observed_at`, `expires_at`, estado unknown |
| Fuga entre usuarios por topic | Baja | Crítico | autorización server-side y tests de aislamiento |
| Bus genérico alcanza al bot | Baja | Crítico | arquitectura read-only; endpoints separados |
| Railway escala a varias réplicas | M | Medio | broker abstracto; Redis al cruzar el umbral |
| Alta frecuencia satura Postgres | M | Alto | no persistir telemetría efímera |
| Agente local amplía superficie de ataque | M | Alto | conexión saliente, pairing, Keychain, allowlist |
| CPU/RAM dominados por TradingView | M | Medio | medir widget real; degradar widgets secundarios |
| Dependencia de APIs comerciales | Alta | Medio | adaptadores, caché y estados degradados |
| Layout libre rompe legibilidad | Alta | Medio | grid con tamaños y presets restringidos |

## 19. Plan por fases

### Fase -1 — Entorno físico

La Fase -1 se gobierna exclusivamente mediante
`docs/VIEWPORT_SPECIFICATION.md`:

- **Fase -1A:** define objetivos y restricciones ergonómicas sin inventar
  propiedades del monitor.
- **Fase -1B:** mide el hardware conectado, valida legibilidad, contraste,
  densidad y reconocimiento.

La validación física y la infraestructura avanzan como líneas paralelas:

- **Línea A — Infraestructura headless:** puede producir comportamiento
  verificable, contratos, eventos, seguridad, adaptadores, reconexión, degradación
  y pruebas.
- **Línea B — Experiencia visual:** Sprint B1 autorizado sobre el hardware ya
  inventariado; su aprobación permanece condicionada a completar las mediciones
  perceptuales de la Fase -1B.

La Línea A no aprueba apariencia, layout, dimensiones, tipografía, densidad,
jerarquía, paleta ni composición. Línea B puede proponerlos de forma experimental
y solo la evidencia física puede aprobarlos. Fixtures y estados simulados prueban
comportamiento; no sustituyen la UX sobre el monitor real.

### Fase 0 — Spikes y contratos

Entregables headless autorizados:

- prueba del TradingView Widget detrás de auth;
- tabla de capacidades y símbolos;
- contrato y fallback de `ChartProvider`;
- contrato de `MediaController` y pruebas Apple Music/Spotify;
- spike del agente macOS con WSS saliente, autenticación y allowlist;
- esquema de eventos versionado;
- esquema de widget manifest;
- estados y primitivas headless sin estilo definitivo.

Entregables visuales habilitados solo como experimento B1:

- tokens visuales, grid, tipografía, espaciado y densidad;
- baseline de CPU/RAM en el viewport secundario validado;
- wireframes y mockups.

Su aprobación definitiva continúa bloqueada por el Experience Gate.

Infrastructure Gate:

- contratos versionados y eventos tipados;
- snapshot consistente;
- reconexión y degradación predecibles;
- aislamiento multiusuario y autorización probados;
- compatibilidad de versiones;
- ausencia de dependencias visuales no validadas;
- TradingView cumple las condiciones técnicas y contractuales del spike.

Experience Gate:

- `VIEWPORT_SPECIFICATION.md` validado con el monitor secundario real;
- legibilidad, contraste, densidad y Regla de los Dos Segundos aprobados;
- capa visual y Component Library aprobadas en el hardware físico.

### Fase 1 — Fundaciones read-only

Entregables headless autorizados:

- módulo nativo;
- snapshot composer;
- registro estático de módulos;
- EventBus en proceso;
- gateway WebSocket autenticado;
- suscripción por topics;
- secuencias, heartbeat, backoff y resync.

Entregables visuales habilitados solo como experimento B1:

- shell visual del Command Center;
- representación visual del estado general;
- layout fijo para el viewport secundario validado y el ultrawide.

El layout del ultrawide y cualquier promoción productiva siguen fuera de B1.

Infrastructure Gate:

- reconexión, pérdida de eventos y aislamiento multiusuario probados;
- estados normal, stale, offline y unknown distinguibles en los contratos;
- cero importaciones del ejecutor;
- p95 fuente -> gateway dentro del SLO de infraestructura.

Experience Gate:

- p95 gateway -> pintura dentro del SLO visual;
- shell y estados comprensibles en el hardware objetivo;
- ninguna dimensión o composición aprobada antes de la Fase -1B.

### Fase 2 — Mercado, gráfico y Bot

Entregables:

- adaptadores de Mercado, Trading y Bot;
- `ChartProvider` con TradingView;
- Bot read-only;
- calendario y alertas fundamentales;
- contexto CoinGlass estrictamente diferenciado de señal;
- deep links a las páginas existentes;
- migración del polling solo dentro del Command Center.

Gate:

- prueba de comprensión de dos segundos con alerta, bot y mercado;
- TradingView cumple condiciones y experiencia mínima;
- caída de TradingView no derriba el Command Center;
- datos stale y modos real/testnet/dry/research visibles.

### Fase 3 — Personalización

Entregables:

- layouts por usuario/dispositivo;
- presets Focus, Operations y Ambient;
- ocultar/mover/redimensionar con límites;
- reset y versionado de layout.

Gate:

- ningún layout puede ocultar alertas críticas ni confundir modos.

### Fase 4 — NexusAgent macOS

Entregables:

- pairing y revocación;
- estado CPU/RAM/disco/red;
- Apple Music;
- Spotify si cumple políticas/capacidades;
- comandos R1 con ACK y auditoría.

Gate:

- no hay listener público, shell remoto ni credenciales fuera de Keychain.

### Fase 5 — IA e infraestructura

Entregables:

- ledger de uso IA;
- coste/latencia/error por componente;
- NAS/UPS/Eero mediante adaptadores validados;
- agregados históricos útiles.

### Fase 6 — Extensibilidad controlada

Entregables:

- manifiestos versionados;
- permisos por widget;
- catálogo interno;
- actualización independiente de módulos compatibles.

Un sistema de plugins de terceros solo se evalúa después de definir firma, sandbox,
permisos, supply chain y rollback.

### Fase 7 — Acciones sensibles, solo si existe necesidad

No está preaprobada. Cualquier control del bot exige un RFC independiente, threat
model, testnet, idempotencia, confirmación y auditoría.

## 20. Estrategia de pruebas

- Contract tests por projection/topic.
- Tenant-isolation tests para snapshot y WebSocket.
- Reconexión, orden, duplicados y huecos de secuencia.
- Fuente stale, caída total y reloj desfasado.
- Visual regression en el viewport secundario validado y 3440x1440; 1920x1080 se
  agrega solo si la medición física confirma ese modo.
- Texto, contraste, teclado y reduced-motion.
- Canvas/iframe visible y no vacío.
- Long-run de 8 horas para memoria, CPU y reconexiones.
- Fallo de TradingView, VPS, Postgres y agente local por separado.
- Prueba que prohíba imports o llamadas al ejecutor desde Command Center.
- CSP y límites de mensajes WebSocket.

## 21. Migración y compatibilidad

- Las páginas actuales permanecen como vistas de detalle.
- El Command Center se agrega al shell sin reemplazar Home inicialmente.
- Los adaptadores envuelven contratos actuales; no se migran todos los módulos de
  una vez.
- El polling de las páginas existentes no se toca hasta comprobar el backbone.
- El módulo se puede deshabilitar por config y volver al estado anterior.
- No cambia config operativa, bot, Testnet, credenciales ni colectores en Fases 0-2.

## 22. Preguntas abiertas

1. ¿Command Center será inicialmente solo para Hugo/admin o producto beta?
2. ¿La pantalla principal se abrirá siempre en `nexux.cl` o también en una instancia
   local? La respuesta define la ruta óptima del agente.
3. ¿Se acepta que los controles de música transiten cifrados por Railway?
4. ¿Qué nivel/licencia de TradingView está disponible para NexUX?
5. ¿Los layouts deben sincronizarse entre dispositivos o ser específicos de pantalla?
6. ¿Cuáles son los tres estados que realmente deben ocupar la primera mirada?
7. ¿Se permite controlar volumen del sistema o solo del reproductor?
8. ¿Qué datos de canción/sistema pueden persistirse y por cuánto tiempo?

## 23. Recomendación final

Aprobar el proyecto con estas condiciones:

1. **Fase 1 read-only.**
2. **TradingView y media pasan por spikes antes de prometer capacidades.**
3. **WebSocket sirve la experiencia incremental, no reemplaza persistencia ni
   comandos críticos.**
4. **Command Center consume projections, nunca stores internos ni ejecutores.**
5. **Extensiones dinámicas y acciones financieras quedan fuera.**
6. **La frescura y la incertidumbre son parte visible del diseño.**

Con este alcance, el Command Center puede convertirse en la superficie principal
de NexUX sin poner en riesgo lo que ya funciona ni convertir una visión de
simplicidad en una plataforma prematuramente compleja.
