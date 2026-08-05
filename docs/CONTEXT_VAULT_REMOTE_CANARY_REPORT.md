# Context Vault Remote Canary Report

Fecha: 2026-08-04  
Resultado: **APROBADO**  
Run ID: `remote-canary-1785890504109`

## Resumen ejecutivo

El canario remoto sintético completó el ciclo `backup -> Google Drive -> eliminación local -> restore -> validación -> limpieza` sin utilizar datos reales. Los eventos, manifiestos, tamaños y hashes restaurados coincidieron exactamente con la fuente sintética.

La colección, el recorder, el interpreter, los schedulers, `launchd`, cron y los backups automáticos permanecen inactivos. No se modificó código, producción, Railway, VPS ni el Bot.

## Ruta detectada

Google Drive para escritorio fue detectado en:

`/Users/hugh/Library/CloudStorage/GoogleDrive-hugoinzunza@gmail.com`

La raíz real de la unidad es:

`/Users/hugh/Library/CloudStorage/GoogleDrive-hugoinzunza@gmail.com/Mi unidad`

El canario utilizó temporalmente:

`/Users/hugh/Library/CloudStorage/GoogleDrive-hugoinzunza@gmail.com/Mi unidad/NexUX/ContextVault/canary/remote-canary-1785890504109`

`~/Documents/NexUX` fue inspeccionado y corresponde a almacenamiento local; no es un enlace ni un montaje de Google Drive. Por eso no se utilizó.

Google Drive web, con la cuenta `hugoinzunza@gmail.com`, mostró la carpeta `NexUX` después del backup. Tras la limpieza y el refresco mostró cero carpetas `NexUX`, confirmando tanto la sincronización como la eliminación remota.

## Snapshot sintético

- Provenance: `synthetic-remote-canary-v1`
- Eventos: 2
- Segmentos cerrados: 1
- Tamaño plaintext del segmento: 1.418 bytes
- Artefactos cifrados: 2
- Tamaño cifrado total: 8.021 bytes
- Algoritmos: AES-256-GCM con clave de datos por artefacto y RSA-OAEP-256 para envoltura
- Clave privada: permaneció exclusivamente en `~/Library/Application Support/NexUX/ContextVaultKeys`

## Tiempos

- Backup y verificación local del montaje: 11,20 ms
- Restore completo desde Google Drive: 269,58 ms

Estos tiempos miden operaciones sobre el montaje local de Drive. La presencia posterior en Google Drive web fue la verificación independiente de sincronización remota y no se incluye en esas latencias.

## Integridad

| Elemento | SHA-256 |
|---|---|
| Snapshot lógico | `a506594edb4fbd6836416b11bf190881f370fd16f5f393df0d0ece16b8f4e0e0` |
| Artefacto cifrado del snapshot | `3a4f3d87132648a6da7dfee60d2f924c200ef0c6401221c2f3469b3fd4d31848` |
| Reporte de backup | `72c96230672d532fe3bfcf825d4e17181427cd8bf9fe57788d1dd895b1a2034d` |
| Reporte de restore | `8e194721ea4c90decefa60399799f37d1b61e997225188bc53b7b5442abbcf31` |
| Segmento plaintext | `f2ed7e32f29b3b5beb88e217a7251ae1f3325d24a21523c1c348e31320997327` |
| Artefacto cifrado del segmento | `77ad8d92bda154ab318d1e777fc008f63869e24ba54068846af6623e024f5990` |
| Manifest del segmento | `c1176336201a721b75c3779d0f46272952cb8f49366ad0bc2c9c8ccfe57b8000` |

Hashes de los dos eventos restaurados:

1. `73797aeb970fb9a51eab7addacd73be9316ba470092d03f28b3533befd9f78e2`
2. `95d25a2ffe19a8580e7c5825f3cde99dd51364ce7ec9f8c0c95fda56bb134c63`

## Restore independiente

Antes del restore se eliminó por completo la fuente local sintética. El destino de restauración tampoco existía. La reconstrucción utilizó únicamente los artefactos cifrados presentes en Google Drive y la clave privada local.

Comparación posterior:

- Eventos: coincidencia exacta.
- Hashes de eventos: coincidencia exacta.
- Manifests: coincidencia exacta.
- Hashes de manifests: coincidencia exacta.
- Tamaños de segmentos: coincidencia exacta.
- Reporte de restore: `verified` con hash y manifest verificados.

## Pruebas fail-closed

| Escenario | Resultado | Evidencia |
|---|---|---|
| Pérdida temporal de conexión | APROBADO | El proveedor rechazó la lectura como `unavailable`. |
| Archivo inexistente | APROBADO | Rechazado como ausente o corrupto. |
| Snapshot cifrado corrupto | APROBADO | Falló la autenticación AES-GCM (`InvalidTag`). |
| Manifest corrupto | APROBADO | Rechazado como `snapshot manifest is invalid`. |
| Espacio insuficiente | APROBADO | `ENOSPC` inyectado en la frontera de escritura; no quedó archivo parcial. |
| Permisos insuficientes | APROBADO | `EACCES` inyectado en la frontera de escritura; no quedó archivo parcial. |

Las pruebas de espacio y permisos fueron simulaciones controladas sobre la llamada de escritura atómica. No se llenó el disco ni se alteraron permisos reales de Google Drive.

## Incidencia detectada

La función de ruta predeterminada actual construye `My Drive/NexUX/ContextVault`. En esta instalación localizada, la carpeta oficial se llama `Mi unidad`. Por tanto, la autodetección del montaje es correcta, pero la resolución automática de la raíz no es portable entre idiomas.

La incidencia no afectó el canario porque la ruta real fue detectada y entregada explícitamente. No se corrigió en este sprint para respetar el alcance de validación sin cambios de código. Debe resolverse antes de una futura activación.

## Limpieza final

- Workspace local sintético: eliminado.
- Fuente local sintética: eliminada antes del restore.
- Restore local sintético: eliminado.
- Artefactos negativos: eliminados.
- Run remoto: eliminado.
- Directorios remotos vacíos creados por el ensayo: eliminados.
- Verificación filesystem: ruta remota ausente.
- Verificación Google Drive web: carpeta `NexUX` ausente después del refresco.
- Datos reales usados: ninguno.

## Decisión

**Remote Canary Validation: APROBADO.**

El Context Vault demostró backup cifrado, sincronización remota, restauración exclusiva desde Google Drive, igualdad exacta y fallos cerrados. Esto valida el ensayo remoto, pero **no autoriza la activación**.

Permanecen desactivados:

- Context Recorder
- Context Collection
- Context Interpreter operativo
- LaunchAgent
- cron
- scheduler
- snapshots y backups automáticos

La activación definitiva continúa requiriendo autorización formal y la resolución previa de la ruta localizada de Google Drive.
