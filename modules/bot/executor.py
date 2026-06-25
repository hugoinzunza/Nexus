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

Sizing = reflejo del diario: riesgo fijo (base_equity × risk_pct) por trade, notional =
riesgo / SL%, leverage derivado = risk_pct / SL%. La base es FIJA (1.000), no el balance
real de la cuenta.
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

DEFAULTS = {
    "enabled": True,
    "live": False,                 # arranca en dry-run; flip manual a real
    "base_equity": 1000.0,         # base FIJA del sizing (no el balance real)
    "risk_pct": 0.02,              # 2% de riesgo por trade (reflejo del diario)
    "pairs": ["BTCUSDT", "ETHUSDT"],
    "max_leverage": 20,
    "max_notional_per_order": 6000.0,
    "max_daily_loss_pct": 5.0,     # -5% del base congela el bot por el día
    "fee_rate": 0.0005,            # taker estimado para comisiones del libro
    "one_position_at_a_time": True,
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
    def __init__(self, store, log, config: dict | None = None):
        self.store = store
        self.log = log
        self.cfg = config or load_config()
        self._client = None
        self._client_err = None

    # --- estado --------------------------------------------------------
    @property
    def live(self) -> bool:
        return bool(self.cfg.get("live"))

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
        symbol = self._symbol(t["pair"])
        if symbol not in self.cfg.get("pairs", []):
            return
        sid = self._setup_id(t)
        if self.store.has_trade(sid):
            return  # idempotencia: ya abrimos (o cerramos) este setup
        if os.path.exists(KILL_FILE):
            self.log(f"bot: KILL-SWITCH activo → no abre {symbol}")
            return
        open_trades = [x for x in self.store.all() if x["status"] == "abierta"]
        max_pos = int(self.cfg.get("max_positions", 1))
        if len(open_trades) >= max_pos:
            self.log(f"bot: {symbol} saltado ({len(open_trades)}/{max_pos} posiciones abiertas)")
            return
        if any(x["symbol"] == symbol for x in open_trades):
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
        base = float(self.cfg["base_equity"])
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

        mode = "live" if self.live else "dry"
        entry_price = px
        if mode == "live":
            margin_needed = (px * qty) / leverage if leverage else px * qty
            try:
                avail = cli.balance_usdt().get("available", 0.0)
                if avail < margin_needed * 1.02:
                    self.log(f"bot: {symbol} saltado (margen insuficiente: req≈{margin_needed:.0f}, disp {avail:.0f})")
                    return
            except Exception:  # noqa: BLE001
                pass
            cli.set_leverage(symbol, leverage)
            resp = cli.market_order(symbol, side, qty, client_id=self._cid(sid, "o"))
            entry_price = float(resp.get("avgPrice") or 0) or px
            # NOTA: esta subcuenta NO admite STOP_MARKET por API (-4120 "use Algo Order
            # API"). El SL lo gestiona el BOT: cuando el diario detecta que el precio tocó
            # el SL (track→"closed"), el ejecutor cierra a mercado. Mientras el VPS esté
            # arriba (systemd Restart=always) la posición queda protegida.

        entry_fee = entry_price * qty * float(self.cfg.get("fee_rate", 0.0005))
        self.store.open_trade({
            "setup_id": sid, "key": t.get("key"), "symbol": symbol, "pair": t["pair"],
            "dir": t["dir"], "source": t.get("source"), "mode": mode,
            "leverage": leverage, "qty": qty, "entry_price": round(entry_price, 8),
            "setup_entry": float(t.get("entry") or px),
            "sl": sl, "tp": t.get("tp"), "risk_usd": round(risk_usd, 2),
            "notional": round(px * qty, 2), "fee_rate": float(self.cfg.get("fee_rate", 0.0005)),
            "entry_fee_usd": round(entry_fee, 4), "ts": t.get("ts_created", time.time()),
        })
        self.log(f"bot[{mode}]: ABRE {side} {symbol} qty={qty} @~{entry_price:.2f} "
                 f"lev={leverage}x notional≈{px*qty:.0f} SL={sl}")

    def _reduce(self, t: dict, ref_price: float) -> None:
        sid = self._setup_id(t)
        trade = self._find_open(sid)
        if not trade:
            return
        frac = float(t.get("frac_closed") or 0)
        if frac <= 0:
            return
        symbol = trade["symbol"]
        qty = trade["qty"] * frac
        cli = self.client()
        px = ref_price or trade["entry_price"]
        try:
            px = cli.mark_price(symbol)
            qty = cli.round_qty(symbol, qty)
        except Exception:  # noqa: BLE001
            pass
        if trade["mode"] == "live" and qty > 0:
            side = "SELL" if trade["dir"] == "long" else "BUY"
            cli.market_order(symbol, side, qty, reduce_only=True,
                             client_id=self._cid(sid, "p" + str(len(trade["partials"]) + 1)))
        fee = px * qty * trade.get("fee_rate", 0.0005)
        self.store.add_partial(sid, t.get("leg", "TP"), qty, round(px, 8),
                               realized_r=t.get("realized_r"), fee_usd=round(fee, 4))
        self.log(f"bot[{trade['mode']}]: PARCIAL {t.get('leg')} {symbol} qty={qty} @~{px:.2f}")
        # Cuando el diario mueve el SL a BREAK-EVEN (tras TP1), intentamos poner un stop
        # NATIVO a la entrada con el remanente. Best-effort: si la subcuenta no admite
        # stops por API (-4120), no pasa nada y el bot sigue gestionando el cierre.
        if t.get("be") and trade["mode"] == "live":
            upd = self._find_open(sid)
            rem = (upd or {}).get("qty_open", 0.0)
            if rem > 0:
                be_side = "SELL" if trade["dir"] == "long" else "BUY"
                try:
                    cli.stop_market(symbol, be_side, trade["entry_price"],
                                    qty=cli.round_qty(symbol, rem), client_id=self._cid(sid, "be"))
                    self.log(f"bot: ✅ stop nativo a break-even en {symbol} @ {trade['entry_price']}")
                except Exception as exc:  # noqa: BLE001
                    self.log(f"bot: stop BE nativo no disponible en {symbol} ({str(exc)[-40:]}); lo gestiona el bot")

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
            try:
                if qty > 0:
                    side = "SELL" if trade["dir"] == "long" else "BUY"
                    cli.market_order(symbol, side, cli.round_qty(symbol, qty),
                                     reduce_only=True, client_id=self._cid(sid, "c"))
            except Exception as exc:  # noqa: BLE001
                self.log(f"bot: ⚠️ error cerrando {symbol}: {exc}")
            try:
                cli.cancel_all_orders(symbol)  # retira el stop de respaldo
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

    def _has_open(self) -> bool:
        return any(x["status"] == "abierta" for x in self.store.all())

    def _daily_loss_hit(self) -> bool:
        max_pct = float(self.cfg.get("max_daily_loss_pct") or 0)
        if not max_pct:
            return False
        now = time.time()
        day_start = now - (now % 86400)  # 00:00 UTC de hoy
        pnl = self.store.realized_pnl_since(day_start)
        # El tope diario es sobre el CAPITAL TOTAL (no la base de sizing por trade).
        cap_ref = float(self.cfg.get("capital") or self.cfg.get("base_equity") or 1000)
        return pnl <= -(cap_ref * max_pct / 100.0)
