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

import hmac
import json
import os
import threading
import time

from core.module_base import NexusModule
from core import klines_push
from modules.journal import binance_client as bc
from . import precio as P

ROOT_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# La lectura/escritura del push vive en `core/klines_push.py` porque tambien la usa
# el modulo de trading para su grafico: con el lector duplicado, el dia que cambie el
# formato uno de los dos se queda atras en silencio.

# Klines públicas de futuros: mismo mercado que opera el bot, sin firma y sin llaves.
# Se usa el endpoint público a propósito: este módulo no debe poder tocar la cuenta.
FAPI_KLINES = "/fapi/v1/klines"
TTL_VELAS = 300          # 5 min: los niveles son de mediano plazo, no hace falta más
MAX_VELAS = 500
# El diario va aparte y mas largo: 500 dias solo alcanzan las anclas de 2025 y 2026.
# El colector del VPS empuja 1.500 velas diarias justamente para cubrir desde 2022,
# y servir solo 500 desperdiciaba eso y dejaba sin ancla los anos anteriores. Las
# velas diarias son chicas, asi que traerlas todas no cuesta nada.
MAX_VELAS_DIARIAS = 1_500

# Pivotes: el curso enseña 5+1+5. No se toma como verdad —NexUX ya usa 10 para rangos
# y 2 para el CDC, y la justificación del curso (cinco días bursátiles) no traslada a
# cripto 24/7— pero es el parámetro del método y la pantalla dice cuál usó.
PIV_CURSO = 5

HORIZONTES = {
    "corto": {
        "label": "Corto / intradía",
        "panorama": ["1d", "4h"],
        "principal": "1h",
        "sincronismo": "15m",
    },
    "medio": {
        "label": "Medio / swing",
        "panorama": ["1w", "1d"],
        "principal": "4h",
        "sincronismo": "1h",
    },
    "largo": {
        "label": "Largo / posición",
        "panorama": ["1w"],
        "principal": "1d",
        "sincronismo": "4h",
    },
}


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
        """Klines públicas con caché. Devuelve `(velas, fuente, metadata)`.

        Sin firma y sin credenciales: este módulo no puede tocar la cuenta.

        Railway responde HTTP 451 desde Binance ("ubicación restringida", verificado
        el 2026-07-26). Por eso la ruta principal es el snapshot que recolecta el VPS.
        Binance directo queda como respaldo local y los klines versionados como último
        recurso. La fuente y su edad viajan en el payload para que la pantalla nunca
        presente un respaldo viejo como dato actual.
        """
        clave = f"{symbol}:{tf}:{limit}"
        with self._lock:
            item = self._cache.get(clave)
            if item and (time.time() - item[0]) < TTL_VELAS:
                return item[1]
        # 1) lo que el VPS empujo. Es la fuente BUENA: Binance en vivo, desde una
        # region que Binance si atiende.
        empujadas, push_meta = klines_push.serie_con_meta(
            ROOT_REPO, symbol, tf, limit)
        if empujadas:
            resultado = (empujadas, "vps_binance", push_meta)
            with self._lock:
                self._cache[clave] = (time.time(), resultado)
            return resultado
        # 2) Binance directo. Funciona en local y en el VPS; en Railway da 451.
        try:
            filas = bc.public_get(bc.FAPI, FAPI_KLINES,
                                  {"symbol": symbol, "interval": tf, "limit": limit})
            velas = [{"t": int(f[0]), "o": float(f[1]), "h": float(f[2]),
                      "l": float(f[3]), "c": float(f[4]), "v": float(f[5])} for f in filas]
            resultado = (velas, "binance_publico", {
                "fuente": "binance_publico",
                "valida": True,
                "last_bar_open_t": velas[-1]["t"] if velas else None,
            })
        except Exception as exc:  # noqa: BLE001
            velas = self._velas_versionadas(symbol, tf, limit)
            if not velas:
                raise
            self.context.log(f"inteligencia: sin Binance ({str(exc)[:80]}), "
                             "uso klines versionados")
            resultado = (velas, "klines_versionados", {
                "fuente": "klines_versionados",
                "valida": False,
                "last_bar_open_t": velas[-1]["t"] if velas else None,
            })
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


    def _velas_empujadas(self, symbol: str, tf: str, limit: int) -> list[dict]:
        """Las klines que empuja el colector del VPS, si estan frescas.

        Se exige frescura a proposito: unas klines empujadas hace tres horas son peor
        que las versionadas, porque PARECEN en vivo. Si el colector murio, se cae al
        siguiente respaldo y la pantalla lo dice.
        """
        return klines_push.serie(ROOT_REPO, symbol, tf, limit)

    def api_post(self, subpath, body, headers, user=None):
        """Ingesta de klines desde el colector del VPS.

        Existe porque Railway esta geo-bloqueado por Binance (HTTP 451) y el patron
        del proyecto es que el VPS recolecte y Railway muestre. No hay ningun otro
        POST en este modulo: no crea ordenes, no toca el bot, no escribe config.
        """
        if subpath != "klines-ingest":
            return None
        token = os.environ.get("NEXUS_INGEST_TOKEN", "").strip()
        if not token:
            return self._json(503, {"error": "ingesta no configurada"})
        if not hmac.compare_digest(headers.get("x-nexus-token", ""), token):
            return self._json(401, {"error": "token invalido"})
        if not isinstance(body, dict):
            return self._json(400, {"error": "payload invalido"})
        series = body.get("series")
        if not isinstance(series, dict) or not series:
            return self._json(400, {"error": "series requerido"})

        limpio = {}
        for clave, filas in series.items():
            # La clave manda a que par y temporalidad pertenece la serie, asi que se
            # valida contra las listas blancas en vez de confiar en lo que llegue.
            partes = str(clave).split(":")
            if len(partes) != 2:
                continue
            symbol, tf = partes[0].upper(), partes[1]
            if symbol not in self._pares() or tf not in self.TFS:
                continue
            if not isinstance(filas, list) or len(filas) > 2_000:
                continue
            velas = []
            for f in filas:
                if not isinstance(f, dict):
                    continue
                try:
                    velas.append({"t": int(f["t"]), "o": float(f["o"]),
                                  "h": float(f["h"]), "l": float(f["l"]),
                                  "c": float(f["c"]), "v": float(f.get("v") or 0)})
                except (KeyError, TypeError, ValueError):
                    continue
            normalizadas, error, _ = klines_push.validar_serie(velas, tf)
            if normalizadas and not error:
                limpio[f"{symbol}:{tf}"] = normalizadas
        if not limpio:
            return self._json(400, {"error": "ninguna serie valida"})

        with self._lock:
            # Una ingesta parcial no puede borrar pares que el snapshot anterior sí
            # tenía. El colector normal publica todo, pero el servidor también debe
            # ser atómico frente a un caller interrumpido o una recolección manual.
            anterior = klines_push.leer_todo(ROOT_REPO) or {}
            combinadas = dict(anterior.get("series") or {})
            combinadas.update(limpio)
            klines_push.escribir(ROOT_REPO, {
                "empujado_ts": time.time(),
                "empujado_at": body.get("captured_at"),
                "fuente": "binance_futuros_vps",
                "series": combinadas})
            self._cache.clear()   # el push manda sobre lo cacheado
        return self._json(200, {"ok": True, "series": len(combinadas),
                                "velas": sum(len(v) for v in combinadas.values())})

    def _pares(self) -> list[str]:
        return list(self.config.get("pares") or ["BTCUSDT", "ETHUSDT", "SOLUSDT",
                                                 "ADAUSDT", "XRPUSDT"])

    # --- API -----------------------------------------------------------
    # Temporalidades que la vista puede pedir. Es una lista blanca a propósito: el
    # `interval` va a una URL de Binance, y aceptar lo que venga del query sería
    # dejar que el navegador arme el request.
    TFS = ("15m", "1h", "4h", "1d", "1w")

    def api(self, subpath, query, user=None):
        if subpath not in ("state", "velas", "mapa"):
            return None
        symbol = (query.get("symbol") or self._pares()[0]).upper()
        if symbol not in self._pares():
            return self._json(400, {"error": "par no habilitado"})
        try:
            if subpath == "velas":
                tf = query.get("tf") or "1h"
                if tf not in self.TFS:
                    return self._json(400, {"error": "temporalidad no habilitada"})
                tope = MAX_VELAS_DIARIAS if tf == "1d" else MAX_VELAS
                velas, fuente, meta = self._velas(symbol, tf, tope)
                ahora_ms = int(time.time() * 1000)
                cerradas = P.velas_cerradas(velas, tf, ahora_ms)
                # El navegador SI puede hablar con Binance (el 451 es del datacenter
                # de Railway, no de la ubicacion del que mira), asi que la cola en vivo
                # la trae el browser. Sin esto el grafico quedaba 13,3 min atrasado
                # —push cada 10 min mas la cache de 5— y se veia como precio congelado.
                # El nombre del stream lo arma el SERVIDOR para no duplicar el mapeo.
                stream = (f"{symbol.lower()}@kline_{tf}"
                          if fuente == "vps_binance" and tf in klines_push.TFS_SERVIBLES
                          else None)
                return self._json(200, {"symbol": symbol, "tf": tf, "velas": velas,
                                        "piv": PIV_CURSO, "fuente": fuente,
                                        "fuente_meta": meta,
                                        "stream_vivo": stream,
                                        "as_of": ahora_ms,
                                        "velas_cerradas": len(cerradas),
                                        "vela_abierta": len(velas) > len(cerradas),
                                        "estructura": P.estructura(cerradas, PIV_CURSO)})
            if subpath == "mapa":
                horizonte = query.get("horizonte") or "medio"
                if horizonte not in HORIZONTES:
                    return self._json(400, {"error": "horizonte no habilitado"})
                return self._json(200, self._mapa_horizonte(symbol, horizonte))
            return self._json(200, self._estado(symbol))
        except Exception as exc:  # noqa: BLE001
            # Un fallo de red no puede tumbar la vista entera: se reporta como dato.
            self.context.log(f"inteligencia: {exc}")
            return self._json(200, {"error": str(exc)[:200], "symbol": symbol,
                                    "research_only": True})

    def _estado(self, symbol: str) -> dict:
        diarias, fuente_d, meta_d = self._velas(symbol, "1d", MAX_VELAS_DIARIAS)
        horarias, fuente_h, meta_h = self._velas(symbol, "1h", MAX_VELAS)
        ahora_ms = int(time.time() * 1000)
        px = float(horarias[-1]["c"]) if horarias else 0.0
        diarias_c = P.velas_cerradas(diarias, "1d", ahora_ms)
        horarias_c = P.velas_cerradas(horarias, "1h", ahora_ms)

        anio = time.gmtime().tm_year
        ancla = P.apertura_anual(diarias_c, anio)
        anclas_historicas = P.aperturas_anuales(diarias_c)
        # Si el año en curso no tiene ancla (par listado después del 1 de enero), se
        # dice que no la hay. Usar la primera vela disponible sería una ficción con
        # cara de dato, que es justo lo que el curso hace y nosotros no.
        grid = P.rejilla(ancla["precio"], px) if ancla else []
        placebo = ({str(p): P.rejilla(ancla["precio"], px, paso=p)
                    for p in P.PASOS_PLACEBO} if ancla else {})

        semanal = P.apertura_semanal(horarias_c, ahora_ms)
        est_1h = P.estructura(horarias_c, PIV_CURSO)
        est_1d = P.estructura(diarias_c, PIV_CURSO)

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
            # Medido el 2026-07-26: el push cada 10 min mas la cache de 5 min del
            # modulo daban 13,3 min de atraso, y la pantalla no lo decia. Un precio
            # de hace 13 minutos presentandose como el actual es la misma familia de
            # defecto que veniamos corrigiendo todo el dia.
            "push_edad_s": klines_push.edad_segundos(ROOT_REPO),
            "fuente_meta": meta_h,
            "fuente_diaria_meta": meta_d,
            "precio": px,
            "precio_as_of": horarias[-1]["t"] if horarias else None,
            "ultima_1h_cerrada": horarias_c[-1]["t"] if horarias_c else None,
            "anio": anio,
            "apertura_anual": ancla,
            "aperturas_anuales": anclas_historicas,
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

    def _mapa_horizonte(self, symbol: str, horizonte: str) -> dict:
        perfil = HORIZONTES[horizonte]
        ahora_ms = int(time.time() * 1000)
        requeridas = list(dict.fromkeys(
            perfil["panorama"] + [perfil["principal"], perfil["sincronismo"]]))
        series = {}
        fuentes = {}
        for tf in requeridas:
            tope = MAX_VELAS_DIARIAS if tf == "1d" else MAX_VELAS
            velas, fuente, meta = self._velas(symbol, tf, tope)
            cerradas = P.velas_cerradas(velas, tf, ahora_ms)
            series[tf] = {"raw": velas, "closed": cerradas}
            fuentes[tf] = {"fuente": fuente, **meta,
                           "closed_bars": len(cerradas),
                           "open_bar_excluded": len(velas) > len(cerradas)}

        principal_tf = perfil["principal"]
        principal = series[principal_tf]
        precio = float(principal["raw"][-1]["c"]) if principal["raw"] else 0.0
        piernas = P.piernas_confirmadas(
            principal["closed"], principal_tf, PIV_CURSO)
        seleccionada = piernas[-1] if piernas else None
        mapa = P.mapa_precios(seleccionada, precio) if seleccionada else None

        estructuras = {}
        referencias = []
        for tf in perfil["panorama"] + [principal_tf, perfil["sincronismo"]]:
            est = P.estructura(series[tf]["closed"], PIV_CURSO)
            estructuras[tf] = est
            for p in est["highs"] + est["lows"]:
                referencias.append({
                    "precio": p["price"],
                    "tipo": "pivote confirmado",
                    "familia": "estructura",
                    "tf": tf,
                    "confirm_idx": p["confirm_idx"],
                    "pivot_t": p["pivot_t"],
                    "confirmed_at": p["confirmed_at"],
                    "selection_reason": "pivote fractal confirmado 5+1+5",
                })

        # Los RMP son referencias objetivas y existen desde la apertura anual. Se
        # agregan al mismo universo del primer obstáculo, sin promoverlos por cercanía
        # ni seleccionar retrospectivamente los que reaccionaron.
        diarias = series["1d"]["closed"]
        ancla = P.apertura_anual(diarias, time.gmtime().tm_year)
        if ancla:
            for nivel in P.rejilla(ancla["precio"], precio):
                referencias.append({
                    "precio": nivel["precio"],
                    "tipo": f"RMP {nivel['pct_del_ancla']:+.0f}%",
                    "familia": "rmp",
                    "tf": "1D",
                    "pivot_t": ancla["t"],
                    "confirmed_at": ancla["t"] + P.TF_MS["1d"],
                    "selection_reason": "rejilla anual mecánica vigente",
                })
        if mapa:
            for familia, niveles in (("retroceso", mapa["retrocesos"]),
                                     ("extension", mapa["extensiones"])):
                for nivel in niveles:
                    referencias.append({
                        "precio": nivel["precio"],
                        "tipo": f"{familia} {nivel['ratio'] * 100:g}%",
                        "familia": f"pierna_{familia}",
                        "tf": principal_tf,
                        "pivot_t": seleccionada["fin_t"],
                        "confirmed_at": seleccionada["confirmed_at"],
                        "selection_reason": "nivel aritmético de la pierna seleccionada",
                    })

        tendencias = {tf: est["tendencia"] for tf, est in estructuras.items()}
        alineacion = P.alineacion_temporal(
            perfil["panorama"], principal_tf, perfil["sincronismo"], tendencias)
        direccion = alineacion["direccion_contexto"]

        vacio = {"evaluado": False, "motivo": "contexto superior sin dirección unívoca"}
        if direccion:
            est_principal = estructuras[principal_tf]
            candidatos_sl = (est_principal["lows"] if direccion == "alcista"
                              else est_principal["highs"])
            candidatos_sl = [
                p for p in candidatos_sl
                if (p["price"] < precio if direccion == "alcista"
                    else p["price"] > precio)
            ]
            if candidatos_sl:
                stop_ref = min(candidatos_sl, key=lambda p: abs(p["price"] - precio))
                medido = P.vacio_disponible(
                    precio, "long" if direccion == "alcista" else "short",
                    stop_ref["price"], referencias)
                vacio = {
                    "evaluado": True,
                    "direccion": direccion,
                    "stop_estructural": stop_ref,
                    **medido,
                    "nota": ("Distancia al primer referente usando el pivote estructural "
                             "principal como stop. Research; no es plan de entrada."),
                }
            else:
                vacio = {"evaluado": False,
                         "motivo": "no existe stop estructural principal detrás del precio"}

        arriba = sorted((r for r in referencias if r["precio"] > precio),
                        key=lambda r: r["precio"])[:5]
        abajo = sorted((r for r in referencias if r["precio"] < precio),
                       key=lambda r: r["precio"], reverse=True)[:5]
        return {
            "research_only": True,
            "execution_enabled": False,
            "validated": False,
            "symbol": symbol,
            "horizonte": horizonte,
            "perfil": perfil,
            "as_of": ahora_ms,
            "precio": precio,
            "fuentes": fuentes,
            "estructuras": estructuras,
            "alineacion": alineacion,
            "mapa": mapa,
            "vacio_horizonte": vacio,
            "piernas_candidatas": piernas[-4:],
            "referencias_cercanas": {"arriba": arriba, "abajo": abajo},
            "nota": ("Escenario causal calculado con barras cerradas. No predice "
                     "dirección, probabilidad ni resultado."),
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
