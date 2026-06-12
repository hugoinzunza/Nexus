# Autostart de Nexux en el Mac mini (launchd)

Esto hace que Nexux arranque solo cuando enciendes el Mac mini y se mantenga
corriendo 24/7 (si se cae, `launchd` lo vuelve a levantar). El Mac mini no
necesita pantalla: Nexux queda escuchando en la red y lo abres desde el iPhone,
el iPad o el MacBook.

> El plist está en [`com.hugo.nexus.plist`](com.hugo.nexus.plist). Si clonaste
> Nexux en una carpeta distinta a `/Users/hugh/Nexus`, edita las rutas adentro
> antes de instalarlo.

## Requisitos previos

```bash
cd ~/Nexus
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p logs
```

## Instalar el servicio

```bash
# 1) Copia el plist a la carpeta de agentes del usuario.
cp ~/Nexus/deploy/com.hugo.nexus.plist ~/Library/LaunchAgents/

# 2) Cárgalo (macOS Ventura+ usa 'bootstrap'; gui/$(id -u) = tu sesión).
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hugo.nexus.plist

# 3) Verifica que quedó corriendo.
launchctl print gui/$(id -u)/com.hugo.nexus | grep -E "state|pid"
curl -s http://127.0.0.1:8800/health
```

En macOS más antiguo, en vez de `bootstrap` puedes usar:

```bash
launchctl load ~/Library/LaunchAgents/com.hugo.nexus.plist
```

## Ver logs

```bash
tail -f ~/Nexus/logs/nexus.out.log   # salida normal
tail -f ~/Nexus/logs/nexus.err.log   # errores
```

## Reiniciar tras actualizar el código

```bash
launchctl kickstart -k gui/$(id -u)/com.hugo.nexus
```

## Detener / desinstalar

```bash
launchctl bootout gui/$(id -u)/com.hugo.nexus      # detener
rm ~/Library/LaunchAgents/com.hugo.nexus.plist     # desinstalar
```

## Que no se duerma el Mac mini

Para que siga sirviendo aunque nadie lo use, conviene evitar que se suspenda:

```bash
sudo pmset -a sleep 0          # no dormir el sistema
sudo pmset -a disksleep 0      # no dormir el disco
```

(O desde **Ajustes del Sistema → Batería/Energía → "Evitar que se duerma".**)

## Abrirlo desde tus otros dispositivos

Averigua la IP local del Mac mini:

```bash
ipconfig getifaddr en0   # Wi-Fi
ipconfig getifaddr en1   # Ethernet (si usa cable)
```

Y desde el iPhone/iPad/MacBook (en la misma red) abre:

```
http://IP_DEL_MAC_MINI:8800/
```

Para tenerlo a mano, en el iPhone/iPad usa **Compartir → Agregar a pantalla de
inicio**: Nexux se instala como app (PWA) a pantalla completa.
