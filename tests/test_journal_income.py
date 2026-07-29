"""La caché de income no debe re-leer el histórico completo en cada corrida."""
import json
import os
import tempfile

from modules.journal import collector as col

DIA = 86_400_000
HORA = 3_600_000


def _fake(llamadas, edad_nacimiento_dias=60):
    """Cuenta nacida hace N días, con actividad reciente. Como la subcuenta real."""
    def futures_income(since, now):
        llamadas.append((since, now))
        filas = []
        for edad_h in (edad_nacimiento_dias * 24, 48, 2):
            t = now - edad_h * HORA
            if t >= since:
                filas.append({"tranId": edad_h, "time": t,
                              "incomeType": "REALIZED_PNL", "income": "1.0"})
        return filas
    return futures_income


def test_no_relee_un_ano_entero_en_cada_corrida(monkeypatch):
    """La condición vieja era `rows[0]["time"] > lookback_start`, o sea "si mi fila más
    vieja es más nueva que la ventana, me faltan datos". Pero la subcuenta nació en
    junio de 2026: nunca va a haber income de hace 365 días, así que no se cumplía
    JAMÁS y se re-leía el año completo cada 90 segundos.

    Con `futures_income` en peso 30 y ~53 páginas por corrida son ~1590 de peso. Medido
    en el VPS: la IP vivía en 1620 de 2400 y el watchdog quedaba ciego el 8% de los
    ciclos por -1003. Ausencia de datos no es ausencia de cobertura.
    """
    llamadas = []
    monkeypatch.setattr(col.bc, "futures_income", _fake(llamadas))
    ahora = 1_785_000_000_000
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "income.json")
        col._load_income(ahora, 365, ruta)
        primera = ahora - llamadas[-1][0]
        assert primera > 300 * DIA, "la primera corrida sí debe traer el histórico"
        for i in range(1, 5):
            col._load_income(ahora + i * 90_000, 365, ruta)
            pedido = (ahora + i * 90_000) - llamadas[-1][0]
            assert pedido < 3 * DIA, \
                f"la corrida {i+1} volvió a pedir {pedido/DIA:.0f} días de histórico"


def test_la_cobertura_se_guarda_y_solo_va_hacia_atras(monkeypatch):
    """`covered_from` es hasta dónde PREGUNTAMOS, no dónde empieza la fila más vieja.
    Como lookback_start avanza con el reloj, una vez cubierto se mantiene solo."""
    llamadas = []
    monkeypatch.setattr(col.bc, "futures_income", _fake(llamadas))
    ahora = 1_785_000_000_000
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "income.json")
        col._load_income(ahora, 365, ruta)
        c1 = json.load(open(ruta))["covered_from"]
        col._load_income(ahora + 10 * DIA, 365, ruta)
        c2 = json.load(open(ruta))["covered_from"]
        assert c1 is not None
        assert c2 <= c1, "la cobertura no puede encogerse"


def test_una_cache_sin_cobertura_declarada_se_reconstruye(monkeypatch):
    """Cachés viejas no traen `covered_from`: no se puede asumir que cubren la ventana."""
    llamadas = []
    monkeypatch.setattr(col.bc, "futures_income", _fake(llamadas))
    ahora = 1_785_000_000_000
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "income.json")
        with open(ruta, "w") as fh:   # formato antiguo, sin covered_from
            json.dump({"rows": [{"tranId": 1, "time": ahora - 5 * DIA,
                                 "incomeType": "REALIZED_PNL", "income": "1.0"}],
                       "last_time": ahora - 5 * DIA}, fh)
        col._load_income(ahora, 365, ruta)
        assert ahora - llamadas[-1][0] > 300 * DIA, \
            "sin cobertura declarada hay que reconstruir, no suponer"
