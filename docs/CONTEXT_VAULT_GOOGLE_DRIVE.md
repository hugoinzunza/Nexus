# NexUX Context Vault en Google Drive

Estado: infraestructura manual implementada; Google Drive real no montado;
coleccion inactiva.

## Arquitectura

```text
Context Storage primario (Mac mini)
  -> segmentos cerrados + manifests encadenados
  -> snapshot causal consistente
  -> data-key AES-256-GCM nueva por artefacto
  -> data-key envuelta con KEK RSA-OAEP-256 exclusiva
  -> SHA-256 de artefacto y recibo local
  -> Google Drive for desktop
  -> lectura posterior y comparacion de hash
```

Google Drive es exclusivamente un destino externo. Nunca se lee como fuente
operativa ni sustituye el Context Storage primario.

## Estado comprobado

- proveedor filesystem para montajes oficiales `GoogleDrive-*` implementado;
- Google Drive for desktop no esta instalado ni montado actualmente en este Mac;
- clave exclusiva generada fuera del repositorio;
- canario sintetico local completado con backup, restore y eventos identicos;
- recorder, backups automaticos, cron y `launchd` permanecen desactivados.

El canario local valida el contrato, el cifrado y la restauracion. No demuestra
durabilidad remota en Google Drive. Esa evidencia queda pendiente hasta instalar,
autenticar y montar Google Drive for desktop.

## Proveedor Google Drive

El proveedor acepta un destino solo cuando se encuentra dentro de:

`~/Library/CloudStorage/GoogleDrive-*/`

La ruta prevista es:

`<GoogleDrive>/My Drive/NexUX/ContextVault`

Cada escritura:

1. se realiza primero en un archivo temporal;
2. ejecuta `fsync`;
3. se publica mediante rename atomico;
4. se relee completamente;
5. compara SHA-256;
6. rechaza sobrescribir un artefacto distinto.

Google Drive for desktop controla la sincronizacion remota. La lectura local
posterior demuestra integridad en el montaje, no confirmacion del servidor de
Google. Antes de activar la coleccion se requiere un canario en el montaje real y
comprobar su disponibilidad desde otra sesion o dispositivo.

## Gestion de claves

Ruta creada:

`~/Library/Application Support/NexUX/ContextVaultKeys`

Contiene:

- `context-vault-private.pem`, permiso `0600`;
- `context-vault-public.pem`;
- `context-vault-key.json`, fingerprint y metadata sin secretos.

El algoritmo es envelope encryption:

- AES-256-GCM cifra cada segmento y cada snapshot;
- cada artefacto recibe una data-key aleatoria independiente;
- RSA-3072 OAEP-SHA256 envuelve la data-key;
- la privada nunca entra al repositorio ni al Vault de Google Drive.

La clave es distinta de la KEK de Binance. La metadata conserva
`recovery_copy_confirmed: false`: antes de activar debe existir una copia de
recuperacion offline, custodiada separadamente y ensayada. Copiar la privada al
mismo Google Drive anularia el aislamiento y esta prohibido.

## Formato del snapshot

El snapshot en claro existe solo en memoria antes de cifrarse. Contiene:

- schema y version;
- fecha de creacion;
- provenance;
- schema y hash de la politica del storage;
- numero de segmentos;
- tamano total;
- hash del manifest final;
- cada manifest completo;
- hash y tamano de cada segmento;
- nombre, hash y tamano de cada artefacto Vault.

El destino recibe unicamente:

- `segments/segment-XXXXXX.vault.json`;
- `snapshots/snapshot-<fecha>-<hash>.vault.json`;
- `provider.json`, que no contiene datos de mercado.

No se suben segmentos, manifests ni precios en claro. El archivo activo tampoco
se incluye: primero debe cerrarse y adquirir un manifest inmutable.

## Backup incremental

El comando manual compara la cadena primaria contra los recibos y artefactos ya
existentes.

- segmentos verificados se reutilizan;
- segmentos nuevos se cifran y publican;
- un artefacto existente sin recibo valido bloquea el proceso;
- un hash distinto bloquea el proceso;
- al final se publica un snapshot cifrado y un reporte local verificable.

No existe programacion automatica ni llamada desde el recorder.

```bash
python3 -m modules.command_center.context_vault_cli backup \
  --storage-root "$HOME/Library/Application Support/NexUX/ContextHistory" \
  --vault-root "<GoogleDrive>/My Drive/NexUX/ContextVault" \
  --public-key-file "$HOME/Library/Application Support/NexUX/ContextVaultKeys/context-vault-public.pem" \
  --provenance "nexux-context-v1"
```

## Restauracion

La restauracion exige:

1. snapshot cifrado existente;
2. clave privada correcta;
3. destino vacio;
4. hash valido del snapshot;
5. AEAD valido;
6. todos los artefactos presentes;
7. hashes de artefactos coincidentes;
8. manifests encadenados y equivalentes al snapshot;
9. audit completo del storage restaurado.

Una falla aborta el proceso. Nunca se declara exitoso un destino parcial.

```bash
python3 -m modules.command_center.context_vault_cli restore \
  --storage-root "$HOME/Library/Application Support/NexUX/ContextHistory" \
  --vault-root "<GoogleDrive>/My Drive/NexUX/ContextVault" \
  --public-key-file "$HOME/Library/Application Support/NexUX/ContextVaultKeys/context-vault-public.pem" \
  --private-key-file "$HOME/Library/Application Support/NexUX/ContextVaultKeys/context-vault-private.pem" \
  --snapshot-artifact "snapshots/<snapshot>.vault.json" \
  --target-root "<destino-vacio>"
```

## Canary restore

El canario genera una unica observacion sintetica en un storage aislado. Nunca
utiliza la historia primaria. Ejecuta:

```text
evento sintetico -> segmento -> manifest -> cifrado -> snapshot -> restore
-> audit -> comparacion exacta de eventos
```

El ensayo local realizado termino con:

- `status: verified`;
- un segmento;
- hashes validos;
- manifests validos;
- eventos origen/restauracion identicos;
- provider declarado `local-contract-emulation`.

Debe repetirse con el provider real cuando Google Drive este montado:

```bash
python3 -m modules.command_center.context_vault_cli canary \
  --vault-root "<GoogleDrive>/My Drive/NexUX/ContextVault" \
  --key-root "$HOME/Library/Application Support/NexUX/ContextVaultKeys" \
  --workspace-root "$HOME/Library/Application Support/NexUX/ContextVaultCanary"
```

## Health operacional

`context_vault` expone solamente:

- estado del provider;
- ultimo backup;
- ultimo restore;
- verificacion de hashes;
- verificacion de manifests;
- espacio disponible;
- tamano total cifrado;
- disponibilidad y fingerprint de la clave publica;
- `automatic_backup_enabled: false`;
- `collection_enabled: false`.

No expone eventos, precios ni material criptografico.

## Recuperacion

Ante perdida del Mac:

1. recuperar la clave privada desde su custodia offline;
2. montar Google Drive;
3. elegir el ultimo snapshot cifrado valido;
4. restaurar en una ruta vacia;
5. auditar segmentos, manifests y cadena de eventos;
6. comparar el reporte de restauracion;
7. promover manualmente la copia solo despues de revision.

No se restaura encima del primario ni se adopta una copia automaticamente.

## Riesgos y limitaciones

- Google Drive for desktop aun no esta instalado ni autenticado.
- La verificacion actual del provider prueba readback local, no confirmacion
  remota del servidor de Google.
- La copia offline de la clave privada aun no esta confirmada.
- Perder la privada hace irrecuperables todos los artefactos.
- Comprometer la privada permite descifrar snapshots copiados.
- El backup depende de segmentos cerrados; el activo nunca se sube.
- No existe scheduler deliberadamente.
- Google Drive no es almacenamiento transaccional ni fuente operativa.

## Bloqueos de activacion

La coleccion sigue inactiva. Antes de cambiar el release gate se exige:

- Google Drive for desktop instalado, autenticado y montado;
- provider real inicializado;
- canario ejecutado dentro del montaje real;
- verificacion remota independiente;
- copia offline de la privada confirmada y ensayada;
- backup y restore reales de la primera cadena cerrada;
- revision formal y commit exclusivo de activacion.

No hay push, merge, deploy, cron, `launchd` ni activacion implicitos en esta capa.
