#!/usr/bin/env python3
"""Escenarios dirigidos y auditables contra Binance Futures Demo.

Cada comando opera solo un simbolo previamente plano, usa fondos virtuales y deja un
artefacto inmutable. No se importa ningun env file: las credenciales Demo deben estar
ya en el entorno del proceso.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.bot.bot_store import BotStore  # noqa: E402
from modules.bot.executor import BotExecutor, ordenar_resuelto  # noqa: E402
from modules.bot.sync import BotSync  # noqa: E402
from modules.bot.testnet_evidence import (  # noqa: E402
    DEMO_URL, freeze_incident_baseline, record_scenario,
)
from modules.trading.binance_account import BinanceFutures  # noqa: E402


def require_demo(data_dir: str | Path) -> Path:
    base = os.environ.get("BINANCE_FAPI_BASE_URL", "").rstrip("/")
    if os.environ.get("NEXUS_TESTNET") != "1" or base != DEMO_URL:
        raise SystemExit(
            "ABORTADO: exige NEXUS_TESTNET=1 y "
            f"BINANCE_FAPI_BASE_URL={DEMO_URL}"
        )
    target = Path(data_dir).expanduser().resolve()
    if target.name != "testnet":
        raise SystemExit("ABORTADO: --data-dir debe terminar exactamente en /testnet")
    target.mkdir(parents=True, exist_ok=True)
    return target


def deployed_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def qty_for_notional(cli: BinanceFutures, symbol: str, notional: float) -> float:
    price = cli.mark_price(symbol)
    filters = cli.symbol_filters(symbol)
    step = filters["qty_step"] or (10 ** -filters["qty_precision"])
    minimum = max(filters["min_qty"], filters["min_notional"] / price)
    qty = math.ceil(max(minimum, notional / price) / step) * step
    return round(qty, filters["qty_precision"])


def wait_qty(cli: BinanceFutures, symbol: str, position_side: str,
             expected: float, timeout: float = 12.0) -> float:
    deadline = time.time() + timeout
    while time.time() < deadline:
        positions = {
            p["position_side"]: abs(float(p["qty"]))
            for p in cli.positions([symbol])
        }
        actual = positions.get(position_side, 0.0)
        tolerance = max(abs(expected) * 0.01, 1e-12)
        if abs(actual - expected) <= tolerance:
            return actual
        time.sleep(0.4)
    raise RuntimeError(
        f"cantidad esperada {symbol} {position_side}={expected}; "
        f"real={cli.positions([symbol])}"
    )


def require_clean_symbol(cli: BinanceFutures, symbol: str) -> None:
    positions = cli.positions([symbol])
    algos = cli.algo_open_orders(symbol)
    if positions or algos:
        raise SystemExit(
            f"ABORTADO: {symbol} debe estar plano y sin algos; "
            f"positions={positions} algos={algos}"
        )


def cancel_own_algos(cli: BinanceFutures, algo_ids: list[str]) -> None:
    for client_algo_id in algo_ids:
        try:
            cli.cancel_algo_order(client_algo_id=client_algo_id)
        except Exception:  # noqa: BLE001
            pass


def close_side(cli: BinanceFutures, symbol: str, position_side: str,
               client_id: str) -> dict | None:
    positions = {
        p["position_side"]: abs(float(p["qty"]))
        for p in cli.positions([symbol])
    }
    qty = positions.get(position_side, 0.0)
    if qty <= 0:
        return None
    side = "SELL" if position_side == "LONG" else "BUY"
    result = ordenar_resuelto(
        cli, symbol, side, cli.round_qty(symbol, qty), client_id,
        position_side=position_side,
    )
    wait_qty(cli, symbol, position_side, 0.0)
    return result


def open_protected(cli: BinanceFutures, symbol: str, position_side: str,
                   qty: float, prefix: str, stop_distance: float = 0.03) -> dict:
    open_side = "BUY" if position_side == "LONG" else "SELL"
    close_order_side = "SELL" if position_side == "LONG" else "BUY"
    opened = ordenar_resuelto(
        cli, symbol, open_side, qty, prefix + "open", position_side=position_side,
    )
    if not opened or float(opened["executed_qty"]) <= 0:
        raise RuntimeError("apertura Demo no confirmada")
    real_qty = wait_qty(cli, symbol, position_side, float(opened["executed_qty"]))
    entry = float(opened.get("avg_price") or 0) or cli.mark_price(symbol)
    trigger = entry * (1 - stop_distance if position_side == "LONG"
                       else 1 + stop_distance)
    algo_id = prefix + "stop"
    cli.algo_stop_market(
        symbol, close_order_side, trigger, qty=real_qty,
        position_side=position_side, client_algo_id=algo_id,
    )
    stop = cli.get_algo_order(algo_id)
    if not stop or stop.get("status") != "NEW":
        raise RuntimeError(f"stop Demo no confirmado: {stop}")
    if (stop.get("position_side") != position_side
            or abs(float(stop.get("qty") or 0) - real_qty) > real_qty * 0.01):
        raise RuntimeError(f"stop Demo no coincide con posicion: {stop}")
    return {"opened": opened, "qty": real_qty, "entry": entry,
            "trigger": float(stop["trigger_price"]), "stop": stop,
            "client_algo_id": algo_id}


class LostResponseClient:
    """Envia una vez y simula que la respuesta se perdio en el trayecto de vuelta."""

    def __init__(self, real: BinanceFutures):
        self.real = real
        self.sent = False

    def market_order(self, *args, **kwargs):
        if self.sent:
            raise RuntimeError("el wrapper no permite un segundo POST")
        self.sent = True
        self.real.market_order(*args, **kwargs)
        raise TimeoutError("timeout sintetico despues de aceptar la orden")

    def get_order(self, *args, **kwargs):
        return self.real.get_order(*args, **kwargs)


def scenario_ambiguous(cli: BinanceFutures, data_dir: Path, symbol: str,
                       notional: float) -> None:
    require_clean_symbol(cli, symbol)
    stamp = str(int(time.time() * 1000))[-9:]
    prefix = f"nxa{stamp}"
    algo_ids = [prefix + "stop"]
    try:
        protected = open_protected(
            cli, symbol, "LONG", qty_for_notional(cli, symbol, notional), prefix,
        )
        before = wait_qty(cli, symbol, "LONG", protected["qty"])
        close_id = prefix + "close"
        recovered = ordenar_resuelto(
            LostResponseClient(cli), symbol, "SELL", protected["qty"], close_id,
            position_side="LONG", intentos=1,
        )
        after = wait_qty(cli, symbol, "LONG", 0.0)
        confirmed = cli.get_order(symbol, close_id)
        if not recovered or not confirmed or float(confirmed["executed_qty"]) <= 0:
            raise RuntimeError("la orden ambigua no fue recuperada por client_id")
        record_scenario(data_dir, "hedge_ambiguous_resolved", {
            "symbol": symbol, "position_side": "LONG", "qty_before": before,
            "qty_after": after, "client_id": close_id,
            "order_id": confirmed.get("order_id"),
            "recovered_status": recovered.get("status"),
            "synthetic_fault": "response_lost_after_exchange_acceptance",
        }, deployed_commit=deployed_commit())
    finally:
        cancel_own_algos(cli, algo_ids)
        close_side(cli, symbol, "LONG", prefix + "cleanup")


def observe_current(cli: BinanceFutures, data_dir: Path) -> None:
    """Acredita solo hechos ya presentes; no envia ordenes ni cambia configuracion."""
    store = BotStore(path=str(data_dir / "bot_trades.json"))
    trades = {
        (trade.get("symbol"), "LONG" if trade.get("dir") == "long" else "SHORT"): trade
        for trade in store.all() if trade.get("status") == "abierta"
    }
    matches = []
    for position in cli.positions():
        position_side = position.get("position_side") or position.get("side")
        trade = trades.get((position.get("symbol"), position_side))
        if not trade:
            continue
        qty = abs(float(position.get("qty") or 0))
        stops = [
            order for order in cli.algo_open_orders(position["symbol"])
            if order.get("status") == "NEW"
            and order.get("position_side") == position_side
            and abs(float(order.get("qty") or 0) - qty) <= max(qty * 0.01, 1e-12)
        ]
        if not stops:
            continue
        matches.append({
            "setup_id": trade.get("setup_id"), "symbol": position["symbol"],
            "position_side": position_side, "position_qty": qty,
            "ledger_qty_open": float(trade.get("qty_open") or 0),
            "stop": stops[0], "partials": trade.get("partials") or [],
        })
    if not matches:
        raise RuntimeError("no existe posicion Demo trazable con stop exacto")
    native = matches[0]
    record_scenario(data_dir, "native_stop_confirmed", native,
                    deployed_commit=deployed_commit())
    partial = next((item for item in matches if item["partials"]), None)
    if not partial:
        raise RuntimeError("no existe remanente Demo con parcial y stop exacto")
    if abs(partial["ledger_qty_open"] - partial["position_qty"]) > max(
            partial["position_qty"] * 0.01, 1e-12):
        raise RuntimeError("el remanente del libro no coincide con Binance")
    record_scenario(data_dir, "partial_stop_resized", partial,
                    deployed_commit=deployed_commit())


def baseline_current_incidents(data_dir: Path) -> None:
    store = BotStore(path=str(data_dir / "bot_trades.json"))
    incidents = [trade for trade in store.all() if trade.get("critical_execution_error")]
    freeze_incident_baseline(data_dir, incidents)


def scenario_restart(cli: BinanceFutures, data_dir: Path, symbol: str,
                     notional: float) -> None:
    require_clean_symbol(cli, symbol)
    stamp = str(int(time.time() * 1000))[-9:]
    prefix = f"nxr{stamp}"
    runtime = data_dir / "scenario_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    store_path = runtime / f"restart-{stamp}.json"
    checkpoint = runtime / f"restart-{stamp}-checkpoint.json"
    result_path = runtime / f"restart-{stamp}-result.json"
    algo_ids = [prefix + "stop"]
    try:
        protected = open_protected(
            cli, symbol, "LONG", qty_for_notional(cli, symbol, notional), prefix,
        )
        sid = f"scenario:restart:{stamp}"
        BotStore(path=str(store_path)).open_trade({
            "setup_id": sid, "symbol": symbol, "pair": symbol.replace("USDT", "_USDT"),
            "dir": "long", "mode": "live", "qty": protected["qty"],
            "entry_price": protected["entry"], "sl": protected["trigger"],
            "lifecycle": "protected", "ts": int(time.time()),
        })
        reconciliation_stop = BotExecutor(
            None, lambda _message: None, config={}
        )._aid(sid, 150)
        algo_ids.append(reconciliation_stop)
        checkpoint.write_text(json.dumps({
            "symbol": symbol, "setup_id": sid, "qty": protected["qty"],
            "store_path": str(store_path), "result_path": str(result_path),
        }), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "_restart-child",
             "--data-dir", str(data_dir), "--checkpoint", str(checkpoint)],
            cwd=ROOT, text=True, capture_output=True, timeout=45, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"proceso de reconciliacion fallo: {proc.stderr[-500:]}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("reconciled"):
            raise RuntimeError(f"reconciliacion no confirmada: {result}")
        record_scenario(data_dir, "restart_reconciled", {
            "symbol": symbol, "position_side": "LONG", "qty": protected["qty"],
            "parent_pid": os.getpid(), "child_pid": result.get("pid"),
            "store_reloaded": True, "position_matched": result.get("position_matched"),
            "stop_matched": result.get("stop_matched"),
        }, deployed_commit=deployed_commit())
    finally:
        cancel_own_algos(cli, algo_ids)
        close_side(cli, symbol, "LONG", prefix + "cleanup")
        for path in (checkpoint, result_path, store_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def restart_child(data_dir: Path, checkpoint_path: Path) -> None:
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    store = BotStore(path=checkpoint["store_path"])
    cli = BinanceFutures()
    executor = BotExecutor(
        store, lambda message: print(message, file=sys.stderr),
        config={"enabled": True, "live": True, "hedge": True,
                "pairs": [checkpoint["symbol"]], "auto_close_orphans": False},
        client=cli, data_dir=str(data_dir), kill_file=str(data_dir / "bot_kill"),
    )
    BotSync(executor, executor.log)._reconciliar_fantasmas(cli, True)
    trade = store.get_open(checkpoint["setup_id"])
    positions = {
        p["position_side"]: abs(float(p["qty"]))
        for p in cli.positions([checkpoint["symbol"]])
    }
    qty = float(checkpoint["qty"])
    position_matched = abs(positions.get("LONG", 0.0) - qty) <= qty * 0.01
    prefix = executor._aid(checkpoint["setup_id"])
    stop_matched = any(
        (order.get("client_algo_id") or "").startswith(prefix)
        and order.get("status") == "NEW"
        and abs(float(order.get("qty") or 0) - qty) <= qty * 0.01
        for order in cli.algo_open_orders(checkpoint["symbol"])
    )
    result = {"pid": os.getpid(), "store_reloaded": bool(trade),
              "position_matched": position_matched, "stop_matched": stop_matched,
              "reconciled": bool(trade and position_matched and stop_matched)}
    Path(checkpoint["result_path"]).write_text(json.dumps(result), encoding="utf-8")
    if not result["reconciled"]:
        raise SystemExit(2)


def scenario_trigger(cli: BinanceFutures, data_dir: Path, symbol: str,
                     notional: float, timeout: float, distance: float) -> None:
    require_clean_symbol(cli, symbol)
    stamp = str(int(time.time() * 1000))[-9:]
    prefix = f"nxt{stamp}"
    algo_ids = [prefix + "stop"]
    started = int(time.time() * 1000)
    try:
        protected = open_protected(
            cli, symbol, "LONG", qty_for_notional(cli, symbol, notional), prefix,
            stop_distance=distance,
        )
        deadline = time.time() + timeout
        terminal = None
        while time.time() < deadline:
            position_qty = sum(
                abs(float(p["qty"])) for p in cli.positions([symbol])
                if p["position_side"] == "LONG"
            )
            terminal = cli.get_algo_order(protected["client_algo_id"])
            if position_qty == 0 and terminal and terminal.get("status") != "NEW":
                break
            time.sleep(1.0)
        else:
            record_scenario(data_dir, "native_stop_triggered", {
                "symbol": symbol, "reason": "timeout_waiting_native_trigger",
                "timeout_seconds": timeout, "stop": terminal,
            }, status="failed", deployed_commit=deployed_commit())
            raise RuntimeError("el stop nativo no se disparo dentro del timeout")
        fills = cli.user_trades(symbol, start_ms=started - 2_000)
        record_scenario(data_dir, "native_stop_triggered", {
            "symbol": symbol, "position_side": "LONG", "qty": protected["qty"],
            "trigger_price": protected["trigger"], "terminal_stop": terminal,
            "position_qty_after": 0.0, "fills_after_open": len(fills),
        }, deployed_commit=deployed_commit())
    finally:
        cancel_own_algos(cli, algo_ids)
        close_side(cli, symbol, "LONG", prefix + "cleanup")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=(
        "baseline-current-incidents", "observe-current", "native-stop-triggered",
        "restart-reconciled",
        "hedge-ambiguous-resolved", "_restart-child",
    ))
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--symbol", default="ADAUSDT")
    parser.add_argument("--notional", type=float, default=15.0)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--stop-distance", type=float, default=0.001)
    parser.add_argument("--checkpoint")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = require_demo(args.data_dir)
    if args.command == "baseline-current-incidents":
        baseline_current_incidents(data_dir)
        print("OK: baseline historico de incidentes congelado")
        return 0
    if args.command == "_restart-child":
        if not args.checkpoint:
            raise SystemExit("--checkpoint es obligatorio")
        restart_child(data_dir, Path(args.checkpoint))
        return 0
    cli = BinanceFutures()
    if not cli.position_mode():
        raise SystemExit("ABORTADO: Binance Demo debe estar previamente en modo HEDGE")
    if args.command == "observe-current":
        observe_current(cli, data_dir)
        print(f"OK: evidencia actual registrada en {data_dir / 'scenario_evidence'}")
        return 0
    cli.set_leverage(args.symbol, 3)
    if args.command == "native-stop-triggered":
        scenario_trigger(cli, data_dir, args.symbol, args.notional,
                         args.timeout, args.stop_distance)
    elif args.command == "restart-reconciled":
        scenario_restart(cli, data_dir, args.symbol, args.notional)
    else:
        scenario_ambiguous(cli, data_dir, args.symbol, args.notional)
    print(f"OK: {args.command} registrado en {data_dir / 'scenario_evidence'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
