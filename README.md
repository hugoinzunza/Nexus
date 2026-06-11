# ◆ Nexus

**Hub personal de Hugo**, pensado para correr 24/7 en el Mac mini. Un núcleo
modular al que se le van enchufando módulos según hagan falta. El nombre es
general a propósito: Nexus va a crecer.

Hoy arranca con dos áreas:

- **📈 Trading** — co-piloto de mercado de cripto en vivo (¡ya funcional!).
- **🎵 Música** — reservado, placeholder por ahora.

> ⚠️ **Solo lectura.** Nexus observa los mercados y muestra información. **No
> ejecuta operaciones ni mueve dinero.** Usa únicamente endpoints públicos.

---

## 🚀 Cómo arrancarlo (un comando)

No hay que instalar nada: usa el Python 3 que ya viene en macOS y **solo su
librería estándar** (cero dependencias).

```bash
cd ~/Nexus
./nexus
```

Luego abrí en el navegador:

- **Hub:** http://127.0.0.1:8800/
- **Trading:** http://127.0.0.1:8800/m/trading/
- **Música:** http://127.0.0.1:8800/m/music/

Para detenerlo: `Ctrl + C`.

Si `./nexus` no tiene permisos de ejecución:

```bash
chmod +x nexus
# o, alternativamente:
python3 -m core.hub
```

---

## 🧠 La visión

Nexus es el "cerebro central" de Hugo en su Mac mini. La idea es tener **un solo
lugar** desde donde vivan cosas distintas (trading, música, y lo que venga:
finanzas, automatización del hogar, notas, salud, etc.), cada una como un
**módulo independiente** que se puede prender, apagar o reemplazar sin tocar el
resto.

El primer módulo serio es el **co-piloto de trading**: un panel que muestra el
mercado cripto en tiempo real para acompañar tus decisiones (sin operar por vos).

---

## 📊 Módulo de Trading

Dashboard web local que muestra, para cada instrumento (por defecto **BTC/USDT**
y **ETH/USDT**):

- **Precio en vivo** con variación 24h y parpadeo verde/rojo en cada cambio.
- **Estadísticas**: máximo/mínimo 24h, mejor bid/ask, volumen.
- **Gráfico de velas** (OHLCV) dibujado en canvas, sin librerías externas.
- **Libro de órdenes** con barras de profundidad y el spread.
- **Señales** (semilla de inteligencia, todo informativo):
  - Posición dentro del rango del día (0–100%).
  - Momentum de los últimos ~15 minutos.
  - Spread en puntos básicos.
  - Desequilibrio del libro (presión compradora vs. vendedora).

**Datos:** API pública REST de [Crypto.com Exchange](https://exchange-docs.crypto.com).
El backend consulta el mercado cada par de segundos y empuja las novedades al
navegador por **SSE** (Server-Sent Events), así el panel se actualiza solo.

### Configuración

Todo se ajusta en [`config/nexus.json`](config/nexus.json):

```json
{
  "host": "127.0.0.1",
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

Para seguir más pares, agregá entradas a `instruments` (ej: `SOL_USDT`,
`XRP_USDT`). Los nombres son los que usa Crypto.com (`BASE_QUOTE`).

---

## 🧩 Arquitectura

```
Nexus/
├── nexus                 ← lanzador (./nexus)
├── config/nexus.json     ← configuración central
├── core/                 ← el núcleo (hub): servidor, loader, contrato base
│   ├── hub.py            ← punto de entrada, página de inicio
│   ├── server.py         ← servidor HTTP + routing + SSE
│   ├── module_loader.py  ← descubre y carga módulos
│   └── module_base.py    ← clase base que todo módulo extiende
├── modules/              ← módulos enchufables
│   ├── trading/          ← co-piloto de mercado (REST Crypto.com + UI)
│   └── music/            ← placeholder
└── docs/ARQUITECTURA.md  ← cómo crear un módulo nuevo
```

El núcleo es chico y estable; la funcionalidad vive en `modules/`. Ver
[`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) para crear un módulo nuevo.

---

## 🛠️ Stack y por qué

- **Python 3 + librería estándar (sin dependencias).** El Mac mini no tenía
  Node ni Homebrew, pero sí Python. Cero `pip install` = arranca con un comando
  y es fácil de mantener a largo plazo.
- **Datos en vivo por polling REST + SSE.** Implementar un cliente WebSocket sin
  librerías es complejo y frágil; con polling REST (cada ~2s) + SSE hacia el
  navegador logramos "tiempo real" suficiente para un dashboard, sin instalar
  nada. Migrar a WebSocket más adelante es un cambio acotado al módulo.
- **Frontend vanilla (HTML/CSS/JS + canvas).** Sin frameworks ni CDNs: carga
  rápido y funciona aunque el Mac mini esté sin más software.

---

## 🔜 Próximos pasos

- **Trading:** alertas configurables (precio objetivo, cruce de momentum),
  más pares, persistencia de histórico, y migrar el feed a WebSocket de
  Crypto.com para menor latencia.
- **Música:** primer prototipo real (biblioteca local o integración con
  Spotify/Apple Music).
- **Hub:** correr como servicio de macOS (launchd) para que arranque solo al
  prender el Mac mini.

---

*Nexus es independiente del proyecto ClaudeOS. No comparten código ni carpetas.*
