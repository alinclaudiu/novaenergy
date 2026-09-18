"""Utilitare comune pentru teste.

Fixturile vin din două surse:

* `login.json` și `principal_*.json` — răspunsuri **reale**, anonimizate, de la
  un cont care are un singur contract (electricitate), fără contoare, facturi
  sau plăți. Ele fixează *forma* adevărată a API-ului.
* `login_multicont.json`, `contA_*.json`, `contB_*.json` — date **inventate**,
  construite în aceeași formă, pentru cazurile pe care contul real nu le
  acoperă: mai multe conturi, gaz, contoare, facturi, plăți, prosumator.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

RADACINA = Path(__file__).parent.parent
sys.path.insert(0, str(RADACINA))

DIRECTOR_FIXTURI = Path(__file__).parent / "fixtures"

# Conturile din `login_multicont.json`: identificator intern → prefixul fixturilor.
PREFIX_PER_CONT = {
    "id-cont-a": "contA",
    "id-cont-b": "contB",
}
CRM_A = "3047398"  # gaz, cu contor, facturi și plăți
CRM_B = "3008726"  # gaz + electricitate, prosumator pe electricitate


def incarca(nume: str):
    """Încarcă o fixtură după nume, cu sau fără sufixul .json."""
    if not nume.endswith(".json"):
        nume = f"{nume}.json"
    return json.loads((DIRECTOR_FIXTURI / nume).read_text(encoding="utf-8"))


@pytest.fixture
def fixtura():
    """Întoarce funcția de încărcare a fixturilor."""
    return incarca


@pytest.fixture(autouse=True)
def activeaza_integrari_custom(enable_custom_integrations):
    """Permite încărcarea integrării din custom_components în teste."""
    yield


@pytest.fixture
def date_intrare():
    """Datele unui config entry valid."""
    return {
        "username": "ion@exemplu.ro",
        "password": "P@rolaSecreta",
        "update_interval": 21600,
        "selected_accounts": [CRM_A],
    }


# Fragmentul din URL → sufixul fixturii.
BUCATI_URL = {
    "balances": "balances",
    "contracts": "contracts",
    "metering-points": "metering_points",
    "invoices": "invoices",
    "payments": "payments",
    "app-info": "app_info",
    "self-readings": "self_readings",
}


def fabrica_client(esueaza_pentru=None, suprascrieri=None, login="login_multicont"):
    """Fabrică de clienți falși care servesc fixturile.

    `esueaza_pentru` — identificatori de cont pentru care orice cerere eșuează.
    `suprascrieri`   — {nume_fixtura: valoare} pentru a înlocui o fixtură.
    """
    from custom_components.novaenergy.api import NovaApiError

    esueaza_pentru = esueaza_pentru or set()
    suprascrieri = suprascrieri or {}

    def _fabrica(session, email, password, timeout=30):
        client = AsyncMock()
        client.contul = None

        async def _switch(account_id):
            client.contul = account_id
            return {}

        async def _get(url, params=None):
            if client.contul in esueaza_pentru:
                raise NovaApiError("cont indisponibil")
            prefix = PREFIX_PER_CONT.get(client.contul, "contA")
            for bucata, nume in BUCATI_URL.items():
                if bucata in url:
                    cheie = f"{prefix}_{nume}"
                    if cheie in suprascrieri:
                        return suprascrieri[cheie]
                    try:
                        return incarca(cheie)
                    except FileNotFoundError:
                        return {}
            return {}

        async def _get_all(url, params=None):
            from custom_components.novaenergy.helpers import extrage_lista

            return extrage_lista(await _get(url, params))

        client.async_login = AsyncMock(return_value=incarca(login))
        client.async_switch_account = AsyncMock(side_effect=_switch)
        client.async_get = AsyncMock(side_effect=_get)
        client.async_get_all = AsyncMock(side_effect=_get_all)
        return client

    return _fabrica
