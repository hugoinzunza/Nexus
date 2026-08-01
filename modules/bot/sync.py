"""Sincronizador del bot VPS → Railway (espejo + cola de comandos).

El VPS es el único que toca Binance; la web pública corre en Railway. Para que el
panel NexUX BOT muestre el estado real sin que Hugo entre a Binance, el VPS EMPUJA
periódicamente un snapshot (balance, posiciones, órdenes, libro) a Railway, y en la
RESPUESTA recibe los comandos que dejó la web (parar / reanudar / cerrar posición),
que ejecuta en Binance. Mismo patrón que el colector del Diario, pero bidireccional.

Se invoca desde el poller del módulo trading cada N ticks (no cada 2s). Si no hay
token/URL de ingesta o no hay cliente de subcuenta, no hace nada.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .executor import DATA_DIR, KILL_FILE, TRADE_ENV  # noqa: F401  (rutas compartidas)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COLLECTOR_ENV = os.path.join(ROOT, "deploy", "collector.env")


def _from_env_or_file(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if v:
        return v
    if os.path.exists(COLLECTOR_ENV):
        try:
            with open(COLLECTOR_ENV, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith(name + "="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            pass
    return ""


class BotSync:
    def __init__(self, executor, log, testnet_executor=None):
        self.executor = executor
        self.log = log
        self.testnet_executor = testnet_executor

    # --- destino -------------------------------------------------------
    @staticmethod
    def _token() -> str:
        return _from_env_or_file("NEXUS_INGEST_TOKEN")

    @staticmethod
    def _ingest_url() -> str:
        base = _from_env_or_file("NEXUS_INGEST_URL")  # .../m/journal/api/ingest
        if not base:
            return ""
        return base.split("/m/")[0] + "/m/bot/api/ingest"

    # --- snapshot ------------------------------------------------------
    def snapshot(self) -> dict:
        ex = self.executor
        cli = ex.client()
        account, positions, orders = {}, [], []
        try:
            from modules.trading import news
            fundamental = news.fundamental_status()
        except Exception:  # noqa: BLE001
            fundamental = {"active": None, "next": None, "blocks_new_entries": False}
        if cli:
            try:
                b = cli.balance_usdt()
                account = {"balance": b["balance"], "available": b["available"],
                           "upnl": b["unrealized_pnl"]}
            except Exception as exc:  # noqa: BLE001
                account = {"error": str(exc)}
            try:
                positions = cli.positions()
            except Exception:  # noqa: BLE001
                pass
            try:
                orders = cli.open_orders()
            except Exception:  # noqa: BLE001
                pass
            # Adjuntar niveles SL/TP1/TP2/TP del libro a cada posición (Binance no los
            # conoce; vienen del setup). TP1=1R, TP2=2R desde el entry del setup.
            try:
                open_trades = [t for t in ex.store.all() if t["status"] == "abierta"]
                by_symbol_side = {
                    (t["symbol"], "LONG" if t.get("dir") == "long" else "SHORT"): t
                    for t in open_trades
                }
                by_symbol = {t["symbol"]: t for t in open_trades}
                for p in positions:
                    tr = by_symbol_side.get((p["symbol"], p.get("side"))) or by_symbol.get(p["symbol"])
                    if not tr:
                        continue
                    p["risk_usd_est"] = tr.get("risk_usd_est")
                    p["risk_pct_account"] = tr.get("risk_pct_account")
                    p["margin_used"] = tr.get("margin_used")
                    p["fee_est_roundtrip"] = tr.get("fee_est_roundtrip")
                    p["quality"] = tr.get("quality")
                    p["quality_reason"] = tr.get("quality_reason")
                    p["sl_pct"] = tr.get("sl_pct")
                    e = tr.get("setup_entry") or tr.get("entry_price")
                    sl = tr.get("sl")
                    if e and sl:
                        R = abs(e - sl)
                        lng = tr.get("dir") == "long"
                        p["sl"] = sl
                        p["tp1"] = round(e + R if lng else e - R, 4)
                        p["tp2"] = round(e + 2 * R if lng else e - 2 * R, 4)
                        p["tp"] = tr.get("tp")
            except Exception:  # noqa: BLE001
                pass
        snapshot = {
            "ts": int(time.time() * 1000),
            "live": ex.live, "active": ex.active,
            "kill": os.path.exists(getattr(ex, "kill_file", KILL_FILE)),
            "account": account, "positions": positions, "open_orders": orders,
            "summary": ex.store.summary(),
            "trades": sorted(ex.store.all(), key=lambda t: t.get("opened_at", 0), reverse=True),
            "watching": self._watching(),
            "fundamental": fundamental,
        }
        if self.testnet_executor:
            snapshot["testnet"] = self._testnet_snapshot()
        return snapshot

    def _testnet_snapshot(self) -> dict:
        ex = self.testnet_executor
        cli = ex.client()
        account, positions = {}, []
        try:
            account = cli.balance_usdt() if cli else {}
        except Exception as exc:  # noqa: BLE001
            account = {"error": str(exc)}
        try:
            positions = cli.positions() if cli else []
        except Exception:  # noqa: BLE001
            pass
        snapshot = {
            "active": ex.active,
            "live_virtual": ex.live,
            "kill": os.path.exists(ex.kill_file),
            "account": account,
            "positions": positions,
            "summary": ex.store.summary(),
            "trades": sorted(
                ex.store.all(), key=lambda t: t.get("opened_at", 0), reverse=True
            )[:50],
        }
        readiness = self._testnet_readiness(ex)
        if readiness:
            snapshot["readiness"] = readiness
        return snapshot

    @staticmethod
    def _testnet_readiness(ex) -> dict | None:
        path = os.path.join(ex.data_dir, "live_readiness.json")
        try:
            with open(path, encoding="utf-8") as fh:
                marker = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
        started = int(marker.get("started_at") or 0)
        required = int(marker.get("required_new_closed") or 5)
        candidates = [t for t in ex.store.all()
                      if int(t.get("opened_at") or 0) >= started]
        closed = [t for t in candidates if t.get("status") == "cerrada"]
        return {
            "phase": marker.get("phase"),
            "started_at": started,
            "deployed_commit": marker.get("deployed_commit"),
            "required": required,
            "closed_candidates": len(closed),
            "open_candidates": len(candidates) - len(closed),
            "status": "review" if len(closed) >= required else "collecting",
            "automatic_live": False,
        }

    def _watching(self) -> list:
        """Setups del diario EN VIGILANCIA (pendientes/activos) en los pares del bot:
        lo que el bot está esperando que se active para operar."""
        try:
            from modules.trading.setups_store import load_all
            from modules.trading import binance
        except Exception:  # noqa: BLE001
            return []
        pairs = set(self.executor.cfg.get("pairs", []))
        price_cache = {}
        out = []
        for s in load_all():
            # Solo PENDIENTES: lo que el bot espera para entrar. Los activos con
            # posición real ya salen en "Posición abierta"; los activos sin posición
            # son residuos que solo confundirían acá.
            if s.get("status") != "pendiente":
                continue
            sym = (s.get("pair") or "").replace("_", "").upper()
            if pairs and sym not in pairs:
                continue
            if sym not in price_cache:
                try:
                    price_cache[sym] = binance.last_price(sym)
                except Exception:  # noqa: BLE001
                    price_cache[sym] = None
            px = price_cache[sym]
            entry = s.get("entry")
            dist = round((px - entry) / entry * 100, 2) if (px and entry) else None
            out.append({
                "pair": s.get("pair"), "dir": s.get("dir"), "status": s.get("status"),
                "entry": s.get("entry"), "entry_lo": s.get("entry_lo"),
                "entry_hi": s.get("entry_hi"), "sl": s.get("sl"), "tp": s.get("tp"),
                "rr": s.get("rr"), "poi_tf": s.get("poi_tf"), "source": s.get("source"),
                "ts_created": s.get("ts_created"), "price_now": px, "dist_pct": dist,
            })
        out.sort(key=lambda x: (x["status"] != "pendiente", -(x.get("ts_created") or 0)))
        return out

    # --- reconciliación (red de seguridad) -----------------------------
    def reconcile(self) -> None:
        """Detecta posiciones REALES sin setup ACTIVO en el diario.

        Por defecto NO cierra nada: una desincronización del store no debe liquidar
        trades operativos. El cierre automático solo corre si la config activa
        `auto_close_orphans=true`; el cierre normal sigue viniendo de la transición
        `closed` del setup o de un comando manual explícito.
        """
        cli = self.executor.client()
        if not cli or not self.executor.live:
            return
        from modules.trading.setups_store import load_all
        hedge = self.executor.hedge
        open_keys = set()  # símbolo (one-way) o (símbolo, dir) (hedge) con setup ACTIVO
        for s in load_all():
            # Una posición real solo queda justificada por un setup ya activado. Un
            # setup pendiente es una orden mental en espera, no una posición abierta.
            if s.get("status") == "activo":
                sym = (s.get("pair") or "").replace("_", "").upper()
                open_keys.add((sym, s.get("dir")) if hedge else sym)
        pairs = set(self.executor.cfg.get("pairs", []))
        for p in cli.positions():
            sym = p["symbol"]
            if sym not in pairs:
                continue
            pdir = "long" if p["side"] == "LONG" else "short"
            has_setup = ((sym, pdir) in open_keys) if hedge else (sym in open_keys)
            if has_setup:
                continue
            if not self.executor.cfg.get("auto_close_orphans", False):
                self.log(f"bot: ⚠️ posición {sym} {pdir} sin setup activo; NO se cierra "
                         "(auto_close_orphans=false)")
                continue
            side = "SELL" if p["side"] == "LONG" else "BUY"
            pos_side = p.get("position_side") if hedge else None
            cli.market_order(sym, side, cli.round_qty(sym, p["qty"]), reduce_only=True,
                             position_side=pos_side, client_id="nxrec" + str(int(time.time()))[-7:])
            if not hedge:
                try:
                    cli.cancel_all_orders(sym)
                except Exception:  # noqa: BLE001
                    pass
            px = cli.mark_price(sym)
            for t in self.executor.store.all():
                if t["symbol"] == sym and t["dir"] == pdir and t["status"] == "abierta":
                    self.executor.store.close_trade(
                        t["setup_id"], round(px, 8), result_r=None,
                        fee_usd=round(px * p["qty"] * t.get("fee_rate", 0.0005), 4))
                    break
            self.log(f"bot: 🔧 reconciliación cerró huérfana {sym} {pdir} (sin setup abierto)")

        self._reconciliar_fantasmas(cli, hedge)
        self._adoptar_ambiguas(cli, hedge)

    def _adoptar_ambiguas(self, cli, hedge: bool) -> None:
        """Posiciones que quizá se abrieron y quedaron sin registro.

        Cuando una apertura queda ambigua, el executor deja constancia en
        `data/bot_ambiguas.json`. Ese archivo se escribía y NADIE lo leía, así que el
        rastro no servía de nada: una posición real, viva, fuera del libro y sin stop —
        el peor estado posible, y encima invisible.

        Acá se cierra el círculo. Si hay una posición real que calza con una apertura
        ambigua, se avisa fuerte y se retira del archivo: a partir de ahí es una huérfana
        normal y la ve `reconcile`, que decide según `auto_close_orphans`. Si la posición
        NO existe, la apertura efectivamente no ocurrió y el rastro se descarta.
        """
        ruta = os.path.join(
            getattr(self.executor, "data_dir", DATA_DIR), "bot_ambiguas.json"
        )
        try:
            with open(ruta, encoding="utf-8") as fh:
                pendientes = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        if not pendientes:
            return
        try:
            reales = {(p["symbol"], "long" if p["side"] == "LONG" else "short"): p
                      for p in cli.positions() if abs(float(p.get("qty") or 0)) > 0}
        except Exception as exc:  # noqa: BLE001
            self.log(f"bot: no se pudo revisar aperturas ambiguas ({exc})")
            return
        ex = self.executor
        quedan = {}
        for sid, info in (pendientes or {}).items():
            clave = (info.get("symbol"), info.get("dir"))
            pos = reales.get(clave)
            if not pos:
                self.log(f"bot: apertura ambigua {sid} no llegó a existir; se descarta")
                continue
            # EXISTE. Avisar y borrar el rastro sería lo peor: se pierde la única pista
            # de una posición viva, fuera del libro y sin stop. Hay que ADOPTARLA: darle
            # registro para que el bot y el watchdog la gestionen, y ponerle stop.
            qty = abs(float(pos.get("qty") or 0))
            sl = info.get("sl")
            entrada = float(pos.get("entry") or 0) or None
            if not (qty > 0 and sl and entrada):
                self.log(f"bot: ⛔ {clave} existe pero falta dato para adoptarla "
                         f"(qty={qty} sl={sl} entrada={entrada}). Revisar a mano.")
                quedan[sid] = info      # se CONSERVA el rastro: sigue sin resolverse
                continue
            pos_side = pos.get("position_side") if hedge else None
            protegida = ex._proteger(cli, info["symbol"], info["dir"], float(sl),
                                     qty, sid, pos_side)
            ex.store.open_trade({
                "setup_id": sid, "symbol": info["symbol"],
                "pair": info["symbol"].replace("USDT", "_USDT"),
                "dir": info["dir"], "mode": "live", "source": "adoptada",
                "leverage": info.get("leverage"), "qty": qty,
                "entry_price": entrada, "sl": float(sl),
                "risk_usd_est": round(abs(entrada - float(sl)) * qty, 2),
                "fee_rate": ex.cfg.get("fee_rate", 0.0005),
                "sin_stop_nativo": not protegida,
                "note": "adoptada por reconciliación tras apertura ambigua",
            })
            self.log(f"bot: 🔧 ADOPTADA {info['symbol']} {info['dir']} qty={qty} "
                     f"SL={sl} (stop nativo: {'sí' if protegida else 'NO, solo watchdog'})")
        try:
            tmp = ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(quedan, fh, indent=1)
            os.replace(tmp, ruta)
        except OSError:
            pass

    def _asegurar_stop_exacto(self, cli, trade: dict, real_qty: float,
                             hedge: bool) -> bool:
        """Garantiza que una posición viva tenga un stop del tamaño real actual."""
        ex = self.executor
        if not all(hasattr(ex, name) for name in
                   ("_aid", "_proteger", "_cancelar_stops_anteriores")):
            return False
        if not hasattr(cli, "algo_open_orders"):
            return False
        symbol = trade["symbol"]
        prefijo = ex._aid(trade["setup_id"])
        lado = "SELL" if trade["dir"] == "long" else "BUY"
        pos_side = ("LONG" if trade["dir"] == "long" else "SHORT") if hedge else None
        try:
            ordenes = cli.algo_open_orders(symbol)
        except Exception as exc:  # noqa: BLE001
            self.log(f"bot: no se pudo auditar el stop de {symbol}: {exc}")
            return False
        for order in ordenes:
            cid = order.get("client_algo_id") or ""
            if not cid.startswith(prefijo) or order.get("status") not in (None, "NEW"):
                continue
            if order.get("side") != lado:
                continue
            if pos_side and order.get("position_side") not in (None, pos_side):
                continue
            if order.get("close_position"):
                return True
            qty = float(order.get("qty") or 0)
            if abs(qty - real_qty) <= max(abs(real_qty) * 0.01, 1e-12):
                return True

        sl = trade.get("sl")
        if not sl:
            self.log(f"bot: ⛔ {symbol} no tiene SL para reparar su protección")
            return False
        gen = len(trade.get("partials", [])) + 150
        qty = cli.round_qty(symbol, real_qty)
        if not ex._proteger(
            cli, symbol, trade["dir"], float(sl), qty,
            trade["setup_id"], pos_side, gen=gen,
        ):
            self.log(f"bot: ⛔ no se pudo reparar el stop exacto de {symbol}")
            return False
        ex._cancelar_stops_anteriores(
            cli, symbol, trade["setup_id"], conservar=ex._aid(trade["setup_id"], gen)
        )
        self.log(f"bot: 🔧 stop de {symbol} reparado a {qty} @ {sl}")
        return True

    def _reconciliar_fantasmas(self, cli, hedge: bool) -> None:
        """El sentido inverso: trades ABIERTOS en el libro que ya no existen en Binance.

        `reconcile` recorre `cli.positions()`, así que solo ve lo que el exchange tiene.
        Un trade del libro sin posición real era invisible, y esa es exactamente la
        secuela del P0 del cierre: un cierre que SÍ había entrado se contabilizaba como
        fallido y el libro quedaba abierto contra un exchange plano. El bot seguía
        "gestionando" una posición que no existía y el P&L quedaba mal.

        Cerrar un registro del libro no manda ninguna orden: es contabilidad. Por eso
        no lo tapa `auto_close_orphans`, que existe para no liquidar posiciones VIVAS.
        """
        try:
            reales = cli.positions()
        except Exception as exc:  # noqa: BLE001
            # Sin lectura confiable no se declara nada fantasma: una caída de la API
            # borraría del libro posiciones que están perfectamente vivas.
            self.log(f"bot: reconciliación inversa saltada (no se pudo leer posiciones: {exc})")
            return
        vivas = {}
        for p in reales:
            qty = abs(float(p.get("qty") or 0))
            if qty <= 0:
                continue
            pdir = "long" if p["side"] == "LONG" else "short"
            vivas[(p["symbol"], pdir) if hedge else p["symbol"]] = qty

        for t in list(self.executor.store.all()):
            if t.get("status") != "abierta" or t.get("mode") != "live":
                continue
            clave = (t["symbol"], t["dir"]) if hedge else t["symbol"]
            real_qty = vivas.get(clave, 0.0)
            libro_qty = float(t.get("qty_open") or 0)
            if real_qty > 0:
                # ¿Del mismo tamaño? Los dos sentidos importan y por motivos distintos.
                if libro_qty > 0 and real_qty < libro_qty * 0.98:
                    # El exchange tiene MENOS: salió un parcial que no se registró. El
                    # libro cree que le queda más de lo que le queda.
                    self.log(f"bot: ⚠️ {t['symbol']} el exchange tiene {real_qty} y el "
                             f"libro {libro_qty}; se ajusta el libro a lo real")
                    self.executor.store.add_partial(
                        t["setup_id"], "AJUSTE-RECONCILIACION",
                        round(libro_qty - real_qty, 8),
                        round(cli.mark_price(t["symbol"]), 8), fee_usd=0.0)
                elif libro_qty > 0 and real_qty > libro_qty * 1.02:
                    # El exchange tiene MÁS. Suele ser un PARTIALLY_FILLED que terminó de
                    # llenarse después de que registramos la parte ejecutada. Es el más
                    # peligroso de los dos: el stop nativo se puso por la cantidad VIEJA,
                    # así que el sobrante está DESCUBIERTO.
                    #
                    # Avisar no basta: mientras nadie mire, esa exposición no tiene stop.
                    # Se AMPLÍA el stop a la cantidad real y se ajusta el libro. Si no se
                    # puede ampliar, ahí sí solo queda gritar.
                    descubierto = real_qty - libro_qty
                    self.log(f"bot: ⛔ {t['symbol']} exchange {real_qty} vs libro "
                             f"{libro_qty}: {descubierto} SIN cubrir por el stop")
                    ex = self.executor
                    pos_side = ("LONG" if t["dir"] == "long" else "SHORT") if hedge else None
                    gen = len(t.get("partials", [])) + 90   # rango propio, no pisa parciales
                    if t.get("sl") and ex._proteger(cli, t["symbol"], t["dir"],
                                                    float(t["sl"]), real_qty,
                                                    t["setup_id"], pos_side, gen=gen):
                        self.log(f"bot: 🔧 stop de {t['symbol']} ampliado a {real_qty}")
                        for viejo_gen in range(gen):
                            try:
                                cli.cancel_algo_order(
                                    client_algo_id=ex._aid(t["setup_id"], viejo_gen))
                            except Exception:  # noqa: BLE001
                                pass
                        ex.store.ajustar_qty(t["setup_id"], real_qty)
                    else:
                        self.log(f"bot: ⛔ NO se pudo cubrir {descubierto} de "
                                 f"{t['symbol']}. Revisar a mano YA.")
                self._asegurar_stop_exacto(cli, t, real_qty, hedge)
                continue

            # No hay posición. ¿Se ejecutó nuestra orden de cierre?
            precio = None
            try:
                orden = cli.get_order(t["symbol"], self.executor._cid(t["setup_id"], "c"))
            except Exception:  # noqa: BLE001
                orden = None
            if orden and float(orden.get("executed_qty") or 0) > 0:
                precio = float(orden.get("avg_price") or 0) or None
                self.log(f"bot: 🔧 {t['symbol']} el cierre SÍ se había ejecutado "
                         f"@ {precio}; el libro decía abierto")
            if precio is None:
                precio = cli.mark_price(t["symbol"])
                self.log(f"bot: 🔧 {t['symbol']} abierto en el libro y sin posición real; "
                         f"se cierra a marca {precio}")
            self.executor.store.close_trade(
                t["setup_id"], round(precio, 8), result_r=None,
                fee_usd=round(precio * libro_qty * t.get("fee_rate", 0.0005), 4))
            # confirm_pnls reemplaza después este P&L estimado por el real de Binance.

    def confirm_pnls(self) -> None:
        """Reemplaza el P&L estimado de las operaciones cerradas por el REAL de Binance
        (income: realized pnl + comisiones). Honestidad: el libro reporta lo de verdad."""
        cli = self.executor.client()
        if not cli:
            return
        for t in self.executor.store.all():
            if t["status"] != "cerrada" or t.get("pnl_confirmed"):
                continue
            if t.get("mode") != "live":
                continue  # A6: no confirmar dry contra income real (0) → pisaba el P&L simulado
            start = int(t.get("opened_at", 0)) * 1000
            end = (int(t.get("closed_at", 0)) + 5) * 1000 if t.get("closed_at") else None
            if not start:
                continue
            try:
                r = cli.realized_pnl(t["symbol"], start, end)
                self.executor.store.confirm_pnl(t["setup_id"], r["neto"], r["commission"])
                self.log(f"bot: P&L REAL {t['symbol']}: {r['neto']:+.4f} USD "
                         f"(bruto {r['pnl_bruto']:+.4f}, comisión {r['commission']:.4f})")
            except Exception as exc:  # noqa: BLE001
                self.log(f"bot: no se pudo confirmar P&L real de {t['symbol']}: {exc}")

    # --- ciclo ---------------------------------------------------------
    def push_and_pull(self) -> None:
        # Defensa adicional a TradingModule._make_bot_sync: una instancia sin cliente
        # de trading no es una fuente autorizada del estado operacional.
        if not self.executor.active or not self.executor.client():
            return
        try:
            self.reconcile()
        except Exception as exc:  # noqa: BLE001
            self.log(f"bot-sync: reconciliación falló: {exc}")
        try:
            self.confirm_pnls()
        except Exception as exc:  # noqa: BLE001
            self.log(f"bot-sync: confirmación de P&L falló: {exc}")
        url, token = self._ingest_url(), self._token()
        if not url or not token:
            return
        payload = json.dumps(self.snapshot()).encode()
        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "Content-Type": "application/json", "X-Nexus-Token": token,
            "User-Agent": "Nexus-bot-sync/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                resp = json.load(r)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            self.log(f"bot-sync: no se pudo empujar a Railway: {exc}")
            return
        for c in (resp.get("commands") or []):
            try:
                self.apply_command(c)
            except Exception as exc:  # noqa: BLE001
                self.log(f"bot-sync: error aplicando comando {c}: {exc}")

    # --- comandos desde la web -----------------------------------------
    def apply_command(self, c: dict) -> None:
        action = (c or {}).get("action")
        if action == "kill":
            open(getattr(self.executor, "kill_file", KILL_FILE), "w").close()
            self.log("bot-sync: 🛑 KILL-SWITCH activado desde la web")
        elif action == "resume":
            try:
                os.remove(getattr(self.executor, "kill_file", KILL_FILE))
            except FileNotFoundError:
                pass
            self.log("bot-sync: ▶️ bot reanudado desde la web")
        elif action == "close":
            self._close_position(c.get("symbol"))

    def _close_position(self, symbol: str | None) -> None:
        cli = self.executor.client()
        if not cli or not symbol:
            return
        pos = cli.positions([symbol])
        if not pos:
            self.log(f"bot-sync: no hay posición en {symbol} para cerrar")
            return
        hedge = self.executor.hedge
        px = pos[0]["entry"]
        try:
            px = cli.mark_price(symbol)
        except Exception:  # noqa: BLE001
            pass
        # En hedge puede haber long y short del mismo símbolo: cerramos todos los lados.
        for p in pos:
            side = "SELL" if p["side"] == "LONG" else "BUY"
            pos_side = p.get("position_side") if hedge else None
            cli.market_order(symbol, side, cli.round_qty(symbol, p["qty"]), reduce_only=True,
                             position_side=pos_side,
                             client_id="nxman" + str(int(time.time()))[-6:] + p["side"][0])
            pdir = "long" if p["side"] == "LONG" else "short"
            for t in self.executor.store.all():
                if t["symbol"] == symbol and t["status"] == "abierta" and (not hedge or t["dir"] == pdir):
                    fee = px * p["qty"] * t.get("fee_rate", 0.0005)
                    self.executor.store.close_trade(t["setup_id"], round(px, 8),
                                                    result_r=None, fee_usd=round(fee, 4))
                    t["note"] = "cierre manual desde la web"
                    break
        if not hedge:
            try:
                cli.cancel_all_orders(symbol)
            except Exception:  # noqa: BLE001
                pass
        self.log(f"bot-sync: ✋ posición {symbol} cerrada manualmente desde la web")
