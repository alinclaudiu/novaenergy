"""Senzorii, verificați prin stările reale produse de integrare."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.novaenergy.const import DOMAIN

from .conftest import CRM_A, CRM_B, fabrica_client

PREFIX_GAZ = "sensor.novaenergy_3047398_gaz"
PREFIX_CONT_A = "sensor.novaenergy_3047398"
PREFIX_CONT_B = "sensor.novaenergy_3008726"
PREFIX_B_GAZ = "sensor.novaenergy_3008726_gaz"
PREFIX_B_ELE = "sensor.novaenergy_3008726_electricitate"


# Fixturile au facturi din 2026; fără timp înghețat, testele de arhivă ar
# începe să eșueze la schimbarea anului.
ZI_DE_REFERINTA = "2026-09-18"


async def _porneste(hass, date_intrare, suprascrieri=None):
    intrare = MockConfigEntry(
        domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"]
    )
    intrare.add_to_hass(hass)
    with patch(
        "custom_components.novaenergy.NovaApiClient",
        side_effect=fabrica_client(suprascrieri=suprascrieri),
    ):
        await hass.config_entries.async_setup(intrare.entry_id)
        await hass.async_block_till_done()
    return intrare


@pytest.fixture
async def pornit(hass, date_intrare):
    return await _porneste(hass, date_intrare)


# ──────────────────────────────────────────────
# Senzori simpli
# ──────────────────────────────────────────────
async def test_sold_total(hass, pornit):
    stare = hass.states.get(f"{PREFIX_CONT_A}_sold_total")
    assert stare is not None
    assert float(stare.state) == 223.70
    assert stare.attributes["device_class"] == "monetary"
    assert stare.attributes["unit_of_measurement"] == "RON"


async def test_factura_restanta(hass, pornit):
    stare = hass.states.get(f"{PREFIX_CONT_A}_factura_restanta")
    assert stare.state == "Da"
    assert stare.attributes["Total restant"] == "223,70 lei"
    assert stare.attributes["Facturi neachitate"] == 2
    assert stare.attributes["Scadența ultimei facturi"] == "15.04.2026"


async def test_sold_prosumator_lipseste_pe_cont_fara_prosumator(hass, pornit):
    """Regula de existență: entitatea nu se creează deloc."""
    assert hass.states.get(f"{PREFIX_CONT_A}_sold_prosumator") is None


async def test_sold_prosumator_apare_cand_exista(hass, date_intrare):
    date_intrare = {**date_intrare, "selected_accounts": [CRM_B]}
    await _porneste(hass, date_intrare)
    stare = hass.states.get(f"{PREFIX_CONT_B}_sold_prosumator")
    assert stare is not None
    assert float(stare.state) == 45.30


async def test_date_lipsa_temporar_dau_unavailable(hass, date_intrare):
    """Sold absent ≠ sold zero."""
    await _porneste(hass, date_intrare, suprascrieri={"contA_balances": {}})
    stare = hass.states.get(f"{PREFIX_CONT_A}_sold_total")
    assert stare.state == "unavailable"


# ──────────────────────────────────────────────
# Senzori cu atribute bogate
# ──────────────────────────────────────────────
async def test_arhiva_facturi_doar_anul_curent(hass, date_intrare, freezer):
    freezer.move_to(ZI_DE_REFERINTA)
    await _porneste(hass, date_intrare)
    stare = hass.states.get(f"{PREFIX_CONT_A}_arhiva_facturi")
    assert int(stare.state) == 2  # a treia factură e din 2025
    assert stare.attributes["Total facturat"] == "223,70 lei"
    assert stare.attributes["Emisă pe 04.03.2026"] == "125,50 lei"


async def test_arhiva_plati(hass, date_intrare, freezer):
    freezer.move_to(ZI_DE_REFERINTA)
    await _porneste(hass, date_intrare)
    stare = hass.states.get(f"{PREFIX_CONT_A}_arhiva_plati")
    assert int(stare.state) == 1
    assert stare.attributes["Total plătit"] == "125,50 lei"
    assert stare.attributes["Plătită pe 10.03.2026"] == "125,50 lei"


async def test_date_contract(hass, pornit):
    stare = hass.states.get(f"{PREFIX_GAZ}_date_contract")
    assert stare.state == "Activ"
    assert stare.attributes["Tip client"] == "Casnic"
    assert stare.attributes["Semnat la"] == "15.01.2024"
    assert stare.attributes["Intrat în vigoare"] == "01.02.2024"


async def test_index_contor_per_serie(hass, pornit):
    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567")
    assert stare is not None
    assert float(stare.state) == 6030
    assert stare.attributes["unit_of_measurement"] == "m³"
    assert stare.attributes["Ultima citire"] == "01.03.2026"
    assert stare.attributes["Consum"] == "145,00"


async def test_utilitatile_au_device_uri_separate(hass, date_intrare):
    date_intrare = {**date_intrare, "selected_accounts": [CRM_B]}
    await _porneste(hass, date_intrare)
    assert hass.states.get(f"{PREFIX_B_GAZ}_date_contract") is not None
    assert (
        hass.states.get(f"{PREFIX_B_ELE}_date_contract") is not None
    )


async def test_index_electricitate_are_kwh(hass, date_intrare):
    date_intrare = {**date_intrare, "selected_accounts": [CRM_B]}
    await _porneste(hass, date_intrare)
    stare = hass.states.get(f"{PREFIX_B_ELE}_index_contor_el9999999")
    assert stare is not None
    assert stare.attributes["unit_of_measurement"] == "kWh"


async def test_toate_entitatile_au_atribuire(hass, pornit):
    stare = hass.states.get(f"{PREFIX_CONT_A}_sold_total")
    assert stare.attributes["attribution"] == "Date furnizate de Nova Power & Gas"


async def test_indexul_de_gaz_are_clasa_potrivita(hass, pornit):
    """Indexul poate intra în tabloul Energie doar cu device_class corect."""
    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567")
    assert stare.attributes["device_class"] == "gas"
    assert stare.attributes["state_class"] == "total_increasing"


async def test_indexul_de_electricitate_are_clasa_energy(hass, date_intrare):
    date_intrare = {**date_intrare, "selected_accounts": [CRM_B]}
    await _porneste(hass, date_intrare)
    stare = hass.states.get(f"{PREFIX_B_ELE}_index_contor_el9999999")
    assert stare.attributes["device_class"] == "energy"


async def test_unitate_neasteptata_ramane_fara_clasa(hass, date_intrare, fixtura):
    """Dacă API-ul întoarce o unitate necunoscută, entitatea nu e respinsă."""
    puncte = fixtura("contA_metering_points")
    puncte["docs"][0]["meters"][0]["unit"] = "unități ciudate"
    await _porneste(hass, date_intrare, suprascrieri={"contA_metering_points": puncte})
    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567")
    assert stare is not None
    assert "device_class" not in stare.attributes


async def test_arhiva_ignora_facturile_din_alt_an(hass, date_intrare, freezer):
    """Aceleași fixturi, alt an: arhiva trebuie să se golească."""
    freezer.move_to("2027-01-15")
    await _porneste(hass, date_intrare)
    assert int(hass.states.get(f"{PREFIX_CONT_A}_arhiva_facturi").state) == 0
    assert int(hass.states.get(f"{PREFIX_CONT_A}_arhiva_plati").state) == 0


async def test_factura_restanta_nu_depinde_de_an(hass, date_intrare, freezer):
    """Restanța e restanță indiferent de anul în care a fost emisă."""
    freezer.move_to("2027-01-15")
    await _porneste(hass, date_intrare)
    assert hass.states.get(f"{PREFIX_CONT_A}_factura_restanta").state == "Da"


async def test_esecul_unui_endpoint_optional_da_unavailable_nu_zero(hass, date_intrare):
    """Dacă `/invoices` cade, arhiva nu are voie să arate 0 — ar fi indistinct
    de „nicio factură anul acesta"."""
    from custom_components.novaenergy.api import NovaApiError

    from .conftest import BUCATI_URL, PREFIX_PER_CONT, incarca

    def _fabrica(session, email, password, timeout=30):
        from unittest.mock import AsyncMock

        client = AsyncMock()
        client.contul = None

        async def _switch(account_id):
            client.contul = account_id
            return {}

        async def _get(url, params=None):
            if "invoices" in url:
                raise NovaApiError("HTTP 500")
            prefix = PREFIX_PER_CONT.get(client.contul, "contA")
            for bucata, nume in BUCATI_URL.items():
                if bucata in url:
                    try:
                        return incarca(f"{prefix}_{nume}")
                    except FileNotFoundError:
                        return {}
            return {}

        async def _get_all(url, params=None):
            from custom_components.novaenergy.helpers import extrage_lista

            return extrage_lista(await _get(url, params))

        client.async_login = AsyncMock(return_value=incarca("login_multicont"))
        client.async_switch_account = AsyncMock(side_effect=_switch)
        client.async_get = AsyncMock(side_effect=_get)
        client.async_get_all = AsyncMock(side_effect=_get_all)
        return client

    intrare = MockConfigEntry(
        domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"]
    )
    intrare.add_to_hass(hass)
    with patch("custom_components.novaenergy.NovaApiClient", side_effect=_fabrica):
        await hass.config_entries.async_setup(intrare.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get(f"{PREFIX_CONT_A}_arhiva_facturi").state == "unavailable"
    assert hass.states.get(f"{PREFIX_CONT_A}_factura_restanta").state == "unavailable"
    # Restul senzorilor, care nu depind de facturi, rămân funcționali.
    assert hass.states.get(f"{PREFIX_CONT_A}_sold_total").state == "223.7"
    assert hass.states.get(f"{PREFIX_GAZ}_date_contract").state == "Activ"


async def test_sume_trimise_ca_text_cu_virgula(hass, date_intrare, freezer):
    """Un backend românesc poate trimite „223,70" în loc de 223.70.

    Fără toleranță, factura ar fi ignorată în tăcere și ai vedea „Nu" la
    factură restantă deși ai de plată.
    """
    freezer.move_to(ZI_DE_REFERINTA)
    from .conftest import incarca

    facturi = incarca("contA_invoices")
    for factura in facturi["docs"]:
        factura["amount"] = str(factura["amount"]).replace(".", ",")
        factura["remainingAmount"] = str(factura["remainingAmount"]).replace(".", ",")

    solduri = incarca("contA_balances")
    solduri["docs"][0]["balance"] = "223,70"

    await _porneste(
        hass,
        date_intrare,
        suprascrieri={"contA_invoices": facturi, "contA_balances": solduri},
    )

    assert hass.states.get(f"{PREFIX_CONT_A}_factura_restanta").state == "Da"
    restanta = hass.states.get(f"{PREFIX_CONT_A}_factura_restanta")
    assert restanta.attributes["Facturi neachitate"] == 2
    assert restanta.attributes["Total restant"] == "223,70 lei"
    assert int(hass.states.get(f"{PREFIX_CONT_A}_arhiva_facturi").state) == 2
    assert float(hass.states.get(f"{PREFIX_CONT_A}_sold_total").state) == 223.70


async def test_doua_contoare_fara_identificatori(hass, date_intrare):
    """Fără serie și fără id, contoarele trebuie deosebite după poziție —
    altfel amândouă ar afișa indexul primului."""
    from .conftest import incarca

    puncte = incarca("contA_metering_points")
    puncte["docs"][0]["meters"] = [
        {"lastIndex": 100, "unit": "m³"},
        {"lastIndex": 200, "unit": "m³"},
    ]
    await _porneste(hass, date_intrare, suprascrieri={"contA_metering_points": puncte})

    indexuri = sorted(
        entitate
        for entitate in hass.states.async_entity_ids("sensor")
        if "index_contor" in entitate
    )
    assert len(indexuri) == 2, "contoarele s-au suprapus într-o singură entitate"
    valori = sorted(float(hass.states.get(e).state) for e in indexuri)
    assert valori == [100.0, 200.0]


async def test_contor_regasit_dupa_serie_cand_ids_se_schimba(hass, date_intrare):
    """Unele API-uri generează id-uri noi la fiecare cerere; seria rămâne."""
    from .conftest import incarca

    puncte = incarca("contA_metering_points")
    del puncte["docs"][0]["meteringPointId"]
    del puncte["docs"][0]["meters"][0]["meterId"]
    await _porneste(hass, date_intrare, suprascrieri={"contA_metering_points": puncte})

    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567")
    assert stare is not None
    assert float(stare.state) == 6030


async def test_unitatea_ascii_e_normalizata(hass, date_intrare):
    """API-ul scrie uneori „m3"; nenormalizată, perechea clasă + unitate e
    invalidă și Home Assistant respinge entitatea."""
    from .conftest import incarca

    puncte = incarca("contA_metering_points")
    puncte["docs"][0]["meters"][0]["unit"] = "m3"
    await _porneste(hass, date_intrare, suprascrieri={"contA_metering_points": puncte})

    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567")
    assert stare is not None
    assert stare.attributes["unit_of_measurement"] == "m³"
    assert stare.attributes["device_class"] == "gas"


async def test_scadenta_cu_formate_de_data_amestecate(hass, date_intrare, freezer):
    """Facturile pot avea scadențe în formate diferite; senzorul trebuie să le
    compare, nu să cadă."""
    freezer.move_to(ZI_DE_REFERINTA)
    from .conftest import incarca

    facturi = incarca("contA_invoices")
    facturi["docs"][0]["dueDate"] = "2026-04-15T00:00:00.000Z"
    facturi["docs"][1]["dueDate"] = "15.03.2026"

    await _porneste(hass, date_intrare, suprascrieri={"contA_invoices": facturi})

    restanta = hass.states.get(f"{PREFIX_CONT_A}_factura_restanta")
    assert restanta.state == "Da"
    assert restanta.attributes["Scadența ultimei facturi"] == "15.04.2026"


async def test_contul_esuat_la_pornire_primeste_entitati_la_revenire(hass, date_intrare):
    """Un cont indisponibil la pornire, printre altele sănătoase, nu are voie să
    rămână definitiv fără entități: integrarea pornește fără el și îl adaugă
    singură când revine."""
    indisponibile = {"id-cont-b"}
    date_intrare = {**date_intrare, "selected_accounts": [CRM_A, CRM_B]}

    intrare = MockConfigEntry(
        domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"]
    )
    intrare.add_to_hass(hass)
    with patch(
        "custom_components.novaenergy.NovaApiClient",
        side_effect=fabrica_client(esueaza_pentru=indisponibile),
    ):
        await hass.config_entries.async_setup(intrare.entry_id)
        await hass.async_block_till_done()

    # Contul sănătos are entități, cel căzut nu are încă.
    assert hass.states.get(f"{PREFIX_GAZ}_date_contract") is not None
    assert hass.states.get(f"{PREFIX_B_GAZ}_date_contract") is None

    indisponibile.clear()
    coordinator = intrare.runtime_data.coordinators[CRM_B]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(f"{PREFIX_B_GAZ}_date_contract") is not None
    assert hass.states.get(f"{PREFIX_CONT_B}_sold_total") is not None


async def test_un_contor_nou_primeste_entitate_fara_repornire(hass, date_intrare):
    """Un contor montat între două actualizări trebuie să apară singur."""
    from .conftest import incarca

    puncte_initiale = incarca("contA_metering_points")
    puncte_initiale["docs"][0]["meters"] = []

    intrare = await _porneste(
        hass, date_intrare, suprascrieri={"contA_metering_points": puncte_initiale}
    )
    assert hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567") is None

    coordinator = next(iter(intrare.runtime_data.coordinators.values()))
    with patch(
        "custom_components.novaenergy.NovaApiClient", side_effect=fabrica_client()
    ):
        coordinator.client = fabrica_client()(None, "a", "b")
        await coordinator.client.async_switch_account("id-cont-a")
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567") is not None


async def test_contract_fara_utilitate_pe_cont_cu_o_singura_utilitate(hass, date_intrare):
    """Dacă există o singură utilitate, un element fără `utilityType` îi aparține."""
    from .conftest import incarca

    contracte = incarca("contA_contracts")
    del contracte["docs"][0]["utilityType"]

    await _porneste(hass, date_intrare, suprascrieri={"contA_contracts": contracte})

    assert hass.states.get(f"{PREFIX_GAZ}_date_contract") is not None


async def test_facturile_nu_se_pierd_pe_cont_cu_doua_utilitati(hass, date_intrare, freezer):
    """Facturile sunt de nivel cont tocmai ca să nu fie aruncate când nu se
    poate spune cărei utilități aparțin."""
    freezer.move_to(ZI_DE_REFERINTA)
    from .conftest import incarca

    facturi = incarca("contA_invoices")
    for factura in facturi["docs"]:
        del factura["utilityType"]  # fără indiciu de utilitate

    date_intrare = {**date_intrare, "selected_accounts": [CRM_B]}
    await _porneste(hass, date_intrare, suprascrieri={"contB_invoices": facturi})

    restanta = hass.states.get(f"{PREFIX_CONT_B}_factura_restanta")
    assert restanta.state == "Da", "facturile au fost pierdute pe contul cu două utilități"
    assert int(hass.states.get(f"{PREFIX_CONT_B}_arhiva_facturi").state) == 2
