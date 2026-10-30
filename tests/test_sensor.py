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
    assert stare.attributes["Cu scadența depășită"] == 1  # doar cea `pastDue`
    assert stare.attributes["Scadența ultimei facturi"] == "15.04.2026"


@pytest.mark.parametrize(
    ("stare_factura", "de_plata", "asteptat"),
    [
        ("unpaid", 50, "Da"),
        ("pastDue", 50, "Da"),
        ("paid", 50, "Nu"),           # achitată, chiar dacă suma n-a fost actualizată
        ("paid", 0, "Nu"),
        ("reversed", 50, "Nu"),       # stornată
        ("inProcessing", 50, "Nu"),   # plata e deja în curs
        ("stare-noua", 50, "Da"),     # necunoscută: decide suma
        ("stare-noua", 0, "Nu"),
    ],
)
async def test_starea_facturii_decide_restanta(
    hass, date_intrare, stare_factura, de_plata, asteptat
):
    """Stările aplicației oficiale: doar `unpaid` și `pastDue` înseamnă datorie."""
    from .conftest import incarca

    facturi = incarca("contA_invoices")
    facturi["data"]["invoices"] = [{
        **facturi["data"]["invoices"][0],
        "status": stare_factura,
        "amountToPay": de_plata,
        "amountRemaining": de_plata,
    }]
    await _porneste(hass, date_intrare, suprascrieri={"contA_invoices": facturi})

    assert hass.states.get(f"{PREFIX_CONT_A}_factura_restanta").state == asteptat


async def test_restul_de_plata_nu_depaseste_factura(hass, date_intrare):
    """Ca în aplicația oficială: restul e plafonat la valoarea facturii."""
    from .conftest import incarca

    facturi = incarca("contA_invoices")
    factura = {**facturi["data"]["invoices"][0], "amountToPay": 999}
    facturi["data"]["invoices"] = [factura]
    await _porneste(hass, date_intrare, suprascrieri={"contA_invoices": facturi})

    restanta = hass.states.get(f"{PREFIX_CONT_A}_factura_restanta")
    assert restanta.attributes["Total restant"] == "125,50 lei"


async def test_platile_fara_suma_nu_apar(hass, date_intrare, freezer):
    """Aplicația oficială ascunde înregistrările cu suma plătită zero."""
    freezer.move_to(ZI_DE_REFERINTA)
    from .conftest import incarca

    plati = incarca("contA_payments")
    plati["data"]["payments"].append(
        {**plati["data"]["payments"][0], "paidValue": 0, "totalAmount": "0.00",
         "date": "2026-03-11", "invoicesIds": "inv-anulata"}
    )
    await _porneste(hass, date_intrare, suprascrieri={"contA_payments": plati})

    stare = hass.states.get(f"{PREFIX_CONT_A}_arhiva_plati")
    assert int(stare.state) == 1
    assert "Plătită pe 11.03.2026" not in stare.attributes


async def test_rest_de_plata_lipsa_inseamna_toata_factura(hass, date_intrare):
    """Ca în aplicația oficială: fără `amountToPay`, de plată e valoarea întreagă."""
    from .conftest import incarca

    facturi = incarca("contA_invoices")
    factura = dict(facturi["data"]["invoices"][0])
    del factura["amountToPay"]
    del factura["amountRemaining"]
    facturi["data"]["invoices"] = [factura]
    await _porneste(hass, date_intrare, suprascrieri={"contA_invoices": facturi})

    restanta = hass.states.get(f"{PREFIX_CONT_A}_factura_restanta")
    assert restanta.state == "Da"
    assert restanta.attributes["Total restant"] == "125,50 lei"


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
    await _porneste(hass, date_intrare, suprascrieri={"contA_balance": {}})
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
    citiri = fixtura("contA_self_readings")
    for citire in citiri["data"]["selfReadings"]:
        citire["unit"] = "unități ciudate"
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})
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
    for factura in facturi["data"]["invoices"]:
        for cheie in ("amountTotal", "amountToPay", "amountRemaining"):
            factura[cheie] = f"{float(factura[cheie]):.2f}".replace(".", ",")

    sold = incarca("contA_balance")
    sold["data"]["total"] = "223,70"

    await _porneste(
        hass,
        date_intrare,
        suprascrieri={"contA_invoices": facturi, "contA_balance": sold},
    )

    assert hass.states.get(f"{PREFIX_CONT_A}_factura_restanta").state == "Da"
    restanta = hass.states.get(f"{PREFIX_CONT_A}_factura_restanta")
    assert restanta.attributes["Facturi neachitate"] == 2
    assert restanta.attributes["Total restant"] == "223,70 lei"
    assert int(hass.states.get(f"{PREFIX_CONT_A}_arhiva_facturi").state) == 2
    assert float(hass.states.get(f"{PREFIX_CONT_A}_sold_total").state) == 223.70


def _citire_gaz(serie, perioada, index, **altele):
    zi, luna, an = perioada.split(".")
    return {
        "meterSeries": serie, "period": perioada, "periodEnd": f"{an}-{luna}-{zi}",
        "newIndex": index, "unit": "m³", "utilityType": "gas", "dialCode": "ZZGN",
        **altele,
    }


async def test_doua_contoare_au_entitati_separate(hass, date_intrare):
    """Două serii pe același cont: fiecare cu indexul ei, nu amândouă cu al
    primului."""
    citiri = {"data": {"selfReadings": [
        _citire_gaz("GS0000001", "01.03.2026", 100),
        _citire_gaz("GS0000002", "01.03.2026", 200),
    ]}}
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})

    assert float(hass.states.get(f"{PREFIX_GAZ}_index_contor_gs0000001").state) == 100
    assert float(hass.states.get(f"{PREFIX_GAZ}_index_contor_gs0000002").state) == 200


@pytest.mark.parametrize("inversat", [False, True])
async def test_indexul_e_ultima_citire_dupa_data(hass, date_intrare, inversat):
    """`/self-readings` e un istoric; ordinea din răspuns nu e garantată, deci
    indexul curent e citirea cu perioada cea mai recentă, nu prima din listă."""
    lista = [
        _citire_gaz("GS1234567", "01.01.2026", 5600, consumption=100),
        _citire_gaz("GS1234567", "01.03.2026", 6030, consumption=145),
        _citire_gaz("GS1234567", "01.02.2026", 5885, consumption=120),
    ]
    if inversat:
        lista.reverse()
    citiri = {"data": {"selfReadings": lista}}
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})

    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567")
    assert float(stare.state) == 6030
    assert stare.attributes["Ultima citire"] == "01.03.2026"
    assert stare.attributes["Consum"] == "145,00"


async def test_citirea_fara_index_nu_ascunde_indexul_cunoscut(hass, date_intrare):
    """O perioadă încă necompletată nu are voie să facă senzorul indisponibil."""
    citiri = {"data": {"selfReadings": [
        _citire_gaz("GS1234567", "01.03.2026", 6030),
        _citire_gaz("GS1234567", "01.04.2026", None),
    ]}}
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})

    assert float(hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567").state) == 6030


async def test_cadranele_zi_si_noapte_sunt_indexuri_separate(hass, date_intrare):
    """La tarif dublu, același contor are două indexuri (zi „EAZ", noapte
    „EAN"); amestecate, senzorul ar sări între ele la fiecare actualizare."""
    def citire(cadran, index):
        return {"meterSeries": "EL5555555", "period": "01.03.2026", "periodEnd": "2026-03-01",
                "newIndex": index, "unit": "kWh", "utilityType": "electricity",
                "dialCode": cadran}

    citiri = {"data": {"selfReadings": [citire("EAZ", 1000), citire("EAN", 400)]}}
    date_intrare = {**date_intrare, "selected_accounts": [CRM_B]}
    await _porneste(hass, date_intrare, suprascrieri={"contB_self_readings": citiri})

    zi = hass.states.get(f"{PREFIX_B_ELE}_index_contor_el5555555_eaz")
    noapte = hass.states.get(f"{PREFIX_B_ELE}_index_contor_el5555555_ean")
    assert float(zi.state) == 1000
    assert float(noapte.state) == 400
    assert zi.attributes["friendly_name"].endswith("(EAZ)")


async def test_cadranul_principal_si_lipsa_lui_sunt_acelasi_index(hass, date_intrare):
    """O citire cu „EA" și una fără cadran, ale aceluiași contor, trebuie să
    dea o singură entitate: două ar avea același `unique_id`, iar Home
    Assistant ar respinge-o pe a doua."""
    def citire(cadran, perioada, index):
        zi, luna, an = perioada.split(".")
        return {"meterSeries": "EL5555555", "period": perioada, "periodEnd": f"{an}-{luna}-{zi}",
                "newIndex": index, "unit": "kWh", "utilityType": "electricity",
                "dialCode": cadran}

    citiri = {"data": {"selfReadings": [
        citire("EA", "01.02.2026", 1000), citire("", "01.03.2026", 1100),
        citire(None, "01.01.2026", 900),
    ]}}
    date_intrare = {**date_intrare, "selected_accounts": [CRM_B]}
    await _porneste(hass, date_intrare, suprascrieri={"contB_self_readings": citiri})

    indexuri = [
        entitate
        for entitate in hass.states.async_entity_ids("sensor")
        if "el5555555" in entitate
    ]
    assert indexuri == [f"{PREFIX_B_ELE}_index_contor_el5555555"]
    assert float(hass.states.get(indexuri[0]).state) == 1100


@pytest.mark.parametrize(
    ("tip", "eticheta"),
    [("Reading", "Citit"), ("Estimation", "Estimat"), ("Self-Reading", "Autocitit"),
     ("Operator Reading", "Citire distribuitor"), ("", "Autocitire"), ("Tip-nou", "Tip-nou")],
)
async def test_tipul_citirii_are_eticheta_aplicatiei(hass, date_intrare, tip, eticheta):
    """Un index estimat trebuie să se poată deosebi de unul citit efectiv."""
    citiri = {"data": {"selfReadings": [
        _citire_gaz("GS1234567", "01.03.2026", 6030, newIndexReadingType=tip),
    ]}}
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})

    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567")
    assert stare.attributes["Tip citire"] == eticheta


async def test_citiri_fara_niciun_identificator(hass, date_intrare):
    """Fără serie, cod de contor sau punct de consum, citirile unei utilități
    sunt tratate ca ale unui singur contor — cu indexul cel mai recent."""
    citiri = {"data": {"selfReadings": [
        {"period": "01.02.2026", "newIndex": 100, "unit": "m³", "utilityType": "gas"},
        {"period": "01.03.2026", "newIndex": 150, "unit": "m³", "utilityType": "gas"},
    ]}}
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})

    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_necunoscut")
    assert float(stare.state) == 150


async def test_unitatea_ascii_e_normalizata(hass, date_intrare):
    """API-ul scrie uneori „m3"; nenormalizată, perechea clasă + unitate e
    invalidă și Home Assistant respinge entitatea."""
    from .conftest import incarca

    citiri = incarca("contA_self_readings")
    for citire in citiri["data"]["selfReadings"]:
        citire["unit"] = "m3"
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})

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
    facturi["data"]["invoices"][0]["dueDate"] = "2026-04-15T00:00:00.000Z"
    facturi["data"]["invoices"][1]["dueDate"] = "15.03.2026"

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
    fara_citiri = {"data": {"enabled": False, "selfReadings": []}}

    intrare = await _porneste(
        hass, date_intrare, suprascrieri={"contA_self_readings": fara_citiri}
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
    for factura in facturi["data"]["invoices"]:
        del factura["utilityType"]  # fără indiciu de utilitate

    date_intrare = {**date_intrare, "selected_accounts": [CRM_B]}
    await _porneste(hass, date_intrare, suprascrieri={"contB_invoices": facturi})

    restanta = hass.states.get(f"{PREFIX_CONT_B}_factura_restanta")
    assert restanta.state == "Da", "facturile au fost pierdute pe contul cu două utilități"
    assert int(hass.states.get(f"{PREFIX_CONT_B}_arhiva_facturi").state) == 2


# ──────────────────────────────────────────────
# Prosumator
# ──────────────────────────────────────────────
@pytest.mark.parametrize(
    ("sold", "exista"),
    [
        ({"total": 0, "prosumer": 0, "isProsumer": True}, True),    # marcajul decide
        ({"total": 0, "prosumer": 0, "isProsumer": False}, False),
        ({"total": 0, "prosumer": 12.5}, True),                     # fără marcaj, creditul
    ],
)
async def test_marcajul_de_prosumator_decide(hass, date_intrare, sold, exista):
    """Creditul de prosumator poate fi 0 exact la pornire; senzorul trebuie să
    existe totuși pe un cont de prosumator, altfel ar dispărea entitatea."""
    await _porneste(hass, date_intrare, suprascrieri={"contA_balance": {"data": sold}})
    stare = hass.states.get(f"{PREFIX_CONT_A}_sold_prosumator")
    assert (stare is not None) is exista
    if exista:
        assert float(stare.state) == float(sold["prosumer"])


async def test_contractul_de_prosumator_marcheaza_contul(hass, date_intrare):
    """Un act de tip „Contract prosumator" (tipAct 6) e și el un semnal."""
    from .conftest import incarca

    contracte = incarca("contA_contracts")
    contracte["docs"].append({**contracte["docs"][0], "contractId": "ctr-p", "tipAct": 6})
    await _porneste(hass, date_intrare, suprascrieri={"contA_contracts": contracte})
    assert hass.states.get(f"{PREFIX_CONT_A}_sold_prosumator") is not None


# ──────────────────────────────────────────────
# Contract
# ──────────────────────────────────────────────
@pytest.mark.parametrize(
    ("stare_api", "asteptat"),
    [("Activ", "Activ"), ("active", "Activ"), ("", "Activ"), (None, "Activ"),
     ("Inactiv", "Inactiv"), ("Reziliat", "Inactiv")],
)
async def test_starea_contractului(hass, date_intrare, stare_api, asteptat):
    """Ca în aplicația oficială, o stare lipsă sau goală înseamnă activ."""
    from .conftest import incarca

    contracte = incarca("contA_contracts")
    contracte["docs"][0]["status"] = stare_api
    await _porneste(hass, date_intrare, suprascrieri={"contA_contracts": contracte})
    assert hass.states.get(f"{PREFIX_GAZ}_date_contract").state == asteptat


@pytest.mark.parametrize("inversat", [False, True])
async def test_se_arata_contractul_nu_actul_aditional(hass, date_intrare, inversat):
    """`/contracts` întoarce toate actele; senzorul arată contractul propriu-zis
    (tipAct 1), indiferent de ordinea din răspuns."""
    from .conftest import incarca

    contracte = incarca("contA_contracts")
    contract = contracte["docs"][0]
    act = {**contract, "contractId": "ctr-act", "number": "ACT-1", "tipAct": 3,
           "signedAt": "01.03.2026", "inForceAt": "01.04.2026"}
    contracte["docs"] = [act, contract] if not inversat else [contract, act]
    await _porneste(hass, date_intrare, suprascrieri={"contA_contracts": contracte})
    assert hass.states.get(f"{PREFIX_GAZ}_date_contract").attributes["Contract"] == "NV-12345"


async def test_dintre_contracte_se_alege_cel_activ_si_recent(hass, date_intrare):
    from .conftest import incarca

    contracte = incarca("contA_contracts")
    vechi = {**contracte["docs"][0], "number": "NV-VECHI", "status": "Inactiv",
             "inForceAt": "01.02.2020"}
    nou = {**contracte["docs"][0], "number": "NV-NOU", "inForceAt": "01.02.2025"}
    contracte["docs"] = [nou, vechi]
    await _porneste(hass, date_intrare, suprascrieri={"contA_contracts": contracte})
    stare = hass.states.get(f"{PREFIX_GAZ}_date_contract")
    assert stare.state == "Activ"
    assert stare.attributes["Contract"] == "NV-NOU"


# ──────────────────────────────────────────────
# Index: valori lipsă și ambiguități
# ──────────────────────────────────────────────
async def test_indexul_zero_inseamna_lipsa(hass, date_intrare):
    """Ca în aplicația oficială, 0 înseamnă „fără index". Luat drept index,
    Home Assistant l-ar vedea ca o resetare a contorului."""
    citiri = {"data": {"selfReadings": [
        _citire_gaz("GS1234567", "01.02.2026", 6030),
        _citire_gaz("GS1234567", "01.03.2026", 0),
    ]}}
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})
    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567")
    assert float(stare.state) == 6030
    assert stare.attributes["Ultima citire"] == "01.02.2026"


async def test_indexul_zero_trece_la_indexul_de_consum(hass, date_intrare):
    citiri = {"data": {"selfReadings": [
        _citire_gaz("GS1234567", "01.02.2026", 6030),
        _citire_gaz("GS1234567", "01.03.2026", 0, consumptionNewIndex=6100),
    ]}}
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})
    assert float(hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567").state) == 6100


@pytest.mark.parametrize(
    ("citire", "asteptat"),
    [({"oldIndex": 0}, "—"), ({"oldIndex": 0, "consumptionOldIndex": 5900}, "5.900,00"),
     ({"oldIndex": 5885}, "5.885,00")],
)
async def test_indexul_anterior_zero_nu_e_afisat(hass, date_intrare, citire, asteptat):
    citiri = {"data": {"selfReadings": [_citire_gaz("GS1234567", "01.03.2026", 6030, **citire)]}}
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})
    stare = hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567")
    assert stare.attributes["Index anterior"] == asteptat


@pytest.mark.parametrize("unitate", ["", "   ", None])
async def test_unitatea_goala_e_cea_a_utilitatii(hass, date_intrare, unitate):
    """Fără unitate, senzorul ar pierde clasa și ar ieși din tabloul Energie."""
    def citire(utilitate, serie, index):
        return {"meterSeries": serie, "period": "01.03.2026", "periodEnd": "2026-03-01",
                "newIndex": index, "unit": unitate, "utilityType": utilitate}

    citiri = {"data": {"selfReadings": [
        citire("gas", "GS7654321", 1200), citire("electricity", "EL9999999", 45210),
    ]}}
    date_intrare = {**date_intrare, "selected_accounts": [CRM_B]}
    await _porneste(hass, date_intrare, suprascrieri={"contB_self_readings": citiri})

    gaz = hass.states.get(f"{PREFIX_B_GAZ}_index_contor_gs7654321")
    ele = hass.states.get(f"{PREFIX_B_ELE}_index_contor_el9999999")
    assert (gaz.attributes["unit_of_measurement"], gaz.attributes["device_class"]) == ("m³", "gas")
    assert (ele.attributes["unit_of_measurement"], ele.attributes["device_class"]) == ("kWh", "energy")


async def test_seria_goala_trece_la_codul_contorului(hass, date_intrare):
    """API-ul trimite `""` pentru câmpurile goale; două contoare fără serie, dar
    cu coduri diferite, nu au voie să se contopească."""
    citiri = {"data": {"selfReadings": [
        _citire_gaz("", "01.03.2026", 100, meterCode="COD-A"),
        _citire_gaz("", "01.03.2026", 200, meterCode="COD-B"),
    ]}}
    await _porneste(hass, date_intrare, suprascrieri={"contA_self_readings": citiri})
    assert float(hass.states.get(f"{PREFIX_GAZ}_index_contor_cod_a").state) == 100
    assert float(hass.states.get(f"{PREFIX_GAZ}_index_contor_cod_b").state) == 200
    assert hass.states.get(f"{PREFIX_GAZ}_index_contor_necunoscut") is None


@pytest.mark.parametrize("inversat", [False, True])
async def test_doua_citiri_din_aceeasi_perioada(hass, date_intrare, inversat):
    """La aceeași dată câștigă indexul mai mare, oricare ar fi ordinea: valoarea
    nu are voie să sară înapoi de la o actualizare la alta."""
    lista = [
        _citire_gaz("GS1234567", "01.03.2026", 6000, newIndexReadingType="Estimation"),
        _citire_gaz("GS1234567", "01.03.2026", 6030, newIndexReadingType="Reading"),
    ]
    if inversat:
        lista.reverse()
    await _porneste(
        hass, date_intrare, suprascrieri={"contA_self_readings": {"data": {"selfReadings": lista}}}
    )
    assert float(hass.states.get(f"{PREFIX_GAZ}_index_contor_gs1234567").state) == 6030
