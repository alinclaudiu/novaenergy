# Întrebări frecvente — Nova Energy România

---

## Ce face, pe scurt, integrarea?

Aduce în Home Assistant datele contului tău Nova Power & Gas: soldul, facturile, plățile, contractele și indexul contoarelor. Le poți pune pe dashboard, le poți folosi în automatizări și le vezi în istoric.

---

## Trebuie să plătesc ceva? Am nevoie de o cheie?

Nu. Integrarea este gratuită, sub licență MIT, și nu conține niciun mecanism de activare. Toate entitățile sunt disponibile imediat după instalare, pentru oricine.

---

## Cum o instalez?

Prin HACS, ca repository custom, sau copiind manual folderul `custom_components/novaenergy/`. Pașii compleți sunt în [SETUP.md](SETUP.md).

---

## Am mai multe conturi Nova. Le pot vedea pe toate?

Da. Dacă ele sunt conturi asociate aceluiași cont de autentificare, integrarea le descoperă singură și te lasă să alegi pe care să le monitorizezi. Fiecare cont primește propriile dispozitive și senzori.

Dacă ai conturi de autentificare complet separate, adaugă integrarea de mai multe ori, o dată pentru fiecare adresă de email.

---

## De ce am mai multe dispozitive pentru același cont?

Pentru că integrarea creează un dispozitiv pentru cont — cu soldul, facturile și plățile — și câte unul pentru fiecare utilitate, cu contractul și contoarele ei. Un cont doar cu energie electrică are deci două dispozitive, `Nova Energy (3047398)` și `Nova Energy (3047398) Energie Electrică`; unul cu gaz și energie electrică are trei.

---

## Cât de des se actualizează datele?

Implicit la 6 ore. Poți schimba intervalul din **Configurare** (⚙️), cu minimum 5 minute.

Nu merită să cobori mult intervalul: facturile se emit lunar, iar soldul se schimbă de câteva ori pe lună. Interogările dese nu aduc informație nouă, doar trafic.

---

## Un senzor arată „indisponibil". E o eroare?

De cele mai multe ori, nu. Înseamnă că API-ul nu a întors valoarea respectivă în acest ciclu.

Integrarea preferă intenționat `unavailable` în locul lui `0`: un zero fals ar intra în statistici și ți-ar strica graficele pe termen lung. La următoarea actualizare reușită, senzorul revine singur.

---

## De ce nu am senzorul de sold prosumator?

Pentru că Nova nu raportează contul ca fiind de prosumator. Senzorul se creează doar pe conturile marcate ca prosumator de platformă (sau care au deja un sold de prosumator) — nu are rost o entitate care arată permanent „nimic".

---

## Am schimbat contorul. Ce se întâmplă?

Senzorii de index sunt identificați prin seria contorului, deci contorul nou primește entități noi, iar cele vechi rămân, cu istoricul lor, până le ștergi din interfață:

- **Index contor** apare pentru contorul nou de la prima lui citire; cel vechi păstrează ultimul index cunoscut cât timp citirea lui mai apare în istoricul Nova.
- **Index facturat** apare pentru contorul nou imediat ce acesta e în lista de contoare a locului de consum, cu un index facturat; cel vechi devine `unavailable` de îndată ce contorul dispare din listă.

---

## De unde vine indexul contorului?

Sunt doi senzori, din două surse ale aplicației Nova. **Index contor** vine din istoricul de citiri (la autocitiri) și arată indexul din cea mai recentă perioadă. **Index facturat** vine din lista de contoare a locului de consum și arată ultimul index facturat; e disponibil oricând, chiar și pentru un contor fără nicio citire în istoric. Primul urmează citirile, al doilea facturile, deci de obicei rămâne puțin în urmă. Pentru tabloul Energie folosește unul singur dintre ei.

---

## Pot trimite autocitirea prin integrare?

Nu în versiunea 1.x — deocamdată integrarea doar citește. Trimiterea autocitirilor scrie în contul tău real, așa că primește o versiune separată, gândită și testată pentru asta.

---

## De ce sumele apar cu punct și virgulă invers față de engleză?

Pentru că respectă convenția românească: punctul separă miile, virgula zecimalele. `1.234,56 lei` înseamnă o mie două sute treizeci și patru de lei și cincizeci și șase de bani.

---

## Ce înseamnă „Factură restantă: Da"?

Că există cel puțin o factură neachitată, cu sumă rămasă de plată. În atribute găsești totalul restant, câte facturi sunt și scadența celei mai îndepărtate.

---

## Arhiva de facturi îmi arată mai puține facturi decât știu că am.

Arhiva numără doar facturile din **anul curent**. O factură emisă în decembrie anul trecut nu apare în arhiva din ianuarie anul acesta.

---

## Trebuie să repornesc Home Assistant după ce schimb setările?

Nu. Modificările făcute din **Configurare** (⚙️) reîncarcă integrarea automat. Repornirea e necesară doar la instalare și la actualizarea versiunii.

---

## Trebuie să șterg și să readaug integrarea la actualizare?

Nu. Actualizezi prin HACS, repornești Home Assistant, iar entitățile și istoricul rămân neatinse. La trecerea la 1.1.0 există două excepții, pentru indexul contoarelor: un contor cu tarif dublu primește senzori noi pentru zi și noapte (`…_eaz`, `…_ean`), iar un contor fără serie primește alt identificator. Senzorul vechi rămâne atunci `unavailable` și îl poți șterge din interfață.

---

## Unde se păstrează parola mea?

În stocarea internă Home Assistant (`.storage`), ca la orice altă integrare. Nu e criptată acolo, dar nu iese din instanța ta: nu apare în loguri nici la nivel de debug, nu apare în raportul de diagnostic și nu pleacă nicăieri în afară de serverele Nova.

---

## Pot trimite raportul de diagnostic într-un issue public?

Da, cu o mică pregătire. Raportul maschează adresa de email și nu conține parola, tokenul sau valorile din răspunsurile API: doar starea conturilor, câte facturi, plăți, contracte, puncte de consum, contoare și citiri există și lista de senzori — exact ce trebuie pentru diagnosticare. Conține însă numărul contului (codul CRM), iar numele senzorilor de index conțin seria contorului; înlocuiește-le înainte de a-l publica, dacă nu vrei să fie vizibile.

---

## Integrarea e oficială, de la Nova?

Nu. Este un proiect independent, scris de la zero, fără nicio legătură cu compania. Folosește aceleași endpoint-uri ca aplicația web de client.

---

## Ceva nu merge. Ce fac?

Începe cu [DEBUG.md](DEBUG.md): explică cum activezi logurile detaliate, ce înseamnă mesajele și ce e normal să vezi. Dacă tot nu se lămurește, deschide un [issue](https://github.com/alinclaudiu/novaenergy/issues) cu logurile și raportul de diagnostic.
