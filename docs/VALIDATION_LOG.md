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
