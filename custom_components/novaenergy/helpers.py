"""Funcții utilitare pentru integrarea Nova Energy România.

Modulul este intenționat **pur**: nu importă `hass`, nu face apeluri de rețea
și nu ține stare. Tot ce se află aici trebuie să poată fi testat offline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .const import UTILITY_SLUG_RO, VALOARE_NECUNOSCUTA

# Formatele de dată întâlnite în răspunsurile API.
FORMATE_DATA = (
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%d.%m.%Y",
)


# ──────────────────────────────────────────────
# Acces tolerant la câmpuri
# ──────────────────────────────────────────────
def prima_valoare(obiect: dict | None, *chei: str, implicit: Any = None) -> Any:
    """Întoarce valoarea primei chei prezente și nenule.

    API-ul poate denumi același câmp în mai multe feluri de la o versiune la
    alta; funcția evită ca o simplă redenumire să rupă toți senzorii.
    """
    if not isinstance(obiect, dict):
        return implicit
    for cheie in chei:
        valoare = obiect.get(cheie)
        if valoare is not None:
            return valoare
    return implicit


def desfa_invelis(raspuns: Any) -> Any:
    """Scoate conținutul din învelișul `{data, status, success}`.

    Autentificarea și informațiile despre aplicație vin împachetate astfel;
    endpoint-urile de listă răspund direct. Funcția tratează ambele cazuri.
    """
    if (
        isinstance(raspuns, dict)
        and "data" in raspuns
        and ({"status", "success"} & set(raspuns) or len(raspuns) == 1)
    ):
        return raspuns["data"]
    return raspuns


def extrage_lista(raspuns: Any) -> list[dict]:
    """Normalizează un răspuns de listă.

    Backend-ul e Payload CMS, care întoarce `{"docs": [...]}`, dar unele
    endpoint-uri pot întoarce direct o listă.
    """
    raspuns = desfa_invelis(raspuns)
    if isinstance(raspuns, list):
        return [element for element in raspuns if isinstance(element, dict)]
    if isinstance(raspuns, dict):
        for cheie in ("docs", "items", "data", "results"):
            valoare = raspuns.get(cheie)
            if isinstance(valoare, list):
                return [element for element in valoare if isinstance(element, dict)]
    return []


def pagina_urmatoare(raspuns: Any) -> int | None:
    """Numărul paginii următoare, sau None dacă răspunsul e complet.

    `totalDocs` nu e de încredere (poate fi `0` deși `docs` are elemente), deci
    singurul semnal folosit este `hasNextPage` / `nextPage`.
    """
    raspuns = desfa_invelis(raspuns)
    if not isinstance(raspuns, dict):
        return None
    if not raspuns.get("hasNextPage"):
        return None
    urmatoare = raspuns.get("nextPage")
    if isinstance(urmatoare, int):
        return urmatoare
    curenta = raspuns.get("page")
    return curenta + 1 if isinstance(curenta, int) else None


# ──────────────────────────────────────────────
# Formatare românească
# ──────────────────────────────────────────────
def ca_numar(valoare: Any) -> float | None:
    """Convertește la număr, tolerând text cu virgulă zecimală.

    API-ul trimite azi numere adevărate, dar un backend românesc poate oricând
    începe să trimită `"223,70"`. Fără această toleranță, sumele respective ar
    fi ignorate în tăcere — iar o factură restantă ar fi raportată ca achitată.
    """
    if valoare is None or isinstance(valoare, bool):
        return None
    if isinstance(valoare, (int, float)):
        return float(valoare)
    if isinstance(valoare, str):
        curatat = valoare.strip().replace(" ", "")
        if curatat.count(",") == 1 and curatat.count(".") == 0:
            curatat = curatat.replace(",", ".")
        try:
            return float(curatat)
        except ValueError:
            return None
    return None


def format_number_ro(valoare: Any, zecimale: int = 2) -> str:
    """Formatează un număr în convenție românească: `1.234,56`."""
    numar = ca_numar(valoare)
    if numar is None:
        return VALOARE_NECUNOSCUTA
    # Se formatează întâi în stil anglo-saxon, apoi se schimbă simbolurile.
    englez = f"{numar:,.{zecimale}f}"
    return englez.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def format_ron(valoare: Any) -> str:
    """Formatează o sumă în lei: `1.234,56 lei`."""
    formatat = format_number_ro(valoare)
    if formatat == VALOARE_NECUNOSCUTA:
        return VALOARE_NECUNOSCUTA
    return f"{formatat} lei"


def parse_api_date(brut: Any) -> datetime | None:
    """Interpretează o dată venită de la API, indiferent de format.

    Rezultatul e întotdeauna **fără fus orar**. API-ul amestecă formatele — unele
    câmpuri vin ca `28.08.2026`, altele ca `2026-08-28T00:00:00.000Z` — iar un
    amestec de date cu și fără fus orar face `max()` să arunce `TypeError`, ceea
    ce ar scoate din funcțiune senzorul care le compară.
    """
    if not isinstance(brut, str) or not brut.strip():
        return None

    text = brut.strip()
    for format_ in FORMATE_DATA:
        try:
            return datetime.strptime(text, format_).replace(tzinfo=None)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def format_date_ro(brut: Any, format_iesire: str = "%d.%m.%Y") -> str:
    """Formatează o dată în stil românesc: `15.04.2026`."""
    data = parse_api_date(brut)
    if data is None:
        return VALOARE_NECUNOSCUTA
    return data.strftime(format_iesire)


def mask_email(email: Any) -> str:
    """Maschează un email, păstrând prima literă și domeniul."""
    if not isinstance(email, str) or "@" not in email:
        return "***"
    local, _, domeniu = email.partition("@")
    if not local or not domeniu:
        return "***"
    if len(local) <= 1:
        return f"*@{domeniu}"
    return f"{local[0]}{'*' * (len(local) - 1)}@{domeniu}"


def normalize_address(obiect: Any) -> str:
    """Construiește o adresă lizibilă din ce trimite API-ul.

    Adresa vine de obicei ca un singur șir de caractere, dar funcția acceptă și
    forma structurată, ca o schimbare de format să nu rupă afișarea.
    """
    if isinstance(obiect, str):
        return obiect.strip() or VALOARE_NECUNOSCUTA
    if not isinstance(obiect, dict):
        return VALOARE_NECUNOSCUTA

    strada = prima_valoare(obiect, "street", "addressLine", "address")
    numar = prima_valoare(obiect, "streetNumber", "number")
    oras = prima_valoare(obiect, "city", "locality")
    judet = prima_valoare(obiect, "county", "district")

    bucati: list[str] = []
    if strada:
        bucati.append(f"{strada} {numar}".strip() if numar else str(strada))
    if oras:
        bucati.append(str(oras))
    if judet and judet != oras:
        bucati.append(f"jud. {judet}")

    return ", ".join(bucati) if bucati else VALOARE_NECUNOSCUTA


def utility_slug(utilitate: str) -> str:
    """Traduce codul de utilitate al API-ului în sufixul folosit în entity_id."""
    return UTILITY_SLUG_RO.get(utilitate, utilitate)


# ──────────────────────────────────────────────
# Conturi
# ──────────────────────────────────────────────
def _normalizeaza_cont(brut: dict) -> dict | None:
    """Reduce un cont din API la forma folosită intern."""
    if not isinstance(brut, dict):
        return None

    crm = prima_valoare(
        brut, "accountNumber", "crmCode", "crm", "accountCode", "number"
    )
    identificator = prima_valoare(brut, "accountId", "id", "_id")
    if not crm and not identificator:
        return None

    nume = prima_valoare(brut, "accountName", "name", "fullName")
    if not nume:
        nume = " ".join(
            str(parte)
            for parte in (
                prima_valoare(brut, "firstName"),
                prima_valoare(brut, "lastName"),
            )
            if parte
        ).strip()

    return {
        "id": str(identificator) if identificator else str(crm),
        "crm": str(crm) if crm else str(identificator),
        "nume": str(nume) if nume else VALOARE_NECUNOSCUTA,
        "adresa": normalize_address(
            prima_valoare(brut, "address", "deliveryAddress", "addressLine")
        ),
    }


def extract_accounts(payload_login: Any) -> list[dict]:
    """Extrage conturile disponibile din răspunsul de autentificare.

    Contul curent apare și ca `loggedInAccount`, și ca `viewedAccount`, iar
    conturile asociate sunt imbricate în primul. Duplicatele se elimină după
    identificator, păstrând prima apariție — cea mai completă.
    """
    continut = desfa_invelis(payload_login)
    if not isinstance(continut, dict):
        return []

    candidati: list[dict] = []

    # `viewedAccount` e mai bogat (are adresă), deci are prioritate.
    for cheie in ("viewedAccount", "loggedInAccount", "account"):
        valoare = continut.get(cheie)
        if isinstance(valoare, dict):
            candidati.append(valoare)

    surse_asociate = [continut]
    surse_asociate.extend(
        valoare
        for cheie in ("loggedInAccount", "viewedAccount")
        if isinstance(valoare := continut.get(cheie), dict)
    )
    for sursa in surse_asociate:
        for cheie in ("associatedAccounts", "accounts", "linkedAccounts"):
            valoare = sursa.get(cheie)
            if isinstance(valoare, list):
                candidati.extend(
                    element for element in valoare if isinstance(element, dict)
                )

    conturi: list[dict] = []
    vazute: set[str] = set()
    for candidat in candidati:
        cont = _normalizeaza_cont(candidat)
        if cont is None or cont["id"] in vazute:
            continue
        vazute.add(cont["id"])
        conturi.append(cont)

    return _dezambiguizeaza(conturi)


def _dezambiguizeaza(conturi: list[dict]) -> list[dict]:
    """Garantează coduri CRM distincte.

    Codul CRM este numărul de client, nu identificatorul contului: două conturi
    asociate pot să îl împartă. Cum el ajunge în cheia coordinatorului și în
    `entity_id`, un duplicat ar face un cont să dispară în tăcere. Când apare,
    codul primește un sufix scurt, derivat din identificatorul contului.
    """
    aparitii: dict[str, int] = {}
    for cont in conturi:
        aparitii[cont["crm"]] = aparitii.get(cont["crm"], 0) + 1

    for cont in conturi:
        if aparitii[cont["crm"]] > 1:
            sufix = cont["id"][-4:] or "x"
            cont["crm"] = f"{cont['crm']}-{sufix}"

    return conturi


def build_account_options(conturi: list[dict]) -> list[dict]:
    """Construiește opțiunile afișate în pasul de selecție al config flow-ului."""
    optiuni: list[dict] = []
    for cont in conturi:
        adresa = cont.get("adresa") or VALOARE_NECUNOSCUTA
        eticheta = f"{adresa} ➜ {cont['crm']}"
        optiuni.append({"value": cont["crm"], "label": eticheta})
    return optiuni


def resolve_selection(
    selectate: list[str], conturi: list[dict], toate_bifate: bool = False
) -> list[str]:
    """Rezolvă selecția de conturi în lista finală de coduri CRM."""
    disponibile = [cont["crm"] for cont in conturi]
    if toate_bifate:
        return disponibile
    return [crm for crm in selectate if crm in disponibile]
