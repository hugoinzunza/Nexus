# NexUX — Instrucciones para Claude

Hub personal de Hugo Inzunza. Núcleo modular **FastAPI + uvicorn**, mobile-first/PWA,
pensado para correr 24/7. **Independiente de ClaudeOS**: no comparten código ni carpetas.

Responder siempre en **español chileno**, tono cercano y directo.

> 📌 **Última sesión y pendientes:** ver [`docs/SESION_2026-06-17.md`](docs/SESION_2026-06-17.md)
> (auth activa, login branded, Radar SMC teaser en Home, tema oscuro, etc. + qué falta).

## REGLA #1 — Todo a GitHub, nada se pierde

GitHub es la **única fuente de verdad**. Hay varias copias de este repo (MacBook de Hugo,
Mac mini de la casa, GitHub). Para que nada se pierda ni se desincronice:

1. **Antes de trabajar:** `git pull` (traer lo último).
2. **Después de cada cambio con sentido:** `git commit` + `git push` de inmediato. No acumular
   cambios sin pushear.
3. **Nada queda solo en local.** Si no está en GitHub, no existe.

Hugo quiere que Claude ejecute los `git push` directamente, no que le pase los comandos.

## Dónde corre

- **Mac mini de la casa** = donde Nexus corre en vivo (server, backtests, colector Binance).
  El remote ahí anda por **SSH**.
- **MacBook** = edición; el push anda vía `gh` (HTTPS). Correrlo en vivo es solo en el Mac mini.
- **Deploy:** Railway (proyecto aparte, Nixpacks). Push a `main` → Railway redespliega.

## Principio del producto

**Todo solo-lectura sobre mercados.** NexUX observa y muestra info; **nunca** opera, ni mueve
ni retira dinero. Mantener esa honestidad — incluido el laboratorio de backtest, que reporta
resultados reales aunque sean negativos (no inflar edge).

## Mapa rápido

- `core/` — núcleo FastAPI (`app.py`, `hub.py`, `module_loader.py`, `module_base.py`, `push.py`).
- `modules/trading/` — co-piloto cripto (Crypto.com REST+SSE) + laboratorio backtest
  (`strategies.py`, `backtest.py`, `smc.py`, `engine.py`, `indicators.py`, `run_backtest.py`).
- `modules/music/` — placeholder.
- `config/nexus.json` — config central. `deploy/` — launchd + guías Mac mini. `docs/ARQUITECTURA.md`.

Detalle completo en `README.md`.
