# Command Center Context Storage & Recovery

Estado: implementado y probado en rama. Coleccion no autorizada.

## Objetivo

Preservar historia causal del Command Center frente a reinicios, cierres
inesperados, corrupcion, perdida del Mac y agotamiento de espacio, sin mezclarla
con Trading Intelligence Lab ni convertirla en una fuente operativa.

## Ruta primaria

Ruta propuesta para macOS:

`~/Library/Application Support/NexUX/ContextHistory`

La capa rechaza una ruta ubicada dentro del repositorio. El layout no se crea al
importar ni al iniciar NexUX con la coleccion bloqueada.

## Layout

```text
ContextHistory/
  active/context-current.jsonl
  segments/segment-000001.jsonl
  manifests/segment-000001.json
  backup-receipts/segment-000001.json
  snapshots/snapshot-<timestamp>.json
  recovery/
  storage-policy.json
  .context-storage.lock
```

Permisos:

- directorios `0700`;
- activo, locks y recibos sensibles `0600`;
- segmentos, manifests y snapshots cerrados `0400`.

## Segmentos y rotacion

Politica inicial:

- cierre al alcanzar 64 MiB o 24 horas;
- cada segmento conserva JSONL original, sin reescritura;
- manifest con conteo, limites de secuencia, timestamps, SHA-256 y hashes de
  eventos extremos;
- manifests encadenados mediante `previous_manifest_hash`;
- el primer evento del segmento nuevo conserva el hash del ultimo evento
  anterior;
- rename, fsync de archivo y fsync de directorio antes de publicar el manifest.

Un cierre interrumpido puede dejar un segmento sin manifest. Ese estado se detecta
como huerfano y bloquea nuevas escrituras; nunca se adopta silenciosamente.

## Consistencia y recuperacion

- escritor y rotador comparten un lock coordinador;
- una escritura parcial se revierte al offset anterior cuando el proceso recibe
  el error;
- una cola incompleta tras una caida bloquea el audit;
- la reparacion requiere el comando explicito `recover-tail` con confirmacion;
- los bytes retirados quedan en cuarentena con hash y recibo;
- ninguna reparacion modifica segmentos cerrados.

## Espacio

El piso inicial es 2 GiB libres. Debajo de ese valor:

- health pasa a `low_space`;
- el writer falla cerrado antes de aceptar otro snapshot;
- no se elimina historia automaticamente.

Un `ENOSPC` durante la escritura deja el recorder en `failed` y revierte la linea
parcial cuando el sistema de archivos lo permite. Cualquier resto no valido sera
detectado en el siguiente audit.

## Retencion

Politica inicial: 90 dias locales como minimo.

El sistema solo identifica `eligible_for_manual_review` cuando:

- el segmento supera la edad minima;
- existe recibo local valido;
- el artefacto Vault externo existe;
- su SHA-256 coincide;
- el manifest y el hash del segmento coinciden con el recibo.

No existe una funcion de borrado. La compactacion de evidencia fuente tampoco esta
autorizada. En el futuro podran crearse indices derivados, pero nunca sustituir
segmentos originales sin un nuevo contrato.

## Vault externo cifrado

Cada segmento cerrado y su manifest se empaquetan y cifran mediante:

- data key AES-256-GCM aleatoria;
- data key envuelta con RSA-OAEP-256;
- una clave nueva por artefacto;
- recibo local y `vault-index.json` externo con hashes verificables.

La clave RSA del Context Vault debe ser exclusiva. No debe reutilizar la KEK de
credenciales de Binance. La privada debe permanecer fuera del Mac mini operativo;
la publica basta para respaldar.

La ruta de esa publica se declara mediante
`NEXUX_CONTEXT_VAULT_PUBLIC_FILE`; el destino se declara con
`NEXUX_CONTEXT_BACKUP_ROOT`. Cuando una futura coleccion cierre un segmento, el
backup cifrado se ejecutara antes de aceptar el storage como sano para retencion.

Google Drive puede alojar los `.vault.json`, pero recibe exclusivamente artefactos
cifrados. No se sincroniza la carpeta primaria en claro.

## Restauracion

La restauracion:

1. exige un destino vacio;
2. descifra cada Vault;
3. verifica AEAD, hash del payload, manifest y segmento;
4. conserva la politica original;
5. reconstruye segmentos inmutables;
6. audita la cadena completa;
7. genera un recibo de restore drill.

El origen solo considera valido el ensayo cuando la lista completa de hashes de
manifests restaurados coincide con la propia.

Antes de la activacion, el storage primario debe permanecer vacio. Por eso el
primer ensayo utiliza una historia canario en dos rutas aisladas: origen de
prueba y copia restaurada. El primario guarda un recibo que referencia ambas y
las vuelve a auditar en cada health check. Si una desaparece o se altera, el
ensayo deja de ser valido. En cuanto nace el primer segmento real, el recibo
aislado expira y se exige restaurar y verificar la cadena primaria real.

## CLI offline

```bash
python3 -m modules.command_center.context_storage_cli init --root <ruta>
python3 -m modules.command_center.context_storage_cli audit --root <ruta>
python3 -m modules.command_center.context_storage_cli rotate --root <ruta> --force
python3 -m modules.command_center.context_storage_cli snapshot --root <ruta>
python3 -m modules.command_center.context_storage_cli backup --root <ruta> \
  --destination <vault-externo> --public-key-file <public.pem>
python3 -m modules.command_center.context_storage_cli restore \
  --vault-dir <vault-externo> --target <destino-vacio> \
  --private-key-file <private.pem>
python3 -m modules.command_center.context_storage_cli verify-restore \
  --root <ruta> --restored-root <destino-restaurado>
python3 -m modules.command_center.context_storage_cli record-isolated-drill \
  --root <primario-vacio> --drill-source-root <canario> \
  --drill-restored-root <canario-restaurado>
```

La CLI no contiene comando de activacion ni de borrado.

## Health

Expone:

- inicializacion e integridad;
- ruta y validacion de que esta fuera del repo;
- segmentos y secuencia final;
- eventos del activo;
- bytes libres y `low_space`;
- cobertura completa de backups;
- restore drill verificado;
- bloqueo de escritura;
- release de coleccion.

No expone precios, eventos ni material criptografico.

## Activacion bloqueada

El codigo contiene un release gate en `False`. Las variables de entorno no pueden
saltarlo. Una futura activacion requiere otro commit, ademas de:

- storage inicializado y `ready`;
- ruta fuera del repo;
- espacio suficiente;
- todos los segmentos cerrados respaldados;
- Vault externo configurado;
- clave publica dedicada disponible;
- restore drill coincidente;
- persistencia y backup confirmados;
- ADR de activacion aprobado.

## Separacion

Este storage usa rutas, schemas, manifests y responsabilidades propias. No lee ni
escribe la cohorte prospectiva de Trading Intelligence Lab.

No se modificaron Wire ABI, EventBus, Gateway, Bot, Railway, VPS ni produccion.
