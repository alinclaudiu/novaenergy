#!/usr/bin/env python3
"""Explorare a API-ului Nova Power & Gas, ca să aflăm forma reală a răspunsurilor.

Scriptul NU face parte din integrare. Se rulează manual, cu credențialele
proprii. Rezultatul lui rămâne local, în `.explorare/` (ignorat de git): el doar
confirmă forma, iar fixturile din `tests/fixtures/` se scriu apoi de mână, cu
valori de exemplu — anonimizatorul ascunde identificatorii, dar lasă să treacă
sumele, indexurile și datele.

Reguli respectate cu strictețe:
  * se ating EXCLUSIV endpoint-uri de citire (GET), plus POST-ul de login și
    cel de comutare a contului; POST pe `/self-readings` (trimiterea unei
    autocitiri) nu este atins niciodată;
  * fiecare răspuns trece prin `anonimizeaza()` înainte de a fi scris pe disc;
  * credențialele se citesc dintr-un fișier .env care nu intră în repo.

Utilizare:
    NOVA_ENV_FILE=/cale/catre/.env python3 scripts/explorare_api.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp

RADACINA = Path(__file__).parent.parent
sys.path.insert(0, str(RADACINA))

from scripts.anonimizare import anonimizeaza, chei_ascunse, contine_text  # noqa: E402

sys.path.insert(0, str(RADACINA / "custom_components" / "novaenergy"))

API_BASE = "https://myaccount-admin.nova-energy.ro/api/v1"
URL_LOGIN = f"{API_BASE}/auth/login"
URL_SWITCH = f"{API_BASE}/auth/switch-account"
ANTET_CONT_VIZUALIZAT = "X-Viewed-Account"

# Doar citiri. Cheia devine numele fixturii.
ENDPOINTURI_GET: dict[str, str] = {
    "balance": f"{API_BASE}/dashboard/balance",
    "contracts": f"{API_BASE}/contracts",
    "metering_points": f"{API_BASE}/metering-points",
    "invoices": f"{API_BASE}/invoices",
    "payments": f"{API_BASE}/payments",
    "self_readings": f"{API_BASE}/self-readings",
}

# Niciodată `tests/fixtures/`: acolo sunt fixturile publicate, scrise de mână.
DIRECTOR_FIXTURI = RADACINA / ".explorare"


def citeste_env() -> tuple[str, str]:
    """Citește credențialele din .env, fără să le afișeze vreodată."""
    cale = Path(os.environ.get("NOVA_ENV_FILE", RADACINA / ".env"))
    valori: dict[str, str] = {}
    if cale.exists():
        for linie in cale.read_text(encoding="utf-8").splitlines():
            linie = linie.strip()
            if not linie or linie.startswith("#") or "=" not in linie:
                continue
            cheie, _, valoare = linie.partition("=")
            valori[cheie.strip()] = valoare.strip().strip('"').strip("'")

    email = valori.get("NOVA_EMAIL") or os.environ.get("NOVA_EMAIL", "")
    parola = valori.get("NOVA_PASSWORD") or os.environ.get("NOVA_PASSWORD", "")

    if not email or not parola:
        print(
            f"Lipsesc credențialele. Creează {cale} cu:\n"
            "  NOVA_EMAIL=adresa@exemplu.ro\n"
            "  NOVA_PASSWORD=parola",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return email, parola


def scrie_fixtura(nume: str, date: Any) -> None:
    DIRECTOR_FIXTURI.mkdir(parents=True, exist_ok=True)
    cale = DIRECTOR_FIXTURI / f"{nume}.json"
    cale.write_text(
        json.dumps(anonimizeaza(date), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"  ✔ {cale.relative_to(RADACINA)}")


# Aceeași regulă ca în integrare (helpers.desfa_invelis), repetată aici ca
# scriptul să ruleze și fără Home Assistant instalat.
CHEI_INVELIS = frozenset({"data", "status", "success", "message", "code", "meta"})


def desfa(raspuns: Any) -> Any:
    """Scoate conținutul din învelișul API-ului: `{data, status, success}`,
    `{message, data}` sau doar `{data}`."""
    if (
        isinstance(raspuns, dict)
        and "data" in raspuns
        and ({"status", "success"} & set(raspuns) or set(raspuns) <= CHEI_INVELIS)
    ):
        return raspuns["data"]
    return raspuns


async def login(sesiune: aiohttp.ClientSession, email: str, parola: str) -> tuple[str, dict]:
    async with sesiune.post(URL_LOGIN, json={"email": email, "password": parola}) as raspuns:
        raspuns.raise_for_status()
        date = await raspuns.json()

    continut = desfa(date)
    sesiune_api = continut.get("session") if isinstance(continut, dict) else None
    token = ""
    if isinstance(sesiune_api, dict):
        token = sesiune_api.get("token") or ""
    if not token and isinstance(continut, dict):
        token = continut.get("token") or continut.get("accessToken") or ""

    if not token:
        print("  ⚠ răspunsul de login nu conține un token recognoscibil")
        print(f"    chei la rădăcină: {sorted(date) if isinstance(date, dict) else type(date)}")
        print(f"    chei sub data: {sorted(continut) if isinstance(continut, dict) else type(continut)}")
    return token, date


async def ia_tot(
    sesiune: aiohttp.ClientSession, token: str, prefix: str, cont: str | None = None
) -> None:
    anteturi = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if cont:
        anteturi[ANTET_CONT_VIZUALIZAT] = cont
    numere: list[str] = []
    for nume, url in ENDPOINTURI_GET.items():
        try:
            async with sesiune.get(url, headers=anteturi) as raspuns:
                if raspuns.status != 200:
                    print(f"  · {nume}: HTTP {raspuns.status} (se ignoră)")
                    continue
                date = await raspuns.json()
                scrie_fixtura(f"{prefix}_{nume}", date)
        except (aiohttp.ClientError, asyncio.TimeoutError) as eroare:
            print(f"  · {nume}: eroare de rețea ({eroare})")
            continue
        if nume == "metering_points":
            puncte = (desfa(date) or {}).get("meteringPoints") or []
            numere = [str(p["number"]) for p in puncte if isinstance(p, dict) and p.get("number")]

    # Contoarele se cer pe numărul locului de consum (nu pe meteringPointId).
    # În fișier, locurile apar ca „loc1", „loc2"…, nu cu numărul lor.
    if not numere:
        print("  · contoare: niciun număr de loc de consum găsit (se ignoră)")
    contoare: dict[str, Any] = {}
    for pozitie, numar in enumerate(numere, start=1):
        url = f"{API_BASE}/metering-points/{quote(numar, safe='')}/meters"
        try:
            async with sesiune.get(url, headers=anteturi) as raspuns:
                if raspuns.status != 200:
                    print(f"  · contoare loc{pozitie}: HTTP {raspuns.status} (se ignoră)")
                    continue
                contoare[f"loc{pozitie}"] = await raspuns.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as eroare:
            print(f"  · contoare loc{pozitie}: eroare de rețea ({type(eroare).__name__})")
    if contoare:
        scrie_fixtura(f"{prefix}_meters", contoare)


async def principal() -> None:
    email, parola = citeste_env()

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as sesiune:
        print("1. Autentificare…")
        token, payload_login = await login(sesiune, email, parola)
        scrie_fixtura("login", payload_login)

        continut = desfa(payload_login)
        principal_ = continut.get("loggedInAccount") or continut.get("viewedAccount") or {}
        conturi = principal_.get("associatedAccounts") or continut.get("associatedAccounts") or []
        print(f"   cont principal: {'da' if principal_ else 'nedetectat'}")
        print(f"   conturi asociate: {len(conturi)}")

        print("2. Endpoint-uri pe contul curent…")
        await ia_tot(sesiune, token, "principal")

        for index, cont in enumerate(conturi):
            id_cont = cont.get("accountId") or cont.get("id") or cont.get("_id")
            if not id_cont:
                print(f"   contul asociat #{index + 1} nu are identificator; se sare peste el")
                continue
            print(f"3.{index + 1} Comutare pe contul asociat #{index + 1}…")
            async with sesiune.post(
                URL_SWITCH,
                json={"accountId": id_cont},
                headers={"Authorization": f"Bearer {token}"},
            ) as raspuns:
                if raspuns.status != 200:
                    print(f"   comutarea a eșuat: HTTP {raspuns.status}")
                    continue
                scrie_fixtura(f"switch_{index + 1}", await raspuns.json())
            await ia_tot(sesiune, token, f"asociat{index + 1}", str(id_cont))

        print("4. Al doilea login întoarce un token distinct?")
        token_doi, _ = await login(sesiune, email, parola)
        print(f"   {'DA' if token_doi != token else 'NU'}")
        print(
            "   → dacă DA, fiecare cont poate avea propria sesiune și coordinatoarele\n"
            "     pot rula în paralel; dacă NU, ar trebui serializate."
        )

    # ── Plasă de siguranță: datele reale nu au voie să rămână în fixturi ──
    print("5. Verificare finală a fixturilor…")
    probleme = []
    local_email = email.split("@")[0]
    for cale in sorted(DIRECTOR_FIXTURI.glob("*.json")):
        continut_fisier = cale.read_text(encoding="utf-8")
        for text, descriere in ((email, "adresa de email"), (local_email, "partea locală a emailului")):
            if contine_text(continut_fisier, text):
                probleme.append(f"{cale.name}: conține {descriere}")

    if probleme:
        print("   ✖ SCURGERE DE DATE — fixturile NU pot fi folosite:")
        for problema in probleme:
            print(f"     {problema}")
        raise SystemExit(2)
    print("   ✔ nicio urmă a datelor de autentificare în fixturi")

    if chei_ascunse:
        print(f"\n   Chei ascunse de anonimizator ({len(chei_ascunse)}):")
        print(f"   {', '.join(sorted(chei_ascunse))}")
        print("   Dacă vreuna dintre ele e o enumerare de business, nu o dată")
        print("   personală, adaug-o în CHEI_SIGURE din scripts/anonimizare.py.")

    print(
        f"\nGata. Răspunsurile sunt în {DIRECTOR_FIXTURI.relative_to(RADACINA)}/ și nu se\n"
        "comit: fixturile din tests/fixtures/ se scriu de mână, cu valori de exemplu."
    )


if __name__ == "__main__":
    asyncio.run(principal())
