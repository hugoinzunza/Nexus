"""El graduador sombra queda APAGADO salvo decision explicita y versionada."""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config", "nexus.json")
GRADER = os.path.join(ROOT, "modules/trading/claude_grader.py")
MODULE = os.path.join(ROOT, "modules/trading/module.py")


def test_la_bandera_viene_apagada_en_config():
    """Opt-in EXPLICITO, no por presencia de API key. La key vive en el entorno de
    Railway, asi que el graduador se encendia solo alli sin que nada en el repo lo
    dijera, y `bot.live=false` no lo apagaba porque nunca lo miro."""
    cfg = json.load(open(CFG, encoding="utf-8"))
    t = cfg["modules"]["trading"]
    assert "claude_grader_enabled" in t, "la bandera desaparecio de config"
    assert t["claude_grader_enabled"] is False, "el graduador quedo encendido"


def test_available_mira_la_bandera_ANTES_que_la_key(monkeypatch):
    """Con la bandera apagada, `available()` es False aunque haya key y SDK. Y se
    consulta antes del cache `_checked`: si se mirara despues, cambiarla exigiria
    reiniciar el proceso."""
    import sys
    sys.path.insert(0, ROOT)
    from modules.trading import claude_grader as g

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-de-mentira-no-se-usa")
    monkeypatch.setattr(g, "habilitado", lambda: False)
    assert g.available() is False

    # SIN el docstring: `_checked` se menciona ahi antes de aparecer en el codigo, y
    # el assert saltaba con la prosa que explica el orden en vez de con el orden.
    src = open(GRADER, encoding="utf-8").read()
    cuerpo = src.split("def available() -> bool:")[1].split("\ndef ")[0]
    cuerpo = cuerpo.split('"""')[2] if cuerpo.count('"""') >= 2 else cuerpo
    # Contra `if _checked:` y no contra `_checked` a secas: la declaracion `global`
    # nombra la variable antes, y declararla no es consultarla.
    assert cuerpo.index("habilitado()") < cuerpo.index("if _checked:"), \
        "la bandera se mira despues del cache: apagarla no tendria efecto en caliente"
    assert cuerpo.index("habilitado()") < cuerpo.index("_resolve_key"), \
        "resuelve la key antes de mirar la bandera"


def test_sin_config_legible_queda_apagado():
    """Falla CERRADO: si no se puede leer la config, no se gasta."""
    src = open(GRADER, encoding="utf-8").read()
    cuerpo = src.split("def habilitado() -> bool:")[1].split("\ndef ")[0]
    assert "return False" in cuerpo.split("except")[1]
    assert 'get("claude_grader_enabled", False)' in cuerpo, "el default no es False"


def test_el_sitio_de_llamada_tambien_comprueba():
    """Doble defensa: el gate tiene que estar VISIBLE donde se gasta, no solo dentro
    de un helper llamado `available`."""
    src = open(MODULE, encoding="utf-8").read()
    assert "claude_grader.habilitado()" in src
    bloque = src.split("if (created and claude_grader.habilitado()")[1][:120]
    assert "available()" in bloque and "_grade_in_background" in bloque


def test_NINGUNA_decision_puede_leer_el_grado():
    """El candado que importa. `claude_grade`/`claude_keep` son metadata y no pueden
    entrar en filtros, sizing, transiciones ni ejecucion.

    Medido el 2026-07-27 sobre 254 setups con resultado: keep=True avgR +0,258 contra
    keep=False +0,506, con CI95 por bloques diarios [-0,546, +0,039] que CRUZA CERO.
    O sea no hay discriminacion positiva demostrada — y tampoco autoriza invertirlo.
    Promoverlo a gate sin evidencia nueva seria actuar sobre ruido.
    """
    import glob
    import re
    # Con limite de palabra: `claude_grader` CONTIENE `claude_grade` como subcadena, y
    # sin esto el test acusaba a un comentario que solo nombra al modulo.
    patron = re.compile(r"\bclaude_(grade|keep)\b")
    permitidos = {
        os.path.join(ROOT, "modules/trading/setups_store.py"),   # solo lo escribe
        os.path.join(ROOT, "modules/trading/claude_grader.py"),  # lo produce
    }
    ofensores = []
    for ruta in glob.glob(os.path.join(ROOT, "modules/**/*.py"), recursive=True):
        if ruta in permitidos:
            continue
        texto = open(ruta, encoding="utf-8").read()
        for linea in texto.splitlines():
            limpia = linea.split("#")[0]
            if patron.search(limpia):
                ofensores.append(f"{os.path.relpath(ruta, ROOT)}: {linea.strip()[:70]}")
    assert not ofensores, "alguna decision lee el grado del graduador:\n" + "\n".join(ofensores)
