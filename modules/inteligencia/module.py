"""Inteligencia — vista "Acción del precio".

Traduce a pantalla los conceptos del curso CreceTrader que SÍ tienen definición
objetiva: apertura anual y su rejilla, apertura semanal, pivotes confirmados y el
vacío disponible hasta el primer obstáculo. Los apuntes y la auditoría están en
`research/crecetrader/`.

QUÉ NO ES ESTE MÓDULO: no emite señales, no toca el bot, no crea ni cancela órdenes,
no lee credenciales. Solo consulta klines PÚBLICAS de Binance (sin firma) y calcula.
Todo lo que muestra va rotulado como research sin validar, porque eso es exactamente
lo que es: del curso completo, cero conceptos tienen evidencia cuantitativa propia.

Por qué existe igual, si nada está validado: los niveles son mecánicos y auditables
—la apertura anual del 1 de enero es un hecho, no una opinión— y verlos en pantalla
es lo que permite decidir qué vale la pena estudiar. Lo que NO se hace es dejar que
la pantalla insinúe que un nivel funciona.
"""
from __future__ import annotations

import json
import os
import threading
import time

from core.module_base import NexusModule
from modules.journal import binance_client as bc
from . import precio as P

ROOT_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Klines públicas de futuros: mismo mercado que opera el bot, sin firma y sin llaves.
# Se usa el endpoint público a propósito: este módulo no debe poder tocar la cuenta.
FAPI_KLINES = "/fapi/v1/klines"
TTL_VELAS = 300          # 5 min: los niveles son de mediano plazo, no hace falta más
MAX_VELAS = 500

# Pivotes: el curso enseña 5+1+5. No se toma como verdad —NexUX ya usa 10 para rangos
# y 2 para el CDC, y la justificación del curso (cinco días bursátiles) no traslada a
# cripto 24/7— pero es el parámetro del método y la pantalla dice cuál usó.
PIV_CURSO = 5


class InteligenciaModule(NexusModule):
    slug = "inteligencia"
    title = "Inteligencia"
    description = "Acción del precio: apertura anual, rejilla, estructura y vacío disponible. Research, sin validar."
    icon = "AP"

    def __init__(self, context):
        super().__init__(context)
        self._lock = threading.Lock()
        self._cache: dict = {}

    def public_dir(self):
        return os.path.join(os.path.dirname(__file__), "public")

    # --- datos ---------------------------------------------------------
    def _velas(self, symbol: str, tf: str, limit: int = MAX_VELAS) -> tuple:
        """Klines públicas con caché. Devuelve `(velas, fuente)`.

        Sin firma y sin credenciales: este módulo no puede tocar la cuenta.

        Y con respaldo, porque el camino directo NO funciona en producción:
        Railway responde HTTP 451 desde Binance ("ubicación restringida", verificado
        el 2026-07-26). El patrón del proyecto es que el VPS recolecta y Railway
        muestra; pedirle las velas al exchange desde el proceso web fue un error de
        diseño mío. Mientras no exista un push de klines desde el VPS, se cae a los
        klines VERSIONADOS del repo, que sí viajan en el deploy.

        Ese respaldo está viejo (unos 41 días) y eso NO se disimula: la fuente viaja
        en el payload y la pantalla la muestra. Para la apertura anual da igual —el 1
        de enero ya pasó y no cambia—, para la apertura semanal no sirve y por eso esa
        función devuelve None sola.
        """
        clave = f"{symbol}:{tf}:{limit}"
        with self._lock:
            item = self._cache.get(clave)
            if item and (time.time() - item[0]) < TTL_VELAS:
                return item[1]
        try:
            filas = bc.public_get(bc.FAPI, FAPI_KLINES,
                                  {"symbol": symbol, "interval": tf, "limit": limit})
            velas = [{"t": int(f[0]), "o": float(f[1]), "h": float(f[2]),
                      "l": float(f[3]), "c": float(f[4]), "v": float(f[5])} for f in filas]
            resultado = (velas, "binance_publico")
        except Exception as exc:  # noqa: BLE001
            velas = self._velas_versionadas(symbol, tf, limit)
            if not velas:
                raise
            self.context.log(f"inteligencia: sin Binance ({str(exc)[:80]}), "
                             "uso klines versionados")
            resultado = (velas, "klines_versionados")
        with self._lock:
            self._cache[clave] = (time.time(), resultado)
        return resultado

    @staticmethod
    def _velas_versionadas(symbol: str, tf: str, limit: int) -> list[dict]:
        """Los klines que viajan en el repo. Dataset versionado, NO un feed."""
        nombre = f"klines_{symbol}_{tf.lower()}.json"
        ruta = os.path.join(ROOT_REPO, "data", nombre)
        try:
            with open(ruta, encoding="utf-8") as fh:
                filas = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(filas, list):
            return []
        return filas[-limit:]

    def _pares(self) -> list[str]:
        return list(self.config.get("pares") or ["BTCUSDT", "ETHUSDT", "SOLUSDT",
                                                 "ADAUSDT", "XRPUSDT"])

    # --- API -----------------------------------------------------------
    # Temporalidades que la vista puede pedir. Es una lista blanca a propósito: el
    # `interval` va a una URL de Binance, y aceptar lo que venga del query sería
    # dejar que el navegador arme el request.
    TFS = ("15m", "1h", "4h", "1d")

    def api(self, subpath, query, user=None):
        if subpath not in ("state", "velas"):
            return None
        symbol = (query.get("symbol") or self._pares()[0]).upper()
        if symbol not in self._pares():
            return self._json(400, {"error": "par no habilitado"})
        try:
            if subpath == "velas":
                tf = query.get("tf") or "1h"
                if tf not in self.TFS:
                    return self._json(400, {"error": "temporalidad no habilitada"})
                velas, fuente = self._velas(symbol, tf, MAX_VELAS)
                return self._json(200, {"symbol": symbol, "tf": tf, "velas": velas,
                                        "piv": PIV_CURSO, "fuente": fuente,
                                        "estructura": P.estructura(velas, PIV_CURSO)})
            return self._json(200, self._estado(symbol))
        except Exception as exc:  # noqa: BLE001
            # Un fallo de red no puede tumbar la vista entera: se reporta como dato.
            self.context.log(f"inteligencia: {exc}")
            return self._json(200, {"error": str(exc)[:200], "symbol": symbol,
                                    "research_only": True})

    def _estado(self, symbol: str) -> dict:
        diarias, fuente_d = self._velas(symbol, "1d", 400)
        horarias, fuente_h = self._velas(symbol, "1h", MAX_VELAS)
        ahora_ms = int(time.time() * 1000)
        px = float(horarias[-1]["c"]) if horarias else 0.0

        anio = time.gmtime().tm_year
        ancla = P.apertura_anual(diarias, anio)
        # Si el año en curso no tiene ancla (par listado después del 1 de enero), se
        # dice que no la hay. Usar la primera vela disponible sería una ficción con
        # cara de dato, que es justo lo que el curso hace y nosotros no.
        grid = P.rejilla(ancla["precio"], px) if ancla else []
        placebo = ({str(p): P.rejilla(ancla["precio"], px, paso=p)
                    for p in P.PASOS_PLACEBO} if ancla else {})

        semanal = P.apertura_semanal(horarias, ahora_ms)
        est_1h = P.estructura(horarias, PIV_CURSO)
        est_1d = P.estructura(diarias, PIV_CURSO)

        # Referencias para el vacío: los niveles de la rejilla más los pivotes
        # confirmados. Es deliberadamente amplio — el punto del concepto es NO omitir
        # obstáculos, y omitir uno es la forma de inflar un RR sin darse cuenta.
        refs = [{"precio": f["precio"], "tipo": f"rejilla {f['pct_del_ancla']:+.0f}%",
                 "tf": "anual"} for f in grid]
        for p in est_1d["highs"] + est_1d["lows"]:
            refs.append({"precio": p["price"], "tipo": "pivote confirmado", "tf": "1D"})
        for p in est_1h["highs"] + est_1h["lows"]:
            refs.append({"precio": p["price"], "tipo": "pivote confirmado", "tf": "1h"})

        arriba = P.vacio_disponible(px, "long", px * 0.985, refs)
        abajo = P.vacio_disponible(px, "short", px * 1.015, refs)

        return {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "aviso": ("Research sin validar. Del curso completo, cero conceptos tienen "
                      "evidencia cuantitativa propia. No es señal ni recomendación."),
            "symbol": symbol,
            "pares": self._pares(),
            # De dónde salieron los datos. Si dice `klines_versionados`, el precio y
            # la estructura están viejos y la pantalla tiene que decirlo.
            "fuente": fuente_h,
            "fuente_diaria": fuente_d,
            "precio": px,
            "vela_1h_cierre": horarias[-1]["t"] if horarias else None,
            "anio": anio,
            "apertura_anual": ancla,
            "desde_apertura_anual_pct": (round((px / ancla["precio"] - 1) * 100, 2)
                                         if ancla and px else None),
            "rejilla": grid,
            "paso_rejilla": P.PASO_RMP,
            "rejilla_placebo": placebo,
            "nota_placebo": ("Los pasos de 7,5% y 12,5% van al lado a propósito: el 10% "
                             "del curso no está demostrado como especial, y una rejilla "
                             "sola siempre parece funcionar."),
            "apertura_semanal": semanal,
            "estructura_1h": est_1h,
            "estructura_1D": est_1d,
            "vacio_arriba": arriba,
            "vacio_abajo": abajo,
            "nota_vacio": ("El SL de referencia es 1,5% (el techo MAX_SL_PCT del bot), "
                           "solo para dar escala al ratio. No es el SL de ningún plan."),
        }

    @staticmethod
    def _json(status, data):
        return status, "application/json; charset=utf-8", \
            json.dumps(data, ensure_ascii=False).encode()

    def health(self):
        return {"slug": self.slug, "status": "ok", "mode": "research",
                "execution": False}


def get_module(context):
    return InteligenciaModule(context)
