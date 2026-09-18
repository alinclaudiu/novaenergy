"""Clientul HTTP pentru API-ul Nova Power & Gas.

Responsabilitate strictă: transport și autentificare. Interpretarea datelor de
business se face în `coordinator.py` și `sensor.py`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_TIMEOUT, HEADERS, URL_LOGIN, URL_SWITCH
from .helpers import desfa_invelis, extrage_lista, mask_email, pagina_urmatoare, prima_valoare

_LOGGER = logging.getLogger(__name__)

# Câte elemente cerem pe pagină și câte pagini acceptăm înainte de a renunța.
# Serverul pagineaza implicit la 10; fără o limită proprie, un cont cu istoric
# lung ar fi citit doar parțial, în tăcere.
ELEMENTE_PE_PAGINA = 100
PAGINI_MAXIME = 50

# Cât de adânc și cât de larg se descrie forma unui răspuns în loguri.
ADANCIME_MAXIMA_FORMA = 4
CAMPURI_MAXIME_FORMA = 25


class NovaApiError(Exception):
    """Eroare de rețea sau răspuns neinterpretabil."""


class NovaAuthError(NovaApiError):
    """Autentificare respinsă de server."""


def _descrie_forma(date: Any, adancime: int = 0) -> str:
    """Descrie structura unui răspuns, fără niciuna dintre valorile lui.

    Logurile de depanare sunt făcute ca să fie lipite în issue-uri publice —
    `DEBUG.md` chiar asta cere. Răspunsurile API conțin însă nume, adrese,
    telefoane, solduri și numere de contract. De aceea în log ajung doar cheile,
    tipurile și mărimile: exact cât trebuie ca să diagnostichezi o schimbare de
    format, și nimic despre persoana din spatele contului.
    """
    if adancime > ADANCIME_MAXIMA_FORMA:
        return "…"

    if isinstance(date, dict):
        if not date:
            return "{}"
        perechi = [
            f"{cheie}: {_descrie_forma(valoare, adancime + 1)}"
            for cheie, valoare in list(date.items())[:CAMPURI_MAXIME_FORMA]
        ]
        if len(date) > CAMPURI_MAXIME_FORMA:
            perechi.append(f"… încă {len(date) - CAMPURI_MAXIME_FORMA}")
        return "{" + ", ".join(perechi) + "}"

    if isinstance(date, list):
        if not date:
            return "[]"
        return f"[{len(date)} × {_descrie_forma(date[0], adancime + 1)}]"

    if date is None:
        return "null"
    if isinstance(date, bool):
        return "bool"
    if isinstance(date, (int, float)):
        return "număr"
    if isinstance(date, str):
        return f"text({len(date)})"
    return type(date).__name__


class NovaApiClient:
    """Sesiune autentificată către API-ul Nova.

    Fiecare cont monitorizat primește propriul client, ca actualizările să poată
    rula în paralel fără să își schimbe reciproc contul vizualizat.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        timeout: int = API_TIMEOUT,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._timeout = timeout
        self._token: str | None = None
        self._cont_curent: str | None = None
        self._blocaj = asyncio.Lock()

    @property
    def token(self) -> str | None:
        """Tokenul curent, sau None dacă nu s-a făcut încă autentificarea."""
        return self._token

    @property
    def email_mascat(self) -> str:
        """Emailul în formă sigură pentru loguri."""
        return mask_email(self._email)

    # ──────────────────────────────────────────
    # Autentificare
    # ──────────────────────────────────────────
    async def async_login(self) -> dict:
        """Se autentifică și reține tokenul. Întoarce payload-ul brut."""
        _LOGGER.debug("Autentificare pentru %s", self.email_mascat)

        date = await self._cerere_bruta(
            "POST",
            URL_LOGIN,
            json={"email": self._email, "password": self._password},
            cu_autentificare=False,
        )

        token = self._extrage_token(date)
        if not token:
            continut = desfa_invelis(date)
            _LOGGER.error(
                "Răspunsul de autentificare nu conține un token; chei primite: %s",
                sorted(continut) if isinstance(continut, dict) else type(date).__name__,
            )
            raise NovaAuthError("Răspunsul de autentificare nu conține un token")

        self._token = str(token)
        _LOGGER.debug("Autentificare reușită pentru %s", self.email_mascat)
        return date

    @staticmethod
    def _extrage_token(raspuns: Any) -> str:
        """Găsește tokenul, indiferent unde îl pune API-ul.

        Forma curentă îl ține la `data.session.token`, dar căutarea acoperă și
        variantele mai simple, ca o schimbare de format să nu blocheze
        autentificarea.
        """
        continut = desfa_invelis(raspuns)
        if isinstance(continut, dict):
            sesiune = continut.get("session")
            if isinstance(sesiune, dict):
                token = prima_valoare(sesiune, "token", "accessToken", "jwt")
                if token:
                    return str(token)
            token = prima_valoare(continut, "token", "accessToken", "jwt")
            if token:
                return str(token)
        if isinstance(raspuns, dict):
            token = prima_valoare(raspuns, "token", "accessToken", "jwt")
            if token:
                return str(token)
        return ""

    async def async_switch_account(self, account_id: str) -> dict:
        """Comută contul vizualizat de această sesiune și îl reține.

        Contul vizualizat e stare pe server, legată de sesiune. După o
        reautentificare, serverul revine la contul implicit — de aceea clientul
        ține minte pe ce cont trebuie să fie și îl reaplică singur.
        """
        _LOGGER.debug("Comutare pe contul %s", account_id)
        rezultat = await self.async_post(URL_SWITCH, json={"accountId": account_id})
        self._cont_curent = account_id
        return rezultat

    # ──────────────────────────────────────────
    # Cereri
    # ──────────────────────────────────────────
    async def async_get(self, url: str, params: dict | None = None) -> Any:
        """GET autentificat."""
        return await self._cerere("GET", url, params=params)

    async def async_get_all(self, url: str, params: dict | None = None) -> list[dict]:
        """Aduce toate paginile unui endpoint de listă, nu doar prima.

        Endpoint-urile Nova răspund paginat, cu 10 elemente implicit. Un cont
        facturat lunar depășește pragul în câteva luni, iar trunchierea ar fi
        tăcută: pagina scurtă vine cu HTTP 200, deci nimic nu ar semnala că
        lipsesc date.
        """
        elemente: list[dict] = []
        pagina = 1

        for _ in range(PAGINI_MAXIME):
            argumente = dict(params or {})
            argumente.update({"limit": ELEMENTE_PE_PAGINA, "page": pagina})
            raspuns = await self.async_get(url, params=argumente)

            elemente.extend(extrage_lista(raspuns))

            urmatoare = pagina_urmatoare(raspuns)
            if urmatoare is None or urmatoare <= pagina:
                return elemente
            pagina = urmatoare

        _LOGGER.warning(
            "S-au atins %d pagini la %s; restul datelor nu au fost citite",
            PAGINI_MAXIME,
            url,
        )
        return elemente

    async def async_post(self, url: str, json: dict | None = None) -> Any:
        """POST autentificat."""
        return await self._cerere("POST", url, json=json)

    async def _cerere(self, metoda: str, url: str, **argumente: Any) -> Any:
        """Cerere autentificată, cu o singură reîncercare după reînnoirea tokenului."""
        if self._token is None:
            async with self._blocaj:
                if self._token is None:
                    await self.async_login()

        # Tokenul cu care pleacă această cerere. Dacă ea eșuează cu 401 și între
        # timp altcineva a reînnoit deja, nu mai are rost o autentificare nouă.
        token_folosit = self._token

        try:
            return await self._cerere_bruta(metoda, url, **argumente)
        except NovaAuthError:
            # Coordinatorul trimite toate cererile odată, deci la expirare
            # primesc toate 401. Fără verificarea de mai jos s-ar face câte o
            # autentificare pentru fiecare — exact endpoint-ul cel mai expus
            # limitării de rată.
            async with self._blocaj:
                if self._token == token_folosit:
                    _LOGGER.debug(
                        "Token expirat pentru %s, se reînnoiește", self.email_mascat
                    )
                    await self.async_login()
                    await self._reaplica_contul()
            return await self._cerere_bruta(metoda, url, **argumente)

    async def _reaplica_contul(self) -> None:
        """Reface comutarea pe cont după o reautentificare.

        Fără asta, sesiunea reînnoită ar privi contul implicit, iar datele altui
        cont ar ajunge, în tăcere, pe dispozitivul greșit.
        """
        cont = self._cont_curent
        if cont is None:
            return
        _LOGGER.debug("Se reface comutarea pe contul %s după reautentificare", cont)
        await self._cerere_bruta("POST", URL_SWITCH, json={"accountId": cont})

    async def _cerere_bruta(
        self, metoda: str, url: str, cu_autentificare: bool = True, **argumente: Any
    ) -> Any:
        """O singură cerere HTTP, fără reîncercare."""
        anteturi = dict(HEADERS)
        if cu_autentificare and self._token:
            anteturi["Authorization"] = f"Bearer {self._token}"

        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.request(
                    metoda, url, headers=anteturi, **argumente
                ) as raspuns:
                    if raspuns.status in (401, 403):
                        raise NovaAuthError(f"Acces respins ({raspuns.status}) la {url}")
                    if raspuns.status >= 400:
                        raise NovaApiError(f"HTTP {raspuns.status} la {url}")

                    date = await raspuns.json(content_type=None)
                    if _LOGGER.isEnabledFor(logging.DEBUG):
                        _LOGGER.debug(
                            "%s %s → %s", metoda, url, _descrie_forma(date)
                        )
                    return date

        except NovaApiError:
            raise
        except TimeoutError as eroare:
            raise NovaApiError(f"Timeout la {url}") from eroare
        except aiohttp.ClientError as eroare:
            raise NovaApiError(f"Eroare de rețea la {url}: {eroare}") from eroare
        except ValueError as eroare:
            raise NovaApiError(f"Răspuns invalid de la {url}: {eroare}") from eroare
