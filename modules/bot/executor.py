"""Ejecutor del bot espejo — la MANO que opera en Binance lo que el diario decide.

El diario (`setups_store.track`) es el CEREBRO: detecta activación, parciales y
cierre de cada setup contra el precio en vivo. Este ejecutor recibe esas mismas
transiciones (enriquecidas con entry/sl/tp) y las refleja en Binance Futuros real.

SEGURIDAD — esto mueve dinero real, así que:
  • Usa SOLO las llaves de la SUBCUENTA (BINANCE_TRADE_*, leídas de deploy/trade.env).
    NUNCA cae a las del colector (BINANCE_API_*, que son la cuenta principal). Si no
    hay BINANCE_TRADE_*, el ejecutor queda INERTE (en Railway, p.ej., no hace nada).
  • Arranca en DRY-RUN (config bot.live=false): calcula y registra en el libro lo que
    HARÍA, sin enviar una sola orden. El paso a real es un flag, y la primera orden
    real se confirma a mano.
  • Guardrails: idempotencia (un trade por setup), kill-switch (archivo data/bot_kill),
    una posición a la vez (regla de colisión BTC/ETH), tope de pérdida diaria, tope de
    notional por orden, leverage acotado, solo pares de la whitelist.

Sizing = reflejo del diario: riesgo fijo (base × risk_pct) por trade, notional =
riesgo / SL%, leverage derivado = risk_pct / SL%.

La BASE es el balance REAL de la subcuenta, leído del exchange (`_equity_base`). Hasta
2026-07-28 eran tres números distintos: 450 para el sizing, 1000 para los porcentajes,
y 897.61 de saldo real. El panel mostraba 0.9% donde se arriesgaba 2%, y el tope diario
del 15% era el 33% de la cuenta. Un número inventado no protege nada.

OJO con el leverage: NO cambia el riesgo por trade (ese lo fija la distancia al SL).
Solo cambia cuánto margen queda inmovilizado, y con ello cuántas posiciones caben. A 5x
un trade al 2% ocupaba el 70% de la cuenta y la puerta de margen rechazaba 7 de 19.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT, "data")
KILL_FILE = os.path.join(DATA_DIR, "bot_kill")
TRADE_ENV = os.path.join(ROOT, "deploy", "trade.env")
CONFIG_PATH = os.path.join(ROOT, "config", "nexus.json")


class BinanceOrdenAmbigua(RuntimeError):
    """No se pudo determinar si una orden se ejecutó.

    Es distinta de "falló": ante esto NADIE debe tocar el store. Se deja el trade
    como está y se reintenta en el próximo ciclo, cuando `get_order` pueda contestar.
    Asumir cualquiera de los dos lados es lo que desincroniza el libro del exchange.
    """


def ordenar_resuelto(cli, symbol: str, side: str, qty: float, client_id: str,
                 reduce_only: bool = False, position_side: str | None = None,
                 intentos: int = 3, log=print) -> dict | None:
    """Manda una orden a mercado y devuelve lo que REALMENTE pasó.

Está a nivel de MÓDULO, no de BotExecutor, porque el watchdog necesita
exactamente lo mismo y corre en otro proceso. La primera versión vivía solo
en el executor: se construyó la solución a las órdenes ambiguas y el
watchdog —el código que cierra posiciones SOLO— siguió llamando a
market_order pelado. Duplicar esto es cómo se desincronizan.

      dict → se ejecutó (total o parcialmente); trae executed_qty y avg_price
      None → con certeza NO se ejecutó; el llamador puede dejar todo como está
      raise → no se pudo determinar; el llamador NO debe asumir nada

    Por qué existe: un POST que falla no dice si falló al ir o al volver. La orden
    pudo ejecutarse y perderse la respuesta. Reintentar con el mismo id devuelve
    "duplicate", que es indistinguible de un fallo real si uno solo mira el error.
    Como el client_id lo generamos nosotros, se lo preguntamos a Binance y el caso
    ambiguo se vuelve un hecho. Esto es lo que ya nos costó plata: un cierre que
    había entrado se contabilizó como fallido y el libro quedó abierto.
    """
    ultimo: Exception | None = None
    for intento in range(intentos):
        try:
            resp = cli.market_order(symbol, side, qty, client_id=client_id,
                                    reduce_only=reduce_only,
                                    position_side=position_side)
            return {"status": resp.get("status") or "FILLED",
                    "executed_qty": float(resp.get("executedQty") or qty),
                    "avg_price": float(resp.get("avgPrice") or 0)}
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            try:
                real = cli.get_order(symbol, client_id)
            except Exception:  # noqa: BLE001
                real = "?"  # no pudimos preguntar: sigue ambiguo
            if real == "?":
                pass
            elif real is None:
                # Binance nunca la recibió → el id sigue libre, se puede reintentar
                if intento >= intentos - 1:
                    log(f"bot: orden {client_id} nunca llegó a Binance "
                             f"tras {intentos} intentos ({str(exc)[-60:]})")
                    return None
            elif float(real.get("executed_qty") or 0) > 0:
                log(f"bot: orden {client_id} SÍ se había ejecutado "
                         f"({real['status']} qty={real['executed_qty']}) pese al "
                         f"error: {str(exc)[-60:]}")
                return real
            else:
                # Existe pero sin ejecutar. El id está quemado: reintentarlo solo
                # devolvería "duplicate". Se corta y se informa el estado real.
                log(f"bot: orden {client_id} existe sin ejecutar "
                         f"({real.get('status')}); no se reintenta")
                return None
            if intento < intentos - 1:
                time.sleep(1.5 * (intento + 1))
    raise BinanceOrdenAmbigua(
        f"no se pudo determinar el estado de {client_id} en {symbol}: {ultimo}")


DEFAULTS = {
    "enabled": True,
    "live": False,                 # arranca en dry-run; flip manual a real
    "base_equity": 1000.0,         # respaldo si no se puede leer el balance real
    "base_equity_auto": True,      # leer el capital del exchange (fuente única)
    # Tope de margen AGREGADO, como fracción del capital. Distinto de max_positions:
    # ese cuenta posiciones EN RIESGO y deja fuera a las que ya tomaron parcial, que
    # siguen ocupando margen completo igual. Sin este tope se observaron 4 posiciones
    # simultáneas pidiendo 1.294,85 USDT sobre una cuenta de 897,61.
    "max_margin_pct": 0.80,
    "risk_pct": 0.02,              # 2% de riesgo por trade (reflejo del diario)
    "pairs": ["BTCUSDT", "ETHUSDT"],
    "max_leverage": 20,
    "max_notional_per_order": 6000.0,
    "min_margin": 0.0,             # piso de margen por orden en USDT (0 = sin piso)
    "max_risk_pct": 0.0,           # tope de riesgo por orden (fracción del base; 0 = sin tope)
    # Perfiles de ENTRADA (análisis del Diario 2026-07-04; None = apagado, comportamiento
    # actual). Lista de perfiles; el setup entra si CALZA CON ALGUNO. Cada perfil puede
    # tener: poi_tfs (lista), dirs (lista), min_rr (float). Ej. recomendado:
    #   [{"poi_tfs": ["4h", "1D"], "min_rr": 5}, {"dirs": ["short"], "min_rr": 5}]
    "entry_profiles": None,
    # Guarda de SLIPPAGE de entrada: si el precio actual ya se alejó del plan más de
    # este % (en contra), NO abre (el libro real mostró fills hasta +1.6% peores que el
    # plan). 0 = apagado.
    "max_entry_slippage_pct": 0.0,
    "max_daily_loss_pct": 5.0,     # -5% del base congela el bot por el día
    "fee_rate": 0.0005,            # taker estimado para comisiones del libro
    "one_position_at_a_time": True,
    # Filtro de calidad para NUEVAS entradas automáticas del indicador. El Diario
    # sigue registrando todo; el bot real opera solo A/A+ salvo que se desactive.
    "quality_filter": True,
    "quality_min_rr": 5.0,
    "quality_poi_tfs": ["1h", "4h", "1D"],
    "quality_require_disc": True,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        cfg.update((data.get("modules", {}) or {}).get("bot", {}) or {})
    except Exception:  # noqa: BLE001
        pass
    return cfg


def _passes_entry_profiles(t: dict, profiles) -> bool:
    """True si el setup calza con ALGÚN perfil de entrada. `profiles=None/[]` = filtro
    apagado (todo pasa). Cada perfil es AND de sus condiciones: poi_tfs, dirs, min_rr."""
    if not profiles:
        return True
    for p in profiles:
        tfs = p.get("poi_tfs")
        if tfs and t.get("poi_tf") not in tfs:
            continue
        dirs = p.get("dirs")
        if dirs and t.get("dir") not in dirs:
            continue
        min_rr = p.get("min_rr")
        if min_rr and (t.get("rr") or 0) < float(min_rr):
            continue
        return True
    return False


def _entry_slippage_ok(plan_entry, ref_price, direction, max_pct) -> bool:
    """False si el precio actual ya se alejó del plan MÁS de max_pct EN CONTRA
    (long: precio muy por encima de la entrada; short: muy por debajo). A favor
    no bloquea (entrar mejor que el plan no es slippage adverso). 0/None = apagado."""
    if not max_pct or not plan_entry or not ref_price:
        return True
    adverse = (ref_price - plan_entry) / plan_entry
    if direction == "short":
        adverse = -adverse
    return adverse * 100.0 <= float(max_pct)


def _trade_creds() -> tuple[str, str]:
    """Credenciales de la SUBCUENTA, solo de BINANCE_TRADE_*. Lee env y, si falta,
    deploy/trade.env. NUNCA usa BINANCE_API_* (cuenta principal)."""
    key = os.environ.get("BINANCE_TRADE_API_KEY", "").strip()
    sec = os.environ.get("BINANCE_TRADE_API_SECRET", "").strip()
    if (not key or not sec) and os.path.exists(TRADE_ENV):
        try:
            with open(TRADE_ENV, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("BINANCE_TRADE_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                    elif line.startswith("BINANCE_TRADE_API_SECRET="):
                        sec = line.split("=", 1)[1].strip()
        except OSError:
            pass
    return key, sec


class BotExecutor:
    def __init__(self, store, log, config: dict | None = None, client=None,
                 data_dir: str | None = None, kill_file: str | None = None):
        self.store = store
        self.log = log
        self.cfg = config or load_config()
        self.data_dir = data_dir or DATA_DIR
        self.kill_file = kill_file or KILL_FILE
        self._client = client
        self._client_err = None

    # --- estado --------------------------------------------------------
    @property
    def live(self) -> bool:
        return bool(self.cfg.get("live"))

    @property
    def hedge(self) -> bool:
        return bool(self.cfg.get("hedge"))

    def client(self):
        """Cliente de la subcuenta (lazy). None → ejecutor inerte (sin llaves)."""
        if self._client is not None:
            return self._client
        if self._client_err:
            return None
        key, sec = _trade_creds()
        if not key or not sec:
            self._client_err = "sin BINANCE_TRADE_* → ejecutor inerte"
            return None
        try:
            from modules.trading.binance_account import BinanceFutures
            self._client = BinanceFutures(api_key=key, api_secret=sec)
            return self._client
        except Exception as exc:  # noqa: BLE001
            self._client_err = str(exc)
            self.log(f"bot: no se pudo crear cliente de la subcuenta: {exc}")
            return None

    @property
    def active(self) -> bool:
        """Activo solo donde la config lo permite Y hay llaves de subcuenta."""
        return bool(self.cfg.get("enabled")) and self.client() is not None

    # --- entrada del poller --------------------------------------------
    def on_transitions(self, label: str, transitions: list, ref_price: float) -> None:
        """Procesa las transiciones de un par. Cada error se aísla para no romper
        el poller del diario."""
        if not self.active or not transitions:
            return
        for t in transitions:
            try:
                typ = t.get("type")
                if typ == "activated":
                    self._open(t, ref_price)
                elif typ == "partial":
                    self._reduce(t, ref_price)
                elif typ == "closed":
                    self._close(t, ref_price)
            except Exception as exc:  # noqa: BLE001
                self.log(f"bot: error procesando {t.get('key')} ({t.get('type')}): {exc}")

    # --- acciones ------------------------------------------------------
    def _open(self, t: dict, ref_price: float) -> None:
        if t.get("paper_only"):
            self.log(f"bot: {t.get('pair')} {t.get('dir')} es paper_only "
                     f"({t.get('strategy_tag') or t.get('source')}) → no abre")
            return
        symbol = self._symbol(t["pair"])
        if symbol not in self.cfg.get("pairs", []):
            return
        sid = self._setup_id(t)
        if self.store.has_trade(sid):
            return  # idempotencia: ya abrimos (o cerramos) este setup
        # Perfiles de entrada (flag, apagado por defecto): del análisis del Diario —
        # rr<5 pierde neto; el edge vive en 4h/1D y shorts. Ver DEFAULTS["entry_profiles"].
        if not _passes_entry_profiles(t, self.cfg.get("entry_profiles")):
            self.log(f"bot: {t.get('pair')} {t.get('dir')} no calza los entry_profiles "
                     f"(tf={t.get('poi_tf')}, rr={t.get('rr')}) → no abre")
            return
        # Guarda de slippage (flag, apagada por defecto): el libro real mostró entradas
        # hasta +1.6% peores que el plan (entrada a mercado tras la activación).
        if not _entry_slippage_ok(t.get("entry"), ref_price, t.get("dir"),
                                  self.cfg.get("max_entry_slippage_pct")):
            self.log(f"bot: {t.get('pair')} {t.get('dir')} precio ya se alejó del plan "
                     f"(entry {t.get('entry')} vs actual {ref_price}) → no abre")
            return
        quality = self._quality(t)
        if not self._quality_allowed(t, quality):
            self.log(f"bot: {symbol} saltado por calidad {quality['grade']} "
                     f"(tf={quality['poi_tf']}, rr={quality['rr']}, disc={quality['disc_ok']})")
            return
        if os.path.exists(self.kill_file):
            self.log(f"bot: KILL-SWITCH activo → no abre {symbol}")
            return
        open_trades = [x for x in self.store.all() if x["status"] == "abierta"]
        max_pos = int(self.cfg.get("max_positions", 1))
        # Solo cuentan para el límite las posiciones AÚN EN RIESGO (sin TP1 tomado). Las
        # que ya tomaron parcial (SL en break-even / trailing) no ocupan cupo: su riesgo
        # es ~0, así que el bot puede abrir otra en paralelo.
        #
        # CUIDADO: eso vale para el RIESGO, no para el MARGEN. Una posición en
        # break-even sigue inmovilizando margen completo en el exchange; riesgo ~0 no
        # implica margen ~0. En dry el margen es gratis y la contradicción no se ve: se
        # llegó a 4 posiciones simultáneas pidiendo 1.294,85 USDT sobre 897,61. El
        # presupuesto de margen de más abajo es la otra mitad de este límite.
        at_risk = [x for x in open_trades if not x.get("partials")]
        if len(at_risk) >= max_pos:
            self.log(f"bot: {symbol} saltado ({len(at_risk)}/{max_pos} posiciones EN RIESGO; "
                     f"{len(open_trades)-len(at_risk)} en trailing no cuentan)")
            return
        # one-way: 1 posición por símbolo. HEDGE: 1 por símbolo+lado (long y short coexisten).
        if self.hedge:
            if any(x["symbol"] == symbol and x["dir"] == t["dir"] for x in open_trades):
                self.log(f"bot: {symbol} saltado (ya hay {t['dir']} abierto en {symbol})")
                return
        elif any(x["symbol"] == symbol for x in open_trades):
            self.log(f"bot: {symbol} saltado (ya hay posición abierta en {symbol})")
            return
        if self._daily_loss_hit():
            self.log(f"bot: tope de pérdida diaria alcanzado → congelado, no abre {symbol}")
            return

        sl = float(t.get("sl") or 0)
        if sl <= 0:
            return
        cli = self.client()
        px = float(t.get("entry") or ref_price or 0)
        try:
            px = cli.mark_price(symbol)
        except Exception:  # noqa: BLE001
            pass
        if px <= 0:
            return
        # Si el precio YA está del lado perdedor del SL, no entrar (trade vencido).
        if (t["dir"] == "long" and px <= sl) or (t["dir"] == "short" and px >= sl):
            self.log(f"bot: {symbol} no abre (precio {px} ya pasó el SL {sl})")
            return
        # Dimensionar con la distancia REAL entrada→SL (precio de ejecución), no la del
        # setup: como entramos a MERCADO, si el fill queda más lejos del SL el riesgo
        # real no debe pasar del 2%. (Antes se usaba la distancia del setup y un fill
        # lejano duplicaba la pérdida vs lo planeado.)
        sl_frac = abs(px - sl) / px
        if sl_frac <= 0:
            return
        base = self._equity_base()
        risk_pct = float(self.cfg["risk_pct"])
        risk_usd = base * risk_pct
        max_lev = int(self.cfg.get("max_leverage", 20))
        lev_ovr = t.get("leverage_override")
        fixed_lev = self.cfg.get("fixed_leverage")
        if lev_ovr:
            leverage = max(1, min(int(lev_ovr), max_lev))           # override del setup
        elif fixed_lev:
            leverage = max(1, min(int(fixed_lev), max_lev))         # leverage fijo global
        else:
            leverage = max(1, min(int(round(risk_pct / sl_frac)), max_lev))  # derivado
        margin_ovr = t.get("margin_override")
        if margin_ovr:
            notional = float(margin_ovr) * leverage   # sizing FIJO: margen × leverage
        else:
            notional = risk_usd / sl_frac             # sizing por riesgo (2%)
        # Piso de MARGEN por orden: si el margen (notional/leverage) queda por debajo del
        # mínimo configurado, sube el notional para alcanzarlo. OJO: en trades de SL ancho
        # esto eleva el riesgo por encima del 2% (riesgo ≈ notional × SL%).
        min_margin = float(self.cfg.get("min_margin") or 0)
        if min_margin and notional / leverage < min_margin:
            notional = min_margin * leverage
        # Cap de RIESGO por orden: aunque el piso de margen o un margin_override suban el
        # notional, ningún trade puede arriesgar más de max_risk_pct del base (riesgo ≈
        # notional × SL%). Protege el extremo (SL muy ancho / override grande). Tiene la
        # última palabra por seguridad: puede bajar el notional por debajo del piso.
        max_risk_pct = float(self.cfg.get("max_risk_pct") or 0)
        if max_risk_pct:
            max_risk_usd = base * max_risk_pct
            if notional * sl_frac > max_risk_usd:
                self.log(f"bot: riesgo {notional*sl_frac:.0f} > tope {max_risk_usd:.0f} "
                         f"({max_risk_pct*100:.0f}% del base) → recorto notional")
                notional = max_risk_usd / sl_frac
        cap = float(self.cfg.get("max_notional_per_order") or 0)
        if cap and notional > cap:
            self.log(f"bot: notional {notional:.0f} > tope {cap:.0f} → recorto a tope")
            notional = cap
        side = "BUY" if t["dir"] == "long" else "SELL"
        qty = notional / px
        try:
            qty = cli.round_qty(symbol, qty)
            filt = cli.symbol_filters(symbol)
            if filt["min_qty"] and qty < filt["min_qty"]:
                self.log(f"bot: qty {qty} < mínimo {filt['min_qty']} en {symbol} → no abre")
                return
            if filt["min_notional"] and px * qty < filt["min_notional"]:
                self.log(f"bot: notional {px*qty:.1f} < mínimo {filt['min_notional']} en {symbol} → no abre")
                return
        except Exception as exc:  # noqa: BLE001
            self.log(f"bot: no se pudieron validar filtros de {symbol}: {exc}")
        if qty <= 0:
            return

        actual_notional = px * qty
        margin_used = actual_notional / leverage if leverage else actual_notional
        risk_usd_est = actual_notional * sl_frac
        # Presupuesto de MARGEN agregado. Cuenta TODAS las posiciones abiertas, también
        # las que ya tomaron parcial: siguen ocupando margen aunque su riesgo sea ~0.
        # Se evalúa en dry igual que en live, para que el dry-run vea las mismas
        # restricciones que el live y las dos muestras sean comparables.
        margin_pct = float(self.cfg.get("max_margin_pct") or 0)
        if margin_pct:
            ocupado = sum(float(x.get("margin_used") or 0) for x in open_trades)
            tope = base * margin_pct
            if ocupado + margin_used > tope:
                self.log(f"bot: {symbol} saltado (margen agregado {ocupado + margin_used:.0f} "
                         f"> tope {tope:.0f} = {margin_pct*100:.0f}% de {base:.0f}; "
                         f"{len(open_trades)} posiciones ocupan {ocupado:.0f})")
                return
        cap_ref = base   # misma referencia que el sizing: el porcentaje mostrado
                         # tiene que ser el que de verdad se arriesga
        risk_pct_account = (risk_usd_est / cap_ref * 100.0) if cap_ref > 0 else None
        fee_est_roundtrip = actual_notional * float(self.cfg.get("fee_rate", 0.0005)) * 2.0

        mode = "live" if self.live else "dry"
        entry_price = px
        sin_stop = False
        if mode == "live":
            margin_needed = margin_used
            try:
                avail = cli.balance_usdt().get("available", 0.0)
                if avail < margin_needed * 1.02:
                    self.log(f"bot: {symbol} saltado (margen insuficiente: req≈{margin_needed:.0f}, disp {avail:.0f})")
                    return
            except Exception:  # noqa: BLE001
                pass
            cli.set_leverage(symbol, leverage)
            pos_side = ("LONG" if t["dir"] == "long" else "SHORT") if self.hedge else None
            try:
                resp = self._ordenar(cli, symbol, side, qty, self._cid(sid, "o"),
                                     position_side=pos_side)
            except BinanceOrdenAmbigua as exc:
                # NO registramos el trade: podría no existir. Pero tampoco lo damos por
                # no abierto, porque podría existir SIN registro y sin nadie gestionando
                # su stop. La reconciliación bidireccional lo levanta en el próximo ciclo.
                self.log(f"bot: ⚠️ apertura AMBIGUA en {symbol} ({exc}); "
                         f"queda para reconciliar, no se abre otra")
                self._marcar_ambigua(sid, symbol, t["dir"], qty, leverage)
                return
            if not resp:
                self.log(f"bot: apertura de {symbol} no se ejecutó; no se registra")
                return
            entry_price = float(resp.get("avg_price") or 0) or px
            # Un fill parcial cambia el tamaño real, y con él el riesgo y el margen.
            # Registrar la qty pedida en vez de la ejecutada dejaría al libro creyendo
            # que arriesga más de lo que arriesga, y al -1R apuntando al lugar errado.
            ejecutada = float(resp.get("executed_qty") or 0)
            if ejecutada > 0 and abs(ejecutada - qty) > 1e-12:
                self.log(f"bot: fill parcial en {symbol}: pedido {qty} ejecutado {ejecutada}")
                qty = ejecutada
                actual_notional = entry_price * qty
                margin_used = actual_notional / leverage if leverage else actual_notional
                risk_usd_est = actual_notional * sl_frac
                risk_pct_account = (risk_usd_est / cap_ref * 100.0) if cap_ref > 0 else None
                fee_est_roundtrip = actual_notional * float(self.cfg.get("fee_rate", 0.0005)) * 2.0
            # STOP NATIVO. Binance movió las condicionales a /fapi/v1/algoOrder el
            # 2025-12-09; el -4120 del endpoint viejo apuntaba justo acá. Es la defensa
            # primaria del -1R: lo hace cumplir el exchange, no el polling del bot.
            #
            # FAIL-CLOSED: si la posición se abrió y el stop NO queda confirmado, se
            # cierra de inmediato. Una posición a 10x sin stop es peor que no haber
            # entrado, y dejarla "cubierta por el watchdog" en silencio es exactamente
            # cómo se pierden 4.17R: el watchdog es respaldo, no sustituto.
            if not self._proteger(cli, symbol, t["dir"], sl, qty, sid, pos_side):
                self.log(f"bot: ⚠️ {symbol} abierto SIN stop confirmado → CIERRA YA")
                cerrada = False
                try:
                    resp_c = self._ordenar(cli, symbol,
                                           "SELL" if t["dir"] == "long" else "BUY", qty,
                                           self._cid(sid, "panic"),
                                           reduce_only=not pos_side,
                                           position_side=pos_side)
                    cerrada = bool(resp_c)
                except BinanceOrdenAmbigua as exc:
                    self.log(f"bot: ⛔ {symbol} sin stop y cierre AMBIGUO ({exc})")
                if cerrada:
                    self.log(f"bot: {symbol} cerrado por falta de stop; no se registra")
                    return
                # El cierre de emergencia NO salió (o no se sabe). La posición puede estar
                # viva. Dejarla fuera del libro sería lo peor posible: sin stop del
                # exchange, sin gestión del bot y sin que el watchdog la vea, porque el
                # watchdog lee el LIBRO. Antes se caía justo acá y se daba por cerrada.
                #
                # Así que se REGISTRA igual, marcada. No es el estado que queríamos, pero
                # es un estado gestionado: el watchdog la cubre y el próximo ciclo
                # reintenta el stop nativo.
                self.log(f"bot: ⛔ {symbol} no se pudo cerrar; se REGISTRA sin stop "
                         f"nativo para que el watchdog lo cubra. Revisar a mano.")
                self._marcar_ambigua(sid, symbol, t["dir"], qty, leverage, sl=sl)
                sin_stop = True

        entry_fee = entry_price * qty * float(self.cfg.get("fee_rate", 0.0005))
        self.store.open_trade({
            "setup_id": sid, "key": t.get("key"), "symbol": symbol, "pair": t["pair"],
            "dir": t["dir"], "source": t.get("source"), "mode": mode,
            "phase_id": t.get("phase_id"), "entry_model": t.get("entry_model"),
            "activation_price": t.get("activation_price"),
            "leverage": leverage, "qty": qty, "entry_price": round(entry_price, 8),
            "setup_entry": float(t.get("entry") or px),
            "sl": sl, "tp": t.get("tp"), "risk_usd": round(risk_usd, 2),
            "risk_usd_est": round(risk_usd_est, 2),
            "risk_pct_account": round(risk_pct_account, 2) if risk_pct_account is not None else None,
            "margin_used": round(margin_used, 2),
            "notional": round(actual_notional, 2), "fee_rate": float(self.cfg.get("fee_rate", 0.0005)),
            "fee_est_roundtrip": round(fee_est_roundtrip, 4),
            "entry_fee_usd": round(entry_fee, 4), "ts": t.get("ts_created", time.time()),
            "quality": quality["grade"], "quality_reason": quality["reason"],
            "poi_tf": quality["poi_tf"], "rr": quality["rr"], "disc_ok": quality["disc_ok"],
            "sl_pct": round(sl_frac * 100, 3),
            # True = la posición quedó SIN stop del exchange. Solo la cubre el
            # watchdog. Se reintenta el stop en el próximo ciclo.
            "sin_stop_nativo": sin_stop,
        })
        self.log(f"bot[{mode}]: ABRE {side} {symbol} qty={qty} @~{entry_price:.2f} "
                 f"lev={leverage}x notional≈{px*qty:.0f} SL={sl} calidad={quality['grade']}")

    @staticmethod
    def _aid(sid: str, gen: int = 0) -> str:
        """clientAlgoId del stop nativo. DETERMINISTA y distinto del newClientOrderId
        de las órdenes MARKET: son espacios de id separados y confundirlos deja stops
        huérfanos o cancela lo que no era.

        `gen` numera los reemplazos. Tras un parcial hay que poner el stop nuevo ANTES
        de retirar el viejo, y para eso los dos tienen que poder coexistir un instante.
        """
        base = "sl" + hashlib.md5(sid.encode()).hexdigest()[:16]
        return base if not gen else f"{base}g{gen}"

    def _proteger(self, cli, symbol: str, direccion: str, sl: float, qty: float,
                  sid: str, pos_side: str | None, gen: int = 0) -> bool:
        """Coloca el stop nativo y CONFIRMA que quedó vivo Y CORRECTO.

        No basta con que el POST no haya lanzado, ni con encontrar el id: se comparan
        lado, positionSide, cantidad y triggerPrice. Un stop que existe pero cubre el
        lado equivocado, la mitad de la posición o un precio distinto es peor que
        ninguno, porque se ve como protección y nadie va a ir a mirar.
        """
        lado = "SELL" if direccion == "long" else "BUY"
        aid = self._aid(sid, gen)
        try:
            cli.algo_stop_market(symbol, lado, sl, qty=qty, position_side=pos_side,
                                 client_algo_id=aid)
        except Exception as exc:  # noqa: BLE001
            self.log(f"bot: no se pudo poner el stop nativo en {symbol}: {str(exc)[-120:]}")
            # Puede haber entrado igual y perderse la respuesta: lo dice la confirmación.
        # Se pregunta por el id EXACTO. Listar y buscar era más frágil y más caro; y
        # el path de listado que da la documentación (`algoOpenOrders`) ni siquiera
        # existe: devuelve 404. El real es `openAlgoOrders`, que queda de respaldo.
        try:
            o = cli.get_algo_order(aid)
            vivos = [o] if o else []
        except Exception:  # noqa: BLE001
            try:
                vivos = cli.algo_open_orders(symbol)
            except Exception as exc:  # noqa: BLE001
                self.log(f"bot: no se pudo confirmar el stop de {symbol}: {str(exc)[-120:]}")
                return False
        for o in vivos:
            if o.get("client_algo_id") != aid:
                continue
            if o.get("status") not in (None, "NEW"):
                self.log(f"bot: stop {aid} en estado {o.get('status')}, no protege")
                return False
            if o.get("side") != lado:
                self.log(f"bot: ⛔ stop de {symbol} con lado {o.get('side')}, esperado {lado}")
                return False
            if pos_side and o.get("position_side") not in (None, pos_side):
                self.log(f"bot: ⛔ stop de {symbol} en positionSide {o.get('position_side')}, "
                         f"esperado {pos_side}")
                return False
            if not o.get("close_position"):
                cubre = float(o.get("qty") or 0)
                if cubre < qty * 0.99:
                    self.log(f"bot: ⛔ stop de {symbol} cubre {cubre} de {qty}: "
                             f"el resto queda descubierto")
                    return False
            disparo = float(o.get("trigger_price") or 0)
            if disparo and abs(disparo - sl) > max(abs(sl) * 0.002, 1e-9):
                self.log(f"bot: ⛔ stop de {symbol} dispara en {disparo}, esperado {sl}")
                return False
            self.log(f"bot: ✅ stop nativo confirmado en {symbol} @ {disparo or sl} "
                     f"por {qty}")
            return True
        return False

    # Cada cuánto se re-lee el balance real. No hace falta más: el sizing tolera de
    # sobra que la base tenga unos minutos, y así una caída de la API no deja al bot
    # pidiendo el balance en cada ciclo.
    _EQUITY_TTL_S = 300.0

    def _equity_base(self) -> float:
        """Capital de referencia para sizing, riesgo mostrado y tope diario.

        FUENTE ÚNICA. Antes había tres números distintos —`base_equity` 450 para el
        sizing, `capital` 1000 para los porcentajes, y 897.61 de saldo real— así que
        el panel mostraba 0.9% donde se arriesgaba 2%, y el tope diario del 15% era en
        realidad 33% de la cuenta. Un número inventado no protege nada.

        Se lee del exchange y se cachea. Si no se puede leer, cae al valor del config,
        que es lo último que sí supimos.
        """
        config = float(self.cfg.get("base_equity") or 0)
        if not self.cfg.get("base_equity_auto", True):
            return config
        ahora = time.time()
        cache = getattr(self, "_equity_cache", None)
        if cache and ahora - cache[0] < self._EQUITY_TTL_S:
            return cache[1]
        try:
            cli = self.client()
            saldo = float(cli.balance_usdt().get("balance") or 0)
        except Exception:  # noqa: BLE001
            saldo = 0.0
        # Un saldo de 0 no es "cuenta vacía", casi siempre es una lectura fallida.
        # Dimensionar contra 0 sería peor que usar el último valor conocido.
        valor = saldo if saldo > 0 else config
        self._equity_cache = (ahora, valor)
        return valor

    def _marcar_ambigua(self, sid: str, symbol: str, direccion: str, qty: float,
                        leverage: int, sl: float | None = None) -> None:
        """Deja constancia de una apertura que pudo quedar viva sin registro.

        Es el único rastro que queda de una posición que quizá existe en Binance y no
        en el libro. La reconciliación lo lee para saber que un huérfano en ese símbolo
        es NUESTRO y hay que adoptarlo, en vez de tratarlo como ajeno y dejarlo sin stop.
        """
        ruta = os.path.join(self.data_dir, "bot_ambiguas.json")
        try:
            with open(ruta, encoding="utf-8") as fh:
                datos = json.load(fh)
        except (OSError, json.JSONDecodeError):
            datos = {}
        # El SL viaja con el rastro: sin él, quien adopte la posición no puede
        # ponerle stop y la adopción no sirve de nada.
        datos[sid] = {"symbol": symbol, "dir": direccion, "qty": qty,
                      "leverage": leverage, "sl": sl, "ts": time.time()}
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            tmp = ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(datos, fh, indent=1)
            os.replace(tmp, ruta)
        except OSError as exc:
            self.log(f"bot: no se pudo registrar la apertura ambigua {sid}: {exc}")

    def _ordenar(self, cli, symbol: str, side: str, qty: float, client_id: str,
                 reduce_only: bool = False, position_side: str | None = None,
                 intentos: int = 3) -> dict | None:
        """Ver `ordenar_resuelto`. Envoltorio para que el executor use su log."""
        return ordenar_resuelto(cli, symbol, side, qty, client_id,
                                reduce_only=reduce_only,
                                position_side=position_side,
                                intentos=intentos, log=self.log)

    def _reduce(self, t: dict, ref_price: float) -> None:
        sid = self._setup_id(t)
        trade = self._find_open(sid)
        if not trade:
            return
        frac = float(t.get("frac_closed") or 0)
        if frac <= 0:
            return
        symbol = trade["symbol"]
        leg = t.get("leg", "TP")
        if any(p.get("leg") == leg for p in trade.get("partials", [])):
            return
        qty = min(trade["qty"] * frac, trade.get("qty_open", trade["qty"]))
        cli = self.client()
        px = ref_price or trade["entry_price"]
        try:
            px = cli.mark_price(symbol)
            qty = cli.round_qty(symbol, qty)
        except Exception:  # noqa: BLE001
            pass
        if qty <= 0:
            return
        if trade["mode"] == "live":
            side = "SELL" if trade["dir"] == "long" else "BUY"
            pos_side = ("LONG" if trade["dir"] == "long" else "SHORT") if self.hedge else None
            try:
                resp = self._ordenar(cli, symbol, side, qty,
                                     self._cid(sid, "p" + str(len(trade["partials"]) + 1)),
                                     reduce_only=True, position_side=pos_side)
            except BinanceOrdenAmbigua as exc:
                # No sabemos si el exchange quedó reducido. Registrar el parcial dejaría
                # el libro creyendo que le queda menos de lo que le queda (o al revés).
                # Se reintenta en el próximo ciclo, cuando se pueda preguntar.
                self.log(f"bot: ⚠️ parcial AMBIGUO en {symbol} ({exc}); no se registra, "
                         f"se reintenta")
                return
            if not resp:
                self.log(f"bot: parcial de {symbol} no se ejecutó; no se registra")
                return
            ejecutada = float(resp.get("executed_qty") or 0)
            if ejecutada > 0 and abs(ejecutada - qty) > 1e-12:
                self.log(f"bot: parcial parcialmente lleno en {symbol}: "
                         f"pedido {qty} ejecutado {ejecutada}")
                qty = ejecutada
            px = float(resp.get("avg_price") or 0) or px
        fee = px * qty * trade.get("fee_rate", 0.0005)
        if not self.store.add_partial(sid, leg, qty, round(px, 8),
                                      realized_r=t.get("realized_r"), fee_usd=round(fee, 4)):
            return
        self.log(f"bot[{trade['mode']}]: PARCIAL {t.get('leg')} {symbol} qty={qty} @~{px:.2f}")
        # El parcial redujo la posición, así que el stop nativo quedó cubriendo MÁS de lo
        # que hay. Se reemplaza por uno del tamaño correcto —y a break-even si el diario
        # lo movió—. Se cancela por `clientAlgoId`, NO con cancel_all_orders: en HEDGE eso
        # se lleva por delante el stop del lado opuesto del mismo símbolo.
        if trade["mode"] == "live":
            upd = self._find_open(sid)
            rem = (upd or {}).get("qty_open", 0.0)
            nivel = trade["entry_price"] if t.get("be") else trade.get("sl")
            if rem > 0 and nivel:
                be_pos = ("LONG" if trade["dir"] == "long" else "SHORT") if self.hedge else None
                # ORDEN IMPORTANTE: primero se pone el stop NUEVO, y solo si queda
                # confirmado se retira el viejo. Al revés —cancelar y después poner— un
                # fallo del reemplazo dejaba la posición sin stop del exchange, que es
                # justo lo que el fail-closed dice que no puede pasar. Por eso `_aid`
                # numera generaciones: los dos tienen que poder coexistir un instante.
                gen = len(trade.get("partials", [])) + 1
                if self._proteger(cli, symbol, trade["dir"], float(nivel),
                                  cli.round_qty(symbol, rem), sid, be_pos, gen=gen):
                    self.log(f"bot: stop nativo re-puesto en {symbol} @ {nivel} "
                             f"por {rem} (tras {t.get('leg')})")
                    for viejo in range(gen):
                        try:
                            cli.cancel_algo_order(client_algo_id=self._aid(sid, viejo))
                        except Exception:  # noqa: BLE001
                            pass  # ya disparado, ya cancelado, o nunca existió
                else:
                    # El reemplazo no quedó: se CONSERVA el viejo. Cubre más cantidad de
                    # la que hay, que en un stop es el lado seguro —cierra lo que
                    # encuentre— y es infinitamente mejor que quedarse sin ninguno.
                    self.log(f"bot: ⚠️ no se pudo re-poner el stop de {symbol} tras el "
                             f"parcial; se CONSERVA el anterior (cubre {trade.get('qty')} "
                             f"de {rem} reales)")

    def _close(self, t: dict, ref_price: float) -> None:
        sid = self._setup_id(t)
        trade = self._find_open(sid)
        if not trade:
            return  # nunca lo abrimos (p.ej. setup anulado sin activar) → nada que cerrar
        symbol = trade["symbol"]
        qty = trade["qty_open"]
        cli = self.client()
        px = float(t.get("outcome_price") or ref_price or trade["entry_price"])
        if trade["mode"] == "live":
            if qty > 0:
                side = "SELL" if trade["dir"] == "long" else "BUY"
                pos_side = ("LONG" if trade["dir"] == "long" else "SHORT") if self.hedge else None
                try:
                    resp = self._ordenar(cli, symbol, side, cli.round_qty(symbol, qty),
                                         self._cid(sid, "c"), reduce_only=True,
                                         position_side=pos_side)
                except BinanceOrdenAmbigua as exc:
                    # CRÍTICO (C1 auditoría): NO marcar cerrado ni cancelar el stop de
                    # respaldo si no sabemos si el cierre salió → la posición podría
                    # seguir viva. Se deja ABIERTO para reintentar en el próximo cruce.
                    self.log(f"bot: ❌ cierre AMBIGUO en {symbol} ({exc}); trade sigue "
                             f"ABIERTO y con su stop; se reintentará")
                    return
                if not resp:
                    # Antes esto se confundía con el caso ambiguo: un "duplicate client
                    # order id" (que significa que el cierre SÍ había entrado) se leía
                    # como fallo y el libro quedaba abierto contra un exchange plano.
                    self.log(f"bot: cierre de {symbol} no se ejecutó; sigue abierto")
                    return
                ejecutada = float(resp.get("executed_qty") or 0)
                if ejecutada > 0 and abs(ejecutada - qty) > 1e-9:
                    self.log(f"bot: cierre parcialmente lleno en {symbol}: "
                             f"pedido {qty} ejecutado {ejecutada}; queda abierto el resto")
                    self.store.add_partial(sid, "CIERRE-PARCIAL", ejecutada,
                                           round(float(resp.get("avg_price") or px), 8),
                                           fee_usd=round(float(resp.get("avg_price") or px)
                                                         * ejecutada
                                                         * trade.get("fee_rate", 0.0005), 4))
                    return
                px = float(resp.get("avg_price") or 0) or px
            try:
                # Cierre OK → recién ahora se retira el stop. Por `clientAlgoId` y no con
                # cancel_all_orders(symbol): en HEDGE eso cancelaría también el stop del
                # lado opuesto, dejando viva una posición ajena a este cierre y sin red.
                cli.cancel_algo_order(client_algo_id=self._aid(sid))
            except Exception:  # noqa: BLE001
                pass
        fee = px * qty * trade.get("fee_rate", 0.0005)
        closed = self.store.close_trade(sid, round(px, 8), result_r=t.get("result_r"),
                                        fee_usd=round(fee, 4))
        if closed:
            self.log(f"bot[{trade['mode']}]: CIERRA {symbol} @~{px:.2f} "
                     f"pnl={closed['pnl_usd']:+.2f} USD (R diario {t.get('result_r')})")

    # --- helpers -------------------------------------------------------
    @staticmethod
    def _symbol(pair: str) -> str:
        return (pair or "").replace("_", "").upper()

    @staticmethod
    def _setup_id(t: dict) -> str:
        return f"{t.get('key')}:{t.get('ts_created')}"

    @staticmethod
    def _cid(sid: str, suffix: str) -> str:
        h = hashlib.md5(sid.encode()).hexdigest()[:16]
        return f"nx{h}{suffix}"[:36]

    def _find_open(self, sid: str) -> dict | None:
        for x in self.store.all():
            if x["setup_id"] == sid and x["status"] == "abierta":
                return x
        return None

    def _quality(self, t: dict) -> dict:
        poi_tf = t.get("poi_tf")
        try:
            rr = float(t.get("rr") or 0.0)
        except (TypeError, ValueError):
            rr = 0.0
        disc_ok = t.get("disc_ok")
        min_rr = float(self.cfg.get("quality_min_rr", 5.0))
        allowed_tfs = set(self.cfg.get("quality_poi_tfs") or ["1h", "4h", "1D"])
        require_disc = bool(self.cfg.get("quality_require_disc", True))
        rr_ok = rr >= min_rr
        tf_ok = poi_tf in allowed_tfs
        # require_disc=False significa IGNORAR disc_ok por completo (incluso False).
        # Motivo (auditoría 2026-07-05): disc_ok mide EQ GLOBAL y como veto contradice
        # la evidencia en 3 datasets (dealing_range 06-12 OOS, capa de plan, y Diario:
        # disc_ok=False +0.460R vs True +0.094R). El premium/discount correcto es el
        # LOCAL por pierna y ya viene validado dentro de detect_pois al formar el POI.
        disc_pass = (disc_ok is True) if require_disc else True
        if tf_ok and rr_ok and disc_pass:
            grade = "A+" if poi_tf in ("4h", "1D") else "A"
            reason = f"{poi_tf} + RR {rr:g} + disciplina OK"
        else:
            grade = "B"
            misses = []
            if not tf_ok:
                misses.append(f"tf {poi_tf}")
            if not rr_ok:
                misses.append(f"RR {rr:g}<{min_rr:g}")
            if not disc_pass:
                misses.append("sin disciplina premium/descuento")
            reason = ", ".join(misses) or "no cumple filtro de calidad"
        return {"grade": grade, "reason": reason, "poi_tf": poi_tf, "rr": rr, "disc_ok": disc_ok}

    def _quality_allowed(self, t: dict, quality: dict) -> bool:
        # Las entradas manuales son decisiones explícitas; no las bloquea el filtro
        # automático del backtest. Siguen pasando por todos los guardrails de riesgo.
        if t.get("source") == "profe":
            return True
        if not self.cfg.get("quality_filter", True):
            return True
        return quality.get("grade") in ("A", "A+")

    def _has_open(self) -> bool:
        return any(x["status"] == "abierta" for x in self.store.all())

    def _daily_loss_hit(self) -> bool:
        max_pct = float(self.cfg.get("max_daily_loss_pct") or 0)
        if not max_pct:
            return False
        now = time.time()
        day_start = now - (now % 86400)  # 00:00 UTC de hoy
        pnl = self.store.realized_pnl_since(day_start)
        # Sobre el capital REAL. Antes se medía contra `capital: 1000`, que no existía:
        # el 15% eran 150 USD, o sea el 17% de una cuenta de 898 y el 33% de una de 450.
        # Un freno calibrado contra un número inventado no frena donde uno cree.
        return pnl <= -(self._equity_base() * max_pct / 100.0)
