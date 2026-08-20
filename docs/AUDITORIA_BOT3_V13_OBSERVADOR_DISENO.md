# Auditoria del diseno del observador Bot3.v13

**Fecha:** 2026-08-19  
**Documento auditado:** `docs/BOT3_V13_OBSERVADOR_DISENO.md`  
**Commit:** `ba4c760`  
**SHA-256 verificado:** `20b4ab35dc922669145a761457ff64c02920c3ba60c9bb1833947c9029d7cbd7`  
**Contrato del motor:** `bf92024708470cc1189b468a8f677cb64d5bb1829bfc7c6dd1b3863f47802c3d`

## Veredicto

`NO CONFORME / REQUIERE REVISION 2 ANTES DEL PROTOCOLO`

La direccion general es correcta: aislamiento de Bot3.v1, API publica sin
credenciales, ingesta H4 y M15, snapshot inmutable, push append-only, instancia
unica y activacion posterior a gates. Sin embargo, quedan tres bloqueos capaces
de hacer divergir el libro entre ejecucion continua y reinicio, mas cuatro
definiciones operacionales necesarias antes de congelar parametros.

No se autoriza implementar ni actualizar snapshots canonicos con este diseno.

## BLOCKER 1 - El head mutable no tiene una transaccion recuperable

El diseno propone appends push permanentes, pero no define como se actualiza la
provenance del manifiesto tras cada append.

La recuperacion actual compara el `head` completo del archivo sellado contra el
`head` guardado en el manifiesto (`runner.py`, `construir_almacenes`). La primera
vela push cambia el head:

- si no se actualiza el manifiesto, el primer reinicio falla;
- si se actualiza despues del append, una caida entre ambas escrituras deja un
  estado valido rechazado;
- si se actualiza antes, una caida deja el manifiesto adelantado al almacen;
- actualizar 14 almacenes y el manifiesto no constituye una operacion atomica.

El protocolo del observador debe definir una recuperacion inequívoca. Una
solucion posible es congelar en el manifiesto el `snapshot_record_count` y el
`snapshot_head`, verificar ese prefijo de nacimiento en cada recuperacion y
aceptar despues solamente la cadena append-only valida. Otra solucion puede usar
un journal/checkpoint transaccional, pero debe demostrar recuperacion tras una
caida entre cada escritura.

Gate obligatorio: caer antes y despues de cada append de almacen y de cada
actualizacion de metadata; todos los reinicios deben reconstruir el mismo libro
y detectar intercambio, truncacion o corrupcion de archivos.

## BLOCKER 2 - M15 puede avanzar con H4 atrasado

Incluir H4 en el pull es necesario pero no suficiente. El motor finaliza lotes
globales con cobertura M15; la frescura H4 no forma parte de
`lote_finalizable(T)`.

Si las siete series M15 llegan y una consulta H4 falla o queda atrasada, el
daemon puede procesar el lote usando un rector H4 congelado. Una ejecucion que
reciba H4 a tiempo y otra que lo reciba despues pueden producir candidatos y
trades distintos. El replay posterior no puede corregir eventos ya sellados.

Antes de procesar cualquier lote M15, el observador debe demostrar para los 14
streams una de estas condiciones normativas:

1. H4 contiene toda vela cuyo cierre sea elegible en `T`; o
2. existe una ausencia H4 causalmente declarada y el motor se abstiene segun una
   regla congelada.

`LAG_MAX` debe evaluarse por mercado y timeframe. Un fallo H4 no puede quedar
oculto por M15 fresco ni por el resto del universo.

Gate obligatorio: retrasar H4 mientras M15 avanza y demostrar cero lotes
procesados hasta recuperar o declarar causalmente la ausencia; continuo y
reinicio deben producir el mismo libro.

## BLOCKER 3 - La verificacion periodica no prueba igualdad de estado

La seccion 8 compara solamente los bytes del ledger. Eso detecta una divergencia
ya materializada, pero no una divergencia latente en RAM. Dos motores pueden
tener el mismo ledger y diferir en:

- candidato u orden vivos;
- posicion y salida transitoria;
- zonas consumidas;
- mercados degradados;
- epocas anunciadas;
- frontera, lotes finalizados o estado de corte.

Si todavia no emitieron otro evento, la firma del ledger coincide y el control
declara un falso exito.

La verificacion debe comparar tambien un `state_digest` canonico del motor en la
misma barrera global, o alimentar a ambos motores con un sufijo desafio identico
y comparar estado y ledger resultantes.

Ademas, copiar archivos mientras el daemon escribe puede mezclar heads de
instantes distintos. La captura scratch debe realizarse bajo el mismo lock,
despues de drenar y cerrar una barrera, con flush/fsync definidos, o mediante un
snapshot atomico equivalente.

Gate obligatorio: introducir una divergencia latente que no cambie el ledger en
el instante de control y comprobar que el verificador la detecta.

## MAJOR 1 - Elegibilidad de vela y paginacion no son normativas

`ahora`, `closeTime cumplido` y `pull desde ultimo_t` permiten implementaciones
distintas. El protocolo debe congelar:

- fuente del reloj de elegibilidad (preferentemente hora de Binance obtenida de
  una API publica, con politica ante indisponibilidad);
- desigualdad exacta: `serverTime >= closeTime + 1 + MARGEN_CIERRE` o su
  equivalente contractual;
- mapeo exacto de cada fila de Binance al esquema OHLCV;
- orden y paginacion por `startTime`, `endTime` y `limit`;
- conducta ante pagina vacia, duplicada, fuera de orden o truncada;
- validacion del simbolo USD-M perpetuo y de las TF `15m`/`4h`.

La cadencia de red no debe cambiar los bytes aceptados ni el orden de sellado.

## MAJOR 2 - `LAG_MAX` no define un camino de recuperacion

"Detener el ciclo" puede dejar al observador bloqueado para siempre: tras una
caida larga, el lag sigue excedido precisamente porque aun no se permitio
recuperar datos.

Debe existir un modo `catch-up` fail-closed:

- permite descargar, ofrecer, drenar y sellar datos;
- prohibe procesar nuevos lotes mientras cualquier stream requerido siga stale;
- pagina hasta un watermark comun verificable;
- solo entonces reanuda el motor, preservando `processed_at` real y la finalidad
  causal del mercado.

No debe saltar lotes ni redefinir la frontera.

## MAJOR 3 - La frontera debe congelar tambien el estado H4

La activacion habla del ultimo cierre M15 comun, pero el sistema usa dos TF y los
snapshots actuales terminan en instantes distintos. El acta debe congelar:

- ultimo `t` y ultimo cierre de cada uno de los 14 snapshots;
- `bootstrap_hasta = F`, cierre M15 comun;
- en H4, exactamente las velas con cierre `<= F` como historia causal elegible;
- hashes, commit y auditoria de continuidad de ambas TF.

Una vela H4 que cierre despues de `F` no puede influir en la primera decision
forward aunque ya exista fisicamente en un archivo o respuesta.

## MAJOR 4 - Falta el estado terminal del daemon

El motor puede cortar por 50 cierres o por tiempo, pero el diseno no dice que
hace el observador despues. Debe congelarse una unica conducta:

- dejar de ingerir y procesar para la cohorte cerrada;
- flush/fsync y sello final;
- health `COMPLETED` con motivo y ultima barrera;
- no reiniciar una cohorte cerrada como si estuviera activa;
- ninguna extension o cohorte nueva automatica.

## Gates minimos para la revision 2

1. Append push y crash en cada frontera de almacen/metadata.
2. M15 fresco con H4 atrasado o ausente.
3. Copia scratch consistente bajo barrera y lock.
4. Divergencia latente de estado con ledger aun identico.
5. Paginacion de backlog mayor al limite de una respuesta.
6. Reloj Binance indisponible o desalineado respecto del Mac.
7. Recuperacion desde lag superior a `LAG_MAX` sin procesar prematuramente.
8. Activacion con cierres terminales H4 y M15 distintos.
9. Corte por N y corte temporal, seguidos de reinicio del servicio.
10. Continuo N+1 versus N + reinicio + push, comparando ledger y state digest.

## Aspectos aprobados

- Separacion completa de Bot3.v1, Bot, Testnet y Live.
- Uso exclusivo de endpoints publicos sin credenciales.
- Necesidad de observar H4 y M15.
- Snapshot inicial inmutable y datos posteriores solo por push.
- Buffer volatil recuperable por re-pull, sujeto a paginacion normativa.
- Instancia unica y rutas dedicadas.
- Actualizacion final de snapshots solo despues de aprobar observador.
- Clasificacion prudente de `common_upstream_gap` con causa no demostrada.
- Grafico mantenido fuera de alcance y como pendiente prioritario separado.

## Estado final

- Diseno rev.1: `NO CONFORME`.
- Protocolo del observador: `NO AUTORIZADO TODAVIA`.
- Implementacion: `NO AUTORIZADA`.
- Actualizacion de snapshots: `NO AUTORIZADA TODAVIA`.
- Despliegue: `NO AUTORIZADO`.
- Cohorte: `NO INICIADA`.
- Bot3.v1: `SUSPENDIDO`.
