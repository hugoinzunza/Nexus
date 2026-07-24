# Colector visual autorizado de CoinGlass

Este colector complementa la API Hobbyist con las vistas que el plan no expone:
mapa de liquidaciones, Heatmap Model 2 y delta agregado del order book. Solo
produce datos `research_only`; no importa el bot ni puede enviar órdenes.

## Diseño

- Perfil Chromium exclusivo: `~/.config/nexux/coinglass-visual-profile`.
- Nunca usa el perfil personal de Chrome.
- Lee tooltips ECharts causales y publica por `X-Nexus-Token`.
- Railway valida origen, activo, cobertura, antigüedad y `execution_enabled:false`.
- Si CoinGlass cambia el DOM, falta acceso o hay menos de cuatro niveles, el
  proceso falla y no publica una captura inventada.

## Instalación en el VPS

```bash
cd /home/hugo/Nexus
python3 -m venv .venv-coinglass
.venv-coinglass/bin/pip install -r deploy/requirements-coinglass-visual.txt
.venv-coinglass/bin/playwright install --with-deps chromium
mkdir -p ~/.config/nexux/coinglass-visual-profile data
chmod 700 ~/.config/nexux/coinglass-visual-profile
```

El archivo `deploy/collector.env` debe contener el mismo
`NEXUS_INGEST_TOKEN` configurado en Railway. No se guardan credenciales
CoinGlass en ese archivo.

## Sesión

Primero se prueba sin login porque las gráficas pueden estar visibles para la
sesión pública:

```bash
cd /home/hugo/Nexus
set -a; source deploy/collector.env; set +a
.venv-coinglass/bin/python3 modules/coinglass/visual_collector.py \
  --once --output data/coinglass_visual_latest.json
```

Si CoinGlass exige login, se abre una única vez el perfil dedicado con
`--headed` dentro de una sesión gráfica/VNC privada del VPS. El usuario inicia
sesión directamente en CoinGlass; NexUX no recibe ni almacena la contraseña.
Después se cierra el navegador y el timer reutiliza ese perfil en headless.

## Activación

```bash
sudo cp deploy/nexus-coinglass-visual.service /etc/systemd/system/
sudo cp deploy/nexus-coinglass-visual.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start nexus-coinglass-visual.service
sudo journalctl -u nexus-coinglass-visual.service -n 80 --no-pager
```

Solo si el primer snapshot muestra cobertura válida:

```bash
sudo systemctl enable --now nexus-coinglass-visual.timer
systemctl list-timers nexus-coinglass-visual.timer
```

## Rollback

```bash
sudo systemctl disable --now nexus-coinglass-visual.timer
sudo systemctl stop nexus-coinglass-visual.service
```

Esto no afecta el colector CoinSignals, el diario, el dry-run ni el bot.

