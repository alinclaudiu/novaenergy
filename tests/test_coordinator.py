"""Coordinatorul: agregare per cont, fetch paralel, toleranță la endpoint-uri goale."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.novaenergy.api import NovaApiError, NovaCredentialeRespinse
from custom_components.novaenergy.const import (
    URL_BALANCE,
    URL_CONTRACTS,
    URL_INVOICES,
    URL_METERING_POINTS,
    URL_PAYMENTS,
    URL_SELF_READINGS,
)
from custom_components.novaenergy.coordinator import ENDPOINTURI, NovaCoordinator

CONT = {"id": "acc-1", "crm": "9100123456", "nume": "Test", "adresa": "Strada Test 1"}


def _client_fals(fixtura, prefix="principal", erori=None):
    """Client care întoarce fixturi în funcție de URL."""
    erori = erori or {}
    harta = {
        URL_BALANCE: f"{prefix}_balance",
        URL_CONTRACTS: f"{prefix}_contracts",
        URL_INVOICES: f"{prefix}_invoices",
        URL_METERING_POINTS: f"{prefix}_metering_points",
        URL_PAYMENTS: f"{prefix}_payments",
        URL_SELF_READINGS: f"{prefix}_self_readings",
    }

    async def _get(url, params=None):
        if url in erori:
            raise erori[url]
        nume = harta.get(url)
        if nume is None:
            return {}
        try:
            return fixtura(nume)
        except FileNotFoundError:
            return {}

    async def _get_all(url, params=None):
        from custom_components.novaenergy.helpers import extrage_lista

        return extrage_lista(await _get(url, params))

    client = AsyncMock()
    client.async_get = AsyncMock(side_effect=_get)
    client.async_get_all = AsyncMock(side_effect=_get_all)
    client.async_switch_account = AsyncMock(return_value={})
    client.async_login = AsyncMock(return_value={})
    return client


def _coordinator(hass, client):
    return NovaCoordinator(hass, client, CONT, timedelta(hours=6))


async def test_agregarea_populeaza_toate_cheile(hass, fixtura):
    coord = _coordinator(hass, _client_fals(fixtura))
    date = await coord._async_update_data()

    for cheie in (
        "account", "balance", "invoices", "payments", "contracts",
        "metering_points", "self_readings", "utilities",
    ):
        assert cheie in date, f"lipsește cheia {cheie}"


async def test_utilitatile_sunt_deduse_din_date(hass, fixtura):
    """Forma reală: un singur contract, pe electricitate."""
    coord = _coordinator(hass, _client_fals(fixtura))
    date = await coord._async_update_data()
    assert date["utilities"] == ["electricity"]


async def test_cont_cu_ambele_utilitati(hass, fixtura):
    coord = _coordinator(hass, _client_fals(fixtura, prefix="contB"))
    date = await coord._async_update_data()
    assert set(date["utilities"]) == {"gas", "electricity"}


async def test_listele_sunt_normalizate(hass, fixtura):
    """Contractele vin paginate (`docs`), restul sub cheia proprie din `data`;
    coordinatorul dă liste simple în ambele cazuri."""
    coord = _coordinator(hass, _client_fals(fixtura, prefix="contA"))
    date = await coord._async_update_data()
    assert len(date["contracts"]) == 1
    assert len(date["invoices"]) == 3
    assert len(date["payments"]) == 1
    assert len(date["metering_points"]) == 1
    assert len(date["self_readings"]) == 2


async def test_soldul_e_un_obiect(hass, fixtura):
    """`/dashboard/balance` întoarce un singur obiect, învelit în `data`."""
    coord = _coordinator(hass, _client_fals(fixtura, prefix="contA"))
    date = await coord._async_update_data()
    assert date["balance"]["total"] == 223.70
    assert date["balance"]["isProsumer"] is False


async def test_forma_reala_e_citita_complet(hass, fixtura):
    """Pe forma reală a API-ului, fiecare listă își găsește elementele."""
    coord = _coordinator(hass, _client_fals(fixtura))
    date = await coord._async_update_data()
    assert len(date["invoices"]) == 2
    assert len(date["payments"]) == 1
    assert len(date["self_readings"]) == 1
    assert len(date["metering_points"]) == 1
    assert date["balance"]["isProsumer"] is True


@pytest.mark.parametrize("raspuns", [{}, {"data": {}}, {"data": {"invoices": []}}, {"data": []}])
async def test_endpoint_fara_date_da_lista_goala(hass, fixtura, raspuns):
    """Un cont fără facturi poate primi orice formă de „nimic" — nu e o eroare."""
    client = _client_fals(fixtura)
    de_baza = client.async_get.side_effect

    async def _get(url, params=None):
        if url == URL_INVOICES:
            return raspuns
        return await de_baza(url, params)

    client.async_get = AsyncMock(side_effect=_get)
    date = await _coordinator(hass, client)._async_update_data()
    assert date["invoices"] == []


async def test_endpoint_optional_care_esueaza_nu_rupe_actualizarea(hass, fixtura):
    client = _client_fals(fixtura, erori={URL_PAYMENTS: NovaApiError("gol")})
    coord = _coordinator(hass, client)
    date = await coord._async_update_data()
    assert date["payments"] == []
    assert date["endpointuri_esuate"] == frozenset({"payments"})
    assert date["balance"]  # restul datelor au sosit


async def test_endpoint_esential_care_esueaza_da_updatefailed(hass, fixtura):
    client = _client_fals(fixtura, erori={URL_BALANCE: NovaApiError("picat")})
    coord = _coordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()


async def test_fetchul_este_cu_adevarat_concurent(hass, fixtura):
    """Toate endpoint-urile trebuie cerute într-un singur val.

    Verificarea nu numără apelurile — asta ar trece și pe o implementare
    secvențială. Fiecare cerere se blochează la o barieră care se deschide doar
    când au ajuns toate: dacă fetch-ul ar fi serial, prima ar aștepta la
    nesfârșit și testul ar expira.
    """
    import asyncio

    numar_endpointuri = 6
    bariera = asyncio.Barrier(numar_endpointuri)
    de_baza = _client_fals(fixtura)

    async def _get_blocat(url, params=None):
        await bariera.wait()
        return await de_baza.async_get.side_effect(url, params)

    async def _get_all_blocat(url, params=None):
        from custom_components.novaenergy.helpers import extrage_lista

        return extrage_lista(await _get_blocat(url, params))

    client = AsyncMock()
    client.async_get = AsyncMock(side_effect=_get_blocat)
    client.async_get_all = AsyncMock(side_effect=_get_all_blocat)
    client.async_switch_account = AsyncMock(return_value={})

    coord = _coordinator(hass, client)
    date = await asyncio.wait_for(coord._async_update_data(), timeout=5)

    assert date["balance"]
    assert client.async_get.await_count + client.async_get_all.await_count >= numar_endpointuri


async def test_comuta_contul_inainte_de_primul_fetch(hass, fixtura):
    client = _client_fals(fixtura)
    coord = _coordinator(hass, client)
    await coord._async_update_data()
    client.async_switch_account.assert_awaited_once_with("acc-1")


async def test_nu_comuta_din_nou_la_a_doua_actualizare(hass, fixtura):
    client = _client_fals(fixtura)
    coord = _coordinator(hass, client)
    await coord._async_update_data()
    await coord._async_update_data()
    assert client.async_switch_account.await_count == 1


async def test_proprietatile_contului(hass, fixtura):
    coord = _coordinator(hass, _client_fals(fixtura))
    assert coord.account_crm == "9100123456"
    assert coord.account_id == "acc-1"


@pytest.mark.parametrize("nume", list(ENDPOINTURI))
async def test_ce_e_esential_si_ce_e_optional(hass, fixtura, nume):
    """Fără sold și contracte nu se pot construi senzorii; restul poate lipsi,
    iar senzorii care depind de el devin indisponibili."""
    endpoint = ENDPOINTURI[nume]
    client = _client_fals(fixtura, erori={endpoint.url: NovaApiError("picat")})
    coord = _coordinator(hass, client)

    if nume in ("balance", "contracts"):
        assert endpoint.esential
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        return

    assert not endpoint.esential
    date = await coord._async_update_data()
    assert nume in date["endpointuri_esuate"]
    assert date[nume] == []


@pytest.mark.parametrize("url", [ENDPOINTURI["balance"].url, ENDPOINTURI["payments"].url])
async def test_parola_respinsa_cere_reautentificare(hass, fixtura, url):
    """Parola respinsă nu e o problemă de moment: Home Assistant trebuie să
    oprească actualizările și să ceară parola nouă — chiar dacă a apărut pe un
    endpoint opțional."""
    client = _client_fals(fixtura, erori={url: NovaCredentialeRespinse("respinsă")})
    with pytest.raises(ConfigEntryAuthFailed):
        await _coordinator(hass, client)._async_update_data()


async def test_parola_respinsa_la_comutare_cere_reautentificare(hass, fixtura):
    client = _client_fals(fixtura)
    client.async_switch_account = AsyncMock(side_effect=NovaCredentialeRespinse("respinsă"))
    with pytest.raises(ConfigEntryAuthFailed):
        await _coordinator(hass, client)._async_update_data()


async def test_comutarea_esuata_e_reincercata_la_ciclul_urmator(hass, fixtura):
    client = _client_fals(fixtura)
    client.async_switch_account = AsyncMock(side_effect=[NovaApiError("503"), {}])
    coord = _coordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
    await coord._async_update_data()
    assert client.async_switch_account.await_count == 2
