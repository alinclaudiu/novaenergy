"""Fluxul de configurare și cel de reconfigurare."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.novaenergy.api import NovaApiError, NovaAuthError
from custom_components.novaenergy.const import DOMAIN

from .conftest import CRM_A, CRM_B, fabrica_client, incarca

CREDENTIALE = {
    "username": "ion@exemplu.ro",
    "password": "P@rolaSecreta",
    "update_interval": 21600,
}


def _client_login(payload=None, eroare=None):
    def _fabrica(session, email, password, timeout=30):
        client = AsyncMock()
        if eroare is not None:
            client.async_login = AsyncMock(side_effect=eroare)
        else:
            client.async_login = AsyncMock(return_value=payload or incarca("login_multicont"))
        return client

    return _fabrica


async def test_formularul_initial(hass):
    rezultat = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert rezultat["type"] is FlowResultType.FORM
    assert rezultat["step_id"] == "user"


async def test_flux_complet(hass):
    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(),
    ):
        rezultat = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALE
        )
        assert rezultat["step_id"] == "accounts"

        rezultat = await hass.config_entries.flow.async_configure(
            rezultat["flow_id"], {"selected_accounts": [CRM_A]}
        )

    assert rezultat["type"] is FlowResultType.CREATE_ENTRY
    assert rezultat["data"]["selected_accounts"] == [CRM_A]
    assert rezultat["title"] == "ion@exemplu.ro"


async def test_selecteaza_toate_conturile(hass):
    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(),
    ):
        rezultat = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALE
        )
        rezultat = await hass.config_entries.flow.async_configure(
            rezultat["flow_id"], {"selected_accounts": [], "select_all": True}
        )

    assert set(rezultat["data"]["selected_accounts"]) == {CRM_A, CRM_B}


async def test_credentiale_gresite(hass):
    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(eroare=NovaAuthError("respins")),
    ):
        rezultat = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALE
        )

    assert rezultat["type"] is FlowResultType.FORM
    assert rezultat["errors"]["base"] == "invalid_auth"


async def test_retea_indisponibila(hass):
    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(eroare=NovaApiError("timeout")),
    ):
        rezultat = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALE
        )

    assert rezultat["errors"]["base"] == "cannot_connect"


async def test_cont_fara_niciun_contract(hass):
    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(payload={"token": "t"}),
    ):
        rezultat = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALE
        )

    assert rezultat["errors"]["base"] == "no_accounts"


async def test_fara_selectie(hass):
    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(),
    ):
        rezultat = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALE
        )
        rezultat = await hass.config_entries.flow.async_configure(
            rezultat["flow_id"], {"selected_accounts": []}
        )

    assert rezultat["type"] is FlowResultType.FORM
    assert rezultat["errors"]["base"] == "no_selection"


async def test_acelasi_cont_de_doua_ori(hass):
    MockConfigEntry(
        domain=DOMAIN, data=CREDENTIALE, unique_id="ion@exemplu.ro"
    ).add_to_hass(hass)

    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(),
    ):
        rezultat = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}, data=CREDENTIALE
        )

    assert rezultat["type"] is FlowResultType.ABORT
    assert rezultat["reason"] == "already_configured"


async def test_emailul_e_normalizat_pentru_unicitate(hass):
    MockConfigEntry(
        domain=DOMAIN, data=CREDENTIALE, unique_id="ion@exemplu.ro"
    ).add_to_hass(hass)

    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(),
    ):
        rezultat = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={**CREDENTIALE, "username": "  ION@exemplu.RO  "},
        )

    assert rezultat["type"] is FlowResultType.ABORT


async def test_options_flow_schimba_intervalul(hass, date_intrare):
    intrare = MockConfigEntry(
        domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"]
    )
    intrare.add_to_hass(hass)

    with patch(
        "custom_components.novaenergy.NovaApiClient", side_effect=fabrica_client()
    ):
        await hass.config_entries.async_setup(intrare.entry_id)
        await hass.async_block_till_done()

    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(),
    ), patch("custom_components.novaenergy.NovaApiClient", side_effect=fabrica_client()):
        rezultat = await hass.config_entries.options.async_init(intrare.entry_id)
        assert rezultat["step_id"] == "init"

        rezultat = await hass.config_entries.options.async_configure(
            rezultat["flow_id"],
            {"selected_accounts": [CRM_A], "update_interval": 3600},
        )
        await hass.async_block_till_done()

    assert rezultat["type"] is FlowResultType.CREATE_ENTRY
    assert intrare.options["update_interval"] == 3600


async def test_reautentificare_cu_parola_noua(hass, date_intrare):
    """La o parolă schimbată, utilizatorul trebuie să o poată actualiza din UI."""
    intrare = MockConfigEntry(
        domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"]
    )
    intrare.add_to_hass(hass)

    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(),
    ), patch("custom_components.novaenergy.NovaApiClient", side_effect=fabrica_client()):
        rezultat = await intrare.start_reauth_flow(hass)
        assert rezultat["step_id"] == "reauth_confirm"

        rezultat = await hass.config_entries.flow.async_configure(
            rezultat["flow_id"], {"password": "ParolaNoua"}
        )
        await hass.async_block_till_done()

    assert rezultat["type"] is FlowResultType.ABORT
    assert rezultat["reason"] == "reauth_successful"
    assert intrare.data["password"] == "ParolaNoua"
    # Emailul rămâne neschimbat: el identifică intrarea.
    assert intrare.data["username"] == date_intrare["username"]


async def test_reautentificare_cu_parola_tot_gresita(hass, date_intrare):
    intrare = MockConfigEntry(
        domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"]
    )
    intrare.add_to_hass(hass)

    with patch(
        "custom_components.novaenergy.config_flow.NovaApiClient",
        side_effect=_client_login(eroare=NovaAuthError("respins")),
    ):
        rezultat = await intrare.start_reauth_flow(hass)
        rezultat = await hass.config_entries.flow.async_configure(
            rezultat["flow_id"], {"password": "TotGresita"}
        )

    assert rezultat["type"] is FlowResultType.FORM
    assert rezultat["errors"]["base"] == "invalid_auth"
    assert intrare.data["password"] == date_intrare["password"]
