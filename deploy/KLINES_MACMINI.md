# Refresco de la historia de velas (Mac mini → Railway)

**Qué es.** Railway está geo-bloqueado de Binance (HTTP 451), así que la historia
profunda que usan los POIs viaja a producción **versionada en git**
(`data/klines_*.json`). Esos archivos son una foto; este job los mantiene frescos
desde el Mac mini, que sí llega a Binance.

**Qué hace cada corrida** (`modules/trading/refresh_klines.py`):
1. Baja **solo lo nuevo** de Binance (incremental, no re-descarga los 4 años).
2. Si algún archivo cambió: `git add` + `commit` + `push` → Railway redeploya.

**Alcance y cadencia.** Por defecto refresca **BTC+ETH** en **1d/4h/1h** (~9 MB),
**mensual**. Es de sobra: el merge en vivo en Railway (Crypto.com) tapa el borde
reciente (hasta ~42 días en 1h, años en 1D/4h). Más frecuente o con 15m solo
infla el repo (cada push reescribe el JSON completo, git no lo diffea).

## Probar a mano

```bash
cd /Users/hugh/Nexus
.venv/bin/python -m modules.trading.refresh_klines --no-push   # actualiza y commitea local
.venv/bin/python -m modules.trading.refresh_klines             # + push a Railway
# opciones:
#   --symbols BTCUSDT,ETHUSDT,SOLUSDT
#   --intervals 1d,4h,1h,15m
```

## Instalar el job (launchd, mensual)

El `git push` corre dentro del agente de usuario: la **clave SSH de git debe estar
en el llavero** para que no pida passphrase:

```bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519   # una sola vez
ssh -T git@github.com                            # debe autenticar sin pedir nada
```

Luego:

```bash
cp /Users/hugh/Nexus/deploy/com.hugo.nexus-klines.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.hugo.nexus-klines.plist
launchctl start com.hugo.nexus-klines            # corrida inmediata de prueba
tail -f /Users/hugh/Nexus/logs/klines.out.log    # ver el resultado
```

Para desinstalar: `launchctl unload ~/Library/LaunchAgents/com.hugo.nexus-klines.plist`.

> Si el push falla por SSH, el log lo dice. Mientras tanto el commit local queda
> hecho; basta con `git push` a mano para publicarlo.
