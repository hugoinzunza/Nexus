"""Observador Bot3.v13 — máquina de silencio H4 (§6.5 del diseño rev.8).

Un mercado que deja de publicar velas H4 bloquea el lote global: sin la grilla
H4 resuelta no se procesa nada, porque decidir con un rector congelado es la
divergencia que todo esto quiere impedir. Si el mercado no vuelve NUNCA, la
espera sería infinita, así que la liveness se obtiene con un **estado terminal**
—`BLOCKED_INTEGRITY`— y no con una prueba fabricada: inventar un watermark
exchange H4 sellaría un marcador en el almacén, que entra en la cadena de
hashes y cambia lo que decide `_calcular_h4`.

Reglas que esta máquina implementa, todas congeladas:

- **solo la evidencia válida avanza**: una paginación válida y COMPLETA que no
  trae la vela es una observación probatoria; un error HTTP, un timeout, un
  `eligibility_time` indisponible o el daemon apagado NO lo son;
- **el comparador no es una resta de relojes** sino evidencia ACUMULADA con
  tope por par de observaciones, así que el tiempo apagado no puede contarse;
- **el primer intervalo de cada corrida aporta cero**: nadie observó ese tramo.
  `run_epoch` lo hace reconstruible tras un reinicio;
- **el acumulado no se cree, se deriva**: al rehidratar se recalcula desde las
  observaciones y se compara con lo persistido.
"""
from __future__ import annotations

import hashlib
import json
import os

from . import contrato as C


class SilencioCorrupto(ValueError):
    """El sidecar decide `BLOCKED_INTEGRITY`: no se acepta a medias."""


def _canon(objeto) -> str:
    return json.dumps(objeto, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def clave(mercado: str, tf: str, primer_cierre: int) -> str:
    """Orden total: mercado, tf y el cierre faltante."""
    return f"{mercado}|{tf}|{int(primer_cierre)}"


def cadena(observaciones: list) -> str:
    """`h_0 = SEMILLA`, `h_i = SHA-256(h_{i-1} ‖ canon(obs_i))`."""
    h = C.SEMILLA_SILENCIO
    for obs in observaciones:
        h = _sha(h + _canon(obs))
    return h


def acumulado(observaciones: list) -> int:
    """Evidencia acumulada, DERIVADA de las observaciones.

    La primera observación de la entrada aporta cero; la primera de cada
    `run_epoch` posterior también, porque nadie observó ese intervalo. El resto
    aporta `min(Δ, TOPE_INTERVALO)`."""
    total = 0
    previa = None
    for obs in observaciones:
        if previa is not None and obs["run_epoch"] == previa["run_epoch"]:
            delta = obs["eligibility_time"] - previa["eligibility_time"]
            total += min(delta, C.TOPE_INTERVALO_MS)
        previa = obs
    return total


class Silencio:
    """Mapa canónico por `(mercado, tf, primer_cierre)`."""

    def __init__(self, cohorte: dict, contrato: str, commit: str):
        self.cohorte = cohorte
        self.contrato = contrato
        self.commit = commit
        self.entradas: dict[str, dict] = {}
        self.run_epoch = 0

    # --- transiciones -----------------------------------------------------
    def abrir_corrida(self) -> int:
        """Nueva continuidad de ejecución. Monotónico y persistido en cada
        observación: sin él, tras un reinicio no hay forma de reconstruir qué
        intervalos aportaron cero."""
        self.run_epoch += 1
        return self.run_epoch

    def observar(self, mercado: str, tf: str, primer_cierre: int,
                 ultimo_cierre_valido: int, eligibility_time: int) -> dict:
        """Registra una observación PROBATORIA: una paginación válida y
        completa que no trajo la vela esperada."""
        k = clave(mercado, tf, primer_cierre)
        entrada = self.entradas.get(k)
        if entrada is None:
            entrada = {
                "estado": "activo", "mercado": mercado, "tf": tf,
                "primer_cierre": int(primer_cierre),
                "ultimo_cierre_valido": int(ultimo_cierre_valido),
                "observaciones": [], "offline_ms": 0, "offline_intervalos": [],
            }
            self.entradas[k] = entrada
        if entrada["estado"] != "activo":
            return entrada
        obs = {"eligibility_time": int(eligibility_time),
               "run_epoch": int(self.run_epoch)}
        previas = entrada["observaciones"]
        if previas and obs["eligibility_time"] <= previas[-1]["eligibility_time"]:
            # Duplicado o retroceso de `serverTime`: aporta CERO y NO mueve el
            # puntero. Nunca se suma un delta negativo ni se reordena.
            if obs["eligibility_time"] < previas[-1]["eligibility_time"]:
                entrada.setdefault("regresiones", []).append(obs)
            return entrada
        previas.append(obs)
        return entrada

    def registrar_offline(self, ms: int, desde: int, hasta: int) -> None:
        """El tiempo apagado NO cuenta como evidencia, pero se registra.

        Apagar el daemon congela el reloj del silencio: es un incentivo que no
        se puede eliminar por diseño, así que al menos queda visible."""
        for entrada in self.entradas.values():
            if entrada["estado"] != "activo":
                continue
            entrada["offline_ms"] += int(ms)
            entrada["offline_intervalos"].append([int(desde), int(hasta)])

    def resolver(self, mercado: str, tf: str, primer_cierre: int) -> None:
        """La vela apareció antes del umbral: la entrada deja de gobernar y se
        conserva para auditoría. Otro cierre faltante es OTRA clave."""
        entrada = self.entradas.get(clave(mercado, tf, primer_cierre))
        if entrada is not None:
            entrada["estado"] = "resuelto"

    # --- consulta ---------------------------------------------------------
    def evidencia(self, k: str) -> int:
        return acumulado(self.entradas[k]["observaciones"])

    def ganadora(self) -> dict | None:
        """La primera entrada que cruza el umbral. Empate a la misma
        observación: gana el menor en el orden total de la clave."""
        candidatas = []
        for k in sorted(self.entradas):
            entrada = self.entradas[k]
            if entrada["estado"] != "activo":
                continue
            ev = acumulado(entrada["observaciones"])
            if ev > C.SILENCIO_MAX_H4_MS:
                cruce = entrada["observaciones"][-1]["eligibility_time"]
                candidatas.append((cruce, k, entrada, ev))
        if not candidatas:
            return None
        candidatas.sort(key=lambda x: (x[0], x[1]))
        _, k, entrada, ev = candidatas[0]
        return {
            "clave": k, "mercado": entrada["mercado"], "tf": entrada["tf"],
            "primer_cierre": entrada["primer_cierre"],
            "ultimo_cierre_valido": entrada["ultimo_cierre_valido"],
            "inicio": entrada["observaciones"][0]["eligibility_time"],
            "umbral_ms": C.SILENCIO_MAX_H4_MS,
            "eligibility_time_decisivo":
                entrada["observaciones"][-1]["eligibility_time"],
            "evidencia_acumulada_ms": ev,
            "observaciones": len(entrada["observaciones"]),
            "cadena": cadena(entrada["observaciones"]),
        }

    # --- persistencia -----------------------------------------------------
    def documento(self) -> dict:
        cuerpo = {
            "schema_version": C.SCHEMA_SILENCIO,
            "cohorte": self.cohorte,
            "contrato": self.contrato,
            "commit": self.commit,
            "run_epoch": self.run_epoch,
            "entradas": {},
        }
        for k in sorted(self.entradas):
            e = dict(self.entradas[k])
            e["evidencia_acumulada_ms"] = acumulado(e["observaciones"])
            e["cadena"] = cadena(e["observaciones"])
            cuerpo["entradas"][k] = e
        # `doc_sha256` cubre el DOCUMENTO entero: la cadena solo autentica las
        # observaciones, y `estado`, `primer_cierre`, `offline_ms` y el propio
        # acumulado también deciden el terminal.
        cuerpo["doc_sha256"] = _sha(_canon(cuerpo))
        return cuerpo

    def guardar(self, ruta: str) -> None:
        cuerpo = _canon(self.documento())
        carpeta = os.path.dirname(ruta) or "."
        os.makedirs(carpeta, exist_ok=True)
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(cuerpo)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
        fd = os.open(carpeta, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @classmethod
    def cargar(cls, ruta: str, cohorte: dict, contrato: str,
               commit: str) -> "Silencio":
        """Rehidrata VALIDANDO. Cualquier discrepancia detiene el observador:
        este archivo decide `BLOCKED_INTEGRITY`, así que no puede aceptarse
        «otro digest válido» en vez del que corresponde."""
        s = cls(cohorte, contrato, commit)
        if not os.path.exists(ruta):
            return s
        with open(ruta, encoding="utf-8") as fh:
            crudo = json.load(fh)
        esperado = crudo.pop("doc_sha256", None)
        real = _sha(_canon(crudo))
        if esperado != real:
            raise SilencioCorrupto(
                f"doc_sha256 no corresponde en {ruta}: "
                f"{str(esperado)[:12]}… != {real[:12]}…")
        if crudo.get("schema_version") != C.SCHEMA_SILENCIO:
            raise SilencioCorrupto(
                f"schema_version {crudo.get('schema_version')!r} desconocida")
        for campo, valor in (("cohorte", cohorte), ("contrato", contrato),
                             ("commit", commit)):
            if crudo.get(campo) != valor:
                raise SilencioCorrupto(
                    f"{campo} ajeno en {ruta}: no es esta cohorte")
        s.run_epoch = int(crudo.get("run_epoch", 0))
        for k, entrada in crudo.get("entradas", {}).items():
            obs = entrada.get("observaciones", [])
            previa = None
            for o in obs:
                if type(o.get("eligibility_time")) is not int \
                        or type(o.get("run_epoch")) is not int:
                    raise SilencioCorrupto(
                        f"observación mal formada en {k}")
                if previa is not None:
                    if o["eligibility_time"] <= previa["eligibility_time"]:
                        raise SilencioCorrupto(
                            f"observaciones no monótonas en {k}")
                    if o["run_epoch"] < previa["run_epoch"]:
                        raise SilencioCorrupto(
                            f"run_epoch retrocede en {k}")
                previa = o
            if entrada.get("cadena") != cadena(obs):
                raise SilencioCorrupto(f"cadena de evidencia rota en {k}")
            if entrada.get("evidencia_acumulada_ms") != acumulado(obs):
                raise SilencioCorrupto(
                    f"el acumulado de {k} no se deriva de sus observaciones")
            s.entradas[k] = {kk: vv for kk, vv in entrada.items()
                             if kk not in ("cadena", "evidencia_acumulada_ms")}
        return s
