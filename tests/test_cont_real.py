"""Ce vede efectiv utilizatorul, pe forma REALĂ a răspunsurilor unui cont adevărat.

Contul are o singură utilitate (electricitate), e prosumator și are, în anul
curent, o factură de furnizare, una de surplus de prosumator, o plată și o
citire de index. Valorile din fixturi sunt de exemplu; forma e cea autentică.
Testul fixează comportamentul integrării exact în acest caz, ca o regresie să
fie vizibilă imediat.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.novaenergy.const import DOMAIN

from .conftest import incarca

# Facturile, plata și citirea din fixturi sunt din 2026.
ZI_DE_REFERINTA = "2026-10-30"


def _contul_din_fixtura() -> dict:
    """Citește contul din fixtură în loc să scrie identificatorii în cod."""
    from homeassistant.util import slugify

    from custom_components.novaenergy.helpers import extract_accounts

    cont = extract_accounts(incarca("login"))[0]
    citire = incarca("principal_self_readings")["data"]["selfReadings"][0]
    return {
        "crm": cont["crm"],
        "serie": citire["meterSeries"],
        "prefix_utilitate": f"sensor.novaenergy_{slugify(cont['crm'])}_electricitate",
        "prefix_cont": f"sensor.novaenergy_{slugify(cont['crm'])}",
    }


_CONT = _contul_din_fixtura()
CRM_REAL = _CONT["crm"]
SERIE = _CONT["serie"]
PREFIX = _CONT["prefix_utilitate"]
PREFIX_CONT = _CONT["prefix_cont"]

BUCATI = {
    "dashboard/balance": "principal_balance",
    "contracts": "principal_contracts",
    "metering-points": "principal_metering_points",
    "invoices": "principal_invoices",
    "payments": "principal_payments",
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
async def cont_real(hass, freezer):
    freezer.move_to(ZI_DE_REFERINTA)
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


async def test_entitatile_si_identificatorii_raman_cei_din_versiunea_1_0(hass, cont_real):
    """Schimbarea API-ului nu are voie să schimbe entitățile: un `unique_id`
    nou ar rupe istoricul, tablourile și automatizările utilizatorului."""
    from homeassistant.helpers import entity_registry as er

    registru = er.async_get(hass)
    ale_integrarii = {
        intrare.entity_id: intrare.unique_id
        for intrare in registru.entities.values()
        if intrare.config_entry_id == cont_real.entry_id
    }
    sufixe = (
        "sold_total",
        "sold_prosumator",
        "factura_restanta",
        "arhiva_facturi",
        "arhiva_plati",
        "electricitate_date_contract",
        f"electricitate_index_contor_{SERIE}",
    )
    assert ale_integrarii == {
        f"sensor.novaenergy_{CRM_REAL}_{sufix}": f"novaenergy_{CRM_REAL}_{sufix}"
        for sufix in sufixe
    }


async def test_utilitatea_detectata_este_electricitate(hass, cont_real):
    coordinator = next(iter(cont_real.runtime_data.coordinators.values()))
    assert coordinator.utilities == ["electricity"]


async def test_contractul_real_e_activ(hass, cont_real):
    stare = hass.states.get(f"{PREFIX}_date_contract")
    assert stare is not None
    assert stare.state == "Activ"
    assert stare.attributes["Tip client"] == "Casnic"
    assert stare.attributes["Semnat la"] == "12.06.2026"
    assert stare.attributes["Intrat în vigoare"] == "01.07.2026"
    assert stare.attributes["Tip livrare"] == "Doar electronic"


async def test_soldul_zero_este_zero_nu_indisponibil(hass, cont_real):
    """Soldul e 0 — o valoare adevărată, nu o absență."""
    stare = hass.states.get(f"{PREFIX_CONT}_sold_total")
    assert stare is not None
    assert float(stare.state) == 0.0


async def test_prosumator_detectat_din_sold(hass, cont_real):
    """Noul API nu mai trimite contractul de prosumator; semnalul e
    `isProsumer` din sold, iar valoarea e creditul din surplus."""
    stare = hass.states.get(f"{PREFIX_CONT}_sold_prosumator")
    assert stare is not None
    assert float(stare.state) == 120.45


async def test_nicio_factura_restanta(hass, cont_real):
    """Ambele facturi sunt achitate; surplusul negativ nu e datorie."""
    stare = hass.states.get(f"{PREFIX_CONT}_factura_restanta")
    assert stare.state == "Nu"
    assert stare.attributes["Facturi neachitate"] == 0


async def test_arhiva_facturilor_separa_surplusul(hass, cont_real):
    """Două facturi în aceeași zi: amândouă rămân vizibile, iar surplusul de
    prosumator nu scade din totalul facturat."""
    stare = hass.states.get(f"{PREFIX_CONT}_arhiva_facturi")
    assert int(stare.state) == 2
    assert stare.attributes["Total facturat"] == "12,34 lei"
    assert stare.attributes["Total surplus prosumator"] == "-120,45 lei"
    valori = {
        cheie: valoare
        for cheie, valoare in stare.attributes.items()
        if cheie.startswith("Emisă pe 15.09.2026")
    }
    assert sorted(valori.values()) == ["-120,45 lei (surplus prosumator)", "12,34 lei"]


async def test_arhiva_platilor(hass, cont_real):
    stare = hass.states.get(f"{PREFIX_CONT}_arhiva_plati")
    assert int(stare.state) == 1
    assert stare.attributes["Plătită pe 25.09.2026"] == "12,34 lei"
    assert stare.attributes["Total plătit"] == "12,34 lei"


async def test_indexul_vine_din_istoricul_de_citiri(hass, cont_real):
    stare = hass.states.get(f"{PREFIX}_index_contor_{SERIE}")
    assert stare is not None
    assert float(stare.state) == 4321.5
    assert stare.attributes["unit_of_measurement"] == "kWh"
    assert stare.attributes["device_class"] == "energy"
    assert stare.attributes["state_class"] == "total_increasing"
    assert stare.attributes["Ultima citire"] == "31.08.2026"
    assert stare.attributes["Serie contor"] == SERIE


async def test_nu_apar_entitati_pentru_gaz(hass, cont_real):
    """Contul nu are contract de gaz."""
    gaz = [
        entitate
        for entitate in hass.states.async_entity_ids("sensor")
        if entitate.startswith("sensor.novaenergy_") and "_gaz_" in entitate
    ]
    assert gaz == []


async def test_dispozitivele_raman_cele_din_versiunea_1_0(hass, cont_real):
    """Identificatorii dispozitivelor folosesc codul API al utilității
    (`electricity`), iar entitățile slug-ul românesc (`electricitate`).
    Nepotrivirea e moștenită și trebuie păstrată: o „armonizare" ar crea
    dispozitive noi și le-ar lăsa goale pe cele vechi."""
    from homeassistant.helpers import device_registry as dr

    registru = dr.async_get(hass)
    dispozitive = dr.async_entries_for_config_entry(registru, cont_real.entry_id)
    dupa_identificator = {
        next(iter(dispozitiv.identifiers)): dispozitiv for dispozitiv in dispozitive
    }
    assert set(dupa_identificator) == {
        (DOMAIN, CRM_REAL),
        (DOMAIN, f"{CRM_REAL}_electricity"),
    }
    cont = dupa_identificator[(DOMAIN, CRM_REAL)]
    utilitate = dupa_identificator[(DOMAIN, f"{CRM_REAL}_electricity")]
    assert utilitate.via_device_id == cont.id
