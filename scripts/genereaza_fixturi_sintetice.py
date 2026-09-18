"""Fixturi sintetice, în forma REALĂ a API-ului Nova (confirmată prin explorare).

Contul folosit la explorare are un singur contract și nicio factură, așa că aceste
date inventate acoperă restul: mai multe conturi, gaz, contoare, facturi, plăți
și un contract de prosumator. Vezi tests/fixtures/README.md."""
import json, sys
from pathlib import Path
RAD = Path(__file__).parent.parent
sys.path.insert(0, str(RAD))
FIX = RAD / "tests" / "fixtures"

def paginat(docs):
    """Învelișul de paginare folosit de toate endpoint-urile de listă."""
    return {"docs": docs, "hasNextPage": False, "hasPrevPage": False, "limit": 10,
            "nextPage": None, "page": 1, "pagingCounter": 1, "prevPage": None,
            "totalDocs": 0, "totalPages": 1}

cont_a = {"accountId": "id-cont-a", "accountNumber": "3047398", "accountName": "POPESCU ION",
          "address": "Strada Florilor 15, Iași", "email": "ion@exemplu.ro",
          "phone": "0700000000", "role": "client"}
cont_b = {"accountId": "id-cont-b", "accountNumber": "3008726", "accountName": "POPESCU MARIA",
          "address": "Bulevardul Independenței 42, Iași", "email": "maria@exemplu.ro",
          "phone": "0700000001", "role": "client"}

date = {
  # Autentificare cu două conturi asociate — contul real nu are niciunul.
  "login_multicont": {
    "data": {
      "session": {"token": "token-secret", "role": "client",
                  "username": "ion@exemplu.ro", "expireAt": 1792307286},
      "loggedInAccount": {"accountId": "id-cont-a", "accountNumber": "3047398",
                          "accountName": "POPESCU ION",
                          "associatedAccounts": [cont_a, cont_b]},
      "viewedAccount": cont_a,
    }, "status": 200, "success": True},

  # Cont A: gaz, cu contor, facturi și plăți.
  "contA_balances": paginat([{"balance": 223.70, "prosumerBalance": 0}]),
  "contA_contracts": paginat([
    {"contractId": "ctr-a1", "number": "NV-12345", "status": "Activ", "type": "Casnic",
     "tipAct": 1, "utilityType": "gas", "signedAt": "15.01.2024", "inForceAt": "01.02.2024",
     "invoiceDeliveryType": "Doar electronic", "prosumerCertificate": "", "prosumerContract": ""},
  ]),
  "contA_metering_points": paginat([
    {"meteringPointId": "mp-a1", "number": "POD0001", "address": "Strada Florilor 15, Iași",
     "contractId": "ctr-a1", "contractType": "individual", "utilityType": "gas",
     "specificIdForUtilityType": "CLC123456",
     "meters": [{"meterId": "mt-a1", "series": "GS1234567", "lastIndex": 6030,
                 "lastReadingDate": "01.03.2026", "consumption": 145, "unit": "m³"}]},
  ]),
  "contA_invoices": paginat([
    {"invoiceId": "inv-1", "number": "NV-0001", "issueDate": "04.03.2026",
     "dueDate": "15.04.2026", "amount": 125.50, "remainingAmount": 125.50,
     "paid": False, "utilityType": "gas"},
    {"invoiceId": "inv-2", "number": "NV-0002", "issueDate": "15.02.2026",
     "dueDate": "15.03.2026", "amount": 98.20, "remainingAmount": 98.20,
     "paid": False, "utilityType": "gas"},
    {"invoiceId": "inv-3", "number": "NV-0003", "issueDate": "10.12.2025",
     "dueDate": "10.01.2026", "amount": 310.00, "remainingAmount": 0,
     "paid": True, "utilityType": "gas"},
  ]),
  "contA_payments": paginat([
    {"paymentId": "pay-1", "paymentDate": "10.03.2026", "amount": 125.50, "utilityType": "gas"},
  ]),
  "contA_self_readings": paginat([]),
  "contA_app_info": {"data": {"selfReadingsEnabled": True, "name": "Nova",
                              "selfReadingIntervalMessage": "Trimite indexul între 1 și 10",
                              "announcements": []}},

  # Cont B: gaz + electricitate, prosumator, ca să acopere ambele ramuri.
  "contB_balances": paginat([{"balance": 0, "prosumerBalance": 45.30}]),
  "contB_contracts": paginat([
    {"contractId": "ctr-b1", "number": "NV-22222", "status": "Activ", "type": "Casnic",
     "tipAct": 1, "utilityType": "gas", "signedAt": "01.06.2023", "inForceAt": "01.07.2023",
     "invoiceDeliveryType": "Doar electronic", "prosumerCertificate": "", "prosumerContract": ""},
    {"contractId": "ctr-b2", "number": "NV-33333", "status": "Activ", "type": "Casnic",
     "tipAct": 1, "utilityType": "electricity", "signedAt": "01.06.2023", "inForceAt": "01.07.2023",
     "invoiceDeliveryType": "Doar electronic",
     "prosumerCertificate": "CERT-999", "prosumerContract": "PROS-999"},
  ]),
  "contB_metering_points": paginat([
    {"meteringPointId": "mp-b1", "number": "POD0002", "address": "Bd. Independenței 42",
     "contractId": "ctr-b1", "contractType": "individual", "utilityType": "gas",
     "specificIdForUtilityType": "CLC222",
     "meters": [{"meterId": "mt-b1", "series": "GS7654321", "lastIndex": 1200,
                 "lastReadingDate": "02.03.2026", "consumption": 60, "unit": "m³"}]},
    {"meteringPointId": "mp-b2", "number": "POD0003", "address": "Bd. Independenței 42",
     "contractId": "ctr-b2", "contractType": "individual", "utilityType": "electricity",
     "specificIdForUtilityType": "POD333",
     "meters": [{"meterId": "mt-b2", "series": "EL9999999", "lastIndex": 45210,
                 "lastReadingDate": "02.03.2026", "consumption": 310, "unit": "kWh"}]},
  ]),
  "contB_invoices": paginat([]),
  "contB_payments": paginat([]),
  "contB_self_readings": paginat([]),
  "contB_app_info": {"data": {"selfReadingsEnabled": True, "name": "Nova",
                              "selfReadingIntervalMessage": "", "announcements": []}},
}

for nume, continut in date.items():
    (FIX / f"{nume}.json").write_text(
        json.dumps(continut, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
print(f"{len(date)} fixturi sintetice scrise")
