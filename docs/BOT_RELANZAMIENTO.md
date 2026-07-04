# Runbook — relanzamiento del bot (tras auditoría 2026-07-04)

Estado al escribir esto: **bot PAUSADO** (kill-switch `data/bot_kill` activo en el VPS),
0 posiciones abiertas, `live: true` en config pero sin efecto por el kill.
Los filtros nuevos (`entry_profiles`, `max_entry_slippage_pct`) ya están en config;
el proceso corriendo aún no los carga (requiere restart — paso 1).

## Por qué está pausado
Análisis de 191 trades dedup (neto de costos): el libro REAL del bot dio 37% win /
−$129 vs 61% del paper — el gap está en los fills (slippage de la entrada a mercado)
y en operar todo (rr<5 pierde: −0.20R/trade). Los filtros del config atacan ambos:
solo 4h/1D o short, siempre rr≥5, y no abrir si el precio ya se alejó >0.3% del plan.
OJO: filtros elegidos in-sample → hay que validarlos out-of-sample ANTES de live.

## Fase 1 — DRY-RUN (2–3 semanas)
En el VPS (`ssh hugo@49.13.85.184`, repo `~/Nexus`):
```bash
cd ~/Nexus && git pull
# 1) poner el bot en dry-run:
#    config/nexus.json → "live": false        (editar y commitear, o sed local)
# 2) quitar el kill para que el DRY corra:
rm -f data/bot_kill
# 3) reiniciar SOLO con el bot plano (verificar antes: 0 posiciones):
sudo systemctl restart nexus.service
```
El bot simulará (mode=dry) con los filtros nuevos. El P&L dry se ve separado en
`summary().by_mode` del panel.

## Fase 2 — criterio de decisión (pre-registrado, NO moverlo después)
Tras ≥20 trades dry o 3 semanas (lo que llegue primero):
- avgR neto del dry > +0.2R  Y  win rate ≥ 55%  → pasa a live (Fase 3).
- Si no cumple → NO activar live; volver a analizar (el edge era in-sample).

## Fase 3 — LIVE (solo si Fase 2 pasó)
```bash
# config/nexus.json → "live": true ; commit/push ; en el VPS:
cd ~/Nexus && git pull && sudo systemctl restart nexus.service   # con bot plano
```
Sizing vigente: base 450, riesgo 2%, min_margin 250, cap de riesgo 8%/orden,
tope diario 15%. Kill-switch de emergencia: botón "Parar bot" en /m/bot/ o
`touch ~/Nexus/data/bot_kill`.

## Notas
- El sesgo SHORT del análisis puede ser régimen del período (mercado bajista
  jun-jul); si el dry-run cae en mercado alcista y los short fallan, es señal
  de régimen, no de bug.
- El graduador de Claude resultó anti-predictivo in-sample: NO usarlo como gate.
- BTA sigue en research (paper_only); no llega al bot.
