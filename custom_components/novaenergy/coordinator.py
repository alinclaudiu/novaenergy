"""Coordinatorul de actualizare pentru un cont Nova.

Un coordinator deservește un singur cont CRM, dar toate utilitățile lui: un
singur val de cereri aduce datele și pentru gaz, și pentru electricitate, iar un
al doilea, contoarele fiecărui loc de consum.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NovaApiClient, NovaApiError, NovaCredentialeRespinse
from .const import (
    DOMAIN,
    URL_BALANCE,
    URL_CONTRACTS,
    URL_INVOICES,
    URL_METERING_POINTS,
    URL_METERS,
    URL_PAYMENTS,
    URL_SELF_READINGS,
    UTILITY_ELECTRICITY,
    UTILITY_GAS,
)
from .helpers import desfa_invelis, extrage_lista, prima_valoare

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Endpoint:
    """Cum se cere un endpoint și unde îi stau datele în răspuns."""

    url: str
    # Lista e sub această cheie, în `data`; `None` înseamnă un singur obiect.
    cheie_lista: str | None = None
    # Paginat ca `{docs, hasNextPage, nextPage}` — se citesc toate paginile.
    paginat: bool = False
    # Fără aceste date integrarea nu are ce afișa: eșecul lor oprește
    # actualizarea. Celelalte pot lipsi legitim (cont nou, fără facturi).
    esential: bool = False

    @property
    def da_lista(self) -> bool:
        """Răspunsul se reduce la o listă, nu la un obiect."""
        return self.paginat or self.cheie_lista is not None


ENDPOINTURI: dict[str, Endpoint] = {
    "balance": Endpoint(URL_BALANCE, esential=True),
    "contracts": Endpoint(URL_CONTRACTS, paginat=True, esential=True),
    "metering_points": Endpoint(URL_METERING_POINTS, cheie_lista="meteringPoints"),
    "invoices": Endpoint(URL_INVOICES, cheie_lista="invoices"),
    "payments": Endpoint(URL_PAYMENTS, cheie_lista="payments"),
    "self_readings": Endpoint(URL_SELF_READINGS, cheie_lista="selfReadings"),
}

UTILITATI_CUNOSCUTE = (UTILITY_GAS, UTILITY_ELECTRICITY)

UNITATI_GAZ = frozenset({"m3", "m³", "mc", "smc", "nmc"})
UNITATI_ELECTRICITATE = frozenset({"kwh", "wh", "mwh", "kvarh", "varh"})


def _utilitatea_contorului(contor: dict) -> str | None:
    """Utilitatea unui contor de pe un loc de consum cu gaz și electricitate.

    Contoarele nu o poartă; se recunoaște după cadran („ZZGN" la gaz, „EA…" la
    electricitate), apoi după unitate. Fără niciun indiciu, rămâne neatribuit
    — mai bine fără senzor decât un contor de gaz pe dispozitivul de curent.
    """
    cadran = str(contor.get("dialCode") or "").strip().casefold()
    if cadran == "zzgn":
        return UTILITY_GAS
    if cadran.startswith("ea"):
        return UTILITY_ELECTRICITY
    unitate = str(contor.get("unit") or "").strip().casefold()
    if unitate in UNITATI_GAZ:
        return UTILITY_GAS
    if unitate in UNITATI_ELECTRICITATE:
        return UTILITY_ELECTRICITY
    return None


def _normalizeaza(endpoint: Endpoint, raspuns: Any) -> Any:
    """Aduce răspunsul la forma folosită de senzori: listă sau obiect."""
    if endpoint.paginat:
        # `async_get_all` a concatenat deja paginile.
        return raspuns if isinstance(raspuns, list) else extrage_lista(raspuns)
    if endpoint.cheie_lista:
        return extrage_lista(raspuns, endpoint.cheie_lista)
    continut = desfa_invelis(raspuns)
    return continut if isinstance(continut, dict) else {}


class NovaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Aduce periodic datele unui cont Nova."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: NovaApiClient,
        account: dict,
        update_interval: timedelta,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        self.client = client
        self.account = account
        self._contul_a_fost_comutat = False

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
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
        """Aduce toate datele contului: un val de cereri în paralel, apoi contoarele."""
        await self._asigura_contul_curent()

        rezultate = await asyncio.gather(
            *(
                self.client.async_get_all(endpoint.url)
                if endpoint.paginat
                else self.client.async_get(endpoint.url)
                for endpoint in ENDPOINTURI.values()
            ),
            return_exceptions=True,
        )

        # Parola respinsă nu se rezolvă reîncercând: Home Assistant trebuie să
        # oprească actualizările și să ceară parola nouă.
        for rezultat in rezultate:
            if isinstance(rezultat, NovaCredentialeRespinse):
                raise ConfigEntryAuthFailed(
                    f"Nova a respins credențialele: {rezultat}"
                ) from rezultat

        date: dict[str, Any] = {"account": self.account}
        esuate: set[str] = set()

        for (nume, endpoint), rezultat in zip(ENDPOINTURI.items(), rezultate, strict=True):
            if isinstance(rezultat, Exception):
                if endpoint.esential:
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
                date[nume] = [] if endpoint.da_lista else {}
                esuate.add(nume)
                continue

            date[nume] = _normalizeaza(endpoint, rezultat)

        # Contoarele se cer pe loc de consum, deci abia după ce se știu locurile.
        if "metering_points" in esuate:
            date["meters"] = []
            esuate.add("meters")
        else:
            date["meters"], contoare_complete = await self._aduce_contoarele(
                date["metering_points"]
            )
            if not contoare_complete:
                esuate.add("meters")

        # Senzorii trebuie să poată deosebi „nu există date" de „nu am reușit
        # să le aduc": altfel un endpoint căzut ar arăta ca un zero adevărat.
        date["endpointuri_esuate"] = frozenset(esuate)
        date["utilities"] = self._deduce_utilitatile(date)
        return date

    async def _aduce_contoarele(self, puncte: list[dict]) -> tuple[list[dict], bool]:
        """Contoarele fiecărui loc de consum, cu ultimul index facturat.

        Ruta se cere o singură dată pe număr de loc de consum, chiar dacă mai
        multe puncte (gaz și electricitate) îl împart. Contoarele nu poartă
        utilitatea: o moștenesc de la loc, dacă acesta are una singură; altfel
        se deduce din contor. Întoarce și dacă toate locurile au răspuns; un loc
        căzut nu le oprește pe celelalte, doar senzorii lui rămân indisponibili.
        """
        utilitati_pe_numar: dict[str, set[str]] = {}
        for punct in puncte:
            numar = prima_valoare(punct, "number")
            if numar is None or not str(numar).strip():
                continue
            utilitate = str(prima_valoare(punct, "utilityType", implicit="")).strip().casefold()
            utilitati_pe_numar.setdefault(str(numar).strip(), set()).add(utilitate)
        numere = list(utilitati_pe_numar)

        rezultate = await asyncio.gather(
            *(
                self.client.async_get(URL_METERS.format(numar=quote(numar, safe="")))
                for numar in numere
            ),
            return_exceptions=True,
        )

        contoare: list[dict] = []
        complete = True
        for pozitie, (numar, rezultat) in enumerate(zip(numere, rezultate, strict=True), start=1):
            if isinstance(rezultat, NovaCredentialeRespinse):
                raise ConfigEntryAuthFailed(
                    f"Nova a respins credențialele: {rezultat}"
                ) from rezultat
            if isinstance(rezultat, Exception):
                # Poziția, nu numărul locului de consum: logurile ajung publice.
                _LOGGER.warning(
                    "Contoarele locului de consum #%d al contului %s nu au putut fi citite: %s",
                    pozitie,
                    self.account_crm,
                    rezultat,
                )
                complete = False
                continue
            utilitati = utilitati_pe_numar[numar] - {""}
            for contor in extrage_lista(rezultat, "meters"):
                contoare.append(
                    {
                        "utilityType": (
                            next(iter(utilitati))
                            if len(utilitati) == 1
                            else _utilitatea_contorului(contor)
                        ),
                        "meterPointNumber": numar,
                        **contor,
                    }
                )
        return contoare, complete

    async def _asigura_contul_curent(self) -> None:
        """Comută sesiunea pe contul deservit, o singură dată."""
        if self._contul_a_fost_comutat or not self.account_id:
            return
        try:
            await self.client.async_switch_account(self.account_id)
        except NovaCredentialeRespinse as eroare:
            raise ConfigEntryAuthFailed(
                f"Nova a respins credențialele: {eroare}"
            ) from eroare
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
