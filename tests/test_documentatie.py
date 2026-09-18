"""Documentația trebuie să existe, să fie în română și să acopere toate entitățile."""

from pathlib import Path

import pytest

from custom_components.novaenergy.sensor import (
    CHEI_ENTITATI,
    SENZORI_DE_CONT,
    SENZORI_DE_UTILITATE,
)

RADACINA = Path(__file__).parent.parent
DOCUMENTE = ("README.md", "SETUP.md", "FAQ.md", "DEBUG.md")


@pytest.mark.parametrize("nume", DOCUMENTE)
def test_documentul_exista_si_e_in_romana(nume):
    continut = (RADACINA / nume).read_text(encoding="utf-8")
    assert len(continut) > 2000, f"{nume} e prea scurt"
    assert any(diacritic in continut for diacritic in "ăâîșț"), f"{nume} nu are diacritice"


def test_cheile_simple_sunt_in_lista_centrala():
    for descriere in SENZORI_DE_CONT + SENZORI_DE_UTILITATE:
        assert descriere.key in CHEI_ENTITATI


def test_toate_entitatile_sunt_documentate():
    readme = (RADACINA / "README.md").read_text(encoding="utf-8")
    for cheie in CHEI_ENTITATI:
        assert cheie in readme, f"senzorul {cheie} nu apare în README"


def test_readme_nu_promite_licentiere():
    readme = (RADACINA / "README.md").read_text(encoding="utf-8").lower()
    for expresie in ("licență necesară", "cumpără o licență", "cheie de activare"):
        assert expresie not in readme


def test_readme_indica_licenta_mit():
    readme = (RADACINA / "README.md").read_text(encoding="utf-8")
    assert "MIT" in readme


def test_sabloanele_de_issue_exista():
    sabloane = RADACINA / ".github" / "ISSUE_TEMPLATE"
    assert (sabloane / "config.yml").exists()
    assert list(sabloane.glob("*bug*")), "lipsește șablonul de raportare a erorilor"


def test_workflow_urile_de_validare_exista():
    workflows = RADACINA / ".github" / "workflows"
    assert (workflows / "hassfest.yml").exists()
    assert (workflows / "hacs.yml").exists()


def test_niciun_workflow_de_analytics():
    """Integrarea nu colectează statistici despre utilizatori."""
    workflows = RADACINA / ".github" / "workflows"
    for fisier in workflows.glob("*.yml"):
        assert "analytics" not in fisier.name.lower()
