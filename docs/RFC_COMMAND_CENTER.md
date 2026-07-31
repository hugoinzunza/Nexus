# RFC: NEXUX Command Center

- **Estado:** Aceptado; Línea A cerrada, Fase A.5 activa y Línea B condicionada
  a la Fase -1B
- **Versión:** 1.2.2
- **Fecha:** 2026-07-30
- **Autoría:** Codex, a partir del Product Vision Document, el repositorio actual
  y la revisión de arquitectura posterior
- **Decisión:** autoriza infraestructura headless verificable; no autoriza
  decisiones visuales, mockups ni despliegue de producción antes de completar la
  Fase -1B
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

Este estado no activa factories productivas ni autoriza decisiones de Línea B.
Los adaptadores adicionales requieren autorización específica y deben conservar
las mismas fronteras contractuales.

### Fase A.5 — Integraciones headless

Línea A arquitectónicamente completa permanece cerrada. A.5 incorpora
integraciones sobre esa base sin reabrir su infraestructura.

La Fase A.5 está autorizada para integrar adaptadores reales, agente macOS,
OAuth, tokens y APIs externas detrás de las interfaces congeladas. Incluye
pruebas de conformidad, observabilidad, degradación, recuperación y validación
técnica del proveedor.

Permanecen bloqueados layout, mockups, tipografía, paleta, dimensiones, densidad,
composición de widgets, aprobación visual, factories productivas y despliegues.

El primer incremento seleccionado es Apple Music, conforme al orden del RFC. Su
adaptador debe funcionar headless, superar `MediaController` y mantener todos
los efectos reales desactivados durante la validación automática.

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
- **Línea B — Experiencia visual:** permanece bloqueada hasta completar la Fase
  -1B.

La Línea A no puede aprobar apariencia, layout, dimensiones, tipografía, densidad,
jerarquía, paleta ni composición. Fixtures, adaptadores falsos y estados simulados
sirven para probar comportamiento, no UX.

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

Entregables visuales bloqueados:

- tokens visuales, grid, tipografía, espaciado y densidad;
- baseline de CPU/RAM en el viewport secundario validado;
- wireframes y mockups.

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

Entregables visuales bloqueados:

- shell visual del Command Center;
- representación visual del estado general;
- layout fijo para el viewport secundario validado y el ultrawide.

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
