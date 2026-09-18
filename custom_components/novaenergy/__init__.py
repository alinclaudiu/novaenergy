"""Integrarea Nova Energy România pentru Home Assistant.

Un config entry corespunde unui cont Nova. Fiecare cont CRM selectat primește
propriul client API și propriul coordinator, ca actualizările să ruleze în
paralel fără să își schimbe reciproc contul vizualizat.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NovaApiClient, NovaApiError, NovaAuthError
from .const import (
    CONF_ACCOUNTS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    PLATFORMS,
)
from .coordinator import NovaCoordinator
from .helpers import extract_accounts

_LOGGER = logging.getLogger(__name__)


@dataclass
class NovaRuntimeData:
    """Obiectele vii ale unui config entry, ținute în `entry.runtime_data`."""

    clients: dict[str, NovaApiClient] = field(default_factory=dict)
    coordinators: dict[str, NovaCoordinator] = field(default_factory=dict)


type NovaConfigEntry = ConfigEntry[NovaRuntimeData]


def _setare(entry: ConfigEntry, cheie: str, implicit=None):
    """Citește o setare din opțiuni, cu revenire la datele intrării."""
    if cheie in entry.options:
        return entry.options[cheie]
    return entry.data.get(cheie, implicit)


async def async_setup_entry(hass: HomeAssistant, entry: NovaConfigEntry) -> bool:
    """Configurează integrarea pentru un cont Nova."""
    sesiune = async_get_clientsession(hass)
    email = entry.data[CONF_USERNAME]
    parola = entry.data[CONF_PASSWORD]

    interval = timedelta(
        seconds=int(_setare(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
    )
    coduri_selectate = list(_setare(entry, CONF_ACCOUNTS, []) or [])

    # ── Descoperirea conturilor ──
    client_descoperire = NovaApiClient(sesiune, email, parola)
    try:
        payload_login = await client_descoperire.async_login()
    except NovaAuthError as eroare:
        raise ConfigEntryAuthFailed(
            f"Autentificarea la Nova a eșuat: {eroare}"
        ) from eroare
    except NovaApiError as eroare:
        raise ConfigEntryNotReady(
            f"Nova nu răspunde în acest moment: {eroare}"
        ) from eroare

    conturi = {cont["crm"]: cont for cont in extract_accounts(payload_login)}
    if not conturi:
        raise ConfigEntryNotReady("Contul Nova nu expune niciun cont de monitorizat")

    # Dacă nu s-a salvat nicio selecție, se monitorizează tot.
    if not coduri_selectate:
        coduri_selectate = list(conturi)

    date_rulare = NovaRuntimeData()

    for crm in coduri_selectate:
        cont = conturi.get(crm)
        if cont is None:
            _LOGGER.warning(
                "Contul %s nu mai există pe acest cont Nova și a fost ignorat", crm
            )
            continue

        # Clientul folosit la descoperire e deja autentificat: îl dăm primului
        # cont, ca să nu mai facem o autentificare în plus la fiecare pornire.
        if client_descoperire is not None:
            client, client_descoperire = client_descoperire, None
        else:
            client = NovaApiClient(sesiune, email, parola)

        date_rulare.clients[crm] = client
        date_rulare.coordinators[crm] = NovaCoordinator(hass, client, cont, interval)

    if not date_rulare.coordinators:
        raise ConfigEntryNotReady(
            "Niciunul dintre conturile selectate nu mai este disponibil"
        )

    # Prima actualizare: conturile se împrospătează în paralel.
    await asyncio.gather(
        *(
            coordinator.async_refresh()
            for coordinator in date_rulare.coordinators.values()
        )
    )

    reusite = [
        crm
        for crm, coordinator in date_rulare.coordinators.items()
        if coordinator.last_update_success
    ]
    if not reusite:
        raise ConfigEntryNotReady(
            "Prima actualizare a eșuat pentru toate conturile selectate"
        )

    esuate = set(date_rulare.coordinators) - set(reusite)
    if esuate:
        _LOGGER.warning(
            "Integrarea pornește fără conturile %s; vor fi reîncercate automat",
            ", ".join(sorted(esuate)),
        )

    entry.runtime_data = date_rulare
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    _LOGGER.info(
        "Nova Energy pornită pentru %d cont(uri): %s",
        len(reusite),
        ", ".join(sorted(reusite)),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NovaConfigEntry) -> bool:
    """Descarcă integrarea."""
    descarcat = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if descarcat:
        entry.runtime_data = NovaRuntimeData()
    return descarcat


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrează intrările vechi. Există o singură versiune deocamdată."""
    _LOGGER.debug("Nimic de migrat pentru versiunea %s", entry.version)
    return True


async def _async_update_options(hass: HomeAssistant, entry: NovaConfigEntry) -> None:
    """Reîncarcă integrarea după modificarea opțiunilor."""
    await hass.config_entries.async_reload(entry.entry_id)
