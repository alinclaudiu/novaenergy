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


# Cadranele care nu primesc sufix în `entity_id`: energia activă la tarif unic
# („EA") și gazul („ZZGN") — un contor cu un singur cadran păstrează astfel
# identificatorul din versiunile anterioare, care conținea doar seria. Celelalte
# (zi „EAZ", noapte „EAN") sunt indexuri distincte ale aceluiași contor.
CADRANE_PRINCIPALE = frozenset({"", "ea", "zzgn"})

# Tipurile de citire, cu etichetele din aplicația oficială. Fără tip, aplicația
# afișează „Autocitire".
TIPURI_CITIRE = {
    "self-reading": "Autocitit",
    "reading": "Citit",
    "estimation": "Estimat",
    "invoiced": "Facturat",
    "operator reading": "Citire distribuitor",
    "consumption convention": "Convenție consum",
    "advance agreement": "Acord avansat",
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


# Stările de factură ale aplicației oficiale: `paid`, `unpaid`, `pastDue`
# (restantă), `inProcessing`, `reversed` (anulată). Pe cele achitate, anulate
# sau cu plata în curs nu mai e nimic de plată; o stare necunoscută e tratată,
# ca în aplicație, drept neachitată și se judecă după sumă.
STARI_FARA_DATORIE = frozenset({"paid", "reversed", "inprocessing"})
STARE_RESTANTA = "pastdue"

CHEI_VALOARE_FACTURA = ("amountTotal", "amount", "totalAmount")
CHEI_DE_PLATA = ("amountToPay", "remainingAmount", "amountDue")
CHEI_VALOARE_PLATA = ("paidValue", "totalAmount", "amount", "value")


def _e_surplus_de_prosumator(factura: dict) -> bool:
    """Factura de compensare a energiei injectate („Prosumer Surplus").

    Are valoare negativă: e un credit al clientului, nu o sumă facturată.
    """
    return "prosum" in str(factura.get("balanceType") or "").casefold()


def _rest_de_plata(factura: dict) -> float:
    """Restul de plată al unei facturi, calculat ca în aplicația oficială.

    De plată e `amountToPay` — sau, dacă lipsește, toată valoarea facturii —
    plafonat la valoarea facturii. `amountTotal` vine ca text. Surplusul de
    prosumator, cu valoare negativă, e un credit, nu o datorie.
    """
    total = ca_numar(prima_valoare(factura, *CHEI_VALOARE_FACTURA))
    de_plata = ca_numar(prima_valoare(factura, *CHEI_DE_PLATA))
    if de_plata is None:
        de_plata = total
    if de_plata is None or de_plata <= 0:
        return 0.0
    if total is not None and total < 0 and _e_surplus_de_prosumator(factura):
        return 0.0
    if total is not None and total > 0:
        de_plata = min(de_plata, total)
    return de_plata


def _facturi_neachitate(facturi: list[dict]) -> list[dict]:
    neachitate: list[dict] = []
    for factura in facturi:
        if factura.get("paid") is True:
            continue
        if str(factura.get("status") or "").casefold() in STARI_FARA_DATORIE:
            continue
        if _rest_de_plata(factura) > 0:
            neachitate.append(factura)
    return neachitate


def _cheie_unica(atribute: dict[str, Any], eticheta: str, detaliu: Any) -> str:
    """O etichetă de atribut care nu suprascrie una existentă.

    Două facturi emise în aceeași zi — de pildă furnizarea și surplusul de
    prosumator — ar avea aceeași etichetă, iar a doua ar ascunde-o pe prima.
    """
    if eticheta not in atribute:
        return eticheta
    if detaliu:
        candidat = f"{eticheta} ({detaliu})"
        if candidat not in atribute:
            return candidat
    numar = 2
    while f"{eticheta} ({numar})" in atribute:
        numar += 1
    return f"{eticheta} ({numar})"


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
        prima_valoare(date.get("balance"), "total", "balance", "totalBalance")
    )


def _sold_prosumator(date: dict, utilitate: str | None) -> Any:
    return ca_numar(
        prima_valoare(date.get("balance"), "prosumer", "prosumerBalance")
    )


def _este_prosumator(date: dict, utilitate: str | None) -> bool:
    """Contul este de prosumator?

    Soldul de prosumator vine ca `0` și pentru cine nu e prosumator, deci zero
    nu e un semnal. Semnalul e `isProsumer` din `/dashboard/balance` — nu cel
    din `/invoices`, care a venit `false` pe un cont de prosumator. Un sold de
    prosumator nenul sau un contract de prosumator (tipAct 6 sau 7) sunt la fel
    de concludente.
    """
    sold = date.get("balance")
    if isinstance(sold, dict):
        if sold.get("isProsumer") is True:
            return True
        if ca_numar(prima_valoare(sold, "prosumer", "prosumerBalance")):
            return True

    contracte = (
        date.get("contracts", [])
        if utilitate is None
        else pentru_utilitate(date.get("contracts", []), utilitate, date.get("utilities", []))
    )
    for contract in contracte:
        if _tip_act(contract) in TIPURI_ACT_PROSUMATOR:
            return True
        for cheie in ("prosumerContract", "prosumerCertificate"):
            valoare = contract.get(cheie)
            if isinstance(valoare, str) and valoare.strip():
                return True
    return False


def _facturi_cont(date: dict) -> list[dict]:
    """Toate facturile contului.

    Facturile și plățile sunt tratate la nivel de cont, nu de utilitate. Ele
    poartă `utilityType`, dar o factură fără el, pe un cont cu gaz și
    electricitate, ar fi aruncată de o filtrare pe utilitate — iar „Factură
    restantă" ar raporta liniștit „Nu" în timp ce există datorie. Totalurile pe
    cont sunt corecte oricum; se pierde doar defalcarea.
    """
    return date.get("invoices", [])


def _plati_cont(date: dict) -> list[dict]:
    """Plățile contului. Vezi raționamentul de la `_facturi_cont`.

    Ca în aplicația oficială, înregistrările fără o sumă plătită pozitivă nu
    sunt plăți și nu apar.
    """
    return [
        plata
        for plata in date.get("payments", [])
        if (ca_numar(prima_valoare(plata, *CHEI_VALOARE_PLATA)) or 0) > 0
    ]


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
            round(sum(_rest_de_plata(factura) for factura in neachitate), 2)
        ),
        "Facturi neachitate": len(neachitate),
        # Ca în aplicația oficială, „restantă" e doar starea `pastDue`.
        "Cu scadența depășită": sum(
            1
            for factura in neachitate
            if str(factura.get("status") or "").casefold() == STARE_RESTANTA
        ),
        "Scadența ultimei facturi": (
            max(scadente).strftime("%d.%m.%Y") if scadente else VALOARE_NECUNOSCUTA
        ),
    }


# Soldul e al contului: /dashboard/balance îl defalcă și pe utilități, dar
# senzorii folosesc totalul, ca aceeași sumă să nu apară de două ori.
SENZORI_DE_CONT: tuple[NovaSensorDescription, ...] = (
    NovaSensorDescription(
        key="sold_total",
        nume_ro="Sold total",
        icon="mdi:cash",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RON",
        state_class=SensorStateClass.TOTAL,
        value_fn=_sold_total,
        endpoint="balance",
    ),
    NovaSensorDescription(
        key="sold_prosumator",
        nume_ro="Sold prosumator",
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RON",
        state_class=SensorStateClass.TOTAL,
        value_fn=_sold_prosumator,
        endpoint="balance",
        # Apare doar pe conturile de prosumator.
        exists_fn=_este_prosumator,
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
            suma = format_ron(prima_valoare(factura, *CHEI_VALOARE_FACTURA))
            if _e_surplus_de_prosumator(factura):
                suma = f"{suma} (surplus prosumator)"
            numar = prima_valoare(factura, "invoiceId", "number")
            atribute[_cheie_unica(atribute, f"Emisă pe {data}", numar)] = suma

        # Surplusul de prosumator e un credit, nu o sumă facturată: adunat la
        # rest, ar face „Total facturat" negativ.
        surplus = [factura for factura in facturi if _e_surplus_de_prosumator(factura)]
        furnizare = [factura for factura in facturi if not _e_surplus_de_prosumator(factura)]
        atribute["Total facturi"] = len(facturi)
        atribute["Total facturat"] = format_ron(_suma(furnizare, *CHEI_VALOARE_FACTURA))
        if surplus:
            atribute["Total surplus prosumator"] = format_ron(
                _suma(surplus, *CHEI_VALOARE_FACTURA)
            )
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
            facturi = prima_valoare(plata, "invoicesIds", "paymentId")
            atribute[_cheie_unica(atribute, f"Plătită pe {data}", facturi)] = format_ron(
                prima_valoare(plata, *CHEI_VALOARE_PLATA)
            )
        atribute["Total plăți"] = len(plati)
        atribute["Total plătit"] = format_ron(_suma(plati, *CHEI_VALOARE_PLATA))
        return atribute


# Tipurile de act din aplicația oficială: contract (1), act adițional (3),
# contract de prosumator (6), act adițional de prosumator (7). Fără tip, actul
# e — tot ca în aplicație — contractul.
TIP_ACT_CONTRACT = 1
TIPURI_ACT_PROSUMATOR = frozenset({6, 7})

# Ca în aplicația oficială, o stare lipsă sau goală înseamnă contract activ.
STARI_CONTRACT_ACTIV = frozenset({"active", "activ", "valid", ""})


def _tip_act(contract: dict) -> int:
    tip = ca_numar(contract.get("tipAct"))
    return int(tip) if tip is not None else TIP_ACT_CONTRACT


def _contract_activ(contract: dict) -> bool:
    stare = str(prima_valoare(contract, "status", "state", implicit="")).strip()
    return stare.casefold() in STARI_CONTRACT_ACTIV


def contractul_principal(contracte: list[dict]) -> dict | None:
    """Contractul de furnizare al unei utilități, dintre toate actele ei.

    `/contracts` întoarce toate actele, nu doar contractul: și actele
    adiționale, și contractul de prosumator. Se alege contractul propriu-zis,
    apoi cel activ, apoi cel intrat cel mai recent în vigoare. Fără niciun
    contract propriu-zis, se arată cel mai potrivit dintre celelalte acte.
    """
    def rang(contract: dict) -> tuple:
        in_vigoare = parse_api_date(
            prima_valoare(contract, "inForceAt", "effectiveFrom", "startDate")
        )
        semnat = parse_api_date(prima_valoare(contract, "signedAt", "signDate"))
        return (
            _tip_act(contract) == TIP_ACT_CONTRACT,
            _contract_activ(contract),
            in_vigoare or datetime.min,
            semnat or datetime.min,
        )

    return max(contracte, key=rang) if contracte else None


class DateContractSensor(NovaEntity):
    """Starea și detaliile contractului pentru o utilitate."""

    _attr_icon = "mdi:file-sign"

    def __init__(self, coordinator: NovaCoordinator, utilitate: str) -> None:
        super().__init__(coordinator, utilitate, "date_contract", "Date contract")

    def _contract(self) -> dict | None:
        return contractul_principal(
            pentru_utilitate(
                self._date.get("contracts", []),
                self._utilitate,
                self._date.get("utilities", []),
            )
        )

    @property
    def native_value(self) -> str:
        contract = self._contract()
        if contract is None:
            return VALOARE_NECUNOSCUTA
        return "Activ" if _contract_activ(contract) else "Inactiv"

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


def _nenul(*valori: Any) -> float | None:
    """Prima valoare numerică nenulă: API-ul pune 0 unde nu are un index."""
    for valoare in valori:
        numar = ca_numar(valoare)
        if numar:
            return numar
    return None


def _index_citire(citire: dict) -> float | None:
    """Indexul nou al unei citiri.

    Ca în aplicația oficială, 0 înseamnă „lipsă", iar atunci contează
    `consumptionNewIndex`. Un 0 luat drept index ar fi văzut de Home Assistant
    ca o resetare a contorului, iar următoarea citire ar apărea în statistici
    ca un consum egal cu tot indexul.
    """
    return _nenul(
        prima_valoare(citire, "newIndex", "index", "lastIndex"),
        citire.get("consumptionNewIndex"),
    )


def _index_anterior(citire: dict) -> float | None:
    return _nenul(citire.get("oldIndex"), citire.get("consumptionOldIndex"))


def _primul_text(obiect: dict, *chei: str) -> str:
    """Primul câmp text completat; API-ul trimite `""` pentru câmpurile goale."""
    for cheie in chei:
        valoare = obiect.get(cheie)
        if valoare is not None and str(valoare).strip():
            return str(valoare).strip()
    return ""


def _data_citirii(citire: dict) -> datetime | None:
    return parse_api_date(
        prima_valoare(citire, "periodEnd", "periodStart", "period", "readingDate")
    )


def cheie_contor(citire: dict) -> tuple[str, str]:
    """Identitatea unui index în istoricul de citiri: (serie, cadran).

    Seria e cheia naturală. Cadranul deosebește indexurile aceluiași contor —
    la tarif dublu, ziua și noaptea. Cadranul principal (sau lipsa lui) se
    reduce la `""`: altfel o citire cu „EA" și una fără cadran ale aceluiași
    contor ar da două entități cu același `unique_id`.
    """
    serie = _primul_text(
        citire, "meterSeries", "series", "meterCode", "meteringPointNo", "meteringPointCode"
    )
    cadran = _primul_text(citire, "dialCode", "dial")
    if cadran.casefold() in CADRANE_PRINCIPALE:
        cadran = ""
    return (serie, cadran.upper())


def ultimele_citiri(citiri: list[dict]) -> dict[tuple[str, str], dict]:
    """Cea mai recentă citire a fiecărui index.

    `/self-readings` e un istoric: același contor apare o dată pe perioadă.
    Ordinea din răspuns nu e garantată, deci decide data perioadei; la aceeași
    dată câștigă indexul mai mare, ca valoarea să nu depindă de ordine și să
    nu scadă de la o actualizare la alta. Citirile fără index sunt ignorate, ca
    o perioadă încă necompletată să nu ascundă indexul cunoscut.
    """
    ultimele: dict[tuple[str, str], tuple[tuple[datetime, float], dict]] = {}
    for citire in citiri:
        index = _index_citire(citire)
        if index is None:
            continue
        cheie = cheie_contor(citire)
        ordine = (_data_citirii(citire) or datetime.min, index)
        existenta = ultimele.get(cheie)
        if existenta is None or ordine >= existenta[0]:
            ultimele[cheie] = (ordine, citire)
    return {cheie: citire for cheie, (_, citire) in ultimele.items()}


class IndexContorSensor(NovaEntity):
    """Ultimul index cunoscut al unui contor, din istoricul de citiri."""

    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator: NovaCoordinator,
        utilitate: str,
        cheie: tuple[str, str],
        citire: dict,
    ) -> None:
        self._cheie_contor = cheie
        serie, cadran = cheie

        # Un contor cu cadranul principal păstrează identificatorul din
        # versiunile anterioare, care conținea doar seria.
        sufix = slugify(serie) if serie else "necunoscut"
        nume = f"Index contor {serie}" if serie else "Index contor"
        if cadran:
            sufix = f"{sufix}_{slugify(cadran)}"
            nume = f"{nume} ({cadran})"

        super().__init__(coordinator, utilitate, f"index_contor_{sufix}", nume)

        # O unitate lipsă sau goală înseamnă unitatea obișnuită a utilității;
        # fără ea, senzorul ar pierde clasa și ar ieși din tabloul Energie.
        unitate = normalizeaza_unitatea(citire.get("unit")) or UNITATE_IMPLICITA.get(
            utilitate, UNITATE_ELECTRICITATE
        )
        self._attr_native_unit_of_measurement = unitate
        self._attr_device_class = CLASA_INDEX.get((utilitate, str(unitate)))

    def _citire(self) -> dict | None:
        """Ultima citire a acestui index, din datele proaspete."""
        citiri = pentru_utilitate(
            self._date.get("self_readings", []),
            self._utilitate,
            self._date.get("utilities", []),
        )
        return ultimele_citiri(citiri).get(self._cheie_contor)

    @property
    def native_value(self) -> Any:
        citire = self._citire()
        return None if citire is None else _index_citire(citire)

    @property
    def available(self) -> bool:
        if not super().available or self._endpoint_a_esuat("self_readings"):
            return False
        return self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        citire = self._citire()
        if citire is None:
            return {}
        tip = str(prima_valoare(citire, "newIndexReadingType", "readingType", implicit="")).strip()
        return {
            "Serie contor": self._cheie_contor[0] or VALOARE_NECUNOSCUTA,
            "Ultima citire": format_date_ro(
                prima_valoare(citire, "periodEnd", "period", "periodStart")
            ),
            # Un index estimat se deosebește astfel de unul citit efectiv.
            "Tip citire": TIPURI_CITIRE.get(tip.casefold(), tip) if tip else "Autocitire",
            "Index anterior": format_number_ro(_index_anterior(citire)),
            "Consum": format_number_ro(prima_valoare(citire, "consumption", "consum")),
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

        citiri = pentru_utilitate(date.get("self_readings", []), utilitate, utilitati)
        for cheie, citire in ultimele_citiri(citiri).items():
            entitati.append(IndexContorSensor(coordinator, utilitate, cheie, citire))

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
