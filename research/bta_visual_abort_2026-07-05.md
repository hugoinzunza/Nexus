# Estudio "abort-si-no-CDC" — pareado contra el baseline touch

Fecha: 2026-07-05 · **Research only · No señal · No bot · NO usar para activar live.**

Derivado del replay OOS (`3202a62`): las zonas tocadas que LUEGO confirman CDC
rinden +0.68 vs −0.16 las que no, pero entrar en el CDC pierde (entrada tardía).
Variante causal probada acá: **entrar al toque y abortar con pérdida reducida si
el CDC no aparece en N velas**.

Universo: los **8.440 trades touch** del estudio OOS, comparación **pareada 1:1**
(misma entrada/stop/target). 10 datasets, 4 años, costos maker-aware, intrabar
conservador. Ventanas N ∈ {4,8,12,16,24} × salidas {mkt, be, cap03(−0.3R)};
si el SL/TP original toca antes de la vela N, manda el original.

Script: `research/bta_visual_abort.py` · Datos: `bta_visual_abort_results.json`.

## Tabla principal (universo completo, netR)

| Variante | ALL avg | ALL loser prom. | ALL DD (R) | OOS avg | OOS DD |
|---|---|---|---|---|---|
| **base (touch)** | −0.033 | −1.149 | 589 | −0.101 | 285 |
| mkt_4 | −0.012 | −0.869 | **312** | −0.072 | 203 |
| be_4 | −0.013 | **−0.623** | 342 | −0.084 | 234 |
| cap03_4 | −0.009 | −0.769 | 381 | −0.073 | 211 |
| be_8 | −0.008 | −0.816 | 358 | −0.067 | 205 |
| **cap03_8** | **−0.004** | −0.911 | 344 | **−0.062** | **187** |
| be_12 | −0.018 | −0.953 | 425 | −0.062 | 188 |
| N=16/24 (todas) | −0.02…−0.04 | −1.0…−1.1 | 500-580 | −0.08…−0.10 | 240-270 |

## Subconjuntos que importan

**rr≥5 (el filtro de Fase 1), todos los TF:**
| | ALL | OOS | DD ALL |
|---|---|---|---|
| base | +0.079 | **−0.065** | 146 |
| mkt_4 | +0.145 | **+0.044** | **54** |
| cap03_8 | +0.156 | −0.010 | 120 |

**1h × rr≥5 (lo más parecido al plan del bot):**
| | ALL | IS | OOS | DD ALL |
|---|---|---|---|---|
| base | +0.173 | +0.229 | +0.056 | 102 |
| mkt_4 | +0.189 | +0.250 | +0.061 | **44** |
| **cap03_8** | **+0.243** | **+0.316** | **+0.094** | 64 |

**Walk-forward rr≥5 (mkt_4 vs base):** mejora los años malos (2024 +0.02→+0.23;
2025 −0.04→+0.02; 2026 −0.14→−0.07) y ~mantiene los buenos (2022/2023).
DD por año siempre menor (2024: 146→40).

**Por par OOS rr≥5 (mkt_4):** mejora **5/7** (ADA −1.09→−0.46, BTC −0.47→−0.12,
XRP −0.45→+0.07, BNB→+0.04, ETH +0.02→+0.20) pero **devuelve casi todo el edge
de los 2 mejores** (DOGE +0.98→+0.08, SOL +0.27→+0.14): los grandes winners
tardan >4 velas en confirmar.

**Winners del baseline destruidos:** mkt_4 15.9% · cap03_8 15.7% · be_12 13.3% ·
be_4 **41%** (demasiado agresivo, descartada).

## Lectura adversarial (intenté que NO funcionara)

1. **No crea edge**: el universo completo sigue NEGATIVO en todas las 15
   variantes (mejor: cap03_8 −0.004 ALL / −0.062 OOS). El aborto es un
   **modelador de riesgo**, no una fuente de alpha.
2. **Ninguna variante domina**: mkt_4 gana en rr≥5-global y en años malos;
   cap03_8 gana en 1h×rr≥5; be_12 empata. Elegir "la mejor por subconjunto" es
   **cherry-picking** — riesgo de overfitting explícito de este estudio.
3. **El costo del seguro es real**: recorta 14-16% de los winners y cede edge en
   los pares/años donde el baseline vuela (DOGE OOS). El beneficio neto depende
   del régimen: paga en mercados que castigan (2024-2026), cobra en los que
   corren (2022-2023 apenas).
4. Lo que SÍ es robusto (todas las ventanas cortas, todos los cortes): **losers
   promedio −1.15 → −0.6/−0.9 y DD −40/65%**, con N grande (8.440 pareado,
   2.531 OOS). La dirección del efecto nunca se invierte.

## Veredicto: **candidato débil — seguir investigando, NO promover**

- Como mejora de EXPECTATIVA: débil y dependiente del subconjunto (OOS +0.09 en
  1h×rr≥5 con cap03_8, n=307; +0.04 en rr≥5 con mkt_4, n=679). Muestras
  modestas, proxy crudo, sensibilidad a (N, modo).
- Como control de RIESGO (colas y DD): hallazgo consistente y direccalmente
  robusto en todos los cortes. Es la faceta que merece seguir.
- **No** entra al bot ni a la Fase 1 (el criterio pre-registrado no se toca).

## Próximo paso propuesto (si quieres seguir)
Columna PARALELA en el Diario: para cada setup vivo del dry-run, registrar si
hubo CDC dentro de las 8 velas posteriores al toque y simular el resultado
"con aborto cap03_8" junto al real. Cuando la Fase 1 junte muestra, comparar
sobre datos forward de verdad — sin tocar el flujo del bot.

## Qué no se tocó
Bot, dry-run Fase 1, `config/nexus.json`, credenciales, VPS (sigue en 502fec5).
Todo corrió local sobre los klines ya presentes en `data/`.
