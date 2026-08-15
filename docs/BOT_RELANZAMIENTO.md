# Runbook — relanzamiento del bot (Fase 1 V2)

**Guía oficial.** La operación sigue en `live:false`: solo dry-run, sin órdenes
reales. La Fase 1 V2 empieza con un modelo de fill causal y conserva la Fase 1 V1
como archivo separado.

## Cierre Fase 1 V2 (2026-07-28)

Fase cerrada por decisión explícita con el bot real aún apagado:

- 20 trades dry cerrados, 75% WR, +91,81 USD simulados y +0,3851R neto promedio.
- Cero posiciones reales durante el cierre; `live:false`.
- El trade 20 (`ADAUSDT short`) ya había tomado 50% en TP1. El remanente se cerró
  manualmente al mark de Binance (`0,1649`) para congelar la muestra: +1,8235R
  bruto y +29,2337 USD netos en ese trade.
- El cierre se conserva etiquetado como manual de fin de fase; no se presenta como
  TP completo ni como salida automática.
- El dry-run quedó detenido con `data/bot_kill`.
- La siguiente etapa es Binance Demo/Testnet con ejecución virtual aislada. No
  autoriza por sí sola el regreso de la cuenta real a `live:true`.

### Reconciliacion posterior del libro (2026-08-12)

La fuente canonica del VPS confirma 20 V2 cerradas y `+91,8131 USD`; su SHA-256
es `ff389904de6bbe74527ec6d9bad5e68c88ca6cc9997fe0a0a81fb41d16e19986`. El corte alternativo de 13
operaciones y `+44,30 USD` corresponde exactamente a las primeras 13 filas cerradas
del mismo libro. La tabla completa y sus limites quedaron fijados en
`docs/BOT_PHASE1_V2_CANONICAL_RECONCILIATION.md`.

La reconciliacion tambien confirma que el riesgo ejecutado no fue homogeneo: vario
entre `6,69` y `17,95 USD`; el trade 20 uso `17,95 USD`. Por ello este cierre no debe
describirse como una cohorte uniforme de `9 USD`, ni utilizarse como prueba de edge.

## Rollover Fase 1 V1 -> V2 (2026-07-18)

La primera muestra dry cerró con 16 trades, 37.5% WR, -0.305R neto promedio,
-$39.37 y $35.56 en costos. No se usa para aprobar live porque el Diario V1
activaba al tocar cualquier borde del POI, pero atribuía el fill al midpoint.
La auditoría de velas de Binance confirmó casos ganadores donde el midpoint nunca
se negoció después de la activación.

Fase 1 V2 corrige la medición:

- `entry_model: midpoint_touch_v2` y `phase_id: phase1_v2_2026-07-18` en cada setup nuevo.
- Una entrada long solo activa al cruzar causalmente el midpoint desde arriba; una
  short, desde abajo. Si el plan nace después del cruce, primero debe rearmarse.
- `activation_price` registra el precio observado que causó la activación.
- Los V1 cerrados se preservan. Los V1 pendientes se archivan como `anulada`; un V1
  activo se deja terminar con sus reglas originales.
- Diario y panel del bot separan V2 de V1. El P&L dry se mide con el resultado neto
  real del BotStore, no con el `result_r` teórico del Diario.
- El criterio no cambia: primero de >=20 trades V2 o 3 semanas, avgR neto >+0.2R y
  WR >=55%. El reloj y el contador comienzan con el primer trade V2.

## Dónde corre qué (no confundir máquinas)

| Máquina | Rol | Repo | Comandos que van aquí |
|---|---|---|---|
| **[LOCAL]** Mac de Hugo | edición + git push | `~/crisol/nexux` | editar config, commit, push |
| **[VPS]** `nexux-de` (`ssh hugo@49.13.85.184`) | **instancia real** (systemd `nexus.service`, WorkingDirectory `/home/hugo/Nexus`) | `~/Nexus` | pull, restart, kill-switch, verificaciones |

El kill-switch es el archivo **`/home/hugo/Nexus/data/bot_kill`** (solo en el VPS;
`data/` no viaja por git — no buscarlo en la copia local). Su chequeo es dinámico:
crear/borrar el archivo surte efecto al instante, sin restart.

## Por qué está pausado
El libro REAL dio 37% win / −$129 vs 61% del paper. La 2a auditoría (Fable 5,
2026-07-04) mostró que el gap es **selección, no ejecución**: el bot estaba
configurado solo con BTC/ETH y cazó 23/27 setups 1h-long — el rincón plano de la
estrategia (en paper ese perfil da +0.012R, ~cero edge). El slippage NO causó las
pérdidas (los ganadores reales tuvieron +0.23% de slippage vs +0.06% los perdedores;
solo 4/27 trades cambiaron de resultado por fills).

## Ajuste de Fase 1 (decisión Hugo, 2026-07-04)
Config para el dry-run, validada en Diario (191) + backtest 4 años (6.263 trades reales,
IS/OOS/walk-forward, neto de costos):
- **`entry_profiles: [{ min_rr: 5 }]`** — piso rr≥5 GLOBAL. Se quitó el combo
  `4h/1D-o-short` porque OOS **no batía** a rr≥5 solo (overfitting). La regla
  "evitar 1h-long" se **refutó OOS** en los 3 datasets (1h-long rr≥5 da +0.11 a +0.74).
- **pairs ampliado** a `BTC, ETH, SOL, ADA, XRP` — los 3 nuevos tienen edge OOS propio
  (SOL el mejor, +1.0R; BTC el peor, +0.66R). Ataca la causa real del gap: diversificar
  fuera de BTC-only. `max_positions` sigue en **2** (tope intacto; solo hay más candidatos).
- **`max_entry_slippage_pct: 0.3`** se mantiene como **higiene**, no como edge.
- **`quality_require_disc: false`** (auditoría visual 2026-07-05): el `disc_ok`
  global queda FUERA del gate. Mide premium/descuento contra el **EQ GLOBAL** del
  dealing range, y como veto contradice la evidencia en 3 datasets (dealing_range
  06-12: empeora OOS; ya se había quitado de la capa de plan; Diario: disc_ok=False
  dio **+0.460R** con 73% WR vs +0.094R con True). El profe mide premium/discount
  **LOCAL por pierna** (fib 0/0.5/1 del swing), y eso ya viene validado dentro de
  `detect_pois` al formar el POI. Semántica corregida en `executor._quality`:
  `require_disc=false` = ignorar `disc_ok` por completo (incluso False).
  **El filtro real de Fase 1 es RR>=5 (+pares +slippage), no la disciplina global.**
- El sesgo SHORT del 1er análisis era **régimen** (jun–jul bajista): en 4 años OOS
  long ≈ short. No se privilegia short.
> ⚠️ El backtest está **anotado** (rr planificado mediana 10.9, TPs lejanos → posible
> look-ahead): sus números ABSOLUTOS no son promesa. Se usó solo para orden RELATIVO y
> estabilidad OOS. El criterio de go-live es la Fase 2 medida en dry-run REAL, no el backtest.

---

## FASE 0 — Preflight (checklist ANTES de quitar el kill)

Correr TODO en **[VPS]** (`ssh hugo@49.13.85.184; cd ~/Nexus`). Si algún check
falla, NO seguir.

```bash
# 0.1 — cero posiciones reales en la subcuenta (GET read-only):
.venv/bin/python3 -c "
from modules.bot.executor import _trade_creds
from modules.trading.binance_account import BinanceFutures
k,s=_trade_creds(); cli=BinanceFutures(api_key=k, api_secret=s)
pos=[p for p in cli.positions() if abs(float(p.get('positionAmt') or 0))>0]
print('POSICIONES:', pos or 'NINGUNA ✓')"

# 0.2 — live:false en el config DEL VPS (para dry-run debe decir false):
grep -n '"live"' config/nexus.json          # esperado: "live": false

# 0.3 — filtros activos en config:
grep -n 'entry_profiles\|max_entry_slippage' config/nexus.json   # deben existir

# 0.4 — rama/commit desplegado = origin/main, árbol limpio:
git fetch origin -q && git status -sb | head -2   # esperado: ## main...origin/main (sin ahead/behind)
git log -1 --pretty='%h %s'

# 0.5 — servicio correcto en systemd:
systemctl is-active nexus.service                  # esperado: active
sudo systemctl show nexus.service -p WorkingDirectory   # esperado: /home/hugo/Nexus

# 0.6 — logs limpios (sin tracebacks recientes):
journalctl -u nexus.service --since "15 minutes ago" --no-pager | grep -iE "traceback|error" | tail -5
# esperado: nada (o solo errores conocidos de red transitorios)

# 0.7 — BTA sigue fuera del bot (guard paper_only presente):
grep -n 'paper_only' modules/bot/executor.py | head -2   # el guard debe existir en _open
```

---

## FASE 1 — Iniciar DRY-RUN (2–3 semanas)

```bash
# [LOCAL] 1) poner live:false y subirlo:
cd ~/crisol/nexux
#    editar config/nexus.json → "live": false
git add config/nexus.json && git commit -m "bot: dry-run Fase 1" && git push

# [VPS] 2) traer el cambio:
cd ~/Nexus && git pull

# [VPS] 3) correr el PREFLIGHT completo (Fase 0). En particular 0.1 y 0.2.

# [VPS] 4) restart CON el kill todavía puesto (orden seguro: nunca hay un momento
#          live:true sin kill). El restart carga live:false + los filtros nuevos:
sudo systemctl restart nexus.service && sleep 10 && systemctl is-active nexus.service

# [VPS] 5) verificar que el proceso cargó dry-run + filtros:
curl -s http://localhost:8800/m/bot/api/state | .venv/bin/python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('live:', d.get('live'), '| kill:', d.get('kill'))"
# esperado: live: False | kill: True

# [VPS] 6) SOLO si el paso 5 dio live:False → quitar el kill (arranca el dry-run):
rm ~/Nexus/data/bot_kill

# [VPS] 7) verificar dry-run activo:
curl -s http://localhost:8800/m/bot/api/state | .venv/bin/python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('live:', d.get('live'), '| kill:', d.get('kill'))"
# esperado: live: False | kill: False
```

El bot simulará (mode=dry) con los filtros. El P&L dry se ve **separado** en el
panel (`summary().by_mode`); no se mezcla con el P&L live histórico.

## FASE 2 — Criterio de decisión (pre-registrado; NO moverlo después)

> **Qué puede y qué NO puede certificar esta fase** (auditoría 2026-07-24).
> El umbral original se mantiene sin tocar, pero hay que ser honesto sobre su
> alcance: **con 20 trades no se puede distinguir éxito de fracaso.** Con un 70%
> observado sobre n=20, el intervalo de confianza inferior del win rate es 48% —
> bajo el umbral de 55%. Se necesitan ~50 trades para separarlos. Y con la
> muestra de hoy (n=7, 71%) el IC es [36%, 92%] y el del avgR [−0.41, +1.09],
> o sea contiene el cero.
>
> Por eso la Fase 2 se lee como **PUERTA DE SEGURIDAD**, no como prueba de edge:
> - **¿Está roto?** Eso sí lo responde una muestra chica: fills absurdos, SL que
>   no dispara, slippage sistemático, idempotencia, reconciliación, doble
>   apertura. Con 20 trades se ve.
> - **¿Tiene edge?** Ninguna muestra que se junte en 3 semanas lo responde. Esa
>   pregunta queda **explícitamente abierta** después de la Fase 2.

Tras **≥20 trades dry o 3 semanas** (lo primero que ocurra):
- avgR neto > **+0.2R** **Y** win rate ≥ **55%** → la puerta de seguridad pasa.
- Si no cumple → NO activar live; volver a analizar.

**Regla dura de muestra (agregada 2026-07-24, no reemplaza lo anterior):**
- Si a las 3 semanas hay **menos de 20 trades cerrados**, la respuesta es
  **"seguir midiendo"**, nunca "evaluar con lo que haya". El reloj no habilita
  una decisión sin muestra.
- Al reportar el resultado, publicar el **intervalo de confianza** del win rate
  y del avgR junto al estimador puntual. Un punto sin intervalo no es evidencia.
- Ningún resultado de la Fase 2 debe describirse como "la estrategia funciona".
  Como máximo: "no se detectaron fallas de ejecución en n trades".

## FASE 3 — LIVE (solo si Fase 2 pasó)
```bash
# [LOCAL] config/nexus.json → "live": true ; commit + push
# [VPS]   preflight Fase 0 completo (0.2 ahora espera true) y:
cd ~/Nexus && git pull && sudo systemctl restart nexus.service   # SOLO con 0 posiciones
```
Sizing vigente: base 450, riesgo 2%, min_margin 250, cap 8%/orden, tope diario 15%.

### Gate Testnet por escenarios (2026-08-12)

Un contador de cinco trades no prueba los caminos peligrosos. Antes de cualquier
revision para live deben existir artefactos verificables de estos cinco escenarios en
Binance Demo/Testnet:

1. apertura con stop nativo confirmado por Binance;
2. parcial con stop reajustado exactamente al remanente;
3. stop nativo disparado realmente y posicion cerrada;
4. reinicio del proceso con reconciliacion completa entre exchange y libro;
5. timeout ambiguo resuelto en HEDGE sin duplicar orden ni mezclar lados.

Cada escenario requiere `status=passed`, timestamp y referencia a evidencia. El
numero de operaciones cerradas se publica como contexto, pero no sustituye este gate.
Completar los cinco escenarios solo habilita revision humana de la maquinaria; no
demuestra rentabilidad y nunca activa live automaticamente.

Un sexto escenario queda pre-registrado como opcional y no bloqueante: cancelar en
Demo el stop nativo de una posicion, dejar que cruce el SL y acreditar el cierre de
emergencia efectuado por `nexus-watchdog` de punta a punta. Hasta ejecutarlo, el
watchdog es un respaldo operativo condicionado, no una defensa verificada por este gate.

La evidencia economica posterior se rige por `ECON-COHORT-001`: 50 cierres exactos o
`2026-10-10 04:30 UTC`, lo primero que ocurra, con una unica evaluacion al cierre. La
configuracion completa queda congelada; cualquier cambio inicia una cohorte nueva.

---

## ROLLBACK / EMERGENCIA

```bash
# PAUSAR YA (bloquea aperturas al instante, sin restart, no cierra nada):
ssh hugo@49.13.85.184 'touch ~/Nexus/data/bot_kill'
#   (equivalente: botón "Parar bot" en https://nexux.cl/m/bot/)

# Restaurar live:true/false → SIEMPRE por config + git (no editar a mano en el VPS):
#   [LOCAL] editar config/nexus.json → commit/push; [VPS] git pull + restart con kill puesto.

# Verificar que NO abrió nada:
#   1) posiciones reales (comando 0.1 del preflight) → NINGUNA
#   2) libro: último trade y su fecha:
ssh hugo@49.13.85.184 '.venv/bin/python3 -c "
import json,datetime
d=json.load(open(\"/home/hugo/Nexus/data/bot_trades.json\"))
t=max(d,key=lambda x:x.get(\"opened_at\") or 0)
print(t[\"pair\"],t[\"dir\"],t[\"mode\"],datetime.datetime.fromtimestamp(t[\"opened_at\"]))"' 2>/dev/null

# Qué logs mirar (todas las decisiones del bot dicen "bot:"):
ssh hugo@49.13.85.184 'journalctl -u nexus.service --since "1 hour ago" --no-pager | grep "bot:" | tail -20'
#   aperturas: "bot: ... abrió" · saltos de filtro: "no calza los entry_profiles",
#   "precio ya se alejó del plan" · kill: "KILL-SWITCH activo"
```

## Notas
- Sesgo SHORT: la 2a auditoría lo confirmó como **régimen** (jun–jul bajista). En 4 años
  OOS long ≈ short (+0.80 vs +0.80). No se privilegia ninguna dirección.
- `rr≥5` es piso conservador: en el Diario separó fuerte (OOS +0.33 vs −0.28 rr<5); en el
  backtest la mejora es leve (+0.80 vs +0.61). No es el origen del edge, es higiene.
- Graduador de Claude anti-predictivo in-sample: NO usarlo como gate.
- BTA sigue en research (`paper_only`); no llega al bot.
- Alcance actual: cerrar primero Fase 1 dry-run/filtros del bot. Las mejoras visuales
  del gráfico/indicador (premium-discount local por pierna, CDC escalera, estados de
  zona, targets de liquidez) quedan para una tarea separada después.
