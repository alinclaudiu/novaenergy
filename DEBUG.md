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
INFO  Setting up novaenergy
DEBUG Autentificare pentru a***@exemplu.ro
DEBUG POST .../accounts/login/client → {data: {loggedInAccount: {accountId: text(36),
      accountName: text(18), accountNumber: text(9), associatedAccounts: null},
      session: {expireAt: număr, role: text(6), token: text(212), username: text(17)},
      viewedAccount: {…}}, status: număr, success: bool}
DEBUG Autentificare reușită pentru a***@exemplu.ro
DEBUG Comutare pe contul 3047398
DEBUG GET .../balances → {docs: [1 × {balance: număr, prosumerBalance: număr}],
      hasNextPage: bool, limit: număr, page: număr, totalDocs: număr, totalPages: număr}
DEBUG GET .../contracts → {docs: [1 × {contractId: text(36), inForceAt: text(10),
      invoiceDeliveryType: text(15), number: text(9), signedAt: text(10),
      status: text(5), tipAct: număr, type: text(6), utilityType: text(11)}], …}
INFO  Nova Energy pornită pentru 1 cont(uri): 3047398
```

Trei lucruri de observat:

- **În log ajunge forma răspunsului, nu conținutul lui.** `text(18)` înseamnă „un
  șir de 18 caractere", nu îți spune care. Asta e intenționat: acest ghid îți cere
  să lipești logurile într-un issue public, iar răspunsurile API conțin numele,
  adresa, telefonul, soldul și numerele tale de contract. Structura e suficientă
  pentru a diagnostica o schimbare de format — și nu spune nimic despre tine.
- Adresa de email apare **mascată** (`a***@exemplu.ro`).
- Cererile pleacă în același val, deci ordinea lor în log poate varia de la o
  rulare la alta.

---

## 4. Situații normale, care nu sunt erori

### Tokenul se reînnoiește

```
DEBUG Token expirat pentru a***@exemplu.ro, se reînnoiește
DEBUG Autentificare pentru a***@exemplu.ro
```

Tokenul are durată limitată. Integrarea îl reînnoiește singură, o singură dată per cerere, și continuă. Nu ai ce face.

### Un endpoint opțional nu întoarce date

```
WARNING Endpoint-ul opțional payments a eșuat pentru contul 3047398: HTTP 404
```

Facturile, plățile și informațiile despre aplicație sunt opționale: dacă lipsesc, senzorii lor rămân goi, iar restul integrării merge mai departe. E normal pe un cont nou, fără istoric.

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

```
ERROR Autentificarea la Nova a eșuat: Acces respins (401)
```

Parola s-a schimbat sau contul e blocat. Verifică pe platforma web, apoi actualizează credențialele reconfigurând integrarea.

### Platforma nu răspunde

```
ERROR Nova nu răspunde în acest moment: Timeout la https://backend.nova-energy.ro/api/...
```

Problemă de rețea sau mentenanță la furnizor. Home Assistant reîncearcă singur; dacă durează ore întregi, verifică dacă platforma web merge din browser.

### Date esențiale lipsă

```
ERROR Nu s-au putut obține datele esențiale (balances) pentru contul 3047398
```

Soldul, contractele și punctele de măsurare sunt obligatorii — fără ele nu se pot construi senzorii, așa că actualizarea se oprește și se reia la ciclul următor.

### Comutarea pe cont eșuează

```
ERROR Comutarea pe contul 3008726 a eșuat: HTTP 403
```

Contul nu mai e accesibil cu aceste credențiale. Scoate-l din selecție.

### Răspuns cu altă formă decât cea așteptată

```
ERROR Răspunsul de autentificare nu conține un token; chei primite: ['message', 'status']
```

Cel mai probabil furnizorul a schimbat API-ul. Deschide un issue cu această linie
din log, împreună cu liniile `DEBUG ... → {…}` care descriu forma răspunsurilor —
exact informația necesară pentru o corecție, fără nimic personal în ea.

---

## 6. Probleme frecvente, fără mesaj de eroare

| Simptom | Cauză probabilă | Ce faci |
|---|---|---|
| Nu apare nicio entitate | integrarea nu a terminat prima actualizare | verifică jurnalul; caută linia „Nova Energy pornită pentru…" |
| Lipsește un senzor anume | API-ul nu întoarce acel câmp pentru contul tău | normal; vezi întrebările din [FAQ.md](FAQ.md) |
| Senzorii sunt `unavailable` | ultima actualizare a eșuat | așteaptă un ciclu; verifică logurile pentru `UpdateFailed` |
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

Raportul conține starea fiecărui cont, câte facturi, plăți, contracte și puncte de măsurare au fost primite, și lista senzorilor activi. Adresa de email este mascată, iar parola și tokenul nu apar deloc — îl poți atașa în siguranță la un issue public.

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

Logurile integrării sunt gândite să poată fi lipite public: emailul e mascat, iar
din răspunsurile API se loghează doar structura. Aruncă totuși un ochi peste ele
înainte de a trimite — alte integrări din aceeași instanță Home Assistant pot să
nu fie la fel de prudente.
