# Playbook operativo observado - Bitcoin Traders SMC

**Version:** `playbook.v1`<br>
**Estado:** `FROZEN RESEARCH BASELINE / NOT TRADING-AUTHORIZED`<br>
**Fuente:** `BOOTCAMP MAYO 2025`, sesiones 1-11.

## Veredicto ejecutivo

La estrategia enseñada no es `OB/FVG -> entrada`. Su secuencia estable es:

```text
horizonte y timeframe rector
-> fractal valido
-> rango operativo y 50%
-> direccion y weak target
-> zona admisible
-> mapa de liquidez previa/exterior
-> riesgo o confirmacion
-> invalidacion, objetivo y gestion
```

El curso entrega un lenguaje consistente para leer contexto y zonas, pero no un
algoritmo totalmente cerrado. La seleccion del swing rector, algunos detalles de
rango y varias decisiones de gestion siguen siendo discrecionales.

## 0. Definir la operacion antes del mapa

Fijar:

- horizonte (swing, intraday o scalp);
- timeframe rector;
- timeframe de estructura interna;
- objetivo estructural esperado;
- riesgo maximo autorizado.

**Evidencia:** S06 00:03:39-00:05:00; S09 00:03:17-00:07:35.

**Abstenerse** si se cambia de estructura solo para justificar una entrada ya
deseada. El profesor reconoce que varias estructuras pueden ser validas; por eso
el horizonte debe elegirse antes.

## 1. Leer la jerarquia temporal

Jerarquia observada:

```text
semanal > diario > H4 > M15 > M5/M3/M1
```

El sistema intraday recomendado para comenzar utiliza diario + H4 y puede llegar
a H1. Las temporalidades menores refinan/confirmar; no anulan silenciosamente el
contexto superior.

**Evidencia:** S01 01:44:15-01:46:39; S09 00:22:58-00:24:22 y
01:14:44-01:15:01.

## 2. Construir el fractal valido

1. identificar impulso;
2. medir desde el swing responsable;
3. exigir retroceso de al menos 50%, por cuerpo o mecha;
4. comprobar que la continuacion rompe el extremo correspondiente;
5. separar fractal rector de fractales internos.

**Evidencia:** S02 00:16:33-00:41:11.

**No inferir:** que un retroceso >50% garantiza continuacion. El profesor lo
considera preferible, pero no aporta frecuencia.

## 3. Construir el rango operativo

Version enseñada y utilizable:

1. detectar toma de liquidez y rompimiento;
2. fijar strong high/low como inicio;
3. esperar finalizacion mediante swing e iBOS;
4. marcar weak high/low opuesto;
5. dividir al 50%;
6. actualizar despues de BOS de continuacion.

**Evidencia:** S03 01:05:15-01:24:54.

**Reserva:** S09 01:28:52-01:34:47 declara que el profesor estudiaba cambiar la
logica de rangos. Esa revision no tenia probabilidad ni definicion final y queda
fuera del playbook.

## 4. Exigir direccion y precio relativo coherentes

- rango alcista: priorizar compras desde 50%/discount hacia weak high;
- rango bajista: priorizar ventas desde 50%/premium hacia weak low;
- contra tendencia: posible, pero se interpreta como retroceso y exige gestion
  separada.

**Evidencia:** S04 00:38:28-00:44:42; S07 00:14:30-00:19:18.

**Abstenerse** si fractal y rango contradicen la idea y no se ha definido de
antemano que se opera un retroceso.

## 5. Seleccionar solo zonas admitidas

Las tres familias de entrada admitidas son:

1. order block;
2. imbalance/FVG;
3. toma de liquidez.

Para un OB, registrar:

- tradicional o no;
- decisional, extremo, breaker o `alta probabilidad`;
- imbalance presente/ausente;
- liquidez de vela;
- liquidez previa generada;
- timeframe y estado de frescura.

**Evidencia:** S04 00:02:49-00:24:50; S06 00:31:54-00:32:37.

El curso prioriza `tradicional + liquidez previa generada`; no exige siempre los
cuatro atributos. `Alta probabilidad` es una etiqueta docente, no una medicion.

## 6. Auditar liquidez antes de aceptar la zona

### Delante del bloque

Buscar trendline, equal highs/lows o high/low relevante antes de llegar a la
zona. Esa liquidez puede fortalecer el contexto del toque.

### Detras del bloque

Buscar liquidez exterior mas alla de su invalidacion. Si existe:

- clasificar el primer OB como posible bloque trampa;
- no eliminar la trampa por refinar timeframe;
- buscar la siguiente zona mas alla de la liquidez;
- o repartir el riesgo solo si el plan lo permite.

**Evidencia:** S05 00:03:57-00:33:19; S08 00:09:45-00:35:40.

**Abstenerse** si la unica justificacion es que el OB “cumple todos los
requisitos” pero deja liquidez obvia detras.

## 7. Elegir el modelo de entrada

### A riesgo

Usar orden directa en la zona cuando:

- el stop estructural cabe en el riesgo;
- existe objetivo con al menos 2R en el ejemplo del curso;
- se acepta la posibilidad de invalidacion sin confirmacion.

### Por confirmacion

1. esperar reaccion en la zona HTF;
2. bajar al timeframe de confirmacion;
3. exigir iBOS estructural;
4. comprobar toma de liquidez a la izquierda;
5. comprobar creacion de liquidez a la derecha;
6. operar desde una zona creada por el desplazamiento.

Tabla observada:

| Zona | Confirmacion |
|---|---|
| Diario | H1 |
| H4 | M15 |
| H1 | M5 |
| M15 | M5/M3/M1 en ejemplos |

**Evidencia:** S06 00:31:54-00:50:21; S08 00:36:05-00:41:50.

## 8. Definir invalidacion y objetivo antes de ejecutar

- stop al otro lado de la estructura/zona que invalida la idea;
- objetivo principal en el weak high/low del rango rector;
- objetivo de una estructura menor corresponde a un recorrido menor;
- descartar entrada a riesgo si no entrega RR suficiente.

**Evidencia:** S06 00:33:54-00:43:06; S07 00:55:44-00:57:58; S08
00:38:48-00:39:15.

**U0:** el curso no fija un buffer, ATR, tolerancia de wick ni costos de ejecucion.

## 9. Gestionar sin redefinir el setup

Reglas estables del plan:

- comenzar con riesgo bajo; la banda docente es `0,5%-1%` por operacion;
- definir por adelantado un limite diario de perdida/stops;
- aceptar la perdida completa antes de ejecutar;
- el docente enuncia como regla universal gestionar dos entradas y dividir entre
  ambas el riesgo total (`0,5 + 0,5` si el plan autoriza `1%`); dos stops terminan
  la operativa del dia;
- un stop correcto no vuelve invalida la estrategia;
- una zona refinada se prefiere en su primer uso;
- revisar el mapa dos o tres veces antes de ejecutar;
- break-even y parciales aparecen en replays, pero no tienen un disparador
  universal;
- una nueva entrada requiere una nueva oportunidad estructural, no revancha.

**Evidencia de dos entradas:** S08 00:52:30-00:53:53, donde la regla se formula
como universal y con riesgo repartido; S11 02:28:11-02:29:52 confirma el mismo
principio con `0,25 + 0,25` para un riesgo total de `0,5%`.

**Evidencia de frescura:** S04 01:04:22-01:10:01 para zona no mitigada/nuevo
extremo; S05 00:32:12-00:33:02 para persistencia de la trampa al refinar.

**Resto de evidencia:** S07 00:57:08-01:07:59; S09 00:08:52-00:13:12; S10
01:31:40-01:39:03; S11 00:25:05-00:53:00.

El reparto personal del profesor (`0,5%` contra tendencia y `1%` a favor), sus dos
stops diarios y la meta semanal de `3%-5%` son ejemplos de su plan, no parametros
universales demostrados.

**Exclusion critica:** S11 01:45:17-01:55:01 propone dimensionar futuros para que
el stop consuma cerca del 80% del margen asignado e incluso contempla
liquidacion. Esa formula no se incorpora: mezcla sizing de cuenta, margen,
apalancamiento y liquidacion sin un modelo auditable de exchange y costos.

## 10. Registrar y revisar

Campos minimos observados:

- fecha/hora y activo;
- timeframe/horizonte;
- direccion y setup;
- entrada, stop, target;
- RR esperado y realizado;
- resultado y motivo de salida;
- captura del mapa;
- error de proceso;
- estado emocional antes/despues.

El profesor recomienda una muestra inicial cercana a 100 operaciones y advierte
contra concluir desde 10-15 ganadoras.

**Evidencia:** S10 00:01:35-00:15:22 y 01:31:40-01:39:03.

## Checklist de estudio

Una idea solo esta completamente descrita si responde:

- [ ] ¿Que horizonte estoy operando?
- [ ] ¿Cual es el timeframe rector?
- [ ] ¿El fractal alcanzo 50%?
- [ ] ¿Cual es el rango activo y su weak target?
- [ ] ¿La entrada esta en premium/discount coherente?
- [ ] ¿Que tipo de zona es?
- [ ] ¿Tiene liquidez previa?
- [ ] ¿Tiene liquidez exterior que la vuelve trampa?
- [ ] ¿Es primer uso efectivo de la zona?
- [ ] ¿Entrada a riesgo o por confirmacion?
- [ ] Si confirma, ¿tomo liquidez izquierda y creo liquidez derecha?
- [ ] ¿Cual es la invalidacion estructural?
- [ ] ¿Cual es el target y RR antes de costos?
- [ ] ¿El riesgo total respeta el plan?
- [ ] ¿Que dato quedara en la bitacora?

## Semaforo de confianza

### Verde: nucleo repetido

- fractal >=50%;
- rango + weak target;
- premium/discount por direccion;
- OB/FVG como zona, no entrada automatica;
- mapa de liquidez;
- riesgo frente a confirmacion;
- confirmacion HTF/LTF;
- registrar y backtestear.

### Amarillo: requiere especificacion externa

- seleccion del swing rector;
- tamaño/volumen minimo de OB;
- tamaño minimo de FVG;
- exactitud cuerpo/mecha fuera de las dos reglas Fibonacci ya separadas;
- operacionalizacion de las dos entradas universales: zonas admisibles,
  correlacion y secuencia;
- break-even y parciales;
- regla de diez velas: se cuenta en el timeframe de la zona y el docente la
  relativiza como `un dato no mas` (S06 00:52:16-00:55:47).

### Rojo: no incorporar

- revision futura de rangos mencionada sin terminar;
- formula de futuros basada en consumir 80% del margen o aceptar liquidacion;
- narrativas de noticias como causalidad;
- porcentajes de acierto relatados sin dataset;
- entradas improvisadas por cobertura;
- reglas SMC externas no enseñadas.

## Estado

`PLAYBOOK.V1 FROZEN / PRIMARY VISUAL GATE CLOSED / NO BOT PROMOTION`
