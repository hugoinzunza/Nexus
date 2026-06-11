# ◆ Nexus

**Hub personal de Hugo**, pensado para correr 24/7 en el Mac mini. Un núcleo
modular (FastAPI + uvicorn) al que le vas enchufando módulos según hagan falta.
El nombre es general a propósito: Nexus va a crecer.

Como el Mac mini no tiene pantalla, Nexus está pensado **mobile-first**: lo abres
desde el iPhone, el iPad o el MacBook, y puedes instalarlo como app (PWA) a
pantalla completa.

Hoy arranca con dos áreas:

- **📈 Trading** — co-piloto de mercado de cripto en vivo (¡ya funcional!).
- **🎵 Música** — reservado, placeholder por ahora.

> ⚠️ **Solo lectura.** Nexus observa los mercados y muestra información. **No
> ejecuta operaciones ni mueve dinero.** Usa únicamente endpoints públicos.

---

## 🧠 La visión

Nexus es el "cerebro central" de Hugo en su Mac mini. La idea es tener **un solo
lugar** desde donde vivan cosas distintas (trading, música, y lo que venga:
finanzas, automatización del hogar, notas, salud, etc.), cada una como un
**módulo independiente** que puedes prender, apagar o reemplazar sin tocar el
resto.

El primer módulo serio es el **co-piloto de trading**: un panel que muestra el
mercado cripto en tiempo real para acompañar tus decisiones (sin operar por ti).

---

## 🚀 Cómo correrlo en local

Necesitas Python 3 y las dependencias del núcleo (FastAPI + uvicorn). La primera
vez creas un entorno virtual e instalas:

```bash
cd ~/Nexus
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Luego, para arrancarlo:

```bash
./nexus
```

`./nexus` usa el `.venv` y levanta uvicorn con recarga automática en
`0.0.0.0:8800`. Abre en el navegador:

- **Hub:** http://127.0.0.1:8800/
- **Trading:** http://127.0.0.1:8800/m/trading/
- **Música:** http://127.0.0.1:8800/m/music/

Para detenerlo: `Ctrl + C`.

> El puerto se toma de la variable de entorno `PORT` (por defecto `8800`).
> Ejemplo: `PORT=9000 ./nexus`.

---

## 📱 Cómo abrirlo desde el iPhone, iPad o MacBook

El Mac mini sirve Nexus en la red local. Desde otro dispositivo **en la misma
red Wi-Fi**, necesitas la IP del Mac mini:

```bash
# En el Mac mini:
ipconfig getifaddr en0   # Wi-Fi
ipconfig getifaddr en1   # Ethernet (si usa cable)
```

Supongamos que devuelve `192.168.1.50`. Entonces, desde el iPhone/iPad/MacBook
abres:

```
http://192.168.1.50:8800/
```

**Instalarlo como app (PWA):**

- **iPhone / iPad (Safari):** toca **Compartir → Agregar a pantalla de inicio**.
  Nexus se instala como app a pantalla completa, con su ícono.
- **MacBook (Chrome/Edge):** ícono de **instalar** en la barra de direcciones.
- **MacBook (Safari):** **Archivo → Agregar al Dock**.

> Para que la PWA sea instalable desde fuera de `localhost`, el navegador suele
> pedir HTTPS. En la red local funciona igual desde la IP; para acceso remoto y
> PWA "de verdad", lo más cómodo es el despliegue en Railway (ver abajo), que ya
> viene con HTTPS y un dominio fijo.

---

## ☁️ Cómo desplegarlo en Railway

Nexus se despliega como un proyecto **aparte** en Railway (llámalo "Nexus",
separado del ERP de PROTEQ). Usa **Nixpacks** (no Dockerfile): no necesita
Chromium ni WeasyPrint, así que el build es liviano.

Archivos que ya dejé listos:

- [`requirements.txt`](requirements.txt) — dependencias (FastAPI, uvicorn, pywebpush).
- [`nixpacks.toml`](nixpacks.toml) — build con Python 3.11.
- [`railway.json`](railway.json) — builder Nixpacks + comando de arranque.
- [`Procfile`](Procfile) — `web: uvicorn core.app:app --host 0.0.0.0 --port $PORT`.
- [`start.sh`](start.sh) — entrypoint equivalente para correr a mano.

### Pasos

1. Sube este repo a GitHub (ver más abajo) y entra a https://railway.app.
2. **New Project → Deploy from GitHub repo** y elige el repo de Nexus.
3. Railway detecta Nixpacks y `railway.json` automáticamente; no toques el
   builder (debe quedar **Nixpacks**, no Docker).
4. En **Settings → Networking → Generate Domain** para obtener una URL pública
   con HTTPS (ej: `nexus-production.up.railway.app`).
5. Railway inyecta `PORT` solo; Nexus lo respeta. No hace falta configurar nada
   más para arrancar.

### Variables de entorno (opcionales, para alertas push a futuro)

Las alertas todavía no están implementadas, pero la cañería de web push ya está
lista. Cuando quieras activarlas, configura en Railway:

| Variable                | Para qué                                            |
|-------------------------|-----------------------------------------------------|
| `VAPID_PUBLIC_KEY_B64`  | Clave pública VAPID (base64url) que usa el frontend. |
| `VAPID_PRIVATE_KEY_B64` | Clave privada VAPID (32 bytes raw en base64url).     |
| `VAPID_SUBJECT`         | `mailto:tu@correo` que identifica al servidor.       |

---

## 🖥️ Autostart 24/7 en el Mac mini (launchd)

Si prefieres correr Nexus en el propio Mac mini (en vez de, o además de,
Railway), hay un servicio `launchd` que lo arranca solo al encender y lo mantiene
vivo. Las instrucciones completas están en
[`deploy/AUTOSTART_MACMINI.md`](deploy/AUTOSTART_MACMINI.md) y el archivo del
servicio en [`deploy/com.hugo.nexus.plist`](deploy/com.hugo.nexus.plist).

---

## 📊 Módulo de Trading

Dashboard web que muestra, para cada instrumento (por defecto **BTC/USDT** y
**ETH/USDT**):

- **Precio en vivo** con variación 24h y parpadeo verde/rojo en cada cambio.
- **Estadísticas**: máximo/mínimo 24h, mejor bid/ask, volumen.
- **Gráfico de velas** (OHLCV) dibujado en canvas, sin librerías externas, con
  **selector de temporalidad por par** (1m, 5m, 15m, 1h, 4h, 1D): al cambiarla,
  el gráfico recarga las velas en esa resolución desde Crypto.com.
- **Libro de órdenes** con barras de profundidad y el spread.
- **Señales** (semilla de inteligencia, todo informativo):
  - Posición dentro del rango del día (0–100%).
  - Momentum de los últimos ~15 minutos.
  - Spread en puntos básicos.
  - Desequilibrio del libro (presión compradora vs. vendedora).

**Datos:** API pública REST de [Crypto.com Exchange](https://exchange-docs.crypto.com).
El backend consulta el mercado cada par de segundos y empuja las novedades al
navegador por **SSE** (Server-Sent Events), así el panel se actualiza solo.

### Backtest de estrategia (SMC)

Hay un motor de estrategia mecánica basada en Smart Money Concepts y su backtest
sobre datos históricos reales de Binance (klines públicas):

- **Estrategia:** barrido de liquidez → cambio de carácter (CHoCH/BOS) → entrada
  en el FVG u order block del impulso. Stop más allá del barrido, take-profit por
  múltiplos de R. Filtros de calidad parametrizables (tendencia por estructura del
  timeframe superior o por EMA, displacement por ATR, premium/discount, tamaño
  mínimo del FVG, sesión). Todo en [`modules/trading/backtest.py`](modules/trading/backtest.py).
- **Validación honesta:** incluye comisiones (0.05%/lado) y slippage (0.02%); y
  sobre todo separa **in-sample vs out-of-sample** (optimiza en el 70% antiguo,
  testea en el 30% reciente) más un **walk-forward** anclado, para no autoengañarse
  con sobreajuste. Reporta win rate, expectativa en R, profit factor, drawdown y
  rachas. El rendimiento pasado no garantiza el futuro.
- **Resultado actual (honesto):** la estrategia base no tiene ventaja robusta
  fuera de muestra (la mejor config in-sample, +0.26R, cae a −0.24R out-of-sample;
  walk-forward −0.24R). El único foco que aguanta es BTCUSDT 4h con filtro EMA,
  pero con muestra chica. La vista web lo explica con su veredicto.
- **Correr el backtest** (baja el histórico a `data/`, que está en `.gitignore`, y
  regenera `modules/trading/backtest_results.json`):

  ```bash
  .venv/bin/python -m modules.trading.run_backtest
  ```

- **Vista web:** http://127.0.0.1:8800/m/trading/backtest (mobile-first): métricas,
  curva de equity en R y todas las tablas. Lee el JSON ya calculado, así funciona
  también en Railway sin recalcular.

### Configuración

Todo se ajusta en [`config/nexus.json`](config/nexus.json):

```json
{
  "port": 8800,
  "modules": {
    "trading": {
      "enabled": true,
      "poll_interval_seconds": 2,
      "instruments": [
        { "name": "BTC_USDT", "label": "BTC/USDT" },
        { "name": "ETH_USDT", "label": "ETH/USDT" }
      ]
    }
  }
}
```

Para seguir más pares, agrega entradas a `instruments` (ej: `SOL_USDT`,
`XRP_USDT`). Los nombres son los que usa Crypto.com (`BASE_QUOTE`).

---

## 🧩 Arquitectura

```
Nexus/
├── nexus                 ← lanzador local (./nexus → uvicorn)
├── start.sh              ← entrypoint de producción (Railway)
├── requirements.txt      ← dependencias del núcleo
├── railway.json / nixpacks.toml / Procfile ← config de despliegue
├── config/nexus.json     ← configuración central
├── core/                 ← el núcleo (hub): app FastAPI, loader, contrato base
│   ├── app.py            ← app FastAPI: routing, estáticos, SSE, PWA, push
│   ├── hub.py            ← ciclo de vida de módulos + página de inicio
│   ├── module_loader.py  ← descubre y carga módulos
│   ├── module_base.py    ← clase base que todo módulo extiende
│   └── push.py           ← web push (preparado para alertas futuras)
├── modules/              ← módulos enchufables
│   ├── trading/          ← co-piloto de mercado (REST Crypto.com + UI)
│   └── music/            ← placeholder
├── static/               ← recursos de la PWA (manifest, sw, íconos)
├── deploy/               ← plist de launchd + guía de autostart
└── docs/ARQUITECTURA.md  ← cómo crear un módulo nuevo
```

El núcleo es chico y estable; la funcionalidad vive en `modules/`. Ver
[`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) para crear un módulo nuevo.

---

## 🛠️ Stack y por qué

- **FastAPI + uvicorn.** Mismo stack que el ERP `apps/proteq-hub` de ClaudeOS,
  así reusamos lo que ya conocemos (despliegue en Railway, patrón de web push,
  estructura). El núcleo es asíncrono y los módulos siguen siendo simples.
- **Módulos enchufables.** El núcleo no sabe nada de trading ni música: solo
  carga lo que esté habilitado en `config/nexus.json` y lo expone en `/m/<slug>/`.
- **Datos en vivo por polling REST + SSE.** Para el trading, un hilo de fondo
  consulta Crypto.com cada ~2s y empuja el estado al navegador por SSE. Migrar a
  WebSocket más adelante es un cambio acotado al módulo.
- **Frontend vanilla (HTML/CSS/JS + canvas).** Sin frameworks ni CDNs: carga
  rápido y funciona desde cualquier dispositivo.
- **PWA instalable.** Manifest + service worker para usar Nexus como app a
  pantalla completa en el iPhone/iPad, con web push ya cableado para alertas.

---

## 🔜 Próximos pasos

- **Trading:** alertas configurables (precio objetivo, cruce de momentum) usando
  el web push ya preparado; más pares; persistencia de histórico; y migrar el
  feed a WebSocket de Crypto.com para menor latencia.
- **Música:** primer prototipo real (biblioteca local o integración con
  Spotify/Apple Music).
- **Hub:** afinar el despliegue (Railway o launchd en el Mac mini) y sumar
  módulos nuevos.

---

*Nexus es independiente del proyecto ClaudeOS. No comparten código ni carpetas.*
