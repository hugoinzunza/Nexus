# Auditoria rev.2 del diseno del observador Bot3.v13

**Fecha:** 2026-08-19  
**Documento auditado:** `docs/BOT3_V13_OBSERVADOR_DISENO.md` rev.2  
**Commit:** `9b39cba`  
**SHA-256 verificado:** `aeaaa7cf5a24654901ae419b542183b4ef189897506c138bd140375c11e77d03`  
**Contrato del motor:** `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d`

## Veredicto

`NO CONFORME / REQUIERE REVISION 3 ACOTADA`

La rev.2 cierra conceptualmente los tres blockers y cuatro majors de la primera
auditoria. La eliminacion del head mutable, el gating H4, el catch-up, la
frontera dual y el estado terminal son direcciones correctas. Persisten tres
contradicciones operacionales que deben resolverse antes de pre-registrar el
protocolo, mas tres precisiones normativas menores.

No se autoriza implementar ni actualizar snapshots canonicos todavia.

## BLOCKER 1 - El lock de vida completa no puede adquirirse para la captura

La seccion 13 dice que el `flock` se toma antes de abrir el libro y se libera
solo al terminar el daemon. La seccion 7 pide tomar "el lock del observador"
para capturar el estado periodicamente. Un verificador externo no puede adquirir
un lock que el daemon conserva durante toda su vida.

Se deben separar dos primitivas:

1. `singleton_lock`: `flock` de vida completa, impide un segundo observador;
2. `cycle_barrier`: mutex interno, adquirido por el ciclo y por la captura para
   obtener un punto consistente.

La captura periodica debe ser iniciada por el proceso propietario o mediante un
canal que le solicite cerrar una barrera. Nunca debe liberar el singleton para
permitir la auditoria.

Gate: solicitar verificacion mientras un ciclo esta entre pull, drenar y append;
la captura debe esperar la barrera sin permitir una segunda instancia.

## BLOCKER 2 - El sufijo sintetico no puede tocar el motor vivo

La seccion 7 ordena alimentar "al motor vivo y al frio" con un sufijo sintetico.
Eso contaminaria el estado y el ledger de la cohorte real, aunque luego se
pretendiera descartar el resultado. El motor vivo es append-only y no tiene
rollback autorizado.

La prueba debe operar sobre DOS clones aislados:

- `clone_live`: clon consistente del estado RAM capturado en la barrera, con
  almacenes y ledger scratch;
- `clone_cold`: reconstruccion desde los archivos scratch en la misma barrera.

El daemon real no recibe velas desafio ni escribe durante esa prueba. Si no se
define una serializacion/reconstruccion verificable de `clone_live`, el sufijo
desafio debe eliminarse y el `state_digest` debe cubrir todo el estado que pueda
afectar decisiones futuras.

Gate: tras una verificacion periodica, los heads, el state digest y el ledger
del daemon real deben permanecer byte a byte iguales a los de antes de iniciar
el desafio.

## BLOCKER 3 - La ausencia H4 no tiene maquinaria operacional definida

La rev.2 permite procesar cuando una ausencia H4 esta sellada por "la misma
maquinaria de watermark que ya usa M15". Esa maquinaria no es generica en la
ruta actual:

- `Motor.watermark_exchange(T)` consulta exclusivamente `self.m15`;
- usa lotes y duracion M15;
- restaura `mercado_degradado` con semantica M15;
- `lote_finalizable(T)` tampoco gobierna H4.

El protocolo del motor ya establece que un hueco H4 posterior a `GENESIS_H4`
produce `historia_insuficiente` sin excepciones. El observador debe definir, sin
modificar esa regla:

- grilla H4 esperada para cada `T` M15;
- watermark local H4 y prueba exacta;
- si se permite watermark exchange H4, sus Q/N, prueba y `detected_at`;
- evento `hueco_detectado(tf="4h")` y sus heads/finalidad;
- prohibicion de reutilizar `mercado_degradado/reingresado` M15 para inventar
  continuidad H4;
- consecuencia: el mercado queda en `historia_insuficiente` para candidatos
  posteriores, mientras los demas mercados pueden continuar.

Esto puede vivir en el protocolo del observador si solo gobierna la ingestión y
usa tipos ya registrados. Si altera estado o semantica del motor, requiere un
Gate contractual nuevo y no puede presentarse como simple precondicion.

Gate: un mercado sin una vela H4, con M15 completo y cuatro referencias H4
frescas, debe sellar exactamente un marcador reproducible; continuo y replay
deben abstener ese mercado y producir el mismo libro.

## MAJOR 1 - La paginacion tiene un borde incorrecto

La formula:

`startTime = ultimo_t + 1 - RESOLAPE*dur`

queda un milisegundo fuera de la grilla y no expresa de forma inequivoca cuantas
velas selladas se reingieren. Para incluir exactamente `RESOLAPE` velas,
incluida la ultima sellada, debe congelarse una expresion alineada, por ejemplo:

`startTime = ultimo_t - (RESOLAPE - 1)*dur`

Tambien falta congelar el avance entre paginas:

`startTime_siguiente = openTime_ultima_fila + dur`

Se debe exigir progreso estricto; una pagina llena que no avance es fallo
cerrado, no un loop infinito.

## MAJOR 2 - `state_digest` resume estado que debe autenticar completo

Guardar solo ultimo elemento y cardinalidad de `lotes_finalizados`, y solo la
cardinalidad de `cierres`, permite que dos estados distintos compartan digest.
`cierres` participa en el corte por semanas ISO; por tanto su contenido afecta
decisiones futuras.

El digest debe incluir las listas completas canonicas o hashes de contenido que
las autentiquen integralmente. Se debe fijar tambien el valor ausente de
`motivo_corte` y declarar que caches derivados (`_cache_h4`, `_swm15`, caches de
almacen) quedan excluidos porque se recomputan sin cambiar resultados.

Gate: alterar una fecha/R de un cierre intermedio conservando cardinalidad y
ultimo elemento debe cambiar el digest.

## MAJOR 3 - `COMPLETED` debe sobrevivir al reinicio

La rev.2 define correctamente el estado terminal, pero no su persistencia. Un
health solo en RAM permitiria que launchd reiniciara el servicio y reconstruyera
la cohorte como activa.

Se requiere un marcador terminal persistente y atomico, ligado a identidad de
cohorte, contrato, commit, motivo, ultima barrera, heads y firma del ledger. El
orden debe ser:

1. cerrar motor y emitir eventos terminales;
2. fsync de almacenes y ledger;
3. escribir marcador temporal, fsync, `os.replace` y fsync del directorio;
4. exponer health `COMPLETED` y salir sin reactivacion.

Al arrancar, el marcador se valida antes de abrir un ciclo. Si existe y coincide,
el servicio reporta `COMPLETED` sin ingerir. Si esta corrupto o discrepa, falla
cerrado.

## Aclaracion sobre el prefijo de nacimiento

La solucion `snapshot_record_count + snapshot_head` es aprobable y evita el
estado mutable. La implementacion debe materializar el nacimiento completo en
staging y publicar un manifiesto atomico que contenga los 14 prefijos. Una caida
durante el primer nacimiento no puede dejar algunos almacenes interpretados
como cohorte ya nacida y otros como primer arranque sin una regla de
recuperacion unica.

## Cierres aprobados de rev.2

- El manifiesto no necesita un head mutable ni un journal por ciclo.
- El snapshot inicial sigue inmutable y el sufijo queda autenticado por cadena.
- H4 es una dependencia obligatoria de cada lote M15.
- El reloj de elegibilidad debe ser Binance, sin fallback al Mac.
- Catch-up ingiere pero no procesa hasta recuperar los 14 streams.
- La frontera congela los 14 terminales y limita H4 a cierres `<= F`.
- El corte deja de ingerir y no crea otra cohorte automaticamente.
- El mapeo push/snapshot identico requiere gate adversarial.
- La clasificacion `common_upstream_gap / causa no demostrada` se mantiene.

## Gates adicionales para revision 3

1. Singleton lock retenido mientras la captura espera una barrera interna.
2. Sufijo desafio solo sobre dos clones scratch; daemon real inmutable.
3. Watermark H4 local y exchange con prueba reproducible.
4. Mercado con hueco H4 queda `historia_insuficiente` sin bloquear los otros.
5. Paginacion alineada, progreso estricto y backlog multipagina.
6. Digest cambia al alterar un cierre intermedio sin cambiar cardinalidad.
7. Marcador `COMPLETED` sobrevive a reinicio y rechaza corrupcion.
8. Caida durante nacimiento parcial de los 14 almacenes.

## Estado final

- Diseno rev.2: `NO CONFORME`.
- Revision requerida: `REV.3 ACOTADA`.
- Protocolo del observador: `NO AUTORIZADO TODAVIA`.
- Implementacion: `NO AUTORIZADA`.
- Snapshots canonicos: `SIN CAMBIOS / ACTUALIZACION NO AUTORIZADA TODAVIA`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte: `NO INICIADA`.
- Bot3.v1: `SUSPENDIDO`.
