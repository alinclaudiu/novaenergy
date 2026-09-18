"""Coordinatorul: agregare per cont, fetch paralel, toleranță la endpoint-uri goale."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.novaenergy.api import NovaApiError
from custom_components.novaenergy.const import (
    URL_APP_INFO,
    URL_BALANCES,
    URL_CONTRACTS,
    URL_INVOICES,
    URL_METERING_POINTS,
    URL_PAYMENTS,
)
from custom_components.novaenergy.coordinator import NovaCoordinator

CONT = {"id": "acc-1", "crm": "9100123456", "nume": "Test", "adresa": "Strada Test 1"}


def _client_fals(fixtura, prefix="principal", erori=None):
    """Client care întoarce fixturi în funcție de URL."""
    erori = erori or {}
    harta = {
        URL_APP_INFO: f"{prefix}_app_info",
        URL_BALANCES: f"{prefix}_balances",
        URL_CONTRACTS: f"{prefix}_contracts",
        URL_INVOICES: f"{prefix}_invoices",
        URL_METERING_POINTS: f"{prefix}_metering_points",
        URL_PAYMENTS: f"{prefix}_payments",
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
        "account", "app_info", "balances", "invoices",
        "payments", "contracts", "metering_points", "utilities",
    ):
        assert cheie in date, f"lipsește cheia {cheie}"


async def test_utilitatile_sunt_deduse_din_date(hass, fixtura):
    """Contul real are un singur contract, pe electricitate."""
    coord = _coordinator(hass, _client_fals(fixtura))
    date = await coord._async_update_data()
    assert date["utilities"] == ["electricity"]


async def test_cont_cu_ambele_utilitati(hass, fixtura):
    coord = _coordinator(hass, _client_fals(fixtura, prefix="contB"))
    date = await coord._async_update_data()
    assert set(date["utilities"]) == {"gas", "electricity"}


async def test_listele_sunt_normalizate_din_docs(hass, fixtura):
    """API-ul întoarce {'docs': [...]} cu paginare; coordinatorul dă liste simple."""
    coord = _coordinator(hass, _client_fals(fixtura, prefix="contA"))
    date = await coord._async_update_data()
    assert isinstance(date["invoices"], list)
    assert len(date["invoices"]) == 3
    assert isinstance(date["metering_points"], list)


async def test_soldul_e_redus_la_un_obiect(hass, fixtura):
    """`/balances` întoarce tot o listă paginată, dar cu un singur element."""
    coord = _coordinator(hass, _client_fals(fixtura, prefix="contA"))
    date = await coord._async_update_data()
    assert date["balances"] == {"balance": 223.70, "prosumerBalance": 0}


async def test_endpoint_care_intoarce_obiect_gol(hass, fixtura):
    """`/invoices` întoarce `{}` când nu există facturi — nu e o eroare."""
    coord = _coordinator(hass, _client_fals(fixtura))
    date = await coord._async_update_data()
    assert date["invoices"] == []


async def test_endpoint_optional_care_esueaza_nu_rupe_actualizarea(hass, fixtura):
    client = _client_fals(fixtura, erori={URL_PAYMENTS: NovaApiError("gol")})
    coord = _coordinator(hass, client)
    date = await coord._async_update_data()
    assert date["payments"] == []
    assert date["balances"]  # restul datelor au sosit


async def test_endpoint_esential_care_esueaza_da_updatefailed(hass, fixtura):
    client = _client_fals(fixtura, erori={URL_BALANCES: NovaApiError("picat")})
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

    assert date["balances"]
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
