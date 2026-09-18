# Ghid de instalare și configurare — Nova Energy România

Ghidul acoperă instalarea, configurarea, exemple de carduri și verificarea că totul funcționează.

---

## Cerințe preliminare

- Home Assistant **2025.11** sau mai nou
- Un cont activ pe platforma Nova Power & Gas („Vreau la Nova"), cu email și parolă
- Opțional: [HACS](https://hacs.xyz/), pentru instalare și actualizări mai ușoare

---

## Metoda 1 — instalare prin HACS (recomandat)

### Pasul 1 — adaugă repository-ul

1. **HACS** → meniul ⋮ din dreapta sus → **Custom repositories**
2. La **Repository** pune `https://github.com/alinclaudiu/novaenergy`
3. La **Category** alege **Integration**
4. **Add**

### Pasul 2 — instalează

1. Caută „**Nova Energy România**" în lista HACS
2. **Download** → confirmă versiunea

### Pasul 3 — repornește

**Setări** → **Sistem** → **Repornește**. Integrarea devine vizibilă abia după repornire.

---

## Metoda 2 — instalare manuală

### Pasul 1 — descarcă

Ia ultima versiune din [pagina de release-uri](https://github.com/alinclaudiu/novaenergy/releases) sau clonează repo-ul.

### Pasul 2 — copiază

Copiază folderul `custom_components/novaenergy/` în directorul de configurare:

```
config/
└── custom_components/
    └── novaenergy/
        ├── __init__.py
        ├── api.py
        ├── config_flow.py
        ├── const.py
        ├── coordinator.py
        ├── diagnostics.py
        ├── helpers.py
        ├── manifest.json
        ├── sensor.py
        ├── strings.json
        └── translations/
```

Prin SSH sau Samba:

```bash
cd /config/custom_components
git clone https://github.com/alinclaudiu/novaenergy.git temp
mv temp/custom_components/novaenergy .
rm -rf temp
```

### Pasul 3 — repornește

---

## Configurare inițială

### Pasul 1 — adaugă integrarea

**Setări** → **Dispozitive și Servicii** → **+ Adaugă Integrare** → caută „**Nova Energy**".

### Pasul 2 — completează credențialele

| Câmp | Ce pui | Observații |
|---|---|---|
| **Email** | adresa contului Nova | aceeași cu cea de pe platforma web |
| **Parolă** | parola contului | se salvează criptat de Home Assistant |
| **Interval actualizare** | secunde | implicit `21600` (6 ore); minim acceptat `300` |

> Datele de facturare se schimbă de câteva ori pe lună. Un interval sub o oră nu aduce informație nouă, doar trafic inutil către serverele Nova.

Erorile posibile:

| Mesaj | Ce înseamnă |
|---|---|
| „Email sau parolă greșită" | credențialele nu au fost acceptate; verifică-le pe platforma web |
| „Serverele Nova nu răspund" | problemă de rețea sau platformă indisponibilă; încearcă mai târziu |
| „Acest cont nu are contracte de monitorizat" | autentificarea a reușit, dar contul nu expune niciun cont de client |
| „Acest cont Nova este deja configurat" | ai deja un config entry cu acest email |

### Pasul 3 — alege conturile

Fiecare cont descoperit apare cu adresa și codul CRM. Bifează ce te interesează sau folosește **Selectează toate conturile**. Trebuie ales cel puțin unul.

### Pasul 4 — confirmă

După confirmare apar device-urile, câte unul pentru fiecare cont × utilitate, cu senzorii dedesubt.

---

## Reconfigurare, fără reinstalare

1. **Setări** → **Dispozitive și Servicii** → **Nova Energy România**
2. **Configurare** (⚙️)
3. Modifică intervalul sau conturile monitorizate
4. **Trimite**

Integrarea se reîncarcă automat. Entitățile existente își păstrează istoricul.

---

## Referință rapidă — entity ID-uri

Soldul aparține contului, restul aparțin utilității:

```
sensor.novaenergy_3047398_sold_total
sensor.novaenergy_3047398_sold_prosumator            # doar dacă ai contract de prosumator
sensor.novaenergy_3047398_factura_restanta
sensor.novaenergy_3047398_arhiva_facturi
sensor.novaenergy_3047398_arhiva_plati
```

Restul urmează tiparul `sensor.novaenergy_{crm}_{utilitate}_{sufix}`, cu utilitatea `gaz` sau `electricitate`. Pentru contul `3047398`, pe gaz:

```
sensor.novaenergy_3047398_gaz_date_contract
sensor.novaenergy_3047398_gaz_index_contor_gs1234567
```

Pe electricitate, același tipar cu `electricitate` în loc de `gaz`.

> Codurile CRM și seriile de contor de mai sus sunt exemple. Ale tale se văd în **Instrumente pentru dezvoltatori** → **Stări**, filtrând după `novaenergy`.

---

## Exemple de carduri Lovelace

### Card general

```yaml
type: entities
title: Nova Power & Gas
entities:
  - entity: sensor.novaenergy_3047398_sold_total
    name: Sold
  - entity: sensor.novaenergy_3047398_factura_restanta
    name: Factură restantă
  - entity: sensor.novaenergy_3047398_gaz_date_contract
    name: Contract
  - entity: sensor.novaenergy_3047398_gaz_index_contor_gs1234567
    name: Index contor
```

### Card cu soldul ca valoare mare

```yaml
type: gauge
entity: sensor.novaenergy_3047398_sold_total
name: Sold de plată
unit: lei
severity:
  green: 0
  yellow: 100
  red: 300
```

### Card condiționat — alertă doar când ai restanțe

```yaml
type: conditional
conditions:
  - condition: state
    entity: sensor.novaenergy_3047398_factura_restanta
    state: "Da"
card:
  type: markdown
  content: >
    ## ⚠️ Factură neachitată

    **{{ state_attr('sensor.novaenergy_3047398_factura_restanta', 'Total restant') }}**
    de plată, scadentă la
    **{{ state_attr('sensor.novaenergy_3047398_factura_restanta', 'Scadența ultimei facturi') }}**.
```

### Card cu arhiva facturilor

```yaml
type: markdown
content: >
  ## Facturi în {{ now().year }}

  {% set s = 'sensor.novaenergy_3047398_arhiva_facturi' %}
  {% for cheie, valoare in states[s].attributes.items() %}
  {% if cheie.startswith('Emisă') %}
  - {{ cheie }}: **{{ valoare }}**
  {% endif %}
  {% endfor %}

  **Total:** {{ state_attr(s, 'Total facturat') }}
```

### Card pentru mai multe conturi

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Cont 3047398 — Gaz
    entities:
      - sensor.novaenergy_3047398_sold_total
      - sensor.novaenergy_3047398_factura_restanta
  - type: entities
    title: Cont 3008726 — Gaz
    entities:
      - sensor.novaenergy_3008726_sold_total
      - sensor.novaenergy_3008726_factura_restanta
```

---

## Verificare după instalare

### Device-urile există

**Setări** → **Dispozitive și Servicii** → **Nova Energy România** → **dispozitive**. Ar trebui să vezi câte un dispozitiv pentru fiecare cont × utilitate.

### Senzorii au valori

**Instrumente pentru dezvoltatori** → **Stări**, filtru `novaenergy`. Compară soldul și facturile cu ce arată platforma web.

### Logurile sunt curate

**Setări** → **Sistem** → **Jurnale**. La pornire ar trebui să apară o singură linie informativă:

```
Nova Energy pornită pentru 2 cont(uri): 3008726, 3047398
```

Dacă ceva nu e în regulă, continuă cu [DEBUG.md](DEBUG.md).

---

## Dezinstalare

### Prin HACS

1. **Setări** → **Dispozitive și Servicii** → **Nova Energy România** → ⋮ → **Șterge**
2. **HACS** → Nova Energy România → ⋮ → **Remove**
3. Repornește

### Manual

1. Șterge integrarea din interfață
2. Șterge folderul `config/custom_components/novaenergy/`
3. Repornește

---

## Observații generale

- Parola se păstrează criptat, în stocarea internă Home Assistant, și nu apare niciodată în loguri.
- Raportul de diagnostic (butonul **Descarcă diagnostic** de pe pagina integrării) maschează adresa de email și nu conține parola sau tokenul — poate fi atașat în siguranță la un issue.
- Integrarea nu trimite date către niciun serviciu în afară de Nova.
