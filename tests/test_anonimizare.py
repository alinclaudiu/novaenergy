"""Anonimizatorul: politică de tip „permite doar ce e sigur"."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.anonimizare import anonimizeaza, contine_text


def test_ascunde_campurile_de_identitate():
    brut = {
        "email": "alin@exemplu.ro",
        "crmCode": "3047398",
        "firstName": "Alin",
        "address": {"street": "Str. Florilor 15", "city": "Iași"},
        "meters": [{"series": "GS1234567"}],
        "amount": 125.5,
    }
    curat = anonimizeaza(brut)

    assert curat["email"] == "utilizator@exemplu.test"
    assert curat["crmCode"] != "3047398"
    assert curat["firstName"] != "Alin"
    assert curat["address"]["street"] != "Str. Florilor 15"
    assert curat["meters"][0]["series"] != "GS1234567"
    assert curat["amount"] == 125.5


def test_ascunde_si_campurile_pe_care_nu_le_cunoaste():
    """Regresie: `accountName` și `username` s-au scurs cândva în fixturi."""
    brut = {
        "accountName": "POPESCU ION-MARIN",
        "accountId": "74f6c941-52a0-f111-b8db-7ced8d8ef5e4",
        "username": "ion@exemplu.ro",
        "camp_inventat_maine": "date personale viitoare",
    }
    curat = anonimizeaza(brut)

    assert "POPESCU" not in str(curat)
    assert "74f6c941" not in str(curat)
    assert "ion@exemplu.ro" not in str(curat)
    assert "date personale viitoare" not in str(curat)


def test_pastreaza_valorile_de_business():
    brut = {
        "totalBalance": 223.7,
        "paid": False,
        "status": "active",
        "utility": "gas",
        "unit": "m³",
        "currency": "RON",
        "clientType": "Casnic",
        "issueDate": "2026-03-04T00:00:00.000Z",
        "dueDate": "2026-04-15",
        "lastIndex": 6030,
        "prosumerBalance": None,
    }
    assert anonimizeaza(brut) == brut


def test_numerele_trimise_ca_text_trec():
    curat = anonimizeaza({"amount": "125.50", "lastIndex": "6030"})
    assert curat["amount"] == "125.50"
    assert curat["lastIndex"] == "6030"


def test_dar_un_text_nenumeric_pe_cheie_numerica_e_ascuns():
    curat = anonimizeaza({"amount": "NV-0001-SERIE-FACTURA"})
    assert "SERIE" not in str(curat)


def test_secretele_dispar_complet():
    curat = anonimizeaza({"data": {"session": {"token": "ey.secret", "role": "client"}}})
    assert "ey.secret" not in str(curat)
    assert curat["data"]["session"]["token"] == "REDACTAT"
    assert curat["data"]["session"]["role"] == "client"


def test_orice_email_devine_surogat_indiferent_de_cheie():
    curat = anonimizeaza({"camp_necunoscut": "cineva@undeva.ro"})
    assert curat["camp_necunoscut"] == "utilizator@exemplu.test"


def test_determinist_intre_apeluri():
    assert anonimizeaza({"crmCode": "3047398"}) == anonimizeaza({"crmCode": "3047398"})


def test_chei_diferite_dau_surogate_diferite():
    """Altfel două câmpuri distincte s-ar confunda între ele în fixturi."""
    curat = anonimizeaza({"accountId": "X", "contractNumber": "X"})
    assert curat["accountId"] != curat["contractNumber"]


def test_nu_modifica_originalul():
    brut = {"firstName": "Alin"}
    anonimizeaza(brut)
    assert brut["firstName"] == "Alin"


def test_plasa_de_siguranta():
    assert contine_text({"a": {"b": "POPESCU"}}, "popescu") is True
    assert contine_text({"a": "altceva"}, "popescu") is False
    assert contine_text({"a": "x"}, "") is False


def test_sirurile_goale_raman_goale():
    """Un câmp necompletat trebuie să rămână recognoscibil ca necompletat."""
    curat = anonimizeaza({"prosumerContract": "", "prosumerCertificate": "   "})
    assert curat["prosumerContract"] == ""
    assert curat["prosumerCertificate"].strip() == ""


def test_surogatele_nu_sunt_hash_uri_nesarate():
    """Un număr de cont are șapte cifre: un hash nesărat ar fi spart imediat."""
    import hashlib

    from scripts.anonimizare import _SARE

    valoare = "3047398"
    nesarat = "ANONIM-" + hashlib.sha256(f"crmCode:{valoare}".encode()).hexdigest()[:8]
    assert anonimizeaza({"crmCode": valoare})["crmCode"] != nesarat
    assert len(_SARE) >= 32


def test_sirurile_dintr_o_lista_sunt_ascunse():
    """Regresie: elementele simple dintr-o listă treceau neatinse."""
    curat = anonimizeaza({"phones": ["0722334455", "0733445566"]})
    assert "0722334455" not in str(curat)
    assert "0733445566" not in str(curat)
    assert len(curat["phones"]) == 2


def test_numerele_mari_fara_cheie_cunoscuta_sunt_ascunse():
    """Un CNP trimis ca număr ar fi trecut neobservat."""
    curat = anonimizeaza({"cnpNumeric": 1900101123456})
    assert "1900101123456" not in str(curat)


def test_numerele_de_business_trec_indiferent_de_marime():
    curat = anonimizeaza({"lastIndex": 1234567, "amount": 223.70, "totalDocs": 0})
    assert curat["lastIndex"] == 1234567
    assert curat["amount"] == 223.70
    assert curat["totalDocs"] == 0


def test_numerele_mici_trec():
    curat = anonimizeaza({"tipAct": 1, "limit": 10, "page": 1, "necunoscut": 42})
    assert curat == {"tipAct": 1, "limit": 10, "page": 1, "necunoscut": 42}


def test_textul_liber_nu_mai_e_pe_lista_sigura():
    """`message` putea conține un anunț personalizat, copiat verbatim."""
    curat = anonimizeaza({"message": "Bună, Ion Popescu! Factura ta e gata."})
    assert "Ion Popescu" not in str(curat)
