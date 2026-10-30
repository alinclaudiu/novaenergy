"""Fixturi sintetice, în forma REALĂ a API-ului Nova (confirmată prin explorare).

Contul folosit la explorare are o singură utilitate (electricitate, prosumator),
așa că aceste date inventate acoperă restul: mai multe conturi, gaz, facturi
neachitate, mai multe contoare și istoric de citiri. Vezi tests/fixtures/README.md."""
import json, sys
from pathlib import Path
RAD = Path(__file__).parent.parent
sys.path.insert(0, str(RAD))
FIX = RAD / "tests" / "fixtures"

def paginat(docs):
    """Învelișul de paginare al contractelor, singura listă paginată."""
    return {"docs": docs, "hasNextPage": False, "hasPrevPage": False, "limit": 100,
            "nextPage": None, "page": 1, "pagingCounter": 1, "prevPage": None,
            "totalDocs": 0, "totalPages": 1}

def in_data(**campuri):
    """Învelișul `{data: {...}}` al celorlalte endpoint-uri."""
    return {"data": campuri}

def sold(total=0, gaz=0, electricitate=0, prosumator=0, este_prosumator=False, de_plata=0):
    return in_data(total=total, electricity=electricitate, gas=gaz, prosumer=prosumator,
                   prosumerDue=0, processingPayments=0, hasProcessingPayment=False,
                   pendingInvoicesCount=de_plata, perMeteringPoint={},
                   isProsumer=este_prosumator)

def contract(id_, numar, utilitate, semnat, in_vigoare):
    return {"contractId": id_, "number": numar, "status": "Activ", "type": "Casnic",
            "tipAct": 1, "utilityType": utilitate, "signedAt": semnat,
            "inForceAt": in_vigoare, "invoiceDeliveryType": "Doar electronic"}

def punct(id_, numar, cod, contract_id, utilitate, adresa):
    return {"meteringPointId": id_, "number": numar, "specificIdForUtilityType": cod,
            "address": adresa, "contractId": contract_id, "contractType": "individual",
            "utilityType": utilitate, "gasRevisions": None}

def factura(id_, emisa, scadenta, total, de_plata, stare, utilitate, tip="Supply"):
    return {"invoiceId": id_, "utilityType": utilitate, "balanceType": tip,
            "amountToPay": de_plata, "amountTotal": f"{total:.2f}",
            "amountRemaining": de_plata, "dueDate": scadenta, "issueDate": emisa,
            "status": stare, "pdfInvoiceStatus": True,
            "meteringPointAddress": "Strada Florilor 15, Iași",
            "meteringPointNumber": "LC-00000011", "meteringPointCode": "CLC123456",
            "meteringPoints": [{"utilityType": utilitate, "address": "Strada Florilor 15, Iași",
                                "amountTotal": total, "amountToPay": de_plata}]}

def contoare(*elemente):
    """Răspunsul rutei de contoare pentru fiecare loc de consum, după număr."""
    return {numar: {"message": "Meters retrieved successfully", "data": {"meters": [
        {"meterPointNumber": numar, "series": serie, "currentIndex": index,
         "meterCode": f"COD-{serie}", "unit": unitate, "dialCode": cadran}
        for (numar_contor, serie, index, unitate, cadran) in elemente if numar_contor == numar
    ]}} for numar in dict.fromkeys(element[0] for element in elemente)}

def citire(serie, perioada, vechi, nou, unitate, utilitate, cadran):
    zi, luna, an = perioada.split(".")
    return {"period": perioada, "periodStart": f"{an}-{luna}-{zi}", "periodEnd": f"{an}-{luna}-{zi}",
            "oldIndex": vechi, "newIndex": nou, "consumption": round(nou - vechi, 3),
            "unit": unitate, "meteringPointNo": "LC-00000011", "meteringPointCode": "CLC123456",
            "meterSeries": serie, "meterCode": f"COD-{serie}", "readingType": "Reading",
            "oldIndexReadingType": "Invoiced", "newIndexReadingType": "Reading",
            "distributorName": "", "constant": 1, "utilityType": utilitate, "dialCode": cadran}

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

  # Cont A: gaz, cu două facturi de plată (una restantă), o plată și istoric de citiri.
  "contA_balance": sold(total=223.70, gaz=223.70, de_plata=2),
  "contA_contracts": paginat([
    contract("ctr-a1", "NV-12345", "gas", "15.01.2024", "01.02.2024"),
  ]),
  "contA_metering_points": in_data(meteringPoints=[
    punct("mp-a1", "LC-00000011", "CLC123456", "ctr-a1", "gas", "Strada Florilor 15, Iași"),
  ]),
  "contA_invoices": in_data(
    invoices=[
      factura("inv-1", "04.03.2026", "15.04.2026", 125.50, 125.50, "unpaid", "gas"),
      factura("inv-2", "15.02.2026", "15.03.2026", 98.20, 98.20, "pastDue", "gas"),
      factura("inv-3", "10.12.2025", "10.01.2026", 310.00, 0, "paid", "gas"),
    ],
    balance={"total": 223.70, "processingPayments": 0, "prosumer": 0, "prosumerDue": 0,
             "isProsumer": False},
    shouldPayAllBtnBeDisabled=False, clePayableDocuments=[]),
  "contA_payments": in_data(payments=[
    {"paymentId": "pay-1", "entryNo": "100001", "date": "2026-03-10", "totalAmount": "125.50",
     "invoicesIds": "inv-0", "utilityType": "gas", "meteringPointAddress": None,
     "meteringPointCode": "CLC123456", "meteringPointNumber": "LC-00000011",
     "invoiceValue": 125.50, "paidValue": 125.50, "bankReference": "000000000002"},
  ]),
  # Cea mai nouă citire e prima: ordinea din răspuns nu e cronologică.
  "contA_self_readings": in_data(
    enabled=True, intervalMessage="Puteți trimite consumul doar în intervalul calendaristic 19-26",
    selfReadings=[
      citire("GS1234567", "01.03.2026", 5885, 6030, "m³", "gas", "ZZGN"),
      citire("GS1234567", "01.02.2026", 5765, 5885, "m³", "gas", "ZZGN"),
    ]),

  # Indexul facturat rămâne în urma ultimei citiri: factura vine după citire.
  "contA_meters": contoare(("LC-00000011", "GS1234567", 5885, "M3", "ZZGN")),

  # Cont B: gaz + electricitate, prosumator, ca să acopere ambele ramuri.
  "contB_balance": sold(prosumator=45.30, este_prosumator=True),
  "contB_contracts": paginat([
    contract("ctr-b1", "NV-22222", "gas", "01.06.2023", "01.07.2023"),
    contract("ctr-b2", "NV-33333", "electricity", "01.06.2023", "01.07.2023"),
  ]),
  "contB_metering_points": in_data(meteringPoints=[
    punct("mp-b1", "LC-00000022", "CLC222", "ctr-b1", "gas", "Bd. Independenței 42"),
    punct("mp-b2", "LC-00000033", "EMO333", "ctr-b2", "electricity", "Bd. Independenței 42"),
  ]),
  "contB_invoices": in_data(invoices=[], balance={}, shouldPayAllBtnBeDisabled=True,
                            clePayableDocuments=[]),
  "contB_payments": in_data(payments=[]),
  "contB_self_readings": in_data(
    enabled=True, intervalMessage="",
    selfReadings=[
      citire("GS7654321", "02.03.2026", 1140, 1200, "m³", "gas", "ZZGN"),
      citire("EL9999999", "02.03.2026", 44900, 45210, "kWh", "electricity", "EA"),
    ]),
  "contB_meters": contoare(
    ("LC-00000022", "GS7654321", 1140, "M3", "ZZGN"),
    ("LC-00000033", "EL9999999", 44900, "KWH", "EA"),
  ),
}

for nume, continut in date.items():
    (FIX / f"{nume}.json").write_text(
        json.dumps(continut, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
print(f"{len(date)} fixturi sintetice scrise")
