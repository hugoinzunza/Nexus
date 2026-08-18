"""Bot3.v9 — constantes, serialización canónica e identidades del contrato.

Implementa literalmente el protocolo pre-registrado congelado:
`docs/BOT3_V9_PROTOCOLO.md`, SHA-256
`9d24166a33aa74af7f2b2dd7d0bdf4e2d16866e13eec7c48e7b1480512001530`
(declarado CONFORME PARA IMPLEMENTACIÓN por la auditoría independiente).

Cláusulas cubiertas aquí: CF-9 (serialización canónica de identidades),
CF-15 (política numérica Q), CF-30 (`event_id` universal), CF-37 (registro
CERRADO de tipos de evento) y la tabla de parámetros congelados.

research_only: este paquete no importa ejecutor, credenciales ni clientes
privados, y no expone endpoints de escritura.
"""
from __future__ import annotations

import hashlib
import json

# --- Identidad del contrato ------------------------------------------------
CONTRATO_HASH = "9d24166a33aa74af7f2b2dd7d0bdf4e2d16866e13eec7c48e7b1480512001530"
PROTOCOLO = "BOT3_V9"

# --- Universo y temporalidades (orden canónico alfabético) -----------------
MERCADOS = ("ADAUSDT", "BNBUSDT", "BTCUSDT", "DOGEUSDT",
            "ETHUSDT", "SOLUSDT", "XRPUSDT")
TF_H4 = "4h"
TF_M15 = "15m"
TF_MS = {"15m": 900_000, "4h": 14_400_000}

# --- Génesis y cobertura (CF-13, CF-28) ------------------------------------
GENESIS_H4 = 1_646_092_800_000          # 2022-03-01T00:00:00Z
EPOCA_M15_MIN_VELAS = 200

# --- Watermarks (CF-22, CF-29, CF-36) --------------------------------------
WATERMARK_LOCAL_N = 3                   # cierres propios posteriores
WATERMARK_EXCHANGE_Q = 4                # mercados de referencia calificantes
WATERMARK_EXCHANGE_N = 3                # cierres sincronizados por mercado

# --- Estructura y submodelo (diseño rev.3 §6-bis, CF-13/14) ----------------
STRUCT_PIV = 8
INT_PIV = 3
SWEEP_LOOKBACK_SWINGS = 6
DIR_EXPIRA_H4 = 180                     # velas H4 sin BOS de continuación
TTL_ZONA_H4 = 180                       # velas H4 desde available_at
DEADLINE_M15 = 64                       # velas M15 desde el toque
VENTANA_IBOS_M15 = 48                   # velas M15 desde el toque
OB_LOOKBACK = 6                         # velas hacia atrás para el OB del FVG

# --- Riesgo y costos (CF-4, CF-15) -----------------------------------------
SL_BUFFER = 0.001                       # 0,1%
RR_MIN = 2.0
FEE_MAKER = 0.0002
FEE_TAKER = 0.0005
SLIPPAGE_STOP = 0.0005
FUNDING_RATE = 0.0001                   # por devengo de 8 h, siempre cargo
FUNDING_HORAS_UTC = (0, 8, 16)

# --- Corte y evaluación (CF-11, CF-35) -------------------------------------
T_CORTE = 1_798_761_599_999             # 2026-12-31T23:59:59.999Z, inclusivo
CORTE_N_CIERRES = 50
CORTE_MIN_SEMANAS_ISO = 8
CORTE_ADMIN_GRACIA_MS = 86_400_000      # 24 h de reloj tras T_corte
BOOTSTRAP_REPLICAS = 10_000
BOOTSTRAP_SEMILLA = 20260817


# --- Serialización canónica (CF-9) -----------------------------------------
def canon(obj) -> str:
    """JSON canónico: UTF-8 sin BOM, claves ordenadas, separadores sin
    espacios. Nunca floats JSON (los precios van como cadenas)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha256_hex(texto: str) -> str:
    """SHA-256 en hexadecimal minúscula de los bytes UTF-8."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def Q(x: float) -> float:
    """Cuantización única del protocolo (CF-15): half-even a 6 decimales
    sobre float64 IEEE-754. Es el ÚNICO operador de cuantización."""
    return round(float(x), 6)


def p6(x: float) -> str:
    """Precio cuantizado como cadena de exactamente 6 decimales (CF-9)."""
    return "%.6f" % Q(x)


def repr_f(x: float) -> str:
    """Representación decimal más corta que hace round-trip al mismo float64
    (CF-17). Usada SOLO por el almacén: cubre los crudos que consume el
    motor, no los valores cuantizados."""
    return repr(float(x))


# --- Identidades jerárquicas (CF-9) ----------------------------------------
def candidate_id(mercado: str, direccion: str, zona_avail: int,
                 zona_lo: float, zona_hi: float, toque_t: int,
                 contrato: str = CONTRATO_HASH) -> str:
    return sha256_hex(canon({
        "contrato": contrato, "dir": direccion, "mercado": mercado,
        "tipo": "candidate", "toque_t": int(toque_t),
        "zona_avail": int(zona_avail),
        "zona_hi": p6(zona_hi), "zona_lo": p6(zona_lo),
    }))


def order_id(cand_id: str, derivada_avail: int,
             derivada_lo: float, derivada_hi: float) -> str:
    return sha256_hex(canon({
        "candidate": cand_id, "derivada_avail": int(derivada_avail),
        "derivada_hi": p6(derivada_hi), "derivada_lo": p6(derivada_lo),
        "tipo": "order",
    }))


def trade_id(ord_id: str, fill_t: int, fill_precio: float) -> str:
    return sha256_hex(canon({
        "fill_precio": p6(fill_precio), "fill_t": int(fill_t),
        "order": ord_id, "tipo": "trade",
    }))


# --- Registro CERRADO de tipos de evento (CF-37) ---------------------------
# Agregar o modificar un tipo exige protocolo v10. Ningún evento puede usar
# una serialización ad hoc.
FAM_JERARQUIA = "jerarquia"
FAM_DESCARTE = "descarte"
FAM_ABSTENCION = "abstencion"
FAM_BARRERA = "barrera"
FAM_MERCADO = "mercado"
FAM_NACIMIENTO = "nacimiento"
FAM_HUECO = "hueco"
FAM_COBERTURA = "cobertura"
FAM_INCIDENCIA = "incidencia"

TIPOS: dict[str, str] = {
    # Jerarquía de trade — preimagen {"contrato","id","tipo"}
    "candidato": FAM_JERARQUIA,
    "orden_creada": FAM_JERARQUIA,
    "orden_cancelada": FAM_JERARQUIA,
    "fill": FAM_JERARQUIA,
    "cerrado": FAM_JERARQUIA,
    "trayectoria_indeterminada": FAM_JERARQUIA,
    "gap_ambiguo": FAM_JERARQUIA,
    "confirmada_sin_fill": FAM_JERARQUIA,
    "descartada_por_arbitraje": FAM_JERARQUIA,
    "abierta_al_corte": FAM_JERARQUIA,      # id = trade
    "orden_al_corte": FAM_JERARQUIA,        # id = order
    # Descarte con zona
    "descarte": FAM_DESCARTE,
    # Abstención sin zona
    "abstencion": FAM_ABSTENCION,
    # Global de barrera
    "lote_finalizado": FAM_BARRERA,
    "frontera": FAM_BARRERA,
    "corte_administrativo": FAM_BARRERA,
    # Estructural por mercado
    "estado_inicial": FAM_MERCADO,
    "epoca_m15": FAM_MERCADO,
    "mercado_degradado": FAM_MERCADO,
    "mercado_reingresado": FAM_MERCADO,
    # Nacimiento del almacén
    "nacimiento": FAM_NACIMIENTO,
    # Hueco (reflejo en ledger)
    "hueco_detectado": FAM_HUECO,
    # Cobertura al corte
    "degradacion_de_cobertura": FAM_COBERTURA,
    # Incidencias de ingestión (CF-26)
    "vela_revisada": FAM_INCIDENCIA,
    "vela_no_incorporada": FAM_INCIDENCIA,
}

MOTIVOS_ABSTENCION = (
    "rango_sin_origen", "historia_insuficiente", "sin_weak_cerrado",
    "direccion_expirada", "direccion_desconocida", "epoca_no_habilitada",
)


def event_id(tipo: str, *, contrato: str = CONTRATO_HASH, id: str | None = None,
             mercado: str | None = None, t: int | None = None,
             tf: str | None = None, motivo: str | None = None,
             desde: int | None = None, hasta: int | None = None,
             zona_avail: int | None = None, zona_lo: float | None = None,
             zona_hi: float | None = None) -> str:
    """`event_id` universal (CF-30/CF-37): SHA-256 de la preimagen canónica de
    la familia del tipo. Un tipo fuera del registro es un error de contrato."""
    fam = TIPOS.get(tipo)
    if fam is None:
        raise ValueError(f"tipo fuera del registro cerrado CF-37: {tipo!r}")
    if fam == FAM_JERARQUIA:
        pre = {"contrato": contrato, "id": id, "tipo": tipo}
    elif fam == FAM_DESCARTE:
        pre = {"contrato": contrato, "mercado": mercado, "motivo": motivo,
               "t": int(t), "tipo": tipo, "zona_avail": int(zona_avail),
               "zona_hi": p6(zona_hi), "zona_lo": p6(zona_lo)}
    elif fam == FAM_ABSTENCION:
        pre = {"contrato": contrato, "mercado": mercado, "motivo": motivo,
               "t": int(t), "tipo": tipo}
    elif fam == FAM_BARRERA:
        pre = {"contrato": contrato, "t": int(t), "tipo": tipo}
    elif fam == FAM_MERCADO:
        pre = {"contrato": contrato, "mercado": mercado, "t": int(t),
               "tipo": tipo}
    elif fam == FAM_NACIMIENTO:
        pre = {"contrato": contrato, "mercado": mercado, "t": int(t),
               "tf": tf, "tipo": tipo}
    elif fam == FAM_HUECO:
        pre = {"contrato": contrato, "desde": int(desde), "hasta": int(hasta),
               "mercado": mercado, "tf": tf, "tipo": tipo}
    elif fam == FAM_COBERTURA:
        pre = {"contrato": contrato, "desde": int(desde), "hasta": int(hasta),
               "mercado": mercado, "tipo": tipo}
    else:  # FAM_INCIDENCIA — CF-26
        pre = {"contenido": id, "mercado": mercado, "t": int(t), "tf": tf,
               "tipo": tipo}
    return sha256_hex(canon(pre))


def incidencia_id(tipo: str, mercado: str, tf: str, t: int,
                  contenido_sha: str) -> str:
    """CF-26: identidad estable de incidencia de ingestión (dedupe
    independiente de la frecuencia de pull)."""
    return event_id(tipo, mercado=mercado, tf=tf, t=t, id=contenido_sha)
