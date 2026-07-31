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
