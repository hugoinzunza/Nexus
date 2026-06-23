"""Módulo de trading: co-piloto de mercado de cripto (solo lectura).

Qué hace:
  - Un hilo de fondo ("poller") consulta la API pública de Crypto.com cada
    pocos segundos y guarda el último estado del mercado en memoria.
  - Expone ese estado al navegador por dos vías:
      * /m/trading/api/state   → snapshot JSON (una foto)
      * /m/trading/api/stream  → SSE, empuja el estado en vivo
  - Calcula algunas "señales" simples (posición en el rango 24h, momentum,
    spread) como semilla de la futura inteligencia/alertas.

Importante: NO ejecuta operaciones. Es un observador.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time

from core.module_base import NexusModule
from . import cryptocom
from . import binance
from . import smc_live
from . import regime
from . import news
from . import claude_grader
from .setups_store import SetupStore

_MOD_DIR = os.path.dirname(os.path.abspath(__file__))
# Versión del despliegue (commit de Railway o arranque del proceso): viaja en el
# estado SSE para que las páginas ABIERTAS se recarguen solas tras un deploy
# (la PWA no vuelve a pedir app.js mientras la pestaña siga viva).
_APP_VERSION = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or str(int(time.time())))[:10]
# Historia profunda persistida (klines_*.json), en la RAÍZ del repo. Ruta ABSOLUTA:
# en Railway/launchd el CWD no siempre es la raíz; con ruta relativa la historia
# profunda no cargaría y caería silenciosa al feed en vivo (sin scroll/zonas).
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(_MOD_DIR)), "data")
_BACKTEST_PATH = os.path.join(_MOD_DIR, "backtest_results.json")
_POI_LAYERS_PATH = os.path.join(_MOD_DIR, "poi_layers_results.json")
_SETUP_BT_PATH = os.path.join(_MOD_DIR, "setup_backtest_results.json")
_HTF_FOR_POI = ["1D", "4h", "1h"]   # temporalidades donde se detectan POIs
# Tope de velas por petición del gráfico (paginación): acota el payload por página
# del back-load al scrollear años hacia atrás. ~3 MB en 15m, cómodo en móvil.
MAX_CHART_PAGE = 5000


class TradingModule(NexusModule):
    slug = "trading"
    title = "Trading"
    description = "Co-piloto de mercado cripto en vivo: gráficos, estructura SMC, POIs y divergencias (BTC, ETH)."
    icon = "📈"

    def __init__(self, context):
        super().__init__(context)
        cfg = self.config
        # Pares con data EN VIVO (crypto.com los sirve sin geo-block; BNB no está en
        # crypto.com → queda solo para backtest histórico, fuera de esta lista).
        self.instruments = cfg.get("instruments", [
            {"name": "BTC_USDT", "label": "BTC/USDT", "binance": "BTCUSDT", "market": "futures"},
            {"name": "ETH_USDT", "label": "ETH/USDT", "binance": "ETHUSDT", "market": "futures"},
            {"name": "SOL_USDT", "label": "SOL/USDT", "binance": "SOLUSDT", "market": "futures"},
            {"name": "XRP_USDT", "label": "XRP/USDT", "binance": "XRPUSDT", "market": "futures"},
            {"name": "ADA_USDT", "label": "ADA/USDT", "binance": "ADAUSDT", "market": "futures"},
            {"name": "DOGE_USDT", "label": "DOGE/USDT", "binance": "DOGEUSDT", "market": "futures"},
        ])
        self._inst_by_name = {i["name"]: i for i in self.instruments}
        self._binance_blocked_until = 0.0   # geo-block de Binance (HTTP 451) recordado
        self.poll_interval = int(cfg.get("poll_interval_seconds", 2))
        self.candle_refresh_every = int(cfg.get("candle_refresh_every", 6))
        self.book_depth = int(cfg.get("book_depth", 12))
        self.candle_timeframe = cfg.get("candle_timeframe", "1m")
        self.candle_count = int(cfg.get("candle_count", 400))
        # Historia del GRÁFICO y del análisis SMC (scroll/zoom hacia atrás + más
        # estructura para POIs/CDC). Se carga profunda una vez por TF y después
        # solo se refresca el tramo reciente (fusión incremental por timestamp).
        # El estado SSE sigue usando candle_count (liviano, se empuja cada 2s).
        self.chart_candle_count = int(cfg.get("chart_candle_count", 1000))

        # Temporalidades que ofrece el selector del gráfico. Son los valores que
        # acepta el parámetro `timeframe` de la API de candlestick de Crypto.com
        # (verificados: 1m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1D, 7D, 1M).
        self.ui_timeframes = cfg.get("ui_timeframes", ["1m", "5m", "15m", "1h", "4h", "1D"])
        self.ui_default_timeframe = cfg.get("ui_default_timeframe", "15m")
        if self.ui_default_timeframe not in self.ui_timeframes:
            self.ui_default_timeframe = self.ui_timeframes[0]

        # Caché de velas por (instrumento, temporalidad). Evita golpear la API en
        # cada cambio de temporalidad o con varios dispositivos abiertos a la vez.
        self._chart_cache = {}
        self._chart_lock = threading.Lock()
        # Historia PROFUNDA persistida (data/klines_*.json, años de velas) cacheada
        # en memoria por mtime. La produce el fetcher del Mac mini (que sí llega a
        # Binance) y se versiona en git, así Railway —geo-bloqueado de Binance— la
        # ve igual. Alimenta la detección de POIs lejanos (zonas bajo el precio).
        self._deep_cache = {}       # (symbol, interval) → {"candles", "mtime"}
        self._full_cache = {}       # (instrumento, tf) → {"candles", "ts"} serie completa

        # Indicador SMC en vivo: análisis cacheado, zonas de POI activas (para las
        # alertas) y estado de "precio dentro" para no spamear (una alerta por toque).
        self._smc_cache = {}        # (instrumento, tf) → {"analysis", "ts"}
        self._smc_lock = threading.Lock()
        self._poi_zones = {}        # instrumento → lista de POIs válidos (para alertas)
        self._risk_off = {}         # instrumento → estado de volatilidad anormal (risk-off)
        self._risk_off_alerted = {} # instrumento → si ya avisamos este episodio de spike
        self._risk_off_last_alert = {}  # instrumento → ts del último push (cooldown anti-spam)
        self._poi_inside = {}       # instrumento → set de claves de POI con el precio dentro
        self.smc_refresh_every = int(cfg.get("smc_refresh_every", 15))  # cada ~30s
        self.smc_alerts = bool(cfg.get("smc_alerts", True))

        # Registro de SETUPS (planes TP/SL) para forward-test: se generan en las TFs
        # de planeación y se siguen contra el precio. El Diario los muestra como tabla.
        self.setup_tfs = cfg.get("setup_tfs", ["1h", "4h"])
        self._setups = SetupStore()

        # Estado compartido. Se reemplaza por referencia (atómico bajo el GIL),
        # así las lecturas desde otros hilos siempre ven una foto consistente.
        self._state = {
            "updated": 0,
            "upstream_ok": False,
            "error": None,
            "instruments": {},
        }
        self._stop = threading.Event()
        self._thread = None
        self._bot_executor = None   # bot espejo (NexUX BOT); inerte si no hay llaves
        self._bot_sync = None       # empuja estado a Railway + trae comandos
        self._bot_sync_every = 8    # cada 8 ticks (~16s con poll 2s)
        # Símbolos Binance que el bot opera: para ellos el gatillo de TP/SL usa el
        # precio de BINANCE (donde se ejecuta), no Crypto.com, para que no diverjan.
        try:
            from modules.bot.executor import load_config as _botcfg
            self._bot_price_syms = set(_botcfg().get("pairs", []))
        except Exception:  # noqa: BLE001
            self._bot_price_syms = set()

    # --- Ciclo de vida -------------------------------------------------
    def start(self) -> None:
        self._bot_executor = self._make_bot_executor()
        self._bot_sync = self._make_bot_sync()
        self._thread = threading.Thread(target=self._poll_loop, name="trading-poller", daemon=True)
        self._thread.start()
        self.context.log(f"trading: poller iniciado ({len(self.instruments)} instrumentos, cada {self.poll_interval}s)")

    def stop(self) -> None:
        self._stop.set()

    def _make_bot_executor(self):
        """Crea el ejecutor del bot espejo. Si falla o no hay llaves de la subcuenta,
        queda inerte y NO afecta al diario (que sigue siendo solo lectura)."""
        try:
            from modules.bot.bot_store import BotStore
            from modules.bot.executor import BotExecutor
            ex = BotExecutor(BotStore(), self.context.log)
            estado = "ACTIVO" if ex.active else "inerte (sin llaves de subcuenta)"
            self.context.log(f"bot: ejecutor espejo {estado} · modo {'LIVE' if ex.live else 'dry-run'}")
            return ex
        except Exception as exc:  # noqa: BLE001
            self.context.log(f"bot: ejecutor no disponible ({exc})")
            return None

    def _make_bot_sync(self):
        """Sincronizador VPS→Railway (espejo + comandos). None si no hay ejecutor."""
        if not self._bot_executor:
            return None
        try:
            from modules.bot.sync import BotSync
            return BotSync(self._bot_executor, self.context.log)
        except Exception as exc:  # noqa: BLE001
            self.context.log(f"bot: sync no disponible ({exc})")
            return None

    # --- Poller --------------------------------------------------------
    def _poll_loop(self) -> None:
        tick = 0
        candle_cache = {}  # instrumento → últimas velas (se refresca más espaciado)
        while not self._stop.is_set():
            instruments_state = {}
            ok = True
            error = None
            for inst in self.instruments:
                name = inst["name"]
                label = inst.get("label", name)
                try:
                    ticker = cryptocom.get_ticker(name)
                    book = cryptocom.get_book(name, self.book_depth)

                    # Las velas se refrescan cada N ticks (son más pesadas y
                    # cambian más lento que el precio).
                    if tick % self.candle_refresh_every == 0 or name not in candle_cache:
                        candle_cache[name] = cryptocom.get_candles(
                            name, self.candle_timeframe, self.candle_count)
                    candles = candle_cache.get(name, [])

                    instruments_state[name] = {
                        "instrument": name,
                        "label": label,
                        "ticker": ticker,
                        "book": book,
                        "candles": candles,
                        "signals": self._compute_signals(ticker, book, candles),
                    }
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    error = str(exc)
                    # Conservamos el último estado bueno si lo había.
                    prev = self._state.get("instruments", {}).get(name)
                    if prev:
                        instruments_state[name] = prev

            # Calendario económico: evento de alto impacto inminente (ventana de peligro)
            # y próximos para el panel. Cacheado en news (30 min), barato por tick.
            try:
                event = news.danger_window()
                calendar = news.upcoming()
            except Exception:  # noqa: BLE001
                event, calendar = None, []

            self._state = {
                "updated": int(time.time() * 1000),
                "version": _APP_VERSION,
                "upstream_ok": ok,
                "error": error,
                "instruments": instruments_state,
                "calendar": calendar,
                "event_window": event,
            }

            # Indicador SMC + alertas: recalculamos las zonas de POI cada N ticks
            # (la detección sobre velas HTF es más pesada) y chequeamos toques
            # cada tick con el precio en vivo.
            for inst in self.instruments:
                name = inst["name"]
                st = instruments_state.get(name)
                if not st:
                    continue
                last = (st.get("ticker") or {}).get("last")
                if not last:
                    continue
                # Para los pares del bot, el gatillo es el precio de BINANCE (donde
                # opera), no Crypto.com → evita cierres/aperturas por divergencia de feed.
                bsym = inst.get("binance")
                if bsym and bsym in self._bot_price_syms:
                    try:
                        last = binance.last_price(bsym)
                        if st.get("ticker"):
                            st["ticker"]["last"] = last
                    except Exception:  # noqa: BLE001
                        pass  # si Binance no responde, seguimos con el de Crypto.com
                # RISK-OFF: vela anormal (guardia de volatilidad) O evento de alto impacto
                # inminente (calendario). En ambos: pausa de entradas + BE defensivo.
                spike = smc_live.volatility_spike(st.get("candles") or [])
                riskoff = spike["spike"] or bool(event)
                ro = {"spike": spike["spike"], "ratio": spike["ratio"],
                      "range_pct": spike["range_pct"], "event": event}
                self._risk_off[name] = ro
                st["risk_off"] = ro
                if tick % self.smc_refresh_every == 0 or name not in self._poi_zones:
                    try:
                        self._poi_zones[name] = smc_live.active_pois(self._htf_candles(name), last)
                    except Exception as exc:  # noqa: BLE001
                        self.context.log(f"smc: no se pudieron calcular POIs de {name}: {exc}")
                    # En risk-off NO se abren entradas nuevas (pausa).
                    if not riskoff:
                        self._record_setups(name, last)
                # En risk-off: proteger lo abierto moviendo a break-even los ganadores.
                if riskoff:
                    try:
                        reason = ("evento " + event["title"]) if event else "volatilidad"
                        prot = self._setups.protect_to_be(name, last, time.time(), reason=reason)
                        # Una alerta por episodio Y con cooldown de 20 min (anti-spam:
                        # evita el re-buzz si la volatilidad flapea sobre el umbral).
                        nowt = time.time()
                        if (not self._risk_off_alerted.get(name)
                                and nowt - self._risk_off_last_alert.get(name, 0) > 1200):
                            self._alert_risk_off(inst.get("label", name), ro, prot)
                            self._risk_off_alerted[name] = True
                            self._risk_off_last_alert[name] = nowt
                    except Exception as exc:  # noqa: BLE001
                        self.context.log(f"riskoff: {name}: {exc}")
                else:
                    self._risk_off_alerted[name] = False
                self._check_alerts(name, inst.get("label", name), last)
                # Seguimiento de los setups abiertos contra el precio en vivo (barato).
                try:
                    transitions = self._setups.track(name, last, time.time())
                    if transitions:
                        self._alert_transitions(inst.get("label", name), transitions)
                        # Bot espejo: refleja en Binance real las mismas transiciones
                        # (abre/parcial/cierra). Inerte si no hay llaves de subcuenta.
                        if self._bot_executor:
                            self._bot_executor.on_transitions(inst.get("label", name), transitions, last)
                except Exception as exc:  # noqa: BLE001
                    self.context.log(f"setups: no se pudo seguir {name}: {exc}")

            # Precalienta la caché del VIX en este hilo de fondo (la descarga no debe
            # bloquear las llamadas a la API). Cacheado en disco ~6 h.
            if tick % self.smc_refresh_every == 0:
                try:
                    regime.vix_now()
                except Exception:  # noqa: BLE001
                    pass

            # Espejo del bot → Railway (estado real) + trae comandos de la web.
            if self._bot_sync and tick % self._bot_sync_every == 0:
                try:
                    self._bot_sync.push_and_pull()
                except Exception as exc:  # noqa: BLE001
                    self.context.log(f"bot-sync: {exc}")

            tick += 1
            self._stop.wait(self.poll_interval)

    # --- SMC en vivo + alertas -----------------------------------------
    def _deep_history(self, instrument: str, timeframe: str) -> list:
        """Historia profunda persistida (data/klines_{symbol}_{interval}.json) para
        la TF pedida. Cacheada en memoria por mtime: solo se relee si el archivo
        cambió (lo actualiza el fetcher del Mac mini y lo trae el deploy). Devuelve
        [] si no hay archivo (p. ej. instrumento sin `binance` configurado)."""
        inst = self._inst_by_name.get(instrument, {})
        sym = inst.get("binance")
        if not sym:
            return []
        iv = binance.UI_TO_BINANCE.get(timeframe, timeframe)
        path = os.path.join(_DATA_DIR, f"klines_{sym}_{iv}.json")
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return []
        key = (sym, iv)
        with self._chart_lock:
            entry = self._deep_cache.get(key)
            if entry and entry["mtime"] == mtime:
                return entry["candles"]
        try:
            with open(path, "r", encoding="utf-8") as fh:
                candles = json.load(fh)
        except Exception:  # noqa: BLE001 - archivo corrupto/ausente: seguimos sin profundo
            return []
        with self._chart_lock:
            self._deep_cache[key] = {"candles": candles, "mtime": mtime}
        return candles

    def _full_candles(self, instrument: str, timeframe: str) -> list:
        """Serie COMPLETA para el gráfico: historia profunda persistida (años) con
        el tramo en vivo fusionado encima, para poder scrollear hacia atrás. Si no
        hay archivo profundo, cae al tramo en vivo. Cacheada con el mismo TTL del
        gráfico (la parte vieja es estática; solo el borde se refresca)."""
        key = (instrument, timeframe)
        now = time.time()
        with self._chart_lock:
            entry = self._full_cache.get(key)
            if entry and now - entry["ts"] < self._chart_ttl(timeframe):
                return entry["candles"]
        recent = self._candles_cached(instrument, timeframe)
        deep = self._deep_history(instrument, timeframe)
        full = self._merge_candles(deep, recent, len(deep) + len(recent) + 10) if deep else recent
        with self._chart_lock:
            self._full_cache[key] = {"candles": full, "ts": now}
        return full

    def _htf_candles(self, instrument: str) -> dict:
        """Velas de las TF de POIs: historia PROFUNDA persistida (años) con el tramo
        en vivo fusionado encima. Así la detección de POIs ve zonas lejanas —los
        OB/POI bajo el precio que importan si el mercado cae fuerte— y no solo las
        últimas ~1000 velas. Si no hay archivo profundo, cae al tramo en vivo."""
        out = {}
        for tf in _HTF_FOR_POI:
            recent = self._candles_cached(instrument, tf)
            deep = self._deep_history(instrument, tf)
            out[tf] = self._merge_candles(deep, recent, len(deep) + len(recent) + 10) if deep else recent
        return out

    def _smc_analysis(self, instrument: str, sel_tf: str) -> dict:
        key = (instrument, sel_tf)
        now = time.time()
        with self._smc_lock:
            entry = self._smc_cache.get(key)
            if entry and now - entry["ts"] < 25:
                return entry["analysis"]
        sel = self._candles_cached(instrument, sel_tf)
        htf = self._htf_candles(instrument)
        last = sel[-1]["c"] if sel else 0.0
        analysis = smc_live.analyze(sel, htf, last, sel_tf)
        # Capa de PERMISO por régimen (VIX<25 + ADX>25). NO toca la detección SMC:
        # es un semáforo sobre el plan. Solo velas CERRADAS (anti-repaint).
        try:
            gate = regime.regime_gate(smc_live.closed_candles(sel, sel_tf))
        except Exception as exc:  # noqa: BLE001 - nunca romper el análisis por el régimen
            gate = {"ok": None, "vix": None, "adx": None, "reason": "s/d"}
            self.context.log(f"regime: no disponible para {instrument} {sel_tf}: {exc}")
        analysis["regime"] = gate
        if analysis.get("tpsl"):
            analysis["tpsl"]["regime_ok"] = gate["ok"]
            analysis["tpsl"]["regime_vix"] = gate["vix"]
            analysis["tpsl"]["regime_adx"] = gate["adx"]
            analysis["tpsl"]["regime_reason"] = gate["reason"]
        with self._smc_lock:
            self._smc_cache[key] = {"analysis": analysis, "ts": now}
        return analysis

    def _check_alerts(self, name: str, label: str, last: float) -> None:
        """Alerta (web push) cuando el precio ENTRA a un POI válido sin mitigar.
        Una alerta por POI por toque: se rearma cuando el precio sale de la zona."""
        zones = self._poi_zones.get(name) or []
        inside_now = set()
        for poi in zones:
            if poi["lo"] <= last <= poi["hi"]:
                inside_now.add(self._poi_key(poi))
        prev = self._poi_inside.get(name, set())
        newly = inside_now - prev
        self._poi_inside[name] = inside_now
        if not (self.smc_alerts and newly):
            return
        # Importamos push de forma perezosa para no acoplar el módulo al core.
        try:
            from core import push
        except Exception:  # noqa: BLE001
            return
        if not push.configurado():
            return
        if not self.config.get("context_alerts", False):
            return  # solo notificamos operaciones del bot; POI/contexto en off
        for poi in zones:
            if self._poi_key(poi) in newly:
                zona = "descuento" if poi["discount"] else "premium"
                base = label.split("/")[0]
                push.notificar(
                    title=f"{base} · POI {poi['tf']}",
                    body=f"{base} tocando POI {poi['tf']} en {zona} (zona de interés, no es señal).",
                    url="/m/trading/",
                    tag=f"poi-{name}-{self._poi_key(poi)}",
                )

    def _alert_transitions(self, label: str, transitions: list) -> None:
        """Push por el ciclo de vida de un setup: entrada llenada (activo), ganada o
        perdida (las del profe se marcan). Reusa core/push como _check_alerts; no-op
        sin VAPID ni suscripciones.

        Por defecto el push de setups lo dispara la INGESTA (journal, con la data
        autoritativa del Mac mini y las suscripciones); este tracker NO notifica para
        no mandar push fantasma de setups locales que no se muestran. Se reactiva con
        NEXUS_SETUP_PUSH=tracker."""
        if os.environ.get("NEXUS_SETUP_PUSH", "ingest") != "tracker":
            return
        if not self.smc_alerts:
            return
        try:
            from core import push
        except Exception:  # noqa: BLE001
            return
        if not push.configurado():
            return
        base = label.split("/")[0]
        for t in transitions:
            src = " (profe)" if t.get("source") == "profe" else ""
            d = "Long" if t["dir"] == "long" else "Short"
            typ = t.get("type")
            st = t["status"]
            tag_extra = st
            if typ == "partial":
                # Parcial alcanzado: toca tomar beneficios y (tras TP1) mover a break-even.
                leg = t.get("leg", "TP")
                pct = int(round(t.get("frac_closed", 0) * 100))
                be = " · SL a break-even" if t.get("be") else ""
                title = f"🎯 {base} · {leg} alcanzado{src}"
                body = (f"{base} {d}: toma {pct}% (parcial en {leg}, "
                        f"{t.get('r_level')}R){be}. Acumulado +{t.get('realized_r')}R.")
                tag_extra = f"{leg}"
            elif typ == "activated":
                title = f"{base} · entrada llenada{src}"
                body = f"{base} {d} {t.get('poi_tf', '')}: el precio entró a la zona. Trade activo (no es señal)."
            elif st == "ganada":
                title = f"✅ {base} · ganada{src}"
                body = f"{base} {d} cerró el trade (+{t.get('result_r')}R con parciales)."
            elif st == "perdida":
                title = f"❌ {base} · perdida{src}"
                body = f"{base} {d} tocó el SL ({t.get('result_r')}R)."
            else:
                continue  # anulada / otras: no alertamos
            try:
                push.notificar(title=title, body=body, url="/m/bot/",
                               tag=f"setup-{t['key']}-{tag_extra}")
            except Exception as exc:  # noqa: BLE001
                self.context.log(f"alertas: no se pudo notificar {t['key']}: {exc}")

    def _alert_risk_off(self, label: str, spike: dict, protected: list) -> None:
        """Push cuando se dispara la guardia de volatilidad (vela anormal): pausa de
        entradas y cuántos trades se movieron a break-even."""
        if not self.smc_alerts:
            return
        try:
            from core import push
        except Exception:  # noqa: BLE001
            return
        if not push.configurado():
            return
        if not self.config.get("context_alerts", False):
            return  # solo operaciones del bot; alertas de contexto en off
        base = label.split("/")[0]
        n = len(protected or [])
        ev = spike.get("event")
        be = (f" · {n} trade(s) a break-even." if n else ".")
        if ev:
            title = f"📅 {base} · evento de alto impacto"
            body = f"{ev.get('title')} ({ev.get('country')}) inminente. Pausa de entradas{be}"
            tag = f"riskoff-event-{base}"
        else:
            title = f"⚠️ {base} · volatilidad anormal"
            body = f"vela {spike.get('ratio')}× lo normal ({spike.get('range_pct')}%). Pausa de entradas{be}"
            tag = f"riskoff-{base}"
        try:
            push.notificar(title=title, body=body, url="/m/trading/", tag=tag)
        except Exception as exc:  # noqa: BLE001
            self.context.log(f"riskoff alerta: {exc}")

    def _record_setups(self, name: str, last: float) -> None:
        """Para cada TF de planeación, si el indicador genera un PLAN válido (tpsl),
        lo registra deduplicado en el store para hacerle forward-test. Si el CDC
        aparece mientras el setup sigue abierto, se marca (cdc_ok) para comparar
        después el desempeño con/sin confirmación."""
        for tf in self.setup_tfs:
            try:
                analysis = self._smc_analysis(name, tf)
                plan = analysis.get("tpsl")
                if plan:
                    created = self._setups.record(plan, name, tf, last, time.time())
                    # Si NACE ya activo (precio en zona al detectarlo) no hay transición
                    # pendiente→activo que el bot escuche → disparamos su apertura a mano.
                    if created and created.get("status") == "activo" and self._bot_executor:
                        self._bot_executor.on_transitions(name, [{
                            "type": "activated", "pair": created["pair"], "dir": created["dir"],
                            "key": created["key"], "ts_created": created["ts_created"],
                            "entry": created.get("entry"), "sl": created.get("sl"),
                            "tp": created.get("tp"), "source": created.get("source"),
                        }], last)
                    if plan.get("cdc_ok"):
                        self._setups.mark_cdc(name, plan, time.time())
                    # MODO SOMBRA: Claude gradúa el setup recién creado (no interviene
                    # la decisión; solo registra una nota para validar a los ~50 trades).
                    if created and claude_grader.available():
                        self._grade_in_background(created)
            except Exception as exc:  # noqa: BLE001
                self.context.log(f"setups: no se pudo registrar {name} {tf}: {exc}")

    def _grade_in_background(self, setup: dict) -> None:
        """Lanza la graduación de Claude en un hilo (la llamada a la API no debe
        bloquear el poller). Tolerante a fallos: si algo falla, el setup queda sin
        grado y la app sigue. El grado se captura al crearse y no se actualiza."""
        snap = dict(setup)   # snapshot: no compartir el dict vivo del store

        def _run():
            try:
                g = claude_grader.grade(snap)
                if g and self._setups.attach_grade(snap["key"], snap["ts_created"], g):
                    self.context.log(f"claude(sombra): {snap['pair']} {snap['dir']} "
                                     f"nota={g.get('grade')} keep={g.get('keep')}")
            except Exception as exc:  # noqa: BLE001
                self.context.log(f"claude grader: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _poi_key(poi: dict) -> str:
        return f"{poi['tf']}:{poi['dir']}:{round(poi['lo'], 2)}:{round(poi['hi'], 2)}"

    # --- Inteligencia (semilla) ---------------------------------------
    def _compute_signals(self, ticker: dict, book: dict, candles: list) -> dict:
        """Señales simples derivadas de los datos. Punto de partida para
        futuras alertas. Todo es informativo, nunca una recomendación."""
        last = ticker.get("last", 0.0)
        high = ticker.get("high", 0.0)
        low = ticker.get("low", 0.0)

        # Posición dentro del rango del día: 0% = en el mínimo, 100% = en el máximo.
        rng = high - low
        range_pos = ((last - low) / rng * 100) if rng > 0 else 50.0

        # Spread relativo (bid/ask) en puntos básicos.
        bid = ticker.get("bid", 0.0)
        ask = ticker.get("ask", 0.0)
        mid = (bid + ask) / 2 if (bid and ask) else last
        spread_bps = ((ask - bid) / mid * 10000) if mid > 0 else 0.0

        # Momentum corto: variación % sobre las últimas 15 velas.
        momentum = 0.0
        if len(candles) >= 16:
            ref = candles[-16]["c"]
            if ref > 0:
                momentum = (last - ref) / ref * 100

        # Desequilibrio del libro: ¿hay más presión compradora o vendedora?
        bid_vol = sum(l["qty"] for l in book.get("bids", [])[:10])
        ask_vol = sum(l["qty"] for l in book.get("asks", [])[:10])
        total = bid_vol + ask_vol
        book_imbalance = ((bid_vol - ask_vol) / total * 100) if total > 0 else 0.0

        return {
            "range_pos": round(range_pos, 1),
            "spread_bps": round(spread_bps, 2),
            "momentum_15": round(momentum, 3),
            "book_imbalance": round(book_imbalance, 1),
        }

    # --- Velas bajo demanda (selector de temporalidad) -----------------
    # Segundos que dura una vela de cada temporalidad (para la caché).
    _TF_SECONDS = {
        "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
        "4h": 14400, "6h": 21600, "12h": 43200, "1D": 86400, "7D": 604800, "1M": 2592000,
    }

    def _chart_ttl(self, timeframe: str) -> float:
        """Cuánto sirve la caché antes de volver a pedir velas. Más corto en
        temporalidades chicas (para que se vean frescas), acotado a 15s."""
        secs = self._TF_SECONDS.get(timeframe, 60)
        return max(2.0, min(secs / 8.0, 15.0))

    # Tamaño del refresco incremental: cubre de sobra el lapso entre refrescos
    # (TTL ≤ 15s) y cualquier hueco razonable, sin volver a bajar toda la historia.
    _REFRESH_BATCH = 120

    @staticmethod
    def _merge_candles(old: list, new: list, cap: int) -> list:
        """Fusiona el tramo nuevo sobre la historia: por timestamp, lo nuevo pisa
        a lo viejo (la vela en curso se actualiza) y se recorta a `cap` velas."""
        by_t = {c["t"]: c for c in old}
        by_t.update({c["t"]: c for c in new})
        out = sorted(by_t.values(), key=lambda c: c["t"])
        return out[-cap:]

    def _candles_cached(self, instrument: str, timeframe: str) -> list:
        key = (instrument, timeframe)
        now = time.time()
        with self._chart_lock:
            entry = self._chart_cache.get(key)
            if entry and now - entry["ts"] < self._chart_ttl(timeframe):
                return entry["candles"]
            prev = entry["candles"] if entry else None
        # Fuente de velas/estructura: Binance si el instrumento lo configura (para
        # que el gráfico y los swings coincidan con lo que Hugo ve en BTCUSDT.P).
        # Pero Binance bloquea por geo a Railway (HTTP 451); si falla, caemos a
        # Crypto.com y recordamos el bloqueo 5 min para no reintentar en cada carga.
        # El ticker/orderbook siempre vienen de Crypto.com.
        # Historia: la PRIMERA carga por TF es profunda (chart_candle_count velas;
        # en Crypto.com pagina con end_ts porque su API entrega máx. 300 por
        # petición). Los refrescos siguientes piden solo el tramo reciente y se
        # fusionan sobre la historia ya cargada (rápido y amable con la API).
        inst = self._inst_by_name.get(instrument, {})
        want = self.chart_candle_count
        fetch_n = self._REFRESH_BATCH if prev else want
        candles = None
        if inst.get("binance") and time.time() > self._binance_blocked_until:
            try:
                candles = binance.recent_klines(inst["binance"], timeframe,
                                                limit=fetch_n,
                                                market=inst.get("market", "futures"))
            except Exception as exc:  # noqa: BLE001 - geo-block u otra falla de red
                self._binance_blocked_until = time.time() + 300
                self.context.log(f"trading: Binance no disponible ({type(exc).__name__}), "
                                 "uso Crypto.com 5 min")
        if candles is None:
            if fetch_n > cryptocom.MAX_CANDLES_PER_CALL:
                candles = cryptocom.get_candles_deep(instrument, timeframe, fetch_n)
            else:
                candles = cryptocom.get_candles(instrument, timeframe, fetch_n)
        if prev:
            candles = self._merge_candles(prev, candles, want)
        with self._chart_lock:
            self._chart_cache[key] = {"candles": candles, "ts": now}
        return candles

    # --- API HTTP ------------------------------------------------------
    def api(self, subpath, query, user=None):
        if subpath == "dashboard":
            # Centro de mando público (Home): indicadores + mercado + calendario,
            # todo de fuentes reales y cacheado en memoria. Tolerante a fallos.
            from . import dashboard as _dash
            try:
                data = _dash.get_dashboard()
            except Exception as exc:  # noqa: BLE001
                return self._json_error(502, f"no se pudo armar el dashboard: {exc}")
            # Titulares en inglés → traducir al español con Claude (cacheado).
            try:
                news = data.get("news") or []
                en = [n["title"] for n in news if n.get("lang") != "es"]
                if en:
                    from . import claude_brief as _brief
                    tr = _brief.translate_titles(en)
                    for n in news:
                        if n.get("lang") != "es":
                            n["title"] = tr.get(n["title"], n["title"])
            except Exception:  # noqa: BLE001
                pass
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            return (200, "application/json; charset=utf-8", body)
        if subpath == "brief":
            # Brief de hoy sintetizado por Claude (cacheado ~2h). Si Claude no
            # está disponible, text=None y el Home usa su brief de respaldo.
            from . import dashboard as _dash
            from . import claude_brief as _brief
            try:
                data = _dash.get_dashboard()
                text = _brief.get_brief(data)
            except Exception:  # noqa: BLE001
                text = None
            body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
            return (200, "application/json; charset=utf-8", body)
        if subpath == "state":
            body = json.dumps(self._state, ensure_ascii=False).encode("utf-8")
            return (200, "application/json; charset=utf-8", body)
        if subpath == "config":
            body = json.dumps({
                "instruments": self.instruments,
                "poll_interval": self.poll_interval,
                "timeframe": self.candle_timeframe,
                "timeframes": self.ui_timeframes,
                "default_timeframe": self.ui_default_timeframe,
            }, ensure_ascii=False).encode("utf-8")
            return (200, "application/json; charset=utf-8", body)
        if subpath == "candles":
            instrument = query.get("instrument", "")
            timeframe = query.get("timeframe", self.ui_default_timeframe)
            known = {i["name"] for i in self.instruments}
            if instrument not in known:
                return self._json_error(400, "instrumento no permitido")
            if timeframe not in self.ui_timeframes:
                return self._json_error(400, "temporalidad no válida")
            try:
                full = self._full_candles(instrument, timeframe)
            except Exception as exc:  # noqa: BLE001
                return self._json_error(502, f"no se pudieron obtener las velas: {exc}")
            # Paginación para scrollear años sin mandar todo de una (mobile-first):
            #   limit  → cuántas velas (tope MAX_CHART_PAGE),
            #   before → devuelve el tramo ANTERIOR a ese timestamp (ms) para el
            #            back-load al hacer scroll a la izquierda.
            try:
                limit = min(int(query.get("limit", self.chart_candle_count)), MAX_CHART_PAGE)
            except (TypeError, ValueError):
                limit = self.chart_candle_count
            limit = max(1, limit)   # limit<=0 no debe devolver TODA la historia
            before = query.get("before")
            if before:
                try:
                    bt = int(before)
                    subset = [c for c in full if c["t"] < bt]
                except (TypeError, ValueError):
                    subset = full
            else:
                subset = full
            candles = subset[-limit:] if limit > 0 else subset
            body = json.dumps({
                "instrument": instrument,
                "timeframe": timeframe,
                "candles": candles,
                "has_more": len(subset) > len(candles),  # ¿quedan más viejas?
            }, ensure_ascii=False).encode("utf-8")
            return (200, "application/json; charset=utf-8", body)
        if subpath == "smc":
            instrument = query.get("instrument", "")
            timeframe = query.get("timeframe", self.ui_default_timeframe)
            known = {i["name"] for i in self.instruments}
            if instrument not in known:
                return self._json_error(400, "instrumento no permitido")
            if timeframe not in self.ui_timeframes:
                return self._json_error(400, "temporalidad no válida")
            try:
                analysis = self._smc_analysis(instrument, timeframe)
            except Exception as exc:  # noqa: BLE001
                return self._json_error(502, f"no se pudo analizar SMC: {exc}")
            body = json.dumps({"instrument": instrument, **analysis},
                              ensure_ascii=False).encode("utf-8")
            return (200, "application/json; charset=utf-8", body)
        if subpath == "board":
            # Tablero multi-activo para el Home (PÚBLICO) en modo TEASER: estado de
            # mercado por moneda que engancha (sesgo, régimen, si hay setup), pero
            # SIN los números accionables (entry/SL/TP). Eso es el producto pagado:
            # ni siquiera se envían al navegador. El que quiera el plan → registro.
            tf = "1h" if "1h" in self.ui_timeframes else self.ui_default_timeframe
            insts_state = (self._state or {}).get("instruments", {})
            rows = []
            for inst in self.instruments:
                name = inst["name"]
                base = name.split("_")[0]
                tk = (insts_state.get(name) or {}).get("ticker") or {}
                row = {"symbol": base, "label": inst.get("label", base),
                       "price": tk.get("last"), "change_24h": tk.get("change"),
                       "bias": None, "regime_ok": None, "setup": "none",
                       "poi": None, "locked": False}
                try:
                    a = self._smc_analysis(name, tf)
                except Exception:  # noqa: BLE001
                    rows.append(row); continue
                rng = a.get("range") or {}
                eq, last = rng.get("eq"), row["price"]
                if eq and last:
                    row["bias"] = {"discount": last < eq,
                                   "pct": round((last - eq) / eq * 100, 2)}
                row["regime_ok"] = (a.get("regime") or {}).get("ok")
                t = a.get("tpsl")
                if t:                                   # hay plan → locked (no se envía)
                    row["locked"] = True
                    row["setup"] = "active" if t.get("state") == "activo" else "watching"
                pois = a.get("active_pois") or []
                if pois:
                    near = min(pois, key=lambda p: abs(p.get("dist_pct", 999)))
                    row["poi"] = {"tf": near.get("tf"), "discount": near.get("discount"),
                                  "dist_pct": near.get("dist_pct")}
                rows.append(row)
            body = json.dumps({"timeframe": tf, "rows": rows},
                              ensure_ascii=False).encode("utf-8")
            return (200, "application/json; charset=utf-8", body)
        if subpath == "backtest":
            if not os.path.isfile(_BACKTEST_PATH):
                return self._json_error(404, "todavía no hay resultados de backtest; corre "
                                             "python3 -m modules.trading.run_backtest")
            with open(_BACKTEST_PATH, "rb") as fh:
                return (200, "application/json; charset=utf-8", fh.read())
        if subpath == "poi_layers":
            if not os.path.isfile(_POI_LAYERS_PATH):
                return self._json_error(404, "todavía no hay experimento de capas; corre "
                                             "python3 -m modules.trading.run_poi_lab")
            with open(_POI_LAYERS_PATH, "rb") as fh:
                return (200, "application/json; charset=utf-8", fh.read())
        if subpath == "setup_backtest":
            if not os.path.isfile(_SETUP_BT_PATH):
                return self._json_error(404, "todavía no hay backtest de setups; corre "
                                             "python3 -m modules.trading.run_setup_backtest")
            with open(_SETUP_BT_PATH, "rb") as fh:
                return (200, "application/json; charset=utf-8", fh.read())
        return None

    def api_post(self, subpath, body, headers, user=None):
        """Carga MANUAL de una entrada del profe al forward-test (paper). NO coloca
        órdenes — solo registra el plan para seguirlo. Auth con NEXUS_INGEST_TOKEN
        si está configurado (igual que la ingesta del Diario)."""
        if subpath != "manual_setup":
            return None
        token = os.environ.get("NEXUS_INGEST_TOKEN", "").strip()
        if token:
            provided = headers.get("x-nexus-token", "")
            if not provided:
                auth = headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    provided = auth[7:]
            if not hmac.compare_digest(str(provided), str(token)):
                return self._json_error(401, "token inválido")
        if not isinstance(body, dict):
            return self._json_error(400, "payload inválido (JSON objeto)")
        # Normaliza el par a un instrumento conocido (BTC / BTCUSDT / BTC_USDT).
        raw = str(body.get("pair", "")).upper().replace("/", "_")
        pair = None
        for inst in self.instruments:
            nm = inst["name"]
            bnc = (inst.get("binance") or "").upper()
            base = nm.split("_")[0]
            if raw in (nm, bnc, base, base + "_USDT", base + "USDT"):
                pair = nm
                break
        if not pair:
            return self._json_error(400, f"par desconocido: {body.get('pair')!r} (usa BTC o ETH)")
        last = None
        try:
            st = (self._state or {}).get("instruments", {}).get(pair) or {}
            last = (st.get("ticker") or {}).get("last")
        except Exception:  # noqa: BLE001
            last = None
        res = self._setups.add_manual(
            pair, body.get("dir", "long"), body.get("entry"), body.get("sl"),
            body.get("tp"), tf=body.get("tf", "manual"), last_price=last,
            label=body.get("label", "profe"))
        if not res.get("ok"):
            return self._json_error(400, res.get("error", "no se pudo registrar"))
        self.context.log(f"setups: entrada MANUAL (profe) registrada {pair} {body.get('dir')} "
                         f"@ {body.get('entry')} (rr {res['rr']})")
        return (200, "application/json; charset=utf-8",
                json.dumps(res, ensure_ascii=False).encode("utf-8"))

    @staticmethod
    def _json_error(status: int, message: str):
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        return (status, "application/json; charset=utf-8", body)

    def sse(self, subpath, query, user=None):
        if subpath != "stream":
            return None
        return self._stream()

    def _stream(self):
        """Generador SSE: empuja el estado actual cada intervalo de poll."""
        # Evento inicial inmediato para que el navegador pinte algo enseguida.
        yield self._sse_event(self._state)
        last_sent = self._state.get("updated")
        idle = 0
        while not self._stop.is_set():
            time.sleep(max(0.5, self.poll_interval / 2))
            updated = self._state.get("updated")
            if updated != last_sent:
                yield self._sse_event(self._state)
                last_sent = updated
                idle = 0
            else:
                idle += 1
                if idle >= 6:  # comentario keep-alive para no cerrar la conexión
                    yield ": keep-alive\n\n"
                    idle = 0

    @staticmethod
    def _sse_event(state: dict) -> str:
        return "data: " + json.dumps(state, ensure_ascii=False) + "\n\n"

    # --- Salud ---------------------------------------------------------
    def health(self) -> dict:
        return {
            "slug": self.slug,
            "status": "ok" if self._state.get("upstream_ok") else "degradado",
            "upstream_ok": self._state.get("upstream_ok"),
            "last_update_ms": self._state.get("updated"),
            "instruments": list(self._state.get("instruments", {}).keys()),
        }


def get_module(context):
    return TradingModule(context)
