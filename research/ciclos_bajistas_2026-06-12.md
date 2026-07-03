# Anatomía de los ciclos bajistas de BTC — ¿dónde estamos en el bear actual?

**Fecha:** 2026-06-12 · **Worktree:** `research-smc-filtros`
**Objetivo:** medir objetivamente los bear markets históricos de BTC, normalizarlos y
ubicar el ciclo actual para decidir, con datos, si el bear luce maduro (cerca de fondo)
o joven (peligroso para largos de swing). **No predecir; encuadrar.**

---

## 1. Resumen ejecutivo (para Hugo)

El bear actual está **maduro en tiempo y en RSI, pero todavía SOMERO en precio**. No luce
como un fondo de capitulación clásico todavía, pero tampoco es "joven": va por la fase
tardía. Traducción para largos de swing: **aún no es el momento de ponerse alcista de
cabeza; conviene esperar o un flush más profundo o confirmación de estructura.**

Las tres señales, sin maquillar:
- **Por drawdown (precio): JOVEN/incompleto.** Hoy −49% (mínimo −51%) desde el ATH. Los 3
  fondos de ciclo previos fueron **−77% a −85%**. El drawdown actual es apenas el **~59%
  de la profundidad mediana** de un fondo. Si este ciclo respetara la profundidad histórica,
  faltaría caída.
- **Por tiempo: MADURO (mitad-tardía).** Llevamos **36 semanas** desde el techo; los bears
  de ciclo tocaron fondo a las **52–58 semanas** (mediana 54). Vamos en el **~66%** del
  tiempo típico.
- **Por RSI mensual: MADURO.** El RSI mensual está en **43**, justo dentro de la zona de
  fondos históricos (**41–49**). Por este indicador, ya estamos en "terreno de fondo".

El matiz clave (honesto): hay un **patrón de fondos cada vez menos profundos** (−85% →
−83% → −77%). Si continúa, este ciclo podría fondear más arriba (zona −55%/−65%, ≈
$44k–$56k), y entonces el −51% actual estaría *cerca* pero no del todo. Pero son **solo 3
casos** — la dispersión en profundidad es real y esa "tendencia" puede romperse.

**Veredicto:** bear **tardío pero sin capitulación de precio confirmada**. RSI y tiempo
dicen "ya casi"; el drawdown dice "todavía no como antes". Para swing: **paciencia** —
buscar largos recién con un barrido más profundo hacia −60%+ **o** con confirmación
(recuperar estructura/MA), no anticipando el fondo.

---

## 2. Metodología

**Datos.** BTC/USD diario desde **2013-01** (Bitstamp, `research/btc_longhistory.py`),
4.911 barras. Bitstamp es de las series USD continuas más antiguas y **captura el ATH de
2013** que Yahoo (parte 2014-09) se pierde.

**Detección objetiva de bears (sin hardcodear fechas).** Se marca un bear cuando el precio
cae **>55%** bajo el ATH vigente; el **fondo** es el mínimo hasta que el precio recupera ese
ATH (nuevo ciclo). Un episodio se considera **bear de CICLO** si dura ≥40 semanas; los más
cortos son **correcciones intra-bull** (p. ej. el −71% de abr-2013 en 13 semanas) y quedan
fuera de la referencia. El **ciclo actual** se mide aparte: del ATH global (oct-2025) a hoy,
sin depender del umbral (el bear está incompleto).

**Métricas por bear:** techo (fecha/precio), fondo (fecha/precio), drawdown máximo,
duración techo→fondo, y **RSI mensual (14)** en el fondo. Trayectorias normalizadas a
tiempo ∈ [0,1] (0=techo, 1=fondo) y precio = % del ATH, para superponerlas.

**Muestra:** solo **3 fondos de ciclo** previos → esto da **rango/referencia, no
predicción**. La dispersión se reporta explícita.

---

## 3. Los bears históricos (objetivo)

| tipo | techo | fondo | ATH $ | fondo $ | DD máx | semanas | RSI mens. fondo |
|---|---|---|---|---|---|---|---|
| corrección | 2013-04-09 | 2013-07-06 | 229 | 66 | −71% | 13 | — |
| **CICLO 1** | 2013-12-04 | 2015-01-14 | 1.132 | 171 | **−85%** | 58 | 49 |
| **CICLO 2** | 2017-12-16 | 2018-12-15 | 19.188 | 3.180 | **−83%** | 52 | 45 |
| **CICLO 3** | 2021-11-08 | 2022-11-21 | 67.559 | 15.766 | **−77%** | 54 | 41 |

**Referencia de fondos de ciclo (n=3):**
- **Drawdown:** −77% a −85% (mediana **−83%**)
- **Duración techo→fondo:** 52 a 58 semanas (mediana **54**)
- **RSI mensual en el fondo:** **41 a 49**
- **Patrón:** drawdowns **decrecientes** −85% → −83% → −77% (cada fondo, algo menos profundo).

La consistencia es alta en **duración** (52–58 sem) y en **RSI de fondo** (41–49), y algo
menor en **profundidad** (rango de 8 puntos, con tendencia a la baja).

---

## 4. El ciclo actual (oct-2025 → hoy)

| métrica | valor | referencia histórica | lectura |
|---|---|---|---|
| Techo | 2025-10-06 · $124.728 | — | — |
| Hoy | 2026-06-12 · $63.312 | — | — |
| **Drawdown actual** | **−49%** (mín −51% el 2026-06-06, $60.859) | −77%..−85% | **somero** (59% del fondo mediano) |
| **Tiempo transcurrido** | **36 sem** (249 días) | 52..58 sem | **66%** del tiempo típico |
| **RSI mensual hoy** | **43** | 41..49 (fondos) | **en zona de fondo** |

Dos lecturas conviven y por eso el veredicto es matizado:
- **Drawdown** dice que falta (−49% vs −77/−85% históricos).
- **Tiempo y RSI** dicen que ya estamos en la ventana de fondo (66% del tiempo, RSI 43∈[41,49]).

Si pesa el **patrón de drawdowns decrecientes**, un fondo en −55%/−65% (≈ $44k–$56k) sería
coherente, y el −51% actual estaría *acercándose*. Si pesa la **profundidad histórica**,
hay riesgo de otra pata bajista. Con n=3 no se puede zanjar; ambas quedan abiertas.

---

## 5. Trayectorias normalizadas superpuestas

% del ATH (eje vertical, 100% = techo) vs tiempo normalizado techo→fondo típico.
`1`=2013-12→2015-01 · `2`=2017-12→2018-12 · `3`=2021-11→2022-11 · `A`=actual · `*`=solape.

```
 100% |*
  95% |A A
  89% | * A
  84% |  * A
  79% | *  *A3 AA    A
  74% |     **A1 AAAA A
  68% |        33      A  33         A
  63% |  1      *   3  33    *3  AAAA AAA
  58% |     2     **1 3 AAAAA **A 1 11
  52% |      2    1       22     1    1 1AA
  47% |        2   22 1 1    2   33 33  211 1
  42% |               212 11 122      2      2      1
  36% |                2         22 22   ** ** *** 22 **1
  31% |                               3 3       33 *3 33* *
  26% |                                                    *3
  21% |                                                   222
  15% |                                                     1
  10% |                                                        
      +--------------------------------------------------------
       techo                                          fondo típico→
```

**Cómo leerlo:** los 3 bears de ciclo (1/2/3) descienden hasta el 15–31% del ATH al llegar
al fondo (derecha). La curva **A** (actual) está, en su porción de tiempo (~66%, hacia el
centro), **claramente más arriba** (~55–63% del ATH) de donde los bears previos ya estaban
en ese mismo punto temporal. Visualmente: **el bear actual va "menos caído" que los
anteriores a esta altura del calendario** — confirma el diagnóstico de drawdown somero.

---

## 6. Veredicto honesto y limitaciones

- **¿Maduro o joven?** **Tardío, pero sin capitulación de precio.** Tiempo (66%) y RSI
  mensual (43, en zona de fondo) dicen "fase final de bear"; el drawdown (−49/−51% vs
  −77/−85%) dice "todavía no tan profundo como los fondos previos". No es un fondo
  confirmado; tampoco es temprano.
- **Para largos de swing:** **no anticipar el fondo.** La evidencia no respalda ponerse
  alcista de cabeza al −49%. Lo prudente: esperar (a) un flush más profundo hacia −60%+
  (acercándose a la zona de fondos), o (b) confirmación estructural (recuperar niveles/MA,
  cambio de carácter en TF alta) antes de buscar swing largos. Esto calza con la
  preocupación de Hugo: no ponerse alcista antes de tiempo.
- **Limitaciones (sin maquillar):**
  - **n=3.** Es referencia, no probabilidad. La dispersión en profundidad es real.
  - **No estacionariedad / régimen distinto:** halving, ETFs spot, BTC como activo macro
    correlacionado con SPX (corr 0.5) → este ciclo puede fondear más somero (tesis de
    rendimientos decrecientes) o comportarse distinto a 2015/2018.
  - El **mínimo actual ($60.859) es de hace días**; el bear sigue **abierto**, así que su
    "fondo" y duración finales aún no existen — todo lo de arriba es estado parcial.
  - El RSI mensual de junio usa un mes **incompleto** (cierre al 12-jun); puede moverse.

---

## 7. Archivos (worktree `research-smc-filtros`)

- `research/btc_longhistory.py` — BTC/USD diario desde 2013 (Bitstamp), cacheado.
- `research/bear_cycles.py` — detección objetiva de bears, métricas, RSI mensual,
  trayectorias normalizadas y overlay ASCII → `research/bear_cycles.json`.
- `research/ciclos_bajistas_2026-06-12.md` — este informe.

**Cómo correrlo:** `/Users/hugh/crisol/nexux/.venv/bin/python research/bear_cycles.py`
