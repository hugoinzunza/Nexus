# Glosario operativo - Bitcoin Traders SMC

Este glosario reproduce el significado observado en `BOOTCAMP MAYO 2025`. No
presupone equivalencia con ICT, Wyckoff, SMC generico ni NexUX.

## Estructura

### Fractal

Impulso seguido por retroceso. Sirve para proyectar direccion, no para entrar por
si solo. Fuente: S02 00:16:33-00:17:03 y 00:40:07-00:41:11.

### Fractal valido

Fractal cuyo retroceso alcanza al menos 50% del impulso. Un retroceso mayor sigue
siendo valido. Falta una invalidacion superior explicita. Fuente: S02
00:25:17-00:29:26.

### Anclaje Fibonacci del fractal

Regla de medicion: el profesor ancla mayormente desde las mechas y utiliza el
cuerpo como fallback cuando ese es el extremo relevante. No debe confundirse con
la forma en que el precio toca el 50%. Fuente: S02 00:27:06-00:27:21.

### Toque del 50% del fractal

Regla de tolerancia: una vez trazada la medicion, el retroceso puede alcanzar el
50% con cuerpo o con mecha indistintamente. Fuente: S02 00:29:08-00:29:17.

### Estructura principal e interna

Escalas anidadas de fractales. La clase practica declara que no existe una
seleccion universal: la estructura rectora depende del horizonte y objetivo de la
operacion. Fuente: S09 00:03:17-00:07:35.

### BOS

Rompimiento estructural de continuacion. Fuente: S03 00:09:36-00:10:52.

### iBOS

Rompimiento de estructura interna. En la version base se observa ruptura con
cuerpo; la clase 9 menciona una posible revision futura que no estaba congelada.
Fuente: S03 01:05:15-01:07:46; S09 01:28:52-01:34:47.

### CDC

Cambio de direccion en estructura externa. El profesor evita `CHoCH` por
considerarlo ambiguo. Fuente: S03 01:16:21-01:18:52.

### Strong high / strong low

Extremo que nace de una toma de liquidez seguida por desplazamiento/rompimiento
y que inicia un rango operativo. No todo high/low valido es fuerte. Fuente: S03
00:15:45-00:21:54 y 01:07:19-01:09:35.

### Weak high / weak low

Extremo opuesto del rango que se usa como objetivo esperado del movimiento. No
es una garantia de barrido. Fuente: S03 01:20:25-01:21:32.

## Rango y precio relativo

### Rango operativo / trading range

Area entre un strong high/low de inicio y una finalizacion identificada mediante
swing e iBOS. Se actualiza tras un BOS de continuacion. La formulacion enseñada
enlaza rangos; la clase 9 reconoce que el profesor estudiaba modificarla. Fuente:
S03 01:07:19-01:22:05; S09 01:28:52-01:34:47.

### Finalizacion

Extremo que cierra la construccion del rango y permite definir el weak high/low.
Puede requerir iBOS posterior si la toma fue solo con mecha. Fuente: S03
01:13:14-01:24:54.

### Premium / discount / nivel 50%

Mitad superior e inferior del rango. En un rango bajista se buscan ventas desde
50% o premium; en uno alcista, compras desde 50% o discount. El 50% tambien es el
umbral de validez del fractal, pero son usos distintos. Fuente: S04
00:38:28-00:44:42; S07 00:14:30-00:18:16.

## Oferta y demanda

### Order block (OB)

Ultima vela contraria antes de un movimiento fuerte: bajista antes de impulso
alcista o alcista antes de impulso bajista. Fuente: S04 00:02:49-00:03:40.

### OB tradicional

OB asociado a rompimiento estructural con volumen/desplazamiento. Es el requisito
base que el curso prioriza. Fuente: S04 00:05:27-00:06:17; S05
00:26:32-00:28:05.

### OB decisional

Ultimo OB que, despues de reaccionar en una zona opuesta, origina el rompimiento.
Fuente: S04 00:21:46-00:23:02.

### OB extremo

Origen mas profundo del movimiento que causa el rompimiento. Fuente: S04
00:23:02-00:23:40.

### Breaker

OB fallido que posteriormente actua en direccion contraria. El profesor lo
describe como menos frecuente. Fuente: S04 00:23:40-00:24:01.

### OB de alta probabilidad

Nombre docente para OB con imbalance en discount (alcista) o premium (bajista).
No es una probabilidad estadistica demostrada. Fuente: S04 00:24:01-00:24:50.

### Imbalance / FVG

Vacio de tres velas donde las mechas de la primera y tercera no se solapan.
Tambien se llama ineficiencia o gap en la clase. Fuente: S04
00:10:42-00:12:37.

### POI

Zona de interes formada por OB e imbalance u otra zona admitida. Una POI es un
lugar para vigilar, no una entrada automatica. Fuente: S04
00:17:53-00:18:23; S06 00:31:54-00:32:37.

## Liquidez

### Liquidez agrupada

Trendline, equal highs o equal lows. El curso evita tratar cada pivote como grupo
operativo. Fuente: S05 00:03:57-00:07:10.

### Liquidez individual admitida

High/low que cubre parcialmente un imbalance o extremo H4+. Su relevancia por
mercado no queda completamente cerrada para cripto. Fuente: S05
00:08:34-00:12:23.

### Liquidez previa

Liquidez situada en el trayecto anterior a la llegada al bloque que se desea
operar. Se usa como evidencia adicional para la zona. Fuente: S08
00:34:25-00:35:40.

### Liquidez exterior

Liquidez pendiente detras del bloque en la direccion de su invalidacion. Puede
convertir el primer OB en bloque trampa. Fuente: S08 00:26:40-00:35:40.

### Bloque trampa

Zona estructuralmente admisible pero construida delante de liquidez pendiente.
Puede reaccionar e inducir una entrada antes de ser atravesada. Refinarla no
elimina la trampa. Fuente: S05 00:28:44-00:33:19; S08
00:09:45-00:14:51.

### Pico de liquidez

High/low formado por velas opuestas de volumen similar y reversa inmediata en
uno de los patrones de la clase 8. La geometria exacta requiere video. Fuente:
S08 00:23:34-00:26:30.

## Entrada y gestion

### Entrada a riesgo

Orden directa en OB, imbalance o toma de liquidez, sin esperar confirmacion LTF.
Favorece fill pero suele usar stop mas amplio. Fuente: S06
00:31:54-00:43:06.

### Entrada por confirmacion

Tras reaccion en zona HTF, se espera iBOS en LTF y se opera desde una zona creada
por el desplazamiento. Fuente: S06 00:43:13-00:50:21.

### iBOS valido

En la clase 8, confirmacion que toma liquidez a la izquierda y crea liquidez a la
derecha. Fuente: S08 00:39:27-00:41:50.

### iBOS de liquidez

Rompimiento que parece confirmacion pero no satisface la construccion anterior y
puede inducir antes de crear otro rango. Fuente: S08 00:39:27-00:41:50.

### Frescura de zona

El profesor recomienda usar una zona una vez. Un OB HTF puede contener zonas LTF
diferentes, lo que explica reacciones multiples sin reutilizar exactamente la
misma zona refinada. Fuente: S07 00:57:08-01:01:04.

### Confirmacion compuesta

Conjunto de fractal, rango, tipo de OB, liquidez institucional y modelo de
entrada. No equivale exclusivamente a una vela o quiebre estructural. Fuente: S08
00:36:05-00:38:10.

## Terminos deliberadamente no congelados

- umbral exacto de `volumen suficiente`;
- tamaño minimo de FVG u OB;
- regla universal para elegir swing rector;
- invalidez superior del fractal tras superar 50%;
- rango revisado insinuado en la clase 9;
- regla de diez velas de la clase 6;
- especificacion operacional completa de la regla universal de dos entradas;
- limites cuantitativos de reentrada, parciales y break-even.

Estos elementos permanecen `U0` hasta evidencia adicional; no se rellenan con
definiciones externas.
