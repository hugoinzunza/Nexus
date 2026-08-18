"""Bot3.v9 — ledger append-only con identidad universal y dedupe.

Cláusulas: CF-25 (heads por evento), CF-26 (identidad estable de
incidencias), CF-30 (`event_id` universal y dedupe contra el ledger YA
ESCRITO), CF-34 (temporalidad triple), CF-37 (registro cerrado de tipos).

El dedupe relee el archivo, nunca solo memoria: tras un crash en cualquier
punto, el reproceso re-deriva los mismos `event_id` y la escritura es
idempotente.
"""
from __future__ import annotations

import json
import os

from .contract import CONTRATO_HASH, PROTOCOLO, TIPOS, canon, event_id


class Ledger:
    """Append-only. Un evento por línea JSON canónica."""

    def __init__(self, ruta: str | None = None, commit: str = "dev"):
        self.ruta = ruta
        self.commit = commit
        self.eventos: list[dict] = []
        self._ids: set[str] = set()
        if ruta and os.path.exists(ruta):
            self._releer()

    def _releer(self) -> None:
        """Reconstruye el índice desde el archivo (CF-30: el dedupe se hace
        contra lo efectivamente escrito)."""
        self.eventos, self._ids = [], set()
        with open(self.ruta, encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea:
                    continue
                ev = json.loads(linea)
                self.eventos.append(ev)
                self._ids.add(ev["event_id"])

    # Tipos cuya IDENTIDAD usa un instante propio distinto del `effective_at`
    # causal. Es una lista CERRADA: `id_t` no es un escape genérico.
    ID_T_PERMITIDO = ("epoca_m15",)

    def _clave(self, tipo: str, campos: dict) -> str:
        t = campos.get("effective_at")
        if tipo in self.ID_T_PERMITIDO and campos.get("id_t") is not None:
            t = campos["id_t"]
        return event_id(
            tipo, contrato=CONTRATO_HASH, id=campos.get("id"),
            mercado=campos.get("mercado"), t=t,
            tf=campos.get("tf"), motivo=campos.get("motivo"),
            desde=campos.get("desde"), hasta=campos.get("hasta"),
            zona_avail=campos.get("zona_avail"), zona_lo=campos.get("zona_lo"),
            zona_hi=campos.get("zona_hi"),
        )

    def append(self, tipo: str, **campos) -> dict | None:
        """Appendea un evento del registro cerrado. Devuelve None si el
        `event_id` ya existe (idempotencia tras crash)."""
        if tipo not in TIPOS:
            raise ValueError(f"tipo fuera del registro cerrado CF-37: {tipo!r}")
        if campos.get("id_t") is not None and tipo not in self.ID_T_PERMITIDO:
            raise ValueError(f"`id_t` no permitido para el tipo {tipo!r}")
        eid = self._clave(tipo, campos)
        if eid in self._ids:
            return None
        # `id_t` es un detalle de identidad: no se persiste en el evento.
        ev = {"event_id": eid, "tipo": tipo, "protocolo": PROTOCOLO,
              "contrato": CONTRATO_HASH, "commit": self.commit,
              **{k: v for k, v in campos.items()
                 if v is not None and k != "id_t"}}
        self.eventos.append(ev)
        self._ids.add(eid)
        if self.ruta:
            os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
            with open(self.ruta, "a", encoding="utf-8") as fh:
                fh.write(canon(ev) + "\n")
        return ev

    # --- consulta ---------------------------------------------------------
    def por_tipo(self, tipo: str) -> list[dict]:
        return [e for e in self.eventos if e["tipo"] == tipo]

    def cierres(self) -> list[dict]:
        return self.por_tipo("cerrado")

    def latencias(self) -> list[int]:
        """CF-34: `finalized_at − effective_at` de los eventos de dominio."""
        return [e["finalized_at"] - e["effective_at"] for e in self.eventos
                if "finalized_at" in e and "effective_at" in e]

    def firma(self) -> str:
        """Firma del ledger completo (para comparar libros byte a byte)."""
        from .contract import sha256_hex
        return sha256_hex("\n".join(canon(e) for e in self.eventos))
