# Refugios de Mediano Plazo (RMP): la rejilla anual no se distingue de un placebo

**Fecha:** 2026-07-26 · **Estado:** `research_only` · `execution_enabled: false` · `validated: false`
**Script:** `research/refugios_anuales.py` · **Datos:** `research/refugios_anuales_results.json`
**Tests:** `research/test_refugios_anuales.py` (20/20 pasando)

---

## VEREDICTO: DESCARTAR

La rejilla `O_y * (1 ± k*0,10)` **no produce más reacción que una rejilla de igual densidad
puesta en otra parte**. Ninguno de los 12 contrastes pre-registrados contra los cuatro controles
sobrevive a Holm; de hecho ninguno llega siquiera a ser significativo sin corregir, salvo uno
cuyo signo va **en contra** de la hipótesis.

Regla de decisión pre-registrada: *DESCARTAR si no separa del placebo de igual densidad*.
Es lo que ocurrió. No se promueve a variable visible del bot.

Lo mismo vale para la **apertura semanal**: indistinguible de un precio cualquiera de la
semana anterior.

---

## 1. Qué se probó y qué no

La pregunta **no** es si el precio reacciona en esos niveles. Con 24 niveles por activo y año,
siempre reacciona en alguno. La pregunta pre-registrada es si reacciona **más** que en una
rejilla cualquiera de la misma densidad.

Y antes de eso, un número que el curso nunca publica:

| | RMP ±10% |
|---|---|
| Niveles construidos (5 pares × 4 años) | 480 |
| Niveles que el precio **nunca visitó** | 255 (53,1%) |
| Niveles visitados | 225 (46,9%) |
| Visitados que produjeron reacción | 54 |
| **Tasa incondicional de reacción** | **11,3%** |

Es decir: de cada 9 niveles de la rejilla anual, aproximadamente **uno** hace lo que el
profesor muestra en la masterclass. Los otros ocho o no se tocan, o se atraviesan sin
reaccionar. Los ejemplos del curso son ese 11%, presentados sin el denominador.

---

## 2. Diseño pre-registrado (congelado antes de mirar resultados)

| Ítem | Valor |
|---|---|
| Venue / símbolo / quote / timezone | **binance / \<PAR\>USDT / USDT / UTC** |
| Datos | snapshot versionado en `data/klines_<PAR>_1d.json` (no es un feed; ~41 días de antigüedad, esperado) |
| Universo | BTC, ETH, SOL, ADA, XRP |
| Ancla `O_y` | apertura de la vela diaria cuyo `open_time == 1-ene 00:00 UTC` |
| Rejilla | `O_y * (1 + dir*k*0,10)`, `k = 1..15`, pasos **lineales** (no compuestos) |
| Validez | del 1-ene de `y` al 31-dic de `y`. La rejilla de `y` **nunca** se evalúa sobre `y-1` |
| Tolerancia de toque | **0,25 · ATR14 previo** (nunca un % fijo) |
| Episodio | contactos separados por <5 velas son **el mismo** episodio |
| Horizonte de reacción | 5 velas diarias |
| Reacción (`hit`) | penetración ≤ 0,5 ATR **y** movimiento ≥ 1,0 ATR en sentido de respeto |
| CI | bootstrap por bloques `(activo, año, trimestre)`, 5.000 iteraciones |
| Corrección múltiple | **Holm**, α = 0,05 |
| Uso evaluado | target / parcial. **Nunca** dirección de entrada |

**Años excluidos:** 2022 en los 5 pares. El snapshot arranca el 2022-02-23 y no existe la vela
del 1-ene-2022. No se sustituyó por la primera vela disponible: eso sería fabricar el ancla.
Quedan **20 celdas ancla** (5 pares × 4 años, 2023-2026; 2026 truncado al 13-jun).

**Niveles no positivos excluidos:** con paso 10% y `k ≥ 10` hacia abajo el precio es cero o
negativo, sin significado para un activo spot.

| Familia | Excluidos | Por celda |
|---|---|---|
| RMP 10% | **120** | 6 (`k` = 10..15 bajistas) |
| Placebo 7,5% | 40 | 2 (`k` = 14, 15) |
| Placebo 12,5% | 160 | 8 (`k` = 8..15) |

Anclas por año (venue, precio y ancla desplazada) en `meta.anchors` del JSON.

---

## 3. Resultado principal

Primer contacto de cada nivel, agrupado en episodios. `n` = episodios con ventana completa.

| Familia | n | Tasa reacción | Magnitud media (ATR) | Penetración media (ATR) | Toque | Reacción incondicional |
|---|---|---|---|---|---|---|
| **RMP 10% (hipótesis)** | **225** | **0,2400** | **1,844** | 2,436 | 46,9% | **11,3%** |
| Placebo 7,5% (a) | 266 | 0,2444 | 1,773 | 2,412 | 47,5% | 11,6% |
| Placebo 12,5% (a) | 188 | 0,2128 | 2,008 | 2,404 | 42,7% | 9,1% |
| Ancla −3 días (b) | 223 | 0,2287 | 1,957 | 2,474 | 46,5% | 10,6% |
| Ancla +3 días (b) | 218 | 0,2706 | 2,017 | 2,352 | 45,4% | 12,3% |
| Aleatorio emparejado (c) | 4.438 | 0,2386 | 1,865 | 2,427 | 46,2% | 11,0% |
| Números redondos (d) | 1.117 | 0,2193 | 1,894 | 2,553 | 98,4% | 21,6% |

La rejilla real cae **en medio del rango de los controles** en todas las columnas. El ancla
desplazada +3 días —un ancla sin ningún significado— reacciona algo más que la real.

### 3.1 Contrastes pre-registrados (12 tests, Holm)

Diferencia `RMP − control`, bootstrap por bloques:

| Métrica | Control | Diff | CI 95% | p crudo | **p Holm** | Sig. |
|---|---|---|---|---|---|---|
| Tasa reacción | Placebo 7,5% | −0,0044 | [−0,0616; +0,0563] | 0,923 | 1,000 | no |
| Tasa reacción | Placebo 12,5% | +0,0272 | [−0,0333; +0,0948] | 0,407 | 1,000 | no |
| Tasa reacción | Ancla −3d | +0,0113 | [−0,0417; +0,0676] | 0,678 | 1,000 | no |
| Tasa reacción | Ancla +3d | −0,0306 | [−0,0828; +0,0287] | 0,288 | 1,000 | no |
| Tasa reacción | Aleatorio | +0,0014 | [−0,0535; +0,0578] | 0,938 | 1,000 | no |
| Tasa reacción | Redondos | +0,0207 | [−0,0395; +0,0738] | 0,535 | 1,000 | no |
| Magnitud (ATR) | Placebo 7,5% | +0,070 | [−0,116; +0,320] | 0,529 | 1,000 | no |
| Magnitud (ATR) | Placebo 12,5% | −0,164 | [−0,504; +0,085] | 0,272 | 1,000 | no |
| Magnitud (ATR) | Ancla −3d | −0,114 | [−0,262; +0,025] | 0,113 | 1,000 | no |
| Magnitud (ATR) | Ancla +3d | **−0,173** | [−0,299; −0,048] | 0,007 | 0,082 | no |
| Magnitud (ATR) | Aleatorio | −0,022 | [−0,127; +0,071] | 0,698 | 1,000 | no |
| Magnitud (ATR) | Redondos | −0,051 | [−0,418; +0,200] | 0,723 | 1,000 | no |

El único p crudo bajo (0,007) es **la rejilla real perdiendo** contra el ancla desplazada, y ni
siquiera eso sobrevive a Holm. No hay nada que promover.

### 3.2 Utilidad como target / parcial

Es el único uso que el propio curso permite ("el nivel anual no genera una entrada por sí
solo"). Métrica: `held` = el precio **no** atravesó el nivel por más de 0,5 ATR, es decir, el
nivel frenó al precio.

| Control | Diff | CI 95% | p crudo | p Holm |
|---|---|---|---|---|
| Placebo 7,5% | −0,0081 | [−0,0631; +0,0487] | 0,828 | 1,000 |
| Placebo 12,5% | +0,0219 | [−0,0369; +0,0880] | 0,499 | 1,000 |
| Ancla −3d | +0,0113 | [−0,0433; +0,0674] | 0,697 | 1,000 |
| Ancla +3d | −0,0352 | [−0,0871; +0,0207] | 0,212 | 1,000 |
| Aleatorio | −0,0040 | [−0,0562; +0,0528] | 0,903 | 1,000 |
| Redondos | +0,0198 | [−0,0383; +0,0736] | 0,542 | 1,000 |

Un RMP no frena al precio más que un nivel cualquiera. **Tampoco sirve como target.**

### 3.3 Utilidad incremental sobre pivotes y volatilidad

Logística `hit ~ is_rmp + distancia a pivote causal (ATR, z) + volatilidad relativa (z) + is_round`,
sobre 5.780 episodios de RMP + aleatorios + redondos:

| Término | Coef |
|---|---|
| `is_rmp` | **+0,0086** · CI 95% bloques **[−0,320; +0,328]** |
| distancia a pivote causal | +0,043 |
| volatilidad relativa | **+0,240** |
| `is_round` | −0,166 |

El coeficiente de "ser un refugio anual" es cero con un CI centrado en cero. Lo que **sí**
predice la reacción es la volatilidad del momento. La rejilla no aporta información propia.

### 3.4 Eventos separados (no mezclados)

RMP, por dirección de aproximación:

| Aproximación | n | Reacción | Magnitud (ATR) | Ruptura | Reclaim | Retest |
|---|---|---|---|---|---|---|
| Desde arriba (soporte) | 56 | 0,393 | 2,475 | 0,339 | 0,588 | 0,824 |
| Desde abajo (resistencia) | 169 | 0,189 | 1,634 | 0,586 | 0,515 | 0,798 |

La asimetría soporte/resistencia es real y grande, pero **aparece idéntica en todas las
familias, incluido el control aleatorio** (soporte 0,270 vs resistencia 0,228). Es una propiedad
del mercado, no del nivel anual. Nótese además: **el 52,4% de los primeros contactos termina en
ruptura** y el 80,2% en retest. "Como un reloj" no describe estos datos.

---

## 4. La trampa del corte por `k` (y cómo se desactivó)

El barrido exploratorio por nivel (20 celdas, `±10%` a `±150%`) produce un aparente ganador:

> **−40%**: 7 reacciones de 9 contactos (tasa 0,778 vs base 0,239), p crudo = 0,00099,
> **p Holm = 0,0199 → sobrevive a Holm.**

Sin auditarlo, esto se publicaría como "el nivel −40% sí funciona". Es falso, por dos razones:

1. **El ancla sin significado produce la misma celda.** Corriendo el barrido idéntico sobre los
   controles:

   | Familia | Celdas | p crudo mínimo | Celdas que sobreviven Holm |
   |---|---|---|---|
   | RMP 10% | 20 | 0,00099 (−40%: 7/9) | **−40%** (p Holm 0,020) |
   | Ancla **−3 días** | 20 | **0,00029** (−40%: 8/10) | **−40%** (p Holm 0,006) |
   | Placebo 7,5% | 22 | 0,0157 | ninguna |
   | Placebo 12,5% | 17 | 0,0157 | ninguna |
   | Ancla +3 días | 20 | 0,0224 | ninguna |

   Un ancla movida tres días —que no es la apertura anual de nada— reproduce el mismo "nivel
   mágico" con un p **más chico**. Lo que mide la celda `−40%` no es el ancla: es "la primera
   vez en el año que el precio cae 40% bajo donde abrió", o sea un drawdown profundo, que es
   otra cosa.

2. **Los 9 episodios no son independientes.** Cinco caen en feb-2025 y feb-2026, en activos
   distintos: es el mismo evento de mercado contado cinco veces. El test binomial por celda
   asume independencia y no la hay; por eso el análisis primario usa bootstrap por bloques
   `(activo, año, trimestre)`, que sí la absorbe.

Este es exactamente el mecanismo que fabrica los ejemplos de la masterclass.

---

## 5. Apertura semanal

Semana **Binance UTC** (lunes 00:00 UTC). No se usó la semana de Londres de los ejemplos del
curso: se mueve con DST y haría el nivel irreproducible. Barras de 1h, se saltan las primeras
24 h porque el precio toca la apertura por definición al abrir la semana. Control: un precio
aleatorio de la semana anterior.

| Familia | n | Tasa reacción | Magnitud (ATR) | Ruptura |
|---|---|---|---|---|
| Apertura semanal | 820 | 0,2451 | 2,135 | 0,577 |
| Precio aleatorio semana previa | 631 | 0,2441 | 1,997 | 0,609 |

| Métrica | Diff | CI 95% | p crudo | p Holm |
|---|---|---|---|---|
| Tasa reacción | +0,0011 | [−0,0446; +0,0447] | 0,967 | 0,967 |
| Magnitud (ATR) | +0,138 | [−0,013; +0,287] | 0,074 | 0,148 |

Sin diferencia. La magnitud roza el borde sin corregir y muere con Holm; con dos tests, no es
evidencia de nada.

---

## 6. Por activo (exploratorio)

30 contrastes de tasa de reacción (5 pares × 6 controles). **Uno** con p crudo < 0,05
(ETH vs placebo 7,5%, p = 0,024). **Cero** sobreviven a Holm (p Holm 0,72).

Es el mismo patrón del estudio de fuerza relativa: sin corregir aparecen cosas, con Holm no
queda nada.

---

## 7. Limitaciones (honestas)

1. **Esto no prueba que el efecto sea cero.** Prueba que, si existe, es menor que la
   resolución del estudio: el CI de la diferencia de tasa contra el control aleatorio es
   ±5,6 puntos porcentuales y el de magnitud ±0,10 ATR. Un edge más chico que eso no sería
   detectable con 20 anclas.
2. **Solo 20 celdas ancla** (5 pares × 4 años). Es lo que permite el snapshot: 2022 no tiene
   1-ene y 2026 está truncado al 13-jun. Los 6.675 episodios son muchos, pero descansan sobre
   pocas anclas independientes, y los pares cripto están fuertemente correlacionados entre sí:
   el bootstrap por bloques mitiga esto, no lo elimina.
3. **Régimen único.** 2023-2026 en cripto es esencialmente un ciclo. No hay evidencia sobre
   otros regímenes ni sobre índices, donde el curso también aplica la idea.
4. **Un solo horizonte (5 velas) y una sola tolerancia (0,25 ATR).** Están pre-registrados y
   no se barrieron. Hacer sensibilidad ahora abriría los grados de libertad que este estudio
   existe para cerrar; si se quiere, es un experimento aparte con su propio pre-registro.
5. **Discontinuidad del control de números redondos.** El paso se deriva de los datos
   (`10^(floor(log10 precio)−1)`), lo que hace que BTC-2025 use 10.000 y BTC-2026 use 1.000,
   o SOL 10 en 2025 y 1 en 2026. Es feo, pero ajustarlo **después** de ver los resultados es
   precisamente lo que se le critica al curso. Queda documentado tal cual.
6. **No se probó confluencia** (RMP + pivote). Es un experimento separado y requiere su propia
   tolerancia pre-registrada. Nada aquí lo autoriza.
7. **Percentiles walk-forward del rango anual**: no se calcularon porque son inestimables. Con
   solo 3 años completos anteriores no hay muestra para percentiles; reportar uno sería inventar
   precisión. Esto **no** valida las horquillas del curso (S&P 20-30%, Nasdaq 30-45%, BTC
   70-130%): siguen sin periodo, muestra ni percentiles, y no deben usarse.
8. **Un venue.** Binance spot USDT UTC. Bitstamp, Coinbase o el índice de TradingView dan
   aperturas anuales distintas y por lo tanto rejillas distintas. El estudio no dice nada sobre
   ellas.

---

## 8. Qué hacer con esto

- **No** promover `annual_open_levels` a variable visible ni a señal.
- **No** usarlo como target ni como parcial: el test de `held` es plano.
- El único uso defendible que queda es **descriptivo**: mostrar la distancia al siguiente nivel
  como contexto en la UI, con la etiqueta explícita de que no tiene poder predictivo medido.
  Incluso eso es opcional y no cambia ningún gate.
- No se tocó el bot, el dry-run, los kill-switches ni nada en `config/`, `core/`, `modules/` o
  `data/`. Todo el output es `research_only` con `execution_enabled: false`.

**Un resultado negativo bien medido es un entregable. Este lo es.**
