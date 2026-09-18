# Nova Energy România — Integrare Home Assistant

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.11%2B-41BDF5?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Licență MIT](https://img.shields.io/badge/licen%C8%9B%C4%83-MIT-green.svg)](LICENSE)
[![GitHub Release](https://img.shields.io/github/v/release/alinclaudiu/novaenergy)](https://github.com/alinclaudiu/novaenergy/releases)
[![GitHub Stars](https://img.shields.io/github/stars/alinclaudiu/novaenergy?style=flat&logo=github)](https://github.com/alinclaudiu/novaenergy/stargazers)
[![Instalări](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/alinclaudiu/novaenergy/main/statistici/shields/descarcari.json)](https://github.com/alinclaudiu/novaenergy)

Integrare custom pentru [Home Assistant](https://www.home-assistant.io/) care aduce în casă datele contului tău de la **Nova Power & Gas** — sold, facturi, plăți, contracte și indexul contoarelor — prin API-ul platformei „Vreau la Nova".

**Toate funcțiile sunt disponibile, pentru toată lumea.** Integrarea nu are chei, nu are activare și nu trimite nimic nicăieri în afară de serverele Nova.

---

## Ce face integrarea

- **Descoperire automată a conturilor** — contul principal și toate conturile asociate, găsite singure la instalare
- **Multi-cont** — fiecare cont CRM primește propria sesiune și propriul ciclu de actualizare, rulate în paralel
- **Device per utilitate** — gazul și energia electrică ale aceluiași cont devin dispozitive separate, cu senzorii lor
- **Sold** — soldul total și, unde există, soldul de prosumator
- **Facturi** — indicator de factură restantă, cu total restant și scadență, plus arhiva facturilor din anul curent
- **Plăți** — arhiva plăților din anul curent, cu total
- **Contract** — stare, număr, tip de client și datele de semnare
- **Index contor** — câte un senzor pentru fiecare contor, identificat prin serie
- **Formatare românească** — sume ca `1.234,56 lei`, date ca `15.04.2026`
- **Reconfigurare fără reinstalare** — intervalul și conturile monitorizate se schimbă din interfață
- **Diagnostic** — raport descărcabil pentru tichete de suport, cu datele personale mascate

---

## Sursa datelor

Datele vin de la backend-ul Nova Power & Gas (`backend.nova-energy.ro/api`), același folosit de aplicația web de client.

| Endpoint | Ce aduce |
|---|---|
| `/accounts/login/client` | autentificare; întoarce contul curent și conturile asociate |
| `/accounts/switch` | comută sesiunea pe un cont asociat |
| `/accounts/me` | detaliile contului curent |
| `/globals/app-info/general` | informații despre aplicație |
| `/balances` | sold total și sold de prosumator |
| `/invoices` | facturi |
| `/payments` | plăți |
| `/contracts` | contracte, per utilitate |
| `/metering-points` | puncte de măsurare, contoare și serii |

Autentificarea se face cu email și parolă. Tokenul primit este reînnoit automat când expiră, fără să fie nevoie de vreo intervenție.

> Integrarea **nu trimite** nimic către contul tău: în versiunea 1.x citește doar. Trimiterea autocitirilor este planificată separat, pentru o versiune viitoare.

---

## Instalare

### HACS (recomandat)

1. Deschide **HACS** în Home Assistant
2. Meniul ⋮ din dreapta sus → **Custom repositories**
3. Adaugă adresa `https://github.com/alinclaudiu/novaenergy`, categoria **Integration**
4. **Add** → caută „Nova Energy România" → **Install**
5. Repornește Home Assistant

### Manual

1. Copiază folderul `custom_components/novaenergy/` în `config/custom_components/`
2. Repornește Home Assistant

---

## Configurare

### Pasul 1 — credențialele

**Setări** → **Dispozitive și Servicii** → **Adaugă Integrare** → caută „**Nova Energy**".

| Câmp | Descriere | Implicit |
|---|---|---|
| Email | adresa contului Nova | — |
| Parolă | parola contului Nova | — |
| Interval actualizare | secunde între interogări | `21600` (6 ore) |

Datele se verifică pe loc, printr-o autentificare reală. Dacă parola e greșită sau serverele nu răspund, primești un mesaj clar și rămâi în formular.

### Pasul 2 — conturile

Conturile se descoperă automat și apar cu adresa și codul CRM:

```
Strada Florilor 15, Iași, jud. Iași ➜ 3047398
Bulevardul Independenței 42, Iași, jud. Iași ➜ 3008726
```

Bifează-le pe cele care te interesează, sau folosește **Selectează toate conturile**.

### Reconfigurare

**Setări** → **Dispozitive și Servicii** → **Nova Energy România** → **Configurare** (⚙️). Poți schimba intervalul și conturile monitorizate; integrarea se reîncarcă singură.

Detalii pas cu pas în [SETUP.md](SETUP.md).

---

## Entități create

Integrarea creează un **device pentru cont** și câte unul **pentru fiecare utilitate** a lui, legate ierarhic:

```
Nova Energy (3047398)                    ← soldul, care e pe cont
├── Nova Energy (3047398) Gaz
└── Nova Energy (3047398) Energie Electrică
```

Separarea urmează datele: API-ul întoarce un singur sold pentru tot contul, dar contracte, facturi și contoare separate pe utilitate. Dacă soldul ar sta pe fiecare utilitate, aceeași sumă ar apărea de două ori și ar părea de plată de două ori.

**Pe dispozitivul contului** — tiparul `sensor.novaenergy_{crm}_{sufix}`:

| Senzor | Sufix entitate | Stare | Icon |
|---|---|---|---|
| Sold total | `sold_total` | sumă în RON | `mdi:cash` |
| Sold prosumator | `sold_prosumator` | sumă în RON | `mdi:solar-power` |
| Factură restantă | `factura_restanta` | `Da` / `Nu` | `mdi:file-document-alert` |
| Arhivă facturi | `arhiva_facturi` | număr de facturi în anul curent | `mdi:file-document-multiple-outline` |
| Arhivă plăți | `arhiva_plati` | număr de plăți în anul curent | `mdi:cash-check` |

**Pe dispozitivul fiecărei utilități** — tiparul `sensor.novaenergy_{crm}_{utilitate}_{sufix}`, cu utilitatea `gaz` sau `electricitate`:

| Senzor | Sufix entitate | Stare | Icon |
|---|---|---|---|
| Date contract | `date_contract` | `Activ` / `Inactiv` | `mdi:file-sign` |
| Index contor | `index_contor_{serie}` | valoarea indexului | `mdi:counter` |

Soldul, facturile și plățile stau pe cont pentru că API-ul le întoarce pe cont. Dacă ar fi filtrate pe utilitate și platforma nu marchează utilitatea pe fiecare factură, ele ar dispărea complet de pe un cont cu gaz și electricitate — iar „Factură restantă" ar spune liniștit „Nu" în timp ce ai de plată. Totalurile pe cont sunt corecte oricum; se pierde doar defalcarea.

**Senzorul de sold prosumator apare doar pe conturile care au un contract de prosumator.** Soldul de prosumator vine ca `0` și pentru cine nu e prosumator, deci semnalul adevărat e contractul, nu suma. La fel, `index_contor` apare o dată pentru fiecare contor real. Când o valoare lipsește temporar, senzorul devine `unavailable` — niciodată `0`, ca să nu strice statisticile pe termen lung.

### Atribute

**Factură restantă**

```yaml
Total restant: "223,70 lei"
Facturi neachitate: 2
Scadența ultimei facturi: "15.04.2026"
```

**Arhivă facturi**

```yaml
Emisă pe 04.03.2026: "125,50 lei"
Emisă pe 15.02.2026: "98,20 lei"
Total facturi: 2
Total facturat: "223,70 lei"
```

**Arhivă plăți**

```yaml
Plătită pe 10.03.2026: "125,50 lei"
Total plăți: 1
Total plătit: "125,50 lei"
```

**Date contract**

```yaml
Contract: "NV-12345"
Tip client: "Casnic"
Semnat la: "15.01.2024"
Intrat în vigoare: "01.02.2024"
Tip livrare: "Doar electronic"
```

**Index contor**

```yaml
Serie contor: "GS1234567"
Ultima citire: "01.03.2026"
Consum: "145,00"
```

---

## Exemple de automatizări

### Notificare la factură restantă

```yaml
automation:
  - alias: "Nova — factură restantă"
    triggers:
      - trigger: state
        entity_id: sensor.novaenergy_3047398_factura_restanta
        to: "Da"
    actions:
      - action: notify.mobile_app_telefon
        data:
          title: "Factură Nova neachitată"
          message: >
            Ai {{ state_attr('sensor.novaenergy_3047398_factura_restanta',
            'Facturi neachitate') }} factură(i) de
            {{ state_attr('sensor.novaenergy_3047398_factura_restanta',
            'Total restant') }}, scadentă la
            {{ state_attr('sensor.novaenergy_3047398_factura_restanta',
            'Scadența ultimei facturi') }}.
```

### Card pentru dashboard

```yaml
type: entities
title: Nova Power & Gas — Gaz
entities:
  - entity: sensor.novaenergy_3047398_sold_total
    name: Sold
  - entity: sensor.novaenergy_3047398_factura_restanta
    name: Factură restantă
  - entity: sensor.novaenergy_3047398_gaz_index_contor_gs1234567
    name: Index contor
  - entity: sensor.novaenergy_3047398_gaz_date_contract
    name: Contract
```

Mai multe carduri, inclusiv unul condiționat pentru alerte, în [SETUP.md](SETUP.md).

---

## Structura fișierelor

```
custom_components/novaenergy/
├── __init__.py        # pornire/oprire, runtime_data, client și coordinator per cont
├── api.py             # transport HTTP, autentificare, reînnoirea tokenului
├── config_flow.py     # configurare în doi pași + reconfigurare
├── const.py           # domeniu, adrese API, valori implicite
├── coordinator.py     # actualizare periodică per cont, cereri în paralel
├── diagnostics.py     # raport de diagnostic, cu date personale mascate
├── helpers.py         # formatare românească, parsare, normalizarea conturilor
├── sensor.py          # entitățile
├── manifest.json
├── strings.json
├── brand/             # pictograma integrării (desen propriu, nu marca furnizorului)
└── translations/
    ├── en.json
    └── ro.json
```

---

## Cerințe

- Home Assistant **2025.11** sau mai nou
- Un cont activ pe platforma Nova Power & Gas
- Nicio dependență pip suplimentară

---

## Limitări cunoscute

1. **Un singur config entry per adresă de email.** Pentru un al doilea cont Nova, folosește alt email.
2. **Doar citire în versiunea 1.x.** Trimiterea autocitirilor, convenția de consum și revizia tehnică la gaz urmează într-o versiune viitoare.
3. **Datele apar atât cât le expune API-ul.** Dacă platforma nu întoarce un anumit câmp pentru contul tău, senzorul respectiv rămâne indisponibil în loc să afișeze o valoare inventată.
4. **Contoarele sunt identificate prin serie.** Dacă furnizorul schimbă contorul, apare o entitate nouă — cea veche rămâne în istoric.
5. **Contoarele apar doar când API-ul le raportează.** Pe unele conturi lista de contoare vine goală în afara perioadei de citire; atunci senzorii de index nu se creează.

### Starea validărilor automate

`hassfest` (validatorul oficial Home Assistant) și suita de teste trec verde.
Validarea HACS trece 7 din 9 verificări: cele două rămase citesc conținutul
fișierelor prin `raw.githubusercontent.com`, fără autentificare, iar un
repository privat răspunde acolo `404`. Se rezolvă de la sine când repo-ul
devine public.

### Ce a fost verificat pe date reale

Forma răspunsurilor API a fost confirmată pe un cont adevărat: autentificarea,
contractele, soldul, punctele de măsurare și endpoint-urile fără date. Nu au putut
fi verificate pe date reale, pentru că acel cont nu le are:

- **conturile asociate** (multi-cont) — codul le tratează, dar nu a întâlnit niciunul;
- **facturile, plățile și contoarele** — numele exacte ale câmpurilor sunt o ipoteză
  informată, iar codul acceptă mai multe denumiri pentru fiecare, ca o nepotrivire să
  nu rupă senzorul.

Dacă întâlnești un senzor care rămâne gol deși platforma web arată date, un
[issue](https://github.com/alinclaudiu/novaenergy/issues) cu raportul de diagnostic
e exact ce trebuie pentru a-l corecta.

---

## Depanare

Dacă ceva nu merge, [DEBUG.md](DEBUG.md) explică pas cu pas cum activezi logurile, cum le citești și ce e normal să vezi. Întrebările frecvente sunt strânse în [FAQ.md](FAQ.md).

---

## Contribuții

Contribuțiile sunt binevenite — deschide un [issue](https://github.com/alinclaudiu/novaenergy/issues) sau trimite un pull request.

---

## Licență

[MIT](LICENSE). Folosește, modifică și redistribuie liber.

Integrarea nu este afiliată cu Nova Power & Gas și nu este un produs oficial al companiei.
