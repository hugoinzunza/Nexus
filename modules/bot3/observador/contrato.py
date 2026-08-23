"""Observador Bot3.v13 — parámetros congelados.

Diseño rev.8, SHA-256
`660c25d6f9151dfcde5db06abf31158f58e5ad3d65a370897299d080561aa781`.

**Ninguno de estos valores se elige en operación** (§15). Cambiarlos es un
observador distinto, y por lo tanto exige acta nueva: elegir un umbral después
de ver el comportamiento real es exactamente la contaminación que todo este
protocolo impide.

`bootstrap_hasta` NO está acá: es la identidad de la cohorte y se congela en el
acta de activación, no en el código.

Este módulo NO importa nada de ejecución ni de credenciales. La API que usa es
pública; sin llaves, la falla máxima posible es no obtener datos.
"""
from __future__ import annotations

import hashlib
import json

from ..v9.contract import MERCADOS, TF_MS

# --- identidad y aislamiento (§2) ----------------------------------------
SERVICIO = "com.hugo.nexux-bot3v13-observador"
NAMESPACE_CONFIG = "modules.bot3v13"
UNIVERSO = tuple(MERCADOS)
TF_OBSERVADAS = ("15m", "4h")

# --- fuente de datos: API PÚBLICA, sin credenciales (§10) -----------------
ENDPOINT_KLINES = "https://fapi.binance.com/fapi/v1/klines"
ENDPOINT_TIME = "https://fapi.binance.com/fapi/v1/time"
LIMITE_PAGINA = 1000

# --- ciclo (§12) ----------------------------------------------------------
CADENCIA_MS = 60_000                    # un pull por minuto
MARGEN_CIERRE_MS = 2_000                # holgura sobre `closeTime` del exchange
RESOLAPE = 3                            # velas ya selladas que se re-piden

# --- watermarks y tolerancias --------------------------------------------
# `LAG_MAX` se evalúa POR MERCADO Y POR TIMEFRAME: 14 evaluaciones, no una
# (§6). Un fallo en H4 no puede quedar oculto por un M15 fresco.
LAG_MAX_MS = {"15m": 3 * TF_MS["15m"], "4h": 2 * TF_MS["4h"]}
DERIVA_MAX_MS = 5_000                   # reloj local vs. `eligibility_time`

# Silencio H4 (§6.5). Decisión operacional [U0]: 72 h es un compromiso entre
# bloquear cohortes por incidentes normales y dejarla detenida sin decidir. NO
# se apoya en provenance documental — no la tengo — y NO se re-elige después de
# ver un silencio real.
SILENCIO_MAX_H4_MS = 72 * 60 * 60 * 1000
# Tope por par de observaciones: un intervalo solo aporta lo que una cadencia
# normal habría aportado, así que el tiempo apagado no puede acumularse.
TOPE_INTERVALO_MS = 2 * CADENCIA_MS

# --- reintentos ------------------------------------------------------------
BACKOFF_BASE_MS = 1_000
BACKOFF_MAX_MS = 30_000
BACKOFF_INTENTOS = 5

# --- verificación de determinismo (§9) ------------------------------------
CADENCIA_VERIFICACION_MS = 6 * 60 * 60 * 1000

# --- rutas (§2, §4, §13) --------------------------------------------------
RAIZ = "~/Library/Application Support/NexUX/Bot3/v13"
SUBRUTA_ESTADO = "state"
SUBRUTA_LIBRO = "ledger/events.jsonl"
ARCHIVO_LOCK = "observador.lock"
CARPETA_ALMACENES = "almacenes"
CARPETA_STAGING = "almacenes.new"
ARCHIVO_COMPLETADO = "completed.json"
ARCHIVO_BLOQUEADO = "blocked.json"
ARCHIVO_SILENCIO = "silencio.json"
ARCHIVO_VERIFICACION = "verificacion.json"
ARCHIVO_SOLICITUD_TERMINAL = "terminal.request"
ARCHIVO_PEDIDO_VERIFICACION = "verify.request"

# --- estados terminales (§13) ---------------------------------------------
COMPLETADO = "COMPLETED"
BLOQUEADO = "BLOCKED_INTEGRITY"
MOTIVO_SILENCIO = "silencio_h4"
MOTIVO_DIVERGENCIA = "determinism_divergence"
# Registro CERRADO de motivos terminales (§13.2). Cualquier otro FALLA CERRADO:
# fallar abierto acá significa publicar como evaluable una cohorte cuya causa
# de cierre nadie definió.
MOTIVOS_INTEGRIDAD = (MOTIVO_DIVERGENCIA, MOTIVO_SILENCIO)
MOTIVOS_CIENTIFICOS = ("muestra", "tiempo", "administrativo")

# Precedencia CONGELADA y total (§13.2.1): la integridad precede a lo
# científico SIEMPRE. Entre los científicos no hay orden porque no pueden
# coexistir — el motor corta una sola vez—, y dos de ellos en un mismo request
# es fallo cerrado.
PRECEDENCIA_TERMINAL = MOTIVOS_INTEGRIDAD + MOTIVOS_CIENTIFICOS
PRECEDENCIA_MOTIVOS = MOTIVOS_INTEGRIDAD        # compat: solo integridad

# --- estados de la verificación (§9.2) ------------------------------------
VERIF_OK = "ok"
VERIF_DIFERIDA = "deferred"
VERIF_PENDIENTE = "pending"
VERIF_DIVERGENTE = "divergent"

# Registro CERRADO de estados del sidecar (§13.4.2). Uno desconocido es fallo
# cerrado para CUALQUIER ganador: sin poder leerlo no se sabe si hay una
# comparación `pending` que deba RETENER un `silencio_h4`.
ESTADOS_VERIFICACION = (VERIF_OK, VERIF_DIFERIDA, VERIF_PENDIENTE,
                        VERIF_DIVERGENTE)

SCHEMA_SILENCIO = 1
SCHEMA_VERIFICACION = 1
SCHEMA_TERMINAL = 2          # §13.7: sin migración desde 1
SEMILLA_SILENCIO = "0" * 64

PARAMS = (
    "SERVICIO", "NAMESPACE_CONFIG", "UNIVERSO", "TF_OBSERVADAS",
    "ENDPOINT_KLINES", "ENDPOINT_TIME", "LIMITE_PAGINA", "CADENCIA_MS",
    "MARGEN_CIERRE_MS", "RESOLAPE", "LAG_MAX_MS", "DERIVA_MAX_MS",
    "SILENCIO_MAX_H4_MS", "TOPE_INTERVALO_MS", "BACKOFF_BASE_MS",
    "BACKOFF_MAX_MS", "BACKOFF_INTENTOS", "CADENCIA_VERIFICACION_MS",
    "RAIZ", "SUBRUTA_ESTADO", "SUBRUTA_LIBRO", "ARCHIVO_LOCK",
    "CARPETA_ALMACENES", "CARPETA_STAGING", "ARCHIVO_COMPLETADO",
    "ARCHIVO_BLOQUEADO", "ARCHIVO_SILENCIO", "ARCHIVO_VERIFICACION",
    "ARCHIVO_SOLICITUD_TERMINAL", "ARCHIVO_PEDIDO_VERIFICACION",
    "SCHEMA_SILENCIO", "SCHEMA_VERIFICACION", "SCHEMA_TERMINAL",
    "SEMILLA_SILENCIO",
    # Los estados terminales, sus motivos y su PRECEDENCIA también son
    # comportamiento congelado: quedaban fuera de la huella y podían cambiar
    # qué terminal gana sin que la identidad del observador se moviera.
    "COMPLETADO", "BLOQUEADO", "MOTIVO_SILENCIO", "MOTIVO_DIVERGENCIA",
    "PRECEDENCIA_MOTIVOS", "PRECEDENCIA_TERMINAL", "MOTIVOS_INTEGRIDAD",
    "MOTIVOS_CIENTIFICOS",
    "VERIF_OK", "VERIF_DIFERIDA", "VERIF_PENDIENTE", "VERIF_DIVERGENTE",
    "ESTADOS_VERIFICACION",
)


def huella() -> str:
    """SHA-256 de los parámetros congelados. Entra en la identidad del
    observador: cambiar cualquiera es otro observador."""
    g = globals()
    cuerpo = {k: g[k] for k in PARAMS}
    return hashlib.sha256(
        json.dumps(cuerpo, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()
