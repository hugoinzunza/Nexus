# NEXUX Command Center — Validation Log

- **Estado:** Activo
- **Inicio:** 2026-07-30
- **Propósito:** conservar evidencia objetiva de las validaciones del producto

## Reglas del registro

- Este documento registra resultados; no define requisitos ni arquitectura.
- Cada validación identifica fecha, entorno, método, evidencia y conclusión.
- Una medición fallida o inconclusa se conserva y se etiqueta como tal.
- Las capturas y datos crudos se referencian mediante rutas o commits; no se
  sustituyen por una interpretación.
- Una conclusión indica explícitamente si aprueba, rechaza o deja pendiente un
  gate.
- Las correcciones se validan en una entrada nueva. No se reescribe el resultado
  histórico.

## Estados

- **APROBADO:** satisface el criterio predefinido.
- **RECHAZADO:** no satisface el criterio predefinido.
- **PENDIENTE:** faltan hardware, datos o mediciones.
- **INCONCLUSO:** la prueba se ejecutó, pero no permite una conclusión.

---

## VAL-0001 — Inventario inicial de pantallas

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Equipo | Mac mini con Apple M4 |
| Entorno | macOS, escritorio de desarrollo |
| Método | `system_profiler SPDisplaysDataType` |

### Resultado

| Pantalla | Detección |
|---|---|
| Principal | TCL 34R83Q |
| Resolución | 3440 × 1440 |
| Escala informada | UI 3440 × 1440 |
| Frecuencia | 170 Hz |
| Monitor secundario | No detectado |

### Observaciones

- La pantalla principal estaba conectada, activa y configurada como principal.
- No fue posible verificar modelo, resolución, escala, frecuencia ni viewport del
  monitor secundario.
- Los valores objetivo de 14 pulgadas, 1920 × 1080 y 30° continúan siendo
  hipótesis hasta la medición física.

### Evidencia

- Salida local de `system_profiler` observada durante la Fase -1A.
- Especificación resultante:
  `docs/VIEWPORT_SPECIFICATION.md`.

### Conclusión

**PENDIENTE.** La evidencia confirma el entorno principal, pero no permite cerrar
la Fase -1B ni autorizar mockups.

---

## VAL-0009 — TradingView Adapter Spike

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Entorno | Fixture autenticado local |
| Proveedor | TradingView Advanced Real-Time Chart Widget |
| Metodo | Montaje real + harness contractual + suite completa |

### Resultado

- `BINANCE:BTCUSDT.P` en 1h alcanzo estado `ready`.
- Latencia observada de montaje: 898 ms.
- Un timeout transitorio produjo `degraded` con codigo estable.
- El adaptador declaro cero capacidades mutables.
- El Wire ABI v1 y su fingerprint permanecieron intactos.
- El catalogo productivo permanecio sin factory.
- La suite cerro con 699 pruebas aprobadas.

### Evidencia

- Commit: `b0e8d6d`.
- Cierre tecnico: `docs/TRADINGVIEW_ADAPTER_SPIKE.md`.
- Implementacion: `modules/command_center/tradingview_adapter.py`.
- Fixture: `modules/command_center/public/tradingview-spike.html`.

### Conclusion

**APROBADO.** La infraestructura de Linea A integro un proveedor externo real
sin cambios estructurales. El resultado no autoriza factory productiva ni
decisiones de Linea B.

---

## VAL-0010 — Cierre arquitectónico de Línea A

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Alcance | Infraestructura base del Command Center |
| Método | Revisión arquitectónica posterior al cierre del primer adaptador real |

### Resultado

- Protocolo congelado y fingerprint preservado.
- Snapshot, EventBus, Gateway y runtime validados.
- Registro estático y harness validados.
- TradingView Adapter Spike cerrado formalmente.
- Suite completa con 700 pruebas aprobadas.
- Cero factories productivas activas.
- Sin cambios en `main`, Railway ni producción.

### Evidencia

- Freeze contractual: `docs/COMPATIBILITY.md`.
- Cierre del adaptador: `docs/TRADINGVIEW_ADAPTER_SPIKE.md`.
- Commit de cierre: `4e5eb3a`.
- Estado arquitectónico: `docs/RFC_COMMAND_CENTER.md`.

### Conclusión

**APROBADO.** Línea A queda arquitectónicamente completa. La plataforma puede
evolucionar mediante adaptadores adicionales sin rediseñar su infraestructura
fundamental. Línea B y las factories productivas no autorizadas permanecen
bloqueadas.

---

## VAL-0011 — Adaptador headless de Apple Music

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Fase | A.5 — Integraciones headless |
| Equipo | Mac mini con Apple M4 |
| Proveedor | Music.app mediante su diccionario AppleScript instalado |
| Método | Harness contractual, dobles deterministas y smoke real acotado |

### Resultado

- El adaptador declaró `current_state`, `play`, `pause`, `next`, `previous`,
  `set_volume` y `open_app`.
- El harness read-only no produjo efectos.
- El harness con comandos validó ACK e idempotencia para todas las capacidades.
- Los reintentos concurrentes con el mismo `command_id` produjeron un solo efecto.
- Music cerrada produjo `unavailable` y el registro conservó el runtime como
  `degraded`; al estar disponible recuperó `ready`.
- Un permiso de automatización pendiente produjo `degraded`, nunca un falso
  `ready`.
- Con el permiso `ChatGPT → Música` autorizado, el smoke real alcanzó `ready` y
  leyó estado `stopped`, volumen `0,59` y ausencia de pista activa.
- `player position = missing value` se modeló como `None`, sin inventar cero.
- `set_volume` al mismo valor y `pause` estando detenido devolvieron ACK
  `applied` sin cambiar estado ni volumen.
- Music estaba cerrada antes de cada smoke y fue cerrada al terminar.
- La suite completa cerró con 727 pruebas aprobadas.

### Límites

- El smoke real no ejecutó `play`, `next` ni `previous` para no alterar la sesión
  del usuario; esas rutas se verificaron contra el diccionario oficial instalado
  y mediante el harness.
- No existe factory productiva, LaunchAgent ni despliegue.
- El adaptador usa `osascript` como puerto técnico local. Una futura
  implementación del agente macOS podrá sustituir el puerto sin cambiar
  `MediaController`.

### Evidencia

- Implementación: `modules/command_center/apple_music_adapter.py`.
- Pruebas: `tests/test_command_center_apple_music_adapter.py`.
- Diccionario local:
  `/System/Applications/Music.app/Contents/Resources/com.apple.Music.sdef`.

### Conclusión

**APROBADO.** Apple Music funciona como primer adaptador real de Fase A.5,
supera el contrato headless y queda listo para revisión arquitectónica. La
factory productiva, el despliegue y Línea B permanecen bloqueados.

---

## VAL-0012 — Discovery de Spotify Web API

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Fase | A.5 — Integraciones headless |
| Método | Documentación oficial vigente + inventario local sin leer secretos |

### Resultado

- NexUX no posee variables, configuración ni aplicación local de Spotify.
- Development Mode requiere que el propietario tenga Spotify Premium.
- Cada app admite hasta cinco usuarios autorizados.
- La cuota de Development Mode se comparte por cuenta de desarrollador.
- Los refresh tokens caducan a los seis meses y `invalid_grant` exige
  reautorización, no retry.
- Los endpoints de reproducción continúan disponibles con scopes
  `user-read-playback-state` y `user-modify-playback-state`.
- Spotify advierte que Development Mode es para experimentación/proyectos
  personales y no debe asumirse como base comercial de streaming.

### Conclusión

**PENDIENTE.** Spotify es técnicamente compatible con `MediaController`, pero no
se implementará hasta disponer de una app, cuenta Premium y decisión de producto
compatibles. Fase A.5 continúa con el agente macOS.

---

## VAL-0013 — Núcleo headless del agente macOS

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Fase | A.5 — Integraciones headless |
| Plataforma | Swift 6.3.3 · macOS |
| Protocolo interno | `nexux.agent.v1` |

### Evidencia

- Paquete Swift independiente en `agents/macos/NexusAgent/`.
- Transporte exclusivamente WSS saliente con token Bearer de dispositivo.
- Token persistido mediante Keychain y restringido a este dispositivo.
- Allowlist por capacidad y acción antes de cualquier efecto.
- ACK `applied`, `rejected` o `unknown` con caché idempotente por
  `command_id`; reutilizar un ID con otro payload falla cerrado.
- Backoff de reconexión acotado y recuperación comprobada con transporte fake.
- Harness nativo: 33 comprobaciones aprobadas, incluida concurrencia sobre un
  mismo `command_id`, límites temporales y rechazo de mensajes sobredimensionados.
- Self-check: protocolo `nexux.agent.v1`, transporte `outbound-wss-only` y
  `factory=disabled`.
- Guard Python verifica ausencia de shell remoto, endpoint inseguro y factory.
- El Wire ABI v1 del navegador no se modificó ni se reutilizó como protocolo
  de control del dispositivo.

### Límites

- No existe todavía endpoint de pairing ni Gateway de agente en Railway.
- No existe `LaunchAgent`, instalación persistente ni firma/notarización.
- No hay handlers reales conectados al proceso Swift.
- No existe factory productiva ni despliegue.

### Conclusión

**APROBADO** como núcleo técnico headless. El próximo sprint puede implementar
pairing y autenticación del dispositivo contra un fake/fixture contractual. La
activación persistente y productiva continúa bloqueada.

---

## VAL-0014 — Pairing contractual del agente macOS

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Fase | A.5 — Integraciones headless |
| Gateway | Fake contractual; ninguna red real |
| Protocolo interno | `nexux.agent-pairing.v1` |

### Contrato

1. El agente envía `request_id`, `device_id`, código de pairing, nonce,
   capacidades ordenadas y deadline.
2. La respuesta debe conservar `request_id`, `device_id` y nonce.
3. Solo `pairing.accepted` puede producir una credencial.
4. El token debe ser opaco, válido y tener expiración futura.
5. La credencial completa se guarda en Keychain; no se escribe en archivos.
6. El transporte WSS exige esa credencial y envía identidad de dispositivo
   explícita junto al Bearer.

### Evidencia

- Aceptación y persistencia contractual verificadas con store en memoria.
- El Gateway fake consume cada código una sola vez.
- Reutilizar un código es rechazado.
- Una respuesta asociada a otro dispositivo no persiste credenciales.
- Un token vencido no se acepta.
- Dos pairings concurrentes fallan cerrados.
- El timeout cancela el intercambio.
- La revocación local elimina la credencial.
- La observabilidad solo publica contadores; no contiene código ni token.
- Harness Swift completo: 48 comprobaciones aprobadas, incluidas descripciones
  redactadas para solicitud, respuesta y credencial.
- Guards Python: 9 aprobados para límites del agente y pairing.

### Límites y riesgos pendientes

- No existe endpoint real ni integración con Railway.
- El consumo atómico del código deberá implementarse y probarse en el servidor.
- La autenticación usa Bearer ligado a `device_id`; aún no incorpora
  proof-of-possession criptográfico.
- No existe rotación silenciosa, revocación remota ni recuperación de cuenta.
- No existe `LaunchAgent`, firma, notarización, handler real o factory.

### Conclusión

**APROBADO** como pairing contractual contra fake. Antes de conectar una red real
se requerirá revisión específica del contrato servidor, almacenamiento de
tokens, consumo atómico del código y política de revocación.

---

## VAL-0015 — Qobuz Adapter capability-limited

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Fase | A.5 — Integraciones headless |
| Aplicación local | Qobuz `8.2.0-b033` · `com.qobuz.desktop` |
| Método | Documentación oficial + bundle/Apple Events/Accessibility read-only |

### Discovery

- Qobuz Connect permite controlar dispositivos y otras apps Qobuz, pero Qobuz
  declara que las aplicaciones de terceros no están soportadas:
  <https://help.qobuz.com/en/articles/313603-can-qobuz-connect-be-used-via-a-third-party-app>.
- La aplicación instalada responde a identidad y versión estándar de macOS.
- El bundle no contiene diccionario `sdef` y `player state` no pertenece a su
  interfaz AppleScript.
- Accessibility solo expone la ventana Electron y controles de ventana; no
  publica el reproductor.
- No se adoptaron API reversa, endpoints no oficiales, Qobuz Connect privado,
  teclas multimedia globales ni automatización por coordenadas.

### Capacidades

| Capacidad `MediaController` | Estado | Motivo |
|---|---|---|
| `open_app` | Disponible | `/usr/bin/open` con argumentos fijos |
| `current_state` | No declarada | No existe fuente pública causal |
| `play` / `pause` | No declaradas | Sin interfaz Qobuz de terceros |
| `next` / `previous` | No declaradas | Sin interfaz Qobuz de terceros |
| `set_volume` | No declarada | Depende del dispositivo de salida |

### Evidencia

- 9 pruebas específicas aprobadas.
- Harness read-only ejecuta únicamente `health`.
- Harness con comandos ejecuta únicamente `open_app` y conserva idempotencia.
- Timeout ambiguo queda en `unknown` y no repite la apertura.
- Registro conserva degradación y recuperación.
- Smoke real read-only: `ready`, versión `8.2.0-b033`, capacidad
  `open_app`, comandos ejecutados `0`.
- El puerto usa `create_subprocess_exec`; no shell, `System Events`, API web ni
  entrada libre.

### Conclusión

**APROBADO** como adaptador real de capacidad limitada. La ausencia de controles
de reproducción es una conclusión del discovery, no trabajo incompleto. Añadirlos
requerirá una interfaz oficial nueva de Qobuz y otra revisión arquitectónica.
Factory productiva y despliegue continúan bloqueados.

---

## VAL-0016 — TIDAL Discovery

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Fase | A.5 — Integraciones headless |
| Aplicación local | TIDAL `2.43.0` · `com.tidal.desktop` |
| Método | Documentación oficial + bundle y Apple Events read-only |

### Discovery

- TIDAL Desktop es una aplicación Electron sin diccionario `sdef`. Responde a
  identidad y versión estándar de macOS, pero `player state` no pertenece a su
  interfaz AppleScript.
- El smoke se realizó con TIDAL cerrado. No se abrió la aplicación, no se leyó
  contenido de sesión y no se ejecutaron comandos de reproducción.
- La Developer Platform oficial permite registrar aplicaciones, autenticar al
  usuario mediante OAuth 2.1/PKCE y reproducir contenido mediante módulos
  oficiales dentro de una aplicación propia:
  <https://developer.tidal.com/documentation/overview>.
- Esa plataforma no controla la sesión de TIDAL Desktop. TIDAL Connect está
  reservado a socios de dispositivos:
  <https://developer.tidal.com/documentation/connect>.
- TIDAL identifica `openapi.tidal.com` como su plataforma autorizada y rechaza
  el uso de APIs no oficiales:
  <https://github.com/orgs/tidal-music/discussions/38>.
- Las Developer Guidelines exigen módulos oficiales y contienen restricciones
  relacionadas con el uso de TIDAL Content junto a tecnologías de inteligencia
  artificial. Su aplicabilidad a NexUX debe resolverse antes de implementar:
  <https://developer.tidal.com/documentation/guidelines/guidelines-developer-guidelines>.

### Rutas evaluadas

| Ruta | Capacidad honesta | Estado |
|---|---|---|
| TIDAL Desktop | salud, proceso, versión y `open_app` | Viable pero redundante con Qobuz |
| TIDAL Developer Platform | reproductor propio con OAuth/PKCE y Player SDK | Pendiente de app, consentimiento y revisión de condiciones |
| TIDAL Connect | control de dispositivos | No disponible sin acuerdo de device partner |
| API o automatización no oficial | no admisible | Descartada |

### Evidencia

- Aplicación instalada en `/Applications/TIDAL.app`, versión `2.43.0`.
- Sin proceso TIDAL activo antes o después del discovery.
- Sin variables, Client ID, Client Secret ni tokens TIDAL configurados en NexUX.
- Sin lectura de credenciales o contenido de `Application Support`.
- Sin archivos de implementación, factories, cambios de ABI ni efectos laterales.

### Conclusión

**APROBADO** como discovery y **PENDIENTE** como integración. No se implementa un
adaptador en este sprint. La ruta nativa solo justificaría capacidades limitadas;
la ruta con SDK oficial es un reproductor NexUX independiente y requiere una
autorización nueva después de registrar la aplicación y resolver las condiciones
de uso. Factory productiva, despliegue y Línea B continúan bloqueados.

---

## VAL-0017 — Línea B Sprint B1 · Shell sobre ARZOPA

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Hardware | ARZOPA, 1920 × 1080 @ 60 Hz, 310 × 170 mm |
| Escala | macOS 1:1; DPR 1.00 |
| Viewport real | Chrome 1920 × 992 |
| Posición física | Bajo el monitor principal |
| Posición lógica | Izquierda, bounds `(-1920, 0, 1920, 1080)` |
| Datos | Snapshot/Gateway reales y fixtures contractuales rotulados |

### Evidencia técnica

- Snapshot HTTP y Gateway WebSocket autenticado reconstruyen la sesión local.
- Ocho módulos configurados aparecen sin activar factories.
- Estados `loading`, `ready`, `degraded`, `stale`, `expired` y `disconnected`
  poseen representación explícita.
- Fixture degraded: banda warning, sin overflow a 1920 × 1080.
- Fixture expired: banda critical y prohibición textual de usar el contexto.
- TradingView montó un iframe real; latencia observada entre 609 y 2621 ms.
- Validación compacta 1280 × 800 sin overflow horizontal.
- Contraste automatizado ≥4.5:1 para textos y estados sobre la superficie base.

### Hallazgo y corrección

El primer smoke físico mostró `expired` con Gateway conectado. El EventBus
conservaba un checkpoint válido pero antiguo para topics estáticos sin publisher.
El resync por sí solo no podía actualizar su `observed_at`.

La shell ahora renueva por HTTP antes de `stale_at` y reconcilia snapshots
monotónicamente. Después de 32 segundos, `snapshot_at` avanzó y el estado
permaneció `ready`. Los gaps de secuencia siguen usando resync del Gateway.

### Evidencia visual

- `docs/evidence/command-center-b1-arzopa-physical.png`
- `docs/evidence/command-center-b1-ready-1920x1080.png`
- `docs/evidence/command-center-b1-expired-1920x1080.png`

### Restricciones preservadas

- Wire ABI y fingerprint intactos.
- Cero factories productivas.
- Sin POST, comandos multimedia, bot ni lógica de dominio.
- Sin merge a `main`, Railway o producción.

### Conclusión

**INCONCLUSO** como gate perceptual y **APROBADO** como candidato técnico B1.
La ejecución en el hardware real está demostrada. Distancia, ángulo, inclinación,
brillo día/noche, tamaños legibles y regla de los dos segundos requieren
observación física del usuario antes de iniciar B2.

### Cierre perceptual — evidencia posterior

| Campo | Resultado |
|---|---|
| Evaluador | Hugo |
| Distancia | 80–90 cm |
| Iluminación | Noche, únicamente barra Quntis |
| Legibilidad | Cómoda |
| Brillo | Suficiente para operar; mejorable por contraste y calibración |
| Jerarquía | Clara |
| Densidad | Adecuada |
| Regla de dos segundos | Cumplida |

No fue necesaria búsqueda visual consciente para identificar el estado principal.
La menor luminancia del Arzopa frente al TCL MiniLED no bloquea el uso. B2 deberá
probar superficies ligeramente más claras y color de estado más intenso sin
introducir grandes áreas blancas.

La prueba se realizó con TradingView como única fuente de contenido de mercado.
La jerarquía y regla de dos segundos deberán repetirse con composición
multimódulo. El resultado anterior `INCONCLUSO` se conserva como evidencia
histórica; esta observación posterior lo resuelve.

**Resolución final:** `VAL-0017 APROBADO`, Sprint B1 perceptualmente aprobado y
Sprint B2 autorizado.

---

## VAL-0018 — Línea B Sprint B2 · Contexto macro y contraste

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Hardware | ARZOPA, 1920 × 1080 @ 60 Hz |
| Viewport observado | Chrome 1920 × 936 durante control remoto |
| Datos | Snapshot, Gateway, TradingView y calendario reales |
| Módulos visibles nuevos | 1: próximo evento macro de alto impacto |

### Evidencia técnica

- TradingView público conserva la función de contexto continuo.
- El enlace `Análisis completo` abre `https://www.tradingview.com/chart/` en una
  pestaña separada con `noopener noreferrer`; no simula LuxAlgo dentro del embed.
- El contexto macro seleccionó `BOJ Press Conference`, JPY, aproximadamente
  2 h 34 min por delante durante la captura.
- La selección ignora eventos pasados y cualquier impacto distinto de `High`.
- El calendario corrigió un recorte que ocultaba eventos futuros detrás de ocho
  eventos recientes.
- La consulta usa `translate=0`; el refresco periódico no activa Claude para
  traducir noticias que el módulo no presenta.
- La composición ocupa 1920 px exactos, sin overflow horizontal ni vertical.
- TradingView alcanzó `Proveedor disponible`.
- La paleta B2 conserva contraste automatizado ≥4.5:1 para texto y estados.

### Evidencia visual

- `docs/evidence/command-center-b2-arzopa-physical.png`

### Restricciones preservadas

- Un solo módulo de contexto adicional.
- Sin POST, decisiones de trading, umbrales inventados ni cambios de severidad.
- Wire ABI, EventBus, Gateway y fingerprint intactos.
- Cero factories productivas.
- Sin merge a `main`, Railway o producción.

### Conclusión

**APROBADO técnicamente** y **PENDIENTE perceptualmente**. La captura confirma
composición y legibilidad mecánica, pero Hugo debe repetir la regla de los dos
segundos y comparar el brillo percibido desde 80–90 cm antes de cerrar B2.

### Cierre perceptual — evidencia posterior

| Campo | Resultado |
|---|---|
| Evaluador | Hugo |
| Distancia | 80–90 cm |
| Iluminación | Noche, barra Quntis, sin iluminación adicional |
| Contraste | Aprobado; mejora claramente frente a B1 |
| Jerarquía | Aprobada |
| Próximo evento | Visible sin competir con el gráfico |
| Densidad | Adecuada |
| Regla de dos segundos | Cumplida |

La optimización mejora la separación entre paneles y la legibilidad sin aumentar
artificialmente el brillo. El gráfico, el estado operacional y el próximo evento
se reconocen sin búsqueda visual consciente. La incorporación de un único
módulo adicional no produjo sobrecarga.

Se aprueba mantener el widget integrado como contexto permanente y usar
`Análisis completo` para abrir el TradingView autenticado con el layout personal
y LuxAlgo. El gráfico propio de NexUX podrá sustituir el widget cuando alcance
madurez, sin modificar ChartProvider, Wire ABI, Gateway, EventBus ni runtime.

Para B3 se recomienda aumentar ligeramente la saturación de estados y reforzar
el contexto derecho, sin rediseñar el layout. Se mantiene la regla de incorporar
un solo módulo por iteración y repetir la validación perceptual.

La conclusión anterior `PENDIENTE perceptualmente` se conserva como evidencia
histórica y queda resuelta por esta observación.

**Resolución final:** `VAL-0018 APROBADO`, Sprint B2 perceptualmente aprobado y
Sprint B3 autorizado.

---

## VAL-0019 — Línea B Sprint B3 · Preparación operacional

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Hardware | ARZOPA, 1920 × 1080 @ 60 Hz |
| Viewport observado | Chrome 1920 × 936 durante control remoto |
| Pregunta | ¿Está el núcleo listo para trabajar? |
| Superficies nuevas | 1 módulo; reemplaza el contenido del panel existente |

### Semántica

El estado general depende exclusivamente de cinco servicios esenciales:
Gateway, EventBus, Snapshot, Internet y Trading. Agente macOS, Apple Music e IA
se muestran como opcionales `Unknown` hasta disponer de telemetría productiva.
No se derivan estados de documentación, harnesses ni capacidades declaradas.

`Ready` significa que el núcleo requerido para analizar está disponible. No
significa que el bot live, IA o automatizaciones locales estén habilitados.

### Evidencia técnica

- Estado real: cinco esenciales `Ready`; tres opcionales `Unknown`; resultado
  general `Ready`.
- Fixture degradado: Gateway y Trading `Degraded`; resultado `Degraded`.
- Fixture desconectado: Gateway, EventBus e Internet `Failed`; resultado
  `Failed`.
- Trading con más de 30 s sin actualización se degrada; con más de 120 s falla.
- Snapshot stale degrada y expired falla.
- La superficie conserva el track superior derecho de B2.
- Viewport 1920 × 936 sin overflow horizontal ni vertical.
- TradingView y el contexto macro permanecen sin cambios funcionales.
- La lectura operacional usa únicamente GET sobre `/health`.

### Evidencia visual

- `docs/evidence/command-center-b3-arzopa-physical.png`

### Restricciones preservadas

- Wire ABI, fingerprint, EventBus, Gateway y runtime sin modificaciones.
- Cero factories productivas.
- Sin POST, comandos, noticias, clima ni widgets decorativos.
- Sin merge a `main`, Railway o producción.

### Conclusión

**APROBADO técnicamente** y **PENDIENTE perceptualmente**. Hugo debe confirmar
desde 80–90 cm que la lista de ocho estados se comprende en aproximadamente dos
segundos y no compite con TradingView ni con el próximo evento macro.

---

## VAL-0020 — Línea B Sprint B4 · Market Ribbon

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-30 |
| Hardware objetivo | ARZOPA, 1920 × 1080 @ 60 Hz |
| Pregunta | ¿Qué merece atención antes de analizar un activo? |
| Superficies nuevas | 1 módulo; reutiliza la banda superior existente |
| Activos | SPX, VIX, DXY, TOTAL, BTC, ETH, SOL y XRP |

### Semántica

Cada activo muestra únicamente símbolo, precio, variación diaria y frescura. SPX,
VIX y DXY provienen de Yahoo Finance; TOTAL de CoinGecko; los cuatro perpetuos de
Binance Futures. La fuente y el timestamp se conservan aunque un proveedor falle.

`live`, `current`, `close`, `stale` y `unknown` describen actualidad de la
lectura, no dirección ni calidad de una oportunidad. `close` permite representar
honestamente el último cierre de un índice sin llamarlo live.

### Evidencia técnica

- Orden fijo: SPX → VIX → DXY → TOTAL → BTC → ETH → SOL → XRP.
- El fallo de un proveedor conserva únicamente su último valor bueno y expone la
  degradación; no rellena datos mediante otra fuente silenciosa.
- BTC, ETH, SOL y XRP remontan serialmente el widget público con el perpetuo
  exacto de Binance.
- SPX, VIX, DXY y TOTAL conservan precio y porcentaje, pero abren el símbolo
  exacto en una pestaña nueva de TradingView y no alteran el gráfico integrado.
- Las cuatro rutas externas son enlaces nativos con `target="_blank"` y
  `rel="noopener noreferrer"`; no dependen de que el navegador permita un popup
  iniciado por JavaScript.
- `Análisis completo` y las cápsulas externas usan el mismo constructor de URL.
- La banda reemplaza la fila de estado duplicada; no agrega altura a la shell.
- API autenticada y exclusivamente GET.
- `/health` expone únicamente estado, refrescos, uso de caché y degradación por
  proveedor; no publica precios ni modifica el Wire ABI.
- Los símbolos externos no aparecen en el mapa estático del adaptador, por lo que
  una regresión no puede volver a montarlos accidentalmente.
- Símbolo usa 13 px, variación 15 px y precio 16 px.
- Los colores semánticos aumentan saturación sin modificar fondos, densidad ni
  composición.
- Viewport 1920 × 936 sin overflow; banda 1920 × 58 px.
- Smoke local autenticado: SPX abrió
  `https://www.tradingview.com/chart/5qSvm5Yx/?symbol=SP%3ASPX` en una pestaña
  nueva y el gráfico integrado permaneció en BTC.
- Suite completa: 770 pruebas aprobadas.
- Wire ABI, fingerprint, EventBus, Gateway, runtime y factories preservados.

### Evidencia visual

- `docs/evidence/command-center-b4-arzopa-physical.png`

### Conclusión

**APROBADO técnicamente** y **PENDIENTE perceptualmente**. Hugo debe confirmar
desde 80–90 cm que la banda se entiende en aproximadamente dos segundos, que la
frescura es reconocible y que los ocho referentes no compiten con el gráfico.
VAL-0019 continúa abierto de forma independiente.

---

## VAL-0021 — Línea B Sprint B5 · Contexto de IA

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-31 |
| Hardware objetivo | ARZOPA, 1920 × 1080 @ 60 Hz |
| Pregunta | ¿Existe una observación de IA que merezca atención ahora? |
| Superficies nuevas | 1 módulo compacto en el rail de contexto |

### Evidencia técnica

- La proyección acepta únicamente evidencia contractual inyectada.
- El estado real no llama Anthropic, `claude_brief` ni `claude_grader`.
- Con el graduador apagado comunica `disabled`, resumen nulo y frescura
  `unknown`.
- Estados, severidades, timestamps, fuentes y resúmenes inválidos fallan
  cerrados.
- El resumen contractual queda limitado a 180 caracteres.
- La API es autenticada, exclusivamente GET y permanece fuera del Wire ABI.
- No existen botones, comandos, recomendaciones ni acciones automáticas.
- Cero factories productivas.
- Viewport técnico 1920 × 907 sin overflow horizontal ni vertical.

### Evidencia visual

- `docs/evidence/command-center-b5-arzopa-technical.png`

### Conclusión

**TÉCNICAMENTE COMPLETO** y **PENDIENTE perceptualmente**. Hugo debe confirmar
desde 80–90 cm que el estado neutral no agrega ruido y que una severidad de
fixture se reconoce sin lectura sostenida.

---

## VAL-0022 — Línea B Sprint B6 · Atención del Bot

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-31 |
| Hardware objetivo | ARZOPA, 1920 × 1080 @ 60 Hz |
| Pregunta | ¿El Bot detectó algo que requiere mi atención? |
| Superficies nuevas | 1 módulo compacto en el rail de contexto |

### Evidencia técnica

- Consume únicamente el estado GET del Bot y reutiliza su autorización.
- La proyección elimina cuenta, órdenes, posiciones, precios, SL, TP y P&L.
- Muestra estado, modo, última señal sanitizada, antigüedad y severidad.
- `dry-run` se representa como estado válido; `kill` como pausa.
- Una fuente con más de 120 segundos se degrada.
- El panel está marcado `solo lectura` y no contiene controles ni enlaces.
- No importa ejecutor, no escribe stores y no modifica el Bot.
- Cero factories productivas.
- Viewport técnico 1920 × 907 sin overflow horizontal ni vertical.

### Evidencia visual

- `docs/evidence/command-center-b6-arzopa-technical.png`

### Conclusión

**TÉCNICAMENTE COMPLETO** y **PENDIENTE perceptualmente**. Hugo debe confirmar
desde 80–90 cm que el modo y la última señal se reconocen sin que el panel
parezca una consola de ejecución.

---

## VAL-0023 — Línea B Sprint B7 · Música

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-31 |
| Hardware objetivo | ARZOPA, 1920 × 1080 @ 60 Hz |
| Pregunta | ¿Qué está sonando y puedo controlarlo? |
| Superficies nuevas | 1 módulo compacto que reemplaza telemetría temporal |

### Evidencia técnica

- Proyección construida exclusivamente sobre `MediaController`.
- Apple Music conserva estado y controles demostrados por su adaptador.
- Qobuz no inventa pista, reproducción ni controles no soportados.
- Comandos con `command_id`, idempotencia, ACK y reconciliación de `unknown`.
- Los efectos se verifican únicamente con `FakeMediaController`.
- Endpoint real GET con `media.factory-inactive`, solo lectura y controles
  deshabilitados.
- Sin POST, sin LaunchAgent, sin shell remoto y sin efectos reales.
- Cero factories productivas.
- Viewport técnico 1920 × 907 sin overflow horizontal ni vertical.

### Evidencia visual

- `docs/evidence/command-center-b7-arzopa-technical.png`

### Conclusión

**TÉCNICAMENTE COMPLETO** y **PENDIENTE perceptualmente**. Hugo debe confirmar
desde 80–90 cm que pista, proveedor y controles pueden reconocerse sin competir
con Atención del Bot.

---

## VAL-0024 — Activación local · Carrusel y Apple Music

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-31 |
| Superficie | Command Center local en `127.0.0.1:8812` |
| Pregunta 1 | ¿El Market Ribbon permanece conectado a datos reales? |
| Pregunta 2 | ¿Play puede iniciar la aplicación local sin inventar estado? |

### Evidencia técnica

- El carrusel consulta su API autenticada al cargar y cada 30 segundos con
  `cache: no-store`.
- Binance Futures entregó BTC, ETH, SOL y XRP con frescura `live`; DXY y TOTAL
  también resultaron `live`. SPX se presentó honestamente como `close` y VIX
  como `current` según sus timestamps.
- La URL antigua `?fixture=ready` entregó los mismos proveedores reales. Un
  fixture solo puede activarse ahora con `fixture_mode=1` explícito.
- Apple Music permanece deshabilitado por defecto. El opt-in local
  `NEXUX_COMMAND_CENTER_MEDIA=apple-music` habilita solo play, pausa, anterior y
  siguiente mediante un endpoint autenticado.
- Play abre Music si está cerrada, espera su disponibilidad, ejecuta el comando
  una sola vez y reconcilia la lectura. Si no existe pista o cola, la interfaz
  informa `Sin pista cargada` en vez de afirmar reproducción.
- No se añadieron factories al registro, LaunchAgent, control remoto, cambios al
  Bot ni despliegues.
- Suite completa: 800 pruebas aprobadas.

### Conclusión

**APROBADO técnicamente en local** y **PENDIENTE perceptualmente** en el Arzopa.
El polling se denomina live por frescura de cada activo, no porque todos los
proveedores ofrezcan streaming continuo.

---

## VAL-0025 — Selector multimedia y metadatos locales

### Contexto

| Campo | Resultado |
|---|---|
| Fecha | 2026-07-31 |
| Hardware objetivo | ARZOPA, 1920 × 1080 @ 60 Hz |
| Pregunta | ¿Qué aplicación quiero abrir y qué está reproduciendo? |
| Proveedores | Apple Music, Qobuz y TIDAL |

### Evidencia técnica

- Selector segmentado de tres proveedores sin modificar el layout general.
- Apple Music: salud, apertura, play/pausa, anterior, siguiente, título, artista,
  álbum y carátula local cuando la pista la entrega.
- Qobuz y TIDAL: salud, versión y apertura; playback y metadatos permanecen
  deshabilitados porque las aplicaciones Desktop no los exponen de forma
  soportada.
- La inspección read-only con Qobuz reproduciendo confirmó que su árbol de
  Accesibilidad solo publica la ventana y controles estándar de macOS. La UI
  muestra `App abierta` y `Sin metadatos ni control remoto`, oculta los botones
  de pista y conserva únicamente `Abrir aplicación`.
- TIDAL instalado `2.43.0` fue detectado cerrado; Qobuz fue detectado `ready` y
  Apple Music `ready` durante el smoke read-only.
- Carátulas limitadas a 5 MB y aceptadas solo como PNG o JPEG.
- El parser de Apple Music acepta el separador decimal regional de macOS sin
  degradar el estado.
- Viewport 1920 × 992: panel de 399 × 167 px, controles completamente visibles,
  sin overflow interno ni desbordamiento de página.
- El registro conserva cero factories; el opt-in es exclusivamente local.
- Suite completa: 806 pruebas aprobadas.

**Corrección posterior:** la conclusión sobre Qobuz/TIDAL fue sustituida por
VAL-0026. La inspección inicial no había habilitado la accesibilidad manual de
Electron y, por tanto, no observó el reproductor interno.

### Conclusión

**APROBADO técnicamente** y **PENDIENTE perceptualmente**. La carátula real debe
validarse cuando Apple Music tenga una pista con artwork cargada; durante el
smoke no existía `current track`, por lo que se verificó el placeholder honesto.

---

## VAL-0026 — Puente multimedia accesible Qobuz/TIDAL

### Contexto

La conclusión de VAL-0025 era incompleta: la inspección inicial no había
habilitado `AXManualAccessibility` en las aplicaciones Electron y solo observó
la envoltura de la ventana. Una segunda inspección sobre reproducción real sí
expuso el árbol del reproductor.

### Evidencia técnica

- Qobuz `8.2.0-b033`: lectura real de `De Onda`, `Bersuit Vergarabat`,
  `Libertinaje`, progreso y estado. Play y pausa se ejecutaron y reconciliaron;
  ambos devolvieron el estado esperado. Sus atajos documentados se envían al PID
  de Qobuz, nunca como tecla multimedia global ni mediante coordenadas.
- TIDAL `2.43.0`: lectura real de pista, artista, playlist/álbum, progreso y
  estado. Los botones accesibles `Pausar`, `Reproducir`, `Anterior` y `Siguiente`
  se operan mediante `AXPress`. Pausa y reproducción fueron reconciliadas.
- Si falta permiso de Accesibilidad, el agente o un control estable, el adaptador
  degrada o rechaza la acción. No inventa metadatos ni confirma un efecto que no
  pudo enviar.
- El puente vive en el agente macOS. No modifica Wire ABI, EventBus, Gateway,
  Bot, factories, Railway ni producción.
- Qobuz Connect y TIDAL Connect siguen fuera de alcance; esta es una integración
  local experimental que puede requerir mantenimiento cuando cambie la UI.

### Resolución

**APROBADO técnicamente en local** para lectura y control. **PENDIENTE
perceptualmente** en el Arzopa. La carátula de Qobuz/TIDAL sigue usando el
placeholder porque Accesibilidad no entrega bytes de imagen confiables.

---

## Próximas validaciones

### VAL-0002 — Viewport secundario

Registrar hardware, resolución nativa, escalado efectivo, frecuencia,
`window.innerWidth`, `window.innerHeight`, `devicePixelRatio` y viewport útil.

### VAL-0003 — Ergonomía

Registrar distancia de observación, diferencia vertical, ángulo de mirada,
inclinación, reflejos y postura.

### VAL-0004 — Legibilidad

Comparar textos de 12, 14, 16 y 20 px desde la posición real, incluyendo números
tabulares. Registrar errores, esfuerzo percibido y tamaño operacional aprobado.

### VAL-0005 — Contraste y brillo

Verificar ratios, estados semánticos y comodidad en condiciones diurnas y
nocturnas.

### VAL-0006 — Densidad perceptual

Determinar cuánta información puede reconocerse sin búsqueda visual sostenida ni
cambio de postura.

### VAL-0007 — Regla neutral de los dos segundos

Medir reconocimiento de estado, modo y anomalía con una pantalla neutral. Registrar
participantes, intentos, tiempos, errores y acciones correctivas.

### VAL-0008 — Regla de los dos segundos en el producto

Ejecutar después de la Fase -1B sobre el primer mockup estático con contenido
realista.
