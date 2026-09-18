#!/usr/bin/env python3
"""Explorare unică a API-ului Nova Power & Gas, pentru a produce fixturi de test.

Scriptul NU face parte din integrare și nu se publică. Se rulează o singură
dată, manual, cu credențialele proprii, ca să aflăm forma reală a răspunsurilor.

Reguli respectate cu strictețe:
  * se ating EXCLUSIV endpoint-uri de citire (GET), plus POST-ul de login și
    cel de comutare a contului; `/self-readings/add` nu este atins niciodată;
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

import aiohttp

RADACINA = Path(__file__).parent.parent
sys.path.insert(0, str(RADACINA))

from scripts.anonimizare import anonimizeaza, chei_ascunse, contine_text  # noqa: E402

sys.path.insert(0, str(RADACINA / "custom_components" / "novaenergy"))

API_BASE = "https://backend.nova-energy.ro/api"
URL_LOGIN = f"{API_BASE}/accounts/login/client"
URL_SWITCH = f"{API_BASE}/accounts/switch"

# Doar citiri. Cheia devine numele fixturii.
ENDPOINTURI_GET: dict[str, str] = {
    "me": f"{API_BASE}/accounts/me",
    "app_info": f"{API_BASE}/globals/app-info/general",
    "metering_points": f"{API_BASE}/metering-points",
    "invoices": f"{API_BASE}/invoices",
    "balances": f"{API_BASE}/balances",
    "contracts": f"{API_BASE}/contracts",
    "payments": f"{API_BASE}/payments",
    "self_readings": f"{API_BASE}/self-readings",
}

DIRECTOR_FIXTURI = RADACINA / "tests" / "fixtures"


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


def desfa(raspuns: Any) -> Any:
    """Scoate conținutul din învelișul {data, status, success} al API-ului."""
    if isinstance(raspuns, dict) and "data" in raspuns and {"status", "success"} & set(raspuns):
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


async def ia_tot(sesiune: aiohttp.ClientSession, token: str, prefix: str) -> None:
    anteturi = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    for nume, url in ENDPOINTURI_GET.items():
        try:
            async with sesiune.get(url, headers=anteturi) as raspuns:
                if raspuns.status != 200:
                    print(f"  · {nume}: HTTP {raspuns.status} (se ignoră)")
                    continue
                scrie_fixtura(f"{prefix}_{nume}", await raspuns.json())
        except (aiohttp.ClientError, asyncio.TimeoutError) as eroare:
            print(f"  · {nume}: eroare de rețea ({eroare})")


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
            id_cont = cont.get("id") or cont.get("_id")
            if not id_cont:
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
            await ia_tot(sesiune, token, f"asociat{index + 1}")

        print("4. Verificarea ipotezei din specificație (§3.3)…")
        token_doi, _ = await login(sesiune, email, parola)
        print(f"   al doilea login întoarce un token distinct: {'DA' if token_doi != token else 'NU'}")
        print(
            "   → dacă DA, fiecare cont poate avea propria sesiune și coordinatoarele\n"
            "     pot rula în paralel; dacă NU, se trece pe varianta cu asyncio.Lock."
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

    print("\nGata. Verifică manual fixturile din tests/fixtures/ înainte de commit.")


if __name__ == "__main__":
    asyncio.run(principal())
