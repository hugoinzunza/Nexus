# Migración de Nexux a un VPS en Alemania (Hetzner)

**Objetivo:** sacar el motor de datos de Nexux del Mac mini y ponerlo en un VPS
alemán con **IP estática**. Resuelve de raíz el HTTP 451 de Binance y la
fragilidad del IP de casa (que se rompió hoy), y libera el Mac mini.

**Qué se mueve:** la **app** (poller SMC + graduador sombra) **y el colector** y
el refresco de klines. Railway sigue sirviendo la web pública; el VPS es el motor
de datos que le empuja todo.

> ⚠️ Binance está geo-bloqueado para EE.UU. (de ahí el 451 de Railway). Alemania
> está **confirmada como región permitida** por staff de Binance. El **Paso 3 es
> la verdad**: si el VPS pasa el 451, seguimos; si no, se destruye y se recrea.

---

## 1) Crear el VPS en Hetzner

1. Cuenta en https://console.hetzner.cloud → crea un **Project** (ej. "nexus").
2. **Add Server**:
   - **Location:** Falkenstein o Nuremberg (**Alemania** — NO Helsinki).
   - **Image:** Ubuntu 24.04.
   - **Type:** **CX22** (2 vCPU, 4 GB) — sobra para Nexux (~€5/mes con IPv4).
   - **Networking:** deja IPv4 pública activada (la necesitas para el whitelist).
   - **SSH key:** sube tu clave pública (`cat ~/.ssh/id_ed25519.pub`; si no tienes,
     `ssh-keygen -t ed25519` en el Mac).
3. Anota la **IPv4 estática** del servidor (la verás en el panel). Le diremos `VPS_IP`.

---

## 2) Acceso y endurecimiento básico

```bash
ssh root@VPS_IP

# Usuario no-root con sudo
adduser hugo && usermod -aG sudo hugo
rsync --archive --chown=hugo:hugo ~/.ssh /home/hugo   # copia tu SSH key al user

# Firewall: solo SSH (la app NO se expone a internet; habla con Railway saliente)
apt update && apt install -y ufw fail2ban
ufw allow OpenSSH && ufw --force enable

# Endurecer SSH: sin root, sin password
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh
```

Reconecta como tu usuario: `ssh hugo@VPS_IP`.

---

## 3) ⚠️ GATE: confirmar que el VPS PASA el 451 (antes de migrar nada)

Esto es público (sin claves). Si devuelve 451, el VPS está en mala región → bórralo
y créalo en otro datacenter alemán.

```bash
# Spot público
curl -s -o /dev/null -w "spot:  HTTP %{http_code}\n"   https://api.binance.com/api/v3/ping
# Futuros público
curl -s -o /dev/null -w "fut:   HTTP %{http_code}\n"   https://fapi.binance.com/fapi/v1/ping
```

- ✅ **`HTTP 200`** en ambos → región OK, continúa.
- ❌ **`HTTP 451`** → región bloqueada. Destruye el server (Hetzner → Delete) y
  recréalo en el otro DC alemán (Paso 1). No sigas hasta tener 200.

---

## 4) Whitelist del IP del VPS en Binance

En Binance → **API Management** → tu key del colector:

1. **IP access restrictions** → *Restrict access to trusted IPs only* → agrega `VPS_IP`.
2. Deja el IP viejo del Mac mini por ahora (lo quitas al final, cuando confirmes
   que el VPS funciona).
3. Confirma permisos: ✅ **Enable Reading**, ✅ **Enable Futures**, ⛔ **Withdrawals OFF**.

> Con IP estática whitelisteada, la key ya **no expira a los 90 días** (ese límite
> solo aplica a keys SIN restricción de IP).

---

## 5) Instalar Nexux en el VPS

```bash
sudo apt install -y python3 python3-venv python3-pip git
cd ~ && git clone https://github.com/hugoinzunza/Nexus.git
cd ~/Nexus
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## 6) Configurar secretos

```bash
cp deploy/collector.env.example deploy/collector.env
nano deploy/collector.env
```

Completa (es el mismo formato `KEY=valor` que ya usas):

```
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
NEXUS_INGEST_URL=https://<tu-app>.up.railway.app/m/journal/api/ingest
NEXUS_INGEST_TOKEN=<mismo token que en Railway>
BINANCE_LOOKBACK_DAYS=365
ANTHROPIC_API_KEY=sk-ant-...     # para el graduador sombra (opcional)
```

`deploy/collector.env` está en `.gitignore` (no se commitea). La app y el colector
lo leerán vía systemd (Paso 8).

---

## 7) Probar A MANO (antes de automatizar)

```bash
cd ~/Nexus
# Colector: debe decir futuros ok=True / spot ok=True (señal de que el IP pasó)
.venv/bin/python -m modules.journal.collector "$(pwd)" 1 deploy/collector.env

# App: levanta y sirve (Ctrl+C para parar tras confirmar)
set -a; . deploy/collector.env; set +a
PORT=8800 ./nexus
```

Si el colector dice `futuros ok=True`, el 451 y el whitelist están resueltos. 🎉

---

## 8) systemd: app + colector + klines (24/7)

Crea un EnvironmentFile compartido y tres units. (El `collector.env` ya sirve
como EnvironmentFile.)

**App** — `/etc/systemd/system/nexus.service`:
```ini
[Unit]
Description=Nexux app (poller SMC + graduador)
After=network-online.target
[Service]
User=hugo
WorkingDirectory=/home/hugo/Nexus
EnvironmentFile=/home/hugo/Nexus/deploy/collector.env
Environment=PORT=8800
ExecStart=/home/hugo/Nexus/.venv/bin/uvicorn core.app:app --host 0.0.0.0 --port 8800
Restart=always
[Install]
WantedBy=multi-user.target
```

**Colector** — `/etc/systemd/system/nexus-collector.service`:
```ini
[Unit]
Description=Nexux colector (Binance -> Railway)
[Service]
Type=oneshot
User=hugo
WorkingDirectory=/home/hugo/Nexus
ExecStart=/home/hugo/Nexus/.venv/bin/python -m modules.journal.collector /home/hugo/Nexus 1 /home/hugo/Nexus/deploy/collector.env
```

**Colector timer** (cada 90 s) — `/etc/systemd/system/nexus-collector.timer`:
```ini
[Unit]
Description=Corre el colector cada 90s
[Timer]
OnBootSec=30
OnUnitActiveSec=90
[Install]
WantedBy=timers.target
```

Activar todo:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nexus.service
sudo systemctl enable --now nexus-collector.timer
# Ver logs:
journalctl -u nexus -f
journalctl -u nexus-collector -f
```

> El refresco de klines: si lo usas, replica el patrón del colector con otro
> `.service` + `.timer` apuntando a `modules.trading.refresh_klines` (intervalo
> mayor, p.ej. cada 6 h con `OnUnitActiveSec=21600`).

---

## 9) Verificar en Railway

Abre el Diario: `https://<tu-app>.up.railway.app/m/journal/`. Debe pasar a "al día"
con PnL/posiciones reales, y los setups fluyendo. Dale un par de ciclos (~3 min).

---

## 10) Decomisionar el Mac mini

Cuando el VPS lleve un par de horas estable:

```bash
# En el MAC MINI — apaga los servicios viejos:
launchctl bootout gui/$(id -u)/com.hugo.nexus
launchctl bootout gui/$(id -u)/com.hugo.nexus-collector
launchctl bootout gui/$(id -u)/com.hugo.nexus-klines
```

Y en Binance, **quita el IP viejo** del Mac mini del whitelist (deja solo `VPS_IP`).

---

## 11) Mantenimiento

- **Actualizar Nexux:** `cd ~/Nexus && git pull && .venv/bin/pip install -r requirements.txt && sudo systemctl restart nexus`.
- **Logs:** `journalctl -u nexus -u nexus-collector --since "1 hour ago"`.
- **Backups:** los datos vivos (`data/*.json` no versionados) se regeneran solos;
  lo único irreemplazable son los secretos (`collector.env`) — guárdalos aparte.
- **Seguridad:** `unattended-upgrades` para parches automáticos:
  `sudo apt install -y unattended-upgrades && sudo dpkg-reconfigure -plow unattended-upgrades`.

---

## Resumen del flujo final

```
  VPS Alemania (IP estática)                Railway (web pública)
  ┌───────────────────────────┐  POST       ┌────────────────────────┐
  │ app: poller SMC + grader  │ ───────────▶ │ /m/journal/api/ingest  │
  │ colector: Binance R/O      │  X-Nexus    │ /m/journal/api/ingest_setups
  │ (cada 90s, systemd timer)  │  -Token     │ guarda y sirve la web  │
  └───────────────────────────┘             └────────────────────────┘
        IP alemana = sin 451                   HTTPS + dominio fijo
```

El Mac mini queda libre. La key de Binance queda atada a una IP estática que no cambia.
