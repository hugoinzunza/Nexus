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

**Honestidad sobre todo.** NexUX observa, muestra y registra; reporta resultados reales aunque
sean negativos (no inflar edge) — incluido el laboratorio de backtest y el diario/forward-test,
que siguen siendo **solo lectura y paper**.

**Excepción acotada y explícita — NexUX BOT (módulo `bot`).** Desde 2026-06 NexUX SÍ opera en
vivo, pero solo a través del bot espejo: ejecuta en Binance Futuros real las mismas señales que
el diario registra. Reglas que NO se rompen:
- **Nunca retira ni mueve fondos fuera del exchange.** La llave tiene retiros OFF.
- Opera **solo** en una **subcuenta dedicada** y aislada (no la cuenta principal), con llaves
  `BINANCE_TRADE_*` exclusivas; jamás cae a las del colector.
- Arranca en **dry-run** (`config.bot.live=false`); el paso a real es deliberado.
- El **diario sigue siendo paper** y se reporta aparte del libro real del bot (no mezclar).
- El libro del bot reporta P&L y comisiones **reales**, sin maquillar.

## Mapa rápido

- `core/` — núcleo FastAPI (`app.py`, `hub.py`, `module_loader.py`, `module_base.py`, `push.py`).
- `modules/trading/` — co-piloto cripto (Crypto.com REST+SSE) + laboratorio backtest
  (`strategies.py`, `backtest.py`, `smc.py`, `engine.py`, `indicators.py`, `run_backtest.py`).
- `modules/music/` — placeholder.
- `config/nexus.json` — config central. `deploy/` — launchd + guías Mac mini. `docs/ARQUITECTURA.md`.

Detalle completo en `README.md`.
