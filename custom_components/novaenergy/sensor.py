"""Senzorii integrării Nova Energy România.

Senzorii cu valoare simplă sunt descriși declarativ (`SENZORI_SIMPLI`), ca să nu
existe patru clase aproape identice. Cei care calculează atribute bogate —
arhivele, contractul, indexul contorului — au clase proprii, unde logica se
citește mai ușor decât într-un lambda.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    ATTRIBUTION,
    DOMAIN,
    PRODUCATOR,
    UTILITY_ELECTRICITY,
    UTILITY_GAS,
    UTILITY_LABELS_RO,
    VALOARE_NECUNOSCUTA,
)
from .coordinator import NovaCoordinator
from .helpers import (
    ca_numar,
    format_date_ro,
    format_number_ro,
    format_ron,
    parse_api_date,
    prima_valoare,
    utility_slug,
)

_LOGGER = logging.getLogger(__name__)

# Sufixele tuturor entităților create de integrare. Sursa unică de adevăr:
# testul documentației verifică față de această listă că fiecare senzor apare
# în README.
CHEI_ENTITATI: tuple[str, ...] = (
    "sold_total",
    "sold_prosumator",
    "factura_restanta",
    "arhiva_facturi",
    "arhiva_plati",
    "date_contract",
    "index_contor",
)

UNITATE_IMPLICITA = {UTILITY_GAS: "m³"}
UNITATE_ELECTRICITATE = "kWh"

# Indexul contorului poate alimenta tabloul Energie, dar numai dacă unitatea
# raportată de API este una pe care Home Assistant o acceptă pentru clasa
# respectivă. Dacă furnizorul întoarce altceva, senzorul rămâne fără clasă —
# mai bine fără integrare în tabloul Energie decât respins de Home Assistant.
CLASA_INDEX: dict[tuple[str, str], SensorDeviceClass] = {
    (UTILITY_GAS, "m³"): SensorDeviceClass.GAS,
    (UTILITY_ELECTRICITY, "kWh"): SensorDeviceClass.ENERGY,
    (UTILITY_ELECTRICITY, "Wh"): SensorDeviceClass.ENERGY,
}

# Home Assistant acceptă doar anumite unități pentru fiecare clasă de senzor.
# API-ul scrie uneori „m3" în loc de „m³"; nenormalizată, perechea
# clasă + unitate devine invalidă și entitatea e respinsă la înregistrare.
UNITATI_ECHIVALENTE = {
    "m3": "m³",
    "mc": "m³",
    "smc": "m³",
    "nmc": "m³",
    "kwh": "kWh",
    "wh": "Wh",
    "mwh": "MWh",
}


def normalizeaza_unitatea(bruta: Any) -> str | None:
    """Aduce unitatea la scrierea pe care o așteaptă Home Assistant."""
    if bruta is None:
        return None
    text = str(bruta).strip()
    if not text:
        return None
    return UNITATI_ECHIVALENTE.get(text.casefold(), text)


# ──────────────────────────────────────────────
# Filtrarea datelor pe utilitate
# ──────────────────────────────────────────────
def pentru_utilitate(elemente: list[dict], utilitate: str, utilitati: list[str]) -> list[dict]:
    """Păstrează elementele care aparțin utilității cerute.

    Elementele fără câmp de utilitate se atribuie contului doar dacă acesta are
    o singură utilitate — altfel nu se poate ști unde aparțin.
    """
    rezultat: list[dict] = []
    for element in elemente:
        # Atenție: pe contracte, `type` înseamnă tipul de client („Casnic"),
        # nu utilitatea — de aceea nu e consultat aici.
        proprie = prima_valoare(element, "utilityType", "utility")
        if isinstance(proprie, str):
            if proprie.lower() == utilitate:
                rezultat.append(element)
        elif len(utilitati) == 1:
            rezultat.append(element)
        else:
            _LOGGER.debug(
                "Element fără utilitate pe un cont cu %d utilități; nu poate fi "
                "atribuit și a fost ignorat: %s",
                len(utilitati),
                sorted(element)[:5],
            )
    return rezultat


def _facturi_neachitate(facturi: list[dict]) -> list[dict]:
    neachitate: list[dict] = []
    for factura in facturi:
        if factura.get("paid") is True:
            continue
        rest = ca_numar(
            prima_valoare(factura, "remainingAmount", "amountDue", "amount", implicit=0)
        )
        if rest is not None and rest > 0:
            neachitate.append(factura)
    return neachitate


def _suma(elemente: list[dict], *chei: str) -> float:
    total = 0.0
    for element in elemente:
        valoare = ca_numar(prima_valoare(element, *chei, implicit=0))
        if valoare is not None:
            total += valoare
    return round(total, 2)


def _din_anul_curent(elemente: list[dict], *chei_data: str) -> list[dict]:
    anul = datetime.now().year
    rezultat: list[dict] = []
    for element in elemente:
        data = parse_api_date(prima_valoare(element, *chei_data))
        if data is not None and data.year == anul:
            rezultat.append(element)
    return rezultat


# ──────────────────────────────────────────────
# Descrieri pentru senzorii simpli
# ──────────────────────────────────────────────
@dataclass(frozen=True, kw_only=True)
class NovaSensorDescription(SensorEntityDescription):
    """Descrierea unui senzor cu valoare simplă."""

    nume_ro: str
    value_fn: Callable[[dict, str], Any]
    attrs_fn: Callable[[dict, str], dict[str, Any]] | None = None
    exists_fn: Callable[[dict, str], bool] = lambda date, utilitate: True
    # Endpoint-ul de care depinde valoarea; dacă a eșuat, senzorul devine
    # indisponibil în loc să raporteze o valoare falsă.
    endpoint: str | None = None


def _sold_total(date: dict, utilitate: str | None) -> Any:
    return ca_numar(
        prima_valoare(date.get("balances"), "balance", "totalBalance", "total")
    )


def _sold_prosumator(date: dict, utilitate: str | None) -> Any:
    return ca_numar(
        prima_valoare(date.get("balances"), "prosumerBalance", "prosumBalance")
    )


def _are_contract_de_prosumator(date: dict, utilitate: str | None) -> bool:
    """Contul are vreun contract de prosumator?

    Soldul de prosumator vine ca `0` și pentru cine nu e prosumator, deci nu
    poate fi folosit ca semnal. Semnalul adevărat e contractul de prosumator
    completat pe contract.
    """
    contracte = (
        date.get("contracts", [])
        if utilitate is None
        else pentru_utilitate(date.get("contracts", []), utilitate, date.get("utilities", []))
    )
    for contract in contracte:
        for cheie in ("prosumerContract", "prosumerCertificate"):
            valoare = contract.get(cheie)
            if isinstance(valoare, str) and valoare.strip():
                return True
    return False


def _facturi_cont(date: dict) -> list[dict]:
    """Toate facturile contului.

    Facturile și plățile sunt tratate la nivel de cont, nu de utilitate. Pe
    contul pe care am putut verifica, `/invoices` nu a returnat niciun exemplar,
    deci nu știm dacă ele poartă `utilityType`. Dacă nu îl poartă, o filtrare pe
    utilitate le-ar arunca pe toate de pe un cont cu gaz și electricitate — iar
    „Factură restantă" ar raporta liniștit „Nu" în timp ce există datorie.
    Totalurile pe cont sunt corecte în ambele cazuri; se pierde doar defalcarea.
    """
    return date.get("invoices", [])


def _plati_cont(date: dict) -> list[dict]:
    """Toate plățile contului. Vezi raționamentul de la `_facturi_cont`."""
    return date.get("payments", [])


def _factura_restanta(date: dict, utilitate: str | None) -> str:
    return "Da" if _facturi_neachitate(_facturi_cont(date)) else "Nu"


def _atribute_factura_restanta(date: dict, utilitate: str | None) -> dict[str, Any]:
    neachitate = _facturi_neachitate(_facturi_cont(date))
    if not neachitate:
        return {"Facturi neachitate": 0}

    scadente = [
        data
        for data in (
            parse_api_date(prima_valoare(factura, "dueDate", "paymentDueDate"))
            for factura in neachitate
        )
        if data is not None
    ]

    return {
        "Total restant": format_ron(
            _suma(neachitate, "remainingAmount", "amountDue", "amount")
        ),
        "Facturi neachitate": len(neachitate),
        "Scadența ultimei facturi": (
            max(scadente).strftime("%d.%m.%Y") if scadente else VALOARE_NECUNOSCUTA
        ),
    }


# Soldul vine o singură dată pentru tot contul: /balances nu are utilitate.
SENZORI_DE_CONT: tuple[NovaSensorDescription, ...] = (
    NovaSensorDescription(
        key="sold_total",
        nume_ro="Sold total",
        icon="mdi:cash",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RON",
        state_class=SensorStateClass.TOTAL,
        value_fn=_sold_total,
        endpoint="balances",
    ),
    NovaSensorDescription(
        key="sold_prosumator",
        nume_ro="Sold prosumator",
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RON",
        state_class=SensorStateClass.TOTAL,
        value_fn=_sold_prosumator,
        endpoint="balances",
        # Apare doar unde există contract de prosumator.
        exists_fn=_are_contract_de_prosumator,
    ),
    NovaSensorDescription(
        key="factura_restanta",
        nume_ro="Factură restantă",
        icon="mdi:file-document-alert",
        value_fn=_factura_restanta,
        attrs_fn=_atribute_factura_restanta,
        endpoint="invoices",
    ),
)

# Acestea diferă de la o utilitate la alta.
SENZORI_DE_UTILITATE: tuple[NovaSensorDescription, ...] = ()


# ──────────────────────────────────────────────
# Entitatea de bază
# ──────────────────────────────────────────────
class NovaEntity(CoordinatorEntity[NovaCoordinator], SensorEntity):
    """Baza comună a tuturor senzorilor: device, identificator, atribuire."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: NovaCoordinator,
        utilitate: str | None,
        cheie: str,
        nume: str,
    ) -> None:
        """Construiește entitatea.

        `utilitate` este `None` pentru datele care aparțin contului întreg, nu
        unei anumite utilități — soldul, de pildă, vine o singură dată pentru tot
        contul. Acelea ajung pe un dispozitiv separat, al contului, iar
        dispozitivele de utilitate atârnă de el.
        """
        super().__init__(coordinator)
        self._utilitate = utilitate
        self._cheie = cheie

        crm = coordinator.account_crm

        if utilitate is None:
            self._attr_unique_id = f"{DOMAIN}_{crm}_{cheie}"
            self.entity_id = f"sensor.{DOMAIN}_{slugify(crm)}_{slugify(cheie)}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, crm)},
                name=f"Nova Energy ({crm})",
                manufacturer=PRODUCATOR,
                model="Cont",
                configuration_url="https://nova-energy.ro/",
            )
        else:
            slug_utilitate = utility_slug(utilitate)
            eticheta = UTILITY_LABELS_RO.get(utilitate, utilitate)
            self._attr_unique_id = f"{DOMAIN}_{crm}_{slug_utilitate}_{cheie}"
            self.entity_id = (
                f"sensor.{DOMAIN}_{slugify(crm)}_{slug_utilitate}_{slugify(cheie)}"
            )
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{crm}_{utilitate}")},
                name=f"Nova Energy ({crm}) {eticheta}",
                manufacturer=PRODUCATOR,
                model=eticheta,
                via_device=(DOMAIN, crm),
                configuration_url="https://nova-energy.ro/",
            )

        self._attr_name = nume

    @property
    def _date(self) -> dict:
        return self.coordinator.data or {}

    def _endpoint_a_esuat(self, nume: str) -> bool:
        """A eșuat endpoint-ul din care se hrănește acest senzor?"""
        return nume in self._date.get("endpointuri_esuate", frozenset())


class NovaSenzorSimplu(NovaEntity):
    """Senzor descris declarativ."""

    entity_description: NovaSensorDescription

    def __init__(
        self, coordinator: NovaCoordinator, utilitate: str, descriere: NovaSensorDescription
    ) -> None:
        super().__init__(coordinator, utilitate, descriere.key, descriere.nume_ro)
        self.entity_description = descriere

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._date, self._utilitate)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        endpoint = self.entity_description.endpoint
        if endpoint and self._endpoint_a_esuat(endpoint):
            return False
        # Lipsa datelor înseamnă „indisponibil", niciodată „zero".
        return self.entity_description.value_fn(self._date, self._utilitate) is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self._date, self._utilitate)


# ──────────────────────────────────────────────
# Senzori cu atribute bogate
# ──────────────────────────────────────────────
class ArhivaFacturiSensor(NovaEntity):
    """Facturile emise în anul curent."""

    _attr_icon = "mdi:file-document-multiple-outline"

    def __init__(self, coordinator: NovaCoordinator) -> None:
        super().__init__(coordinator, None, "arhiva_facturi", "Arhivă facturi")

    def _facturi(self) -> list[dict]:
        return _din_anul_curent(
            _facturi_cont(self._date), "issueDate", "date", "createdAt"
        )

    @property
    def native_value(self) -> int:
        return len(self._facturi())

    @property
    def available(self) -> bool:
        # Un „0" ar fi indistinct de „nu am putut aduce facturile".
        return super().available and not self._endpoint_a_esuat("invoices")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        facturi = self._facturi()
        atribute: dict[str, Any] = {}
        for factura in facturi:
            data = format_date_ro(prima_valoare(factura, "issueDate", "date", "createdAt"))
            suma = format_ron(prima_valoare(factura, "amount", "totalAmount"))
            atribute[f"Emisă pe {data}"] = suma
        atribute["Total facturi"] = len(facturi)
        atribute["Total facturat"] = format_ron(_suma(facturi, "amount", "totalAmount"))
        return atribute


class ArhivaPlatiSensor(NovaEntity):
    """Plățile efectuate în anul curent."""

    _attr_icon = "mdi:cash-check"

    def __init__(self, coordinator: NovaCoordinator) -> None:
        super().__init__(coordinator, None, "arhiva_plati", "Arhivă plăți")

    def _plati(self) -> list[dict]:
        return _din_anul_curent(
            _plati_cont(self._date), "paymentDate", "date", "createdAt"
        )

    @property
    def native_value(self) -> int:
        return len(self._plati())

    @property
    def available(self) -> bool:
        return super().available and not self._endpoint_a_esuat("payments")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        plati = self._plati()
        atribute: dict[str, Any] = {}
        for plata in plati:
            data = format_date_ro(prima_valoare(plata, "paymentDate", "date", "createdAt"))
            atribute[f"Plătită pe {data}"] = format_ron(
                prima_valoare(plata, "amount", "value")
            )
        atribute["Total plăți"] = len(plati)
        atribute["Total plătit"] = format_ron(_suma(plati, "amount", "value"))
        return atribute


class DateContractSensor(NovaEntity):
    """Starea și detaliile contractului pentru o utilitate."""

    _attr_icon = "mdi:file-sign"

    def __init__(self, coordinator: NovaCoordinator, utilitate: str) -> None:
        super().__init__(coordinator, utilitate, "date_contract", "Date contract")

    def _contract(self) -> dict | None:
        contracte = pentru_utilitate(
            self._date.get("contracts", []), self._utilitate, self._date.get("utilities", [])
        )
        return contracte[0] if contracte else None

    @property
    def native_value(self) -> str:
        contract = self._contract()
        if contract is None:
            return VALOARE_NECUNOSCUTA
        stare = str(prima_valoare(contract, "status", "state", implicit="")).lower()
        return "Activ" if stare in ("active", "activ", "valid") else "Inactiv"

    @property
    def available(self) -> bool:
        return super().available and self._contract() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        contract = self._contract()
        if contract is None:
            return {}
        return {
            "Contract": prima_valoare(
                contract, "number", "contractNumber", implicit=VALOARE_NECUNOSCUTA
            ),
            "Tip client": prima_valoare(
                contract, "type", "clientType", "customerType", implicit=VALOARE_NECUNOSCUTA
            ),
            "Semnat la": format_date_ro(prima_valoare(contract, "signedAt", "signDate")),
            "Intrat în vigoare": format_date_ro(
                prima_valoare(contract, "inForceAt", "effectiveFrom", "startDate")
            ),
            "Tip livrare": prima_valoare(
                contract, "invoiceDeliveryType", "deliveryType", implicit=VALOARE_NECUNOSCUTA
            ),
        }


class IndexContorSensor(NovaEntity):
    """Indexul unui contor, identificat prin serie."""

    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator: NovaCoordinator,
        utilitate: str,
        punct: dict,
        contor: dict,
        indice_punct: int = 0,
        indice_contor: int = 0,
    ) -> None:
        serie = prima_valoare(contor, "series", "meterSeries")
        self._serie = str(serie) if serie else ""
        self._indice_punct = indice_punct
        self._indice_contor = indice_contor

        # Seria e cheia naturală. Dacă lipsește, poziția ține locul ei — altfel
        # două contoare fără identificatori ar primi aceeași entitate și ar
        # afișa amândouă datele primului.
        sufix = slugify(self._serie) if self._serie else f"{indice_punct}_{indice_contor}"
        nume = f"Index contor {self._serie}" if self._serie else "Index contor"

        super().__init__(coordinator, utilitate, f"index_contor_{sufix}", nume)

        self._id_punct = prima_valoare(punct, "meteringPointId", "id", "_id")
        self._id_contor = prima_valoare(contor, "meterId", "id", "_id")
        unitate = normalizeaza_unitatea(
            prima_valoare(
                contor,
                "unit",
                implicit=UNITATE_IMPLICITA.get(utilitate, UNITATE_ELECTRICITATE),
            )
        )
        self._attr_native_unit_of_measurement = unitate
        self._attr_device_class = CLASA_INDEX.get((utilitate, str(unitate)))

    def _puncte(self) -> list[dict]:
        return pentru_utilitate(
            self._date.get("metering_points", []),
            self._utilitate,
            self._date.get("utilities", []),
        )

    def _contor(self) -> dict | None:
        """Regăsește contorul în datele proaspete.

        Se încearcă, în ordine: identificatorii, seria, poziția. API-ul nu
        garantează niciunul dintre ele, iar o potrivire greșită ar arăta indexul
        altui contor.
        """
        puncte = self._puncte()

        if self._id_punct is not None and self._id_contor is not None:
            for punct in puncte:
                if prima_valoare(punct, "meteringPointId", "id", "_id") != self._id_punct:
                    continue
                for contor in punct.get("meters") or []:
                    if prima_valoare(contor, "meterId", "id", "_id") == self._id_contor:
                        return contor

        if self._serie:
            for punct in puncte:
                for contor in punct.get("meters") or []:
                    serie = prima_valoare(contor, "series", "meterSeries")
                    if serie is not None and str(serie) == self._serie:
                        return contor
            return None

        if self._indice_punct < len(puncte):
            contoare = puncte[self._indice_punct].get("meters") or []
            if self._indice_contor < len(contoare):
                return contoare[self._indice_contor]

        return None

    @property
    def native_value(self) -> Any:
        contor = self._contor()
        if contor is None:
            return None
        return ca_numar(prima_valoare(contor, "lastIndex", "index", "value"))

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        contor = self._contor()
        if contor is None:
            return {}
        return {
            "Serie contor": self._serie or VALOARE_NECUNOSCUTA,
            "Ultima citire": format_date_ro(
                prima_valoare(contor, "lastReadingDate", "readingDate")
            ),
            "Consum": format_number_ro(prima_valoare(contor, "consumption", "consum")),
        }


# ──────────────────────────────────────────────
# Construirea entităților
# ──────────────────────────────────────────────
def construieste_senzori(coordinator: NovaCoordinator) -> list[NovaEntity]:
    """Construiește toate entitățile pentru un cont."""
    date = coordinator.data or {}
    utilitati = date.get("utilities", [])
    entitati: list[NovaEntity] = []

    # ── La nivel de cont ──
    for descriere in SENZORI_DE_CONT:
        if descriere.exists_fn(date, None):
            entitati.append(NovaSenzorSimplu(coordinator, None, descriere))

    entitati.append(ArhivaFacturiSensor(coordinator))
    entitati.append(ArhivaPlatiSensor(coordinator))

    # ── Per utilitate ──
    for utilitate in utilitati:
        for descriere in SENZORI_DE_UTILITATE:
            if descriere.exists_fn(date, utilitate):
                entitati.append(NovaSenzorSimplu(coordinator, utilitate, descriere))

        entitati.append(DateContractSensor(coordinator, utilitate))

        puncte = pentru_utilitate(date.get("metering_points", []), utilitate, utilitati)
        for indice_punct, punct in enumerate(puncte):
            for indice_contor, contor in enumerate(punct.get("meters") or []):
                entitati.append(
                    IndexContorSensor(
                        coordinator, utilitate, punct, contor, indice_punct, indice_contor
                    )
                )

    return entitati


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Creează senzorii și îi completează pe măsură ce apar date noi.

    Entitățile nu se construiesc o singură dată, la pornire: un cont care ratează
    prima actualizare ar rămâne definitiv fără senzori, iar un contor montat
    ulterior nu ar apărea niciodată fără repornirea Home Assistant.
    """
    for coordinator in entry.runtime_data.coordinators.values():
        adaugate: set[str] = set()

        @callback
        def _adauga_entitati_noi(
            coordinator: NovaCoordinator = coordinator,
            adaugate: set[str] = adaugate,
        ) -> None:
            if not coordinator.data:
                return

            noi = [
                entitate
                for entitate in construieste_senzori(coordinator)
                if entitate.unique_id not in adaugate
            ]
            if not noi:
                return

            adaugate.update(entitate.unique_id for entitate in noi)
            _LOGGER.debug(
                "Se adaugă %d entități pentru contul %s",
                len(noi),
                coordinator.account_crm,
            )
            async_add_entities(noi)

        _adauga_entitati_noi()
        entry.async_on_unload(coordinator.async_add_listener(_adauga_entitati_noi))
