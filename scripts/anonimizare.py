"""Anonimizarea răspunsurilor API înainte ca ele să devină fixturi de test.

Politica este **permite doar ce e cunoscut ca sigur**, nu invers. Un câmp nou,
apărut într-o versiune viitoare a API-ului, este ascuns automat — inversul ar
însemna ca fiecare câmp personal nou să se scurgă până când cineva îl observă.

Valorile numerice, booleene și nule trec întotdeauna: de ele depind testele, și
nu identifică pe nimeni. Pentru șiruri de caractere, trec doar cheile din
`CHEI_SIGURE`, iar restul primesc un surogat stabil **în cadrul unei rulări**
(aceeași valoare dă același surogat, ca legăturile dintre fixturi să rămână
valide), dar imposibil de inversat între rulări.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

# Sare generată la fiecare rulare și **niciodată** salvată. Fără ea, surogatele
# ar fi hash-uri nesărate ale unor valori scurte și previzibile (un număr de
# cont are șapte cifre), deci recuperabile prin forță brută în câteva secunde de
# oricine citește fixturile din repo.
#
# Prețul e că regenerarea fixturilor schimbă toate surogatele. De aceea testele
# nu scriu valori de surogat în cod, ci le citesc din fixturi.
_SARE = secrets.token_hex(16)

# Șiruri de business: enumerări, unități, date calendaristice, stări.
# Nimic de aici nu identifică o persoană.
CHEI_SIGURE: frozenset[str] = frozenset({
    # stări și enumerări
    "status", "success", "state", "role", "type", "utility", "utilityType",
    "clientType", "customerType", "deliveryType", "paid", "currency",
    "unit", "measurementUnit", "readingType", "category", "kind",
    # date calendaristice
    "date", "issueDate", "dueDate", "paymentDate", "createdAt", "updatedAt",
    "signedAt", "effectiveFrom", "effectiveTo", "startDate", "endDate",
    "expiryDate", "revisionDate", "lastReadingDate", "readingDate", "expireAt",
    "periodStart", "periodEnd", "month", "year", "inForceAt",
    # enumerări confirmate în răspunsurile reale
    "contractType", "invoiceDeliveryType", "crmAccountType", "legalEntityType",
    "tipAct", "isNGO", "option", "strategy", "_strategy", "collection",
    "selfReadingIntervalMessage", "selfReadingsEnabled",
})

# Chei numerice care trebuie să treacă chiar dacă API-ul le trimite ca text.
CHEI_NUMERICE: frozenset[str] = frozenset({
    "amount", "totalAmount", "remainingAmount", "amountDue", "value",
    "totalBalance", "prosumerBalance", "balance", "lastIndex", "index",
    "consumption", "consum", "totalDocs", "totalPages", "page", "limit",
    "quantity", "price", "vat",
})

# Chei al căror conținut e secret: nu primesc surogat, ci dispar.
CHEI_SECRETE: frozenset[str] = frozenset({
    "token", "accessToken", "refreshToken", "jwt", "password", "authorization",
    "apiKey", "secret", "signature",
})

EMAIL_SURROGAT = "utilizator@exemplu.test"

# Peste acest prag, un număr fără cheie cunoscută e mai probabil un
# identificator (CNP, telefon, număr de cont) decât o valoare de business.
PRAG_NUMAR_IDENTIFICATOR = 100_000

# Chei surogate la fiecare rulare, ca să poată fi inspectate după.
chei_ascunse: set[str] = set()


def _pare_numar(valoare: str) -> bool:
    try:
        float(valoare.replace(",", "."))
    except ValueError:
        return False
    return True


def _surogat(valoare: Any, cheie: str) -> str:
    """Înlocuitor stabil, care păstrează o urmă a tipului de câmp."""
    amprenta = hashlib.sha256(
        f"{_SARE}:{cheie}:{valoare}".encode("utf-8")
    ).hexdigest()[:8]
    return f"ANONIM-{amprenta}"


def _numar_sigur(cheie: str, valoare: float | int) -> bool:
    """Poate trece acest număr neatins?

    Numerele sunt de obicei valori de business — sume, indexuri, contoare — dar
    un CNP sau un telefon trimis ca număr ar scăpa neobservat. Cele cu cheie
    cunoscută trec întotdeauna; restul doar dacă sunt mici.
    """
    if isinstance(valoare, bool):
        return True
    if cheie in CHEI_NUMERICE or cheie in CHEI_SIGURE:
        return True
    return abs(valoare) < PRAG_NUMAR_IDENTIFICATOR


def _valoare_simpla(cheie: str, valoare: Any) -> Any:
    """Decide soarta unei valori care nu e dicționar sau listă."""
    if valoare is None:
        return None

    if isinstance(valoare, (bool, int, float)):
        if _numar_sigur(cheie, valoare):
            return valoare
        chei_ascunse.add(cheie)
        return _surogat(valoare, cheie)

    if isinstance(valoare, str):
        if not valoare.strip():
            # Un șir gol nu identifică pe nimeni, dar faptul că e gol e o
            # informație de business (câmp necompletat) care trebuie păstrată.
            return valoare
        if "@" in valoare:
            chei_ascunse.add(cheie)
            return EMAIL_SURROGAT
        if cheie in CHEI_SIGURE:
            return valoare
        if cheie in CHEI_NUMERICE and _pare_numar(valoare):
            return valoare
        chei_ascunse.add(cheie)
        return _surogat(valoare, cheie)

    return _surogat(valoare, cheie)


def anonimizeaza(date: Any, cheie_parinte: str = "") -> Any:
    """Întoarce o copie a datelor, cu tot ce nu e sigur înlocuit.

    Originalul nu este modificat.
    """
    if isinstance(date, list):
        # Elementele simple dintr-o listă moștenesc politica cheii care o
        # conține: o listă de telefoane sub cheia `phones` nu are cheie proprie
        # pentru fiecare element, dar rămâne o listă de date personale.
        return [
            anonimizeaza(element, cheie_parinte)
            if isinstance(element, (dict, list))
            else _valoare_simpla(cheie_parinte, element)
            for element in date
        ]

    if not isinstance(date, dict):
        return date

    rezultat: dict[str, Any] = {}
    for cheie, valoare in date.items():
        if cheie in CHEI_SECRETE:
            rezultat[cheie] = "REDACTAT"
        elif isinstance(valoare, (dict, list)):
            rezultat[cheie] = anonimizeaza(valoare, cheie)
        else:
            rezultat[cheie] = _valoare_simpla(cheie, valoare)

    return rezultat


def contine_text(date: Any, text: str) -> bool:
    """Verifică dacă un text apare oriunde în structură. Plasă de siguranță."""
    if not text:
        return False
    return text.casefold() in str(date).casefold()
