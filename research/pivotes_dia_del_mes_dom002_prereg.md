# PIVOT-DOM-002 — Confirmación del día 25 en mínimos (pre-registro)

**Método congelado el 2026-08-15 ANTES de computar sobre el set de confirmación.**
`research_only` · sin señal · sin bot.

## Hipótesis ÚNICA

Los **mínimos estructurales** (pivotes low confirmados) se concentran en el
**día 25 del mes (UTC)** más de lo esperable por azar. Nada más se testea; el
resto de la tabla se publica solo por transparencia.

Origen: hallazgo exploratorio de DOM-001 en BTC spot 2017-2026 (p=0,0013 en su
brazo, consistente en ambas definiciones de pivote y ambas mitades). Mecanismo
candidato: expiración mensual de opciones (último viernes, típicamente 24-28).

## Set de confirmación y su honestidad

**ETH, SOL, ADA, XRP, DOGE, BNB** — futuros 1d, 2022-02 → 2026-06 (~1.573 velas
c/u), datos que DOM-001 no tocó. BTC queda EXCLUIDO (su período está dentro del
descubrimiento).

**Limitación declarada:** las alts co-mueven con BTC, así que esto es
**replicación en forma débil** — seis símbolos no son seis experimentos
independientes. Se compensa en la inferencia (abajo) y se declara que la
confirmación fuerte solo la dará el forward.

## Test congelado

- Pivotes 5+1+5 (primario) y 3+1+3 (secundario publicado); solo lows.
- **Estadístico:** total de lows en día 25 sumado sobre los 6 activos.
- **Nulo por rotación CONJUNTA:** un mismo corrimiento de k días de calendario
  aplicado simultáneamente a los 6 activos (k uniforme en [30, 1400], 4.000
  repeticiones, semilla 13). Preserva el espaciamiento de pivotes de cada
  activo Y el co-movimiento entre activos; destruye solo la alineación con el
  día del mes. Así la dependencia cruzada no infla la significancia.
- **p unilateral:** fracción de rotaciones con total ≥ observado.

## Criterio de lectura, congelado

**La replicación débil se supera solo si:** p < 0,05 **y** al menos 4 de los 6
activos muestran obs > esperado individualmente. Cualquier otro resultado =
no replica, y el día 25 vuelve al cajón del ruido.

Aunque pase: esto NO habilita uso operativo. Habilita únicamente el brazo
forward, registrado ahora: **mínimos de BTC desde 2026-08-16**, evaluación
cuando se acumulen ≥50 lows nuevos (~2 años), mismo test. Hasta entonces es
monitoreo descriptivo sin poder estadístico, y se declara así.

## Predicción registrada

Si el mecanismo de expiración es real, debería verse en las alts (es de mercado
completo). Prior general escéptico: la casa lleva 4 estudios de
calendario/niveles y ninguno superó su control. 50/50 honesto.

---

## Resultados (2026-08-15, posteriores al freeze — `pivotes_dia_del_mes_dom002.py`)

### Primario (5+1+5, el que decide)

| Activo | lows | día 25 obs | esperado | |
|---|---:|---:|---:|---|
| ETH | 109 | 7 | 3,6 | ↑ |
| SOL | 91 | 3 | 3,0 | ↑ |
| ADA | 105 | 6 | 3,5 | ↑ |
| XRP | 103 | 5 | 3,4 | ↑ |
| DOGE | 104 | 7 | 3,4 | ↑ |
| BNB | 100 | 4 | 3,3 | ↑ |
| **TOTAL** | | **32** | **20,1** | **p conjunta = 0,0757** |

Elevados: **6/6**. Criterio congelado: p<0,05 **y** ≥4/6. → **NO REPLICA**
(la p conjunta falla; 0,076 > 0,05).

### Secundario (3+1+3, publicado, no decisivo)

Total 51 vs 32,9 esperado, p=0,0403, 6/6 elevados — habría pasado, pero el
criterio se congeló sobre el primario y así se lee.

### Lectura honesta

- La **dirección** es unánime: 12 de 12 brazos entre DOM-001 y DOM-002 muestran
  elevación del día 25 en mínimos, y los 6 activos individualmente. Eso no es
  común en ruido puro.
- Pero la rotación conjunta —que existe justamente para que el co-movimiento
  cripto no fabrique replicaciones— deja la p primaria en 0,076. Un test
  ingenuo por activo habría "confirmado" fácil; ese test habría estado mal.
- **Veredicto formal: no replica.** El día 25 queda como candidato con
  dirección consistente y significancia insuficiente — exactamente el tipo de
  señal que el brazo forward registrado (BTC, ≥50 lows desde 2026-08-16,
  evaluación ~2028) tiene que dirimir. Hasta entonces: sin señal, sin uso
  operativo, sin excepciones.
