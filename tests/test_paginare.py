"""Paginarea: serverul răspunde cu 10 elemente pe pagină, implicit.

Un cont facturat lunar depășește pragul în câteva luni. Trunchierea ar fi
tăcută — pagina scurtă vine cu HTTP 200 — deci senzorii ar raporta încrezători
valori greșite, iar o factură neachitată rămasă pe pagina 2 ar face
„Factură restantă" să spună „Nu".
"""

import re
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aioresponses import CallbackResult, aioresponses
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.novaenergy.api import NovaApiClient
from custom_components.novaenergy.const import DOMAIN, URL_INVOICES, URL_LOGIN

from .conftest import BUCATI_URL, incarca

# Clientul adaugă `limit` și `page` în adresă, deci potrivirea trebuie să
# accepte orice șir de interogare.
FACTURI_ORICE_PAGINA = re.compile(rf"^{re.escape(URL_INVOICES)}(\?.*)?$")


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
    facturi = [{"invoiceId": f"inv-{i}", "amount": 10} for i in range(25)]

    async def raspunde(url, **argumente):
        params = dict(url.query)
        pagina = int(params.get("page", 1))
        per_pagina = int(params.get("limit", 10))
        start = (pagina - 1) * per_pagina
        felie = facturi[start : start + per_pagina]
        return CallbackResult(
            payload=_pagina(felie, pagina, per_pagina, len(facturi))
        )

    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t"}}})
        for _ in range(5):
            mock.get(FACTURI_ORICE_PAGINA, callback=raspunde)

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        toate = await client.async_get_all(URL_INVOICES)

    assert len(toate) == 25, f"s-au citit doar {len(toate)} din 25 de facturi"
    assert [f["invoiceId"] for f in toate] == [f"inv-{i}" for i in range(25)]


async def test_async_get_all_se_opreste_la_o_singura_pagina(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t"}}})
        mock.get(FACTURI_ORICE_PAGINA, payload=_pagina([{"invoiceId": "unu"}], 1, 100, 1))

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        toate = await client.async_get_all(URL_INVOICES)

    assert len(toate) == 1


async def test_async_get_all_tolereaza_raspuns_gol(sesiune):
    """`/invoices` întoarce `{}` când nu există facturi."""
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t"}}})
        mock.get(FACTURI_ORICE_PAGINA, payload={})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        assert await client.async_get_all(URL_INVOICES) == []


async def test_factura_neachitata_de_pe_pagina_a_doua_e_vazuta(hass, date_intrare, freezer):
    """Cazul care doare: datoria e pe pagina 2, iar senzorul ar spune „Nu"."""
    freezer.move_to("2026-09-18")

    facturi = [
        {
            "invoiceId": f"inv-{i}",
            "issueDate": f"{(i % 9) + 1:02d}.01.2026",
            "dueDate": "15.04.2026",
            "amount": 10,
            "remainingAmount": 0,
            "paid": True,
            "utilityType": "gas",
        }
        for i in range(12)
    ]
    # A treisprezecea, neachitată, ajunge pe pagina a doua la 10 pe pagină.
    facturi.append(
        {
            "invoiceId": "inv-restanta",
            "issueDate": "01.09.2026",
            "dueDate": "15.10.2026",
            "amount": 250,
            "remainingAmount": 250,
            "paid": False,
            "utilityType": "gas",
        }
    )

    def _fabrica(session, email, password, timeout=30):
        client = AsyncMock()
        client.contul = None

        async def _switch(account_id):
            client.contul = account_id
            return {}

        async def _get(url, params=None):
            params = params or {}
            for bucata, nume in BUCATI_URL.items():
                if bucata not in url:
                    continue
                if nume == "invoices":
                    per_pagina = min(int(params.get("limit", 10)), 10)  # plafon server
                    pagina = int(params.get("page", 1))
                    start = (pagina - 1) * per_pagina
                    return _pagina(
                        facturi[start : start + per_pagina],
                        pagina,
                        per_pagina,
                        len(facturi),
                    )
                try:
                    return incarca(f"contA_{nume}")
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

    restanta = hass.states.get("sensor.novaenergy_3047398_factura_restanta")
    assert restanta.state == "Da", "factura de pe pagina a doua a fost pierdută"
    assert restanta.attributes["Total restant"] == "250,00 lei"
    assert int(hass.states.get("sensor.novaenergy_3047398_arhiva_facturi").state) == 13
