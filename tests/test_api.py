"""Clientul HTTP: autentificare, reînnoirea tokenului, erori, discreție în loguri."""

import logging

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.novaenergy.api import NovaApiClient, NovaApiError, NovaAuthError
from custom_components.novaenergy.const import URL_LOGIN, URL_ME, URL_SWITCH


@pytest.fixture
async def sesiune():
    async with aiohttp.ClientSession() as ses:
        yield ses


async def test_login_stocheaza_tokenul(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "abc123", "loggedInAccount": {}})
        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        assert client.token == "abc123"


async def test_login_accepta_denumiri_alternative_de_token(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"accessToken": "xyz"})
        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        assert client.token == "xyz"


async def test_credentiale_gresite_ridica_autherror(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, status=401)
        client = NovaApiClient(sesiune, "a@b.ro", "gresita")
        with pytest.raises(NovaAuthError):
            await client.async_login()


async def test_raspuns_de_login_fara_token_e_eroare(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"mesaj": "ceva"})
        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        with pytest.raises(NovaAuthError):
            await client.async_login()


async def test_401_declanseaza_relogin_si_o_singura_reincercare(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "vechi"})
        mock.get(URL_ME, status=401)
        mock.post(URL_LOGIN, payload={"token": "nou"})
        mock.get(URL_ME, payload={"crmCode": "1"})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        rezultat = await client.async_get(URL_ME)

        assert rezultat == {"crmCode": "1"}
        assert client.token == "nou"


async def test_401_persistent_nu_reincearca_la_infinit(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_ME, status=401)
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_ME, status=401)

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        with pytest.raises(NovaAuthError):
            await client.async_get(URL_ME)


async def test_eroare_de_retea_devine_novaapierror(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_ME, exception=aiohttp.ClientError("cablu scos"))

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        with pytest.raises(NovaApiError):
            await client.async_get(URL_ME)


async def test_eroare_de_server_devine_novaapierror(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_ME, status=500)

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        with pytest.raises(NovaApiError):
            await client.async_get(URL_ME)


async def test_get_face_login_automat_daca_nu_exista_token(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_ME, payload={"ok": True})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        assert client.token is None
        assert await client.async_get(URL_ME) == {"ok": True}


async def test_switch_account(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.post(URL_SWITCH, payload={"viewedAccount": {"id": "acc-2"}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        rezultat = await client.async_switch_account("acc-2")
        assert rezultat["viewedAccount"]["id"] == "acc-2"


async def test_logul_descrie_forma_nu_continutul(sesiune, caplog):
    """Logurile de depanare sunt lipite în issue-uri publice: nicio valoare
    din răspuns nu are voie să ajungă acolo."""
    caplog.set_level(logging.DEBUG)
    with aioresponses() as mock:
        mock.post(
            URL_LOGIN,
            payload={
                "data": {
                    "session": {"token": "tok-secret-123", "username": "ion@gmail.com"},
                    "viewedAccount": {
                        "accountName": "POPESCU ION",
                        "email": "ion@gmail.com",
                        "phone": "0722334455",
                        "address": "Str. Lalelelor 12, Iași",
                        "accountNumber": "3047398",
                    },
                },
                "status": 200,
                "success": True,
            },
        )
        client = NovaApiClient(sesiune, "ion@gmail.com", "P@rolaSecreta")
        await client.async_login()

    for date_personale in (
        "POPESCU ION", "ion@gmail.com", "0722334455",
        "Str. Lalelelor 12", "3047398", "tok-secret-123", "P@rolaSecreta",
    ):
        assert date_personale not in caplog.text, f"{date_personale!r} a ajuns în log"

    # Structura rămâne vizibilă — de ea e nevoie la diagnosticare.
    assert "session" in caplog.text
    assert "viewedAccount" in caplog.text
    assert "text(" in caplog.text


async def test_parola_si_emailul_nu_ajung_in_loguri(sesiune, caplog):
    caplog.set_level(logging.DEBUG)
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "tokenfoartelung1234567890"})
        mock.get(URL_ME, payload={"ok": True})

        client = NovaApiClient(sesiune, "alin@exemplu.ro", "P@rolaSecreta")
        await client.async_login()
        await client.async_get(URL_ME)

    assert "P@rolaSecreta" not in caplog.text
    assert "alin@exemplu.ro" not in caplog.text
    assert "tokenfoartelung1234567890" not in caplog.text


async def test_tokenul_e_gasit_in_invelisul_real(sesiune):
    """Forma reală a API-ului: {data: {session: {token}}, status, success}."""
    with aioresponses() as mock:
        mock.post(
            URL_LOGIN,
            payload={
                "data": {
                    "session": {"token": "tok-real", "role": "client", "expireAt": 1792307286},
                    "loggedInAccount": {"accountId": "a1", "accountNumber": "123"},
                    "viewedAccount": {"accountId": "a1", "accountNumber": "123"},
                },
                "status": 200,
                "success": True,
            },
        )
        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        assert client.token == "tok-real"


async def test_invelis_fara_token_ridica_autherror(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"message": "ceva"}, "status": 200, "success": True})
        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        with pytest.raises(NovaAuthError):
            await client.async_login()


async def test_contul_e_reaplicat_dupa_reautentificare(sesiune):
    """Contul vizualizat e stare pe server: după re-login trebuie comutat din nou.

    Altfel datele altui cont ar ajunge în tăcere pe dispozitivul greșit.
    """
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t1"}}})
        mock.post(URL_SWITCH, payload={"ok": True})
        mock.get(URL_ME, status=401)                       # tokenul expiră
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t2"}}})
        mock.post(URL_SWITCH, payload={"ok": True})        # ← comutarea refăcută
        mock.get(URL_ME, payload={"ok": True})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        await client.async_switch_account("cont-2")
        assert await client.async_get(URL_ME) == {"ok": True}

    cereri_switch = [
        cerere for cerere in mock.requests if str(cerere[1]).endswith("/accounts/switch")
    ]
    apeluri = sum(len(mock.requests[cheie]) for cheie in cereri_switch)
    assert apeluri == 2, "comutarea pe cont nu a fost refăcută după reautentificare"


async def test_fara_cont_setat_nu_se_comuta_degeaba(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t1"}}})
        mock.get(URL_ME, status=401)
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t2"}}})
        mock.get(URL_ME, payload={"ok": True})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        assert await client.async_get(URL_ME) == {"ok": True}

    assert not [c for c in mock.requests if str(c[1]).endswith("/accounts/switch")]


async def test_o_singura_reautentificare_pentru_cereri_paralele(sesiune):
    """Coordinatorul trimite toate cererile odată. Dacă tokenul expiră, toate
    primesc 401 în același timp — dar trebuie să rezulte o singură
    autentificare, nu una pentru fiecare cerere: login-ul e endpoint-ul cel mai
    expus limitării de rată."""
    import asyncio

    from aioresponses import CallbackResult

    from custom_components.novaenergy.const import URL_BALANCES, URL_CONTRACTS

    adrese = [URL_ME, URL_BALANCES, URL_CONTRACTS]
    bariera = asyncio.Barrier(len(adrese))

    async def raspunde_401(url, **argumente):
        # Nicio cerere nu primește 401 până nu au ajuns toate aici: exact
        # situația reală, în care expirarea le prinde pe toate deodată.
        await bariera.wait()
        return CallbackResult(status=401)

    autentificari = 0

    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "vechi"}}})
        for adresa in adrese:
            mock.get(adresa, callback=raspunde_401)
        # Mai multe autentificări disponibile decât ar trebui folosite: dacă
        # implementarea face câte una per cerere, testul o va vedea în numărător.
        for _ in range(len(adrese)):
            mock.post(URL_LOGIN, payload={"data": {"session": {"token": "nou"}}})
        for adresa in adrese:
            mock.get(adresa, payload={"ok": True})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        autentificare_reala = client.async_login

        async def numara():
            nonlocal autentificari
            autentificari += 1
            return await autentificare_reala()

        client.async_login = numara

        await client.async_login()
        rezultate = await asyncio.gather(
            *(client.async_get(adresa) for adresa in adrese)
        )

    assert all(rezultat == {"ok": True} for rezultat in rezultate)
    assert client.token == "nou"
    assert autentificari == 2, (
        f"{autentificari} autentificări: una la pornire și una singură la "
        f"reînnoire, oricâte cereri ar primi 401 deodată"
    )
