"""Coordinatorul de actualizare pentru un cont Nova.

Un coordinator deservește un singur cont CRM, dar toate utilitățile lui: un
singur val de cereri aduce datele și pentru gaz, și pentru electricitate.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NovaApiClient, NovaApiError
from .const import (
    DOMAIN,
    URL_APP_INFO,
    URL_BALANCES,
    URL_CONTRACTS,
    URL_INVOICES,
    URL_METERING_POINTS,
    URL_PAYMENTS,
    UTILITY_ELECTRICITY,
    UTILITY_GAS,
)
from .helpers import desfa_invelis, extrage_lista, prima_valoare

_LOGGER = logging.getLogger(__name__)

# Fără aceste date integrarea nu are ce afișa: eșecul lor oprește actualizarea.
ENDPOINTURI_ESENTIALE: dict[str, str] = {
    "balances": URL_BALANCES,
    "contracts": URL_CONTRACTS,
    "metering_points": URL_METERING_POINTS,
}

# Acestea pot lipsi legitim (cont nou, fără plăți, fără facturi).
ENDPOINTURI_OPTIONALE: dict[str, str] = {
    "invoices": URL_INVOICES,
    "payments": URL_PAYMENTS,
    "app_info": URL_APP_INFO,
}

# Cheile care conțin liste, nu obiecte.
CHEI_LISTA = frozenset({"contracts", "metering_points", "invoices", "payments"})

# Soldul vine tot ca listă paginată, dar are întotdeauna un singur element;
# se reduce la un obiect, ca senzorii să nu indexeze o listă.
CHEI_DOC_UNIC = frozenset({"balances"})

UTILITATI_CUNOSCUTE = (UTILITY_GAS, UTILITY_ELECTRICITY)


class NovaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Aduce periodic datele unui cont Nova."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: NovaApiClient,
        account: dict,
        update_interval: timedelta,
    ) -> None:
        self.client = client
        self.account = account
        self._contul_a_fost_comutat = False

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {account.get('crm', '')}",
            update_interval=update_interval,
        )

    @property
    def account_crm(self) -> str:
        """Codul CRM al contului deservit."""
        return str(self.account.get("crm", ""))

    @property
    def account_id(self) -> str:
        """Identificatorul intern al contului."""
        return str(self.account.get("id", ""))

    @property
    def utilities(self) -> list[str]:
        """Utilitățile prezente efectiv pe cont."""
        if not self.data:
            return []
        return list(self.data.get("utilities", []))

    # ──────────────────────────────────────────
    async def _async_update_data(self) -> dict[str, Any]:
        """Aduce toate datele contului într-un singur val de cereri."""
        await self._asigura_contul_curent()

        toate = {**ENDPOINTURI_ESENTIALE, **ENDPOINTURI_OPTIONALE}

        rezultate = await asyncio.gather(
            *(
                self.client.async_get_all(url)
                if nume in CHEI_LISTA or nume in CHEI_DOC_UNIC
                else self.client.async_get(url)
                for nume, url in toate.items()
            ),
            return_exceptions=True,
        )

        date: dict[str, Any] = {"account": self.account}
        esuate: set[str] = set()

        for nume, rezultat in zip(toate, rezultate, strict=True):
            if isinstance(rezultat, Exception):
                if nume in ENDPOINTURI_ESENTIALE:
                    raise UpdateFailed(
                        f"Nu s-au putut obține datele esențiale ({nume}) pentru contul "
                        f"{self.account_crm}: {rezultat}"
                    ) from rezultat
                _LOGGER.warning(
                    "Endpoint-ul opțional %s a eșuat pentru contul %s: %s",
                    nume,
                    self.account_crm,
                    rezultat,
                )
                date[nume] = [] if nume in CHEI_LISTA else {}
                esuate.add(nume)
                continue

            if nume in CHEI_LISTA:
                # `async_get_all` a concatenat deja paginile.
                date[nume] = rezultat if isinstance(rezultat, list) else extrage_lista(rezultat)
            elif nume in CHEI_DOC_UNIC:
                documente = rezultat if isinstance(rezultat, list) else extrage_lista(rezultat)
                date[nume] = documente[0] if documente else {}
            else:
                date[nume] = desfa_invelis(rezultat) or {}

        # Senzorii trebuie să poată deosebi „nu există date" de „nu am reușit
        # să le aduc": altfel un endpoint căzut ar arăta ca un zero adevărat.
        date["endpointuri_esuate"] = frozenset(esuate)
        date["utilities"] = self._deduce_utilitatile(date)
        return date

    async def _asigura_contul_curent(self) -> None:
        """Comută sesiunea pe contul deservit, o singură dată."""
        if self._contul_a_fost_comutat or not self.account_id:
            return
        try:
            await self.client.async_switch_account(self.account_id)
        except NovaApiError as eroare:
            raise UpdateFailed(
                f"Comutarea pe contul {self.account_crm} a eșuat: {eroare}"
            ) from eroare
        self._contul_a_fost_comutat = True

    @staticmethod
    def _deduce_utilitatile(date: dict[str, Any]) -> list[str]:
        """Determină ce utilități există pe cont, din contracte și puncte de măsurare."""
        gasite: set[str] = set()

        for sursa in (date.get("contracts", []), date.get("metering_points", [])):
            for element in sursa:
                utilitate = prima_valoare(element, "utilityType", "utility")
                if isinstance(utilitate, str) and utilitate.lower() in UTILITATI_CUNOSCUTE:
                    gasite.add(utilitate.lower())

        # Ordine stabilă, ca entity_id-urile să nu depindă de ordinea din răspuns.
        return [utilitate for utilitate in UTILITATI_CUNOSCUTE if utilitate in gasite]
