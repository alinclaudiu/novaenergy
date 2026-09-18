"""Ce vede efectiv utilizatorul, pe fixturile REALE ale unui cont adevărat.

Contul de test are un singur contract, pe electricitate, fără contoare, facturi
sau plăți. Acest test fixează comportamentul integrării exact în acest caz —
cel mai sărac cu putință — ca o regresie să fie vizibilă imediat.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.novaenergy.const import DOMAIN

from .conftest import incarca

def _contul_din_fixtura() -> dict:
    """Citește contul din fixtură în loc să scrie surogatele în cod.

    Surogatele se schimbă la fiecare regenerare a fixturilor — anonimizatorul
    folosește o sare nouă de fiecare dată, tocmai ca ele să nu fie inversabile.
    """
    from homeassistant.util import slugify

    from custom_components.novaenergy.helpers import extract_accounts

    cont = extract_accounts(incarca("login"))[0]
    return {
        "crm": cont["crm"],
        "id": cont["id"],
        "prefix_utilitate": f"sensor.novaenergy_{slugify(cont['crm'])}_electricitate",
        "prefix_cont": f"sensor.novaenergy_{slugify(cont['crm'])}",
    }


_CONT = _contul_din_fixtura()
CRM_REAL = _CONT["crm"]
ID_REAL = _CONT["id"]
PREFIX = _CONT["prefix_utilitate"]
PREFIX_CONT = _CONT["prefix_cont"]

BUCATI = {
    "balances": "principal_balances",
    "contracts": "principal_contracts",
    "metering-points": "principal_metering_points",
    "invoices": "principal_invoices",
    "payments": "principal_payments",
    "app-info": "principal_app_info",
    "self-readings": "principal_self_readings",
}


def _client_real(session, email, password, timeout=30):
    client = AsyncMock()

    async def _get(url, params=None):
        for bucata, nume in BUCATI.items():
            if bucata in url:
                return incarca(nume)
        return {}

    async def _get_all(url, params=None):
        from custom_components.novaenergy.helpers import extrage_lista

        return extrage_lista(await _get(url, params))

    client.async_login = AsyncMock(return_value=incarca("login"))
    client.async_switch_account = AsyncMock(return_value={})
    client.async_get = AsyncMock(side_effect=_get)
    client.async_get_all = AsyncMock(side_effect=_get_all)
    return client


@pytest.fixture
async def cont_real(hass):
    intrare = MockConfigEntry(
        domain=DOMAIN,
        data={
            "username": "utilizator@exemplu.test",
            "password": "parola",
            "update_interval": 21600,
            "selected_accounts": [CRM_REAL],
        },
        unique_id="utilizator@exemplu.test",
    )
    intrare.add_to_hass(hass)
    with patch("custom_components.novaenergy.NovaApiClient", side_effect=_client_real):
        await hass.config_entries.async_setup(intrare.entry_id)
        await hass.async_block_till_done()
    return intrare


async def test_integrarea_porneste_pe_contul_real(hass, cont_real):
    from homeassistant.config_entries import ConfigEntryState

    assert cont_real.state is ConfigEntryState.LOADED


async def test_utilitatea_detectata_este_electricitate(hass, cont_real):
    coordinator = next(iter(cont_real.runtime_data.coordinators.values()))
    assert coordinator.utilities == ["electricity"]


async def test_contractul_real_e_activ(hass, cont_real):
    stare = hass.states.get(f"{PREFIX}_date_contract")
    assert stare is not None
    assert stare.state == "Activ"
    assert stare.attributes["Tip client"] == "Casnic"
    assert stare.attributes["Semnat la"] == "28.08.2026"
    assert stare.attributes["Intrat în vigoare"] == "01.09.2026"
    assert stare.attributes["Tip livrare"] == "Doar electronic"


async def test_soldul_zero_este_zero_nu_indisponibil(hass, cont_real):
    """Soldul real e 0 — o valoare adevărată, nu o absență."""
    stare = hass.states.get(f"{PREFIX_CONT}_sold_total")
    assert stare is not None
    assert float(stare.state) == 0.0


async def test_prosumator_detectat_din_contract(hass, cont_real):
    """Contractul real are câmpurile de prosumator completate."""
    assert hass.states.get(f"{PREFIX_CONT}_sold_prosumator") is not None


async def test_arhivele_sunt_goale_dar_prezente(hass, cont_real):
    """Fără facturi și plăți, senzorii există și arată zero."""
    assert int(hass.states.get(f"{PREFIX_CONT}_arhiva_facturi").state) == 0
    assert int(hass.states.get(f"{PREFIX_CONT}_arhiva_plati").state) == 0
    assert hass.states.get(f"{PREFIX_CONT}_factura_restanta").state == "Nu"


async def test_fara_contoare_nu_apar_senzori_de_index(hass, cont_real):
    """Punctul de măsurare real are lista de contoare goală."""
    indexuri = [
        entitate
        for entitate in hass.states.async_entity_ids("sensor")
        if "index_contor" in entitate
    ]
    assert indexuri == []


async def test_nu_apar_entitati_pentru_gaz(hass, cont_real):
    """Contul nu are contract de gaz."""
    gaz = [
        entitate
        for entitate in hass.states.async_entity_ids("sensor")
        if entitate.startswith("sensor.novaenergy_") and "_gaz_" in entitate
    ]
    assert gaz == []
