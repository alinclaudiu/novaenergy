"""Raportul de diagnostic nu are voie să scurgă date personale."""

import json
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.novaenergy.const import DOMAIN
from custom_components.novaenergy.diagnostics import async_get_config_entry_diagnostics

from .conftest import CRM_A, fabrica_client


async def _intrare_configurata(hass, date_intrare):
    intrare = MockConfigEntry(
        domain=DOMAIN, data=date_intrare, unique_id=date_intrare["username"]
    )
    intrare.add_to_hass(hass)
    with patch(
        "custom_components.novaenergy.NovaApiClient", side_effect=fabrica_client()
    ):
        await hass.config_entries.async_setup(intrare.entry_id)
        await hass.async_block_till_done()
    return intrare


async def test_nu_scurge_parola_sau_emailul(hass, date_intrare):
    intrare = await _intrare_configurata(hass, date_intrare)
    raport = await async_get_config_entry_diagnostics(hass, intrare)
    serializat = json.dumps(raport, ensure_ascii=False, default=str)

    assert "P@rolaSecreta" not in serializat
    assert "ion@exemplu.ro" not in serializat
    assert raport["intrare"]["utilizator"] == "i**@exemplu.ro"


async def test_contine_starea_conturilor(hass, date_intrare):
    intrare = await _intrare_configurata(hass, date_intrare)
    raport = await async_get_config_entry_diagnostics(hass, intrare)

    assert CRM_A in raport["conturi"]
    assert raport["conturi"][CRM_A]["ultima_actualizare_reusita"] is True
    assert raport["conturi"][CRM_A]["utilitati"] == ["gas"]


async def test_numara_senzorii_activi(hass, date_intrare):
    intrare = await _intrare_configurata(hass, date_intrare)
    raport = await async_get_config_entry_diagnostics(hass, intrare)

    assert raport["stare"]["senzori_activi"] > 0
    assert all(
        entitate.startswith("sensor.novaenergy_")
        for entitate in raport["stare"]["lista_senzori"]
    )


async def test_raporteaza_endpointurile_esuate(hass, date_intrare):
    """Într-un tichet de suport, asta explică de ce lipsesc senzori."""
    from unittest.mock import AsyncMock

    from custom_components.novaenergy.api import NovaApiError

    from .conftest import BUCATI_URL, PREFIX_PER_CONT, incarca

    def _fabrica(session, email, password, timeout=30):
        client = AsyncMock()
        client.contul = None

        async def _switch(account_id):
            client.contul = account_id
            return {}

        async def _get(url, params=None):
            if "payments" in url:
                raise NovaApiError("timeout")
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

    raport = await async_get_config_entry_diagnostics(hass, intrare)
    assert raport["conturi"][CRM_A]["endpointuri_esuate"] == ["payments"]
    # Raportul trebuie să rămână serializabil ca JSON.
    json.dumps(raport, ensure_ascii=False, default=str)
