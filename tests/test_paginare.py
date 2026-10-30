"""Paginarea: `/contracts` răspunde cu 10 elemente pe pagină, implicit.

E singura listă paginată a noului API — facturile, plățile și citirile vin
întregi. Trunchierea ar fi tăcută — pagina scurtă vine cu HTTP 200 — deci un
contract rămas pe pagina 2 ar face să dispară, fără nicio eroare, toți
senzorii utilității lui.
"""

import re
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.novaenergy.api import NovaApiClient
from custom_components.novaenergy.const import DOMAIN, URL_CONTRACTS, URL_LOGIN

from .conftest import BUCATI_URL, incarca

# Clientul adaugă `limit` și `page` în adresă, deci potrivirea trebuie să
# accepte orice șir de interogare.
CONTRACTE_ORICE_PAGINA = re.compile(rf"^{re.escape(URL_CONTRACTS)}(\?.*)?$")


def _pagina(elemente: list[dict], pagina: int, per_pagina: int, total: int) -> dict:
    """Răspuns în forma reală a serverului, inclusiv `totalDocs` nefiabil."""
    ultima = (total + per_pagina - 1) // per_pagina or 1
    return {
        "docs": elemente,
        "hasNextPage": pagina < ultima,
        "hasPrevPage": pagina > 1,
        "limit": per_pagina,
        "nextPage": pagina + 1 if pagina < ultima else None,
        "page": pagina,
        "pagingCounter": (pagina - 1) * per_pagina + 1,
        "prevPage": pagina - 1 if pagina > 1 else None,
        "totalDocs": 0,  # serverul real trimite 0 chiar și când există elemente
        "totalPages": ultima,
    }


@pytest.fixture
async def sesiune():
    async with aiohttp.ClientSession() as ses:
        yield ses


async def test_async_get_all_aduna_toate_paginile(sesiune):
    contracte = [{"contractId": f"ctr-{i}", "status": "Activ"} for i in range(25)]

    async def raspunde(url, **argumente):
        params = dict(url.query)
        pagina = int(params.get("page", 1))
        per_pagina = int(params.get("limit", 10))
        start = (pagina - 1) * per_pagina
        felie = contracte[start : start + per_pagina]
        return CallbackResult(
            payload=_pagina(felie, pagina, per_pagina, len(contracte))
        )

    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t"}}})
        for _ in range(5):
            mock.get(CONTRACTE_ORICE_PAGINA, callback=raspunde)

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        toate = await client.async_get_all(URL_CONTRACTS)

    assert len(toate) == 25, f"s-au citit doar {len(toate)} din 25 de contracte"
    assert [c["contractId"] for c in toate] == [f"ctr-{i}" for i in range(25)]


async def test_async_get_all_se_opreste_la_o_singura_pagina(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t"}}})
        mock.get(CONTRACTE_ORICE_PAGINA, payload=_pagina([{"contractId": "unu"}], 1, 100, 1))

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        toate = await client.async_get_all(URL_CONTRACTS)

    assert len(toate) == 1


async def test_async_get_all_tolereaza_raspuns_gol(sesiune):
    """Un endpoint fără date poate întoarce `{}`."""
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t"}}})
        mock.get(CONTRACTE_ORICE_PAGINA, payload={})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        assert await client.async_get_all(URL_CONTRACTS) == []


async def test_contractul_de_pe_pagina_a_doua_e_vazut(hass, date_intrare):
    """Cazul care doare: contractul de gaz e pe pagina 2, iar fără paginare
    toată utilitatea ar dispărea, fără nicio eroare."""
    electricitate = [
        {"contractId": f"ctr-{i}", "number": f"NV-{i}", "status": "Activ", "type": "Casnic",
         "utilityType": "electricity", "signedAt": "01.06.2023", "inForceAt": "01.07.2023"}
        for i in range(10)
    ]
    # Al unsprezecelea, singurul de gaz, ajunge pe pagina a doua la 10 pe pagină.
    contracte = [*electricitate, {
        "contractId": "ctr-gaz", "number": "NV-GAZ", "status": "Activ", "type": "Casnic",
        "utilityType": "gas", "signedAt": "01.06.2023", "inForceAt": "01.07.2023",
    }]

    def _fabrica(session, email, password, timeout=30):
        client = AsyncMock()

        async def _get(url, params=None):
            params = params or {}
            for bucata, nume in BUCATI_URL.items():
                if bucata not in url:
                    continue
                if nume == "contracts":
                    per_pagina = min(int(params.get("limit", 10)), 10)  # plafon server
                    pagina = int(params.get("page", 1))
                    start = (pagina - 1) * per_pagina
                    return _pagina(
                        contracte[start : start + per_pagina],
                        pagina,
                        per_pagina,
                        len(contracte),
                    )
                try:
                    return incarca(f"contB_{nume}")
                except FileNotFoundError:
                    return {}
            return {}

        async def _get_all(url, params=None):
            from custom_components.novaenergy.helpers import extrage_lista, pagina_urmatoare

            elemente, pagina = [], 1
            while True:
                argumente = dict(params or {})
                argumente.update({"limit": 100, "page": pagina})
                raspuns = await _get(url, argumente)
                elemente.extend(extrage_lista(raspuns))
                urmatoare = pagina_urmatoare(raspuns)
                if urmatoare is None or urmatoare <= pagina:
                    return elemente
                pagina = urmatoare

        client.async_login = AsyncMock(return_value=incarca("login_multicont"))
        client.async_switch_account = AsyncMock(return_value={})
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

    gaz = hass.states.get("sensor.novaenergy_3047398_gaz_date_contract")
    assert gaz is not None, "contractul de pe pagina a doua a fost pierdut"
    assert gaz.attributes["Contract"] == "NV-GAZ"
