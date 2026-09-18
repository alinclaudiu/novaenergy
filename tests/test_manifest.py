"""Verifică metadata integrării și absența oricărui mecanism de licențiere."""

import json
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "novaenergy"


def test_manifest_valid():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "novaenergy"
    assert manifest["domain"] == COMPONENT.name
    assert manifest["config_flow"] is True
    assert manifest["requirements"] == []
    assert manifest["codeowners"] == ["@alinclaudiu"]


def test_fara_licentiere():
    """Nicio urmă de sistem de licențiere în integrare."""
    interzise = ("license", "licenta", "licență", "fingerprint", "activation")
    for fisier in COMPONENT.rglob("*.py"):
        continut = fisier.read_text(encoding="utf-8").lower()
        for cuvant in interzise:
            assert cuvant not in continut, f"{fisier} conține '{cuvant}'"


def test_hacs_json_valid():
    hacs = json.loads((COMPONENT.parent.parent / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["country"] == ["RO"]
    assert hacs["homeassistant"] == "2025.11.0"
