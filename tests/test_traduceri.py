"""Traducerile trebuie să acopere tot ce folosește codul."""

import json
import re
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "novaenergy"


def _incarca(nume: str) -> dict:
    return json.loads((COMPONENT / nume).read_text(encoding="utf-8"))


def _chei(obiect, prefix=""):
    """Toate căile de chei dintr-un dicționar imbricat."""
    cai = set()
    for cheie, valoare in obiect.items():
        cale = f"{prefix}.{cheie}" if prefix else cheie
        if isinstance(valoare, dict):
            cai |= _chei(valoare, cale)
        else:
            cai.add(cale)
    return cai


def test_ro_si_en_au_aceleasi_chei():
    ro = _incarca("translations/ro.json")
    en = _incarca("translations/en.json")
    assert _chei(ro) == _chei(en)


def test_strings_identic_cu_engleza():
    """strings.json e sursa traducerilor; trebuie să acopere aceleași chei."""
    assert _chei(_incarca("strings.json")) == _chei(_incarca("translations/en.json"))


def test_toate_erorile_din_cod_au_traducere():
    sursa = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    folosite = set(re.findall(r'erori\["base"\] = "(\w+)"', sursa))
    strings = _incarca("strings.json")

    assert folosite, "testul nu a găsit nicio cheie de eroare în config_flow.py"
    assert folosite <= set(strings["config"]["error"])


def test_traducerea_romana_are_diacritice():
    text = (COMPONENT / "translations/ro.json").read_text(encoding="utf-8")
    assert any(diacritic in text for diacritic in "ăâîșț")
