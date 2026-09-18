"""Ciclul de viață al integrării: setup, unload, reconfigurare."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.novaenergy import NovaRuntimeData
from custom_components.novaenergy.api import NovaApiError
from custom_components.novaenergy.const import DOMAIN

from .conftest import CRM_A, CRM_B, fabrica_client


async def _configureaza(hass, fixtura, date_intrare, esueaza_pentru=None):
    intrare = MockConfigEntry(domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"])
    intrare.add_to_hass(hass)
    with patch(
        "custom_components.novaenergy.NovaApiClient",
        side_effect=fabrica_client(esueaza_pentru),
    ):
        await hass.config_entries.async_setup(intrare.entry_id)
        await hass.async_block_till_done()
    return intrare


async def test_setup_reuseste(hass, fixtura, date_intrare):
    intrare = await _configureaza(hass, fixtura, date_intrare)
    assert intrare.state is ConfigEntryState.LOADED


async def test_runtime_data_are_tipul_corect(hass, fixtura, date_intrare):
    intrare = await _configureaza(hass, fixtura, date_intrare)
    assert isinstance(intrare.runtime_data, NovaRuntimeData)


async def test_un_coordinator_per_cont_selectat(hass, fixtura, date_intrare):
    date_intrare = {**date_intrare, "selected_accounts": [CRM_A, CRM_B]}
    intrare = await _configureaza(hass, fixtura, date_intrare)
    assert len(intrare.runtime_data.coordinators) == 2
    assert len(intrare.runtime_data.clients) == 2


async def test_fiecare_cont_are_client_propriu(hass, fixtura, date_intrare):
    """Sesiuni separate, ca actualizările să nu își schimbe reciproc contul."""
    date_intrare = {**date_intrare, "selected_accounts": [CRM_A, CRM_B]}
    intrare = await _configureaza(hass, fixtura, date_intrare)
    clienti = list(intrare.runtime_data.clients.values())
    assert clienti[0] is not clienti[1]


async def test_unload(hass, fixtura, date_intrare):
    intrare = await _configureaza(hass, fixtura, date_intrare)
    assert await hass.config_entries.async_unload(intrare.entry_id)
    await hass.async_block_till_done()
    assert intrare.state is ConfigEntryState.NOT_LOADED


async def test_esecul_unui_singur_cont_nu_opreste_integrarea(hass, fixtura, date_intrare):
    date_intrare = {**date_intrare, "selected_accounts": [CRM_A, CRM_B]}
    intrare = await _configureaza(
        hass, fixtura, date_intrare, esueaza_pentru={"id-cont-a"}
    )
    assert intrare.state is ConfigEntryState.LOADED


async def test_esecul_tuturor_conturilor_da_retry(hass, fixtura, date_intrare):
    intrare = MockConfigEntry(domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"])
    intrare.add_to_hass(hass)

    def _fabrica(session, email, password, timeout=30):
        client = AsyncMock()
        client.async_login = AsyncMock(side_effect=NovaApiError("rețea picată"))
        client.async_switch_account = AsyncMock(side_effect=NovaApiError("rețea picată"))
        client.async_get = AsyncMock(side_effect=NovaApiError("rețea picată"))
        return client

    with patch("custom_components.novaenergy.NovaApiClient", side_effect=_fabrica):
        await hass.config_entries.async_setup(intrare.entry_id)
        await hass.async_block_till_done()

    assert intrare.state is ConfigEntryState.SETUP_RETRY


async def test_schimbarea_optiunilor_reincarca(hass, fixtura, date_intrare):
    intrare = await _configureaza(hass, fixtura, date_intrare)
    with patch(
        "custom_components.novaenergy.NovaApiClient", side_effect=fabrica_client()
    ):
        hass.config_entries.async_update_entry(intrare, options={"update_interval": 3600})
        await hass.async_block_till_done()
    assert intrare.state is ConfigEntryState.LOADED


async def test_nu_se_autentifica_de_doua_ori_pentru_un_singur_cont(hass, fixtura, date_intrare):
    """Clientul folosit la descoperirea conturilor e reutilizat, nu aruncat."""
    fabrica = fabrica_client()
    creati = []

    def _numara(*argumente, **cuvinte_cheie):
        client = fabrica(*argumente, **cuvinte_cheie)
        creati.append(client)
        return client

    intrare = MockConfigEntry(domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"])
    intrare.add_to_hass(hass)
    with patch("custom_components.novaenergy.NovaApiClient", side_effect=_numara):
        await hass.config_entries.async_setup(intrare.entry_id)
        await hass.async_block_till_done()

    assert len(creati) == 1, "s-a creat un client în plus față de conturile monitorizate"
