"""Clientul HTTP: autentificare, reînnoirea tokenului, erori, discreție în loguri."""

import logging

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.novaenergy.api import (
    NovaApiClient,
    NovaApiError,
    NovaAuthError,
    NovaCredentialeRespinse,
    _descrie_forma,
)
from custom_components.novaenergy.const import (
    ANTET_CONT_VIZUALIZAT,
    URL_BALANCE,
    URL_LOGIN,
    URL_SWITCH,
)


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
        mock.get(URL_BALANCE, status=401)
        mock.post(URL_LOGIN, payload={"token": "nou"})
        mock.get(URL_BALANCE, payload={"crmCode": "1"})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        rezultat = await client.async_get(URL_BALANCE)

        assert rezultat == {"crmCode": "1"}
        assert client.token == "nou"


async def test_401_persistent_nu_reincearca_la_infinit(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_BALANCE, status=401)
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_BALANCE, status=401)

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        with pytest.raises(NovaAuthError):
            await client.async_get(URL_BALANCE)


async def test_eroare_de_retea_devine_novaapierror(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_BALANCE, exception=aiohttp.ClientError("cablu scos"))

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        with pytest.raises(NovaApiError):
            await client.async_get(URL_BALANCE)


async def test_eroare_de_server_devine_novaapierror(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_BALANCE, status=500)

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        with pytest.raises(NovaApiError):
            await client.async_get(URL_BALANCE)


async def test_get_face_login_automat_daca_nu_exista_token(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"token": "t"})
        mock.get(URL_BALANCE, payload={"ok": True})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        assert client.token is None
        assert await client.async_get(URL_BALANCE) == {"ok": True}


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
        mock.get(URL_BALANCE, payload={"ok": True})

        client = NovaApiClient(sesiune, "alin@exemplu.ro", "P@rolaSecreta")
        await client.async_login()
        await client.async_get(URL_BALANCE)

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
        mock.get(URL_BALANCE, status=401)                       # tokenul expiră
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t2"}}})
        mock.post(URL_SWITCH, payload={"ok": True})        # ← comutarea refăcută
        mock.get(URL_BALANCE, payload={"ok": True})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        await client.async_switch_account("cont-2")
        assert await client.async_get(URL_BALANCE) == {"ok": True}

    cereri_switch = [
        cerere for cerere in mock.requests if str(cerere[1]).endswith("/auth/switch-account")
    ]
    apeluri = sum(len(mock.requests[cheie]) for cheie in cereri_switch)
    assert apeluri == 2, "comutarea pe cont nu a fost refăcută după reautentificare"


async def test_fara_cont_setat_nu_se_comuta_degeaba(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t1"}}})
        mock.get(URL_BALANCE, status=401)
        mock.post(URL_LOGIN, payload={"data": {"session": {"token": "t2"}}})
        mock.get(URL_BALANCE, payload={"ok": True})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()
        assert await client.async_get(URL_BALANCE) == {"ok": True}

    assert not [c for c in mock.requests if str(c[1]).endswith("/auth/switch-account")]


async def test_o_singura_reautentificare_pentru_cereri_paralele(sesiune):
    """Coordinatorul trimite toate cererile odată. Dacă tokenul expiră, toate
    primesc 401 în același timp — dar trebuie să rezulte o singură
    autentificare, nu una pentru fiecare cerere: login-ul e endpoint-ul cel mai
    expus limitării de rată."""
    import asyncio

    from aioresponses import CallbackResult

    from custom_components.novaenergy.const import URL_CONTRACTS, URL_INVOICES

    adrese = [URL_BALANCE, URL_INVOICES, URL_CONTRACTS]
    bariera = asyncio.Barrier(len(adrese))

    async def raspunde_401(url, **argumente):
        # Nicio cerere nu primește 401 până nu au ajuns toate aici: exact
        # situația reală, în care expirarea le prinde pe toate deodată.
        await bariera.wait()
        return CallbackResult(status=401)

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
        await client.async_login()
        rezultate = await asyncio.gather(
            *(client.async_get(adresa) for adresa in adrese)
        )

    autentificari = _cereri_catre(mock, "/auth/login")
    assert all(rezultat == {"ok": True} for rezultat in rezultate)
    assert client.token == "nou"
    assert autentificari == 2, (
        f"{autentificari} autentificări: una la pornire și una singură la "
        f"reînnoire, oricâte cereri ar primi 401 deodată"
    )


# ──────────────────────────────────────────────
# Contul vizualizat
# ──────────────────────────────────────────────
LOGIN_CU_CONT = {
    "data": {
        "session": {"token": "t1"},
        "loggedInAccount": {"accountId": "acc-1", "accountNumber": "111"},
        "viewedAccount": {"accountId": "acc-1", "accountNumber": "111"},
    },
    "status": 200,
    "success": True,
}


def _cereri_catre(mock, sufix: str) -> int:
    return sum(
        len(mock.requests[cheie]) for cheie in mock.requests if str(cheie[1]).endswith(sufix)
    )


async def test_comutarea_pe_contul_implicit_nu_trimite_cerere(sesiune):
    """Sesiunea e deja pe contul cu care s-a autentificat: comutarea ar fi o
    cerere inutilă către server, la fiecare pornire."""
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.get(URL_BALANCE, payload={"data": {"total": 0}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("acc-1")
        await client.async_get(URL_BALANCE)

    assert _cereri_catre(mock, "/auth/switch-account") == 0


async def test_comutarea_pe_alt_cont_trimite_cerere(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, payload={"data": {"viewedAccount": {"accountId": "acc-2"}}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("acc-2")

    cereri = [c for c in mock.requests if str(c[1]).endswith("/auth/switch-account")]
    assert len(cereri) == 1
    assert mock.requests[cereri[0]][0].kwargs["json"] == {"accountId": "acc-2"}


async def test_fiecare_cerere_poarta_contul_vizualizat(sesiune):
    """Aplicația oficială trimite contul în antetul `X-Viewed-Account` la
    fiecare cerere; fără el, datele ar putea veni de pe contul implicit."""
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, payload={"ok": True})
        mock.get(URL_BALANCE, payload={"data": {"total": 0}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("acc-2")
        await client.async_get(URL_BALANCE)

    cerere = next(c for c in mock.requests if str(c[1]) == URL_BALANCE)
    anteturi = mock.requests[cerere][0].kwargs["headers"]
    assert anteturi[ANTET_CONT_VIZUALIZAT] == "acc-2"
    assert anteturi["Authorization"] == "Bearer t1"


async def test_fara_comutare_nu_se_trimite_antetul(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.get(URL_BALANCE, payload={"data": {"total": 0}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_get(URL_BALANCE)

    cerere = next(c for c in mock.requests if str(c[1]) == URL_BALANCE)
    assert ANTET_CONT_VIZUALIZAT not in mock.requests[cerere][0].kwargs["headers"]


async def test_tokenul_emis_la_comutare_e_folosit(sesiune):
    """Dacă serverul emite o sesiune nouă la comutare, vechiul token nu mai
    trebuie folosit."""
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, payload={"data": {"session": {"token": "t-comutat"}}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("acc-2")

    assert client.token == "t-comutat"


async def test_comutarea_esuata_nu_lasa_antetul_setat(sesiune):
    """Dacă serverul refuză comutarea, cererile nu au voie să pretindă că
    vizualizează contul respectiv."""
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, status=500)
        mock.get(URL_BALANCE, payload={"data": {"total": 0}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        with pytest.raises(NovaApiError):
            await client.async_switch_account("acc-2")
        await client.async_get(URL_BALANCE)

    cerere = next(c for c in mock.requests if str(c[1]) == URL_BALANCE)
    assert ANTET_CONT_VIZUALIZAT not in mock.requests[cerere][0].kwargs["headers"]


async def test_contul_implicit_nu_e_recomutat_dupa_reautentificare(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.get(URL_BALANCE, status=401)
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.get(URL_BALANCE, payload={"data": {"total": 0}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("acc-1")
        assert await client.async_get(URL_BALANCE) == {"data": {"total": 0}}

    assert _cereri_catre(mock, "/auth/switch-account") == 0


# ──────────────────────────────────────────────
# Refacerea sesiunii
# ──────────────────────────────────────────────
async def test_parola_respinsa_nu_e_reincercata(sesiune):
    """Parola schimbată: toate cererile primesc 401, iar reautentificarea e
    respinsă. Trebuie să rezulte o singură autentificare eșuată — nu una per
    cerere și nu una la fiecare ciclu — și o eroare pe care Home Assistant o
    poate transforma în cererea de parolă nouă."""
    import asyncio

    from custom_components.novaenergy.const import URL_CONTRACTS, URL_INVOICES

    adrese = [URL_BALANCE, URL_INVOICES, URL_CONTRACTS]
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        for adresa in adrese:
            mock.get(adresa, status=401)
        mock.post(URL_LOGIN, status=401, repeat=True)

        client = NovaApiClient(sesiune, "a@b.ro", "parola-veche")
        await client.async_login()
        rezultate = await asyncio.gather(
            *(client.async_get(adresa) for adresa in adrese), return_exceptions=True
        )
        assert all(isinstance(r, NovaCredentialeRespinse) for r in rezultate), rezultate

        # Ciclul următor nu mai încearcă deloc.
        with pytest.raises(NovaCredentialeRespinse):
            await client.async_get(URL_BALANCE)

    assert _cereri_catre(mock, "/auth/login") == 2  # cea inițială + una respinsă


async def test_login_respins_la_configurare_e_eroare_de_autentificare(sesiune):
    with aioresponses() as mock:
        mock.post(URL_LOGIN, status=401)
        client = NovaApiClient(sesiune, "a@b.ro", "gresita")
        with pytest.raises(NovaCredentialeRespinse):
            await client.async_login()


async def test_403_nu_declanseaza_reautentificare(sesiune):
    """Ca în aplicația oficială, doar 401 înseamnă token expirat. Un 403 nu se
    rezolvă cu o sesiune nouă — iar o reautentificare la fiecare ciclu ar lovi
    degeaba endpoint-ul de login."""
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.get(URL_BALANCE, status=403)

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        with pytest.raises(NovaApiError) as eroare:
            await client.async_get(URL_BALANCE)

    assert not isinstance(eroare.value, NovaAuthError)
    assert _cereri_catre(mock, "/auth/login") == 1


async def test_comutarea_esuata_dupa_reautentificare_e_reluata(sesiune):
    """Dacă reautentificarea reușește, dar comutarea pe cont eșuează, sesiunea
    nouă e pe contul implicit. Ea nu are voie să fie folosită — ar aduce datele
    altui cont pe acest dispozitiv — iar următoarea cerere reface totul."""
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, payload={"ok": True})
        mock.get(URL_BALANCE, status=401)                 # tokenul expiră
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, status=503)                 # recomutarea eșuează
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)       # ciclul următor
        mock.post(URL_SWITCH, payload={"ok": True})
        mock.get(URL_BALANCE, payload={"data": {"total": 1}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("acc-2")
        with pytest.raises(NovaApiError):
            await client.async_get(URL_BALANCE)
        assert client.token is None, "sesiunea necomutată a rămas în folosință"

        assert await client.async_get(URL_BALANCE) == {"data": {"total": 1}}

    assert _cereri_catre(mock, "/auth/switch-account") == 3
    cerere = [c for c in mock.requests if str(c[1]) == URL_BALANCE][0]
    assert mock.requests[cerere][-1].kwargs["headers"][ANTET_CONT_VIZUALIZAT] == "acc-2"


async def test_cererile_paralele_impart_esecul_recomutarii(sesiune):
    """Când recomutarea eșuează, cererile din același val primesc aceeași
    eroare, fără câte o autentificare fiecare."""
    import asyncio

    from custom_components.novaenergy.const import URL_CONTRACTS, URL_INVOICES

    from aioresponses import CallbackResult

    adrese = [URL_BALANCE, URL_INVOICES, URL_CONTRACTS]
    bariera = asyncio.Barrier(len(adrese))

    async def raspunde_401(url, **argumente):
        # Toate cererile sunt în zbor înainte ca vreuna să primească 401, ca în
        # realitate: coordinatorul le trimite pe toate odată.
        await bariera.wait()
        return CallbackResult(status=401)

    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, payload={"ok": True})
        for adresa in adrese:
            mock.get(adresa, callback=raspunde_401)
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT, repeat=True)
        mock.post(URL_SWITCH, status=503, repeat=True)

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("acc-2")
        rezultate = await asyncio.gather(
            *(client.async_get(adresa) for adresa in adrese), return_exceptions=True
        )

    assert all(isinstance(r, NovaApiError) for r in rezultate), rezultate
    assert _cereri_catre(mock, "/auth/login") == 2  # cea inițială + o singură refacere


async def test_recomutarea_foloseste_tokenul_nou(sesiune):
    """Comutarea de după reautentificare pleacă deja cu tokenul nou, iar acesta
    devine al clientului abia după ce comutarea a reușit."""
    login_nou = {
        **LOGIN_CU_CONT,
        "data": {**LOGIN_CU_CONT["data"], "session": {"token": "t2"}},
    }
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, payload={"ok": True})
        mock.get(URL_BALANCE, status=401)
        mock.post(URL_LOGIN, payload=login_nou)
        mock.post(URL_SWITCH, payload={"ok": True})
        mock.get(URL_BALANCE, payload={"data": {"total": 1}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("acc-2")
        await client.async_get(URL_BALANCE)

    comutari = mock.requests[next(c for c in mock.requests if str(c[1]) == URL_SWITCH)]
    assert comutari[1].kwargs["headers"]["Authorization"] == "Bearer t2"
    assert client.token == "t2"


async def test_comutarea_nu_scrie_in_log_identificatorul_contului(sesiune, caplog):
    """Logurile ajung în issue-uri publice: din identificatorul contului apare
    doar finalul."""
    caplog.set_level(logging.DEBUG)
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, payload={"ok": True})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("1f2e3d4c-0000-4000-8000-00000000beef")

    assert "1f2e3d4c" not in caplog.text
    assert "…beef" in caplog.text


def test_forma_ascunde_cheile_care_sunt_identificatori():
    """Unele răspunsuri sunt hărți cu chei ca numărul locului de consum; în log
    ajunge doar câte sunt și forma valorilor."""
    forma = _descrie_forma(
        {"total": 0, "perMeteringPoint": {"LC-00000001": {"total": 1}, "LC-00000002": {}}}
    )
    assert "LC-00000001" not in forma
    assert "perMeteringPoint: {2 chei × {total: număr}}" in forma
    assert _descrie_forma({"9100123456": {"total": 0}}) == "{1 chei × {total: număr}}"


async def test_comutarile_poarta_contul_vazut_de_sesiune(sesiune):
    """Ca în aplicația oficială, cererea de comutare poartă în antet contul pe
    care sesiunea îl vede încă — la prima comutare și la cea de după
    reautentificare, la fel. Cererile de date poartă contul comutat."""
    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, payload={"ok": True})
        mock.get(URL_BALANCE, status=401)
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        mock.post(URL_SWITCH, payload={"ok": True})
        mock.get(URL_BALANCE, payload={"data": {"total": 1}})

        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_switch_account("acc-2")
        await client.async_get(URL_BALANCE)

    comutari = mock.requests[next(c for c in mock.requests if str(c[1]) == URL_SWITCH)]
    assert [c.kwargs["headers"][ANTET_CONT_VIZUALIZAT] for c in comutari] == ["acc-1", "acc-1"]
    date = mock.requests[next(c for c in mock.requests if str(c[1]) == URL_BALANCE)]
    assert date[-1].kwargs["headers"][ANTET_CONT_VIZUALIZAT] == "acc-2"
    autentificari = mock.requests[next(c for c in mock.requests if str(c[1]) == URL_LOGIN)]
    assert all(ANTET_CONT_VIZUALIZAT not in c.kwargs["headers"] for c in autentificari)


async def test_reautentificarea_intrerupta_nu_lasa_tokenul_mort(sesiune):
    """O anulare în mijlocul reautentificării lasă sesiunea inutilizabilă:
    cererile care așteaptă primesc o eroare, nu reîncearcă cu tokenul pe care
    serverul l-a respins deja."""
    import asyncio
    from unittest.mock import AsyncMock

    with aioresponses() as mock:
        mock.post(URL_LOGIN, payload=LOGIN_CU_CONT)
        client = NovaApiClient(sesiune, "a@b.ro", "parola")
        await client.async_login()

    epoca = client._epoca
    client._reautentifica = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await client._reface_sesiunea(epoca)

    assert client.token is None
    # O cerere care a pornit în aceeași epocă primește eroarea, fără reîncercare.
    with pytest.raises(NovaApiError):
        await client._reface_sesiunea(epoca)
    assert client._reautentifica.await_count == 1
