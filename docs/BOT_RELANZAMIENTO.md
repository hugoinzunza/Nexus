# Runbook — relanzamiento del bot (tras auditoría 2026-07-04)

**Guía oficial.** Estado al escribir: bot **PAUSADO** (kill-switch activo en el VPS),
0 posiciones, `live: true` en config (sin efecto por el kill). Filtros
(`entry_profiles`, `max_entry_slippage_pct`) ya en config; el proceso corriendo
aún no los carga (los toma en el próximo restart).

## Dónde corre qué (no confundir máquinas)

| Máquina | Rol | Repo | Comandos que van aquí |
|---|---|---|---|
| **[LOCAL]** Mac de Hugo | edición + git push | `~/crisol/nexux` | editar config, commit, push |
| **[VPS]** `nexux-de` (`ssh hugo@49.13.85.184`) | **instancia real** (systemd `nexus.service`, WorkingDirectory `/home/hugo/Nexus`) | `~/Nexus` | pull, restart, kill-switch, verificaciones |

El kill-switch es el archivo **`/home/hugo/Nexus/data/bot_kill`** (solo en el VPS;
`data/` no viaja por git — no buscarlo en la copia local). Su chequeo es dinámico:
crear/borrar el archivo surte efecto al instante, sin restart.

## Por qué está pausado
191 trades dedup netos de costos: el libro REAL dio 37% win / −$129 vs 61% del paper —
gap de fills (slippage de entrada a mercado) + operar todo (rr<5 pierde −0.20R/trade).
Los filtros atacan ambos: solo 4h/1D o short, siempre rr≥5, y no abrir si el precio
ya se alejó >0.3% del plan. Filtros elegidos in-sample → validar out-of-sample ANTES de live.

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
```

El bot simulará (mode=dry) con los filtros. El P&L dry se ve **separado** en el
panel (`summary().by_mode`); no se mezcla con el P&L live histórico.

## FASE 2 — Criterio de decisión (pre-registrado; NO moverlo después)
Tras **≥20 trades dry o 3 semanas** (lo primero que ocurra):
- avgR neto > **+0.2R** **Y** win rate ≥ **55%** → pasa a Fase 3.
- Si no cumple → NO activar live; el edge era in-sample, volver a analizar.

## FASE 3 — LIVE (solo si Fase 2 pasó)
```bash
# [LOCAL] config/nexus.json → "live": true ; commit + push
# [VPS]   preflight Fase 0 completo (0.2 ahora espera true) y:
cd ~/Nexus && git pull && sudo systemctl restart nexus.service   # SOLO con 0 posiciones
```
Sizing vigente: base 450, riesgo 2%, min_margin 250, cap 8%/orden, tope diario 15%.

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
- Sesgo SHORT del análisis puede ser régimen (jun–jul bajista); si el dry-run cae en
  mercado alcista y los short fallan, es señal de régimen, no de bug.
- Graduador de Claude anti-predictivo in-sample: NO usarlo como gate.
- BTA sigue en research (`paper_only`); no llega al bot.
