"""Funcțiile pure: formatare românească, parsare, normalizare conturi."""

import pytest

from custom_components.novaenergy.helpers import (
    build_account_options,
    desfa_invelis,
    extrage_lista,
    extract_accounts,
    format_date_ro,
    format_number_ro,
    format_ron,
    mask_email,
    normalize_address,
    prima_valoare,
    resolve_selection,
    utility_slug,
)


@pytest.mark.parametrize(
    ("intrare", "asteptat"),
    [
        (1234.5, "1.234,50 lei"),
        (0, "0,00 lei"),
        (125.5, "125,50 lei"),
        (1000000, "1.000.000,00 lei"),
        ("98.2", "98,20 lei"),
        (None, "—"),
        ("text", "—"),
    ],
)
def test_format_ron(intrare, asteptat):
    assert format_ron(intrare) == asteptat


@pytest.mark.parametrize(
    ("intrare", "asteptat"),
    [
        (150, "150,00"),
        (1234.567, "1.234,57"),
        ("89.1", "89,10"),
        (-45.5, "-45,50"),
    ],
)
def test_format_number_ro(intrare, asteptat):
    assert format_number_ro(intrare) == asteptat


def test_format_number_ro_fara_zecimale():
    assert format_number_ro(6030, zecimale=0) == "6.030"


def test_format_date_ro():
    assert format_date_ro("2026-04-15T00:00:00.000Z") == "15.04.2026"
    assert format_date_ro("2026-04-15") == "15.04.2026"
    assert format_date_ro(None) == "—"
    assert format_date_ro("text invalid") == "—"


@pytest.mark.parametrize(
    ("intrare", "asteptat"),
    [
        ("alin@exemplu.ro", "a***@exemplu.ro"),
        ("a@exemplu.ro", "*@exemplu.ro"),
        ("", "***"),
        ("fara-arond", "***"),
    ],
)
def test_mask_email(intrare, asteptat):
    assert mask_email(intrare) == asteptat


def test_utility_slug():
    assert utility_slug("gas") == "gaz"
    assert utility_slug("electricity") == "electricitate"
    assert utility_slug("necunoscut") == "necunoscut"


def test_prima_valoare_alege_prima_cheie_prezenta():
    """API-ul poate denumi același câmp în mai multe feluri; codul nu trebuie
    să se rupă la prima variație."""
    assert prima_valoare({"totalBalance": 10}, "total", "totalBalance") == 10
    assert prima_valoare({"total": 5, "totalBalance": 10}, "total", "totalBalance") == 5
    assert prima_valoare({}, "total", implicit=0) == 0
    assert prima_valoare({"total": None}, "total", implicit=7) == 7


def test_normalize_address():
    adresa = normalize_address(
        {"street": "Strada Florilor 15", "city": "Iași", "county": "Iași"}
    )
    assert "Strada Florilor 15" in adresa
    assert "Iași" in adresa
    assert normalize_address(None) == "—"
    assert normalize_address({}) == "—"


def test_extract_accounts_pe_fixtura_reala(fixtura):
    """Contul real are un singur cont, fără conturi asociate."""
    conturi = extract_accounts(fixtura("login"))
    assert len(conturi) == 1
    assert all({"id", "crm", "nume", "adresa"} <= set(cont) for cont in conturi)
    # CRM-urile trebuie să fie unice, altfel device-urile se suprapun.
    assert len({cont["crm"] for cont in conturi}) == len(conturi)


def test_extract_accounts_fara_duplicate_cand_principalul_e_si_asociat(fixtura):
    """Contul curent apare și în lista de conturi asociate."""
    payload = fixtura("login_multicont")
    conturi = extract_accounts(payload)
    id_uri = [cont["id"] for cont in conturi]
    assert len(id_uri) == len(set(id_uri))


def test_build_account_options(fixtura):
    optiuni = build_account_options(extract_accounts(fixtura("login_multicont")))
    assert len(optiuni) == 2
    assert all("value" in optiune and "label" in optiune for optiune in optiuni)
    # Eticheta ajută utilizatorul să recunoască contul: adresă + CRM.
    assert any("3047398" in optiune["label"] for optiune in optiuni)


def test_resolve_selection_cu_toate_bifate(fixtura):
    conturi = extract_accounts(fixtura("login_multicont"))
    rezultat = resolve_selection([], conturi, toate_bifate=True)
    assert set(rezultat) == {cont["crm"] for cont in conturi}


def test_resolve_selection_pastreaza_selectia_explicita(fixtura):
    conturi = extract_accounts(fixtura("login_multicont"))
    ales = conturi[0]["crm"]
    assert resolve_selection([ales], conturi, toate_bifate=False) == [ales]


def test_resolve_selection_ignora_conturi_inexistente(fixtura):
    conturi = extract_accounts(fixtura("login_multicont"))
    assert resolve_selection(["CRM-INVENTAT"], conturi, toate_bifate=False) == []


def test_desfa_invelisul_real(fixtura):
    """Autentificarea vine ca {data, status, success}."""
    continut = desfa_invelis(fixtura("login"))
    assert "session" in continut
    assert "loggedInAccount" in continut


def test_desfa_lasa_neatins_ce_nu_e_invelit():
    assert desfa_invelis({"docs": [1, 2]}) == {"docs": [1, 2]}
    assert desfa_invelis([1, 2]) == [1, 2]


def test_extrage_lista_din_raspuns_paginat(fixtura):
    """Endpoint-urile de listă întorc {docs: [...]} cu paginare."""
    assert extrage_lista(fixtura("principal_balances")) == [
        {"balance": 0, "prosumerBalance": 0}
    ]


def test_extrage_lista_din_raspuns_gol(fixtura):
    """`/invoices` întoarce un obiect gol când nu există facturi."""
    assert extrage_lista(fixtura("principal_invoices")) == []


def test_adresa_vine_ca_sir_de_caractere():
    assert normalize_address("Strada Florilor 15, Iași") == "Strada Florilor 15, Iași"
    assert normalize_address("   ") == "—"


def test_conturi_cu_acelasi_cod_crm_primesc_coduri_distincte():
    """Codul CRM e numărul de client, nu identificatorul contului: două conturi
    îl pot împărți. Fără dezambiguizare, unul ar dispărea în tăcere."""
    payload = {
        "data": {
            "loggedInAccount": {
                "accountId": "id-unu",
                "accountNumber": "3047398",
                "accountName": "A",
                "associatedAccounts": [
                    {"accountId": "id-unu", "accountNumber": "3047398", "accountName": "A"},
                    {"accountId": "id-doi", "accountNumber": "3047398", "accountName": "B"},
                ],
            }
        }
    }
    conturi = extract_accounts(payload)
    assert len(conturi) == 2
    coduri = {cont["crm"] for cont in conturi}
    assert len(coduri) == 2, f"coduri CRM suprapuse: {coduri}"
    assert all(cod.startswith("3047398") for cod in coduri)


def test_codurile_unice_raman_neatinse():
    payload = {
        "data": {
            "loggedInAccount": {
                "accountId": "id-unu",
                "accountNumber": "3047398",
                "associatedAccounts": [
                    {"accountId": "id-doi", "accountNumber": "3008726"},
                ],
            }
        }
    }
    assert {c["crm"] for c in extract_accounts(payload)} == {"3047398", "3008726"}


def test_datele_sunt_intotdeauna_fara_fus_orar():
    """Amestecul de date cu și fără fus orar face max() să arunce TypeError."""
    from custom_components.novaenergy.helpers import parse_api_date

    cu_fus = parse_api_date("2026-08-28T00:00:00.000Z")
    fara_fus = parse_api_date("28.08.2026")
    assert cu_fus.tzinfo is None
    assert fara_fus.tzinfo is None
    # Trebuie să poată fi comparate între ele fără excepție.
    assert max(cu_fus, fara_fus) is not None
