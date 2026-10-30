# Ghid de depanare — Nova Energy România

---

## 1. Activează logurile detaliate

Cea mai simplă cale, fără repornire: **Setări** → **Dispozitive și Servicii** → **Nova Energy România** → ⋮ → **Activează jurnalizarea de depanare**.

Varianta din `configuration.yaml`, dacă preferi să rămână permanentă:

```yaml
logger:
  default: warning
  logs:
    custom_components.novaenergy: debug
```

După modificare, repornește Home Assistant.

Pentru și mai mult context, poți urmări separat modulele:

```yaml
logger:
  default: warning
  logs:
    custom_components.novaenergy.api: debug
    custom_components.novaenergy.coordinator: debug
    custom_components.novaenergy.sensor: debug
```

---

## 2. Unde găsești logurile

### Din interfață

**Setări** → **Sistem** → **Jurnale** → **ÎNCARCĂ JURNALUL COMPLET**, apoi caută `novaenergy`.

### Din fișier

```bash
# Calea obișnuită
cat /config/home-assistant.log

# Doar liniile integrării
grep novaenergy /config/home-assistant.log

# Doar erorile
grep -E "ERROR|WARNING" /config/home-assistant.log | grep novaenergy

# Ultimele 100 de linii, în timp real
tail -f -n 100 /config/home-assistant.log | grep novaenergy
```

### Din terminal

```bash
# Docker
docker logs -f homeassistant 2>&1 | grep novaenergy

# Home Assistant OS, prin add-on-ul SSH
ha core logs --follow | grep novaenergy
```

---

## 3. Ce vezi la o pornire normală

```
DEBUG Autentificare pentru a***@exemplu.ro
DEBUG POST .../auth/login → {data: {loggedInAccount: {accountId: text(36),
      accountName: text(18), accountNumber: text(7), associatedAccounts: null},
      preferences: {…}, session: {canImpersonate: bool, expireAt: număr,
      role: text(6), token: text(…), username: text(17)}, viewedAccount: {…}},
      status: număr, success: bool}
DEBUG Autentificare reușită pentru a***@exemplu.ro
DEBUG GET .../dashboard/balance → {data: {electricity: număr, gas: număr,
      hasProcessingPayment: bool, isProsumer: bool, pendingInvoicesCount: număr,
      perMeteringPoint: {}, processingPayments: număr, prosumer: număr,
      prosumerDue: număr, total: număr}}
DEBUG GET .../contracts → {docs: [1 × {contractId: text(36), inForceAt: text(10),
      invoiceDeliveryType: text(15), number: text(13), signedAt: text(10),
      status: text(5), tipAct: număr, type: text(6), utilityType: text(11)}], …}
DEBUG GET .../self-readings → {data: {enabled: bool, intervalMessage: text(62),
      selfReadings: [1 × {consumption: număr, dialCode: text(2), meterSeries: text(16),
      newIndex: număr, period: text(10), unit: text(3), utilityType: text(11), …}]}}
INFO  Nova Energy pornită pentru 1 cont(uri): 3047398
```

Patru lucruri de observat:

- **În log ajunge forma răspunsului, nu conținutul lui.** `text(18)` înseamnă „un
  șir de 18 caractere", nu îți spune care. Asta e intenționat: acest ghid îți cere
  să lipești logurile într-un issue public, iar răspunsurile API conțin numele,
  adresa, telefonul, soldul și numerele tale de contract. Structura e suficientă
  pentru a diagnostica o schimbare de format — și nu spune nimic despre tine.
- Adresa de email apare **mascată** (`a***@exemplu.ro`) în liniile integrării.
  Liniile scrise de Home Assistant însuși despre intrarea de configurare — de
  pildă „Config entry '…' for novaenergy integration could not authenticate" —
  conțin titlul intrării, adică emailul complet: înlocuiește-l înainte de a le
  publica.
- Cererile pleacă în paralel — contoarele într-un al doilea val, după punctele
  de consum —, deci ordinea lor în log poate varia de la o
  rulare la alta.
- Pe contul principal nu apare nicio linie „Comutare pe contul…": sesiunea e
  deja pe el. Comutarea apare doar pentru conturile asociate.

---

## 4. Situații normale, care nu sunt erori

### Tokenul se reînnoiește

```
DEBUG Token expirat pentru a***@exemplu.ro, se reînnoiește
DEBUG Autentificare pentru a***@exemplu.ro
```

Tokenul are durată limitată. Integrarea îl reînnoiește singură — o singură dată pentru toate cererile care l-au găsit expirat — și continuă. Nu ai ce face.

### Un endpoint opțional nu întoarce date

```
WARNING Endpoint-ul opțional payments a eșuat pentru contul 3047398:
        HTTP 404 la https://…/payments
```

Punctele de consum, contoarele, facturile, plățile și citirile sunt opționale: dacă eșuează, senzorii care depind de ele devin `unavailable`, iar restul integrării merge mai departe. Un cont nou, fără istoric, primește liste goale, nu erori.

```
WARNING Contoarele locului de consum #1 al contului 3047398 nu au putut fi citite:
        HTTP 500 la https://…/metering-points/…/meters
```

Contoarele se cer pentru fiecare loc de consum în parte; un loc căzut lasă fără date doar senzorii de index facturat ai lui. Numărul locului de consum nu apare în log: e înlocuit cu poziția și cu „…".

### Un cont pornește mai târziu

```
WARNING Integrarea pornește fără conturile 3008726; vor fi reîncercate automat
```

Un cont a eșuat la prima actualizare, restul au reușit. Integrarea pornește cu ce are și reîncearcă la următorul ciclu.

### Un cont selectat a dispărut

```
WARNING Contul 3008726 nu mai există pe acest cont Nova și a fost ignorat
```

Contul a fost dezasociat la furnizor. Intră în **Configurare** (⚙️) și actualizează selecția.

---

## 5. Situații de eroare

### Autentificare respinsă

La pornire:

```
WARNING Config entry 'a***@exemplu.ro' for novaenergy integration could not authenticate:
        Autentificarea la Nova a eșuat: Credențiale respinse (401) la https://…/auth/login
```

În timpul funcționării:

```
ERROR Authentication failed while fetching novaenergy 3047398 data:
      Nova a respins credențialele: Credențiale respinse (401) la https://…/auth/login
```

Parola s-a schimbat sau contul e blocat. Integrarea se oprește după o singură încercare — nu mai repetă autentificarea la fiecare ciclu — iar Home Assistant afișează o notificare de **reautentificare**: introdu acolo parola nouă. Prima linie e scrisă de Home Assistant și conține emailul tău complet (aici mascat).

### Platforma nu răspunde

În timpul funcționării:

```
ERROR Error fetching novaenergy 3047398 data: Nu s-au putut obține datele esențiale
      (balance) pentru contul 3047398: Timeout la https://…/dashboard/balance
```

La pornire, Home Assistant nu scrie nimic în jurnal cu setările obișnuite: pe cardul integrării apare starea de reîncercare, cu motivul „Nova nu răspunde în acest moment: …". În jurnal motivul apare doar cu `homeassistant.config_entries: debug` la `logger:`, într-o linie care conține emailul tău complet (aici mascat):

```
DEBUG Config entry 'a***@exemplu.ro' for novaenergy integration not ready yet:
      Nova nu răspunde în acest moment: Timeout la https://…/auth/login; Retrying in 10 seconds
```

Problemă de rețea sau mentenanță la furnizor. Home Assistant reîncearcă singur; dacă durează ore întregi, verifică dacă platforma web merge din browser.

### Date esențiale lipsă

```
ERROR Error fetching novaenergy 3047398 data: Nu s-au putut obține datele esențiale
      (balance) pentru contul 3047398: HTTP 503 la https://…/dashboard/balance
```

Soldul și contractele sunt obligatorii — fără ele nu se pot construi senzorii, așa că actualizarea se oprește și se reia la ciclul următor. Punctele de consum, contoarele, facturile, plățile și citirile pot lipsi: senzorii care depind de ele devin `unavailable`, restul merg mai departe.

### Toate cererile dau 404

Cardul integrării rămâne în reîncercare cu motivul „Nova nu răspunde în acest moment: HTTP 404 la https://…/auth/login" sau, dacă integrarea pornise deja:

```
ERROR Error fetching novaenergy 3047398 data: Nu s-au putut obține datele esențiale
      (balance) pentru contul 3047398: HTTP 404 la https://…/dashboard/balance
```

Nova și-a mutat API-ul. Așa s-a întâmplat în 2026, când aplicația de client a trecut pe platforma nouă „MyAccount", iar versiunea 1.0.0 a integrării a rămas fără date. Actualizează integrarea din HACS; dacă ești deja pe ultima versiune, deschide un issue.

### Comutarea pe cont eșuează

```
ERROR Error fetching novaenergy 3008726 data: Comutarea pe contul 3008726 a eșuat:
      HTTP 403 la https://…/auth/switch-account
```

Contul nu mai e accesibil cu aceste credențiale. Scoate-l din selecție.

### Răspuns cu altă formă decât cea așteptată

```
ERROR Răspunsul de autentificare nu conține un token; chei primite: ['message', 'status']
```

Cel mai probabil furnizorul a schimbat API-ul. Deschide un issue cu această linie
din log, împreună cu liniile `DEBUG ... → {…}` care descriu forma răspunsurilor —
exact informația necesară pentru o corecție, fără valorile din răspunsuri.

---

## 6. Probleme frecvente, fără mesaj de eroare

| Simptom | Cauză probabilă | Ce faci |
|---|---|---|
| Nu apare nicio entitate | integrarea nu a terminat prima actualizare | verifică starea de pe cardul integrării; cu depanarea activată, caută în jurnal linia „Nova Energy pornită pentru…" |
| Lipsește un senzor anume | API-ul nu întoarce acel câmp pentru contul tău | normal; vezi întrebările din [FAQ.md](FAQ.md) |
| Senzorii sunt `unavailable` | ultima actualizare a eșuat | așteaptă un ciclu; caută în jurnal `Error fetching novaenergy` |
| Valorile nu se schimbă | intervalul e de 6 ore | scade-l din **Configurare**, sau folosește `homeassistant.update_entity` |
| Entity ID diferit de exemple | codul CRM și seria contorului sunt ale tale | ia ID-urile reale din **Instrumente pentru dezvoltatori** → **Stări** |

Forțarea unei actualizări imediate:

```yaml
action: homeassistant.update_entity
target:
  entity_id: sensor.novaenergy_3047398_sold_total
```

---

## 7. Raportul de diagnostic

**Setări** → **Dispozitive și Servicii** → **Nova Energy România** → **Descarcă diagnostic**.

Raportul conține starea fiecărui cont, câte facturi, plăți, contracte, puncte de consum, contoare și citiri au fost primite, și lista senzorilor activi. Adresa de email este mascată, iar parola și tokenul nu apar deloc. Conține însă numărul contului (codul CRM), iar numele senzorilor de index conțin seria contorului: înlocuiește-le înainte de a atașa raportul la un issue public, dacă nu vrei să fie vizibile.

---

## 8. Cum raportezi o problemă

Deschide un [issue](https://github.com/alinclaudiu/novaenergy/issues) cu:

1. **Ce ai făcut** și **ce te așteptai să se întâmple**
2. **Versiunea integrării** și versiunea Home Assistant
3. **Logurile relevante**, cu depanarea activată
4. **Raportul de diagnostic**, atașat

Pentru loguri, folosește un bloc de cod în issue, ca să rămână lizibile:

````markdown
```
2026-09-18 10:00:00 ERROR (MainThread) [custom_components.novaenergy...] ...
```
````

Logurile integrării sunt gândite să poată fi lipite public: emailul e mascat,
identificatorii conturilor asociate apar trunchiați, iar din răspunsurile API se
loghează doar structura. Numărul contului (codul CRM) apare însă în mesaje, iar
liniile scrise de Home Assistant despre intrarea de configurare conțin emailul
complet — înlocuiește-le înainte de a trimite, dacă nu vrei să fie vizibile. Aruncă
oricum un ochi peste loguri: alte integrări din aceeași instanță Home Assistant pot
să nu fie la fel de prudente.
