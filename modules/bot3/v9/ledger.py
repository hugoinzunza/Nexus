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

from . import marco
from .contract import CONTRATO_HASH, PROTOCOLO, TIPOS, canon, event_id


class Ledger:
    """Append-only. Un evento por línea JSON canónica."""

    def __init__(self, ruta: str | None = None, commit: str = "dev"):
        self.ruta = ruta
        self.commit = commit
        self.durable = False        # el observador lo activa (rev.8 §5)
        self.eventos: list[dict] = []
        self._ids: set[str] = set()
        # Índice por identidad: el dedupe compara contra el evento previo, y
        # buscarlo recorriendo la lista era O(n) por reaparición — es decir
        # cuadrático justo en el reinicio, donde TODOS los eventos reaparecen.
        self._por_id: dict[str, dict] = {}
        if ruta and os.path.exists(ruta):
            self._releer()

    def _releer(self) -> None:
        """Reconstruye el índice desde el archivo (CF-30: el dedupe se hace
        contra lo efectivamente escrito) VERIFICÁNDOLO.

        Releer confiando en el `event_id` escrito convertía el archivo en la
        autoridad: un id alterado, una línea repetida o dos contenidos bajo
        el mismo id entraban al índice y desde ahí gobernaban el dedupe de
        toda la corrida. Se recalcula cada identidad desde el payload y se
        falla cerrado."""
        self.eventos, self._ids, self._por_id = [], set(), {}
        por_id = self._por_id
        # Mismo encuadre que el almacén (rev.8 §5.1): la cola truncada por una
        # caída se descarta y se repone por reemisión idempotente; cualquier
        # otro defecto es corrupción y falla cerrado.
        tramas, cola = marco.leer(self.ruta)
        if cola:
            marco.truncar_cola(self.ruta)
        if True:
            for n, linea in enumerate(tramas, 1):
                ev = json.loads(linea)
                eid = ev.get("event_id")
                # `contrato` y `protocolo` no son telemetría: son la
                # autoridad científica del libro. `_clave` recalcula con el
                # CONTRATO_HASH vigente, así que sin esta comprobación un
                # libro de otro contrato entraba y quedaba avalado por el id
                # que nosotros mismos le derivábamos.
                if ev.get("contrato") != CONTRATO_HASH:
                    raise ValueError(
                        f"contrato ajeno en {self.ruta}:{n} — "
                        f"{str(ev.get('contrato'))[:12]}… != "
                        f"{CONTRATO_HASH[:12]}…")
                if ev.get("protocolo") != PROTOCOLO:
                    raise ValueError(
                        f"protocolo ajeno en {self.ruta}:{n} — "
                        f"{ev.get('protocolo')!r} != {PROTOCOLO!r}")
                campos = dict(ev)
                campo_t = self.ID_T_CAMPO.get(ev.get("tipo"))
                if campo_t is not None:
                    # La identidad usa un instante propio, guardado bajo otro
                    # nombre. Se exige presente y entero: sin él no hay forma
                    # de verificar el id, y aceptarlo sería el mismo agujero.
                    valor = ev.get(campo_t)
                    if not isinstance(valor, int) or isinstance(valor, bool):
                        raise ValueError(
                            f"{ev['tipo']} en {self.ruta}:{n} sin `{campo_t}` "
                            f"entero: su identidad no es verificable")
                    campos["id_t"] = valor
                esperado = self._clave(ev["tipo"], campos)
                if eid != esperado:
                    raise ValueError(
                        f"event_id alterado en {self.ruta}:{n} — "
                        f"{str(eid)[:12]}… no corresponde al payload "
                        f"(debería ser {esperado[:12]}…)")
                previo = por_id.get(eid)
                if previo is not None:
                    if canon(previo) == canon(ev):
                        raise ValueError(
                            f"línea duplicada en {self.ruta}:{n} — el libro "
                            f"es append-only, no un multiconjunto")
                    raise ValueError(
                        f"event_id {str(eid)[:12]}… repetido en "
                        f"{self.ruta}:{n} con contenido distinto")
                por_id[eid] = ev
                self.eventos.append(ev)
                self._ids.add(eid)

    # Tipos cuya IDENTIDAD usa un instante propio distinto del `effective_at`
    # causal. Es una lista CERRADA: `id_t` no es un escape genérico.
    ID_T_PERMITIDO = ("epoca_m15",)

    # `id_t` no se persiste con ese nombre, pero su VALOR sí queda en el
    # evento. Este mapa dice dónde, y es lo que permite recalcular la
    # identidad al releer sin cambiar un solo byte del libro.
    ID_T_CAMPO = {"epoca_m15": "epoca_t0"}

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
        campo_t = self.ID_T_CAMPO.get(tipo)
        if campo_t is not None:
            # Simetría escritura/lectura: si la identidad usa un instante
            # propio, el evento DEBE llevarlo persistido Y la identidad debe
            # calcularse con ESE valor. Validar `epoca_t0` sin usarlo dejaba
            # escribir un archivo que `_releer` rechaza acto seguido: el id
            # salía de `effective_at` y la relectura lo reconstruía desde
            # `epoca_t0`.
            valor = campos.get(campo_t)
            if type(valor) is not int:          # `bool` es subclase de `int`
                raise ValueError(
                    f"{tipo} exige `{campo_t}` entero: su identidad usa un "
                    f"instante propio y sin él el libro no es verificable")
            idt = campos.get("id_t")
            if idt is not None:
                if type(idt) is not int:
                    raise ValueError(
                        f"{tipo}: `id_t` debe ser entero, no {type(idt).__name__}")
                if idt != valor:
                    raise ValueError(
                        f"{tipo}: `id_t` ({idt}) y `{campo_t}` ({valor}) "
                        f"discrepan")
            # Se DERIVA del campo persistido, venga o no `id_t`. `id_t` sigue
            # excluido del evento, así que no cambia un byte del libro.
            campos = {**campos, "id_t": valor}
        eid = self._clave(tipo, campos)
        if eid in self._ids:
            # Reaparición: DEBE ser el mismo evento. Un mismo `event_id` con
            # payload distinto significa que el replay no es determinista, y
            # descartarlo en silencio ocultaría esa divergencia. `commit` y
            # `processed_at` se excluyen: son metadatos de build y telemetría
            # (CF-34), no contenido del evento.
            previo = self._por_id[eid]
            nuevo = {k: v for k, v in campos.items()
                     if v is not None and k != "id_t"}
            volatiles = {"processed_at", "commit"}
            a = {k: v for k, v in previo.items()
                 if k not in volatiles | {"event_id", "tipo", "protocolo",
                                          "contrato"}}
            b = {k: v for k, v in nuevo.items() if k not in volatiles}
            if a != b:
                difs = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
                raise ValueError(
                    f"evento {tipo} {eid[:12]}… reaparece con payload "
                    f"distinto en los campos {sorted(difs)}")
            return None
        # `id_t` es un detalle de identidad: no se persiste en el evento.
        ev = {"event_id": eid, "tipo": tipo, "protocolo": PROTOCOLO,
              "contrato": CONTRATO_HASH, "commit": self.commit,
              **{k: v for k, v in campos.items()
                 if v is not None and k != "id_t"}}
        self.eventos.append(ev)
        self._ids.add(eid)
        self._por_id[eid] = ev
        if self.ruta:
            marco.escribir(self.ruta, canon(ev), durable=self.durable)
        return ev

    # --- consulta ---------------------------------------------------------
    def sincronizar(self) -> None:
        """`fsync` del libro al cerrar el ciclo (rev.8 §5, paso 4)."""
        if self.ruta:
            marco.sincronizar(self.ruta)

    def por_tipo(self, tipo: str) -> list[dict]:
        return [e for e in self.eventos if e["tipo"] == tipo]

    def huecos_exchange(self, mercado: str, desde: int) -> list[dict]:
        """El `hueco_detectado` exchange de ESTE marcador, si el libro ya lo
        documenta. Se busca por (mercado, desde) y NO por `event_id`, para
        poder detectar que fue emitido bajo OTRO `T`.

        Devuelve TODOS los matches, no el primero: si el libro tuviera dos
        entradas para el mismo marcador, quedarse con la primera dejaba pasar
        la validación y ocultaba la segunda.

        No sustituye la comprobación canónica: la reemisión ocurre igual, y
        es `append()` quien falla cerrado si el payload difiere."""
        return [e for e in self.eventos
                if e["tipo"] == "hueco_detectado"
                and e.get("motivo") == "exchange"
                and e.get("mercado") == mercado
                and e.get("desde") == int(desde)]

    def degradaciones(self, mercado: str, detected_at: int) -> list[dict]:
        """Los `mercado_degradado` de ESTE marcador. Se busca por
        `detected_at`, recuperable del marcador sellado. `mercado_degradado`
        es FAM_MERCADO, así que su `event_id` SÍ incluye `T`: dos copias bajo
        distinto `T` son dos ids distintos y `append()` no las vería."""
        return [e for e in self.eventos
                if e["tipo"] == "mercado_degradado"
                and e.get("mercado") == mercado
                and e.get("detected_at") == int(detected_at)]

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
