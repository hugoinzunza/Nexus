"""La fuente canónica es lo único que separa a las cohortes de otra mudanza de repo.

Si deja de ser append-only, `shadow_exit` y `candle_reversal_shadow` pierden registros en
silencio: ambos reconstruyen su cohorte iterando los setups presentes en el archivo fuente.
"""
import json

from research.hypothesis_lab import canonical_setups


def _setup(key, creado, **extra):
    base = {"key": key, "ts_created": creado, "dir": "long",
            "entry": 100.0, "sl": 99.0, "tp": 105.0}
    base.update(extra)
    return base


def _escribir(path, setups):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(setups), encoding="utf-8")
    return path


def test_une_los_dos_stores_sin_perder_ninguno(tmp_path):
    viejo = _escribir(tmp_path / "viejo.json", [_setup("BTC", 1), _setup("ETH", 2)])
    vivo = _escribir(tmp_path / "vivo.json", [_setup("SOL", 3)])

    payload = canonical_setups.merge([viejo, vivo], tmp_path / "canonical.json")

    assert payload["meta"]["total"] == 3
    assert {row["key"] for row in payload["setups"]} == {"BTC", "ETH", "SOL"}


def test_un_setup_canonizado_sobrevive_a_la_desaparicion_de_su_origen(tmp_path):
    """El escenario exacto del 2026-08-06: el servidor se muda de repositorio y el store
    que tenía la historia deja de existir para el observador."""
    viejo = _escribir(tmp_path / "viejo.json", [_setup("BTC", 1)])
    vivo = _escribir(tmp_path / "vivo.json", [_setup("SOL", 3)])
    salida = tmp_path / "canonical.json"
    canonical_setups.merge([viejo, vivo], salida)

    # El store histórico desaparece del todo.
    viejo.unlink()
    payload = canonical_setups.merge([viejo, vivo], salida)

    assert payload["meta"]["total"] == 2
    assert {row["key"] for row in payload["setups"]} == {"BTC", "SOL"}
    assert payload["meta"]["sources"][0]["error"] == "source_missing"


def test_conserva_la_version_mas_nueva_de_un_setup_que_evoluciona(tmp_path):
    salida = tmp_path / "canonical.json"
    origen = _escribir(tmp_path / "vivo.json",
                       [_setup("BTC", 1, status="pendiente", ts_updated=10)])
    canonical_setups.merge([origen], salida)

    _escribir(origen, [_setup("BTC", 1, status="ganada", ts_updated=20, result_r=5.0)])
    payload = canonical_setups.merge([origen], salida)

    assert payload["meta"]["total"] == 1
    assert payload["setups"][0]["status"] == "ganada"
    assert payload["meta"]["updated_this_pass"] == 1


def test_nunca_retrocede_a_una_version_anterior(tmp_path):
    salida = tmp_path / "canonical.json"
    nuevo = _escribir(tmp_path / "a.json", [_setup("BTC", 1, status="ganada", ts_updated=20)])
    canonical_setups.merge([nuevo], salida)

    viejo = _escribir(tmp_path / "b.json", [_setup("BTC", 1, status="pendiente", ts_updated=10)])
    payload = canonical_setups.merge([viejo], salida)

    assert payload["setups"][0]["status"] == "ganada"
    assert payload["meta"]["updated_this_pass"] == 0


def test_es_idempotente(tmp_path):
    salida = tmp_path / "canonical.json"
    origen = _escribir(tmp_path / "vivo.json", [_setup("BTC", 1), _setup("ETH", 2)])

    canonical_setups.merge([origen], salida)
    segunda = canonical_setups.merge([origen], salida)

    assert segunda["meta"]["added_this_pass"] == 0
    assert segunda["meta"]["updated_this_pass"] == 0
    assert segunda["meta"]["total"] == 2


def test_la_lista_plana_solo_se_reescribe_cuando_el_contenido_cambia(tmp_path):
    """Reescribir sin cambios es el falso positivo de frescura que este sprint eliminó,
    y además haría abortar la pasada de `candle_reversal_shadow`."""
    salida = tmp_path / "canonical.json"
    plana = tmp_path / "setups.json"
    origen = _escribir(tmp_path / "vivo.json", [_setup("BTC", 1)])

    assert canonical_setups.merge_to_flat([origen], salida, plana)["meta"]["flat_rewritten"]
    assert not canonical_setups.merge_to_flat([origen], salida, plana)["meta"]["flat_rewritten"]

    _escribir(origen, [_setup("BTC", 1), _setup("ETH", 2)])
    assert canonical_setups.merge_to_flat([origen], salida, plana)["meta"]["flat_rewritten"]
    assert json.loads(plana.read_text(encoding="utf-8"))[-1]["key"] == "ETH"


def test_un_origen_ilegible_no_detiene_la_union(tmp_path):
    roto = tmp_path / "roto.json"
    roto.write_text("{no es json", encoding="utf-8")
    bueno = _escribir(tmp_path / "bueno.json", [_setup("BTC", 1)])

    payload = canonical_setups.merge([roto, bueno], tmp_path / "canonical.json")

    assert payload["meta"]["total"] == 1
    assert payload["meta"]["sources"][0]["present"] is False
    assert payload["meta"]["sources"][1]["present"] is True


def test_no_escribe_jamas_en_los_origenes(tmp_path):
    origen = _escribir(tmp_path / "vivo.json", [_setup("BTC", 1)])
    antes = origen.read_bytes(), origen.stat().st_mtime_ns

    canonical_setups.merge([origen], tmp_path / "canonical.json")

    assert (origen.read_bytes(), origen.stat().st_mtime_ns) == antes
