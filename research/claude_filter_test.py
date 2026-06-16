"""Test retrospectivo: ¿el criterio de Claude habría mejorado el forward-test?

Para CADA trade cerrado (ganador Y perdedor), le mostramos a Claude SOLO el
contexto disponible AL CREARSE el setup (cero look-ahead: nada de result_r,
outcome, status ni ts_closed) y le pedimos que decida abrir o saltar, como un
trader disciplinado filtrando por calidad. Luego medimos la matriz de confusión.

HONESTIDAD METODOLÓGICA:
- Se prueban AMBOS lados (ganadores y perdedores). Un filtro que skipea todo
  evita el 100% de los perdedores pero también de los ganadores → no aporta.
  El edge existe solo si skip-rate(perdedores) > skip-rate(ganadores) Y la
  expectativa de los trades que Claude MANTIENE supera la del set completo.
- Se EXCLUYEN los 7 primeros setups (fuera de la estrategia): ts_created >= CUTOFF.
- Muestra chica (~14 trades, con duplicados correlacionados) → es un PROOF OF
  CONCEPT, no una validación estadística. La validación real se acumula con el
  tiempo, ahora que las guardias dejan los datos limpios.

Uso:  .venv/bin/python -m research.claude_filter_test
Lee ANTHROPIC_API_KEY de deploy/collector.env (gitignored).
"""
from __future__ import annotations

import json
import os
import sys

import anthropic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUPS = os.path.join(ROOT, "data", "setups.json")
ENV = os.path.join(ROOT, "deploy", "collector.env")

# Corte: solo setups creados en/después de este ts (excluye los 7 fuera de estrategia).
CUTOFF_TS = 1781433030
MODEL = "claude-opus-4-8"

# Campos disponibles AL CREARSE (sin look-ahead). El resto (result_r, status,
# outcome_price, ts_closed, paper_*) NO se le muestra a Claude.
SYSTEM = """Eres un trader disciplinado de Smart Money Concepts (SMC) evaluando si \
TOMAR o SALTAR un setup, usando SOLO el contexto previo a la entrada (no sabes qué \
pasó después). La estrategia busca calidad sobre cantidad. Factores de un buen setup:
- Disciplina premium/descuento (OTE): largo en descuento, corto en premium (disc_ok).
- Régimen favorable: idealmente VIX < 25 y ADX > 25 (regime_ok).
- R:R razonable y zona bien definida.
- Confirmación de cambio de carácter (CDC) si aplica.
- Evitar entrar contra estructura mayor o en contexto pobre.
Sé selectivo: si el contexto es flojo o el régimen es desfavorable, SALTA. \
Devuelve tu decisión llamando a la herramienta `decidir`."""

TOOL = {
    "name": "decidir",
    "description": "Registra la decisión sobre el setup.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["abrir", "skip"],
                         "description": "abrir = tomar el setup; skip = no tomarlo"},
            "confidence": {"type": "integer", "description": "0-100"},
            "rationale": {"type": "string", "description": "razón breve (1 frase)"},
        },
        "required": ["decision", "confidence", "rationale"],
    },
}


def load_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    if os.path.isfile(ENV):
        for line in open(ENV, encoding="utf-8"):
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                return
    sys.exit("falta ANTHROPIC_API_KEY (en entorno o deploy/collector.env)")


def blind_context(s: dict) -> str:
    """Solo lo conocido al crearse el setup — cero look-ahead."""
    reg = "n/d"
    if s.get("regime_ok") is not None:
        reg = "favorable" if s["regime_ok"] else "desfavorable"
        reg += f" (VIX={s.get('regime_vix')}, ADX={s.get('regime_adx')})"
    disc = {True: "sí (alineado)", False: "no (mal lado)", None: "n/d"}[s.get("disc_ok")]
    return (
        f"Par: {s['pair']}\n"
        f"Dirección: {s['dir']}\n"
        f"TF del POI: {s.get('poi_tf')} (TF de planeación: {s.get('sel_tf')})\n"
        f"Zona de entrada (POI): {s.get('entry_lo')} – {s.get('entry_hi')} (ref {s.get('entry')})\n"
        f"Stop loss: {s.get('sl')}\n"
        f"Take profit: {s.get('tp')} ({s.get('tp_label','')})\n"
        f"R:R: {s.get('rr')}\n"
        f"Precio al detectarse: {s.get('price_at_create')}\n"
        f"Premium/descuento (OTE): {disc}\n"
        f"Régimen: {reg}\n"
        f"CDC al generarse: {s.get('cdc_status_init', 'n/d')}\n"
        f"Estado inicial: {s.get('state_init','pendiente')}"
    )


def decide(client, s) -> dict:
    resp = client.messages.create(
        model=MODEL, max_tokens=1024,
        system=SYSTEM,
        tools=[TOOL], tool_choice={"type": "tool", "name": "decidir"},
        messages=[{"role": "user", "content":
                   "Evalúa este setup y decide:\n\n" + blind_context(s)}],
    )
    for b in resp.content:
        if b.type == "tool_use":
            return b.input
    return {"decision": "abrir", "confidence": 0, "rationale": "(sin respuesta)"}


def main():
    load_key()
    client = anthropic.Anthropic()
    setups = json.load(open(SETUPS, encoding="utf-8"))
    closed = sorted(
        [s for s in setups
         if s.get("status") in ("ganada", "perdida")
         and s.get("result_r") is not None
         and (s.get("ts_created") or 0) >= CUTOFF_TS],
        key=lambda s: s["ts_created"])
    print(f"Trades en el test (excluidos los 7 primeros): {len(closed)}\n")

    rows = []
    for s in closed:
        d = decide(client, s)
        win = s["result_r"] > 0
        rows.append({"win": win, "r": s["result_r"], "dec": d["decision"],
                     "conf": d["confidence"], "why": d["rationale"], "pair": s["pair"]})
        mark = "GANA" if win else "PIERDE"
        print(f"  {s['pair']:10} {s['dir']:5} R={s['result_r']:+6.2f} [{mark}] "
              f"→ Claude: {d['decision'].upper():5} (conf {d['confidence']}) — {d['rationale']}")

    # Matriz de confusión
    wins = [r for r in rows if r["win"]]
    losers = [r for r in rows if not r["win"]]
    skip_l = [r for r in losers if r["dec"] == "skip"]
    skip_w = [r for r in wins if r["dec"] == "skip"]
    kept = [r for r in rows if r["dec"] == "abrir"]

    def rate(part, whole):
        return 100 * len(part) / len(whole) if whole else 0.0

    print("\n=== MATRIZ DE CONFUSIÓN ===")
    print(f"  Perdedores: {len(losers)} | Claude SKIPEA {len(skip_l)} "
          f"({rate(skip_l, losers):.0f}%) ✅ | abre {len(losers)-len(skip_l)}")
    print(f"  Ganadores:  {len(wins)} | Claude SKIPEA {len(skip_w)} "
          f"({rate(skip_w, wins):.0f}%) ❌ | abre {len(wins)-len(skip_w)}")

    print("\n=== EXPECTATIVA (R promedio por trade) ===")
    all_r = sum(r["r"] for r in rows) / len(rows) if rows else 0
    kept_r = sum(r["r"] for r in kept) / len(kept) if kept else 0
    print(f"  Set completo:        {all_r:+.3f} R/trade ({len(rows)} trades)")
    print(f"  Solo los que Claude MANTIENE: {kept_r:+.3f} R/trade ({len(kept)} trades)")
    edge = (rate(skip_l, losers) > rate(skip_w, wins)) and (kept_r > all_r)
    print(f"\n  VEREDICTO: {'señal de edge (skipea más perdedores que ganadores Y mejora expectativa)' if edge else 'sin señal clara — Claude no discrimina mejor que tomar todo'}")
    print("  ⚠️  Muestra chica → proof of concept, NO validación estadística.")


if __name__ == "__main__":
    main()
