# Colector del Diario en el Mac mini (arquitectura híbrida)

Binance bloquea los servidores de Railway por ubicación (HTTP 451). Por eso la
**lectura de Binance se hace desde el Mac mini** (IP de Chile, que además es la
que pones en el whitelist de la API key) y el resultado se **envía a Railway**,
que solo lo guarda y lo muestra.

```
  Mac mini (IP Chile)                         Railway (web pública)
  ┌─────────────────────┐   POST /ingest      ┌──────────────────────┐
  │ collector.py        │  ───────────────▶   │ /m/journal/api/ingest │
  │  · lee Binance R/O  │   X-Nexus-Token     │  guarda el JSON       │
  │  · arma el JSON     │                     │ /m/journal/  lo sirve │
  └─────────────────────┘                     └──────────────────────┘
```

El colector es **solo lectura** de Binance: nunca crea, cancela, transfiere ni
retira.

## 1) Configurar credenciales (archivo local, NO se commitea)

```bash
cd ~/Nexus
cp deploy/collector.env.example deploy/collector.env
# Edita deploy/collector.env y completa:
#   BINANCE_API_KEY, BINANCE_API_SECRET
#   NEXUS_INGEST_URL   (la URL de Railway + /m/journal/api/ingest)
#   NEXUS_INGEST_TOKEN (el mismo token que pusiste en Railway)
```

`deploy/collector.env` está en `.gitignore`. (Alternativa: `~/.nexus/binance.env`.)

**Permisos de la API key en Binance:** ✅ Enable Reading, ✅ Enable Futures,
⛔ Enable Withdrawals desactivado, y restringe por IP a la IP pública del Mac mini.

## 2) Probar el colector a mano

```bash
cd ~/Nexus
.venv/bin/python -m modules.journal.collector
```

Debe leer Binance y responder `✓ enviado a Railway: {'ok': True, ...}`. Si falla,
el log dice por qué (credenciales, permisos, red).

## 3) Instalar el servicio launchd (cada 5 min)

```bash
mkdir -p ~/Nexus/logs
cp ~/Nexus/deploy/com.hugo.nexus-collector.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hugo.nexus-collector.plist

# Forzar una corrida ya:
launchctl kickstart -k gui/$(id -u)/com.hugo.nexus-collector

# Ver logs:
tail -f ~/Nexus/logs/collector.out.log
```

(En macOS antiguo: `launchctl load ~/Library/LaunchAgents/com.hugo.nexus-collector.plist`.)

## 4) Verificar

Abre el Diario en Railway: **https://<tu-app>.up.railway.app/m/journal/**. Debe
mostrar tus estadísticas y "actualizado hace X min". El estado pasa de
"Esperando datos del colector" a "al día".

## Detener / desinstalar

```bash
launchctl bootout gui/$(id -u)/com.hugo.nexus-collector
rm ~/Library/LaunchAgents/com.hugo.nexus-collector.plist
```

## Variables de entorno — resumen

| Dónde | Variable | Para qué |
|---|---|---|
| Mac mini (`collector.env`) | `BINANCE_API_KEY` / `BINANCE_API_SECRET` | Leer Binance (R/O) |
| Mac mini (`collector.env`) | `NEXUS_INGEST_URL` | Endpoint de ingesta de Railway |
| Mac mini (`collector.env`) | `NEXUS_INGEST_TOKEN` | Token compartido |
| Mac mini (`collector.env`) | `BINANCE_LOOKBACK_DAYS` | Opcional (días, por defecto 365) |
| **Railway** | `NEXUS_INGEST_TOKEN` | **Mismo token** (autentica la ingesta) |

> Railway ya **no** necesita `BINANCE_API_KEY` ni `BINANCE_API_SECRET`: puedes
> borrarlas de sus Variables. Solo necesita `NEXUS_INGEST_TOKEN`.
