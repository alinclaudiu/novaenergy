# Fixturi de test

## Forma reală a API-ului

`login.json` și `principal_*.json` reproduc **forma reală** a răspunsurilor noului
backend (`myaccount-admin.nova-energy.ro/api/v1`), confirmată pe un cont adevărat —
cu `scripts/explorare_api.py` și, pentru ruta de contoare, cu o captură separată pe
același cont. Toate valorile sunt înlocuite cu
date de exemplu, scrise de mână; structura este cea autentică:

- autentificarea vine învelită: `{data: {session, loggedInAccount, viewedAccount, preferences}, status, success}`,
  cu tokenul la `data.session.token`;
- `/contracts` e singura listă paginată: `{docs: [...], page, limit, totalDocs, …}`;
- restul listelor vin sub o cheie proprie din `data`: `/invoices` → `data.invoices`,
  `/payments` → `data.payments`, `/metering-points` → `data.meteringPoints`,
  `/self-readings` → `data.selfReadings`; nu sunt paginate;
- `/dashboard/balance` e un singur obiect: `{data: {total, prosumer, isProsumer, …}}`;
- `/metering-points/{number}/meters` cere **numărul** locului de consum, nu
  `meteringPointId`, și răspunde `{message, data: {meters: [{series, dialCode,
  currentIndex, meterCode, unit, meterPointNumber}]}}`, cu unitatea în majuscule
  (`"KWH"`); fixturile `*_meters.json` țin acest răspuns sub numărul fiecărui loc
  de consum;
- unele rute răspund `{message, data}` în loc de `{data}`;
- `totalDocs` **nu** e de încredere — poate fi `0` deși `docs` are elemente;
- utilitatea se numește `utilityType`, iar pe contracte `type` înseamnă tipul de
  client („Casnic"), nu utilitatea;
- datele calendaristice vin amestecat: `12.06.2026` pe contracte și facturi,
  `2026-09-25` pe plăți și pe capetele perioadelor de citire;
- `amountTotal` (la facturi) și `totalAmount` (la plăți) vin ca **text** (`"12.34"`),
  restul sumelor ca numere;
- starea contractului e în română (`"Activ"`), cea a facturii în engleză (`"paid"`);
- surplusul de prosumator vine ca factură separată, cu `balanceType: "Prosumer Surplus"`
  și valoare negativă;
- `isProsumer` e `true` în `/dashboard/balance`, dar `false` în `data.balance` din
  `/invoices`, pe același cont — de aceea integrarea îl citește doar pe primul.

Contul folosit la confirmare are o singură utilitate (electricitate, prosumator),
fără conturi asociate, fără gaz și fără facturi neachitate.

## Date inventate (aceeași formă)

`login_multicont.json`, `contA_*.json` și `contB_*.json` sunt **construite**, nu
reale, cu `scripts/genereaza_fixturi_sintetice.py`. Ele acoperă ce contul real nu
are: două conturi asociate, gaz, facturi neachitate și restante, mai multe citiri
pentru același contor.

| Fixtură | Conține |
|---|---|
| `contA_*` | gaz: 3 facturi (una `unpaid`, una `pastDue`, una `paid` din anul trecut), o plată, două citiri ale aceluiași contor, în ordine necronologică |
| `contB_*` | gaz + electricitate, prosumator |

Stările facturilor (`paid`, `unpaid`, `pastDue`, `inProcessing`, `reversed`) și
codurile de cadran (`EA`, `EAZ`, `EAN`, `ZZGN`) vin din aplicația oficială Nova.

## Regenerare

```bash
NOVA_ENV_FILE=/cale/catre/.env python3 scripts/explorare_api.py   # forma, din contul tău
python3 scripts/genereaza_fixturi_sintetice.py                    # cele inventate
```

Scriptul de explorare scrie în `.explorare/`, un director ignorat de git — niciodată
peste fixturile de aici. Trece fiecare răspuns prin `scripts/anonimizare.py`, care
ascunde identificatorii și refuză un rezultat ce conține adresa de email folosită
la autentificare, dar lasă să treacă sumele, indexurile și datele: rezultatul
confirmă forma, nu e bun de publicat. Fixturile `login.json` și `principal_*.json`
se actualizează apoi de mână, în forma confirmată, cu valori de exemplu. Fixturile
din repo nu conțin date dintr-un cont real.
