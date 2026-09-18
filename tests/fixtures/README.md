# Fixturi de test

## Forma reală a API-ului

`login.json` și `principal_*.json` reproduc **forma reală** a răspunsurilor,
confirmată rulând `scripts/explorare_api.py` pe un cont adevărat. Valorile sunt
înlocuite cu date de exemplu; structura este cea autentică:

- autentificarea vine învelită: `{data: {session, loggedInAccount, viewedAccount}, status, success}`,
  cu tokenul la `data.session.token`;
- endpoint-urile de listă răspund paginat: `{docs: [...], page, limit, totalDocs, …}`;
- `/balances` e tot o listă paginată, dar cu un singur element: `{balance, prosumerBalance}`;
- `/globals/app-info/general` vine învelit în `{data: …}`;
- un endpoint fără date poate întoarce `{}` gol (așa face `/invoices`);
- `totalDocs` **nu** e de încredere — poate fi `0` deși `docs` are elemente;
- utilitatea se numește `utilityType`, iar pe contracte `type` înseamnă tipul de
  client („Casnic"), nu utilitatea;
- datele calendaristice vin ca `28.08.2026`, nu în format ISO;
- starea contractului e în română: `"Activ"`.

Contul folosit la confirmare avea un singur contract (electricitate), fără
contoare, facturi sau plăți — de aceea aceste fixturi nu acoperă singure toate
ramurile.

## Date inventate (aceeași formă)

`login_multicont.json`, `contA_*.json` și `contB_*.json` sunt **construite**, nu
reale, cu `scripts/genereaza_fixturi_sintetice.py`. Ele acoperă ce contul real nu
are: două conturi asociate, gaz, contoare cu index, facturi, plăți și un contract
de prosumator.

| Fixtură | Conține |
|---|---|
| `contA_*` | gaz: contor, 3 facturi (2 din anul curent, neachitate), o plată |
| `contB_*` | gaz + electricitate, prosumator pe electricitate |

Câmpurile facturilor, plăților și contoarelor din aceste fixturi sunt **o ipoteză
informată**: contul real nu a returnat niciun exemplar, așa că numele exacte nu
au fost confirmate. Codul citește fiecare câmp prin `prima_valoare()`, cu mai
multe denumiri acceptate, tocmai ca o nepotrivire să nu rupă senzorul. Ele se
confirmă la prima rulare pe un cont care are facturi.

## Regenerare

```bash
NOVA_ENV_FILE=/cale/catre/.env python3 scripts/explorare_api.py   # din contul tău
python3 scripts/genereaza_fixturi_sintetice.py                    # cele inventate
```

Scriptul de explorare trece fiecare răspuns prin `scripts/anonimizare.py`, care
ascunde implicit orice câmp text pe care nu îl cunoaște ca sigur, și refuză să
lase fixturi care conțin adresa de email folosită la autentificare. Fixturile
din repo nu conțin date dintr-un cont real.
