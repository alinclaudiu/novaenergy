"""Clientul HTTP pentru API-ul Nova Power & Gas.

Responsabilitate strictă: transport și autentificare. Interpretarea datelor de
business se face în `coordinator.py` și `sensor.py`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import ANTET_CONT_VIZUALIZAT, API_TIMEOUT, HEADERS, URL_LOGIN, URL_SWITCH
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


class NovaCredentialeRespinse(NovaAuthError):
    """Emailul sau parola nu mai sunt acceptate la autentificare.

    Spre deosebire de un token expirat, aici o nouă încercare nu are cum să
    reușească: Home Assistant trebuie să ceară parola din nou.
    """


def _id_mascat(identificator: Any) -> str:
    """Identificatorul unui cont, în formă sigură pentru loguri publice."""
    text = str(identificator or "")
    return f"…{text[-4:]}" if len(text) > 4 else "…"


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
        # Unele răspunsuri sunt hărți ale căror chei sunt chiar identificatori ai
        # clientului — numere de cont, de loc de consum. Doar numele de câmpuri,
        # care sunt identificatori valizi, pot apărea în log.
        if not all(isinstance(cheie, str) and cheie.isidentifier() for cheie in date):
            prima = next(iter(date.values()))
            return f"{{{len(date)} chei × {_descrie_forma(prima, adancime + 1)}}}"
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
        # Contul pe care serverul îl arată după autentificare, fără comutare.
        self._cont_implicit: str | None = None
        # Crește la fiecare refacere a sesiunii, reușită sau nu: o cerere pornită
        # într-o epocă mai veche știe astfel că altcineva a refăcut-o deja.
        self._epoca = 0
        self._ultima_eroare: NovaApiError | None = None
        # Odată respinse, credențialele nu mai sunt încercate: fiecare încercare
        # ar fi încă o autentificare eșuată, pe endpoint-ul cel mai sensibil.
        self._credentiale_respinse: NovaCredentialeRespinse | None = None
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
        token, date = await self._autentifica()
        self._token = token
        self._cont_implicit = self._extrage_contul_vizualizat(date)
        return date

    async def _autentifica(self) -> tuple[str, Any]:
        """Obține un token nou, fără să-l pună încă în folosință."""
        if self._credentiale_respinse is not None:
            raise NovaCredentialeRespinse(*self._credentiale_respinse.args)

        _LOGGER.debug("Autentificare pentru %s", self.email_mascat)
        try:
            date = await self._cerere_bruta(
                "POST",
                URL_LOGIN,
                json={"email": self._email, "password": self._password},
                cu_autentificare=False,
            )
        except NovaCredentialeRespinse as eroare:
            self._credentiale_respinse = eroare
            raise

        token = self._extrage_token(date)
        if not token:
            continut = desfa_invelis(date)
            _LOGGER.error(
                "Răspunsul de autentificare nu conține un token; chei primite: %s",
                sorted(continut) if isinstance(continut, dict) else type(date).__name__,
            )
            raise NovaAuthError("Răspunsul de autentificare nu conține un token")

        _LOGGER.debug("Autentificare reușită pentru %s", self.email_mascat)
        return str(token), date

    @staticmethod
    def _extrage_contul_vizualizat(raspuns: Any) -> str | None:
        """Identificatorul contului pe care sesiunea îl arată implicit."""
        continut = desfa_invelis(raspuns)
        if not isinstance(continut, dict):
            return None
        for cheie in ("viewedAccount", "loggedInAccount"):
            cont = prima_valoare(continut.get(cheie), "accountId", "id", "_id")
            if cont:
                return str(cont)
        return None

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
        ține minte pe ce cont trebuie să fie și îl reaplică singur. În plus,
        fiecare cerere poartă contul în antetul `X-Viewed-Account`, exact ca
        aplicația oficială.
        """
        if self._token is None:
            await self._reface_sesiunea(self._epoca)

        rezultat: Any = {}
        # Pe contul implicit sesiunea e deja; o comutare n-ar schimba nimic.
        if account_id != self._cont_implicit:
            _LOGGER.debug("Comutare pe contul %s", _id_mascat(account_id))
            rezultat = await self._cerere(
                "POST",
                URL_SWITCH,
                json={"accountId": account_id},
                cont_vizualizat=self._cont_implicit or "",
            )
            self._preia_tokenul_nou(rezultat)

        self._cont_curent = account_id
        return rezultat

    def _preia_tokenul_nou(self, raspuns: Any) -> None:
        """Unele servere emit un token nou la comutare; dacă e așa, îl folosim."""
        token = self._extrage_token(raspuns)
        if token:
            self._token = token

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
        """Cerere autentificată, cu o singură reîncercare după refacerea sesiunii."""
        if self._token is None:
            await self._reface_sesiunea(self._epoca)

        epoca = self._epoca
        try:
            return await self._cerere_bruta(metoda, url, **argumente)
        except NovaCredentialeRespinse:
            raise
        except NovaAuthError:
            _LOGGER.debug("Token expirat pentru %s, se reînnoiește", self.email_mascat)
            await self._reface_sesiunea(epoca)
        return await self._cerere_bruta(metoda, url, **argumente)

    # ──────────────────────────────────────────
    # Sesiunea
    # ──────────────────────────────────────────
    async def _reface_sesiunea(self, epoca_vazuta: int) -> None:
        """Reface sesiunea o singură dată pentru toate cererile care o așteaptă.

        Coordinatorul trimite toate cererile odată, deci la expirarea tokenului
        primesc toate 401 deodată. Doar prima reface sesiunea; celelalte, pornite
        în aceeași epocă, folosesc rezultatul ei — sesiunea nouă sau eroarea.
        Altfel fiecare cerere și-ar face propria autentificare, exact pe
        endpoint-ul cel mai expus limitării de rată. Următorul val de cereri
        încearcă din nou.
        """
        async with self._blocaj:
            if self._epoca != epoca_vazuta:
                if self._token is None:
                    eroare = self._ultima_eroare or NovaApiError(
                        "Sesiunea Nova nu a putut fi refăcută"
                    )
                    raise type(eroare)(*eroare.args)
                return
            try:
                await self._reautentifica()
            except BaseException as eroare:
                # Și o întrerupere (anulare, sesiune HTTP închisă) lasă sesiunea
                # inutilizabilă: tokenul vechi a fost deja respins de server.
                self._token = None
                self._ultima_eroare = (
                    eroare
                    if isinstance(eroare, NovaApiError)
                    else NovaApiError("Refacerea sesiunii Nova a fost întreruptă")
                )
                raise
            finally:
                self._epoca += 1

    async def _reautentifica(self) -> None:
        """Sesiune nouă, adusă pe contul curent înainte de a fi folosită.

        Contul vizualizat e stare pe server, legată de sesiune: o sesiune nouă
        arată contul implicit. Tokenul nou devine vizibil celorlalte cereri abia
        după comutare — altfel o cerere pornită între timp ar primi datele
        contului implicit, care ar ajunge, în tăcere, pe dispozitivul greșit.
        """
        token, date = await self._autentifica()
        implicit = self._extrage_contul_vizualizat(date)
        cont = self._cont_curent
        if cont is not None and cont != implicit:
            _LOGGER.debug(
                "Se reface comutarea pe contul %s după reautentificare", _id_mascat(cont)
            )
            raspuns = await self._cerere_bruta(
                "POST",
                URL_SWITCH,
                json={"accountId": cont},
                token=token,
                cont_vizualizat=implicit or "",
            )
            token = self._extrage_token(raspuns) or token
        self._token = token
        self._cont_implicit = implicit

    async def _cerere_bruta(
        self,
        metoda: str,
        url: str,
        cu_autentificare: bool = True,
        token: str | None = None,
        cont_vizualizat: str | None = None,
        **argumente: Any,
    ) -> Any:
        """O singură cerere HTTP, fără reîncercare.

        `X-Viewed-Account` poartă contul pe care cererea îl privește: pentru
        date, contul curent; pentru o comutare, ca în aplicația oficială, contul
        pe care sesiunea îl vede încă (`cont_vizualizat`; `""` = niciunul).
        """
        anteturi = dict(HEADERS)
        token = token or self._token
        if cu_autentificare and token:
            anteturi["Authorization"] = f"Bearer {token}"
            cont = self._cont_curent if cont_vizualizat is None else cont_vizualizat
            if cont:
                anteturi[ANTET_CONT_VIZUALIZAT] = cont

        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.request(
                    metoda, url, headers=anteturi, **argumente
                ) as raspuns:
                    # Ca în aplicația oficială, doar 401 înseamnă autentificare
                    # respinsă; un 403 nu se schimbă printr-o reautentificare.
                    if raspuns.status == 401:
                        if not cu_autentificare:
                            raise NovaCredentialeRespinse(
                                f"Credențiale respinse (401) la {url}"
                            )
                        raise NovaAuthError(f"Acces respins (401) la {url}")
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
